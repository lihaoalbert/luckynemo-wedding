"""mp_worker：小程序生成任务执行器（常驻 ECS）。

轮询 mp_jobs 队列，执行 free_photo / paid_photo 任务：
取订单上传的照片（uploads 表 → OSS）→ Seedream 以选装（套装+场景）生成婚纱照
→ 结果写回 OSS results/ 前缀 → job 标记 done 并附签名 URL。

依赖：requests + PyYAML（luckynemo-toolkit 已在 /opt/luckynemo/toolkit，复用其 .env 的 ARK key）
运行：python3 mp_worker.py（建议 systemd luckynemo-worker.service）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

import db_compat

SERVER_DIR = Path(__file__).resolve().parent
DB_PATH = SERVER_DIR / "data" / "app.db"
TOOLKIT_ENV = Path("/opt/luckynemo/toolkit/.env")
POLL_INTERVAL = 5
TMP = Path("/tmp/mp_worker")
TMP.mkdir(exist_ok=True)


def _load_env() -> dict:
    env = {}
    for f in (SERVER_DIR / ".env", TOOLKIT_ENV):
        if f.is_file():
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = _load_env()
SEEDREAM_MODEL = ENV.get("SEEDREAM_MODEL", "doubao-seedream-5-0-pro-260628")
VIDU_KEY = ENV.get("VIDU_API_KEY", "")
MINIMAX_KEY = ENV.get("MINIMAX_API_KEY", "")
MINIMAX_BASE = ENV.get("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")
OSS_AK = ENV.get("OSS_ACCESS_KEY_ID", "")
OSS_SK = ENV.get("OSS_ACCESS_KEY_SECRET", "")
OSS_BUCKET = ENV.get("OSS_BUCKET", "ibi-private")
OSS_ENDPOINT = f"https://{OSS_BUCKET}.{ENV.get('OSS_REGION', 'oss-cn-shanghai')}.aliyuncs.com"
#: 微信订阅消息（生成完成推送）：MP 后台模板 73339「内容生成成功通知」
MP_APPID = ENV.get("MP_APPID", "")
MP_SECRET = ENV.get("MP_SECRET", "")
MP_SUB_TMPL = ENV.get("MP_SUB_TMPL", "IlIzXgigktofL--1YSNksEv_3snoOCS8Vhc-_Co67xs")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def db() -> sqlite3.Connection:
    """数据库连接：默认 SQLite；DB_BACKEND=mysql 时走 RDS（db_compat 双后端，2026-08-11）。"""
    if ENV.get("DB_BACKEND") == "mysql":
        return db_compat.connect_mysql(
            host=ENV.get("MYSQL_HOST", ""), user=ENV.get("MYSQL_USER", ""),
            password=ENV.get("MYSQL_PASSWORD", ""), database=ENV.get("MYSQL_NAME", "lucky_nemo"),
            port=int(ENV.get("MYSQL_PORT", "3306")))
    return sqlite3.connect(DB_PATH)


# ---------------- OSS ----------------
def oss_sign(secret: str, s: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), s.encode(), hashlib.sha1).digest()).decode()


def oss_get(key: str, dest: Path) -> Path:
    expires = str(int(time.time()) + 600)
    resource = f"/{OSS_BUCKET}/{key}"
    sign = oss_sign(OSS_SK, f"GET\n\n\n{expires}\n{resource}")
    url = (f"{OSS_ENDPOINT}/{quote(key)}?Expires={expires}"
           f"&OSSAccessKeyId={OSS_AK}&Signature={quote(sign, safe='')}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


def oss_put_url(key: str, data: bytes, content_type: str, expire: int = 7 * 86400) -> str:
    import email.utils
    date = email.utils.formatdate(usegmt=True)
    resource = f"/{OSS_BUCKET}/{key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    headers = {"Date": date, "Content-Type": content_type,
               "Authorization": f"OSS {OSS_AK}:{oss_sign(OSS_SK, string_to_sign)}"}
    r = requests.put(f"{OSS_ENDPOINT}/{quote(key)}", data=data, headers=headers, timeout=120)
    r.raise_for_status()
    expires = str(int(time.time()) + expire)
    sign = oss_sign(OSS_SK, f"GET\n\n\n{expires}\n{resource}")
    return f"{OSS_ENDPOINT}/{quote(key)}?Expires={expires}&OSSAccessKeyId={OSS_AK}&Signature={quote(sign, safe='')}"


# ---------------- Ark / Seedream ----------------
#: 生图双通道：「iFocusing 路由」(ifocus，默认) + 「火山直连」(direct，备用)。
#: 一侧欠费/限流/异常时自动 failover 另一侧；ARK_CHANNEL 环境变量可强制指定主通道
ARK_CHANNELS = {
    "ifocus": ("https://router.i-focusing.com", "IFOCUS_API_KEY"),
    "direct": ("https://ark.cn-beijing.volces.com", "ARK_API_KEY"),
}


def _ark_channels() -> list:
    """按主备顺序返回 [(通道名, base, key)]，只保留配了 key 的通道。"""
    primary = ENV.get("ARK_CHANNEL", "ifocus")
    names = [primary] + [n for n in ARK_CHANNELS if n != primary]
    return [(n, ARK_CHANNELS[n][0], ENV.get(ARK_CHANNELS[n][1], ""))
            for n in names if ENV.get(ARK_CHANNELS[n][1], "")]


def seedream(prompt: str, ref_files: list[Path], size: str = "2K") -> bytes:
    imgs = []
    for p in ref_files:
        b64 = base64.b64encode(p.read_bytes()).decode()
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        imgs.append(f"data:{mime};base64,{b64}")
    payload = {"model": SEEDREAM_MODEL, "prompt": prompt, "size": size,
               "watermark": False, "response_format": "url",
               "negative_prompt": "纸张，书本，文件，杂物，垃圾，多余人物，多余肢体，悬空物体，"
                                  "文字，水印，logo，畸形手，面部畸变"}
    if imgs:
        payload["image"] = imgs
    channels = _ark_channels()
    if not channels:
        raise RuntimeError("生图通道未配置（IFOCUS_API_KEY / ARK_API_KEY 均缺失）")
    last_err = None
    for i, (name, base, key) in enumerate(channels):
        try:
            r = requests.post(f"{base}/api/v3/images/generations", json=payload,
                              headers={"Authorization": f"Bearer {key}"}, timeout=300)
            data = r.json()
            if r.status_code >= 300 or "error" in data:
                raise RuntimeError(json.dumps(data.get("error", data), ensure_ascii=False)[:300])
            if i > 0:
                log(f"Seedream 主通道失败，已由备用通道 {name} 完成")
            url = data["data"][0]["url"]
            return requests.get(url, timeout=120).content
        except Exception as e:  # noqa: BLE001
            last_err = e
            log(f"Seedream 通道 {name} 失败：{str(e)[:200]}")
    raise RuntimeError(f"Seedream 全部通道失败：{str(last_err)[:300]}")


# ---------------- 面部分析（LLM 化妆师建议） ----------------
def analyze_face(photo: Path, makeup_name: str, gender: str = "female") -> str:
    """多模态 LLM 分析人物原图，针对所选妆造给出个性化上妆建议（≤120字）。"""
    if not MINIMAX_KEY:
        return ""
    ta = "他" if gender == "male" else "她"
    b64 = base64.b64encode(photo.read_bytes()).decode()
    mime = "image/jpeg" if photo.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    try:
        r = requests.post(
            f"{MINIMAX_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {MINIMAX_KEY}"},
            json={"model": "abab6.5s-chat", "max_tokens": 250, "temperature": 0.4,
                  "messages": [{"role": "user", "content": [
                      {"type": "text", "text": (
                          f"你是资深化妆师。观察这张脸：脸型、肤色、肤质、五官比例、需要扬长避短的地方。"
                          f"针对「{makeup_name}」这款妆容，给出 3-4 条适合{ta}的具体上妆建议"
                          "（如眉形走向、眼影范围、腮红位置与浓淡、唇色选择、修容取舍）。"
                          "只输出建议本身，简洁专业，不超过120字。")},
                      {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]},
            timeout=60,
        )
        advice = r.json()["choices"][0]["message"]["content"].strip()
        log(f"面部分析建议：{advice[:60]}...")
        return advice
    except Exception as e:
        log(f"面部分析失败（跳过）：{e}")
        return ""


def merge_face_advice(prompt: str, advice: str, notes: str = "") -> str:
    """把 LLM 化妆建议 + 用户自定义意见融合进标准提示词。"""
    if advice:
        prompt += f"\n结合人物面部特征的个性化上妆建议（务必采纳）：{advice}"
    if notes:
        prompt += f"\n用户特别要求（优先级最高）：{notes}"
    return prompt


# ---------------- 定制模卡（VLM 审核/规格化/质检） ----------------
def vlm_json(text: str, images: list[Path], max_tokens: int = 700) -> dict:
    """多模态 LLM 调用，期望返回 JSON（容错解析）。用于定制模卡的审核、规格化与质检。"""
    if not MINIMAX_KEY:
        raise RuntimeError("未配置 MINIMAX_API_KEY，无法做定制模卡审核")
    content = [{"type": "text", "text": text}]
    for p in images:
        b64 = base64.b64encode(p.read_bytes()).decode()
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    r = requests.post(
        f"{MINIMAX_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {MINIMAX_KEY}"},
        json={"model": "abab6.5s-chat", "max_tokens": max_tokens, "temperature": 0.3,
              "messages": [{"role": "user", "content": content}]},
        timeout=90,
    )
    out = r.json()["choices"][0]["message"]["content"].strip()
    out = re.sub(r"```(?:json)?", "", out).strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # 兜底：raw_decode 只取第一个完整 JSON 对象，忽略其后多余内容
        #（旧实现用贪心正则 \{[\s\S]*\}，LLM 输出多段花括号内容时必炸 "Extra data"，反馈 #35）
        start = out.find("{")
        if start >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(out[start:])
                if isinstance(obj, dict):
                    return obj
            except json.JSONDecodeError:
                pass
        raise RuntimeError(f"VLM 返回非 JSON：{out[:120]}")


#: 定制模卡固定画质尾缀（与模卡库 gen_variants.py 同一骨架，保证质量下限）
MOKA_PROMPT_TAIL = ("竖版构图，真实人体比例约7.5头身，人物与地面有自然接触和投影，"
                    "摄影级质感，无文字无水印，人物为虚拟模特面孔，"
                    "不出现任何真实名人面孔和证件文书")


def run_custom_moka(job_id: int, order_no: str, payload: dict) -> None:
    """定制模卡：VLM 安全审核+意图规格化 → Seedream 生成 → VLM 质检（≤2 次重试）→ 存 diy_moka/。
    范例图有人脸时只给 VLM 取风格、不进 Seedream 参考图（避免复刻真人肖像）。"""
    description = str(payload.get("description") or "").strip()
    example = None
    keys = payload.get("example_keys") or []
    if keys:
        try:
            example = oss_get(keys[0], TMP / f"{order_no}_diy_ref.jpg")
        except Exception as e:
            log(f"job#{job_id} 范例图下载失败，按纯文字定制：{e}")
    if not description and not example:
        raise RuntimeError("定制模卡需要文字描述或范例图")
    mode = payload.get("mode") or "couple"
    people = {"couple": "一对年轻情侣（一男一女）",
              "solo_f": "一位年轻女性", "solo_m": "一位年轻男性"}.get(mode, "一对年轻情侣（一男一女）")
    # 第 1 步：内容安全 + 意图规格化
    spec = vlm_json(
        "你是婚纱摄影模板定制师。根据用户描述" + ("和范例图" if example else "") + "完成两件事：\n"
        f"【用户描述】{description or '（没有文字，只参考范例图）'}\n"
        "1. 安全审核：涉及色情裸露、政治敏感、真实名人、证件文书、复刻真实人物肖像 → safe=false 并给出 reason；\n"
        "2. 规格化：把需求改写成一段完整的中文摄影绘图提示词 prompt（场景/服装/姿势/神态/光影/色调/构图），"
        f"画面中的人物必须是：{people}。范例图里若有人物，只提取风格元素，绝不描述其长相。"
        "prompt 不要包含画幅/画质/水印类要求（我会另加）。\n"
        '只输出 JSON：{"safe": true或false, "reason": "不安全时的一句话原因", '
        '"has_face": 范例图是否含清晰人脸true或false, "prompt": "绘图提示词"}',
        [example] if example else [])
    if not spec.get("safe"):
        raise RuntimeError("定制内容未通过安全审核：" + str(spec.get("reason") or "不符合内容规范"))
    prompt = str(spec.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("没能理解你的定制需求，换个说法再试试")
    prompt_full = prompt + "，" + MOKA_PROMPT_TAIL
    refs = [example] if (example and spec.get("has_face") is False) else []
    log(f"job#{job_id} custom_moka 规格：{prompt[:60]}... 参考图 {len(refs)} 张")
    # 第 2 步：生成 + VLM 质检（人数性别/畸形/文字/与需求一致性），不通过最多重试 2 次
    last_issue = ""
    result = None
    for attempt in range(1, 4):
        p = prompt_full + (f"\n上一版问题（必须避免）：{last_issue}" if last_issue else "")
        result = seedream(p, refs)
        gen_file = TMP / f"{order_no}_diy_gen.jpg"
        gen_file.write_bytes(result)
        qc = vlm_json(
            f"质检这张婚纱摄影模板图。要求：画面中必须是{people}；五官手部无畸形；无清晰可读文字/水印。"
            f"用户需求是「{description or prompt[:80]}」。"
            '只输出 JSON：{"pass": true或false, "issue": "不通过的一句话原因（通过则留空）"}',
            [gen_file], max_tokens=200)
        if qc.get("pass"):
            log(f"job#{job_id} custom_moka 质检通过（第 {attempt} 次）")
            break
        last_issue = str(qc.get("issue") or "质量不达标")[:100]
        log(f"job#{job_id} custom_moka 质检未过（第 {attempt} 次）：{last_issue}")
    else:
        raise RuntimeError(f"定制模卡连续 3 次未过质检（{last_issue}），换个描述再试试")
    key = f"diy_moka/{order_no}/{uuid.uuid4().hex[:8]}.jpg"
    url = oss_put_url(key, result, "image/jpeg")
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"url": url, "oss_key": key, "mode": mode,
                              "description": description, "prompt": prompt}, ensure_ascii=False), job_id))
    conn.execute("UPDATE mp_orders SET status='done', updated_at=datetime('now') WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()
    log(f"job#{job_id} custom_moka 完成 -> {key}")


def seedream_qc(prompt: str, refs: list[Path], expect_people: str, job_id: int, tag: str,
                max_attempts: int = 2) -> bytes:
    """生成 + VLM 质检兜底（2026-08-07 P1：从 custom_moka 推广到 template/duo/series）。

    质检项：人数与预期一致 / 五官手部无畸形 / 无清晰可读文字水印 / 五官与参考图真实人物一致。
    不通过带问题重试；最终不通过也交付最后一版（避免用户长时间等待后空手），日志留痕。
    VLM 未配置时静默退化为直出（不挡主流程）。
    """
    if not MINIMAX_KEY:
        return seedream(prompt, refs)
    last_issue = ""
    result = b""
    for attempt in range(1, max_attempts + 1):
        p = prompt + (f"\n上一版问题（必须避免）：{last_issue}" if last_issue else "")
        result = seedream(p, refs)
        gen_file = TMP / f"qc_{job_id}_{re.sub(r'[^A-Za-z0-9]', '_', tag)}_{attempt}.jpg"
        gen_file.write_bytes(result)
        try:
            qc = vlm_json(
                f"质检这张生成照片。要求：画面中必须是{expect_people}；五官手部无畸形；"
                "无清晰可读文字/水印；人物五官与其余参考图里的真实人物是同一人（明显不像 = 不通过）。"
                '只输出 JSON：{"pass": true或false, "issue": "不通过的一句话原因（通过则留空）"}',
                [gen_file] + list(refs[:2]), max_tokens=200)
        except Exception as e:
            log(f"job#{job_id} {tag} 质检调用失败，直接交付：{e}")
            return result
        if qc.get("pass"):
            if attempt > 1:
                log(f"job#{job_id} {tag} 质检第 {attempt} 次通过")
            return result
        last_issue = str(qc.get("issue") or "质量不达标")[:100]
        log(f"job#{job_id} {tag} 质检未过（第 {attempt}/{max_attempts} 次）：{last_issue}")
    log(f"job#{job_id} {tag} 质检 {max_attempts} 次未过，交付最后一版（{last_issue}）")
    return result


def run_template_series(job_id: int, order_no: str, payload: dict) -> None:
    """系列整组生成（九宫格）：同一锚点对系列全部变体逐张换人，进度实时写进 result_json.urls。"""
    moka_path = SITE_DIR / "moka" / "index.json"
    if not moka_path.is_file():
        raise RuntimeError("模卡库缺失")
    moka_data = json.loads(moka_path.read_text(encoding="utf-8"))
    series_id = payload.get("series_id", "")
    series = next((s for s in moka_data.get("series", []) if s.get("id") == series_id), None)
    if not series:
        raise RuntimeError(f"模卡系列不存在 {series_id}")
    tpl_map = {t["id"]: t for t in moka_data.get("templates", [])}
    # variant_ids（选片子集，v4）：只生成选中的变体；缺省=整组
    want = set(payload.get("variant_ids") or [])
    variant_ids = [v for v in series.get("variants", [])
                   if v in tpl_map and (not want or v in want)]
    if not variant_ids:
        raise RuntimeError(f"系列 {series_id} 没有可用模板")
    # 锚点规则与 template_photo 一致：定妆照优先，缺省回退原始上传照片
    _check_anchor_pair(payload)
    photos = []
    if payload.get("anchor_key"):
        photos.append(oss_get(payload["anchor_key"], TMP / f"{order_no}_anchor.jpg"))
    else:
        photos += order_photos(order_no, "A", limit=1)
    has_b = False
    if payload.get("anchor_key_b"):
        photos.append(oss_get(payload["anchor_key_b"], TMP / f"{order_no}_anchor_b.jpg"))
        has_b = True
    elif payload.get("mode") == "couple":
        b_photos = order_photos(order_no, "B", limit=1)
        photos += b_photos
        has_b = bool(b_photos)
    if not photos:
        raise RuntimeError("请先上传本人照片，再做一键同款")
    if payload.get("mode") == "couple" and not has_b:
        raise RuntimeError("情侣模板需要另一方也上传照片（协同创作邀请 TA，或在对话里发 TA 的照片）")
    # 人脸三视图注入（反馈 #26 侧脸不像）：A/B 各自有三视图就带上
    face_refs = _face_sheet_refs(order_no, ["A", "B"] if payload.get("mode") == "couple" else ["A"])
    photos += face_refs
    prompt = (
        "最后一张参考图是完整的摄影作品模板，前面的参考图是要替换上去的人物。"
        "把模板中的人物替换为参考图的人物（多人时按性别一一对应替换），"
        "严格保持模板的构图、场景、服装、妆容、道具、神态、光影、色调、背景完全不变，"
        "只替换人物的五官与面部特征，人物的发型与发色始终保持本人参考图的样式"
        "（不采用模板人物的发型），真实人体比例约7.5头身，与场景自然融合有投影，"
        "摄影级质感，无文字无水印"
    )
    if face_refs:
        prompt += "。" + FACE_SHEET_ANCHOR
    heights = _order_heights(order_no)
    if heights and payload.get("mode") == "couple":
        prompt += f"。两人真实身高：{heights}，严格还原身高差与各自体型"
    total = len(variant_ids)
    urls = []
    for i, tid in enumerate(variant_ids, 1):
        tpl = SITE_DIR / "moka" / tpl_map[tid]["file"]
        if not tpl.is_file():
            log(f"job#{job_id} template_series 模板缺失 {tid}，跳过")
            continue
        log(f"job#{job_id} template_series {series_id} 第 {i}/{total} 张 {tid}")
        expect = "一男一女（情侣）" if payload.get("mode") == "couple" else "一位人物（与参考图同人）"
        img = seedream_qc(prompt, photos + [tpl], expect, job_id, f"series_{tid}")
        # 裁脸换脸终案：photos 前 1-2 张为人物锚点（A/B），作换脸身份参考的一部分
        img = face_swap_restore(order_no, img, job_id, f"series_{tid}",
                                anchor_files=photos[:2] if has_b else photos[:1])
        key = f"results/{order_no}/{uuid.uuid4().hex[:8]}.jpg"
        url = oss_put_url(key, img, "image/jpeg")
        urls.append({"id": tid, "url": url, "oss_key": key})
        conn = db()
        conn.execute("UPDATE mp_jobs SET result_json=?, updated_at=datetime('now') WHERE id=?",
                     (json.dumps({"urls": urls, "total": total, "series_id": series_id},
                                 ensure_ascii=False), job_id))
        conn.commit()
        conn.close()
    if not urls:
        raise RuntimeError(f"系列 {series_id} 模板全部缺失")
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"urls": urls, "total": total, "series_id": series_id},
                             ensure_ascii=False), job_id))
    conn.execute("UPDATE mp_orders SET status='done', updated_at=datetime('now') WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()
    _maybe_ref_reward(order_no)
    notify_photo_done(order_no, "template_series", len(urls))
    log(f"job#{job_id} template_series 完成 {series_id} 共 {len(urls)} 张")


def _latest_face_sheet(order_no: str, role: str) -> Path | None:
    """取成员最新一张人脸三视图（face_sheet 任务产物），没有返回 None。"""
    conn = db()
    rows = conn.execute(
        "SELECT payload_json, result_json FROM mp_jobs"
        " WHERE order_no=? AND kind='face_sheet' AND status='done' ORDER BY id DESC LIMIT 5",
        (order_no,)).fetchall()
    conn.close()
    for pj, rj in rows:
        payload = json.loads(pj) if pj else {}
        result = json.loads(rj) if rj else {}
        if payload.get("role", "A") != role:
            continue
        key = result.get("oss_key")
        if key:
            try:
                return oss_get(key, TMP / f"{order_no}_{role}_facesheet.jpg")
            except Exception as e:
                log(f"人脸三视图下载失败 {key}: {e}")
    return None


def _order_heights(order_no: str) -> str:
    """读订单 selection 里的身高信息（chat set_heights 收集，反馈 #27）。"""
    conn = db()
    row = conn.execute("SELECT selection_json FROM mp_orders WHERE order_no=?", (order_no,)).fetchone()
    conn.close()
    sel = json.loads(row[0]) if row and row[0] else {}
    return str(sel.get("heights") or "")


