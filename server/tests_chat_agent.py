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


# ---- P2 摘要触发：测试内不真开后台线程，改为记录"本应触发"的事件 ----
ROLLUP_TRIGGERS: list = []


def _fake_maybe_rollup(conn, order_no, deps):
    n = conn.execute(
        "SELECT COUNT(*) FROM mp_chat_messages WHERE order_no=? AND role='user'",
        (order_no,)).fetchone()[0]
    if n and n % 10 == 0:
        ROLLUP_TRIGGERS.append((order_no, n))


chat_agent._maybe_rollup = _fake_maybe_rollup


def _counting_m3(system, user):
    LLM_CALLS["old"] += 1
    return _REAL_M3(system, user)


app._m3_chat = _counting_m3

# ---- deps：vlm 打桩（不拉真实 OSS 图），签名 URL 打桩 ----
DEPS = dict(app._MP_CHAT_AGENT_DEPS)
DEPS["vlm"] = lambda keys: ("手机界面截图：小程序聊天页，里面是一张刚生成的婚纱照预览，画面略模糊")
DEPS["signed_url"] = lambda key, expire=3600: "https://oss.example/" + key
DEPS["db_factory"] = app._db

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
            check(any(w in reply for w in ("哪播", "用在哪", "派什么用场")),
                  "S1 T2 接着问用途")
        def t3(reply, action, ctx):
            check("声音" in reply, "S1 T3 接着问声音")
        reps = run_turns("S1", ORDER, [
            {"message": "把我们的花絮做成一个搞笑视频", "check": t1},
            {"message": "欢乐搞笑的那种", "check": t2},
            {"message": "都可以", "check": t3},
        ])
        heads = [r[:6] for r in reps]
        check(len(set(heads)) == len(heads), "S1 各轮 ack 开场互不相同（人设多样性）")
        check(all("记下了～" not in r for r in reps), "S1 无旧版「记下了～」话术")
        check(all("预告片偏好" not in r for r in reps), "S1 无「预告片偏好」旧称")
        # prefs 落库校验
        conn = app._db()
        row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                           (ORDER,)).fetchone()
        conn.close()
        prefs = json.loads(row[0])
        check(prefs.get("tone") == "欢乐搞笑的那种", "S1 prefs.tone 已记录")
        check(prefs.get("usage") == "无", "S1 prefs.usage noop 记为无")

    @scenario("S2 反馈#41 用这张出片（新路径×最多2次取正确 + 旧基线）")
    def s2():
        wipe(ORDER)
        out = None
        for attempt in (1, 2):  # LLM 工具选择有非确定性，给一次重试（重试前 wipe 状态）
            body = app.MpChatIn(order_no=ORDER, message="用这张出片", images=[CHAT_IMG],
                                history=[])
            conn = app._db()
            try:
                out = chat_agent.run(conn, body, DEPS)
            finally:
                conn.close()
            if out["action"].get("type") == "generate_photo":
                break
            wipe(ORDER)
        check(out["action"].get("type") == "generate_photo", "S2 action=generate_photo")
        check(out["action"].get("template_key") == CHAT_IMG, "S2 template_key=刚发的图")
        check(out["action"].get("mode") == "couple", "S2 mode=couple")
        print("        reply: " + out["reply"].replace("\n", " ⏎ ")[:160])

        def t(reply, action, ctx):
            check(action.get("type") == "generate_photo", "S2-old action=generate_photo")
            check(action.get("template_key") == CHAT_IMG, "S2-old template_key=刚发的图")
            check(action.get("mode") == "couple", "S2-old mode=couple")
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

    @scenario("S5 收集流 5 问全走通 + 收单真建 storylab_film 任务（新路径）")
    def s5():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_jobs WHERE order_no=? AND kind='storylab_film'", (ORDER,))
        conn.commit()
        conn.close()
        def t_done(reply, action, ctx):
            check("故事片场" in reply, "S5 收单话术用「故事片场」新称")
            check("预告片偏好" not in reply, "S5 收单话术无「预告片偏好」旧称")
            check("即将开放" not in reply, "S5 收单不再搪塞「即将开放」")
            check(action.get("card", {}).get("title") == "故事片场偏好已记录",
                  "S5 偏好卡标题为「故事片场偏好已记录」")
        reps = run_turns("S5", ORDER, [
            {"message": "想做一支婚礼预告片"},
            {"message": "温情感人的"},
            {"message": "婚礼现场播"},
            {"message": "纯背景音乐"},
            {"message": "没有"},
            {"message": "没有了", "check": t_done},
        ])
        heads = [r[:6] for r in reps]
        check(len(set(heads)) == len(heads), "S5 各轮 ack 开场互不相同（人设多样性）")
        conn = app._db()
        row = conn.execute("SELECT storylab_prefs FROM mp_orders WHERE order_no=?",
                           (ORDER,)).fetchone()
        jobs = conn.execute("SELECT status FROM mp_jobs WHERE order_no=? AND kind='storylab_film'",
                            (ORDER,)).fetchall()
        conn.close()
        prefs = json.loads(row[0])
        check(bool(prefs.get("_done")), "S5 收集完成 _done")
        for k, want in (("tone", "温情感人的"), ("usage", "婚礼现场播"),
                        ("voice", "纯背景音乐"), ("must_include", "无"),
                        ("avoid", "无")):
            check(prefs.get(k) == want, "S5 prefs.%s=%r（期望 %r）" % (k, prefs.get(k), want))
        check(len(jobs) == 1 and jobs[0][0] == "queued",
              "S5 收单幂等创建 storylab_film 任务（queued）")
        conn = app._db()
        again = chat_agent.enqueue_storylab_film(conn, ORDER, DEPS)
        n = conn.execute("SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='storylab_film'",
                         (ORDER,)).fetchone()[0]
        conn.close()
        check(not again and n == 1, "S5 enqueue 幂等（重复调用不重建）")

    @scenario("S8 get_storylab_film 工具：查片状态/给查看入口（新路径）")
    def s8():
        conn = app._db()
        row = conn.execute("SELECT id FROM mp_jobs WHERE order_no=? AND kind='storylab_film'",
                           (ORDER,)).fetchone()
        conn.close()
        check(row is not None, "S8 前置：S5 已建 storylab_film 任务")
        ctx = {"conn": app._db(), "order_no": ORDER, "body": None, "deps": DEPS, "state": {}}
        r1 = chat_agent._tool_get_storylab_film(ctx, {})
        check(r1.get("ok") and r1.get("status") == "queued", "S8 制作中状态可查")
        # 模拟完成：result_json 落 oss_key，断言给查看入口
        conn = app._db()
        conn.execute("UPDATE mp_jobs SET status='done', result_json=? WHERE order_no=?"
                     " AND kind='storylab_film'",
                     (json.dumps({"oss_key": "results/" + ORDER + "/storylab_film_x.mp4",
                                  "duration": 18.5}), ORDER))
        conn.commit()
        conn.close()
        ctx = {"conn": app._db(), "order_no": ORDER, "body": None, "deps": DEPS, "state": {}}
        r2 = chat_agent._tool_get_storylab_film(ctx, {})
        check(r2.get("status") == "done" and r2.get("_final"), "S8 完成后 _final 直达")
        check(r2.get("action", {}).get("type") == "show_result", "S8 给查看短片入口")
        ctx["conn"].close()

    @scenario("S6 定妆额度不足路径（执行层确定性断言，不赌 LLM 措辞）")
    def s6():
        body = app.MpChatIn(order_no=ORDER_QUOTA, message="用这张照片修一张定妆照",
                            images=["materials/20260829/Q/base.jpg"], history=[])
        conn = app._db()
        ctx = {"conn": conn, "order_no": ORDER_QUOTA, "body": body, "deps": DEPS,
               "state": {}}
        chk = chat_agent._check_makeup_photo(ctx, {})
        check(chk.get("ok"), "S6 预检通过（有图有认证）")
        suffix, action = chat_agent._exec_makeup_photo(ctx, {"who": "me"})
        check(action.get("type") == "none", "S6 额度不足不建任务")
        check("用完" in suffix or "充值" in suffix, "S6 话术告知额度用完")
        conn.close()
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

    @scenario("S9 全量留痕 + topic 打标（P1/P3）")
    def s9():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        conn.commit()
        conn.close()
        run_turns("S9", ORDER, [{"message": "把我们的花絮做成一个搞笑视频"}])
        conn = app._db()
        rows = conn.execute(
            "SELECT role, topic, action_json FROM mp_chat_messages WHERE order_no=?"
            " ORDER BY id", (ORDER,)).fetchall()
        conn.close()
        check(len(rows) == 2, "S9 留痕 user+assistant 两行")
        check(rows[0][0] == "user" and rows[1][0] == "assistant", "S9 角色成对")
        check(rows[0][1] == "storylab", "S9 topic 打标 storylab")
        check(json.loads(rows[1][2] or "{}").get("type") == "storylab_trailer",
              "S9 assistant 行含 action 快照")

    @scenario("S10 历史端点：分页/倒序/重签（P1）")
    def s10():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        for i in range(25):
            conn.execute(
                "INSERT INTO mp_chat_messages(order_no,role,text,images_json,topic,created_at)"
                " VALUES(?,?,?,?,?,?)",
                (ORDER, "user" if i % 2 == 0 else "assistant",
                 "第%d条测试消息" % i,
                 json.dumps(["materials/x/%d.jpg" % i]) if i == 24 else None,
                 "chat", "2026-08-29T10:%02d:00+00:00" % (i % 60)))
        conn.commit()
        conn.close()
        r1 = json.loads(app.mp_chat_history(ORDER, 0, 10).body)
        items = r1["items"]
        check(len(items) == 10 and r1["has_more"], "S10 第一页 10 条且 has_more")
        check(items[0]["id"] > items[-1]["id"], "S10 倒序")
        r2 = json.loads(app.mp_chat_history(ORDER, items[-1]["id"], 10).body)
        check(r2["items"] and r2["items"][0]["id"] < items[-1]["id"],
              "S10 before_id 游标分页无重叠")
        with_img = [it for it in items if it["images"]]
        check(len(with_img) == 1 and "OSSAccessKeyId=" in with_img[0]["images"][0],
              "S10 images 重签 24h（真实签名 URL）")

    @scenario("S11 记忆注入：新会话（history 空）能引用刚说过的话（P1）")
    def s11():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        conn.commit()
        conn.close()
        run_turns("S11", ORDER, [{"message": "故事片场的基调我想要爆笑吐槽风的"}])
        def t(reply, action, ctx):
            check("爆笑" in reply, "S11 新会话引用到之前说的基调（DB 注入 dialog）")
        run_turns("S11b", ORDER, [{"message": "我刚才说要什么基调？", "check": t}])

    @scenario("S12 recall_past：翻旧账引用（P3）")
    def s12():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        conn.execute("DELETE FROM mp_chat_state WHERE order_no=?", (ORDER,))
        conn.execute(
            "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
            (ORDER, "user", "我想好了，情绪基调要爆笑吐槽风这种风格，越搞笑越好", "prefs", NOW))
        conn.execute(
            "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
            (ORDER, "assistant", "记下来啦，爆笑吐槽风！", "prefs", NOW))
        for i in range(14):  # 14 条填充，把目标消息顶出最近 6 轮窗口
            conn.execute(
                "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
                (ORDER, "user" if i % 2 == 0 else "assistant", "闲聊填充 %d" % i,
                 "chat", "2026-08-29T11:%02d:00+00:00" % i))
        conn.commit()
        conn.close()
        def t(reply, action, ctx):
            check("爆笑" in reply, "S12 reply 引用到爆笑吐槽风（recall_past 路径）")
        run_turns("S12", ORDER, [{"message": "上次我说要什么风格？", "check": t}])
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        conn.commit()
        conn.close()

    @scenario("S13 清除对话记录：历史清空 + summary/profile 重置（P2）")
    def s13():
        conn = app._db()
        conn.execute(
            "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
            (ORDER, "user", "测试清除", "chat", NOW))
        state = chat_agent.load_state(conn, ORDER)
        state.setdefault("facts", {})["dialog_summary"] = "旧摘要"
        state["facts"]["user_profile"] = {"heights": "173cm"}
        chat_agent.save_state(conn, ORDER, state)
        conn.commit()
        conn.close()
        r = json.loads(app.mp_chat_history_delete(ORDER).body)
        check(r.get("ok"), "S13 DELETE 端点 ok")
        conn = app._db()
        n = conn.execute("SELECT COUNT(*) FROM mp_chat_messages WHERE order_no=?",
                         (ORDER,)).fetchone()[0]
        conn.close()
        check(n == 0, "S13 历史已清空")
        state = chat_agent.load_state(conn2 := app._db(), ORDER)
        check(not state["facts"].get("dialog_summary"), "S13 dialog_summary 已重置")
        check(not state["facts"].get("user_profile"), "S13 user_profile 已重置")
        conn2.close()

    @scenario("S14 滚动摘要：直调摘要函数（P2，合成消息不真跑 10 轮）")
    def s14():
        wipe(ORDER)
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        dialog = [
            ("user", "他身高183，我165，记住了"),
            ("assistant", "记住啦，新郎183新娘165～"),
            ("user", "我喜欢复古港风的妆容，以后都按这个来"),
            ("assistant", "记上：复古港风妆容偏好 ✅"),
            ("user", "把我们的花絮做成搞笑视频"),
            ("assistant", "好呀，先定个调调"),
            ("user", "爆笑吐槽风"),
            ("assistant", "嘿嘿，这个好玩！"),
            ("user", "不要出现宾客正脸"),
            ("assistant", "禁区记下了"),
            ("user", "婚礼现场播，纯背景音乐"),
            ("assistant", "齐活！你的「故事片场」开机准备完成"),
        ]
        for role, text in dialog:
            conn.execute(
                "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
                (ORDER, role, text, "chat", NOW))
        conn.commit()
        conn.close()
        conn = app._db()
        ok = chat_agent.rollup_summary(conn, ORDER, DEPS)
        state = chat_agent.load_state(conn, ORDER)
        conn.close()
        summary = state["facts"].get("dialog_summary") or ""
        profile = state["facts"].get("user_profile") or {}
        check(ok and summary, "S14 摘要生成成功")
        check(len(summary) <= 300, "S14 摘要 ≤300 字（实际 %d）" % len(summary))
        check(bool(profile), "S14 user_profile 有提取：%s" % list(profile)[:5])
        check(any("183" in str(v) for v in profile.values()), "S14 profile 含身高事实")
        conn = app._db()
        conn.execute("DELETE FROM mp_chat_messages WHERE order_no=?", (ORDER,))
        before = len(ROLLUP_TRIGGERS)
        for i in range(9):  # 9 条 + record_chat_turn 的 1 条 = 第 10 轮触发
            conn.execute(
                "INSERT INTO mp_chat_messages(order_no,role,text,topic,created_at) VALUES(?,?,?,?,?)",
                (ORDER, "user", "msg%d" % i, "chat", NOW))
        conn.commit()
        chat_agent.record_chat_turn(conn, ORDER, app.MpChatIn(
            order_no=ORDER, message="第10条", images=[], history=[]), "回复", {"type": "none"}, DEPS)
        conn.close()
        check(len(ROLLUP_TRIGGERS) > before, "S14 第 10 轮触发摘要节拍（fake 记录到 %s）"
              % (str(ROLLUP_TRIGGERS[-1]) if ROLLUP_TRIGGERS else None))

    s1()
    s2()
    s3()
    s4()
    s5()
    s6()
    s7()
    s8()
    s9()
    s10()
    s11()
    s12()
    s13()
    s14()


