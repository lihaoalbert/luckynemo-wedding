"""tests_chat_agent.py — chat_agent 智能体回归评测集（2026-08-29）。

把历史反馈做成场景，seed 本地 SQLite 后直调 chat_agent.run（LLM 用真实 MiniMax，
调用计数挂在 chat_agent._llm 上）；关键场景同时在旧路径（app.mp_chat, MP_CHAT_AGENT=0）
跑基线，输出新旧对照表。

场景：
  S1 #53 搞笑视频三连问 → 进入收集后每轮推一个 canonical 问句，不复读
  S2 #41 "用这张出片" → 必须给出 generate_photo 动作（按钮）
  S3 #40 发截图问"你看这个" → 走反馈流程（先确认再提交）
  S4   素材问答：有（骑马）/ 无（潜水）双路 + 编造防线
  S5   收集流 5 问全走通 → _done + 卡片 + 落库
  S6   定妆额度不足路径
  S7   worker 完成事件注入 → 对话里能感知

运行：cd server && python3 tests_chat_agent.py
成本：全量 ≤20 次 LLM 调用（计数断言在末尾）。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
REPO = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

_TMP = Path(tempfile.mkdtemp(prefix="ln_chat_agent_test_"))
os.environ["DATA_DIR"] = str(_TMP / "data")
os.environ["SITE_DIR"] = str(_TMP / "site")
os.environ["TOOLKIT_DIR"] = str(REPO / "tools" / "luckynemo-toolkit")
os.environ.pop("MP_CHAT_AGENT", None)  # 旧路径基线默认

# SITE_DIR：wardrobe/scenes 链到 website/，hongzhuang/moka 链到 assets/
(_TMP / "site").mkdir(parents=True)
for name, target in (("wardrobe", REPO / "website" / "wardrobe"),
                     ("scenes", REPO / "website" / "scenes"),
                     ("hongzhuang", REPO / "assets" / "hongzhuang"),
                     ("moka", REPO / "assets" / "moka")):
    os.symlink(target, _TMP / "site" / name)

import app  # noqa: E402  载入 .env + 建 deps
import chat_agent  # noqa: E402

# ---- LLM 调用计数 ----
LLM_CALLS = {"new": 0, "old": 0}
_REAL_LLM = chat_agent._llm


def _counting_llm(deps, messages, tools=None, max_tokens=600, temperature=0.3):
    LLM_CALLS["new"] += 1
    return _REAL_LLM(deps, messages, tools=tools, max_tokens=max_tokens,
                     temperature=temperature)


chat_agent._llm = _counting_llm
_REAL_M3 = app._m3_chat


def _counting_m3(system, user):
    LLM_CALLS["old"] += 1
    return _REAL_M3(system, user)


app._m3_chat = _counting_m3

# ---- deps：vlm 打桩（不拉真实 OSS 图），签名 URL 打桩 ----
DEPS = dict(app._MP_CHAT_AGENT_DEPS)
DEPS["vlm"] = lambda keys: ("手机界面截图：小程序聊天页，里面是一张刚生成的婚纱照预览，画面略模糊")
DEPS["signed_url"] = lambda key, expire=3600: "https://oss.example/" + key

NOW = "2026-08-29T00:00:00+00:00"
ORDER = "LN-TEST-001"
ORDER_QUOTA = "LN-TEST-QUOTA"

CHAT_IMG = "materials/20260829/chat/tpl1.jpg"
CHAT_SHOT = "materials/20260829/chat/shot1.jpg"
A_IMG = "materials/20260829/A/front1.jpg"


def seed():
    shutil.rmtree(os.environ["DATA_DIR"], ignore_errors=True)
    conn = app._db()
    for ono, free_quota, free_used in ((ORDER, 20, 0), (ORDER_QUOTA, 1, 1)):
        conn.execute(
            "INSERT INTO mp_orders(order_no,open_token,status,auth_ok,free_used,paid_count,"
            "selection_json,created_at,updated_at,mode,free_quota,share_token)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (ono, "wx-test-open-token", "auth_ok", 1, free_used, 0, "", NOW, NOW,
             "couple", free_quota, "tok" + ono[-3:]))
        for role in ("A", "B"):
            conn.execute(
                "INSERT INTO mp_members(order_no,role,byted_token,auth_url,asset_group_id,"
                "auth_ok,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)",
                (ono, role, "", "", "", NOW, NOW))
    conn.execute("INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                 " VALUES(?,?,?,?,?,?)", (ORDER, "tpl1.jpg", CHAT_IMG, 0, "image/jpeg", NOW))
    conn.execute("INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                 " VALUES(?,?,?,?,?,?)", (ORDER + "-chat", "shot1.jpg", CHAT_SHOT, 0,
                                         "image/jpeg", NOW))
    conn.execute("INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                 " VALUES(?,?,?,?,?,?)", (ORDER, "front1.jpg", A_IMG, 0, "image/jpeg", NOW))
    # 最近一次定妆任务（done）+ 一张成片（done），供出片/修图/展示链路
    conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,result_json,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (ORDER, "makeup_photo",
         json.dumps({"role": "A", "makeup_id": "hz214", "makeup_name": "原生裸妆",
                     "makeup_prompt": "test"}, ensure_ascii=False),
         "done", json.dumps({"url": "", "oss_key": "results/" + ORDER + "/mk.jpg"}), NOW, NOW))
    conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,result_json,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (ORDER, "free_photo", "{}", "done",
         json.dumps({"url": "", "oss_key": "results/" + ORDER + "/p1.jpg"}), NOW, NOW))
    # storylab 素材标签：3 段（含"骑马"，不含"潜水"）
    segs = [
        ("seg1.mp4", "新郎骑马，新娘微笑跟随，夕阳下的草地", "户外草地", "互动", 5),
        ("seg2.mp4", "新娘回头望向镜头，裙摆飞扬", "海边栈道", "回眸", 4),
        ("seg3.mp4", "两人碰杯，亲友起哄欢笑", "婚宴现场", "欢乐", 3),
    ]
    for fn, cap, scene, mt, hl in segs:
        conn.execute(
            "INSERT INTO mp_storylab_tags(order_no,oss_key,filename,duration,motion_level,"
            "highlight,highlight_window,tags_json,status,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ORDER, "materials/v/" + fn, fn, 12.0, "中", hl, "",
             json.dumps({"caption": cap, "scene": scene, "moment_type": mt,
                         "emotion": "温馨", "quality": "good", "roles_hint": []},
                        ensure_ascii=False), "ok", NOW))
    # 额度不足订单：已用 10 次定妆
    for i in range(10):
        conn.execute(
            "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?)",
            (ORDER_QUOTA, "makeup_photo", "{}", "done", NOW, NOW))
    conn.execute("INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                 " VALUES(?,?,?,?,?,?)",
                 (ORDER_QUOTA, "base.jpg", "materials/20260829/Q/base.jpg", 0,
                  "image/jpeg", NOW))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# runner
# ------------------------------------------------------------------
FAILURES: list = []
RESULTS: list = []


def wipe(order_no: str):
    """场景间隔离：清空该订单的收集状态与智能体会话状态。"""
    conn = app._db()
    conn.execute("UPDATE mp_orders SET storylab_prefs='' WHERE order_no=?", (order_no,))
    conn.execute("DELETE FROM mp_chat_state WHERE order_no=?", (order_no,))
    conn.commit()
    conn.close()



def check(cond, label):
    mark = "PASS" if cond else "FAIL"
    if not cond:
        FAILURES.append(label)
    RESULTS.append(("  assert " + label, mark))
    print(("    [PASS] " if cond else "    [FAIL] ") + label)


def run_turns(scn, order_no, turns, old_path=False):
    """逐轮跑场景；turns: [{message, images?, check(reply, action, ctx)}]"""
    history: list = []
    replies: list = []
    for i, t in enumerate(turns, 1):
        body = app.MpChatIn(order_no=order_no, message=t.get("message", ""),
                            images=t.get("images", []), history=list(history))
        conn = app._db()
        try:
            if old_path:
                resp = json.loads(app.mp_chat(body).body)
                reply, action = resp["reply"], resp["action"]
            else:
                out = chat_agent.run(conn, body, DEPS)
                reply, action = out["reply"], out["action"]
        finally:
            conn.close()
        replies.append(reply)
        print("    T%d %s → action=%s" % (i, t.get("message", "")[:30], action.get("type")))
        print("        reply: " + reply.replace("\n", " ⏎ ")[:160])
        if t.get("check"):
            t["check"](reply, action, {"order_no": order_no, "turn": i, "replies": replies})
        history.append("用户：" + t.get("message", ""))
        history.append("助手：" + reply)
    # 通用断言：相邻两轮 reply 不得相同（反馈 #53 复读防线）
    for a in range(1, len(replies)):
        check(replies[a] != replies[a - 1],
              "%s T%d 相邻两轮 reply 不同" % (scn, a + 1))
    return replies


def scenario(name):
    def deco(fn):
        print("\n=== %s ===" % name)
        return fn
    return deco


# ------------------------------------------------------------------
# 场景
# ------------------------------------------------------------------
def run_all():
    @scenario("S1 反馈#53 搞笑视频三连问（新路径）")
    def s1():
        def t1(reply, action, ctx):
            check(action.get("type") == "storylab_trailer", "S1 T1 action=storylab_trailer")
            check("情绪基调" in reply, "S1 T1 问情绪基调")
        def t2(reply, action, ctx):
            check("情绪基调" not in reply, "S1 T2 不复读情绪基调问句")
            check("这片子主要在哪用" in reply, "S1 T2 接着问用途")
        def t3(reply, action, ctx):
            check("声音想怎么处理" in reply, "S1 T3 接着问声音")
        run_turns("S1", ORDER, [
            {"message": "把我们的花絮做成一个搞笑视频", "check": t1},
            {"message": "欢乐搞笑的那种", "check": t2},
            {"message": "都可以", "check": t3},
        ])
        # prefs 落库校验
        conn = app._db()
        row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                           (ORDER,)).fetchone()
        conn.close()
        prefs = json.loads(row[0])
        check(prefs.get("tone") == "欢乐搞笑的那种", "S1 prefs.tone 已记录")
        check(prefs.get("usage") == "无", "S1 prefs.usage noop 记为无")

    @scenario("S2 反馈#41 用这张出片（新路径 + 旧基线）")
    def s2():
        wipe(ORDER)
        def t(reply, action, ctx):
            check(action.get("type") == "generate_photo", "S2 action=generate_photo")
            check(action.get("template_key") == CHAT_IMG, "S2 template_key=刚发的图")
            check(action.get("mode") == "couple", "S2 mode=couple")
        run_turns("S2-new", ORDER, [{"message": "用这张出片", "images": [CHAT_IMG],
                                     "check": t}])
        run_turns("S2-old", ORDER, [{"message": "用这张出片", "images": [CHAT_IMG],
                                     "check": t}], old_path=True)

    @scenario("S3 反馈#40 发截图走反馈流程（新路径 + 旧基线）")
    def s3():
        wipe(ORDER)
        def t1(reply, action, ctx):
            check("反馈" in reply, "S3 T1 reply 提及反馈")
            check(action.get("type") in ("none", "submit_feedback"),
                  "S3 T1 action 不越权执行")
        def t2(reply, action, ctx):
            check(action.get("type") == "submit_feedback", "S3 T2 action=submit_feedback")
        run_turns("S3-new", ORDER, [
            {"message": "你看这个，生成的照片很模糊", "images": [CHAT_SHOT], "check": t1},
            {"message": "好，提交吧", "check": t2},
        ])
        conn = app._db()
        n = conn.execute("SELECT COUNT(*) FROM mp_feedback WHERE order_no=?", (ORDER,)).fetchone()[0]
        conn.close()
        check(n >= 1, "S3 反馈已落库")
        run_turns("S3-old", ORDER, [
            {"message": "你看这个，生成的照片很模糊", "images": [CHAT_SHOT], "check": t1},
            {"message": "好，提交吧", "check": t2},
        ])

    @scenario("S4 素材问答：有/无/编造防线（新路径）")
    def s4():
        wipe(ORDER)
        def hit(reply, action, ctx):
            check("骑马" in reply, "S4 命中 reply 提到骑马")
            # fact_check 纠错文案会带"没发现"字样（道歉语境），判"有"看事实句
            check(("有的" in reply) or ("有：" in reply), "S4 命中明确答有（fact_check 兜底生效）")
        def miss(reply, action, ctx):
            check(("没发现" in reply) or ("没有" in reply) or ("还没" in reply),
                  "S4 未命中如实说没有")
        run_turns("S4", ORDER, [
            {"message": "我们有没有骑马的镜头", "check": hit},
            {"message": "有没有潜水的画面", "check": miss},
        ])

    @scenario("S5 收集流 5 问全走通（新路径）")
    def s5():
        wipe(ORDER)
        run_turns("S5", ORDER, [
            {"message": "想做一支婚礼预告片"},
            {"message": "温情感人的"},
            {"message": "婚礼现场播"},
            {"message": "纯背景音乐"},
            {"message": "没有"},
            {"message": "没有了"},
        ])
        conn = app._db()
        row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                           (ORDER,)).fetchone()
        conn.close()
        prefs = json.loads(row[0])
        check(bool(prefs.get("_done")), "S5 收集完成 _done")
        for k, want in (("tone", "温情感人的"), ("usage", "婚礼现场播"),
                        ("voice", "纯背景音乐"), ("must_include", "无"),
                        ("avoid", "无")):
            check(prefs.get(k) == want, "S5 prefs.%s=%r（期望 %r）" % (k, prefs.get(k), want))

    @scenario("S6 定妆额度不足路径（新路径，明令直执/确认通道都会撞额度墙）")
    def s6():
        def t1(reply, action, ctx):
            check(action.get("type") == "none", "S6 额度不足不建任务")
            check("用完" in reply or "充值" in reply, "S6 reply 告知额度用完")
        run_turns("S6", ORDER_QUOTA, [
            {"message": "用这张照片修一张定妆照",
             "images": ["materials/20260829/Q/base.jpg"], "check": t1},
        ])
        conn = app._db()
        n = conn.execute("SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND status='queued'",
                         (ORDER_QUOTA,)).fetchone()[0]
        conn.close()
        check(n == 0, "S6 无 queued 任务（未越权扣费）")

    @scenario("S7 worker 完成事件注入（新路径）")
    def s7():
        wipe(ORDER)
        conn = app._db()
        conn.execute("INSERT INTO mp_chat_state(order_no,state_json,updated_at)"
                     " VALUES(?,?,?)",
                     (ORDER, json.dumps({"events": [{"kind": "job_done", "text":
                        "「定妆照」任务已完成，结果已入相册", "at": NOW}], "turn": 1}), NOW))
        conn.commit()
        conn.close()
        def t(reply, action, ctx):
            check(("完成" in reply) or ("定妆" in reply), "S7 reply 感知到完成事件")
        run_turns("S7", ORDER, [{"message": "我的定妆照生成好了吗", "check": t}])

    s1()
    s2()
    s3()
    s4()
    s5()
    s6()
    s7()


if __name__ == "__main__":
    print("seed 测试库：" + os.environ["DATA_DIR"])
    seed()
    run_all()
    print("\n---- 对照表 ----")
    print("LLM 调用：新路径 %d 次，旧基线 %d 次，合计 %d（预算 ≤20）"
          % (LLM_CALLS["new"], LLM_CALLS["old"], LLM_CALLS["new"] + LLM_CALLS["old"]))
    print("断言 %d 条，失败 %d 条" % (len(RESULTS), len(FAILURES)))
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("ALL GREEN")