def _template_ref_for_result(order_no: str, base_key: str) -> Path | None:
    """回溯成片对应的模卡模板图（反馈 #47：修图意见引用模板时作参考图传入）。
    template_photo 按 payload.template_id / custom_template_key；template_series 按
    result.urls 里与 base_key 匹配的变体 id。查不到或加载失败返回 None（不挡修图）。"""
    conn = db()
    rows = conn.execute(
        "SELECT kind, payload_json, result_json FROM mp_jobs"
        " WHERE order_no=? AND status='done' AND kind IN ('template_photo','template_series')"
        " ORDER BY id DESC LIMIT 20", (order_no,)).fetchall()
    conn.close()
    tpl_id, custom_key = "", ""
    for jkind, pj, rj in rows:
        payload = json.loads(pj) if pj else {}
        result = json.loads(rj) if rj else {}
        if jkind == "template_photo" and result.get("oss_key") == base_key:
            tpl_id = payload.get("template_id", "")
            custom_key = payload.get("custom_template_key", "")
            break
        if jkind == "template_series":
            hit = next((u for u in result.get("urls") or []
                        if isinstance(u, dict) and u.get("oss_key") == base_key), None)
            if hit:
                tpl_id = hit.get("id", "")
                break
    try:
        if tpl_id:
            moka_path = SITE_DIR / "moka" / "index.json"
            moka_data = json.loads(moka_path.read_text(encoding="utf-8"))
            tpl_map = {t["id"]: t for t in moka_data.get("templates", [])}
            t = tpl_map.get(tpl_id)
            if t:
                f = SITE_DIR / "moka" / t["file"]
                if f.is_file():
                    return f
        if custom_key:
            return oss_get(custom_key, TMP / f"{order_no}_edit_tpl.jpg")
    except Exception as e:
        log(f"修图模板回溯失败 {order_no} {base_key}: {e}")
    return None


