"""chat_agent.py — 小程序 chat 智能体架构（2026-08-29，A 档地基 + B 档工具化）。

替代 app.mp_chat 的单轮「M3 意图路由 + 服务端 if-elif」模式：
- 会话状态 mp_chat_state（goal/stage/slots/pending_confirm/facts/events/turn），跨轮存活；
- ≤4 轮 agent 循环：LLM 原生 function calling 决策 → 确定性工具执行 → observation 回注；
- 副作用类工具（生成/删除/反馈）走 propose→确认 通道：LLM 只能提案，服务端预检后
  立即执行（用户明令）或写入 pending_confirm 等下轮确认（推测意图）；
- storylab 预告片偏好收集为服务端确定性状态机（平移旧 mp_chat 尾块，反馈 #53 终案），
  canonical 问句与 start5/bare_yes/noop5/cancel5/_done/_paused 语义等价保留；
- worker 完成钩子（mp_worker._push_chat_event）把 job 完成事件追加进 state.events，
  本轮注入 system prompt 后消费即清——观察闭环。

接线：app.mp_chat 开头 `MP_CHAT_AGENT=1` 时走本模块，否则旧路径原样保留。
依赖全部经 deps dict 注入（app.py 组装），本模块不 import app，避免循环依赖。

工具协议：MiniMax abab6.5s-chat 原生 function calling 已实测支持（2026-08-29 探测：
带 tools 参数返回标准 tool_calls；role="tool" + tool_call_id 回传后可正常收尾），
故主协议用原生 tool_calls；若响应退化为纯文本 JSON（{"tool":...} 协议）也能解析兜底。
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any

log = logging.getLogger("luckynemo.chat_agent")

# ------------------------------------------------------------------
# 会话状态
# ------------------------------------------------------------------
DEFAULT_STATE: dict = {"goal": None, "stage": "open", "slots": {},
                       "pending_confirm": None, "facts": {}, "events": [], "turn": 0}

MAX_ROUNDS = 4
MAX_EVENTS = 10


def load_state(conn, order_no: str) -> dict:
    row = conn.execute("SELECT state_json FROM mp_chat_state WHERE order_no=?",
                       (order_no,)).fetchone()
    if row and row[0]:
        try:
            state = json.loads(row[0])
            if isinstance(state, dict):
                out = dict(DEFAULT_STATE)
                out.update(state)
                return out
        except Exception:  # noqa: BLE001 - 状态损坏按新会话处理
            log.warning("mp_chat_state 损坏 order_no=%s，重置", order_no)
    return dict(DEFAULT_STATE)


def save_state(conn, order_no: str, state: dict) -> None:
    from datetime import datetime, timezone
    state["events"] = (state.get("events") or [])[-MAX_EVENTS:]
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO mp_chat_state(order_no,state_json,updated_at) VALUES(?,?,?)"
        " ON CONFLICT(order_no) DO UPDATE SET state_json=excluded.state_json,"
        " updated_at=excluded.updated_at",
        (order_no, json.dumps(state, ensure_ascii=False), now))
    conn.commit()


# ------------------------------------------------------------------
# storylab 预告片偏好收集状态机（平移 app.mp_chat 服务端驱动版，反馈 #53 终案）
# canonical 问句/语义与旧实现等价；_paused 在旧代码中写入但从未被读取（cancel 不生效），
# 本实现补上读取——这是有意修正：cancel5 的语义就是暂停，旧行为视为缺陷。
# ------------------------------------------------------------------
PREF_KEYS5 = ("tone", "usage", "voice", "must_include", "avoid")
_STORYLAB_CANON_ASK = {
    "tone": "想要什么情绪基调？比如：温情感人 / 欢乐搞笑 / 高级电影感",
    "usage": "这片子主要在哪用？自己留念 / 发朋友圈 / 婚礼现场播",
    "voice": "声音想怎么处理？保留现场原声 / 纯背景音乐 / 加一段旁白",
    "must_include": "有没有一定要出现的画面或瞬间？（比如某个场景、某句话）",
    "avoid": "有没有不想出现的内容？（比如宾客正脸、某段画面；没有就说没有）",
}
_STORYLAB_ASK_MARK = {
    "tone": "情绪基调", "usage": "这片子主要在哪用", "voice": "声音想怎么处理",
    "must_include": "一定要出现的画面", "avoid": "不想出现的内容",
}
_BARE_YES = ("是的", "对", "嗯", "好", "好呀", "好的", "可以", "嗯嗯", "要", "想做")
_NOOP5 = ("没有", "没", "无", "没有啦", "木有", "都可以", "随便", "没啥", "没有了", "你定")
_CANCEL5 = ("算了", "不用了", "不想做了", "先不做", "以后再说", "取消", "先这样")
_DECLINE = ("不要", "不用", "先不", "别", "没有", "没", "不")
_YES_ALL = _BARE_YES + ("确认", "没问题", "行", "行啊", "好哒", "嗯好", "好滴", "ok", "OK")
_VID_RE = re.compile(r"(做|出|剪|弄|搞|生成|拍).{0,8}(视频|片子|短片|预告片|微电影)"
                     r"|(视频|片子|短片|预告片|微电影).{0,8}(做|出|剪|弄|搞|生成)")
_PREFS_CARD_IMG = "https://luckynemo.ibi.ren/moka/templates/mk005.png"


def _is_yes(msg: str) -> bool:
    if msg in _YES_ALL:
        return True
    return len(msg) <= 8 and any(
        msg.startswith(w) for w in ("好", "嗯", "是的", "对", "可以", "确认", "提交", "行"))


#: 收集中纯答案的速记通道：短答案直接走确定性状态机，不烧 LLM 调用（可见行为等价）
_PLAIN_ANSWER_RE = re.compile(r"^[一-鿿A-Za-z0-9，。、！!？?～~ /\-\.]{1,20}$")
_FAST_PATH_BLOCK = ("看", "图", "片", "生成", "出片", "删掉", "删", "上传", "传",
                    "额度", "钱", "卡", "？", "?", "视频", "素材", "多少",
                    "模板", "妆", "反馈", "头像", "像")


def _is_decline(msg: str) -> bool:
    return any(msg.startswith(w) for w in _DECLINE) or msg in _CANCEL5


def _collection_step(conn, order_no: str, message: str, atype: str, deps) -> dict | None:
    """确定性收集步：返回 {"reply","action"} 覆盖 agent 输出；None 表示不介入。

    与旧 mp_chat 尾块等价：仅在最终 action 为 none/storylab_trailer 时接管（开始/续问），
    或消息命中视频意图且未开始（或已暂停）时启动。用户消息默认记为当前缺失项的答案
    （bare_yes 不记，noop 记"无"）。"""
    row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                       (order_no,)).fetchone()
    started = bool(row and row[0])  # 非空串即已进入收集（哪怕还是 {}）
    prefs = json.loads(row[0]) if started else {}
    done = bool(prefs.get("_done"))
    paused = bool(prefs.get("_paused"))
    missing = [k for k in PREF_KEYS5 if not prefs.get(k)]
    msg = (message or "").strip()
    bare_yes = msg in _BARE_YES
    noop = msg in _NOOP5
    cancel = msg in _CANCEL5
    start = bool(_VID_RE.search(msg)) and (not started or paused)
    touch = deps["touch"]
    if done:
        return None  # 收集已完结，交回正常对话
    if cancel and started and not paused:
        prefs["_paused"] = 1
        touch(conn, order_no, storylab_prefs=json.dumps(prefs, ensure_ascii=False))
        return {"reply": "好，先帮你记着，想做的时候随时跟我说～",
                "action": {"type": "none"}, "clear_pending": True}
    if start:
        prefs.pop("_paused", None)
        # 启动即落库（started=True），后续答案才有记录落点——等价旧链路里
        # M3 storylab_trailer 动作合并 fields 先落库、状态机再接管引导的作用
        touch(conn, order_no, storylab_prefs=json.dumps(prefs, ensure_ascii=False))
    if start or (started and not paused and missing
                 and atype in ("none", "storylab_trailer")):
        if not bare_yes and msg and not start and missing:
            prefs[missing[0]] = "无" if noop else msg[:200]
            touch(conn, order_no, storylab_prefs=json.dumps(prefs, ensure_ascii=False))
            missing = [k for k in PREF_KEYS5 if not prefs.get(k)]
        action = {"type": "storylab_trailer", "fields": dict(prefs), "missing": missing}
        if missing:
            head = ("好呀，我们可以一起把素材做成一支短片～" if (start or not prefs)
                    else "记下了～")
            return {"reply": head + _STORYLAB_CANON_ASK[missing[0]],
                    "action": action, "clear_pending": True}
        prefs["_done"] = 1
        touch(conn, order_no, storylab_prefs=json.dumps(prefs, ensure_ascii=False))
        action["card"] = {"img": _PREFS_CARD_IMG, "title": "预告片偏好已记录",
                          "desc": "{} · 必含：{}".format(prefs.get("tone", ""),
                                                     prefs.get("must_include", "")[:20])}
        log.info("chat_agent storylab 收单 order_no=%s prefs=%s", order_no, list(prefs))
        return {"reply": "全部记好啦 ✅ 预告片偏好已记录，生成能力即将开放，"
                         "到时候第一时间通知你。",
                "action": action, "clear_pending": True}
    return None


# ------------------------------------------------------------------
# LLM 调用（MiniMax abab6.5s-chat，原生 function calling）
# ------------------------------------------------------------------
def _llm(deps, messages: list, tools: list | None = None,
         max_tokens: int = 600, temperature: float = 0.3) -> dict:
    """调 MiniMax 对话。返回 {"content": str|None, "tool_calls": [...]}。失败抛异常。"""
    import requests
    cfg = deps["llm"]
    payload: dict = {"model": cfg.get("model", "abab6.5s-chat"),
                     "max_tokens": max_tokens, "temperature": temperature,
                     "messages": messages}
    if tools:
        payload["tools"] = tools
    r = requests.post(f"{cfg['base']}/chat/completions",
                      headers={"Authorization": "Bearer " + cfg["key"]},
                      json=payload, timeout=60)
    data = r.json()
    msg = data["choices"][0]["message"]
    return {"content": (msg.get("content") or "").strip() or None,
            "tool_calls": msg.get("tool_calls") or []}


def _parse_decision(resp: dict) -> dict | None:
    """把 LLM 响应解析成决策：{"final_reply","action"} 或 {"tool","args"}。"""
    if resp.get("tool_calls"):
        call = resp["tool_calls"][0]
        if len(resp["tool_calls"]) > 1:
            log.warning("chat_agent 多工具调用只取第一个：%d 个",
                        len(resp["tool_calls"]))
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
        except Exception:  # noqa: BLE001
            args = {}
        if not isinstance(args, dict):
            args = {}
        return {"tool": call["function"].get("name", ""), "args": args}
    text = resp.get("content") or ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text)  # 思维链剥除（防烧输出预算）
    text = re.sub(r"```(?:json)?", "", text).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        # 模型直接说人话（未按 JSON 协议）：当最终回复收编，而不是当解析失败
        if text:
            return {"final_reply": text[:600]}
        return None
    try:
        dec = json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        try:
            dec = json.JSONDecoder().raw_decode(text[m.start():])[0]
        except Exception:  # noqa: BLE001
            return None
    if not isinstance(dec, dict):
        return None
    if dec.get("tool"):
        args = dec.get("args") if isinstance(dec.get("args"), dict) else {}
        return {"tool": str(dec["tool"]), "args": args}
    if "final_reply" in dec:
        return {"final_reply": str(dec.get("final_reply") or ""), "action": dec.get("action")}
    return None


# ------------------------------------------------------------------
# 工具集
# ------------------------------------------------------------------
#: 副作用类（生成/删除/反馈）：LLM 只能提案，走 propose→确认 通道
PROPOSE_TOOLS = {"generate_photo", "edit_photo", "makeup_photo", "regenerate_makeup",
                 "duo_photo", "custom_moka", "delete_assets", "submit_feedback"}


def _spec(name: str, desc: str, props: dict, required: list | None = None) -> dict:
    return {"type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": {"type": "object", "properties": props,
                                        "required": required or []}}}


def build_tool_specs() -> list:
    return [
        _spec("get_order_state", "查看本订单当前进度摘要（模式/认证/上传数/定妆/已选/额度）。"
              "用户问“现在到哪步了/我接下来该干嘛/还有多少额度“时用。",
              {}),
        _spec("list_recent_photos", "列出相册里最近的照片/视频（OSS key，供你判断可用素材）。",
              {"kind": {"type": "string", "enum": ["image", "video", "all"]},
               "limit": {"type": "integer"}}),
        _spec("moka_list", "同款大片库清单（分组/系列/模板，精简版）。用户想挑模板、问有什么风格时用。",
              {}),
        _spec("moka_search", "按关键词搜同款大片模板（标题/系列/描述匹配）。",
              {"keyword": {"type": "string"}}, ["keyword"]),
        _spec("job_status", "最近的生成任务状态（进行中的和最近完成的）。用户问“生成好了吗/进度如何“时用。",
              {"limit": {"type": "integer"}}),
        _spec("list_results", "最近生成完成的成片（带可看的临时链接）。",
              {"limit": {"type": "integer"}}),
        _spec("material_summary", "素材理解摘要卡：把视频花絮的高光时刻做成卡片发给用户。"
              "仅当素材理解有内容时可用；用户问“素材里有什么/高光时刻“时用。",
              {}),
        _spec("material_ask", "素材问答：用户问“有没有xx镜头/拍没拍到xx“时，先调本工具检索相关片段标签，"
              "再基于返回的 caption 作答——只许依据返回内容，严禁编造。",
              {"question": {"type": "string"}}, ["question"]),
        _spec("collect_prefs", "预告片偏好收集：查当前收集状态（已开始/缺哪几项/是否完成），"
              "或登记用户刚回答的一项。视频生成需求相关时用。",
              {"key": {"type": "string", "enum": list(PREF_KEYS5)},
               "value": {"type": "string"}}),
        _spec("update_selection", "修改用户的拍摄选择（套装/场景/动作/妆容/身高备注等，只能用资产库里的值；"
              "身高是自由文本，如“新郎183cm新娘165cm“）。",
              {"fields": {"type": "object",
                          "properties": {"scenes": {"type": "array", "items": {"type": "string"}},
                                         "poses": {"type": "array", "items": {"type": "string"}},
                                         "set_id": {"type": "string"},
                                         "makeup_id": {"type": "string"},
                                         "makeup_notes": {"type": "string"},
                                         "heights": {"type": "string"}}}},
               ["fields"]),
        _spec("set_mode", "切换拍摄模式：couple=婚纱照（双人），solo=个人写真（单人）。",
              {"mode": {"type": "string", "enum": ["couple", "solo"]}}, ["mode"]),
        _spec("save_chat_images", "把用户刚发的照片保存为拍摄底图。who=me 是用户本人，partner 是伴侣"
              "（新娘/新郎/老婆/老公/对象）。用户发照片说明是谁、或说“传照片/做底图/补传“时用，"
              "严禁只回“已收到“却不保存。",
              {"who": {"type": "string", "enum": ["me", "partner"]}}, ["who"]),
        _spec("navigate_card", "给用户一张页面卡片（跳转入口，用户自己点）。页面："
              "/pages/upload/upload 上传、/pages/makeup/makeup 定妆、/pages/wardrobe/wardrobe 选服装场景、"
              "/pages/pose/pose 选动作神态。",
              {"page": {"type": "string"}}, ["page"]),
        _spec("show_result", "把最新生成好的成片/定妆照发给用户看。",
              {}),
        _spec("show_uploads", "把用户已上传的照片发给用户看。",
              {}),
        # ---- 副作用提案类（生成/删除/反馈）----
        _spec("generate_photo", "直接出片：用用户刚发的图（或最近的聊天图/专属大片）当模板 + 最新定妆照"
              "一键同款出图。用户说“用这张出片/帮我生成/用最新定妆照出一张“时用。",
              {"mode": {"type": "string", "enum": ["couple", "solo_f", "solo_m"]},
               "note": {"type": "string"},
               "confirm": {"type": "boolean",
                           "description": "true=用户是直接明令（“用这张出片“）；false=你推测的意图，需先请用户确认"}}),
        _spec("edit_photo", "修改刚生成的成片（局部修图：去眼镜/换表情/背景亮一点等），"
              "instruction 是具体修改点。改妆容/重新定妆不要用本工具。",
              {"instruction": {"type": "string"}, "confirm": {"type": "boolean"}},
              ["instruction"]),
        _spec("makeup_photo", "用用户刚发的图直接出定妆照（底图=刚发的图）。who=me/partner；"
              "makeup_id 用红妆阁目录里的值，用户没指定就用默认原图直出版。",
              {"who": {"type": "string", "enum": ["me", "partner"]},
               "makeup_id": {"type": "string"}, "note": {"type": "string"},
               "confirm": {"type": "boolean"}}),
        _spec("regenerate_makeup", "按修正指令重出定妆照（在最近定妆配方上追加要求），"
              "如“腮红淡一点“。instruction 是修正点。",
              {"instruction": {"type": "string"}, "confirm": {"type": "boolean"}},
              ["instruction"]),
        _spec("duo_photo", "双人合照：把照片里的两个人（两张单人照或一张合照）生成一张亲密合照。",
              {"note": {"type": "string"}, "confirm": {"type": "boolean"}}),
        _spec("custom_moka", "定制专属大片（DIY 模板）：用户明确说“做模板/定制专属大片“时用，"
              "description 写清用户真实需求（多轮补充合并进来，有范例图要写“参考我发的图“）。",
              {"description": {"type": "string"},
               "mode": {"type": "string", "enum": ["couple", "solo_f", "solo_m"]},
               "confirm": {"type": "boolean"}}),
        _spec("delete_assets", "删除资产：reset=全部上传+生成图并重置流程；all_uploads=只删全部上传；"
              "all_photos=只删全部生成图。不可逆，必须用户明确要求。",
              {"target": {"type": "string", "enum": ["reset", "all_uploads", "all_photos"]},
               "confirm": {"type": "boolean"}},
              ["target"]),
        _spec("submit_feedback", "提交意见反馈（用户报 bug/提功能想法，且已确认要提交）。"
              "fb_type: bug/feature/other，text 是整理后的完整描述。",
              {"fb_type": {"type": "string", "enum": ["bug", "feature", "other"]},
               "text": {"type": "string"}, "confirm": {"type": "boolean"}},
              ["text"]),
    ]


TOOL_SPECS = build_tool_specs()
TOOL_NAMES = {t["function"]["name"] for t in TOOL_SPECS}


# ------------------------------------------------------------------
# 工具执行（平移 app.mp_chat 的 if-elif 分支逻辑，行为等价）
# ------------------------------------------------------------------
def _latest_makeup_job(conn, order_no: str):
    row = conn.execute(
        "SELECT payload_json, status FROM mp_jobs WHERE order_no=? AND kind='makeup_photo'"
        " ORDER BY id DESC LIMIT 1", (order_no,)).fetchone()
    if row:
        return {"status": row[1], "payload": json.loads(row[0])}
    return None


def _order_summary(conn, order_no: str, deps) -> str:
    order = deps["get_order"](conn, order_no)
    if not order:
        return "- 订单不存在"
    photo_count = conn.execute(
        "SELECT COUNT(*) FROM uploads WHERE contact=? AND content_type LIKE 'image/%'",
        (order_no,)).fetchone()[0]
    makeup_job = _latest_makeup_job(conn, order_no)
    members = order["members"]
    if order.get("mode") == "couple":
        auth_txt = "、".join(
            "{}{}".format("创建者" if r == "A" else "伴侣",
                          "已认证" if members.get(r, {}).get("auth_ok") else "未认证")
            for r in ("A", "B"))
    else:
        auth_txt = "创建者" + ("已认证" if members.get("A", {}).get("auth_ok") else "未认证")
    lines = [
        "- 拍摄模式：{}".format(order["mode"] or "未选（couple=婚纱照，solo=个人写真）"),
        "- 认证：{}".format(auth_txt),
        "- 已上传照片：{} 张".format(photo_count),
        "- 定妆：{}".format(
            "已定妆「{}」".format(makeup_job["payload"].get("makeup_name"))
            if makeup_job and makeup_job["status"] == "done" else "未定妆"),
        "- 已选：{}".format(order["selection"] or "还没选"),
        "- 额度：免费剩 {} 张 / 付费剩 {} 张".format(
            max(0, order["free_quota"] - (order["free_used"] or 0)),
            order["paid_count"] or 0),
    ]
    return "\n".join(lines)


def _moka_index(deps) -> dict:
    try:
        p = deps["site_dir"] / "moka" / "index.json"
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _tool_get_order_state(ctx, args) -> dict:
    return {"ok": True, "summary": _order_summary(ctx["conn"], ctx["order_no"], ctx["deps"])}


def _tool_list_recent_photos(ctx, args) -> dict:
    conn, order_no = ctx["conn"], ctx["order_no"]
    kind = args.get("kind") or "all"
    limit = int(args.get("limit") or 6)
    rows = conn.execute(
        "SELECT oss_key, content_type FROM uploads WHERE contact IN (?,?,?)"
        " ORDER BY id DESC LIMIT ?", (order_no, order_no + "-B", order_no + "-chat",
                                      limit * 3)).fetchall()
    out = {"images": [], "videos": []}
    for k, ct in rows or []:
        if (ct or "").startswith("video/"):
            out["videos"].append(k)
        else:
            out["images"].append(k)
        if len(out["images"]) >= limit and len(out["videos"]) >= limit:
            break
    if kind == "image":
        out.pop("videos")
    elif kind == "video":
        out.pop("images")
    else:
        out["images"] = out["images"][:limit]
        out["videos"] = out["videos"][:limit]
    return {"ok": True, **out}


def _tool_moka_list(ctx, args) -> dict:
    data = _moka_index(ctx["deps"])
    series = [{"id": s.get("id"), "name": s.get("name", ""), "group": s.get("group", "")}
              for s in data.get("series", [])]
    groups = [{"id": g.get("id"), "name": g.get("name", "")} for g in data.get("groups", [])]
    templates = [{"id": t["id"], "title": t.get("title", ""), "mode": t.get("mode", ""),
                  "series": t.get("series", "")} for t in data.get("templates", [])]
    return {"ok": True, "groups": groups, "series": series,
            "templates": templates[:60], "total_templates": len(templates)}


def _tool_moka_search(ctx, args) -> dict:
    kw = str(args.get("keyword") or "").strip()
    data = _moka_index(ctx["deps"])
    hits = []
    for t in data.get("templates", []):
        blob = "{} {} {} {}".format(t.get("title", ""), t.get("series", ""),
                                    t.get("desc", ""), json.dumps(t.get("components", {}),
                                                                  ensure_ascii=False))
        if kw and kw in blob:
            hits.append({"id": t["id"], "title": t.get("title", ""), "mode": t.get("mode", ""),
                         "series": t.get("series", "")})
        if len(hits) >= 8:
            break
    return {"ok": True, "keyword": kw, "hits": hits}


def _tool_job_status(ctx, args) -> dict:
    rows = ctx["conn"].execute(
        "SELECT kind, status, created_at FROM mp_jobs WHERE order_no=?"
        " ORDER BY id DESC LIMIT ?", (ctx["order_no"], int(args.get("limit") or 4))).fetchall()
    return {"ok": True, "jobs": [{"kind": r[0], "status": r[1], "at": r[2]} for r in rows or []]}


def _tool_list_results(ctx, args) -> dict:
    deps = ctx["deps"]
    rows = ctx["conn"].execute(
        "SELECT kind, result_json, created_at FROM mp_jobs WHERE order_no=? AND status='done'"
        " AND kind IN ('free_photo','solo_photo','paid_photo','template_photo','makeup_photo')"
        " ORDER BY id DESC LIMIT ?", (ctx["order_no"], int(args.get("limit") or 4))).fetchall()
    photos = []
    for kind, rj, at in rows:
        res = json.loads(rj) if rj else {}
        url = deps["signed_url"](res["oss_key"], expire=86400) if res.get("oss_key") else res.get("url", "")
        if url:
            photos.append({"kind": kind, "url": url, "at": at})
    return {"ok": True, "photos": photos}


def _tool_material_summary(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    summary = deps["storylab_summary"](conn, order_no)
    if not summary:
        return {"ok": False, "reason": "本单还没有已理解的视频素材（素材理解为空）"}
    deps["state"]["facts"]["material_total"] = summary["total"]
    tops = summary["highlights"][:3]
    reply = ("我从你们的视频素材里找到了这些高光时刻：\n" +
             "\n".join("· {}（高光{}/5）".format(s["caption"], s["highlight"]) for s in tops))
    desc = "、".join(s["caption"] for s in tops if s["caption"]) or "详见逐段标签"
    action = {"type": "storylab_summary", "kind": "storylab_trailer",
              "card": {"img": _PREFS_CARD_IMG, "title": "素材摘要",
                       "desc": "{} 段已理解，高光 {}".format(summary["total"], desc)}}
    return {"ok": True, "_final": True, "final_reply": reply, "action": action}


def _tool_material_ask(ctx, args) -> dict:
    """素材问答检索：只返回命中的 caption，作答是 LLM 的事（禁编造由 fact_check 兜底）。"""
    conn, order_no = ctx["conn"], ctx["order_no"]
    q = str(args.get("question") or "")
    rows = conn.execute(
        "SELECT tags_json FROM mp_storylab_tags WHERE order_no=? AND status='ok'",
        (order_no,)).fetchall()
    if not rows:
        return {"ok": False, "reason": "本单还没有已理解的视频素材", "captions": []}
    terms = [t for t in re.split(r"[^一-鿿]+", q) if len(t) >= 2]
    caps = []
    for rj in rows:
        t = json.loads(rj[0]) if rj[0] else {}
        cap = str(t.get("caption", ""))
        blob = cap + str(t.get("scene", "")) + str(t.get("moment_type", ""))
        if not terms or any(term in blob for term in terms):
            caps.append(cap)
    return {"ok": True, "captions": caps[:10],
            "note": "只能依据以上 caption 回答；没有就是没发现，不许编造"}


def _tool_collect_prefs(ctx, args) -> dict:
    conn, order_no = ctx["conn"], ctx["order_no"]
    row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                       (order_no,)).fetchone()
    started = bool(row and row[0])
    prefs = json.loads(row[0]) if started else {}
    key, value = args.get("key"), args.get("value")
    if key in PREF_KEYS5 and isinstance(value, str) and value.strip():
        prefs[key] = value.strip()[:200]
        ctx["deps"]["log"].info("chat_agent collect_prefs LLM 写入 %s=%s", key, prefs[key])
        ctx["deps"]["touch"](conn, order_no,
                             storylab_prefs=json.dumps(prefs, ensure_ascii=False))
    missing = [k for k in PREF_KEYS5 if not prefs.get(k)]
    return {"ok": True, "started": started, "done": bool(prefs.get("_done")),
            "paused": bool(prefs.get("_paused")), "prefs": prefs, "missing": missing,
            "next_question": _STORYLAB_CANON_ASK[missing[0]] if missing else ""}


def _tool_update_selection(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    order = deps["get_order"](conn, order_no)
    fields = args.get("fields") or {}
    sel = dict(order["selection"] or {})
    assets = deps["load_assets"]()
    if isinstance(fields.get("makeup_id"), str) and fields["makeup_id"] in assets["makeup_ids"]:
        sel["makeup_id"] = fields["makeup_id"]
    if isinstance(fields.get("makeup_notes"), str) and fields["makeup_notes"].strip():
        sel["makeup_notes"] = fields["makeup_notes"].strip()[:200]
    if isinstance(fields.get("heights"), str) and fields["heights"].strip():
        sel["heights"] = fields["heights"].strip()[:100]
        ctx["state"]["facts"]["heights"] = sel["heights"]
    if isinstance(fields.get("set_id"), str) and fields["set_id"] in assets["valid_sets"]:
        sel["set_id"] = fields["set_id"]
    for key, valid in (("scenes", assets["valid_scenes"]), ("poses", assets["all_poses"])):
        if isinstance(fields.get(key), list):
            picked = [x for x in fields[key] if x in valid]
            if picked:
                sel[key] = picked
    conn.execute("UPDATE mp_orders SET selection_json=?, updated_at=? WHERE order_no=?",
                 (json.dumps(sel, ensure_ascii=False), deps["now"](), order_no))
    conn.commit()
    return {"ok": True, "silent": True,
            "action": {"type": "update_selection", "selection": sel},
            "note": "选择已更新：" + json.dumps(sel, ensure_ascii=False)[:200]}


def _tool_set_mode(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    mode = args.get("mode")
    if mode not in ("couple", "solo"):
        return {"ok": False, "reason": "mode 只能是 couple/solo"}
    deps["touch"](conn, order_no, mode=mode)
    deps["recompute_auth"](conn, order_no)
    return {"ok": True, "silent": True,
            "action": {"type": "set_mode", "mode": mode},
            "note": "拍摄模式已切换为 " + mode}


def _tool_save_chat_images(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    body = ctx["body"]
    if not body.images:
        return {"ok": False, "_final": True, "final_reply":
                "我还没收到图片哦，点输入框旁边的 📷 传一张试试～",
                "action": {"type": "none"}}
    who = args.get("who") if args.get("who") in ("me", "partner") else "me"
    contact = order_no if who == "me" else order_no + "-B"
    added = 0
    for key in body.images[:3]:
        # 去重只看目标相册（chat 上传会先在 -chat 暂存相册登记同 key，反馈 #22）
        if not conn.execute("SELECT 1 FROM uploads WHERE oss_key=? AND contact=?",
                            (key, contact)).fetchone():
            conn.execute(
                "INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (contact, key.rsplit("/", 1)[-1], key, 0, "image/jpeg", deps["now"]()))
            added += 1
    conn.commit()
    deps["log"].info("chat_agent add_base_photo order_no=%s who=%s added=%d",
                     order_no, who, added)
    suffix = "\n（已把 {} 张保存为{}拍摄底图 ✅）".format(
        added, "你的" if who == "me" else "伴侣的")
    return {"ok": True, "silent": True, "reply_suffix": suffix,
            "action": {"type": "add_base_photo", "added": added, "who": who}}


def _tool_navigate_card(ctx, args) -> dict:
    page = str(args.get("page") or "")
    allowed = ("/pages/upload/upload", "/pages/makeup/makeup",
               "/pages/wardrobe/wardrobe", "/pages/pose/pose")
    if page not in allowed:
        return {"ok": False, "reason": "未知页面，可选：" + "、".join(allowed)}
    return {"ok": True, "silent": True,
            "action": {"type": "navigate", "page": page},
            "note": "已给「" + page + "」入口卡片"}


def _tool_show_result(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    row = conn.execute(
        "SELECT result_json FROM mp_jobs WHERE order_no=? AND status='done'"
        " AND kind IN ('free_photo','solo_photo','makeup_photo') ORDER BY id DESC LIMIT 1",
        (order_no,)).fetchone()
    url = ""
    if row and row[0]:
        res = json.loads(row[0]) or {}
        url = deps["signed_url"](res["oss_key"], expire=86400) if res.get("oss_key") else res.get("url", "")
    if url:
        return {"ok": True, "silent": True,
                "action": {"type": "show_result", "photos": [url]}}
    return {"ok": False, "_final": True,
            "final_reply": "你还没有生成好的照片哦，先跟我一步步来，马上就有啦～",
            "action": {"type": "none"}}


def _tool_show_uploads(ctx, args) -> dict:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    rows = conn.execute(
        "SELECT oss_key FROM uploads WHERE contact LIKE ? AND content_type LIKE 'image/%'"
        " ORDER BY id DESC LIMIT 6", (order_no + "%",)).fetchall()
    if rows:
        return {"ok": True, "silent": True,
                "action": {"type": "show_uploads",
                           "photos": [deps["signed_url"](r[0], expire=3600) for r in rows]}}
    return {"ok": False, "_final": True,
            "final_reply": "你还没有上传照片呢，先传几张清晰的正脸照吧～",
            "action": {"type": "navigate", "page": "/pages/upload/upload"}}


READ_TOOLS = {
    "get_order_state": _tool_get_order_state,
    "list_recent_photos": _tool_list_recent_photos,
    "moka_list": _tool_moka_list,
    "moka_search": _tool_moka_search,
    "job_status": _tool_job_status,
    "list_results": _tool_list_results,
    "material_summary": _tool_material_summary,
    "material_ask": _tool_material_ask,
    "collect_prefs": _tool_collect_prefs,
}

#: LLM 绕过工具、直接按旧协议在 action 里发的类型 → 路由回工具执行
#: （等价旧路径"M3 出 action、服务端 if-elif 执行"；字段从 action 里取）
_ACTION_TOOL_ROUTE = {
    "generate_photo": ("generate_photo", ("mode", "note")),
    "edit_photo": ("edit_photo", ("instruction",)),
    "makeup_photo": ("makeup_photo", ("who", "makeup_id", "note")),
    "regenerate_makeup": ("regenerate_makeup", ("instruction",)),
    "duo_photo": ("duo_photo", ("note",)),
    "custom_moka": ("custom_moka", ("description", "mode")),
    "delete_assets": ("delete_assets", ("target",)),
    "submit_feedback": ("submit_feedback", ("fb_type", "text")),
    "navigate": ("navigate_card", ("page",)),
    "show_result": ("show_result", ()),
    "show_uploads": ("show_uploads", ()),
    "set_mode": ("set_mode", ("mode",)),
    "add_base_photo": ("save_chat_images", ("who",)),
    "update_selection": ("update_selection", ("fields",)),
}


# ------------------------------------------------------------------
# 副作用工具：预检（不写入）与执行（平移 app.mp_chat 分支）
# ------------------------------------------------------------------
def _img_keys(body) -> list:
    return [k for k in (body.images or [])
            if not k.lower().endswith((".mp4", ".mov", ".m4v", ".3gp", ".avi"))]


def _check_generate_photo(ctx, args) -> dict:
    body = ctx["body"]
    tpl = _img_keys(body)[0] if _img_keys(body) else ""
    if not tpl:
        row = ctx["conn"].execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
            " ORDER BY id DESC LIMIT 1", (ctx["order_no"] + "-chat",)).fetchone()
        tpl = row[0] if row else ""
    if not tpl:
        row = ctx["conn"].execute(
            "SELECT result_json FROM mp_jobs WHERE order_no=? AND kind='custom_moka'"
            " AND status='done' ORDER BY id DESC LIMIT 1", (ctx["order_no"],)).fetchone()
        tpl = (json.loads(row[0]) or {}).get("oss_key", "") if row and row[0] else ""
    if not tpl:
        return {"ok": False, "reason": "no_template",
                "msg": "把想做成模板的照片发给我，或先去同款大片库挑一张，我马上给你出片～"}
    return {"ok": True, "summary": "用这张照片按最新定妆照一键同款出片", "tpl": tpl}


def _exec_generate_photo(ctx, args) -> tuple:
    conn, order_no, deps, body = ctx["conn"], ctx["order_no"], ctx["deps"], ctx["body"]
    mode = args.get("mode") if args.get("mode") in ("couple", "solo_f", "solo_m") else ""
    order = deps["get_order"](conn, order_no)
    couple = mode == "couple" or (not mode and order["mode"] == "couple")
    tpl = _check_generate_photo(ctx, args).get("tpl", "")
    anchors = {}
    for pj, rj in conn.execute(
            "SELECT payload_json, result_json FROM mp_jobs WHERE order_no=?"
            " AND kind='makeup_photo' AND status='done' ORDER BY id DESC LIMIT 10",
            (order_no,)).fetchall():
        role = (json.loads(pj) or {}).get("role", "A") if pj else "A"
        if role not in anchors and rj:
            anchors[role] = (json.loads(rj) or {}).get("oss_key", "")
    action = {"type": "generate_photo", "template_key": tpl,
              "mode": "couple" if couple else "solo",
              "anchor_key": anchors.get("A", ""),
              "anchor_key_b": anchors.get("B", "") if couple else "",
              "note": str(args.get("note") or "")[:100]}
    return "", action


def _check_edit_photo(ctx, args) -> dict:
    instruction = str(args.get("instruction") or "")[:200].strip()
    if not instruction:
        return {"ok": False, "reason": "no_instruction",
                "msg": "想改哪里？告诉我具体一点，比如\"去掉眼镜\"\"背景亮一点\"～"}
    row = ctx["conn"].execute(
        "SELECT result_json FROM mp_jobs WHERE order_no=? AND status='done'"
        " AND kind IN ('free_photo','solo_photo','template_photo','edit_photo')"
        " ORDER BY id DESC LIMIT 1", (ctx["order_no"],)).fetchone()
    base_key = (json.loads(row[0]) or {}).get("oss_key", "") if row and row[0] else ""
    if not base_key:
        return {"ok": False, "reason": "no_result",
                "msg": "你还没有生成好的成片哦，先出一张再来改～"}
    return {"ok": True, "summary": "按你的要求修改刚出的成片（{}）".format(instruction[:30]),
            "base_key": base_key}


def _exec_edit_photo(ctx, args) -> tuple:
    chk = _check_edit_photo(ctx, args)
    action = {"type": "edit_photo", "base_key": chk["base_key"],
              "instruction": str(args.get("instruction") or "")[:200]}
    return "", action


def _check_makeup_photo(ctx, args) -> dict:
    if not _img_keys(ctx["body"]):
        return {"ok": False, "reason": "no_image",
                "msg": "我还没收到图片哦，点输入框旁边的 📷 传一张试试～"}
    return {"ok": True, "summary": "用你刚发的照片出一张定妆照"}


def _exec_makeup_photo(ctx, args) -> tuple:
    conn, order_no, deps, body = ctx["conn"], ctx["order_no"], ctx["deps"], ctx["body"]
    order = deps["get_order"](conn, order_no)
    who = args.get("who") if args.get("who") in ("me", "partner") else "me"
    role = "A" if who == "me" else "B"
    if not order["members"].get(role, {}).get("auth_ok"):
        return ("\n（出定妆照前，需要本人先完成真人认证哦，去「我的」页核验一下）",
                {"type": "none"})
    contact = order_no if role == "A" else order_no + "-B"
    base_key = _img_keys(body)[0]
    if not conn.execute("SELECT 1 FROM uploads WHERE oss_key=? AND contact=?",
                        (base_key, contact)).fetchone():
        conn.execute(
            "INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
            " VALUES(?,?,?,?,?,?)",
            (contact, base_key.rsplit("/", 1)[-1], base_key, 0, "image/jpeg", deps["now"]()))
    catalog = deps["load_makeup_catalog"]()
    style = next((s for s in catalog if s["id"] == args.get("makeup_id")), None)
    if not style:
        gender = "male" if args.get("gender") == "male" else "female"
        style = next(s for s in catalog
                     if s["id"] == ("hz108" if gender == "male" else "hz214"))
    makeup_count = conn.execute(
        "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='makeup_photo'",
        (order_no,)).fetchone()[0]
    action: dict = {"type": "makeup_photo", "page": "/pages/makeup/makeup"}
    if makeup_count >= 10:
        if (order["free_used"] or 0) < order["free_quota"]:
            deps["touch"](conn, order_no, free_used=(order["free_used"] or 0) + 1)
        else:
            return ("\n（免费定妆次数用完啦，充值后再继续）", {"type": "none"})
    payload = {"role": role, "makeup_id": style["id"], "makeup_name": style["name"],
               "makeup_prompt": style["prompt"],
               "gender": style.get("gender", "female"), "engine": "seedream",
               "base_key": base_key,
               "makeup_notes": str(args.get("note") or "")[:200],
               "hairstyle": "", "hairstyle_name": ""}
    conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (order_no, "makeup_photo", json.dumps(payload, ensure_ascii=False),
         "queued", deps["now"](), deps["now"]()))
    conn.commit()
    deps["log"].info("chat_agent makeup_photo order_no=%s role=%s makeup=%s",
                     order_no, role, style["id"])
    return ("\n（正在用这张照片生成「{}」定妆照，去定妆页看进度 ✅）".format(style["name"]),
            action)


def _check_regenerate_makeup(ctx, args) -> dict:
    if not _latest_makeup_job(ctx["conn"], ctx["order_no"]):
        return {"ok": False, "reason": "no_makeup",
                "msg": "", "navigate": "/pages/makeup/makeup"}
    instruction = str(args.get("instruction") or "")[:200]
    if not instruction.strip():
        return {"ok": False, "reason": "no_instruction",
                "msg": "想怎么调整？比如「腮红淡一点」「唇色换豆沙色」～"}
    return {"ok": True, "summary": "按「{}」重出定妆照".format(instruction[:30])}


def _exec_regenerate_makeup(ctx, args) -> tuple:
    conn, order_no, deps = ctx["conn"], ctx["order_no"], ctx["deps"]
    job = _latest_makeup_job(conn, order_no)
    if not job:
        return "", {"type": "navigate", "page": "/pages/makeup/makeup"}
    base = job["payload"]
    instruction = str(args.get("instruction") or "")[:200]
    new_prompt = (base.get("makeup_prompt", "") +
                  "\n追加修正要求：{}（在原配方基础上只改这一点，其余保持不变）".format(instruction))
    conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (order_no, "makeup_photo",
         json.dumps({**base, "makeup_prompt": new_prompt}, ensure_ascii=False),
         "queued", deps["now"](), deps["now"]()))
    conn.commit()
    return "", {"type": "regenerate_makeup", "page": "/pages/makeup/makeup"}


def _check_duo_photo(ctx, args) -> dict:
    images = _img_keys(ctx["body"])[:2]
    if not images:
        rows = ctx["conn"].execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
            " ORDER BY id DESC LIMIT 2", (ctx["order_no"] + "-chat",)).fetchall()
        images = [r[0] for r in rows]
    if not images:
        return {"ok": False, "reason": "no_images",
                "msg": "把你们的照片发给我（两张单人照或一张合照），我马上给你们合拍～"}
    return {"ok": True, "summary": "把照片里的两个人生成一张亲密合照", "images": images}


def _exec_duo_photo(ctx, args) -> tuple:
    images = _check_duo_photo(ctx, args).get("images", [])
    return "", {"type": "duo_photo", "images": images,
                "note": str(args.get("note") or "")[:100]}


def _check_custom_moka(ctx, args) -> dict:
    description = str(args.get("description") or ctx["body"].message or "")[:500].strip()
    if not description and not _img_keys(ctx["body"]):
        return {"ok": False, "reason": "empty",
                "msg": "描述一下你想要的画面，或者发一张喜欢的样片给我，就能定制啦～"}
    count = ctx["conn"].execute(
        "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='custom_moka'",
        (ctx["order_no"],)).fetchone()[0]
    if count >= 3:
        return {"ok": False, "reason": "quota",
                "msg": "这张单的免费定制次数（3 次）用完啦，去同款大片库挑一张现成的也很出片哦～"}
    return {"ok": True, "summary": "按你的描述定制一张专属大片", "description": description}


def _exec_custom_moka(ctx, args) -> tuple:
    conn, order_no, deps, body = ctx["conn"], ctx["order_no"], ctx["deps"], ctx["body"]
    order = deps["get_order"](conn, order_no)
    chk = _check_custom_moka(ctx, args)
    description = chk.get("description", "")
    mode = args.get("mode") if args.get("mode") in ("couple", "solo_f", "solo_m") else ""
    if not mode:
        mode = "couple" if order["mode"] == "couple" else "solo_f"
    conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
        (order_no, "custom_moka",
         json.dumps({"description": description, "mode": mode,
                     "example_keys": _img_keys(body)[:1]}, ensure_ascii=False),
         "queued", deps["now"](), deps["now"]()))
    conn.commit()
    deps["log"].info("chat_agent custom_moka order_no=%s mode=%s", order_no, mode)
    return "", {"type": "custom_moka", "mode": mode}


def _check_delete_assets(ctx, args) -> dict:
    target = args.get("target", "reset")
    if target not in ("reset", "all_uploads", "all_photos"):
        target = "reset"
    return {"ok": True, "summary": "删除资产（{}）——不可逆，删完重新开始".format(target),
            "target": target}


def _exec_delete_assets(ctx, args) -> tuple:
    chk = _check_delete_assets(ctx, args)
    deleted = ctx["deps"]["delete_assets"](ctx["conn"], ctx["order_no"], chk["target"])
    return "", {"type": "delete_assets", "target": chk["target"], "deleted": deleted}


def _check_submit_feedback(ctx, args) -> dict:
    text = str(args.get("text") or ctx["body"].message or "")[:1000]
    if not text:
        return {"ok": False, "reason": "empty", "msg": "把遇到的问题或想法简单说一下，我整理好了给你确认～"}
    return {"ok": True, "summary": "提交一条意见反馈", "text": text}


def _exec_submit_feedback(ctx, args) -> tuple:
    conn, order_no, deps, body = ctx["conn"], ctx["order_no"], ctx["deps"], ctx["body"]
    fb_type = args.get("fb_type") if args.get("fb_type") in ("bug", "feature", "other") else "other"
    text = _check_submit_feedback(ctx, args).get("text", "")
    images = list((body.images or [])[:3])
    if not images:
        rows = conn.execute(
            "SELECT oss_key FROM uploads WHERE contact=? ORDER BY id DESC LIMIT 3",
            (order_no + "-chat",)).fetchall()
        images = [r[0] for r in rows]
    conn.execute(
        "INSERT INTO mp_feedback(order_no,type,text,images_json,created_at) VALUES(?,?,?,?,?)",
        (order_no, fb_type, text, json.dumps(images, ensure_ascii=False), deps["now"]()))
    conn.commit()
    deps["log"].info("chat_agent feedback order_no=%s type=%s imgs=%d",
                     order_no, fb_type, len(images))
    return "", {"type": "submit_feedback", "fb_type": fb_type}


PROPOSE_CHECK = {"generate_photo": _check_generate_photo,
                 "edit_photo": _check_edit_photo,
                 "makeup_photo": _check_makeup_photo,
                 "regenerate_makeup": _check_regenerate_makeup,
                 "duo_photo": _check_duo_photo,
                 "custom_moka": _check_custom_moka,
                 "delete_assets": _check_delete_assets,
                 "submit_feedback": _check_submit_feedback}
PROPOSE_EXEC = {"generate_photo": _exec_generate_photo,
                "edit_photo": _exec_edit_photo,
                "makeup_photo": _exec_makeup_photo,
                "regenerate_makeup": _exec_regenerate_makeup,
                "duo_photo": _exec_duo_photo,
                "custom_moka": _exec_custom_moka,
                "delete_assets": _exec_delete_assets,
                "submit_feedback": _exec_submit_feedback}

#: 预检失败时给 LLM 的替代话术（no_image/no_instruction 等场景前端需要有动作时也会用到）
CHECK_FAIL_MSG = {"no_image": "我还没收到图片哦，点输入框旁边的 📷 传一张试试～"}


# ------------------------------------------------------------------
# 人格层 system prompt
# ------------------------------------------------------------------
PERSONA_SYS = """你是「徐大恩 LuckyNemo」小程序的创作小助手，花名"小恩"。
人格：热情、具体、说人话。多用订单事实和素材标签说话（"你们的素材里有一段新郎骑马"），
不说"好的，我明白了""请问您是希望"这类正确的废话；用户着急/失望时先安抚一句再办事。
回复 ≤80 字，口语化，可以偶尔用～和 emoji。

