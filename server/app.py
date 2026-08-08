"""徐大恩 LuckyNemo 官网轻量后端。

功能：
- POST /api/leads          预约留资 → SQLite + 飞书订单表，返回 order_no
- POST /api/questionnaire  故事问卷 → SQLite + 飞书「故事问卷」表 + OSS 存原文
- POST /api/uploads/sign   OSS PostObject 签名（浏览器直传 ibi-private）
- GET  /api/health         健康检查

凭据全部从环境变量读（生产：/opt/luckynemo/server/.env），代码与日志不打印 secret。
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import string
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("luckynemo")

# ------------------------------------------------------------------
# 配置（.env 加载，不覆盖已有环境变量）
# ------------------------------------------------------------------
SERVER_DIR = Path(__file__).resolve().parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv(SERVER_DIR / ".env")
# 备用凭据（ARK / MiniMax）从工具箱 .env 读，不覆盖已有变量
_load_dotenv(Path(os.environ.get("TOOLKIT_DIR", "/opt/luckynemo/toolkit")) / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


OSS_AK = _env("OSS_ACCESS_KEY_ID")
OSS_SK = _env("OSS_ACCESS_KEY_SECRET")
OSS_BUCKET = _env("OSS_BUCKET", "ibi-private")
OSS_REGION = _env("OSS_REGION", "oss-cn-shanghai")
OSS_ENDPOINT = f"https://{OSS_BUCKET}.{OSS_REGION}.aliyuncs.com"

LARK_APP_ID = _env("LARK_APP_ID")
LARK_APP_SECRET = _env("LARK_APP_SECRET")
LARK_BASE_TOKEN = _env("LARK_BASE_TOKEN")
LARK_ORDER_TABLE_ID = _env("LARK_ORDER_TABLE_ID")
LARK_STORY_TABLE_ID = _env("LARK_STORY_TABLE_ID")
LARK_OPENAPI = "https://open.feishu.cn/open-apis"

DATA_DIR = Path(_env("DATA_DIR", str(SERVER_DIR / "data")))
DB_PATH = DATA_DIR / "app.db"

MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB
SIGN_EXPIRE_SECONDS = 600             # 签名 10 分钟过期

# ------------------------------------------------------------------
# SQLite
# ------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT UNIQUE,
  name TEXT NOT NULL,
  contact TEXT NOT NULL,
  wedding_date TEXT,
  feishu_ok INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questionnaires (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  contact TEXT NOT NULL,
  fields_json TEXT NOT NULL,
  oss_key TEXT,
  feishu_ok INTEGER DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contact TEXT NOT NULL,
  filename TEXT NOT NULL,
  oss_key TEXT NOT NULL,
  size INTEGER,
  content_type TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mp_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT UNIQUE,
  open_token TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'created',
  auth_ok INTEGER DEFAULT 0,
  free_used INTEGER DEFAULT 0,
  paid_count INTEGER DEFAULT 0,
  selection_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mp_jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_no TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  result_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _migrate() -> None:
    """轻量迁移：给 mp_orders 补 asset_group_id 列（人脸认证回调写入）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(mp_orders)")]
    if "asset_group_id" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN asset_group_id TEXT DEFAULT ''")
    if "byted_token" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN byted_token TEXT DEFAULT ''")
    if "auth_url" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN auth_url TEXT DEFAULT ''")
    if "mode" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN mode TEXT DEFAULT ''")
    if "share_token" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN share_token TEXT DEFAULT ''")
    if "ref" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN ref TEXT DEFAULT ''")
    if "free_quota" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN free_quota INTEGER DEFAULT 20")
    # 裂变奖励标记：受邀订单首次生成成功后给邀请人 +1 张免费额度（只奖一次）
    if "ref_rewarded" not in cols:
        conn.execute("ALTER TABLE mp_orders ADD COLUMN ref_rewarded INTEGER DEFAULT 0")
    # 设备表：协同创作（新娘/新郎两台手机同一订单）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_devices("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "order_no TEXT NOT NULL, open_token TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'A',"
        "created_at TEXT NOT NULL, UNIQUE(order_no, open_token))"
    )
    # 意见反馈：bug / 功能期望（文字+图片，持续改进用）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_feedback("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "order_no TEXT NOT NULL, type TEXT NOT NULL DEFAULT 'other',"
        "text TEXT NOT NULL, images_json TEXT DEFAULT '[]',"
        "status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL)"
    )
    fb_cols = [r[1] for r in conn.execute("PRAGMA table_info(mp_feedback)")]
    if "reply" not in fb_cols:
        conn.execute("ALTER TABLE mp_feedback ADD COLUMN reply TEXT DEFAULT ''")
    # 上传照片的拍摄槽位（front/left/right/body/''）：三视图素材自动归集（2026-08-07）
    up_cols = [r[1] for r in conn.execute("PRAGMA table_info(uploads)")]
    if "slot" not in up_cols:
        conn.execute("ALTER TABLE uploads ADD COLUMN slot TEXT DEFAULT ''")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_assets("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "oss_key TEXT UNIQUE, group_id TEXT, created_at TEXT NOT NULL)"
    )
    # 订单成员表：A=新娘/本人，B=新郎（婚纱照双人认证）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_members("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "order_no TEXT NOT NULL, role TEXT NOT NULL,"
        "byted_token TEXT DEFAULT '', auth_url TEXT DEFAULT '',"
        "asset_group_id TEXT DEFAULT '', auth_ok INTEGER DEFAULT 0,"
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
        "UNIQUE(order_no, role))"
    )
    # 虚拟支付：登录态（session_key 做用户登录态签名）+ 支付单
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_sessions("
        "openid TEXT PRIMARY KEY, session_key TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_pay_orders("
        "out_trade_no TEXT PRIMARY KEY, order_no TEXT NOT NULL, openid TEXT NOT NULL,"
        "product TEXT NOT NULL, coins INTEGER NOT NULL, grant_count INTEGER NOT NULL,"
        "status TEXT NOT NULL DEFAULT 'created', created_at TEXT NOT NULL, paid_at TEXT DEFAULT '')"
    )
    # 同款大片收藏（按微信 openid 归属）
    conn.execute(
        "CREATE TABLE IF NOT EXISTS mp_favs("
        "openid TEXT NOT NULL, series_id TEXT NOT NULL, created_at TEXT NOT NULL,"
        "PRIMARY KEY(openid, series_id))"
    )
    conn.commit()
    # 存量订单迁移：已认证通过的订单视为成员 A 已认证
    for row in conn.execute(
            "SELECT order_no, asset_group_id, byted_token, auth_url FROM mp_orders WHERE auth_ok=1").fetchall():
        exists = conn.execute(
            "SELECT 1 FROM mp_members WHERE order_no=? AND role='A'", (row[0],)).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO mp_members(order_no,role,byted_token,auth_url,asset_group_id,auth_ok,created_at,updated_at)"
                " VALUES(?,'A',?,?,?,1,?,?)",
                (row[0], row[2] or "", row[3] or "", row[1] or "", _now(), _now()))
    conn.commit()
    # 存量订单补 share_token（协同创作邀请链接）
    for (ono,) in conn.execute(
            "SELECT order_no FROM mp_orders WHERE share_token IS NULL OR share_token=''").fetchall():
        conn.execute("UPDATE mp_orders SET share_token=? WHERE order_no=?",
                     (secrets.token_hex(8), ono))
    conn.commit()
    conn.close()


#: 认证回调共享密钥（放在回调 URL 参数里校验来源，配置于 server/.env）
MP_AUTH_CALLBACK_TOKEN = _env("MP_AUTH_CALLBACK_TOKEN", "")


def _db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    conn.close()
    _migrate()
    return sqlite3.connect(DB_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------
# 飞书（tenant_access_token 缓存 + 多维表格写记录）
# ------------------------------------------------------------------
_token_cache: dict = {"token": None, "expire": 0.0}


def _tenant_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expire"] - 60:
        return _token_cache["token"]
    r = requests.post(
        f"{LARK_OPENAPI}/auth/v3/tenant_access_token/internal",
        json={"app_id": LARK_APP_ID, "app_secret": LARK_APP_SECRET},
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：{data.get('msg')}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire"] = time.time() + data.get("expire", 7200)
    return _token_cache["token"]


def _bitable_create_record(table_id: str, fields: dict) -> str:
    """写一条记录，返回 record_id。失败抛异常（由调用方降级处理）。"""
    r = requests.post(
        f"{LARK_OPENAPI}/bitable/v1/apps/{LARK_BASE_TOKEN}/tables/{table_id}/records",
        headers={"Authorization": f"Bearer {_tenant_token()}"},
        json={"fields": fields},
        timeout=20,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"写飞书多维表格失败：code={data.get('code')} msg={data.get('msg')}")
    return data["data"]["record"]["record_id"]


def _parse_date_ms(text: str) -> Optional[int]:
    """尽力把用户输入的婚期文本解析成毫秒时间戳；解析不出返回 None（不填该字段）。"""
    if not text:
        return None
    m = re.search(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})(?:\s*[月\-/\.]\s*(\d{1,2}))?", text)
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3) or 1)
    try:
        dt = datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


# ------------------------------------------------------------------
# 阿里云 OSS（HMAC-SHA1 签名，无需 oss2 SDK）
# ------------------------------------------------------------------
def _oss_sign_string(secret: str, string_to_sign: str) -> str:
    return base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()


def oss_put_object(key: str, data: bytes, content_type: str = "text/plain; charset=utf-8") -> None:
    """服务端直传小文件（问卷原文 txt）。失败抛异常。"""
    date = email.utils.formatdate(usegmt=True)
    resource = f"/{OSS_BUCKET}/{key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    headers = {
        "Date": date,
        "Content-Type": content_type,
        "Authorization": f"OSS {OSS_AK}:{_oss_sign_string(OSS_SK, string_to_sign)}",
    }
    r = requests.put(f"{OSS_ENDPOINT}/{quote(key)}", data=data, headers=headers, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"OSS PUT 失败：HTTP {r.status_code} {r.text[:200]}")


def oss_post_signature(key: str, content_type: str) -> dict:
    """生成 PostObject 签名，供浏览器直传。"""
    expire_at = datetime.now(timezone.utc).timestamp() + SIGN_EXPIRE_SECONDS
    expiration = datetime.fromtimestamp(expire_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    policy_doc = {
        "expiration": expiration,
        "conditions": [
            ["content-length-range", 1, MAX_UPLOAD_BYTES],
            ["eq", "$key", key],
            ["starts-with", "$Content-Type", content_type.split("/")[0] + "/"],
        ],
    }
    policy_b64 = base64.b64encode(json.dumps(policy_doc).encode()).decode()
    signature = _oss_sign_string(OSS_SK, policy_b64)
    return {
        "url": OSS_ENDPOINT,
        "fields": {
            "key": key,
            "policy": policy_b64,
            "OSSAccessKeyId": OSS_AK,
            "Signature": signature,
            "Content-Type": content_type,
        },
    }


def _sanitize_segment(text: str) -> str:
    """OSS key 路径段清洗：只留中英文数字与 -_.，其余转 -。"""
    cleaned = re.sub(r"[^\w一-鿿.\-]+", "-", text.strip())
    return cleaned.strip("-.") or "anonymous"


# ------------------------------------------------------------------
# FastAPI
# ------------------------------------------------------------------
app = FastAPI(title="LuckyNemo Site API", docs_url=None, redoc_url=None, openapi_url=None)


class LeadIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    contact: str = Field(min_length=2, max_length=100)
    date: Optional[str] = Field(default=None, max_length=50)


class QuestionnaireIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    contact: str = Field(min_length=2, max_length=100)
    raw_text: str = Field(min_length=1, max_length=200_000)
    order_no: Optional[str] = Field(default=None, max_length=50)
    # 问卷各题字段（与飞书「故事问卷」表字段同名，全部可选）
    fields: dict = Field(default_factory=dict)


class UploadSignIn(BaseModel):
    contact: Optional[str] = Field(default=None, max_length=100)
    order_no: Optional[str] = Field(default=None, max_length=50)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=3, max_length=100)
    size: int = Field(gt=0)
    slot: str = Field(default="", max_length=10)  # front/left/right/body/''（三视图素材槽位）


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/leads")
def create_lead(body: LeadIn) -> JSONResponse:
    """预约留资：SQLite + 飞书订单表，返回 order_no。"""
    order_no = "LN" + datetime.now().strftime("%Y%m%d") + "-" + "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(3)
    )
    feishu_ok = False
    feishu_err = None
    try:
        fields: dict = {
            "称呼": body.name,
            "微信": body.contact,
            "订单号": order_no,
            "当前工序": "待质检",
            # 产品线留空（客户还没定）
        }
        ms = _parse_date_ms(body.date or "")
        if ms:
            fields["婚期"] = ms
        _bitable_create_record(LARK_ORDER_TABLE_ID, fields)
        feishu_ok = True
    except Exception as exc:  # 飞书失败不阻断留资，记日志事后补
        feishu_err = str(exc)
        log.error("leads 飞书写入失败 order_no=%s err=%s", order_no, feishu_err)

    conn = _db()
    try:
        conn.execute(
            "INSERT INTO leads(order_no,name,contact,wedding_date,feishu_ok,created_at) VALUES(?,?,?,?,?,?)",
            (order_no, body.name, body.contact, body.date or "", 1 if feishu_ok else 0, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("lead created order_no=%s feishu_ok=%s", order_no, feishu_ok)
    return JSONResponse({"ok": True, "order_no": order_no, "feishu_sync": feishu_ok})


#: 允许写入飞书「故事问卷」表的字段白名单（防脏字段）
_STORY_FIELDS = [
    "相识经过", "重要节点", "求婚经过", "心动细节-他", "心动细节-她",
    "最感动的事", "想对他说的话", "想对她说的话", "想对父母说的话", "风格偏好",
]


@app.post("/api/questionnaire")
def create_questionnaire(body: QuestionnaireIn) -> JSONResponse:
    """故事问卷：SQLite + 飞书「故事问卷」表 + OSS 存原文 txt。"""
    warnings = []
    # 1) OSS 存完整原文
    oss_key = ""
    try:
        day = datetime.now().strftime("%Y%m%d")
        who = _sanitize_segment(body.order_no or body.contact)
        oss_key = f"stories/{day}/{who}.txt"
        oss_put_object(oss_key, body.raw_text.encode("utf-8"))
    except Exception as exc:
        log.error("questionnaire OSS 写入失败 contact=%s err=%s", body.contact, exc)
        warnings.append(f"oss: {exc}")
    # 2) 飞书「故事问卷」表
    feishu_ok = False
    try:
        fields: dict = {"称呼": body.name, "微信": body.contact, "完整原文": body.raw_text}
        for k in _STORY_FIELDS:
            v = str(body.fields.get(k) or "").strip()
            if v:
                fields[k] = v[:9000]  # 多维表格文本字段上限保护
        _bitable_create_record(LARK_STORY_TABLE_ID, fields)
        feishu_ok = True
    except Exception as exc:
        log.error("questionnaire 飞书写入失败 contact=%s err=%s", body.contact, exc)
        warnings.append(f"feishu: {exc}")
    # 3) SQLite
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO questionnaires(name,contact,fields_json,oss_key,feishu_ok,created_at) VALUES(?,?,?,?,?,?)",
            (body.name, body.contact, json.dumps(body.fields, ensure_ascii=False),
             oss_key, 1 if feishu_ok else 0, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("questionnaire saved contact=%s oss_key=%s feishu_ok=%s", body.contact, oss_key, feishu_ok)
    resp = {"ok": True, "feishu_sync": feishu_ok, "oss_key": oss_key}
    if warnings:
        resp["warnings"] = warnings
    return JSONResponse(resp)


@app.post("/api/uploads/sign")
def upload_sign(body: UploadSignIn) -> JSONResponse:
    """OSS PostObject 签名：浏览器直传 ibi-private，不过 ECS 带宽。"""
    if not (body.content_type.startswith("image/") or body.content_type.startswith("video/")):
        raise HTTPException(status_code=400, detail="只允许图片或视频文件")
    if body.size > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="单文件不能超过 500MB")
    who = _sanitize_segment(body.order_no or body.contact or "anonymous")
    day = datetime.now().strftime("%Y%m%d")
    safe_name = _sanitize_segment(Path(body.filename).name)
    key = f"materials/{day}/{who}/{uuid.uuid4().hex[:8]}-{safe_name}"
    signed = oss_post_signature(key, body.content_type)
    slot = body.slot if body.slot in ("front", "left", "right", "body") else ""
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at,slot) VALUES(?,?,?,?,?,?,?)",
            (who, body.filename, key, body.size, body.content_type, _now(), slot),
        )
        conn.commit()
    finally:
        conn.close()
    log.info("upload signed who=%s key=%s size=%d slot=%s", who, key, body.size, slot)
    return JSONResponse({"ok": True, "key": key, **signed})


class FaceSheetAutoIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=50)
    role: str = Field(default="A", max_length=2)


@app.post("/api/mp/face_sheet/auto")
def mp_face_sheet_auto(body: FaceSheetAutoIn) -> JSONResponse:
    """上传完成回调：正脸 + 至少 1 张侧脸凑齐时自动创建 face_sheet 任务（用户无感知）。

    已有 queued/running/done 的三视图任务则不重复创建（手动重出走 me 页入口）。
    """
    role = "B" if body.role == "B" else "A"
    contact = f"{body.order_no}-B" if role == "B" else body.order_no
    conn = _db()
    try:
        front = conn.execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND slot='front' ORDER BY id DESC LIMIT 1",
            (contact,)).fetchone()
        sides = [r[0] for r in conn.execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND slot IN ('left','right')"
            " ORDER BY id DESC LIMIT 2", (contact,)).fetchall()]
        if not front or not sides:
            return JSONResponse({"ok": True, "triggered": False,
                                 "reason": "正脸或侧脸照片未凑齐"})
        running = conn.execute(
            "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='face_sheet'"
            " AND status IN ('queued','running','done')"
            " AND json_extract(payload_json,'$.role')=?",
            (body.order_no, role)).fetchone()[0]
        if running:
            return JSONResponse({"ok": True, "triggered": False, "reason": "已有三视图"})
        conn.execute(
            "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (body.order_no, "face_sheet",
             json.dumps({"role": role, "base_key": front[0], "side_keys": sides}, ensure_ascii=False),
             "queued", _now(), _now()))
        conn.commit()
        log.info("face_sheet auto queued order_no=%s role=%s", body.order_no, role)
        return JSONResponse({"ok": True, "triggered": True})
    finally:
        conn.close()


class WardrobeSelectionIn(BaseModel):
    contact: str = Field(min_length=2, max_length=100)
    selection: dict = Field(default_factory=dict)


#: 真人认证邀请链接（微信外的人脸核身服务；小程序内引导用户完成）
MP_AUTH_INVITE_URL = _env(
    "MP_AUTH_INVITE_URL",
    "https://router.i-focusing.com/real-human-auth/invite/c35ce4ae81e62679db18bf8c1437e1fb?v=c35ce4ae",
)

#: 微信小程序（AppSecret 只在服务端使用，换取 openid）
MP_APPID = _env("MP_APPID")
MP_SECRET = _env("MP_SECRET")

# ---------------- 小程序码（裂变海报扫码进入，scene 带邀请人 share_token） ----------------
_wx_token_cache: dict = {}


def _wx_access_token() -> str:
    """微信 client_credential access_token（内存缓存，提前 5 分钟刷新）。"""
    now = time.time()
    tok = _wx_token_cache.get("token")
    if tok and now < _wx_token_cache.get("expires", 0):
        return tok
    r = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": MP_APPID, "secret": MP_SECRET},
        timeout=15)
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"获取微信 access_token 失败：{data}")
    _wx_token_cache["token"] = data["access_token"]
    _wx_token_cache["expires"] = now + int(data.get("expires_in", 7200)) - 300
    return data["access_token"]


def _wx_qrcode_png(scene: str, page: str = "pages/chat/chat") -> bytes:
    """wxacode.getUnlimited 生成小程序码（scene ≤32 字符，携带裂变归因）。"""
    r = requests.post(
        "https://api.weixin.qq.com/wxa/getwxacodeunlimit",
        params={"access_token": _wx_access_token()},
        json={"scene": scene, "page": page, "check_path": False,
              "width": 280, "env_version": "release"},
        timeout=30)
    # 失败时返回的是 JSON 错误而非 PNG
    if r.headers.get("Content-Type", "").startswith("application/json"):
        raise RuntimeError(f"小程序码生成失败：{r.text[:200]}")
    return r.content


@app.get("/api/mp/qrcode")
def mp_qrcode(order_no: str) -> JSONResponse:
    """订单分享小程序码（scene=r_<share_token>），OSS 缓存一份重复使用。"""
    conn = _db()
    try:
        row = conn.execute("SELECT share_token FROM mp_orders WHERE order_no=?",
                           (order_no,)).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="订单不存在或无分享标识")
    key = f"qrcodes/{row[0]}.png"
    url = oss_signed_get_url(key, expire=300)
    try:
        head = requests.head(url, timeout=10)
        exists = head.status_code == 200
    except requests.RequestException:
        exists = False
    if not exists:
        png = _wx_qrcode_png(f"r_{row[0]}")
        oss_put(key, png, "image/png")
        url = oss_signed_get_url(key, expire=300)
    return JSONResponse({"ok": True, "url": url})

#: iFocusing 真人认证 API（文档：router.i-focusing.com/user/docs 三步流程）
IFOCUS_API_KEY = _env("IFOCUS_API_KEY", "")
IFOCUS_BASE = _env("IFOCUS_BASE", "https://router.i-focusing.com/api/ark")
IFOCUS_API_VERSION = _env("IFOCUS_API_VERSION", "2024-01-01")
#: 微信虚拟支付（代币模式，iOS 强制；MP 控制台「虚拟支付 → 基本配置」取 offerId/AppKey）
#: 文档：https://developers.weixin.qq.com/miniprogram/dev/platform-capabilities/business-capabilities/virtual-payment.html
VP_OFFER_ID = _env("VP_OFFER_ID", "")
VP_APP_KEY = _env("VP_APP_KEY", "")                      # 现网 AppKey
VP_APP_KEY_SANDBOX = _env("VP_APP_KEY_SANDBOX", "")      # 沙箱 AppKey
VP_ENV = int(_env("VP_ENV", "0"))                        # 0=现网 1=沙箱
#: 商品表：代币「金币」1 元 = 1 币（MP 后台已配，发布后不可改）；价格须整数元
#: per_photo=4 币→1 张额度，pack52=52 币→20 张额度（2026-08-07 调价：原 49 币→50 张）
#: iOS/Android 同价（用户会跨平台比价，费率差异当获客成本；iOS 通道费率 12%）
VP_PRODUCTS = {
    "per_photo": {"coins": 4, "grant": 1, "title": "4 元/张"},
    "pack52": {"coins": 52, "grant": 20, "title": "52 元 · 20 张"},
}
#: 本站对外地址（拼认证回调用）
PUBLIC_BASE = _env("PUBLIC_BASE", "https://luckynemo.ibi.ren")
#: MiniMax（性别识别等轻量多模态调用）
MINIMAX_KEY = _env("MINIMAX_API_KEY", "")
MINIMAX_BASE = _env("MINIMAX_BASE_URL", "https://api.minimaxi.com/v1")


def ifocus_call(action: str, payload: dict) -> dict:
    """调用 iFocusing ark API。宽容解包响应并全量写日志（字段名按真实响应校准）。"""
    if not IFOCUS_API_KEY:
        raise HTTPException(status_code=500, detail="认证服务未配置（IFOCUS_API_KEY）")
    r = requests.post(
        f"{IFOCUS_BASE}?Action={action}&Version={IFOCUS_API_VERSION}",
        headers={"Authorization": f"Bearer {IFOCUS_API_KEY}"},
        json=payload, timeout=30,
    )
    log.info("ifocus %s http=%d resp=%s", action, r.status_code, r.text[:1500])
    try:
        data = r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail=f"认证服务返回异常：HTTP {r.status_code}")
    for key in ("Response", "Result", "Data", "data"):
        if isinstance(data.get(key), dict):
            return data[key]
    return data if isinstance(data, dict) else {}


def _pick(d: dict, *keys: str) -> str:
    """大小写不敏感地取第一个非空字段。"""
    lowered = {k.lower(): v for k, v in d.items()}
    for k in keys:
        v = lowered.get(k.lower())
        if v:
            return str(v)
    return ""


def oss_signed_get_url(key: str, expire: int = 7 * 86400) -> str:
    """OSS GET 签名 URL（供认证服务拉取素材照片）。"""
    expires = str(int(time.time()) + expire)
    resource = f"/{OSS_BUCKET}/{key}"
    sign = _oss_sign_string(OSS_SK, f"GET\n\n\n{expires}\n{resource}")
    return (f"{OSS_ENDPOINT}/{quote(key)}?OSSAccessKeyId={OSS_AK}"
            f"&Expires={expires}&Signature={quote(sign)}")


def oss_put(key: str, data: bytes, content_type: str) -> None:
    """OSS PUT 直传（服务端小文件：小程序码等）。"""
    date = email.utils.formatdate(usegmt=True)
    resource = f"/{OSS_BUCKET}/{key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    headers = {"Date": date, "Content-Type": content_type,
               "Authorization": f"OSS {OSS_AK}:{_oss_sign_string(OSS_SK, string_to_sign)}"}
    r = requests.put(f"{OSS_ENDPOINT}/{quote(key)}", data=data, headers=headers, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"OSS PUT 失败：HTTP {r.status_code} {r.text[:200]}")


def _safe_oss_delete(key: str) -> None:
    """删除 OSS 对象（失败只记日志，不阻断）。"""
    if not key:
        return
    try:
        date = email.utils.formatdate(usegmt=True)
        resource = f"/{OSS_BUCKET}/{key}"
        sign = _oss_sign_string(OSS_SK, f"DELETE\n\n\n{date}\n{resource}")
        requests.delete(f"{OSS_ENDPOINT}/{quote(key)}",
                        headers={"Date": date, "Authorization": f"OSS {OSS_AK}:{sign}"}, timeout=30)
    except Exception as exc:
        log.warning("OSS 删除失败 key=%s err=%s", key, exc)