def _face_sheet_refs(order_no: str, roles: list[str]) -> list[Path]:
    """收集各成员的人脸三视图（存在的才给）。"""
    refs = []
    for role in roles:
        f = _latest_face_sheet(order_no, role)
        if f:
            refs.append(f)
    return refs


def _check_anchor_pair(payload: dict) -> None:
    """情侣任务锚点校验：A/B 锚点绝不能是同一张图（反馈 #50 根因之一——
    前端锚点错配曾把男方定妆照贴给新娘，新娘脸直接错）。发现即拒绝，不浪费额度。"""
    a, b = payload.get("anchor_key"), payload.get("anchor_key_b")
    if a and b and a == b:
        raise RuntimeError("两个出镜人选了同一张定妆照，请回上一步重新选择各自的定妆照")


def face_restore(order_no: str, gen: bytes, job_id: int, tag: str) -> bytes:
    """【兜底通道】整图面部还原：脸部只占百余像素时模型往"标准美人脸"漂，效果弱于
    face_swap_restore（裁脸换脸），仅在 OpenCV/YuNet 不可用时降级使用。
    失败/无身份参考时静默返回原图（不挡交付）。"""
    identity = _identity_refs(order_no)
    if not identity:
        log(f"job#{job_id} {tag} 无身份参考，跳过面部还原")
        return gen
    gen_file = TMP / f"{order_no}_facefix_{re.sub(r'[^A-Za-z0-9]', '_', tag)}.jpg"
    gen_file.write_bytes(gen)
    prompt = ("这是对图1照片的面部还原修图，不是重新生成：只重绘图1中人物的脸部五官与脸型，"
              "使其与后附本人参考照片的长相高度一致——后附参考图是人物的本人真实照片，是长相的唯一权威，"
              "宁可不那么好看也必须像本人，严禁美化成标准模板脸。"
              "严格保持图1的构图、场景、服装、发型、光影、色调、姿势与其余一切完全不变，"
              "修图痕迹自然无破绽，摄影级质感，无文字无水印")
    try:
        out = seedream(prompt, [gen_file] + identity)
        log(f"job#{job_id} {tag} 面部还原完成（身份参考 {len(identity)} 张）")
        return out
    except Exception as e:
        log(f"job#{job_id} {tag} 面部还原失败，交付一遍图：{str(e)[:200]}")
        return gen


# ---------------- 裁脸换脸贴回（2026-08-23 定稿，F5 终案实验验证） ----------------
#: OpenCV YuNet 人脸检测模型（232KB，Apache-2.0，vendor 进库）
YUNET_MODEL = SERVER_DIR / "models" / "face_detection_yunet_2023mar.onnx"


def _yunet_detect(cv2, img):
    """检出全部人脸 [(box, 5关键点)]，按面积从大到小。box=(x,y,w,h)。"""
    det = cv2.FaceDetectorYN.create(str(YUNET_MODEL), "", (img.shape[1], img.shape[0]), 0.5)
    _, faces = det.detect(img)
    if faces is None:
        return []
    out = [(f[:4], f[4:14].reshape(5, 2).astype("float32")) for f in faces]
    return sorted(out, key=lambda f: f[0][2] * f[0][3], reverse=True)


def _face_mask(cv2, np, shape, box, feather=14):
    """按人脸框生成竖椭圆羽化 mask：盖住脸与下颌，不吃头发与背景。"""
    x, y, w, h = box
    mask = np.zeros(shape[:2], np.uint8)
    cv2.ellipse(mask, (int(x + w / 2), int(y + h * 0.62)),
                (int(w * 0.62), int(h * 0.78)), 0, 0, 360, 255, -1)
    return (cv2.GaussianBlur(mask, (0, 0), feather).astype("float32") / 255.0)[..., None]