【输出纪律】只输出一个 JSON 对象，不要 markdown 代码块，不要 <think> 思维过程。
要么输出最终回复 {"final_reply": "对用户说的话", "action": {...}}，
要么调用一个工具（需要信息时用工具查，不要编）。action 只能是工具返回里给的形态或 {"type": "none"}。

【句式纪律】同一订单内，同一个问句/客套句式不许用第二次：
"好的，我明白了""请问您是希望""还有其他需要帮助的吗"这类说过就换说法。

【按钮纪律】答应用户做的事必须落成工具调用或 action，禁止只说不做（反馈 #41）；
让用户"点下面卡片"时 action 必须带对应入口。

【不重复确认】（反馈 #53）历史里问过且用户已答过的事项禁止再问；
复述被用户肯定后的下一轮必须执行或给明确下一步，不许再抛一个确认问句。

【空确认防线】没有待确认提案时，用户只回一个「好/嗯/是的」不要凭空执行任何操作——
先问一句「好呀，是想让我做什么？」。

【执行边界】消耗额度或不可逆的操作（出片/定妆/修图/合照/定制/删除/反馈），
用户是明令（"用这张出片""帮我生成"）时工具 confirm=true 直接执行；
意图是你推测的（从图片/模糊表述）时 confirm=false，final_reply 里先请用户确认。