def _delete_assets(conn: sqlite3.Connection, order_no: str, target: str, oss_key: str = "") -> int:
    """删除资产：upload=单张上传照片 / photo=单张生成图 / all_uploads / all_photos / reset=全部+重置流程。"""
    deleted = 0
    if target == "upload" and oss_key:
        rows = conn.execute(
            "SELECT id, oss_key FROM uploads WHERE contact LIKE ? AND oss_key=?",
            (f"{order_no}%", oss_key)).fetchall()
        for rid, key in rows:
            _safe_oss_delete(key)
            conn.execute("DELETE FROM uploads WHERE id=?", (rid,))
            deleted += 1
    elif target == "photo" and oss_key:
        rows = conn.execute(
            "SELECT id, result_json FROM mp_jobs WHERE order_no=? AND result_json LIKE ?",
            (order_no, f"%{oss_key}%")).fetchall()
        for rid, rj in rows:
            res = json.loads(rj) if rj else {}
            _safe_oss_delete(res.get("oss_key", ""))
            conn.execute("DELETE FROM mp_jobs WHERE id=?", (rid,))
            deleted += 1
    if target in ("all_uploads", "reset"):
        rows = conn.execute(
            "SELECT id, oss_key FROM uploads WHERE contact LIKE ?", (f"{order_no}%",)).fetchall()
        for rid, key in rows:
            _safe_oss_delete(key)
            deleted += 1
        conn.execute("DELETE FROM uploads WHERE contact LIKE ?", (f"{order_no}%",))
    if target in ("all_photos", "reset"):
        rows = conn.execute(
            "SELECT id, result_json FROM mp_jobs WHERE order_no=?", (order_no,)).fetchall()
        for rid, rj in rows:
            res = json.loads(rj) if rj else {}
            _safe_oss_delete(res.get("oss_key", ""))
            deleted += 1
        conn.execute("DELETE FROM mp_jobs WHERE order_no=?", (order_no,))
    if target == "reset":
        _mp_touch(conn, order_no, mode="", status="created", selection_json="{}")
    conn.commit()
    return deleted


def _ifocus_fetch_group_id(byted_token: str) -> str:
    """认证完成后用 BytedToken 换 Asset Group ID（文档第 2 步）。取不到返回 ''。"""
    if not byted_token or not IFOCUS_API_KEY:
        return ""
    try:
        result = ifocus_call("GetVisualValidateResult", {"BytedToken": byted_token})
        return _pick(result, "GroupId", "AssetGroupId", "AssetGroupID", "AssetGroup")
    except Exception as exc:
        log.warning("ifocus GetVisualValidateResult 失败：%s", exc)
        return ""


def _ifocus_sync_assets(conn: sqlite3.Connection, order_no: str) -> None:
    """把订单已上传的照片登记到认证服务真人素材组（文档第 3 步，尽力而为）。"""
    order = _mp_get_order(conn, order_no)
    if not order or not order.get("asset_group_id") or not IFOCUS_API_KEY:
        return
    rows = conn.execute(
        "SELECT oss_key, filename FROM uploads WHERE contact=? AND content_type LIKE 'image/%' ORDER BY id",
        (order_no,),
    ).fetchall()
    for oss_key, filename in rows:
        if conn.execute("SELECT 1 FROM mp_assets WHERE oss_key=?", (oss_key,)).fetchone():
            continue
        try:
            ifocus_call("CreateAsset", {
                "GroupId": order["asset_group_id"],
                "Name": filename or Path(oss_key).name,
                "AssetType": "Image",
                "URL": oss_signed_get_url(oss_key),
            })
            conn.execute("INSERT INTO mp_assets(oss_key,group_id,created_at) VALUES(?,?,?)",
                         (oss_key, order["asset_group_id"], _now()))
            conn.commit()
            log.info("ifocus CreateAsset ok order_no=%s key=%s", order_no, oss_key)
        except Exception as exc:
            log.warning("ifocus CreateAsset 失败 key=%s err=%s", oss_key, exc)


@app.get("/api/mp/login")
def mp_login(code: str) -> JSONResponse:
    """wx.login 的 js_code 换 openid（小程序启动时调用）。"""
    if not MP_APPID or not MP_SECRET:
        raise HTTPException(status_code=500, detail="小程序凭证未配置（MP_APPID/MP_SECRET）")
    try:
        r = requests.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={"appid": MP_APPID, "secret": MP_SECRET, "js_code": code,
                    "grant_type": "authorization_code"},
            timeout=15,
        )
        data = r.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"微信接口异常：{exc}")
    if "openid" not in data:
        raise HTTPException(status_code=400, detail=f"登录失败：{data.get('errmsg', data)}")
    # 存 session_key（虚拟支付的用户登录态签名要用）
    if data.get("session_key"):
        conn = _db()
        conn.execute(
            "INSERT INTO mp_sessions(openid, session_key, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(openid) DO UPDATE SET session_key=excluded.session_key, updated_at=excluded.updated_at",
            (data["openid"], data["session_key"], _now()))
        conn.commit()
        conn.close()
    log.info("mp login ok openid=%s", data["openid"][:8] + "***")
    return JSONResponse({"ok": True, "openid": data["openid"]})


@app.api_route("/api/mp/auth-callback", methods=["GET", "POST"])
async def mp_auth_callback(request: Request, token: str = "", order_no: str = "") -> JSONResponse:
    """iFocusing 认证回调（宽容解析 GET/POST + 任意 JSON 字段名，按真实回调校准）。

    提供给服务商的回调地址（拼在 CreateVisualValidateSession 的 CallbackURL）：
      https://luckynemo.ibi.ren/api/mp/auth-callback?token=<MP_AUTH_CALLBACK_TOKEN>&order_no=<订单号>
    """
    if MP_AUTH_CALLBACK_TOKEN and token != MP_AUTH_CALLBACK_TOKEN:
        raise HTTPException(status_code=403, detail="token 校验失败")
    body: dict = {}
    try:
        data = await request.json()
        if isinstance(data, dict):
            body = data
    except Exception:
        pass
    # 服务商回调把 GroupId 等参数挂在 URL query 上（可与我们自带的 order_no/role 一起回来），
    # 兼容 JSON body 形式，统一合并后宽容取值
    merged = {**dict(request.query_params), **body}
    log.info("mp auth-callback merged=%s", {k: v for k, v in merged.items() if k != "token"})
    order_no = _pick(merged, "order_no", "OrderNo", "OrderID", "order")
    role = "B" if _pick(merged, "role") == "B" else "A"
    byted = _pick(merged, "BytedToken", "Token", "SessionId", "SessionToken")
    asset = _pick(merged, "GroupId", "asset_group_id", "AssetGroupId", "AssetGroupID")
    conn = _db()
    try:
        order = _mp_get_order(conn, order_no) if order_no else None
        if not order and byted:
            row = conn.execute(
                "SELECT order_no, role FROM mp_members WHERE byted_token=?", (byted,)).fetchone()
            if row:
                order = _mp_get_order(conn, row[0])
                role = row[1]
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        member_fields: dict = {"auth_ok": 1}
        if byted:
            member_fields["byted_token"] = byted
        if not asset:
            asset = _ifocus_fetch_group_id(byted or _member_byted(conn, order["order_no"], role))
        if asset:
            member_fields["asset_group_id"] = asset
        _mp_member_upsert(conn, order["order_no"], role, **member_fields)
        ok = _mp_recompute_auth(conn, order["order_no"])
        log.info("mp auth-callback order_no=%s role=%s asset_group_id=%s order_auth_ok=%s",
                 order["order_no"], role, asset, ok)
        _ifocus_sync_assets(conn, order["order_no"])
        if request.method == "GET":
            # 浏览器/web-view 里的落地页：友好成功页 + 一键返回小程序
            return _auth_done_html(role)
        return JSONResponse({"ok": True})
    finally:
        conn.close()