def _paste_swapped_face(cv2, np, base_img, box, swap_path: Path) -> None:
    """把换脸 crop 按关键点相似变换对齐贴回 base_img 的 box 区域（就地修改）。"""
    x0, y0, x1, y1 = box
    crop = base_img[y0:y1, x0:x1].copy()
    swap = cv2.imread(str(swap_path))
    if swap is None:
        raise RuntimeError(f"换脸结果读取失败 {swap_path}")
    box_c, pts_c = _yunet_detect(cv2, crop)[0]
    _, pts_s = _yunet_detect(cv2, swap)[0]
    M, _ = cv2.estimateAffinePartial2D(pts_s, pts_c, method=cv2.LMEDS)
    if M is None:
        raise RuntimeError("关键点对齐失败")
    warped = cv2.warpAffine(swap, M, (crop.shape[1], crop.shape[0]),
                            flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
    # 颜色匹配：脸部区域均值/方差对齐原图光照，消除换脸图与场景的色温差
    m = _face_mask(cv2, np, crop.shape, box_c, feather=4)[:, :, 0] > 0.5
    for c in range(3):
        src, dst = warped[:, :, c][m], crop[:, :, c][m]
        warped[:, :, c] = np.clip(
            (warped[:, :, c].astype("float32") - src.mean()) * (dst.std() / (src.std() + 1e-6))
            + dst.mean(), 0, 255).astype(np.uint8)
    mask = _face_mask(cv2, np, crop.shape, box_c)
    base_img[y0:y1, x0:x1] = (warped * mask + crop * (1 - mask)).astype(np.uint8)


#: 裁脸换脸提示词（F5 实验定稿）：参考图含双人时按性别对应本人
FACE_SWAP_PROMPT = ("把图1中人物的脸部替换为后附参考照片中与图1人物同性别的那位本人的脸："
                    "五官、脸型、皮肤质感严格向本人照片还原，宁可朴素也必须像本人，严禁美化成标准模板脸；"
                    "保持图1的构图、姿势、发型轮廓、光影方向、背景与其余一切完全不变，"
                    "换脸边缘自然融合无破绽，摄影级质感，无文字无水印")


def face_swap_restore(order_no: str, gen: bytes, job_id: int, tag: str,
                      anchor_files: list[Path] | None = None) -> bytes:
    """终案面部工序（反馈 #52 及 8-23 对照实验）：整图一遍生成环境光影保真但小脸必漂，
    本工序对每张人脸：检出人脸 → 裁脸放大（脸≥300px，模型注意力集中在脸部）→
    Seedream 带本人参考换脸（identity 上限最高，实测远优于火山人像融合与整图还原）→
    YuNet 5 关键点仿射对齐 + 颜色匹配 + 羽化贴回（环境一个像素不动）。
    任一环节失败只影响该张脸（保留原脸），整体绝不挡交付；cv2/模型缺失降级 face_restore。"""
    try:
        import cv2
        import numpy as np
    except ImportError:
        log(f"job#{job_id} {tag} OpenCV 不可用，降级整图面部还原")
        return face_restore(order_no, gen, job_id, tag)
    if not YUNET_MODEL.is_file():
        log(f"job#{job_id} {tag} YuNet 模型缺失，降级整图面部还原")
        return face_restore(order_no, gen, job_id, tag)
    # 身份参考：本任务实际使用的锚点图 + 三视图/原照（去重，至多 4 张）
    refs: list[Path] = []
    for f in (anchor_files or []) + _identity_refs(order_no):
        if f and f not in refs:
            refs.append(f)
    refs = refs[:4]
    if not refs:
        log(f"job#{job_id} {tag} 无身份参考，跳过裁脸换脸")
        return gen
    img = cv2.imdecode(np.frombuffer(gen, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        log(f"job#{job_id} {tag} 成片解码失败，交付一遍图")
        return gen
    faces = _yunet_detect(cv2, img)
    if not faces:
        log(f"job#{job_id} {tag} 未检出人脸，交付一遍图")
        return gen
    ih, iw = img.shape[:2]
    swapped = 0
    for fi, (box, _) in enumerate(faces[:2]):  # 至多处理 2 张脸（我们的场景至多双人）
        x, y, w, h = [float(v) for v in box]
        # 裁脸框：脸占约 1/2 宽度（带颈部与部分肩部上下文，换脸自然）
        ex, ey = w * 1.0, h * 0.9
        x0, y0 = max(0, int(x - ex)), max(0, int(y - ey))
        x1, y1 = min(iw, int(x + w + ex)), min(ih, int(y + h + ey * 1.3))
        crop = img[y0:y1, x0:x1].copy()
        # 放大到脸 ≥300px（小火山/Seedream 都需要足够像素才保真）
        scale = min(3.0, max(1.0, 340.0 / max(w, h)))
        if scale > 1.01:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        crop_file = TMP / f"{order_no}_fcrop_{re.sub(r'[^A-Za-z0-9]', '_', tag)}_{fi}.jpg"
        swap_file = TMP / f"{order_no}_fswap_{re.sub(r'[^A-Za-z0-9]', '_', tag)}_{fi}.jpg"
        try:
            cv2.imwrite(str(crop_file), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            swap_file.write_bytes(seedream(FACE_SWAP_PROMPT, [crop_file] + refs))
            _paste_swapped_face(cv2, np, img, (x0, y0, x1, y1), swap_file)
            swapped += 1
        except Exception as e:
            log(f"job#{job_id} {tag} 第 {fi + 1} 张脸换脸失败，保留原脸：{str(e)[:160]}")
    if swapped:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if ok:
            log(f"job#{job_id} {tag} 裁脸换脸完成（{swapped}/{min(len(faces), 2)} 张脸）")
            return buf.tobytes()
    return gen


def _identity_refs(order_no: str) -> list[Path]:
    """修图链路的人物身份参考（反馈 #49/#50）：优先人脸三视图（真脸权威参考），
    没有三视图则回退成员原始照片（正脸槽位优先，每角色 1 张，最多 2 张）。"""
    refs = _face_sheet_refs(order_no, ["A", "B"])
    if refs:
        return refs
    conn = db()
    keys = []
    for role in ("A", "B"):
        contact = order_no if role == "A" else f"{order_no}-{role}"
        row = conn.execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
            " ORDER BY (slot='front') DESC, id DESC LIMIT 1", (contact,)).fetchone()
        if row:
            keys.append((role, row[0]))
    conn.close()
    for i, (role, key) in enumerate(keys):
        try:
            refs.append(oss_get(key, TMP / f"{order_no}_{role}_identity{i}.jpg"))
        except Exception as e:
            log(f"身份参考下载失败 {key}: {e}")
    return refs


def run_face_sheet(job_id: int, order_no: str, payload: dict) -> None:
    """人脸三视图：正脸底照 + 用户原始侧脸照为参考，生成正/左/右脸部特写卡（反馈 #26）。

    只有脸部特写、不参考服装；产物供 template/duo/series 生成时作侧脸身份锚点。
    2026-08-07 画质实测：5.0 Pro 三视角分镜 2K×3 + 本地拼接 > 4.5@4K 单图
    （发丝/皮肤细节更好且画幅规范），故分镜生成后 Pillow 横拼。
    """
    role = "B" if payload.get("role") == "B" else "A"
    base_key = payload.get("base_key")
    side_keys = [k for k in (payload.get("side_keys") or []) if k][:2]
    if not base_key:
        raise RuntimeError("人脸三视图任务缺 base_key（正脸底照）")
    if not side_keys:
        raise RuntimeError("人脸三视图任务缺 side_keys（侧脸原照，至少 1 张）")
    base = oss_get(base_key, TMP / f"{order_no}_{role}_facebase.jpg")
    sides = [oss_get(k, TMP / f"{order_no}_{role}_faceside{i}.jpg")
             for i, k in enumerate(side_keys)]
    views = []
    for tag, view in (("front", "正面脸部特写"), ("left", "左侧脸特写"), ("right", "右侧脸特写")):
        refs = [base] if tag == "front" else [base] + sides
        prompt = (f"同一人物{view}，只有头部特写，不显示服装与身体，纯白背景，无边框，竖版"
                  + FACE_SHEET_IDENTITY)
        log(f"job#{job_id} face_sheet 角色 {role} {tag} 参考图 {len(refs)} 张")
        views.append(seedream(prompt, refs, size="1440x2560"))
    # 横拼 3 张竖版（4320x2560）
    from PIL import Image
    import io
    imgs = [Image.open(io.BytesIO(b)) for b in views]
    canvas = Image.new("RGB", (sum(i.width for i in imgs), max(i.height for i in imgs)), "white")
    x = 0
    for im in imgs:
        canvas.paste(im, (x, 0))
        x += im.width
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=92)
    img = buf.getvalue()
    key = f"results/{order_no}/{uuid.uuid4().hex[:8]}.jpg"
    url = oss_put_url(key, img, "image/jpeg")
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"url": url, "oss_key": key, "role": role}, ensure_ascii=False), job_id))
    conn.commit()
    conn.close()
    log(f"job#{job_id} face_sheet 完成 角色 {role} -> {key}")


# ---------------- storylab 素材理解（VLM 打标，storylab 组 2026-08-29） ----------------
#: 每单最多打标段数 / 单段时长上限（超限跳过并记日志）
STORYLAB_MAX_SEGMENTS = 20
STORYLAB_MAX_DURATION = 60


def _storylab_mod():
    """惰性导入 luckynemo-toolkit 的 storylab_ingest 打标模块。

    mp_worker 本身不依赖 toolkit 包（仅复用其 .env 凭据），这里按序找 toolkit 根：
    TOOLKIT_DIR 环境变量 → ECS 固定路径 → 仓库本地路径。
    """
    for p in (ENV.get("TOOLKIT_DIR", ""), "/opt/luckynemo/toolkit",
              str(SERVER_DIR.parent / "tools" / "luckynemo-toolkit")):
        if p and Path(p).is_dir() and p not in sys.path:
            sys.path.insert(0, p)
    import luckynemo.storylab_ingest as si
    return si


def run_storylab_ingest(job_id: int, order_no: str, payload: dict) -> None:
    """素材理解：订单上传的视频（uploads 表 video/*）逐段 VLM 打标 → mp_storylab_tags。

    复用 storylab_ingest 的探测/抽帧/本地 motion/音峰/VLM 打标函数（P4 模块，
    奔奔 15 段实测与人工剪辑师 3/3 黄金镜头一致）。限额每单 20 段、单段 ≤60s；
    单段失败重试 1 次再标 error 不阻塞整单；已打标过的段自动跳过（幂等，可重跑补新素材）。
    """
    si = _storylab_mod()
    conn = db()
    rows = conn.execute(
        "SELECT oss_key, filename FROM uploads"
        " WHERE contact IN (?, ?) AND content_type LIKE 'video/%'"
        " ORDER BY id LIMIT ?", (order_no, f"{order_no}-B", STORYLAB_MAX_SEGMENTS + 20)).fetchall()
    conn.close()
    if not rows:
        raise RuntimeError("订单没有已登记的视频素材（uploads 表无 video/* 记录）")
    work = TMP / f"storylab_{order_no}"
    work.mkdir(exist_ok=True)
    api_key = MINIMAX_KEY
    if not api_key:
        raise RuntimeError("未配置 MINIMAX_API_KEY，无法做素材理解打标")
    vlm_model = ENV.get("STORYLAB_VLM_MODEL", si.DEFAULT_VLM_MODEL)
    ok = err = skipped = 0
    done_keys = []
    conn = db()
    done_keys = [r[0] for r in conn.execute(
        "SELECT oss_key FROM mp_storylab_tags WHERE order_no=?", (order_no,)).fetchall()]
    conn.close()
    for key, filename in rows:
        if len(done_keys) >= STORYLAB_MAX_SEGMENTS:
            log(f"job#{job_id} storylab 已达每单 {STORYLAB_MAX_SEGMENTS} 段上限，其余跳过")
            break
        if key in done_keys:
            continue
        suffix = Path(filename or key).suffix or ".mp4"
        local = work / f"{len(done_keys):02d}{suffix}"
        try:
            oss_get(key, local)
            probe = si.probe_video(local)
            if probe["duration"] > STORYLAB_MAX_DURATION:
                log(f"job#{job_id} storylab 跳过 {filename or key}："
                    f"{probe['duration']:.0f}s 超过单段 {STORYLAB_MAX_DURATION}s 上限")
                skipped += 1
                continue
            frames, timestamps = si.extract_frames(local, probe, work / "frames")
            m_score = si.motion_score(local)
            m_level = si.motion_level(m_score)
            peaks = si.audio_peaks(local) if probe["has_audio"] else []
            log(f"job#{job_id} storylab 打标 {filename or key}（{probe['duration']:.0f}s，运动{m_level}）")
            tags, last_err = None, ""
            for attempt in range(1, si.TAG_MAX_ATTEMPTS + 1):
                try:
                    tags = si.normalize_tags(
                        si.vlm_tag_segment(frames, timestamps, probe, m_level, peaks,
                                           api_key, vlm_model),
                        probe["duration"])
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)[:200]
                    log(f"  VLM 失败（第 {attempt}/{si.TAG_MAX_ATTEMPTS} 次）：{last_err}")
                    if attempt < si.TAG_MAX_ATTEMPTS:
                        time.sleep(3)
            conn = db()
            if tags:
                win = tags.get("highlight_window")
                conn.execute(
                    "INSERT INTO mp_storylab_tags(order_no,oss_key,filename,duration,motion_level,"
                    "highlight,highlight_window,tags_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (order_no, key, filename or Path(key).name, probe["duration"], m_level,
                     tags.get("highlight", 0),
                     f"{win[0]}-{win[1]}" if win else "",
                     json.dumps(tags, ensure_ascii=False), "ok", _now_iso()))
                ok += 1
                done_keys.append(key)
            else:
                conn.execute(
                    "INSERT INTO mp_storylab_tags(order_no,oss_key,filename,duration,status,error,created_at)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (order_no, key, filename or Path(key).name,
                     probe["duration"], "error", last_err, _now_iso()))
                err += 1
                done_keys.append(key)
            conn.commit()
            conn.close()
        except Exception as e:  # noqa: BLE001 - 单段异常不阻塞整单
            err += 1
            log(f"job#{job_id} storylab 段处理失败 {filename or key}: {str(e)[:200]}")
        finally:
            try:
                local.unlink(missing_ok=True)
            except OSError:
                pass
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"segments": ok + err, "ok": ok, "error": err, "skipped_long": skipped},
                             ensure_ascii=False), job_id))
    conn.commit()
    conn.close()
    log(f"job#{job_id} storylab_ingest 完成：打标 {ok} 段，失败 {err} 段，超限跳过 {skipped} 段")