【few-shot 1·明令出片】
用户：用这张出片
→ 调 generate_photo(confirm=true)，final_reply："收到，这就按你的定妆照出片～"

【few-shot 2·推测意图先确认】
用户：（发了婚纱照范例）想要这样的
→ 调 custom_moka(description="参考我发的图：韩式极简婚纱照，室内纯色背景", confirm=false)，
final_reply："想做一张这种韩式极简风格的专属大片对吗？回我"好"就开工～"

【few-shot 3·多轮任务全程】
用户：帮我们把花絮剪成视频
→ 调 collect_prefs 查状态 → final_reply 按服务端给出的下一个问题问（一次只问一个）
用户：温情感人的，婚礼现场播
→ 服务端状态机会记录这两项并给下一问；你只需把问题自然地问出口
用户：没有 / 都可以
→ noop 语义照实记"无"，继续下一问，直到 5 项集齐
（收集中的问句由服务端 canonical 驱动，严禁自己改写或一次问多个）

【素材问答纪律】回答"有没有 xx 镜头"必须先调 material_ask，只依据返回的 caption 作答：
有就指出哪段，没有就如实说"我理解的片段里还没发现"，严禁编造（漏报也算编造）。

【图片消息】用户消息里会注明带了几张图，并附图片内容的客观描述（VLM 识别）。
描述是人物照片+用户说明是谁/说做底图 → save_chat_images（严禁只回"已收到"）；
描述是范例图+用户说想要这样的 → custom_moka；UI 截图+用户问"你看这个" → 走反馈流程。