def _auth_done_html(role: str) -> "HTMLResponse":
    who = "伴侣" if role == "B" else "本人"
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>认证成功 · 徐大恩 LuckyNemo</title>
<script src="https://res.wx.qq.com/open/js/jweixin-1.3.2.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, "PingFang SC", serif; min-height: 100vh;
    background: #faf7f4; color: #2b2320;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    padding: 40px 28px; text-align: center;
  }}
  .badge {{
    width: 88px; height: 88px; border-radius: 50%;
    background: linear-gradient(135deg, #d98f83, #c0736a);
    color: #fff; font-size: 44px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 12px 32px rgba(192,115,106,0.35);
  }}
  h1 {{ font-size: 26px; margin-top: 28px; letter-spacing: 0.05em; }}
  .sub {{ font-size: 15px; color: #8a7f78; margin-top: 14px; line-height: 2; }}
  .btn {{
    margin-top: 36px; width: 100%; max-width: 320px; padding: 16px 0;
    border: none; border-radius: 999px; font-size: 17px; font-weight: 600;
    background: #c0736a; color: #fff;
  }}
  .hint {{ font-size: 13px; color: #b0a59d; margin-top: 18px; line-height: 1.8; }}
</style></head>
<body>
  <div class="badge">✓</div>
  <h1>{who}认证成功</h1>
  <div class="sub">你的脸已经被安全地记录，<br>接下来就可以开始你们的创作啦。</div>
  <button class="btn" onclick="backToMini()">返回小程序，继续 →</button>
  <div class="hint">如果没有自动跳转，请手动回到小程序，<br>点击「我已完成认证」继续。</div>
<script>
function backToMini() {{
  try {{
    if (window.wx && wx.miniProgram) {{
      wx.miniProgram.navigateBack({{ delta: 1 }});
      setTimeout(function() {{ wx.miniProgram.reLaunch({{ url: '/pages/chat/chat' }}); }}, 600);
    }} else {{
      document.querySelector('.hint').innerHTML = '请手动回到小程序，点击「我已完成认证」继续。';
    }}
  }} catch (e) {{
    document.querySelector('.hint').innerHTML = '请手动回到小程序，点击「我已完成认证」继续。';
  }}
}}
// 在小程序 web-view 里，3 秒后自动返回
setTimeout(function() {{
  if (window.wx && wx.miniProgram) {{
    try {{ wx.miniProgram.navigateBack({{ delta: 1 }}); }} catch (e) {{}}
  }}
}}, 3000);
</script>
</body></html>"""
    return HTMLResponse(html)


class MpOrderIn(BaseModel):
    open_token: str = Field(min_length=6, max_length=100)  # v1 设备 token；AppID 下来后换 openid
    order_no: Optional[str] = Field(default=None, max_length=50)
    mode: Optional[str] = Field(default=None, max_length=10)  # couple=婚纱照 / solo=个人写真
    ref: Optional[str] = Field(default=None, max_length=64)  # 裂变来源（邀请人 share_token）


class MpJobIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=50)
    kind: str = Field(min_length=1, max_length=30)
    payload: dict = Field(default_factory=dict)


class MpChatIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=50)
    message: str = Field(min_length=0, max_length=500)
    images: list[str] = Field(default_factory=list, max_length=3)  # 聊天中上传的图片 OSS keys
    history: list[str] = Field(default_factory=list, max_length=8)  # 最近对话（追问/确认上下文）


class MpFeedbackIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=50)
    type: str = Field(default="other", max_length=20)  # bug / feature / other
    text: str = Field(min_length=1, max_length=1000)
    images: list[str] = Field(default_factory=list, max_length=3)  # OSS keys


@app.post("/api/mp/feedback")
def mp_feedback_create(body: MpFeedbackIn) -> JSONResponse:
    """意见反馈提交（bug / 功能期望 / 其他，文字+图片）。"""
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO mp_feedback(order_no,type,text,images_json,created_at) VALUES(?,?,?,?,?)",
            (body.order_no, body.type, body.text,
             json.dumps(body.images[:3], ensure_ascii=False), _now()),
        )
        conn.commit()
        log.info("mp feedback order_no=%s type=%s len=%d imgs=%d",
                 body.order_no, body.type, len(body.text), len(body.images))
        return JSONResponse({"ok": True})
    finally:
        conn.close()


@app.get("/api/mp/feedback")
def mp_feedback_list(order_no: str) -> JSONResponse:
    """用户自己的历史反馈（最新 10 条）。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT type,text,images_json,status,created_at,reply FROM mp_feedback"
            " WHERE order_no=? ORDER BY id DESC LIMIT 10", (order_no,)).fetchall()
        items = [
            {"type": r[0], "text": r[1],
             "images": [oss_signed_get_url(k, expire=3600) for k in json.loads(r[2] or "[]")],
             "status": r[3], "time": r[4], "reply": r[5] or ""}
            for r in rows
        ]
        return JSONResponse({"ok": True, "items": items})
    finally:
        conn.close()


class MpDeleteIn(BaseModel):
    order_no: str = Field(min_length=1, max_length=50)
    target: str = Field(min_length=1, max_length=20)  # upload/photo/all_uploads/all_photos/reset
    oss_key: str = Field(default="", max_length=300)


@app.post("/api/mp/delete")
def mp_delete(body: MpDeleteIn) -> JSONResponse:
    """删除资产：单张上传照/单张生成图/全部上传/全部生成/全部+重置流程。"""
    conn = _db()
    try:
        deleted = _delete_assets(conn, body.order_no, body.target, body.oss_key)
        log.info("mp delete order_no=%s target=%s deleted=%d", body.order_no, body.target, deleted)
        return JSONResponse({"ok": True, "deleted": deleted})
    finally:
        conn.close()


def _mp_members(conn: sqlite3.Connection, order_no: str) -> dict:
    """订单成员认证状态：{'A': {...}, 'B': {...}}。A=新娘/本人，B=新郎。"""
    rows = conn.execute(
        "SELECT role,auth_ok,asset_group_id,auth_url FROM mp_members WHERE order_no=?",
        (order_no,),
    ).fetchall()
    return {
        r[0]: {"auth_ok": bool(r[1]), "asset_group_id": r[2] or "", "has_link": bool(r[3])}
        for r in rows
    }


def _member_byted(conn: sqlite3.Connection, order_no: str, role: str) -> str:
    row = conn.execute(
        "SELECT byted_token FROM mp_members WHERE order_no=? AND role=?",
        (order_no, role)).fetchone()
    return (row[0] or "") if row else ""


def _mp_member_upsert(conn: sqlite3.Connection, order_no: str, role: str, **fields) -> None:
    """写入/更新成员记录（不存在则插入）。"""
    exists = conn.execute(
        "SELECT 1 FROM mp_members WHERE order_no=? AND role=?", (order_no, role)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO mp_members(order_no,role,created_at,updated_at) VALUES(?,?,?,?)",
            (order_no, role, _now(), _now()))
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields) + ", updated_at=?"
        conn.execute(
            f"UPDATE mp_members SET {sets} WHERE order_no=? AND role=?",
            (*fields.values(), _now(), order_no, role))
    conn.commit()


def _mp_required_roles(order: dict) -> list[str]:
    """该订单需要认证的角色：婚纱照双人 = A+B，其余（含未选模式）= 只 A。"""
    return ["A", "B"] if order.get("mode") == "couple" else ["A"]


def _mp_find_auth(conn: sqlite3.Connection, open_token: str):
    """按微信身份找该用户最近一次已完成的真人认证（新订单/加入订单时继承，免重复认证）。

    匹配本人在历史订单里的成员记录：自己创建的订单里是 A，被邀请加入的订单里是 B。
    老订单可能没有 mp_devices 行，故用 mp_orders.open_token 并集设备表。
    """
    return conn.execute(
        "SELECT m.byted_token, m.asset_group_id FROM mp_members m"
        " JOIN mp_orders o ON o.order_no=m.order_no"
        " LEFT JOIN mp_devices d ON d.order_no=m.order_no AND d.open_token=?"
        " WHERE m.auth_ok=1 AND m.role=COALESCE(d.role, 'A')"
        " AND (o.open_token=? OR d.open_token IS NOT NULL)"
        " ORDER BY m.id DESC LIMIT 1", (open_token, open_token)).fetchone()


def _mp_recompute_auth(conn: sqlite3.Connection, order_no: str) -> bool:
    """按成员状态重算订单级 auth_ok（双人模式需 A+B 都过）并落库。"""
    order = _mp_get_order(conn, order_no)
    if not order:
        return False
    members = order["members"]
    ok = all(members.get(r, {}).get("auth_ok") for r in _mp_required_roles(order))
    _mp_touch(conn, order_no, auth_ok=1 if ok else 0,
              status="auth_ok" if ok else "created")
    return ok


def _mp_get_order(conn: sqlite3.Connection, order_no: str) -> dict | None:
    row = conn.execute(
        "SELECT order_no,open_token,status,auth_ok,free_used,paid_count,selection_json,created_at,updated_at,asset_group_id,byted_token,auth_url,mode,share_token,free_quota"
        " FROM mp_orders WHERE order_no=?", (order_no,),
    ).fetchone()
    if not row:
        return None
    return {
        "order_no": row[0], "status": row[2], "auth_ok": bool(row[3]),
        "free_used": row[4] or 0, "paid_count": row[5] or 0,
        "selection": json.loads(row[6]) if row[6] else {},
        "created_at": row[7], "updated_at": row[8], "asset_group_id": row[9] or "",
        "byted_token": row[10] or "", "auth_url": row[11] or "",
        "mode": row[12] or "",
        "share_token": row[13] or "", "free_quota": row[14] if row[14] is not None else 20,
        "members": _mp_members(conn, order_no),
    }


def _mp_touch(conn: sqlite3.Connection, order_no: str, **fields) -> None:
    sets, vals = [], []
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(v)
    sets.append("updated_at=?")
    vals.append(_now())
    vals.append(order_no)
    conn.execute(f"UPDATE mp_orders SET {', '.join(sets)} WHERE order_no=?", vals)
    conn.commit()


@app.get("/api/mp/auth-session")
def mp_auth_session(order_no: str, role: str = "A") -> dict:
    """为订单成员创建真人认证会话（iFocusing 文档第 1 步），返回 H5 认证链接。

    role：A=新娘/本人，B=新郎（婚纱照双人各认各的，每次调用生成新链接不过期）。
    未配置 IFOCUS_API_KEY 时回退到旧静态邀请链接，保证流程不断。
    """
    role = "B" if role == "B" else "A"
    if not IFOCUS_API_KEY:
        sep = "&" if "?" in MP_AUTH_INVITE_URL else "?"
        return {"ok": True, "url": f"{MP_AUTH_INVITE_URL}{sep}order={order_no}", "mode": "legacy"}
    callback = (f"{PUBLIC_BASE}/api/mp/auth-callback"
                f"?token={MP_AUTH_CALLBACK_TOKEN}&order_no={order_no}&role={role}")
    who = "本人" if role == "A" else "伴侣"
    result = ifocus_call("CreateVisualValidateSession", {
        "CallbackURL": callback,
        "Name": f"徐大恩真人认证-{who}-{order_no}",
    })
    url = _pick(result, "H5Link", "AuthUrl", "H5Url", "Url", "ValidateUrl", "SessionUrl", "WebUrl")
    byted = _pick(result, "BytedToken", "Token", "SessionId", "SessionToken", "ValidateToken")
    if not url:
        raise HTTPException(status_code=502, detail=f"认证会话创建失败：{result}")
    conn = _db()
    try:
        _mp_member_upsert(conn, order_no, role, byted_token=byted, auth_url=url)
    finally:
        conn.close()
    log.info("mp auth-session order_no=%s role=%s byted=%s", order_no, role,
             (byted[:8] + "***") if byted else "(响应未含 token)")
    # 反代版链接（web-view 内打开需业务域名验证；验证未配时前端回退复制链接）
    from urllib.parse import urlparse as _urlparse
    _u = _urlparse(url)
    proxy_url = f"{PUBLIC_BASE}/auth-h5{_u.path}?{_u.query}" if "volcengine.com" in _u.netloc else ""
    return {"ok": True, "url": url, "proxy_url": proxy_url, "role": role, "mode": "session"}


@app.get("/api/mp/detect-gender")
def mp_detect_gender(order_no: str, role: str = "A") -> dict:
    """按用户最新上传的照片自动识别性别（预选妆造 Tab），识别失败返回 unknown 由用户手选。"""
    if not MINIMAX_KEY:
        return {"ok": True, "gender": "unknown"}
    contact = order_no if role != "B" else f"{order_no}-B"
    conn = _db()
    try:
        row = conn.execute(
            "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%' ORDER BY id DESC LIMIT 1",
            (contact,)).fetchone()
    finally:
        conn.close()
    if not row:
        return {"ok": True, "gender": "unknown"}
    try:
        url = oss_signed_get_url(row[0], expire=600)
        img = base64.b64encode(requests.get(url, timeout=60).content).decode()
        r = requests.post(
            f"{MINIMAX_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {MINIMAX_KEY}"},
            json={"model": "abab6.5s-chat", "messages": [{"role": "user", "content": [
                {"type": "text", "text": "照片中人物的生理性别是？只回答一个字：男 或 女"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img}"}}]}],
                "max_tokens": 10},
            timeout=60,
        )
        text = r.json()["choices"][0]["message"]["content"]
        gender = "male" if "男" in text else ("female" if "女" in text else "unknown")
    except Exception as exc:
        log.warning("detect-gender 失败 order_no=%s role=%s err=%s", order_no, role, exc)
        gender = "unknown"
    log.info("detect-gender order_no=%s role=%s gender=%s", order_no, role, gender)
    return {"ok": True, "gender": gender}


@app.get("/api/mp/auth-status")
def mp_auth_status(order_no: str) -> dict:
    """小程序轮询：回调未到达时，主动用各成员 BytedToken 查认证结果（文档第 2 步）。"""
    conn = _db()
    try:
        order = _mp_get_order(conn, order_no)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        if not order["auth_ok"]:
            for role in _mp_required_roles(order):
                member = order["members"].get(role, {})
                if member.get("auth_ok"):
                    continue
                asset = _ifocus_fetch_group_id(_member_byted(conn, order_no, role))
                if asset:
                    _mp_member_upsert(conn, order_no, role, auth_ok=1, asset_group_id=asset)
            _mp_recompute_auth(conn, order_no)
            order = _mp_get_order(conn, order_no)
            if order["auth_ok"]:
                _ifocus_sync_assets(conn, order_no)
        return {"ok": True, "order": order}
    finally:
        conn.close()


@app.get("/api/mp/orders")
def mp_orders_list(open_token: str) -> JSONResponse:
    """按微信身份列历史订单（删小程序/换手机找回用）：含自己创建的与作为伴侣加入的。"""
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT o.order_no, o.mode, o.created_at,"
            " COALESCE((SELECT d.role FROM mp_devices d"
            "           WHERE d.order_no=o.order_no AND d.open_token=?), 'A')"
            " FROM mp_orders o"
            " WHERE o.open_token=?"
            " OR EXISTS(SELECT 1 FROM mp_devices d2"
            "           WHERE d2.order_no=o.order_no AND d2.open_token=?)"
            " ORDER BY o.id DESC LIMIT 20",
            (open_token, open_token, open_token)).fetchall()
        orders = []
        for order_no, mode, created_at, role in rows:
            n = 0
            for r in conn.execute(
                    "SELECT result_json FROM mp_jobs WHERE order_no=? AND status='done' AND kind != 'face_sheet'"
                    " ORDER BY id DESC LIMIT 200", (order_no,)).fetchall():
                result = json.loads(r[0]) if r[0] else {}
                if result.get("url"):
                    n += 1
                n += sum(1 for it in (result.get("urls") or []) if isinstance(it, dict) and it.get("url"))
            orders.append({"order_no": order_no, "mode": mode or "", "role": role,
                           "created_at": created_at, "photo_count": n})
        return JSONResponse({"ok": True, "orders": orders})
    finally:
        conn.close()


@app.post("/api/mp/order")
def mp_order_create(body: MpOrderIn) -> JSONResponse:
    """创建或恢复小程序订单；带 mode 时更新订单模式（couple 婚纱照 / solo 个人写真）。"""
    conn = _db()
    try:
        if body.order_no:
            order = _mp_get_order(conn, body.order_no)
            if order:
                if body.mode in ("couple", "solo") and order["mode"] != body.mode:
                    _mp_touch(conn, body.order_no, mode=body.mode)
                    _mp_recompute_auth(conn, body.order_no)
                    order = _mp_get_order(conn, body.order_no)
                return JSONResponse({"ok": True, "order": order})
        order_no = "MP" + datetime.now().strftime("%Y%m%d") + "-" + "".join(
            secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4)
        )
        share_token = secrets.token_hex(8)
        conn.execute(
            "INSERT INTO mp_orders(order_no,open_token,status,share_token,ref,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?)",
            (order_no, body.open_token, "created", share_token, body.ref or "", _now(), _now()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO mp_devices(order_no,open_token,role,created_at) VALUES(?,?,?,?)",
            (order_no, body.open_token, "A", _now()),
        )
        # 认证继承：该微信身份之前完成过真人认证则直接带过来（删小程序/新订单免重做）
        auth = _mp_find_auth(conn, body.open_token)
        if auth and (auth[0] or auth[1]):
            _mp_member_upsert(conn, order_no, "A", auth_ok=1,
                              byted_token=auth[0] or "", asset_group_id=auth[1] or "")
            log.info("mp order %s 继承历史认证 role=A", order_no)
        conn.commit()
        log.info("mp order created order_no=%s ref=%s", order_no, body.ref or "-")
        return JSONResponse({"ok": True, "order": _mp_get_order(conn, order_no)})
    finally:
        conn.close()


class MpJoinIn(BaseModel):
    share_token: str = Field(min_length=8, max_length=64)
    open_token: str = Field(min_length=6, max_length=100)


@app.post("/api/mp/join")
def mp_join(body: MpJoinIn) -> JSONResponse:
    """协同创作：通过分享令牌加入订单，设备绑定为成员 B（幂等）。"""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT order_no FROM mp_orders WHERE share_token=?", (body.share_token,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="邀请链接无效或已过期")
        order_no = row[0]
        existing = conn.execute(
            "SELECT role FROM mp_devices WHERE order_no=? AND open_token=?",
            (order_no, body.open_token)).fetchone()
        if existing:
            role = existing[0]
        else:
            # 创建者是 A，加入者一律绑定为 B（新郎）
            conn.execute(
                "INSERT INTO mp_devices(order_no,open_token,role,created_at) VALUES(?,?,?,?)",
                (order_no, body.open_token, "B", _now()))
            # 认证继承：加入者本人之前完成过真人认证则直接带过来
            auth = _mp_find_auth(conn, body.open_token)
            if auth and (auth[0] or auth[1]):
                _mp_member_upsert(conn, order_no, "B", auth_ok=1,
                                  byted_token=auth[0] or "", asset_group_id=auth[1] or "")
                _mp_recompute_auth(conn, order_no)
                log.info("mp join %s 继承历史认证 role=B", order_no)
            conn.commit()
            role = "B"
        log.info("mp join order_no=%s role=%s", order_no, role)
        return JSONResponse({"ok": True, "order": _mp_get_order(conn, order_no), "role": role})
    finally:
        conn.close()


@app.get("/api/mp/order/{order_no}")
def mp_order_get(order_no: str) -> JSONResponse:
    conn = _db()
    try:
        order = _mp_get_order(conn, order_no)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        jobs = []
        makeup_gender = {}
        try:
            makeup_gender = {m["id"]: m.get("gender", "")
                             for m in _load_makeup_catalog(Path(_env("SITE_DIR", "/var/www/luckynemo")))}
        except Exception:
            pass
        for r in conn.execute(
                "SELECT kind,status,result_json,payload_json FROM mp_jobs WHERE order_no=? ORDER BY id DESC LIMIT 200",  # 反馈 #33：30 条窗口会把老定妆照挤出锚点列表
                (order_no,)):
            payload = json.loads(r[3]) if r[3] else {}
            jobs.append({
                "kind": r[0], "status": r[1],
                "result": json.loads(r[2]) if r[2] else None,
                "role": payload.get("role", "A"),
                "makeup_name": payload.get("makeup_name", ""),
                "gender": payload.get("gender", "") or makeup_gender.get(payload.get("makeup_id", ""), ""),
                "engine": payload.get("engine", "seedream"),
            })
        photo_count = conn.execute(
            "SELECT COUNT(*) FROM uploads WHERE contact=? AND content_type LIKE 'image/%'",
            (order_no,),
        ).fetchone()[0]
        photo_count_b = conn.execute(
            "SELECT COUNT(*) FROM uploads WHERE contact=? AND content_type LIKE 'image/%'",
            (f"{order_no}-B",),
        ).fetchone()[0]
        return JSONResponse({"ok": True, "order": order, "jobs": jobs,
                             "photo_count": photo_count, "photo_count_b": photo_count_b})
    finally:
        conn.close()


@app.post("/api/mp/auth-pass")
def mp_auth_pass(body: MpOrderIn) -> JSONResponse:
    """真人认证通过回写（认证服务回调或客服核验后调用）。"""
    if not body.order_no:
        raise HTTPException(status_code=400, detail="缺 order_no")
    conn = _db()
    try:
        _mp_touch(conn, body.order_no, auth_ok=1, status="auth_ok")
        return JSONResponse({"ok": True, "order": _mp_get_order(conn, body.order_no)})
    finally:
        conn.close()


#: 动作神态选项库（源自小徐试点 SOP，四步流程第 3 步）
MP_POSES = {
    "站姿": ["正面并肩", "挽手侧立", "他背后环抱", "她提裙转圈"],
    "坐姿": ["并肩太师椅", "对视沙发坐", "她坐他站身后"],
    "神态": ["微笑对视", "大笑", "低头浅笑", "闭眼靠肩", "认真深情"],
    "互动": ["牵手走", "碰杯", "为她戴头纱", "为她整理项链"],
}

#: 个人写真动作神态库（solo 模式）
MP_POSES_SOLO = {
    "站姿": ["正面自然站立", "侧身回眸", "提裙转圈", "背影远望"],
    "坐姿": ["优雅端坐", "托腮沉思", "侧坐回头"],
    "神态": ["微笑", "大笑", "低头浅笑", "闭眼感受", "眼神坚定"],
    "特写": ["回眸特写", "侧脸轮廓", "低头抚发", "手持捧花特写"],
}

#: 定妆照提示词模板（与 assets/hongzhuang/build_prompt.py 一致，按性别配方自动适配）
_MAKEUP_PROMPT_TMPL = (
    "以参考照片中的{person}为人物，严格保持{ta}的五官、脸型、下颌线、发型完全不变，"
    "卸掉眼镜，只为{ta}化上「{name}」妆容，配方如下：\n"
    "{recipe}\n"
    "整体妆感要求：{vibe}。妆容清透自然，绝不老气。\n"
    "正面肩部以上肖像，浅灰色纯色背景，柔和均匀的摄影棚灯光，专业妆面照质感，"
    "不要改变脸型和五官结构，不要加任何饰品，无文字无水印，3:4竖版"
)


def _compose_makeup_prompt(style: dict) -> str:
    """按 spec.parts 配方（女性：底妆/眼妆/腮红/唇妆；男性：底妆/眉毛/修容/唇妆）组装提示词。
    spec.no_makeup 为素颜版：不化妆，只统一背景光线。
    spec.use_original 为原图直出版：人物 100% 不动，仅抠图换干净背景（治"不像本人"）。"""
    male = style.get("gender") == "male"
    if style.get("spec", {}).get("use_original"):
        person = "男性" if male else "女性"
        return (
            f"这是对参考照片的背景替换与皮肤清理编辑，不是重新生成：参考照片中的{person}就是最终成片人物，"
            "严格保持其脸部、五官、脸型、表情、发型、服装、画面构图不变，"
            "不做任何美颜、美化、重绘或五官调整，与参考照片的人物一模一样。\n"
            "允许的改动仅两类：①把杂乱的原始背景替换为浅灰色纯色摄影棚背景，人物边缘干净自然、"
            "与场景自然融合有投影，光线统一为柔和均匀的摄影棚灯光；"
            "②皮肤清理：去掉汗珠、汗水、油光、明显痘痘等皮肤瑕疵，轻度自然，不过度磨皮，"
            "痣和五官特征必须保留。无文字无水印"
        )
    if style.get("spec", {}).get("no_makeup"):
        person, ta = ("男性", "他") if male else ("女性", "她")
        return (
            f"以参考照片中的{person}为人物，严格保持{ta}的五官、脸型、下颌线、发型完全不变，"
            f"保持素颜，不为{ta}化任何妆，仅做肤色均匀与轻微提亮，卸掉眼镜。"
            "与参考照片人物的相似度是第一优先级：宁可朴素也绝不美化、不把五官往标准模板靠。\n"
            "正面肩部以上肖像，浅灰色纯色背景，柔和均匀的摄影棚灯光，专业肖像照质感，"
            "不要改变脸型和五官结构，不要加任何饰品，无文字无水印，3:4竖版"
        )
    parts = style["spec"]["parts"]
    recipe = "\n".join(f"{k}：{v}" for k, v in parts.items() if k != "发型")
    return _MAKEUP_PROMPT_TMPL.format(
        person="男性" if male else "女性", ta="他" if male else "她",
        name=style["name"], vibe=style["vibe"], recipe=recipe,
    )


def _load_makeup_catalog(site: Path) -> list[dict]:
    """读红妆阁 index.json，输出小程序选妆数据（含组装好的定妆提示词）。"""
    data = json.loads((site / "hongzhuang/index.json").read_text(encoding="utf-8"))
    styles = []
    for s in data["styles"]:
        styles.append({
            "id": s["id"], "name": s["name"], "series": s["series"],
            "gender": s.get("gender", "female"),
            "vibe": s["vibe"], "img": "/hongzhuang/" + s["file"],
            "prompt": _compose_makeup_prompt(s),
            "spec": s.get("spec", {}),
        })
    return styles


@app.get("/api/mp/catalog")
def mp_catalog() -> dict:
    """输出选装目录（霓裳阁套装 + 微剧情场景 + 红妆阁妆造/发型 + 动作神态），静态文件由站点目录提供。"""
    site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
    try:
        sets_js = (site / "wardrobe/data.js").read_text(encoding="utf-8")
        scenes_js = (site / "scenes/data.js").read_text(encoding="utf-8")
        makeup = _load_makeup_catalog(site)
        hz = json.loads((site / "hongzhuang/index.json").read_text(encoding="utf-8"))
        hairstyles = [
            {"id": h["id"], "name": h["name"], "gender": h.get("gender", "female"),
             "fit": h.get("fit", ""), "img": "/hongzhuang/" + h["file"],
             "prompt_key": h["prompt_key"]}
            for h in hz.get("hairstyles", [])
        ]
        # 模卡库（一键同款模板，v2 系列化：系列=主题场景锁定，变体=不同瞬间/构图）
        # v4：系列带 moments/tags/hot_base/cover/status，hot=运营基数+真实生成计数
        moka = []
        moka_series = []
        moka_groups = []
        moments = []
        moka_path = site / "moka" / "index.json"
        if moka_path.is_file():
            moka_data = json.loads(moka_path.read_text(encoding="utf-8"))
            moka = [
                {"id": t["id"], "mode": t["mode"], "title": t["title"],
                 "desc": t.get("desc", ""), "img": "/moka/" + t["file"],
                 "series": t.get("series", ""),
                 "components": t.get("components", {}),
                 **({"placeholder": True} if t.get("placeholder") else {})}
                for t in moka_data.get("templates", [])
            ]
            hot_real = _moka_hot_counts()
            moka_series = []
            for s in moka_data.get("series", []):
                sid = s.get("id", "")
                base = int(s.get("hot_base", 0) or 0)
                moka_series.append({
                    **s,
                    "hot": base + hot_real.get(sid, 0),
                })
            moka_groups = moka_data.get("groups", [])
            moments = moka_data.get("moments", [])
        return {"ok": True, "sets_js": sets_js, "scenes_js": scenes_js,
                "makeup": makeup, "hairstyles": hairstyles, "moka": moka,
                "moka_series": moka_series, "moka_groups": moka_groups,
                "moments": moments,
                "poses": MP_POSES, "poses_solo": MP_POSES_SOLO,
                "img_base": {"wardrobe": "/wardrobe/img/", "scenes": "/scenes/img/",
                             "makeup": "/hongzhuang/"}}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"目录数据缺失：{exc}")


def _moka_hot_counts() -> dict:
    """各系列真实生成次数（template_series 每单计 1 + template_photo 每张计 1），
    叠加在 series.hot_base 运营基数上（决策：热门人数=运营基数+真实计数）。"""
    site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
    moka_path = site / "moka" / "index.json"
    if not moka_path.is_file():
        return {}
    moka_data = json.loads(moka_path.read_text(encoding="utf-8"))
    tpl_series = {t["id"]: t.get("series", "") for t in moka_data.get("templates", [])}
    counts: dict = {}
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT kind, payload_json FROM mp_jobs"
            " WHERE status='done' AND kind IN ('template_series','template_photo')").fetchall()
    finally:
        conn.close()
    for kind, pj in rows:
        try:
            p = json.loads(pj or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if kind == "template_series":
            sid = p.get("series_id", "")
        else:
            sid = tpl_series.get(p.get("template_id", ""), "")
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def _enrich_job_payload(body: "MpJobIn", order: dict) -> dict:
    """把订单 selection 里的用户化妆意见/性别合并进任务参数（自定义意见的落点）。"""
    payload = dict(body.payload or {})
    if body.kind == "makeup_photo":
        sel = order.get("selection") or {}
        # 对话里提的化妆意见与页面选项合并（页面选项在前，优先级更高）
        notes = "；".join(x for x in [str(payload.get("makeup_notes") or ""),
                                      str(sel.get("makeup_notes") or "")] if x)
        if notes:
            payload["makeup_notes"] = notes[:300]
        if sel.get("gender") and not payload.get("gender"):
            payload["gender"] = str(sel["gender"])
    return payload


def _moka_series_size(payload: dict) -> int:
    """系列整组生成的扣费张数 = 变体数；payload 带 variant_ids（选片子集）时按子集张数。"""
    series_id = payload.get("series_id", "")
    site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
    moka_path = site / "moka" / "index.json"
    if moka_path.is_file():
        moka_data = json.loads(moka_path.read_text(encoding="utf-8"))
        for s in moka_data.get("series", []):
            if s.get("id") == series_id:
                variants = s.get("variants", [])
                want = payload.get("variant_ids") or []
                if want:
                    want = [v for v in want if v in variants]
                    if not want:
                        break
                    return len(want)
                n = len(variants)
                if n:
                    return n
    raise HTTPException(status_code=400, detail=f"大片系列不存在：{series_id}")


# ---------------- 同款大片收藏（v4，按 openid 归属） ----------------

class MpFavIn(BaseModel):
    open_token: str = Field(min_length=6, max_length=120)
    series_id: str = Field(min_length=1, max_length=40)
    fav: bool = True


def _fav_openid(open_token: str) -> str:
    """收藏鉴权：open_token 取 wx- 前缀得 openid，且须是登录过（mp_sessions 有记录）的用户。"""
    openid = _vp_openid(open_token)
    if not openid:
        return ""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT 1 FROM mp_sessions WHERE openid=?", (openid,)).fetchone()
    finally:
        conn.close()
    return openid if row else ""


@app.post("/api/mp/fav")
def mp_fav_set(body: MpFavIn) -> JSONResponse:
    """收藏/取消收藏一个系列。openid 取自 open_token（wx- 前缀），与虚拟支付同一约定。"""
    openid = _fav_openid(body.open_token)
    if not openid:
        raise HTTPException(status_code=401, detail="登录态无效")
    conn = _db()
    try:
        if body.fav:
            conn.execute(
                "INSERT INTO mp_favs(openid,series_id,created_at) VALUES(?,?,?) "
                "ON CONFLICT(openid,series_id) DO NOTHING",
                (openid, body.series_id, _now()))
        else:
            conn.execute(
                "DELETE FROM mp_favs WHERE openid=? AND series_id=?",
                (openid, body.series_id))
        conn.commit()
    finally:
        conn.close()
    return JSONResponse({"ok": True})


@app.get("/api/mp/favs")
def mp_fav_list(open_token: str = "") -> JSONResponse:
    """我的收藏系列 id 列表。"""
    openid = _fav_openid(open_token)
    if not openid:
        raise HTTPException(status_code=401, detail="登录态无效")
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT series_id FROM mp_favs WHERE openid=? ORDER BY created_at DESC",
            (openid,)).fetchall()
    finally:
        conn.close()
    return JSONResponse({"ok": True, "favs": [r[0] for r in rows]})


@app.post("/api/mp/job")
def mp_job_create(body: MpJobIn) -> JSONResponse:
    """创建生成任务（免费 1 张或付费张数），worker 异步执行。"""
    conn = _db()
    try:
        order = _mp_get_order(conn, body.order_no)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        # 定妆/单人写真/人脸三视图只需对应成员认证（新郎侧查 B）；婚纱照成片需订单所需成员全部认证
        if body.kind in ("makeup_photo", "solo_photo", "face_sheet"):
            role = (body.payload or {}).get("role", "A")
            role = "B" if role == "B" else "A"
            if not order["members"].get(role, {}).get("auth_ok"):
                raise HTTPException(status_code=403, detail="请先完成真人认证")
        elif not order["auth_ok"]:
            raise HTTPException(status_code=403, detail="请先完成双人真人认证")
        # 定妆限量：每单免费 10 次，超出后每次扣 1 张免费额度（防止无限刷妆造图）
        if body.kind == "makeup_photo":
            makeup_count = conn.execute(
                "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='makeup_photo'",
                (body.order_no,)).fetchone()[0]
            if makeup_count >= 10:
                if (order["free_used"] or 0) < order["free_quota"]:
                    _mp_touch(conn, body.order_no, free_used=(order["free_used"] or 0) + 1)
                else:
                    raise HTTPException(status_code=403, detail="免费额度已用完，请充值后再继续")
        if body.kind in ("free_photo", "solo_photo", "template_photo", "edit_photo", "duo_photo"):
            # 内测额度：每单 free_quota 张免费（默认 20），先扣免费再扣付费
            if (order["free_used"] or 0) < order["free_quota"]:
                _mp_touch(conn, body.order_no, free_used=(order["free_used"] or 0) + 1, status="generating")
            elif order["paid_count"] > 0:
                _mp_touch(conn, body.order_no, paid_count=order["paid_count"] - 1, status="generating")
            else:
                raise HTTPException(status_code=403, detail="免费额度已用完，请充值后再生成")
        elif body.kind == "template_series":
            # 系列整组生成（九宫格）：按系列变体数一次性扣额度，先免费后付费
            n = _moka_series_size(body.payload or {})
            free_left = max(0, order["free_quota"] - (order["free_used"] or 0))
            use_free = min(free_left, n)
            need_paid = n - use_free
            if need_paid > order["paid_count"]:
                raise HTTPException(
                    status_code=403,
                    detail=f"整组生成需要 {n} 张额度（免费余 {free_left}、付费余 {order['paid_count']}），请先充值")
            _mp_touch(conn, body.order_no,
                      free_used=(order["free_used"] or 0) + use_free,
                      paid_count=order["paid_count"] - need_paid, status="generating")
        else:
            _mp_touch(conn, body.order_no, status="generating")
        conn.execute(
            "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (body.order_no, body.kind,
             json.dumps(_enrich_job_payload(body, order), ensure_ascii=False),
             "queued", _now(), _now()),
        )
        conn.commit()
        log.info("mp job queued order_no=%s kind=%s", body.order_no, body.kind)
        # 照片此时应已传完，同步登记到认证服务真人素材组（文档第 3 步，失败不挡任务）
        _ifocus_sync_assets(conn, body.order_no)
        return JSONResponse({"ok": True, "status": "queued"})
    finally:
        conn.close()


# ---------------- 微信虚拟支付（代币模式） ----------------
# 商品即额度：用户付 4/52 币 → 到账 1/20 张 paid_count。
# 到账以 Midas 发货推送（/api/mp/vpay/notify）为准，客户端 confirm 为补偿通道（内测期信任客户端
# 成功回调，后台可用 MP「虚拟支付 → 交易订单」对账；正式放量前应加平台查单核验）。

def _vp_appkey() -> str:
    return VP_APP_KEY_SANDBOX if VP_ENV == 1 else VP_APP_KEY


def _vp_hmac(data: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def _vp_openid(open_token: str) -> str:
    return open_token[3:] if open_token.startswith("wx-") else ""


def _vp_grant(conn: sqlite3.Connection, pay: sqlite3.Row) -> None:
    """到账（幂等）：created → paid 才加额度。"""
    cur = conn.execute(
        "UPDATE mp_pay_orders SET status='paid', paid_at=? WHERE out_trade_no=? AND status='created'",
        (_now(), pay["out_trade_no"]))
    if cur.rowcount == 1:
        conn.execute(
            "UPDATE mp_orders SET paid_count=paid_count+?, updated_at=? WHERE order_no=?",
            (pay["grant_count"], _now(), pay["order_no"]))
        log.info("vpay 到账 out_trade_no=%s order_no=%s +%d 张",
                 pay["out_trade_no"], pay["order_no"], pay["grant_count"])


class MpVpayPrepareIn(BaseModel):
    order_no: str = Field(min_length=6, max_length=40)
    product: str = Field(min_length=2, max_length=20)
    open_token: str = Field(min_length=6, max_length=120)
    platform: str = "android"


@app.post("/api/mp/vpay/prepare")
def mp_vpay_prepare(body: MpVpayPrepareIn) -> JSONResponse:
    """下单并签名：signData/paySig/signature 三要素给 wx.requestVirtualPayment。"""
    if not VP_OFFER_ID or not _vp_appkey():
        raise HTTPException(status_code=503, detail="虚拟支付未配置（VP_OFFER_ID/VP_APP_KEY）")
    product = VP_PRODUCTS.get(body.product)
    if not product:
        raise HTTPException(status_code=400, detail="未知商品")
    openid = _vp_openid(body.open_token)
    conn = _db()
    try:
        if not openid:
            raise HTTPException(status_code=401, detail="支付需要微信登录态，请重启小程序后再试")
        sess = conn.execute(
            "SELECT session_key FROM mp_sessions WHERE openid=?", (openid,)).fetchone()
        if not sess:
            raise HTTPException(status_code=401, detail="登录态已过期，请重启小程序后再试")
        if not _mp_get_order(conn, body.order_no):
            raise HTTPException(status_code=404, detail="订单不存在")
        platform = body.platform if body.platform in ("android", "ios", "windows", "mac") else "android"
        out_trade_no = f"VP{int(time.time())}{secrets.token_hex(3)}".upper()
        sign_data = json.dumps({
            "offerId": VP_OFFER_ID,
            "buyQuantity": product["coins"],
            "env": VP_ENV,
            "currencyType": "CNY",
            "platform": platform,
            "productId": "",
            "goodsPrice": "",
            "outTradeNo": out_trade_no,
            "attach": body.order_no,
        }, separators=(",", ":"))
        conn.execute(
            "INSERT INTO mp_pay_orders(out_trade_no,order_no,openid,product,coins,grant_count,status,created_at)"
            " VALUES(?,?,?,?,?,?,'created',?)",
            (out_trade_no, body.order_no, openid, body.product,
             product["coins"], product["grant"], _now()))
        conn.commit()
        return JSONResponse({
            "ok": True,
            "signData": sign_data,
            "paySig": _vp_hmac("requestVirtualPayment&" + sign_data, _vp_appkey()),
            "signature": _vp_hmac(sign_data, sess[0]),
            "mode": "short_series_coin",
            "outTradeNo": out_trade_no,
        })
    finally:
        conn.close()


class MpVpayConfirmIn(BaseModel):
    out_trade_no: str = Field(min_length=8, max_length=64)
    open_token: str = Field(min_length=6, max_length=120)


@app.post("/api/mp/vpay/confirm")
def mp_vpay_confirm(body: MpVpayConfirmIn) -> JSONResponse:
    """客户端支付成功后的到账确认（Midas 推送可能延迟/缺失时的补偿通道，幂等）。"""
    conn = _db()
    conn.row_factory = sqlite3.Row
    try:
        pay = conn.execute(
            "SELECT * FROM mp_pay_orders WHERE out_trade_no=?", (body.out_trade_no,)).fetchone()
        if not pay:
            raise HTTPException(status_code=404, detail="支付单不存在")
        if pay["openid"] != _vp_openid(body.open_token):
            raise HTTPException(status_code=403, detail="支付单不属于当前用户")
        _vp_grant(conn, pay)
        conn.commit()
        order = _mp_get_order(conn, pay["order_no"])
        return JSONResponse({"ok": True, "paid_count": order["paid_count"] if order else 0})
    finally:
        conn.close()


@app.post("/api/mp/vpay/notify")
async def mp_vpay_notify(request: Request) -> JSONResponse:
    """Midas 发货推送：验签（hmac(appkey, uri&body)）→ 到账。头里没有签名时仅记录不处理。"""
    raw = (await request.body()).decode("utf-8", "replace")
    sig = (request.headers.get("Wechatpay-Signature") or request.headers.get("X-Pay-Sig")
           or request.headers.get("pay-sig") or "")
    log.info("vpay notify headers=%s body=%s", dict(request.headers), raw[:800])
    expected = _vp_hmac("/api/mp/vpay/notify&" + raw, _vp_appkey()) if _vp_appkey() else ""
    if not sig or not hmac.compare_digest(sig, expected):
        log.warning("vpay notify 验签不通过（sig=%s），仅记录", sig[:16])
        return JSONResponse({"code": "FAIL", "message": "sign mismatch"})
    try:
        data = json.loads(raw)
    except ValueError:
        return JSONResponse({"code": "FAIL", "message": "bad json"})
    out_trade_no = (data.get("out_trade_no") or data.get("outTradeNo")
                    or (data.get("order") or {}).get("out_trade_no") or "")
    conn = _db()
    conn.row_factory = sqlite3.Row
    try:
        pay = conn.execute(
            "SELECT * FROM mp_pay_orders WHERE out_trade_no=?", (out_trade_no,)).fetchone()
        if pay:
            _vp_grant(conn, pay)
            conn.commit()
    finally:
        conn.close()
    return JSONResponse({"code": "SUCCESS", "message": "OK"})


@app.get("/api/mp/me")
def mp_me(order_no: str) -> JSONResponse:
    """「我的」页聚合：订单状态 + 认证 + 上传照片分组 + 生成记录 + 额度。"""
    conn = _db()
    try:
        order = _mp_get_order(conn, order_no)
        if not order:
            raise HTTPException(status_code=404, detail="订单不存在")
        uploads = {"A": [], "B": []}
        for contact, role in ((order_no, "A"), (f"{order_no}-B", "B")):
            rows = conn.execute(
                "SELECT oss_key, created_at, slot FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
                " ORDER BY id DESC LIMIT 12", (contact,)).fetchall()
            uploads[role] = [
                {"url": oss_signed_get_url(r[0], expire=3600), "key": r[0], "time": r[1],
                 "slot": r[2] or ""} for r in rows
            ]
        photos = []
        for r in conn.execute(
                "SELECT id, kind, result_json, created_at FROM mp_jobs"
                " WHERE order_no=? AND status='done' AND kind != 'face_sheet'"
                " ORDER BY id DESC LIMIT 200",  # 反馈 #31：20 条窗口会把老成片挤出相册
                (order_no,)).fetchall():
            result = json.loads(r[2]) if r[2] else {}
            if result.get("url"):
                photos.append({
                    "job": r[0], "kind": r[1], "url": result["url"], "key": result.get("oss_key", ""), "time": r[3],
                    "label": {"makeup_photo": "定妆照", "free_photo": "婚纱照",
                              "solo_photo": "个人写真", "paid_photo": "付费成片",
                              "face_sheet": "人脸三视图"}.get(r[1], r[1]),
                })
            # 系列整组（template_series）结果在 result.urls 数组里，逐张入列（反馈 #25）
            for item in result.get("urls") or []:
                if isinstance(item, dict) and item.get("url"):
                    photos.append({
                        "job": r[0], "kind": r[1], "url": item["url"], "key": item.get("oss_key", ""),
                        "time": r[3], "label": "系列组图",
                    })
        return JSONResponse({
            "ok": True,
            "order": {
                "order_no": order["order_no"], "mode": order["mode"],
                "status": order["status"], "auth_ok": order["auth_ok"],
                "members": order["members"], "share_token": order["share_token"],
                "created_at": order["created_at"],
            },
            "quota": {
                "free_total": order["free_quota"],
                "free_left": max(0, order["free_quota"] - (order["free_used"] or 0)),
                "paid_left": order["paid_count"],
            },
            "uploads": uploads,
            "photos": photos,
        })
    finally:
        conn.close()


# ------------------------------------------------------------------
# 小程序对话接口：自然语言 → M3 意图路由 → 替用户操作
# ------------------------------------------------------------------
_MP_CHAT_SYS = """你是「徐大恩 LuckyNemo」小程序的 AI 小助手，语气温柔、专业、简短（reply ≤80 字）。
你陪用户走完拍摄流程：选模式(婚纱照couple/个人写真solo) → 真人认证 → 上传照片 → 定妆 → 选服装场景 → 选动作神态 → 出图。
听懂用户的自然语言，替 TA 操作或回答。

【订单状态】
{state}

【最近对话】
{dialog}

【可选资产】
{assets}

【输出要求】只输出 JSON，不要 markdown 代码块：
{{"reply": "对用户说的话", "action": {{...}}}}
action 只能是以下之一：
- {{"type": "navigate", "page": "/pages/upload/upload"}} 引导去页面（可选页：/pages/upload/upload 上传、/pages/makeup/makeup 定妆、/pages/wardrobe/wardrobe 选服装场景、/pages/pose/pose 选动作神态）
- {{"type": "update_selection", "fields": {{"scenes": ["场景名"], "poses": ["动作名"], "set_id": "set-01", "makeup_id": "hz002", "makeup_notes": "用户自己的化妆要求", "heights": "两人身高信息"}}}} 修改选择（只能用可选资产里的值；makeup_notes 是自由文本，记录用户提的化妆意见，如"卧蚕明显一点""唇色要豆沙色"；heights 是自由文本，用户提到身高时记录，如"新郎183cm新娘165cm"，用于还原身高差）
- {{"type": "regenerate_makeup", "instruction": "腮红淡一点"}} 按修正指令重新出定妆照
- {{"type": "makeup_photo", "who": "me或partner", "makeup_id": "hz214", "note": "用户的修饰要求（可空）"}} 对话里直接出定妆照：用户发照片说"用这张修/做一张定妆照""修一张原始图作为定妆照"时用——底图=用户刚发的图；who 按"这是谁的定妆照"判断（新郎/老公/男方=操作者本人时用 me，新娘/老婆/伴侣用 partner，参考对话里用户的自称，拿不准先问）；makeup_id 用可选妆造里的值，用户说"原始/原图/最像本人"或没指定妆容时默认原图直出版（女 hz214/男 hz108）；note 带用户的附加修饰要求（如"把脸上的汗去掉"）。用这个动作时 reply 说明"正在生成定妆照"
- {{"type": "show_result"}} 把最新生成好的成片/定妆照发给用户看
- {{"type": "show_uploads"}} 把用户已上传的照片发给用户看
- {{"type": "set_mode", "mode": "solo"}} 切换拍摄模式（solo=个人写真，couple=婚纱照）
- {{"type": "delete_assets", "target": "reset"}} 删除资产：reset=删除全部上传照片+生成图并重置流程（用户说"全部删掉重新开始"时用）；all_uploads=只删全部上传照片；all_photos=只删全部生成图
- {{"type": "submit_feedback", "fb_type": "bug", "text": "整理后的反馈内容"}} 用户确认后提交意见反馈（fb_type: bug/feature/other）
- {{"type": "add_base_photo", "who": "me或partner"}} 把用户刚发的图片保存为拍摄底图。用户发照片说明是谁的（"这是新娘/新郎/我老婆/他的照片"）或说"传照片/做底图/新底图/重新上传/补传"时**必须用**（严禁只回"已收到"却不保存）：who=me 指照片是用户本人，partner 指是用户的伴侣（新娘/新郎/老婆/老公/对象），按对话语境判断；拿不准照片里是谁时，先用 none 问一句"照片是您本人还是您伴侣？"
- {{"type": "custom_moka", "description": "用户真实需求的完整描述", "mode": "couple或solo_f或solo_m"}} 定制专属大片：**只有用户明确说要"做模板/定制专属大片"才用**。description 必须写用户的真实需求（把多轮补充合并进来，范例图需求就写清"参考我发的图"+用户补充，严禁照抄示例占位文字）；mode 按画面人数推断：双人=couple、女生单人=solo_f、男生单人=solo_m，推断不出先用 none 问一句
- {{"type": "generate_photo", "mode": "couple或solo_f或solo_m", "note": "用户的调整要求（可空）"}} 直接出片：用户说"用这张出片/帮我生成/用最新定妆照出一张"时用，系统会把用户刚发的图（或最近发的图/专属大片）当模板 + 用最新定妆照一键同款出图。用户从来没发过图时先别用，引导 TA 发图或去挑同款大片
- {{"type": "duo_photo", "note": "合照场景/氛围要求（可空）"}} 生成双人合照：用户发两个人的照片（两张单人照或一张现成合照），说"把照片里的人生成一张合照/帮我们俩合拍一张"时用，系统用照片里的真人直接生成两人亲密合照
- {{"type": "edit_photo", "instruction": "去掉眼镜"}} 修改已生成的成片：用户对刚出的图提局部修改（去眼镜/换个表情/背景亮一点/去掉某个东西）时用，instruction 是具体修改点。注意：这是改"成片"，不是改定妆照——用户说改妆容/重新定妆才用 regenerate_makeup
- {{"type": "none"}} 纯回答

【重要】用户意图是操作时，action 必须给对应类型，reply 不许承诺 action 做不到的事：
- "补充/再传照片" → navigate 到 /pages/upload/upload
- "看生成的图/成片/再发我看看" → show_result
- "看我上传的照片" → show_uploads
- "我想拍个人写真/换成单人" → set_mode solo；"拍婚纱照" → set_mode couple
- "删掉所有照片/清空重新开始" → delete_assets reset
- "不像我/不满意" → 先安抚，再用 regenerate_makeup 带上用户的修正点
- "用这张出片/帮我生成/出一张看看" → generate_photo
- "把这两张照片里的人生成一张合照/帮我俩合拍一张" → duo_photo（真人生成合照）；用户明确说"做模板/定制专属大片"才用 custom_moka，两者别混
- "改一下刚出的图/去个眼镜/这张去掉XX" → edit_photo（改成片）；"改妆容/重新定妆" → regenerate_makeup（改定妆照），别混
- "用这张修/做一张定妆照""修一张原始图作为定妆照" → makeup_photo（who 按对话判断，给对 makeup_id）
- 【禁止光说不给按钮】reply 里说"点这里/点下面"时，action 必须同时给对应按钮（navigate 或 generate_photo）；AI 答应在做的操作必须有 action 落地，绝不允许只回"好的，我明白了"却什么都不做

【意见反馈流程】用户报 bug 或提功能想法时，先追问细节（action 用 none），把问题整理成一句话问用户"我帮你把这条反馈提交给团队吗？"。用户明确同意（好/提交/嗯）→ submit_feedback，text 是你整理后的完整描述（含用户补充的细节）。用户之前的消息里带图的（历史中标注[N张图]），反馈会一并带上。
【图片意图】用户发图时（消息里会注明带了几张图），谨慎判断用途：
- 用户发图说"想要这样的/照这个做/定制同款/做成这样的模板" → custom_moka（图会作为范例一起提交）；
- 用户发图说明是谁的照片（"这是新娘/新郎/我老婆的照片"）或说"做底图/新底图/重新上传/补传/用来生成/用这张拍" → add_base_photo 带上正确的 who，**不许只回"已收到"不保存**；
- 【硬约束】消息里出现"底图/新底图/上传/补传/重新上传"字样时，一律 add_base_photo，**严禁 custom_moka**——"底图"是拍摄用的人脸照片，不是大片范例图；
- UI 截图、效果问题图、带"你看这个/怎么回事"的图，一律视为反馈素材，走意见反馈流程；
- 拿不准时先问一句"这张图是反馈问题的截图，还是当拍摄底图？"，别擅自处理。"""


def _mp_chat_context(conn: sqlite3.Connection, order_no: str) -> tuple[dict, dict, dict | None]:
    """组装对话上下文：订单状态 + 可选资产 + 最近一次定妆任务。"""
    order = _mp_get_order(conn, order_no)
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    photo_count = conn.execute(
        "SELECT COUNT(*) FROM uploads WHERE contact=? AND content_type LIKE 'image/%'",
        (order_no,)).fetchone()[0]
    row = conn.execute(
        "SELECT payload_json, status FROM mp_jobs WHERE order_no=? AND kind='makeup_photo' ORDER BY id DESC LIMIT 1",
        (order_no,)).fetchone()
    makeup_job = None
    if row:
        makeup_job = {"status": row[1], "payload": json.loads(row[0])}
    site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
    try:
        makeup = _load_makeup_catalog(site)
        makeup_f = "、".join(f"{m['id']}{m['name']}" for m in makeup if m["gender"] == "female")
        makeup_m = "、".join(f"{m['id']}{m['name']}" for m in makeup if m["gender"] == "male")
    except Exception:
        makeup_f = makeup_m = "（读取失败）"
    sets_js = (site / "wardrobe/data.js").read_text(encoding="utf-8")
    scenes_js = (site / "scenes/data.js").read_text(encoding="utf-8")
    set_ids = re.findall(r'"id":\s*"(set-\d+)"', sets_js)
    scene_names = re.findall(r'"name":\s*"([^"]+)"', scenes_js)
    state = {
        "拍摄模式": order["mode"] or "未选（couple=婚纱照，solo=个人写真）",
        "认证": "、".join(
            f"{'创建者' if r == 'A' else '伴侣'}{'已认证' if order['members'].get(r, {}).get('auth_ok') else '未认证'}"
            for r in _mp_required_roles(order)),
        "已上传照片": f"{photo_count} 张",
        "定妆": (f"已定妆「{makeup_job['payload'].get('makeup_name')}」" if makeup_job
                 and makeup_job["status"] == "done" else "未定妆"),
        "已选": order["selection"] or "还没选",
    }
    state_text = "\n".join(f"- {k}：{v}" for k, v in state.items())
    assets_text = "\n".join([
        f"- 女士妆造：{makeup_f}", f"- 男士妆造：{makeup_m}",
        f"- 套装：{'、'.join(set_ids)}", f"- 场景：{'、'.join(scene_names[:30])}",
        f"- 动作(双人)：{'、'.join(p for g in MP_POSES.values() for p in g)}",
        f"- 动作(单人)：{'、'.join(p for g in MP_POSES_SOLO.values() for p in g)}",
    ])
    return order, {"state": state_text, "assets": assets_text}, makeup_job


def _mp_chat_user_text(body: MpChatIn) -> str:
    """用户消息 + 图片附注。"""
    text = body.message.strip() or "（只发了图片，没说话）"
    if body.images:
        text += f"\n[用户同时发了 {len(body.images)} 张图片]"
    return text


def _m3_chat(system: str, user: str) -> dict:
    """调 MiniMax 对话，期望返回 JSON 文本；容错解析。"""
    if not MINIMAX_KEY:
        raise HTTPException(status_code=500, detail="对话服务未配置（MINIMAX_API_KEY）")
    r = requests.post(
        f"{MINIMAX_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {MINIMAX_KEY}"},
        json={"model": "abab6.5s-chat", "max_tokens": 400, "temperature": 0.3,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=60,
    )
    data = r.json()
    text = data["choices"][0]["message"]["content"].strip()
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise


@app.post("/api/mp/chat")
def mp_chat(body: MpChatIn) -> JSONResponse:
    """自然语言对话：理解意图 → 回复 + 动作（跳转/改选择/重出定妆照）。"""
    conn = _db()
    try:
        order, ctx, makeup_job = _mp_chat_context(conn, body.order_no)
        dialog = "\n".join(body.history[-6:]) or "（本轮刚开始）"
        try:
            result = _m3_chat(_MP_CHAT_SYS.format(state=ctx["state"], assets=ctx["assets"], dialog=dialog),
                              _mp_chat_user_text(body))
        except HTTPException:
            raise
        except Exception as exc:
            log.warning("mp chat M3 失败：%s", exc)
            return JSONResponse({"ok": True, "reply": "我刚才走神了一下，你再说一次好吗？",
                                 "action": {"type": "none"}})
        reply = str(result.get("reply") or "我在呢～")
        action = result.get("action") if isinstance(result.get("action"), dict) else {"type": "none"}
        atype = action.get("type", "none")

        if atype == "update_selection":
            # 校验并合并到订单 selection（只接受资产库里的值）
            fields = action.get("fields") or {}
            sel = dict(order["selection"] or {})
            site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
            makeup_ids = {m["id"] for m in _load_makeup_catalog(site)}
            valid_scenes = set(re.findall(r'"name":\s*"([^"]+)"',
                                          (site / "scenes/data.js").read_text(encoding="utf-8")))
            valid_sets = set(re.findall(r'"id":\s*"(set-\d+)"',
                                        (site / "wardrobe/data.js").read_text(encoding="utf-8")))
            all_poses = {p for g in list(MP_POSES.values()) + list(MP_POSES_SOLO.values()) for p in g}
            if isinstance(fields.get("makeup_id"), str) and fields["makeup_id"] in makeup_ids:
                sel["makeup_id"] = fields["makeup_id"]
            if isinstance(fields.get("makeup_notes"), str) and fields["makeup_notes"].strip():
                sel["makeup_notes"] = fields["makeup_notes"].strip()[:200]
            # 身高信息（反馈 #27：还原两人身高差，生成时写进 prompt）
            if isinstance(fields.get("heights"), str) and fields["heights"].strip():
                sel["heights"] = fields["heights"].strip()[:100]
            if isinstance(fields.get("set_id"), str) and fields["set_id"] in valid_sets:
                sel["set_id"] = fields["set_id"]
            for key, valid in (("scenes", valid_scenes), ("poses", all_poses)):
                if isinstance(fields.get(key), list):
                    picked = [x for x in fields[key] if x in valid]
                    if picked:
                        sel[key] = picked
            conn.execute("UPDATE mp_orders SET selection_json=?, updated_at=? WHERE order_no=?",
                         (json.dumps(sel, ensure_ascii=False), _now(), body.order_no))
            conn.commit()
            action = {"type": "update_selection", "selection": sel}

        elif atype == "regenerate_makeup":
            # 在最近定妆配方上追加修正指令，重建定妆任务
            if not makeup_job:
                action = {"type": "navigate", "page": "/pages/makeup/makeup"}
            else:
                base = makeup_job["payload"]
                instruction = str(action.get("instruction") or "")[:200]
                new_prompt = (base.get("makeup_prompt", "") +
                              f"\n追加修正要求：{instruction}（在原配方基础上只改这一点，其余保持不变）")
                conn.execute(
                    "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (body.order_no, "makeup_photo",
                     json.dumps({**base, "makeup_prompt": new_prompt}, ensure_ascii=False),
                     "queued", _now(), _now()))
                conn.commit()
                action = {"type": "regenerate_makeup", "page": "/pages/makeup/makeup"}

        elif atype == "show_result":
            # 把最新的成片/定妆照发给用户看
            row = conn.execute(
                "SELECT result_json FROM mp_jobs WHERE order_no=? AND status='done'"
                " AND kind IN ('free_photo','solo_photo','makeup_photo') ORDER BY id DESC LIMIT 1",
                (body.order_no,)).fetchone()
            url = ""
            if row and row[0]:
                url = (json.loads(row[0]) or {}).get("url", "")
            if url:
                action = {"type": "show_result", "photos": [url]}
            else:
                action = {"type": "none"}
                reply = "你还没有生成好的照片哦，先跟我一步步来，马上就有啦～"

        elif atype == "show_uploads":
            # 把用户已上传的照片发给用户看
            rows = conn.execute(
                "SELECT oss_key FROM uploads WHERE contact LIKE ? AND content_type LIKE 'image/%'"
                " ORDER BY id DESC LIMIT 6",
                (f"{body.order_no}%",)).fetchall()
            if rows:
                action = {"type": "show_uploads",
                          "photos": [oss_signed_get_url(r[0], expire=3600) for r in rows]}
            else:
                action = {"type": "navigate", "page": "/pages/upload/upload"}
                reply = "你还没有上传照片呢，先传几张清晰的正脸照吧～"

        elif atype == "set_mode":
            mode = action.get("mode") if action.get("mode") in ("couple", "solo") else None
            if mode:
                _mp_touch(conn, body.order_no, mode=mode)
                _mp_recompute_auth(conn, body.order_no)
                action = {"type": "set_mode", "mode": mode}
            else:
                action = {"type": "none"}

        elif atype == "delete_assets":
            target = action.get("target", "reset")
            if target not in ("reset", "all_uploads", "all_photos"):
                target = "reset"
            deleted = _delete_assets(conn, body.order_no, target)
            action = {"type": "delete_assets", "target": target, "deleted": deleted}

        elif atype == "submit_feedback":
            fb_type = action.get("fb_type") if action.get("fb_type") in ("bug", "feature", "other") else "other"
            text = str(action.get("text") or body.message or "")[:1000]
            if not text:
                action = {"type": "none"}
            else:
                images = list(body.images[:3])
                if not images:
                    # 本条没发图：带上用户最近在聊天里发的图（反馈截图场景）
                    rows = conn.execute(
                        "SELECT oss_key FROM uploads WHERE contact=? ORDER BY id DESC LIMIT 3",
                        (f"{body.order_no}-chat",)).fetchall()
                    images = [r[0] for r in rows]
                conn.execute(
                    "INSERT INTO mp_feedback(order_no,type,text,images_json,created_at) VALUES(?,?,?,?,?)",
                    (body.order_no, fb_type, text,
                     json.dumps(images, ensure_ascii=False), _now()))
                conn.commit()
                log.info("mp chat feedback order_no=%s type=%s imgs=%d", body.order_no, fb_type, len(images))
                action = {"type": "submit_feedback", "fb_type": fb_type}

        elif atype == "add_base_photo":
            if not body.images:
                action = {"type": "none"}
                reply = "我还没收到图片哦，点输入框旁边的 📷 传一张试试～"
            else:
                # who=partner：照片是伴侣的，存进 B 相册（情侣生成按 A/B 双相册取图）
                who = action.get("who") if action.get("who") in ("me", "partner") else "me"
                contact = body.order_no if who == "me" else f"{body.order_no}-B"
                added = 0
                for key in body.images[:3]:
                    # 去重只看目标相册：chat 上传会先在 -chat 暂存相册登记同 key，
                    # 全表去重会导致永远 added=0（反馈 #22 的根因）
                    exists = conn.execute(
                        "SELECT 1 FROM uploads WHERE oss_key=? AND contact=?", (key, contact)).fetchone()
                    if not exists:
                        conn.execute(
                            "INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                            " VALUES(?,?,?,?,?,?)",
                            (contact, Path(key).name, key, 0, "image/jpeg", _now()))
                        added += 1
                conn.commit()
                log.info("mp chat add_base_photo order_no=%s who=%s added=%d", body.order_no, who, added)
                action = {"type": "add_base_photo", "added": added, "who": who}
                if added:
                    reply += f"\n（已把 {added} 张保存为{'你的' if who == 'me' else '伴侣的'}拍摄底图 ✅）"

        elif atype == "makeup_photo":
            # 对话里直接出定妆照：刚发的图作底照 + 指定妆容（默认原图直出版）
            if not body.images:
                action = {"type": "none"}
                reply = "我还没收到图片哦，点输入框旁边的 📷 传一张试试～"
            else:
                who = action.get("who") if action.get("who") in ("me", "partner") else "me"
                role = "A" if who == "me" else "B"
                if not order["members"].get(role, {}).get("auth_ok"):
                    action = {"type": "none"}
                    reply += "\n（出定妆照前，需要本人先完成真人认证哦，去「我的」页核验一下）"
                else:
                    # 底图先存进对应相册（A/B 分存）
                    contact = body.order_no if role == "A" else f"{body.order_no}-B"
                    base_key = body.images[0]
                    if not conn.execute("SELECT 1 FROM uploads WHERE oss_key=? AND contact=?",
                                        (base_key, contact)).fetchone():
                        conn.execute(
                            "INSERT INTO uploads(contact,filename,oss_key,size,content_type,created_at)"
                            " VALUES(?,?,?,?,?,?)",
                            (contact, Path(base_key).name, base_key, 0, "image/jpeg", _now()))
                    # 妆容：M3 给的 makeup_id 优先，缺省按性别给原图直出版
                    site = Path(_env("SITE_DIR", "/var/www/luckynemo"))
                    catalog = _load_makeup_catalog(site)
                    style = next((s for s in catalog if s["id"] == action.get("makeup_id")), None)
                    if not style:
                        gender = "male" if action.get("gender") == "male" else "female"
                        style = next(s for s in catalog
                                     if s["id"] == ("hz108" if gender == "male" else "hz214"))
                    # 定妆限量与 /api/mp/job 一致：每单免费 10 次，超出扣免费额度
                    makeup_count = conn.execute(
                        "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='makeup_photo'",
                        (body.order_no,)).fetchone()[0]
                    if makeup_count >= 10:
                        if (order["free_used"] or 0) < order["free_quota"]:
                            _mp_touch(conn, body.order_no, free_used=(order["free_used"] or 0) + 1)
                        else:
                            action = {"type": "none"}
                            reply += "\n（免费定妆次数用完啦，充值后再继续）"
                    if action.get("type") != "none":
                        payload = {"role": role, "makeup_id": style["id"], "makeup_name": style["name"],
                                   "makeup_prompt": style["prompt"], "gender": style.get("gender", "female"),
                                   "engine": "seedream", "base_key": base_key,
                                   "makeup_notes": str(action.get("note") or "")[:200],
                                   "hairstyle": "", "hairstyle_name": ""}
                        conn.execute(
                            "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at)"
                            " VALUES(?,?,?,?,?,?)",
                            (body.order_no, "makeup_photo",
                             json.dumps(payload, ensure_ascii=False), "queued", _now(), _now()))
                        conn.commit()
                        log.info("mp chat makeup_photo order_no=%s role=%s makeup=%s",
                                 body.order_no, role, style["id"])
                        action = {"type": "makeup_photo", "page": "/pages/makeup/makeup"}
                        reply += f"\n（正在用这张照片生成「{style['name']}」定妆照，去定妆页看进度 ✅）"

        elif atype == "custom_moka":
            # 定制专属模卡：描述/范例图 → 队列生成（worker 做安全审核+质检重试），每单免费 3 次
            description = str(action.get("description") or body.message or "")[:500].strip()
            mode = action.get("mode") if action.get("mode") in ("couple", "solo_f", "solo_m") else ""
            if not mode:
                mode = "couple" if order["mode"] == "couple" else "solo_f"
            if not description and not body.images:
                action = {"type": "none"}
                reply = "描述一下你想要的画面，或者发一张喜欢的样片给我，就能定制啦～"
            else:
                diy_count = conn.execute(
                    "SELECT COUNT(*) FROM mp_jobs WHERE order_no=? AND kind='custom_moka'",
                    (body.order_no,)).fetchone()[0]
                if diy_count >= 3:
                    action = {"type": "none"}
                    reply = "这张单的免费定制次数（3 次）用完啦，去同款大片库挑一张现成的也很出片哦～"
                else:
                    conn.execute(
                        "INSERT INTO mp_jobs(order_no,kind,payload_json,status,created_at,updated_at)"
                        " VALUES(?,?,?,?,?,?)",
                        (body.order_no, "custom_moka",
                         json.dumps({"description": description, "mode": mode,
                                     "example_keys": list(body.images[:1])}, ensure_ascii=False),
                         "queued", _now(), _now()))
                    conn.commit()
                    log.info("mp chat custom_moka order_no=%s mode=%s", body.order_no, mode)
                    action = {"type": "custom_moka", "mode": mode}

        elif atype == "generate_photo":
            # 直接出片：把用户刚发的图（或最近聊天图/DIY 模卡）当模板 + 最新定妆照锚点，
            # 解析出参数交给前端走 generating 页（任务创建与额度校验在 /api/mp/job 完成）
            mode = action.get("mode") if action.get("mode") in ("couple", "solo_f", "solo_m") else ""
            couple = mode == "couple" or (not mode and order["mode"] == "couple")
            tpl_key = body.images[0] if body.images else ""
            if not tpl_key:
                row = conn.execute(
                    "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
                    " ORDER BY id DESC LIMIT 1", (f"{body.order_no}-chat",)).fetchone()
                tpl_key = row[0] if row else ""
            if not tpl_key:
                row = conn.execute(
                    "SELECT result_json FROM mp_jobs WHERE order_no=? AND kind='custom_moka'"
                    " AND status='done' ORDER BY id DESC LIMIT 1", (body.order_no,)).fetchone()
                tpl_key = (json.loads(row[0]) or {}).get("oss_key", "") if row and row[0] else ""
            if not tpl_key:
                action = {"type": "none"}
                reply = "把想做成模板的照片发给我，或先去同款大片库挑一张，我马上给你出片～"
            else:
                anchors = {}
                for pj, rj in conn.execute(
                        "SELECT payload_json, result_json FROM mp_jobs WHERE order_no=?"
                        " AND kind='makeup_photo' AND status='done' ORDER BY id DESC LIMIT 10",
                        (body.order_no,)).fetchall():
                    role = (json.loads(pj) or {}).get("role", "A") if pj else "A"
                    if role not in anchors and rj:
                        anchors[role] = (json.loads(rj) or {}).get("oss_key", "")
                action = {"type": "generate_photo", "template_key": tpl_key,
                          "mode": "couple" if couple else "solo",
                          "anchor_key": anchors.get("A", ""),
                          "anchor_key_b": anchors.get("B", "") if couple else "",
                          "note": str(action.get("note") or "")[:100]}

        elif atype == "edit_photo":
            # 成片局部修图：取最新成片做底图 + 用户修改指令，交给前端走 generating 页
            instruction = str(action.get("instruction") or "")[:200].strip()
            row = conn.execute(
                "SELECT result_json FROM mp_jobs WHERE order_no=? AND status='done'"
                " AND kind IN ('free_photo','solo_photo','template_photo','edit_photo')"
                " ORDER BY id DESC LIMIT 1", (body.order_no,)).fetchone()
            base_key = (json.loads(row[0]) or {}).get("oss_key", "") if row and row[0] else ""
            if not instruction:
                action = {"type": "none"}
                reply = "想改哪里？告诉我具体一点，比如\"去掉眼镜\"\"背景亮一点\"～"
            elif not base_key:
                action = {"type": "none"}
                reply = "你还没有生成好的成片哦，先出一张再来改～"
            else:
                action = {"type": "edit_photo", "base_key": base_key, "instruction": instruction}

        elif atype == "duo_photo":
            # 双人合照：用户发的两个人照片（本条或最近聊天图）直接生成亲密合照
            images = list(body.images[:2])
            if not images:
                rows = conn.execute(
                    "SELECT oss_key FROM uploads WHERE contact=? AND content_type LIKE 'image/%'"
                    " ORDER BY id DESC LIMIT 2", (f"{body.order_no}-chat",)).fetchall()
                images = [r[0] for r in rows]
            if not images:
                action = {"type": "none"}
                reply = "把你们的照片发给我（两张单人照或一张合照），我马上给你们合拍～"
            else:
                action = {"type": "duo_photo", "images": images,
                          "note": str(action.get("note") or "")[:100]}

        return JSONResponse({"ok": True, "reply": reply, "action": action})
    finally:
        conn.close()


@app.post("/api/wardrobe/selection")
def wardrobe_selection(body: WardrobeSelectionIn) -> JSONResponse:
    """试衣间选择：JSON 存 OSS selections/ 前缀，供 Nemo Studio 读取生成定妆照。"""
    if not body.selection:
        raise HTTPException(status_code=400, detail="selection 不能为空")
    day = datetime.now().strftime("%Y%m%d")
    who = _sanitize_segment(body.contact)
    key = f"selections/{day}/{who}/{uuid.uuid4().hex[:8]}.json"
    try:
        payload = json.dumps(
            {"contact": body.contact, "selection": body.selection, "created_at": _now()},
            ensure_ascii=False, indent=2,
        )
        oss_put_object(key, payload.encode("utf-8"))
    except Exception as exc:
        log.error("wardrobe selection OSS 写入失败 contact=%s err=%s", body.contact, exc)
        raise HTTPException(status_code=502, detail="选择保存失败，请稍后再试") from exc
    log.info("wardrobe selection saved contact=%s key=%s", body.contact, key)
    return JSONResponse({"ok": True, "key": key})