def _suggest_window(duration: float, window: str) -> dict:
    """高光窗口 "a-b" → 建议入出点；没有则素材中段。"""
    try:
        a, b = window.split("-")
        ia, ib = float(a), float(b)
        if 0 <= ia < ib <= duration + 0.5:
            return {"in": ia, "out": min(ib, duration)}
    except Exception:  # noqa: BLE001
        pass
    start = max(0.0, duration / 2 - 1.5)
    return {"in": start, "out": min(duration, start + 3.0)}


def _m3_storyboard_film(segs: list, prefs: dict) -> list:
    """1 次 M3 调用：素材标签 + 偏好 → 镜表（≤12 镜，竖屏，真实为主，0 生成帧）。"""
    if not MINIMAX_KEY:
        raise RuntimeError("未配置 MINIMAX_API_KEY，无法生成分镜")
    model = ENV.get("MINIMAX_LLM_MODEL", "MiniMax-M3")
    system = (
        "你是短片剪辑分镜师。根据给定的真实素材片段（caption/时长/高光窗口/建议入出点）"
        "和用户偏好，输出竖屏短片的镜表 JSON。只输出 JSON（无 markdown 代码块）。\n"
        '格式：{"shots":[{"oss_key":"...","in":秒,"out":秒,"note":"一句话画面说明"}...]}\n'
        "规则：≤12 镜；优先采用 suggested 入出点（用户高光窗口），可小幅调整但必须在片段时长内；"
        "每镜 1.5-8 秒；按叙事排序（开场→发展→高潮→收尾）；遵守用户偏好"
        "（情绪基调定节奏、必含画面优先安排、禁区画面避开）；只用给定 oss_key；竖屏 9:16 构图思维。")
    user = json.dumps({"prefs": {k: v for k, v in prefs.items() if not k.startswith("_")},
                       "segments": segs}, ensure_ascii=False)
    r = requests.post(f"{MINIMAX_BASE}/chat/completions",
                      headers={"Authorization": f"Bearer {MINIMAX_KEY}"},
                      json={"model": model, "max_tokens": 8000, "temperature": 0.5,
                            "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": user}]},
                      timeout=180)
    text = r.json()["choices"][0]["message"]["content"]
    text = re.sub(r"<think>[\s\S]*?</think>", "", text or "")  # M3 思维链剥除
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise RuntimeError("M3 分镜输出无法解析")
    blob = m.group(0)
    data = None
    try:
        data = json.loads(blob)
    except Exception:  # noqa: BLE001
        try:
            data, _ = json.JSONDecoder().raw_decode(blob)
        except Exception:  # noqa: BLE001
            # 尾部截断修复：补闭合；再不行逐镜提取完整 shot 对象
            trimmed = re.sub(r",\s*$", "", blob)
            for suffix in ("]}", "}", "]"):
                try:
                    data = json.loads(trimmed + suffix)
                    break
                except Exception:  # noqa: BLE001
                    continue
            if data is None:
                shots_raw = re.findall(r"\{[^{}]*\"oss_key\"[^{}]*\}", blob)
                if shots_raw:
                    data = {"shots": [json.loads(s) for s in shots_raw]}
    shots = (data or {}).get("shots") or []
    shots = [s for s in shots if isinstance(s, dict) and s.get("oss_key")]
    if not shots:
        raise RuntimeError("M3 分镜输出空镜表")
    return shots[:12]


def run_storylab_film(job_id: int, order_no: str, payload: dict) -> None:
    """「故事片场」短片：素材标签 → M3 分镜（1 次）→ ffmpeg/PIL 组装（0 生成调用）。

    交付 results/{order_no}/storylab_film_{ts}.mp4；<3 段可用素材直接报错误。
    voice=加旁白 的偏好 v1 不执行（BGM+原声），由 chat 话术说明"旁白版随后就来"。
    """
    import storylab_film as sf
    conn = db()
    rows = conn.execute(
        "SELECT oss_key, filename, duration, highlight, highlight_window, tags_json"
        " FROM mp_storylab_tags WHERE order_no=? AND status='ok' ORDER BY highlight DESC",
        (order_no,)).fetchall()
    prow = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                        (order_no,)).fetchone()
    conn.close()
    if len(rows) < 3:
        raise RuntimeError(f"故事片场素材不足（已理解 {len(rows)} 段 < 3 段），多传几段视频花絮再来")
    prefs = json.loads(prow[0]) if prow and prow[0] else {}
    work = TMP / f"film_{order_no}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        bgm = oss_get("assets/storylab/bgm.mp3", work / "bgm.mp3")
        font = oss_get("assets/storylab/font.ttc", work / "font.ttc")
        segs, materials = [], {}
        for key, fn, dur, hl, win, tj in rows[:12]:
            local = oss_get(key, work / (fn or Path(key).name))
            t = json.loads(tj) if tj else {}
            materials[key] = local
            segs.append({"oss_key": key, "caption": t.get("caption", ""),
                         "duration": dur or 0, "highlight": hl or 0,
                         "highlight_window": win or "",
                         "suggested": _suggest_window(dur or 0, win or "")})
        log(f"job#{job_id} storylab_film 素材 {len(segs)} 段，M3 分镜中...")
        shots = _m3_storyboard_film(segs, prefs)
        shots = [s for s in shots if s["oss_key"] in materials]
        if len(shots) < 2:
            raise RuntimeError("M3 镜表与素材对不上（可用镜 < 2），请重试")
        subtitles = sf.pick_subtitles(str(prefs.get("tone", "")), len(shots))
        out = work / "storylab_film.mp4"
        meta = sf.assemble(shots, materials, bgm, font, work / "intermediates", out,
                           subtitles)
        key = f"results/{order_no}/storylab_film_{time.strftime('%Y%m%d_%H%M%S')}.mp4"
        url = oss_put_url(key, out.read_bytes(), "video/mp4")
        conn = db()
        conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                     (json.dumps({"url": url, "oss_key": key, "duration": meta["duration"],
                                  "shots": meta["shots"], "width": meta["width"],
                                  "height": meta["height"]}, ensure_ascii=False), job_id))
        conn.execute("UPDATE mp_orders SET status='done', updated_at=datetime('now') WHERE order_no=?",
                     (order_no,))
        conn.commit()
        conn.close()
        log(f"job#{job_id} storylab_film 完成 -> {key}（{meta['duration']:.1f}s，{meta['shots']} 镜）")
        meta["local"] = str(out)
        meta["oss_key"] = key
        return meta
    finally:
        if not payload.get("keep_local"):
            try:
                for f in work.glob("*"):
                    if f.is_file():
                        f.unlink()
                inter = work / "intermediates"
                if inter.is_dir():
                    for f in inter.glob("*"):
                        f.unlink()
            except OSError:
                pass


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ---------------- Vidu 参考生图（定妆照优先通道） ----------------
VIDU_BASE = "https://api.vidu.cn/ent/v2"


def vidu_reference2image(prompt: str, ref_files: list[Path], aspect_ratio: str = "3:4",
                         model: str = "viduq2") -> bytes:
    """Vidu 参考生图/图片编辑：图1人物 + 图2妆造参考 + 提示词。异步任务轮询取图。"""
    if not VIDU_KEY:
        raise RuntimeError("未配置 VIDU_API_KEY")
    imgs = []
    for p in ref_files:
        b64 = base64.b64encode(p.read_bytes()).decode()
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        imgs.append(f"data:{mime};base64,{b64}")
    r = requests.post(
        f"{VIDU_BASE}/reference2image",
        headers={"Authorization": f"Bearer {VIDU_KEY}", "Content-Type": "application/json"},
        json={"model": model, "prompt": prompt, "images": imgs, "aspect_ratio": aspect_ratio},
        timeout=120,
    )
    data = r.json()
    if r.status_code >= 300 or "task_id" not in data:
        raise RuntimeError(f"Vidu 创建任务失败：{json.dumps(data, ensure_ascii=False)[:300]}")
    task_id = data["task_id"]
    log(f"Vidu 任务 {task_id} 已创建，轮询中...")
    for _ in range(60):  # 最长 5 分钟
        time.sleep(5)
        q = requests.get(f"{VIDU_BASE}/tasks/{task_id}/creations",
                         headers={"Authorization": f"Bearer {VIDU_KEY}"}, timeout=30)
        qd = q.json()
        state = qd.get("state", "")
        if state == "success":
            urls = qd.get("creations") or []
            img_url = urls[0].get("url") if urls else None
            if not img_url:
                raise RuntimeError(f"Vidu 成功但无结果图：{json.dumps(qd, ensure_ascii=False)[:300]}")
            return requests.get(img_url, timeout=120).content
        if state in ("failed", "fail", "error"):
            raise RuntimeError(f"Vidu 任务失败：{json.dumps(qd, ensure_ascii=False)[:300]}")
    raise RuntimeError("Vidu 任务超时（5 分钟未完成）")