【反馈流程】用户报 bug/提想法：先调 submit_feedback 之前的追问把细节问清，
整理成一句话问"我帮你把这条反馈提交给团队吗？"，用户同意（好/提交/嗯）再
submit_feedback(confirm=false→用户确认后执行)。

【状态与事件】下面给你的是本订单事实、会话状态和刚发生的事件（生成完成等）。
事件只注入一次，用户问起进度/成片时主动报喜并引导查看。"""


def build_system_prompt(conn, order_no, body, deps, state, events, storylab_text) -> str:
    parts = [PERSONA_SYS, "【订单状态】\n" + _order_summary(conn, order_no, deps)]
    facts = state.get("facts") or {}
    if facts:
        parts.append("【记住的事实】\n" + "\n".join("- {}：{}".format(k, v) for k, v in facts.items()))
    pc = state.get("pending_confirm")
    if pc:
        parts.append("【待用户确认的提案】{}：{}\n用户回「好/确认」即执行，回「算了」即取消"
                     .format(pc["tool"], pc.get("summary", "")))
    if events:
        parts.append("【刚刚发生】\n" + "\n".join("- " + str(e.get("text", "")) for e in events))
    dialog = "\n".join(list(body.history or [])[-12:]) or "（本轮刚开始）"
    parts.append("【最近对话】\n" + dialog)
    if storylab_text:
        parts.append("【素材理解】（回答素材问题只能依据这些 caption）\n" + storylab_text)
    else:
        parts.append("【素材理解】（空：本单还没有已理解的视频素材，忽略素材类话题，"
                     "用户想做片子时引导先上传视频花絮）")
    return "\n\n".join(parts)


def build_user_text(body, deps) -> str:
    """用户消息 + 图片/视频附注（图片先过 VLM 识别，反馈 #40；视频只标注不入 VLM）。"""
    text = (body.message or "").strip() or "（只发了图片，没说话）"
    video_ext = (".mp4", ".mov", ".m4v", ".3gp", ".avi")
    vids = [k for k in (body.images or []) if k.lower().endswith(video_ext)]
    imgs = [k for k in (body.images or []) if k not in vids]
    if vids:
        text += ("\n[用户同时上传了 {} 段视频，已存入相册并排队自动理解，"
                 "理解完成后可以聊素材/做片子]".format(len(vids)))
    if imgs:
        desc = deps["vlm"](imgs)
        text += "\n[用户同时发了 {} 张图片".format(len(imgs))
        if desc:
            text += "，图片内容：{}".format(desc)
        text += "]"
    return text


