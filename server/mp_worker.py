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


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def db() -> sqlite3.Connection:
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
        m = re.search(r"\{[\s\S]*\}", out)
        if m:
            return json.loads(m.group(0))
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
    variant_ids = [v for v in series.get("variants", []) if v in tpl_map]
    if not variant_ids:
        raise RuntimeError(f"系列 {series_id} 没有可用模板")
    # 锚点规则与 template_photo 一致：定妆照优先，缺省回退原始上传照片
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
        "只替换人物的五官与面部特征，真实人体比例约7.5头身，与场景自然融合有投影，"
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


def _face_sheet_refs(order_no: str, roles: list[str]) -> list[Path]:
    """收集各成员的人脸三视图（存在的才给）。"""
    refs = []
    for role in roles:
        f = _latest_face_sheet(order_no, role)
        if f:
            refs.append(f)
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
FACE_SHEET_ANCHOR = ("随附的人脸三视图（正/左/右侧脸部特写）是人物五官的权威参考："
                     "人物的侧脸鼻梁高度、下颌线、耳朵形状严格按三视图还原，不要美化成标准模板脸")


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
    lock = "保持与参考图人物五官、脸型完全一致，无文字无水印，摄影级质感"
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
    result = None
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
    elif kind == "duo_photo":
        # 双人合照：参考图里的两个人（两张单人照或一张现成合照）生成一张亲密合照
        keys = (payload.get("photos") or [])[:2]
        if not keys:
            raise RuntimeError("合照任务缺人物照片")
        photos = [oss_get(k, TMP / f"{order_no}_duo_{i}.jpg") for i, k in enumerate(keys)]
        note = str(payload.get("note") or "").strip()
        # 人脸三视图注入（反馈 #26 侧脸不像）
        face_refs = _face_sheet_refs(order_no, ["A", "B"])
        photos += face_refs
        prompt = (
            "参考图是要合在一起拍摄的两个人（可能一张照片一个人，也可能一张里已有两人）。"
            "生成一张这两个人的亲密合照：两人的五官与参考图人物一一对应保持一致，"
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
            "只替换人物的五官与面部特征，真实人体比例约7.5头身，与场景自然融合有投影，"
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
        if payload.get("anchor_key_b") and not payload.get("anchor_key"):
            photos = _anchor_or_photos_b(order_no, payload, job_id)
        else:
            photos = _anchor_or_photos(order_no, payload, job_id)
        extra, scene_txt = asset_refs(payload)
        photos += extra
        prompt = build_photo_prompt(payload, scene_txt)
    else:
        # 婚纱照：新娘/新郎双锚点 + 服装/场景视觉参考，脸和氛围都锁住
        bride = _anchor_or_photos(order_no, payload, job_id)
        groom = _anchor_or_photos_b(order_no, payload, job_id)
        photos = (bride[:1] + groom[:2]) if bride else groom
        extra, scene_txt = asset_refs(payload)
        photos += extra
        prompt = build_photo_prompt(payload, scene_txt)
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
    key = f"results/{order_no}/{uuid.uuid4().hex[:8]}.jpg"
    url = oss_put_url(key, result, "image/jpeg")
    conn = db()
    conn.execute("UPDATE mp_jobs SET status='done', result_json=?, updated_at=datetime('now') WHERE id=?",
                 (json.dumps({"url": url, "oss_key": key}), job_id))
    conn.execute("UPDATE mp_orders SET status='done', updated_at=datetime('now') WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()
    log(f"job#{job_id} 完成 -> {key}")


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
                except Exception as e:
                    log(f"job#{job_id} 失败：{e}")
                    fail_job(job_id, str(e)[:500])
        except Exception as e:
            log(f"轮询异常：{e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