def makeup_with_vidu(prompt: str, ref_files: list[Path]) -> bytes:
    """定妆照：优先 Vidu（人物照 + 红妆阁妆造图双参考），失败回退 Seedream。"""
    if VIDU_KEY:
        try:
            return vidu_reference2image(prompt, ref_files)
        except Exception as e:
            log(f"Vidu 失败，回退 Seedream：{e}")
    return None


# ---------------- 任务执行 ----------------
SITE_DIR = Path(ENV.get("SITE_DIR", "/var/www/luckynemo"))

#: 人脸三视图规范（与 tools/luckynemo-toolkit video_pipeline 同源移植，2026-08-07，
#: 反馈 #26：婚纱照大量侧脸对视，单正脸参考侧脸失真）。
#: 生成方式（2026-08-07 画质实测定稿）：5.0 Pro 三视角分镜 2K×3 + Pillow 横拼，
#: 优于 4.5@4K 单图（发丝/皮肤细节更好、画幅规范）
FACE_SHEET_IDENTITY = ("，保持与参考图人物五官、脸型完全一致，侧脸的鼻梁高度、下颌线、"
                       "耳朵形状严格按侧面参考照还原，不要美化成标准模板脸")
#: 生成任务注入人脸三视图时的锚定尾缀
#: （三视图由原始照片生成、不随定妆/换发型重出，故明确"仅供五官参考"，
#:  发型妆容跟主锚点图/模板走，避免侧脸镜头被三视图里的旧发型往回拉）
FACE_SHEET_ANCHOR = ("随附的人脸三视图（正/左/右侧脸部特写）是人物五官的权威参考："
                     "人物的侧脸鼻梁高度、下颌线、耳朵形状严格按三视图还原，不要美化成标准模板脸；"
                     "三视图仅供五官特征参考，其中的发型与妆容不作参考")


def scene_index() -> dict:
    """场景资产索引：id/名称 → {name, pitch, img}（微剧情场景库）。"""
    import re as _re
    try:
        js = (SITE_DIR / "scenes/data.js").read_text(encoding="utf-8")
    except Exception:
        return {}
    idx = {}
    for m in _re.finditer(r"\{[^{}]*\}", js):
        block = m.group(0)
        idm = _re.search(r'"id":\s*"([^"]+)"', block)
        nm = _re.search(r'"name":\s*"([^"]+)"', block)
        pm = _re.search(r'"pitch":\s*"([^"]+)"', block)
        im = _re.search(r'"img":\s*"([^"]+)"', block)
        dm = _re.search(r'"directives":\s*"([^"]+)"', block)
        if idm and im:
            info = {"name": nm.group(1) if nm else "",
                    "pitch": pm.group(1) if pm else "", "img": im.group(1),
                    "directives": dm.group(1) if dm else ""}
            idx[idm.group(1)] = info
            if nm:
                idx[nm.group(1)] = info  # 对话接口可能传名称
    return idx


def clothing_file(img: str) -> Path | None:
    """霓裳阁服装图本地路径（worker 与站点同机，直接读静态目录）。"""
    if not img:
        return None
    p = SITE_DIR / "wardrobe" / "img" / img.replace("img/", "", 1)
    return p if p.is_file() else None


def asset_refs(payload: dict) -> tuple[list[Path], str]:
    """收集服装图 + 场景图作为视觉参考，返回 (文件列表, 场景描述文本)。"""
    refs: list[Path] = []
    s = payload.get("set") or {}
    for piece in ("dress", "suit"):
        f = clothing_file(((s.get(piece) or {}).get("img") or ""))
        if f:
            refs.append(f)
    idx = scene_index()
    scene_txts = []
    for sid in payload.get("scenes") or []:
        info = idx.get(sid)
        if not info:
            continue
        base = f"{info['name']}（{info['pitch']}）" if info["pitch"] else info["name"]
        # 场景专属指令：道具/人物状态/光影/防穿帮（如雨景必须有手执伞）
        if info.get("directives"):
            base += f"，{info['directives']}"
        scene_txts.append(base)
        f = SITE_DIR / "scenes" / "img" / Path(info["img"]).name
        if f.is_file():
            refs.append(f)
    return refs, "；".join(scene_txts)


def order_photos(order_no: str, role: str = "A", limit: int = 4, skip_key: str = "") -> list[Path]:
    """取成员照片：A=新娘/本人（contact=order_no），B=新郎（contact=order_no-B）。
    skip_key：排除指定 OSS key（底照已单独下载时避免重复）。"""
    contact = order_no if role == "A" else f"{order_no}-{role}"
    conn = db()
    keys = [r[0] for r in conn.execute(
        "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%' ORDER BY id DESC LIMIT ?",
        (contact, limit + 1))]
    conn.close()
    files = []
    for i, key in enumerate(keys):
        if key == skip_key:
            continue
        try:
            files.append(oss_get(key, TMP / f"{order_no}_{role}_{i}.jpg"))
        except Exception as e:
            log(f"照片下载失败 {key}: {e}")
        if len(files) >= limit:
            break
    return files


def _anchor_or_photos(order_no: str, payload: dict, job_id: int) -> list[Path]:
    """优先用定妆照锚点（锁定妆造后的脸），锚点缺失回退新娘原照片。"""
    anchor_key = payload.get("anchor_key")
    if anchor_key:
        try:
            log(f"job#{job_id} 使用定妆照锚点 {anchor_key}")
            return [oss_get(anchor_key, TMP / f"{order_no}_anchor.jpg")]
        except Exception as e:
            log(f"锚点下载失败，回退原照片：{e}")
    return order_photos(order_no, "A")


def _anchor_or_photos_b(order_no: str, payload: dict, job_id: int) -> list[Path]:
    """新郎侧：优先新郎定妆照锚点（anchor_key_b），否则新郎原照片。"""
    anchor_key = payload.get("anchor_key_b")
    if anchor_key:
        try:
            log(f"job#{job_id} 使用新郎定妆照锚点 {anchor_key}")
            return [oss_get(anchor_key, TMP / f"{order_no}_anchor_b.jpg")]
        except Exception as e:
            log(f"新郎锚点下载失败，回退原照片：{e}")
    return order_photos(order_no, "B", limit=2)


def build_photo_prompt(payload: dict, scene_txt: str) -> str:
    s = payload.get("set") or {}
    dress = (s.get("dress") or {}).get("name", "白色婚纱")
    if not scene_txt:
        scene_txt = "柔和纯色背景"
    makeup_txt = f"妆容为「{payload['makeup_name']}」，保持与参考定妆照一致的妆面，" if payload.get("makeup_name") else ""
    if payload.get("mode") == "solo" and payload.get("makeup_name_b"):
        makeup_txt = f"妆容为「{payload['makeup_name_b']}」，保持与参考定妆照一致的妆面，"
    poses = payload.get("poses") or []
    pose_txt = "、".join(poses) if poses else "自然微笑"
    lock = "保持与参考图人物五官、脸型、发型发色完全一致，无文字无水印，摄影级质感"
    ref_note = "提示词后附的参考图依次为：人物、服装、场景参考，请按参考图的服装款式与场景氛围绘制，"
    # 比例与融合（2026-07-30 用户反馈：头身比失调 + 抠图感 + 穿帮杂物）
    proportion = ("真实人体比例：全身竖版构图，身高约7.5个头长，头部大小自然，"
                  "脸部参考图仅用于锁定五官特征，不要参照参考图的头肩比例，")
    fusion = ("人物光影必须与场景光源方向一致，场景的光斑与色彩也落在人物和服装上，"
              "人物在地面有自然投影，与场景融为一体，绝无抠图合成感；"
              "地面上只有自然场景，绝对不要出现纸张、书本、文件等任何多余物品，")
    if payload.get("mode") == "solo":
        if s.get("suit") and not s.get("dress"):
            suit_name = (s.get("suit") or {}).get("name", "深色西装")
            return (
                f"一位年轻男性的全身写真照：他穿{suit_name.split('·')[-1]}，{makeup_txt}"
                f"场景：{scene_txt}，动作神态：{pose_txt}，影楼级布光，"
                f"{proportion}{fusion}{ref_note}画面中仅他一个人物，{lock}"
            )
        return (
            f"一位年轻女性的全身写真照：她穿{dress.split('·')[-1]}，{makeup_txt}"
            f"场景：{scene_txt}，动作神态：{pose_txt}，影楼级布光，"
            f"{proportion}{fusion}{ref_note}画面中仅她一个人物，{lock}"
        )
    suit = (s.get("suit") or {}).get("name", "深色西装")
    groom_makeup = f"新郎妆容为「{payload['makeup_name_b']}」，" if payload.get("makeup_name_b") else ""
    return (
        f"一对新婚夫妻的全身婚纱照：新娘穿{dress.split('·')[-1]}，新郎穿{suit.split('·')[-1]}，"
        f"新娘{makeup_txt}{groom_makeup}场景：{scene_txt}，动作神态：{pose_txt}，"
        f"{proportion}{fusion}"
        f"参考图前两张为新娘与新郎，{ref_note}画面中仅这一男一女，{lock}"
    )