def _history_messages(history: list) -> list:
    out = []
    for h in list(history or [])[-12:]:
        if h.startswith("助手："):
            out.append({"role": "assistant", "content": h[len("助手："):]})
        elif h.startswith("用户："):
            out.append({"role": "user", "content": h[len("用户："):]})
    return out


# ------------------------------------------------------------------
# 主入口
# ------------------------------------------------------------------
def run(conn, body, deps) -> dict:
    """智能体对话主入口。入参同 /api/mp/chat，返回 {{"reply", "action"}}（前端协议不变）。"""
    order_no = body.order_no
    order = deps["get_order"](conn, order_no)
    if not order:
        return {"reply": "没找到这个订单哦，回到首页重新进一下试试～",
                "action": {"type": "none"}}
    state = load_state(conn, order_no)
    state["turn"] = int(state.get("turn") or 0) + 1
    events = state.get("events") or []
    if events:
        state["events"] = []  # 消费即清
    msg = (body.message or "").strip()

    # ---- 0) 待确认提案的确定性解决（省一次 LLM 调用，且不受模型波动影响） ----
    pc = state.get("pending_confirm")
    if pc:
        if _is_yes(msg):
            ctx = {"conn": conn, "order_no": order_no, "body": body, "deps": deps,
                   "state": state}
            suffix, action = PROPOSE_EXEC[pc["tool"]](ctx, pc.get("args") or {})
            state["pending_confirm"] = None
            save_state(conn, order_no, state)
            reply = "好嘞，这就帮你办～" + (suffix or "")
            return {"reply": reply, "action": action}
        if _is_decline(msg):
            state["pending_confirm"] = None
            save_state(conn, order_no, state)
            return {"reply": "好，先不弄啦，还想做什么随时跟我说～",
                    "action": {"type": "none"}}
        state["pending_confirm"] = None  # 用户改口：清掉提案，走正常理解

    # ---- 0.5) storylab 收集中：纯答案速记通道（确定性状态机，省 LLM 调用） ----
    if msg:
        row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                           (order_no,)).fetchone()
        if row and row[0]:
            _p = json.loads(row[0])
            if (not _p.get("_done") and not _p.get("_paused")
                    and _PLAIN_ANSWER_RE.match(msg)
                    and not any(w in msg for w in _FAST_PATH_BLOCK)):
                step = _collection_step(conn, order_no, msg, "none", deps)
                if step:
                    save_state(conn, order_no, state)
                    return {"reply": step["reply"], "action": step["action"]}

    # ---- 1) agent 循环（≤4 轮） ----
    storylab_summary = deps["storylab_summary"](conn, order_no)
    storylab_text = deps["storylab_summary_text"](storylab_summary) if storylab_summary else ""
    sys_prompt = build_system_prompt(conn, order_no, body, deps, state, events, storylab_text)
    # 历史只进 system prompt【最近对话】（与旧路径一致）：以 assistant 角色注入
    # 会让模型模仿自然语言回复、破坏 JSON 输出纪律（实测反馈 #53 场景踩中）。
    msgs = [{"role": "system", "content": sys_prompt}]
    msgs.append({"role": "user", "content": build_user_text(body, deps)})

    ctx = {"conn": conn, "order_no": order_no, "body": body, "deps": deps, "state": state}
    proposed: list = []
    final: dict | None = None
    silent_notes: list = []
    reply_suffixes: list = []
    pending_action: dict | None = None
    action_from_tool = False
    rounds = 0
    for rounds in range(1, MAX_ROUNDS + 1):
        try:
            resp = _llm(deps, msgs, tools=TOOL_SPECS)
        except Exception as exc:  # noqa: BLE001
            deps["log"].warning("chat_agent LLM 失败 order_no=%s: %s", order_no, exc)
            break
        dec = _parse_decision(resp)
        if dec is None:
            deps["log"].warning("chat_agent 决策解析失败 order_no=%s round=%d",
                                order_no, rounds)
            break
        if "final_reply" in dec:
            final = {"final_reply": dec.get("final_reply") or "", "action": dec.get("action")}
            break
        tool, args = dec.get("tool") or "", dec.get("args") or {}
        if tool not in TOOL_NAMES:
            msgs.append({"role": "user",
                         "content": "[系统] 未知工具 {}，请改用可用工具或输出 final_reply".format(tool)})
            continue
        if tool in PROPOSE_TOOLS:
            chk = PROPOSE_CHECK[tool](ctx, args)
            if chk.get("ok"):
                confirm = bool(args.get("confirm"))
                if confirm:
                    proposed.append((tool, {k: v for k, v in args.items() if k != "confirm"}))
                    obs = ("[预检通过] 提案「{}」将在本轮结束后立即执行，"
                           "请直接给用户最终回复").format(chk["summary"])
                else:
                    obs = ("[预检通过] 提案「{}」已登记为待确认。请 final_reply 向用户确认"
                           "（「回我好就帮你办」这种），action 给 {{\"type\":\"none\"}}").format(chk["summary"])
                    state["pending_confirm"] = {"tool": tool, "args": {k: v for k, v in args.items() if k != "confirm"},
                                                "summary": chk["summary"]}
                msgs.append({"role": "user", "content": obs})
            else:
                reason_msg = chk.get("msg") or chk.get("reason", "")
                if chk.get("navigate"):
                    final = {"final_reply": reason_msg or "先去做定妆吧～",
                             "action": {"type": "navigate", "page": chk["navigate"]}}
                    break
                final = {"final_reply": reason_msg or "这个暂时办不了，换个说法试试？",
                         "action": {"type": "none"}}
                break
            continue
        result = READ_TOOLS.get(tool) or {
            "set_mode": _tool_set_mode,
            "update_selection": _tool_update_selection,
            "save_chat_images": _tool_save_chat_images,
            "navigate_card": _tool_navigate_card,
            "show_result": _tool_show_result,
            "show_uploads": _tool_show_uploads,
        }.get(tool)
        if result is None:
            msgs.append({"role": "user", "content": "[系统] 工具 {} 不可用".format(tool)})
            continue
        result = result(ctx, args)
        if result.get("_final"):
            action_from_tool = True
            final = {"final_reply": result.get("final_reply") or "",
                     "action": result.get("action")}
            break
        if result.get("silent"):
            # 立即生效类工具：动作记账，话术仍由 LLM 组织
            action_from_tool = True
            pending_action = result.get("action")
            if result.get("reply_suffix"):
                reply_suffixes.append(result["reply_suffix"])
            if result.get("note"):
                silent_notes.append(result["note"])
            msgs.append({"role": "user", "content": "[系统] " + result.get("note", "已完成")})
            continue
        msgs.append({"role": "user",
                     "content": "[工具结果 {}] {}".format(tool, json.dumps(
                         {k: v for k, v in result.items() if k != "ok"},
                         ensure_ascii=False)[:1500])})

    if final is None:
        deps["log"].warning("chat_agent 到达轮次上限 order_no=%s rounds=%d（兜底回复）",
                            order_no, rounds)
        final = {"final_reply": _fallback_reply(conn, order_no, deps, state, events),
                 "action": pending_action or {"type": "none"}}

    reply = str(final.get("final_reply") or "").strip() or "我在呢～"
    action = final.get("action") if isinstance(final.get("action"), dict) else {"type": "none"}
    if not action.get("type"):
        action = {"type": "none"}
    if action.get("type") == "none" and pending_action is not None:
        action = pending_action

    # ---- 3) 执行 confirm=true 的提案（用户明令，本轮直接办） ----
    for tool, args in proposed:
        chk = PROPOSE_CHECK[tool](ctx, args)
        if not chk.get("ok"):
            reply += "\n" + (chk.get("msg") or "这一步没办成，稍后再试下～")
            continue
        action_from_tool = True
        suffix, action = PROPOSE_EXEC[tool](ctx, args)
        if suffix:
            reply += suffix

    # ---- 3.5) LLM 绕过工具直接发的 action → 路由回工具执行（等价旧路径） ----
    route = _ACTION_TOOL_ROUTE.get(action.get("type", ""))
    if route and not action_from_tool:
        deps["log"].info("chat_agent LLM 直发 action=%s，路由回工具执行", action.get("type"))
        tool_name, arg_keys = route
        t_args = {k: action[k] for k in arg_keys if k in action}
        if tool_name in PROPOSE_TOOLS:
            chk = PROPOSE_CHECK[tool_name](ctx, t_args)
            if chk.get("ok"):
                suffix, action = PROPOSE_EXEC[tool_name](ctx, t_args)
                if suffix:
                    reply += suffix
            elif chk.get("navigate"):
                action = {"type": "navigate", "page": chk["navigate"]}
            else:
                action = {"type": "none"}
                reply += "\n" + (chk.get("msg") or "这一步没办成，稍后再试下～")
        else:
            fn = {"set_mode": _tool_set_mode, "update_selection": _tool_update_selection,
                  "save_chat_images": _tool_save_chat_images,
                  "navigate_card": _tool_navigate_card,
                  "show_result": _tool_show_result,
                  "show_uploads": _tool_show_uploads}.get(tool_name)
            res = fn(ctx, t_args) if fn else {"ok": False}
            if res.get("_final"):
                action = res.get("action") or {"type": "none"}
                if res.get("final_reply"):
                    reply = res["final_reply"]
                if res.get("reply_suffix"):
                    reply += res["reply_suffix"]
            elif res.get("silent"):
                action = res.get("action") or {"type": "none"}
                if res.get("reply_suffix"):
                    reply += res["reply_suffix"]
            else:
                action = {"type": "none"}
                if res.get("final_reply"):
                    reply = res["final_reply"]
                elif res.get("reason"):
                    reply += "\n" + str(res["reason"])

    for s in reply_suffixes:
        if s not in reply:
            reply += s
    if state.get("pending_confirm") and ("回我" not in reply and "确认" not in reply):
        reply += "\n（确认的话回我「好」就行）"

    # ---- 4) storylab 收集状态机（确定性，等价旧 mp_chat 尾块） ----
    step = _collection_step(conn, order_no, msg, action.get("type", "none"), deps)
    if step:
        if step.get("clear_pending") and state.get("pending_confirm"):
            state["pending_confirm"] = None
        reply, action = step["reply"], step["action"]

    # ---- 5) 素材问答反编造兜底（与旧 _mp_storylab_fact_check 相同，经 deps 调用） ----
    if storylab_text:
        reply = deps["storylab_fact_check"](conn, order_no, body.message or "", reply)

    # ---- 6) 复读兜底（反馈 #53） ----
    last_ai = ""
    for h in reversed(list(body.history or [])[-12:]):
        if h.startswith("助手："):
            last_ai = h[len("助手："):].strip()
            break
    if last_ai and reply.strip() and reply.strip() == last_ai:
        deps["log"].warning("chat_agent 重复回复兜底 order_no=%s", order_no)
        reply = ("刚刚我卡壳把同一句话说重复了，抱歉～你上一条的意思我已经明白了，"
                 "我们接着往下进行，还有什么想补充的吗？")

    save_state(conn, order_no, state)
    return {"reply": reply, "action": action}


def _fallback_reply(conn, order_no, deps, state, events=None) -> str:
    """到达轮次上限的兜底（观察驱动：用已知事实组织一句诚实的推进话术）。"""
    pc = state.get("pending_confirm")
    if pc:
        return "刚刚想帮你确认一下：{}？回我「好」就帮你办～".format(pc.get("summary", ""))
    for e in (events or []):
        return "我在呢～{}。你是想看看结果，还是要继续调整？跟我说一声就行。".format(
            e.get("text", "刚有任务完成了"))
    return ("我刚刚理了一下手头的信息，有点没跟上你的节奏～简单说一句你现在最想做什么，"
            "我马上帮你安排。")