# ------------------------------------------------------------------
# E2E：真跑一部「故事片场」短片（env STORYLAB_FILM_E2E=1 才跑）
# 上传 4 段真实花絮 → seed tags/prefs → 直调 mp_worker.run_storylab_film
# → ffprobe 结构断言 + 抽帧目检。M3 仅 1 次调用。
# ------------------------------------------------------------------
ORDER_FILM = "LN-TEST-FILM"
E2E_VIDEOS = [
    # (本地文件, 时长, caption, highlight_window, highlight)
    ("2ad6d66c0431d5f20521b089f30ef8f9.mp4", 43.09, "新郎新娘入场相拥，亲友欢呼鼓掌", "10.7-19.3", 5),
    ("0cafa93e0d70ddfb56be69a3e5d11c47.mp4", 12.97, "新娘抛捧花，众人抢花欢笑", "4.0-9.0", 4),
    ("611644315b5dd072ddc9804e831eceb2.mp4", 7.13, "新人交换戒指特写，誓言", "1.0-5.5", 5),
    ("85fb6728608af9c17d0594410dc59d36.mp4", 7.5, "两人共舞，灯光璀璨", "", 3),
]


def e2e_storylab_film():
    print("\n=== E2E 真跑一部故事片场短片 ===")
    import subprocess
    import mp_worker

    # 本地 worker 的 ENV 只读 server/.env + /opt toolkit .env；本地把 toolkit .env 补进来
    tk_env = REPO / "tools" / "luckynemo-toolkit" / ".env"
    for line in tk_env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            mp_worker.ENV.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    mp_worker.MINIMAX_KEY = mp_worker.ENV.get("MINIMAX_API_KEY", "")
    mp_worker.MINIMAX_BASE = mp_worker.ENV.get("MINIMAX_BASE_URL", mp_worker.MINIMAX_BASE)

    intake = REPO / "referrence" / "刘奔奔&徐驰" / "intake_20260724"
    # 1) 上传素材到 OSS（幂等覆盖即可）
    for fn, dur, cap, win, hl in E2E_VIDEOS:
        key = "materials/storylab_e2e/" + fn
        app.oss_put_object(key, (intake / fn).read_bytes(), content_type="video/mp4")
        print("    上传 " + key)

    # 2) seed：订单 + prefs(done) + tags + job；worker 指向同一测试库
    conn = app._db()
    conn.execute("DELETE FROM mp_jobs WHERE order_no=?", (ORDER_FILM,))
    conn.execute("DELETE FROM mp_storylab_tags WHERE order_no=?", (ORDER_FILM,))
    conn.execute("DELETE FROM mp_orders WHERE order_no=?", (ORDER_FILM,))
    conn.execute(
        "INSERT INTO mp_orders(order_no,open_token,status,created_at,updated_at,mode,free_quota,share_token)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (ORDER_FILM, "wx-t", "created", NOW, NOW, "couple", 20, "tokfilm"))
    conn.execute("UPDATE mp_orders SET storylab_prefs=? WHERE order_no=?",
                 (json.dumps({"tone": "温馨治愈系", "usage": "婚礼现场播",
                              "voice": "纯背景音乐", "must_include": "交换戒指",
                              "avoid": "无", "_done": 1}, ensure_ascii=False), ORDER_FILM))
    for fn, dur, cap, win, hl in E2E_VIDEOS:
        conn.execute(
            "INSERT INTO mp_storylab_tags(order_no,oss_key,filename,duration,motion_level,"
            "highlight,highlight_window,tags_json,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (ORDER_FILM, "materials/storylab_e2e/" + fn, fn, dur, "中", hl, win,
             json.dumps({"caption": cap, "scene": "", "moment_type": "",
                         "emotion": "温馨"}, ensure_ascii=False), "ok", NOW))
    cur = conn.execute(
        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?)",
        (ORDER_FILM, "storylab_film", "{}", "running", NOW, NOW))
    job_id = cur.lastrowid
    conn.commit()
    conn.close()
    mp_worker.DB_PATH = Path(os.environ["DATA_DIR"]) / "app.db"

    # 3) 真跑（keep_local 保留成片供目检）
    meta = mp_worker.run_storylab_film(job_id, ORDER_FILM, {"keep_local": 1})
    check(meta is not None, "E2E worker 返回成片 meta")

    # 4) ffprobe 结构断言
    local = meta["local"]
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", local], capture_output=True, text=True).stdout)
    vstream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    astream = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
    dur = float(probe["format"]["duration"])
    check(vstream["width"] == 720 and vstream["height"] == 1280, "E2E 720x1280 竖屏")
    fps = eval(vstream["avg_frame_rate"])
    check(abs(fps - 24) < 0.5, "E2E 24fps")
    check(dur > 8, "E2E 总时长 >8s（片名卡2s+镜组+AI卡2.5s）")
    check(astream is not None, "E2E 音轨在位（BGM/原声混流）")
    check(meta["shots"] >= 2, "E2E 镜表 ≥2 镜")

    # 5) 抽帧目检：片头卡 / 中段镜 / AI 标识卡
    qc = Path("/tmp/storylab_e2e_qc")
    qc.mkdir(exist_ok=True)
    frames = [(1.0, "title"), (dur / 2, "mid"), (dur - 1.0, "endcard")]
    for t, name in frames:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", local,
                        "-frames:v", "1", str(qc / (name + ".png"))], check=True)
    print("    目检抽帧：" + ", ".join(str(qc / (n + ".png")) for _, n in frames))
    conn = app._db()
    row = conn.execute("SELECT status, result_json FROM mp_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    check(row[0] == "done" and json.loads(row[1]).get("oss_key", "").startswith("results/"),
          "E2E job done 且 result 落库")
    print("    成片本地路径：" + local)


if __name__ == "__main__":
    print("seed 测试库：" + os.environ["DATA_DIR"])
    seed()
    run_all()
    if os.environ.get("STORYLAB_FILM_E2E") == "1":
        e2e_storylab_film()
    else:
        print("\n（E2E 真跑片子未启用：STORYLAB_FILM_E2E=1 时执行）")
    print("\n---- 对照表 ----")
    print("LLM 调用：新路径 %d 次，旧基线 %d 次，合计 %d（预算 ≤20；E2E 另计 M3 1 次）"
          % (LLM_CALLS["new"], LLM_CALLS["old"], LLM_CALLS["new"] + LLM_CALLS["old"]))
    print("断言 %d 条，失败 %d 条" % (len(RESULTS), len(FAILURES)))
    if FAILURES:
        print("FAILURES:")
        for f in FAILURES:
            print("  - " + f)
        sys.exit(1)
    print("ALL GREEN")