def run_job(job_id: int, order_no: str, kind: str, payload: dict) -> None:
    if kind == "custom_moka":
        run_custom_moka(job_id, order_no, payload)
        return
    if kind == "template_series":
        run_template_series(job_id, order_no, payload)
        return
    if kind == "face_sheet":
        run_face_sheet(job_id, order_no, payload)
        return
    if kind == "storylab_ingest":
        run_storylab_ingest(job_id, order_no, payload)
        return
    if kind == "storylab_film":
        run_storylab_film(job_id, order_no, payload)
        return
    result = None
    anchor_imgs: list = []  # 本任务实际使用的人物锚点图（供裁脸换脸做身份参考）
    if kind == "edit_photo":
        # 成片局部修图：以已生成的成片为底，按用户指令只改指定部分（去眼镜/调表情/改细节）
        base_key = payload.get("base_key")
        if not base_key:
            raise RuntimeError("修图任务缺 base_key")
        photos = [oss_get(base_key, TMP / f"{order_no}_edit_base.jpg")]
        instruction = str(payload.get("instruction") or "").strip()
        if not instruction:
            raise RuntimeError("修图任务缺修改指令")
        prompt = (f"这是对图1照片的局部修图，不是重新生成：{instruction}。"
                  "严格保持人物五官、构图、场景、服装、光影、色调等其余部分完全不变，"
                  "只修改用户要求的部分，修图痕迹自然无破绽，摄影级质感，无文字无水印")
        # 反馈 #49/#50：「不像本人」类修图若只送成片，模型没见过本人，永远修不像——
        # 注入身份参考：优先人脸三视图（原始照片生成的权威长相），缺则回退本人原始照片
        identity = _identity_refs(order_no)
        if identity:
            photos += identity
            prompt += ("。紧随其后的参考图是图1中人物的本人真实照片（长相的权威参考）："
                       "若修改意见涉及不像/五官/长相，必须把人物五官脸型向本人照片还原")
        # 反馈 #47：修改意见引用模板（"男生发型用模板里的"）时模板图必须传入，
        # 否则模型无从得知模板内容——回溯底图来源任务，同款/系列成片带上对应模板
        tpl_ref = _template_ref_for_result(order_no, base_key)
        if tpl_ref:
            photos.append(tpl_ref)
            prompt += "。最后一张参考图是生成图1时使用的摄影模板，修改意见中提及「模板」的部分参照它执行"
    elif kind == "duo_photo":
        # 双人合照：参考图里的两个人（两张单人照或一张现成合照）生成一张亲密合照
        keys = (payload.get("photos") or [])[:2]
        if not keys:
            raise RuntimeError("合照任务缺人物照片")
        photos = [oss_get(k, TMP / f"{order_no}_duo_{i}.jpg") for i, k in enumerate(keys)]
        anchor_imgs = list(photos)  # 双人合照的两个人物参考即锚点
        note = str(payload.get("note") or "").strip()
        # 人脸三视图注入（反馈 #26 侧脸不像）
        face_refs = _face_sheet_refs(order_no, ["A", "B"])
        photos += face_refs
        prompt = (
            "参考图是要合在一起拍摄的两个人（可能一张照片一个人，也可能一张里已有两人）。"
            "生成一张这两个人的亲密合照：两人的五官、脸型与发型发色与参考图人物一一对应保持一致，"
            "两人自然依偎或牵手，温馨浪漫的场景与柔和暖光，真实人体比例约7.5头身，"
            "人物与地面有自然接触和投影，摄影级质感，无文字无水印"
        )
        if face_refs:
            prompt += "。" + FACE_SHEET_ANCHOR
        heights = _order_heights(order_no)
        if heights:
            prompt += f"。两人真实身高：{heights}，严格还原身高差与各自体型"
        if note:
            prompt += f"。场景氛围要求：{note}"
    elif kind == "makeup_photo":
        # 定妆照任务：对应成员照片（A=新娘/本人，B=新郎）+ 红妆阁配方提示词
        role = "B" if payload.get("role") == "B" else "A"
        # 用户指定底照：单独下载并排到参考图第一位（定妆以它为基础，其余做人脸参考）
        base_key = payload.get("base_key")
        photos = order_photos(order_no, role, skip_key=base_key)
        if base_key:
            try:
                photos.insert(0, oss_get(base_key, TMP / f"{order_no}_{role}_base.jpg"))
                log(f"job#{job_id} 使用用户选定底照 {base_key}")
            except Exception as e:
                log(f"底照下载失败，按默认顺序：{e}")
        prompt = payload.get("makeup_prompt") or ""
        if not prompt:
            raise RuntimeError("makeup_photo 任务缺 makeup_prompt")
        if not photos:
            raise RuntimeError("订单没有可用照片（uploads 表为空）")
        # 原图直出版：只用底图一张（严禁参考其他照片），不融合妆容建议、不改发型
        use_original = "原图直出" in str(payload.get("makeup_name", ""))
        if use_original:
            photos = photos[:1]
            advice = ""
            # 用户的附加修饰要求（如"去掉汗水"）：仅限皮肤瑕疵层面，五官严禁改变
            if payload.get("makeup_notes"):
                prompt += (f"\n额外修饰要求（仅限皮肤瑕疵层面，五官脸型表情严禁改变）："
                           f"{payload['makeup_notes']}")
            # 用户显式选了发型（反馈 #36）：原图直出唯一放开的改动——只换发型，其余仍严格不动
            if payload.get("hairstyle"):
                prompt += (
                    f"\n发型例外：允许且仅允许将人物发型调整为「{payload['hairstyle']}」，"
                    "除此之外脸部、五官、脸型、表情、服装、画面构图仍严格保持与参考照片一致"
                )
        else:
            # LLM 化妆师：先分析人物原图给出个性化建议，融合进标准提示词
            advice = analyze_face(photos[0], payload.get("makeup_name", ""), payload.get("gender", "female"))
            prompt = merge_face_advice(prompt, advice, payload.get("makeup_notes", ""))
            # 发型装扮：用户选了发型则允许改发型（五官脸型仍不动），否则保持原发型
            if payload.get("hairstyle"):
                prompt += (
                    f"\n发型要求：将人物发型调整为「{payload['hairstyle']}」，"
                    "允许改变发型，但五官、脸型、妆容仍须与人物一致"
                )
        # 引擎选择（内测开放）：vidu=妆效好但有漂移风险 / seedream=默认保脸（MiniMax 生图已下架）
        engine = payload.get("engine") or "seedream"
        style_file = SITE_DIR / "hongzhuang" / "styles" / f"{payload.get('makeup_id', '')}.png"
        if engine == "vidu" and style_file.is_file() and not use_original:
            # viduq2 图片编辑模式。男妆只发用户底图+纯文字配方（实测：发参考妆图会被小朗同化）；
            # 女妆发用户图+红妆阁妆造参考图（漂移可接受且妆效更好）；素颜版只发底图+文字
            male = payload.get("gender") == "male"
            no_makeup = "素颜" in str(payload.get("makeup_name", ""))
            if no_makeup:
                vidu_prompt = (
                    "这是对图1照片的人物肖像优化，不是换人：严禁改变图1人物的任何五官特征、脸型、发型和年龄感。"
                    "保持素颜不化妆，仅做肤色均匀与轻微提亮，摘掉眼镜，"
                    "正面肩部以上肖像特写，浅灰纯色背景，专业肖像照质感"
                )
            else:
                vidu_prompt = (
                    f"这是对图1照片的人物修图化妆，不是换人：严禁改变图1人物的任何五官特征、脸型、发型和年龄感。"
                    f"为{'他' if male else '她'}化上「{payload.get('makeup_name', '')}」妆容，"
                    "摘掉眼镜，正面肩部以上肖像特写，浅灰纯色背景，专业妆面照质感"
                )
            vidu_prompt = merge_face_advice(vidu_prompt, advice, payload.get("makeup_notes", ""))
            if payload.get("hairstyle"):
                vidu_prompt += f"\n发型调整为「{payload['hairstyle']}」，允许改变发型，五官脸型不变"
            vidu_refs = photos[:1] if (male or no_makeup) else photos[:1] + [style_file]
            result = makeup_with_vidu(vidu_prompt, vidu_refs)
            if result is None:
                result = seedream(prompt, photos)
        else:
            result = seedream(prompt, photos)
    elif kind == "template_photo":
        # 一键同款：定妆照锚点（缺省时回退原始上传照片——定妆后台化）+ 模板图，只换人，其他保持模板
        _check_anchor_pair(payload)
        photos = []
        if payload.get("anchor_key"):
            photos.append(oss_get(payload["anchor_key"], TMP / f"{order_no}_anchor.jpg"))
        else:
            photos += order_photos(order_no, "A", limit=1)
        has_b = False
        if payload.get("anchor_key_b"):
            photos.append(oss_get(payload["anchor_key_b"], TMP / f"{order_no}_anchor_b.jpg"))
            has_b = True
        elif payload.get("mode") == "couple":
            b_photos = order_photos(order_no, "B", limit=1)
            photos += b_photos
            has_b = bool(b_photos)
        if not photos:
            raise RuntimeError("请先上传本人照片，再做一键同款")
        if payload.get("mode") == "couple" and not has_b:
            raise RuntimeError("情侣模板需要另一方也上传照片（协同创作邀请 TA，或在对话里发 TA 的照片）")
        anchor_imgs = photos[:2] if has_b else photos[:1]
        tpl = None
        if payload.get("custom_template_key"):
            # DIY 定制模卡：从 OSS 取（custom_moka 任务的产物）
            tpl = oss_get(payload["custom_template_key"], TMP / f"{order_no}_diy_moka.jpg")
        else:
            tpl_path = SITE_DIR / "moka" / "templates" / f"{payload.get('template_id', '')}.png"
            if not tpl_path.is_file():
                raise RuntimeError(f"模板不存在 {payload.get('template_id')}")
            tpl = tpl_path
        # 人脸三视图注入（反馈 #26 侧脸不像）：加在模板图之前，保持"最后一张是模板"
        face_refs = _face_sheet_refs(order_no, ["A", "B"] if has_b else ["A"])
        photos += face_refs
        photos.append(tpl)
        # 微调：换服装（附加服装参考图）
        swap_note = payload.get("swap_note", "")
        for img in payload.get("swap_imgs") or []:
            f = clothing_file(img)
            if f:
                photos.append(f)
        prompt = (
            "最后一张参考图是完整的摄影作品模板，前面的参考图是要替换上去的人物。"
            "把模板中的人物替换为参考图的人物（多人时按性别一一对应替换），"
            "严格保持模板的构图、场景、服装、妆容、道具、神态、光影、色调、背景完全不变，"
            "只替换人物的五官与面部特征，人物的发型与发色始终保持本人参考图的样式"
            "（不采用模板人物的发型），真实人体比例约7.5头身，与场景自然融合有投影，"
            "摄影级质感，无文字无水印"
        )
        if face_refs:
            prompt += "。" + FACE_SHEET_ANCHOR
        heights = _order_heights(order_no)
        if heights and has_b:
            prompt += f"。两人真实身高：{heights}，严格还原身高差与各自体型"
        if swap_note:
            prompt += f"。特别调整：{swap_note}"
        log(f"job#{job_id} template_photo 模板 {payload.get('template_id') or payload.get('custom_template_key')} 参考图 {len(photos)} 张")
        expect = "一男一女（情侣）" if has_b else "一位人物（与参考图同人）"
        result = seedream_qc(prompt, photos, expect, job_id, "template_photo")
    elif kind == "solo_photo":
        # 个人写真：定妆照锚点（A=本人/新娘；anchor_key_b 存在时为男士单人）+ 服装/场景视觉参考
        male_solo = bool(payload.get("anchor_key_b")) and not payload.get("anchor_key")
        if male_solo:
            photos = _anchor_or_photos_b(order_no, payload, job_id)
        else:
            photos = _anchor_or_photos(order_no, payload, job_id)
        # 人脸三视图注入（侧脸身份锚定，与 template_photo 一致）：插在人物锚点后、服装场景参考前
        anchor_imgs = photos[:1]  # 单人：锚点（或回退原照）即身份参考
        face_refs = _face_sheet_refs(order_no, ["B"] if male_solo else ["A"])
        photos += face_refs
        extra, scene_txt = asset_refs(payload)
        photos += extra
        prompt = build_photo_prompt(payload, scene_txt)
        if face_refs:
            prompt += "。" + FACE_SHEET_ANCHOR
    else:
        # 婚纱照：新娘/新郎双锚点 + 服装/场景视觉参考，脸和氛围都锁住
        bride = _anchor_or_photos(order_no, payload, job_id)
        groom = _anchor_or_photos_b(order_no, payload, job_id)
        photos = (bride[:1] + groom[:2]) if bride else groom
        anchor_imgs = photos[:2]  # 新娘锚点 + 新郎锚点
        # 人脸三视图注入（侧脸身份锚定）：插在人物锚点后、服装场景参考前
        face_refs = _face_sheet_refs(order_no, ["A", "B"])
        photos += face_refs
        extra, scene_txt = asset_refs(payload)
        photos += extra
        prompt = build_photo_prompt(payload, scene_txt)
        if face_refs:
            prompt += "。" + FACE_SHEET_ANCHOR
    if not photos:
        raise RuntimeError("订单没有可用照片（uploads 表为空）")
    if result is None:
        log(f"job#{job_id} {kind} 参考图 {len(photos)} 张，生成中...")
        # P1 品控兜底：合照/单人/婚纱照全链路 VLM 质检 + 带问题重试（2026-08-07）
        if kind == "duo_photo":
            expect = "两个人（与参考图人物一一对应）"
        elif kind == "solo_photo" or payload.get("mode") != "couple":
            expect = "一位人物（与参考图同人）"
        else:
            expect = "一男一女（情侣）"
        result = seedream_qc(prompt, photos, expect, job_id, kind)
    # 裁脸换脸终案（2026-08-23）：真人出片类任务全量过；定妆照/修图链路本身带身份约束，跳过
    if kind in ("template_photo", "duo_photo", "solo_photo", "free_photo", "paid_photo"):
        result = face_swap_restore(order_no, result, job_id, kind, anchor_files=anchor_imgs)
    key = f"results/{order_no}/{uuid.uuid4().hex[:8]}.jpg"
    url = oss_put_url(key, result, "image/jpeg")
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"url": url, "oss_key": key}), job_id))
    conn.execute("UPDATE mp_orders SET status='done', updated_at=datetime('now') WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()
    _maybe_ref_reward(order_no)
    if kind in PHOTO_KIND_LABEL:
        notify_photo_done(order_no, kind, 1)
    log(f"job#{job_id} 完成 -> {key}")


# ---------------- 微信订阅消息（生成完成推送，2026-08-11） ----------------
#: 用户发起生成时前端弹订阅（一次性：接受一次=可发一次），凭证落 mp_subs 表；
#: 任务完成时消耗一张凭证发推送，点击进相册页 pages/photos/photos。
#: 模板 73339「内容生成成功通知」：short_thing1=内容类型 / number2=生成数量 / time3=生成时间
PHOTO_KIND_LABEL = {"makeup_photo": "定妆照", "template_photo": "同款大片",
                    "template_series": "系列组图", "duo_photo": "双人合照",
                    "solo_photo": "个人写真", "free_photo": "婚纱照", "paid_photo": "婚纱照"}
_wx_token_cache: dict = {}


def _wx_access_token() -> str:
    now = time.time()
    if _wx_token_cache.get("token") and now < _wx_token_cache.get("expires", 0):
        return _wx_token_cache["token"]
    r = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                     params={"grant_type": "client_credential",
                             "appid": MP_APPID, "secret": MP_SECRET}, timeout=15)
    data = r.json()
    if not data.get("access_token"):
        raise RuntimeError(f"取微信 access_token 失败：{data}")
    _wx_token_cache["token"] = data["access_token"]
    _wx_token_cache["expires"] = now + data.get("expires_in", 7200) - 300
    return data["access_token"]


def notify_photo_done(order_no: str, kind: str, count: int = 1) -> None:
    """生成完成 → 订阅消息推送（无订阅凭证/未配置时静默跳过）。"""
    if not (MP_APPID and MP_SECRET and MP_SUB_TMPL):
        return
    conn = db()
    row = conn.execute("SELECT open_token FROM mp_orders WHERE order_no=?", (order_no,)).fetchone()
    openid = row[0][3:] if row and row[0] and row[0].startswith("wx-") else ""
    sub = None
    if openid:
        sub = conn.execute(
            "SELECT id FROM mp_subs WHERE order_no=? AND openid=? AND used=0 ORDER BY id LIMIT 1",
            (order_no, openid)).fetchone()
        if sub:
            # 先消耗凭证再发：一次性订阅发不出去（用户后来取消了授权等）也不重试
            conn.execute("UPDATE mp_subs SET used=1 WHERE id=?", (sub[0],))
            conn.commit()
    conn.close()
    if not sub:
        return
    label = PHOTO_KIND_LABEL.get(kind, "照片")
    try:
        r = requests.post(
            f"https://api.weixin.qq.com/cgi-bin/message/subscribe/send?access_token={_wx_access_token()}",
            json={"touser": openid, "template_id": MP_SUB_TMPL,
                  "page": "pages/photos/photos",
                  "data": {"short_thing1": {"value": label},
                           "number2": {"value": count},
                           "time3": {"value": time.strftime("%Y年%-m月%-d日 %H:%M")}}},
            timeout=15)
        resp = r.json()
        if resp.get("errcode"):
            log(f"订阅消息发送失败 order={order_no}: {resp}")
        else:
            log(f"订阅消息已推送 order={order_no} {label}x{count}")
    except Exception as e:
        log(f"订阅消息发送异常 order={order_no}: {e}")


def _push_chat_event(order_no: str, kind: str) -> None:
    """job 完成事件追加进 mp_chat_state.events（chat_agent 观察闭环，2026-08-29）。

    事件由 chat 下一轮注入 system prompt（消费即清）。无状态行则创建；
    任何异常吞掉不挡交付。
    """
    try:
        label = PHOTO_KIND_LABEL.get(kind, "")
        if kind == "storylab_ingest":
            label = "素材理解"
        if kind == "storylab_film":
            label = "故事片场短片"
        text = f"「{label or kind}」任务已完成，结果已入相册"
        now = _now_iso()
        conn = db()
        row = conn.execute("SELECT state_json FROM mp_chat_state WHERE order_no=?",
                           (order_no,)).fetchone()
        if row and row[0]:
            try:
                state = json.loads(row[0])
                if not isinstance(state, dict):
                    state = {}
            except Exception:  # noqa: BLE001
                state = {}
        else:
            state = {"goal": None, "stage": "open", "slots": {}, "pending_confirm": None,
                     "facts": {}, "events": [], "turn": 0}
        events = state.get("events") or []
        events.append({"kind": "job_done", "job_kind": kind, "text": text, "at": now})
        state["events"] = events[-10:]
        sj = json.dumps(state, ensure_ascii=False)
        if row:
            conn.execute("UPDATE mp_chat_state SET state_json=?, updated_at=? WHERE order_no=?",
                         (sj, now, order_no))
        else:
            conn.execute("INSERT INTO mp_chat_state(order_no,state_json,updated_at)"
                         " VALUES(?,?,?)", (order_no, sj, now))
        conn.commit()
        conn.close()
    except Exception as e:  # noqa: BLE001
        log(f"chat event 写入失败（忽略）order={order_no}: {e}")


def _maybe_ref_reward(order_no: str) -> None:
    """裂变奖励（2026-08-07）：受邀订单首次生成成功 → 邀请人 +1 张免费额度（只奖一次）。

    order.ref = 邀请人 share_token（chat 分享卡片/海报小程序码带入）。
    """
    conn = db()
    row = conn.execute("SELECT ref, ref_rewarded FROM mp_orders WHERE order_no=?",
                       (order_no,)).fetchone()
    if not row or not row[0] or row[1]:
        conn.close()
        return
    referrer = conn.execute("SELECT order_no, free_quota FROM mp_orders WHERE share_token=?",
                            (row[0],)).fetchone()
    if referrer and referrer[0] != order_no:
        conn.execute("UPDATE mp_orders SET free_quota=? WHERE order_no=?",
                     ((referrer[1] or 20) + 1, referrer[0]))
        log(f"裂变奖励：{order_no} 首次生成成功，邀请人 {referrer[0]} +1 张免费额度")
    conn.execute("UPDATE mp_orders SET ref_rewarded=1 WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()


def fail_job(job_id: int, err: str) -> None:
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='failed', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"error": err}), job_id))
    conn.commit()
    conn.close()


def main() -> None:
    if not _ark_channels():
        log("缺生图通道密钥（IFOCUS_API_KEY / ARK_API_KEY），退出")
        sys.exit(1)
    log("mp_worker 启动")
    while True:
        try:
            conn = db()
            rows = list(conn.execute(
                "SELECT id, order_no, kind, payload_json FROM mp_jobs WHERE status='queued' ORDER BY id LIMIT 3"))
            conn.close()
            for job_id, order_no, kind, payload_json in rows:
                conn = db()
                conn.execute("UPDATE mp_jobs SET status='running', updated_at=datetime('now') WHERE id=?", (job_id,))
                conn.commit()
                conn.close()
                try:
                    run_job(job_id, order_no, kind, json.loads(payload_json))
                    _push_chat_event(order_no, kind)  # 完成事件 → chat_agent 观察闭环
                except Exception as e:
                    log(f"job#{job_id} 失败：{e}")
                    fail_job(job_id, str(e)[:500])
        except Exception as e:
            log(f"轮询异常：{e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
