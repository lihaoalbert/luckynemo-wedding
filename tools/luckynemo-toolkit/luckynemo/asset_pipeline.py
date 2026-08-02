"""asset_pipeline：火山方舟私域虚拟人像素材库（Assets API）管理。

用途：
- 把虚拟角色（或每单授权素材）注册进方舟素材库，拿到 asset:// ID
- 入库素材在 Seedance 2.0 视频生成中以 reference_image 角色引用，
  是过反 Deepfake 审核的正规通道（未入库人像素材会被拦截）

鉴权说明：
- Assets API 走火山引擎 IAM AccessKey（VOLC_ACCESS_KEY_ID / VOLC_SECRET_ACCESS_KEY），
  与方舟推理的 ARK_API_KEY 不是一套；火山 V4 签名（HMAC-SHA256），
  官方 SDK 生成代码未覆盖 Assets 接口，故此处直连 universal API。
- CreateAsset 要求素材有可访问 URL：本模块先把本地文件 PUT 到阿里云 OSS
  （沿用 server/.env 的 OSS_* 配置），再用签名 GET URL 提交入库。

用法：
    python -m luckynemo.asset_pipeline create-group --name 陈奕辰 --desc "demo 虚拟角色"
    python -m luckynemo.asset_pipeline upload --group group-xxx --file ./全身.png --name chen_full
    python -m luckynemo.asset_pipeline list-assets --group group-xxx
"""

from __future__ import annotations

import argparse
import base64
import datetime
import email.utils
import hashlib
import hmac
import json
import mimetypes
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

from . import config

TOOLKIT_ROOT = Path(__file__).resolve().parent.parent
SERVER_ENV = TOOLKIT_ROOT.parent.parent / "server" / ".env"

VOLC_API = "https://open.volcengineapi.com/"
VOLC_SERVICE = "ark"
VOLC_REGION = "cn-beijing"
ASSETS_VERSION = "2024-01-01"


# ------------------------------------------------------------------
# 配置读取（toolkit .env 走 config，server/.env 只取 OSS_*）
# ------------------------------------------------------------------
def _load_server_env() -> dict[str, str]:
    """解析 server/.env（不打印内容），只供 OSS 托管中转用。"""
    result: dict[str, str] = {}
    if SERVER_ENV.is_file():
        for line in SERVER_ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _volc_keys() -> tuple[str, str]:
    config.load_dotenv()
    ak = os.environ.get("VOLC_ACCESS_KEY_ID", "").strip()
    sk = os.environ.get("VOLC_SECRET_ACCESS_KEY", "").strip()
    if not ak or not sk:
        raise RuntimeError("缺少 VOLC_ACCESS_KEY_ID / VOLC_SECRET_ACCESS_KEY（见 README 素材库章节）")
    return ak, sk


# ------------------------------------------------------------------
# 火山 V4 签名（universal API 直连）
# ------------------------------------------------------------------
def _volc_sign_and_call(action: str, body: dict, *, version: str = ASSETS_VERSION) -> dict:
    ak, sk = _volc_keys()
    payload = json.dumps(body, ensure_ascii=False).encode()
    payload_hash = hashlib.sha256(payload).hexdigest()

    now = datetime.datetime.now(datetime.timezone.utc)
    x_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    query = f"Action={action}&Version={version}"
    signed_headers = "content-type;host;x-content-sha256;x-date"
    canonical_headers = (
        f"content-type:application/json\nhost:open.volcengineapi.com\n"
        f"x-content-sha256:{payload_hash}\nx-date:{x_date}\n"
    )
    canonical_request = f"POST\n/\n{query}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    credential_scope = f"{date_stamp}/{VOLC_REGION}/{VOLC_SERVICE}/request"
    string_to_sign = (
        f"HMAC-SHA256\n{x_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    )

    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k_date = _hmac(sk.encode(), date_stamp)
    k_region = _hmac(k_date, VOLC_REGION)
    k_service = _hmac(k_region, VOLC_SERVICE)
    k_signing = _hmac(k_service, "request")
    signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-Date": x_date,
        "X-Content-Sha256": payload_hash,
        "Authorization": (
            f"HMAC-SHA256 Credential={ak}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    resp = requests.post(f"{VOLC_API}?{query}", data=payload, headers=headers, timeout=60)
    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"火山 API 非 JSON 响应：HTTP {resp.status_code} {resp.text[:300]}")
    err = data.get("ResponseMetadata", {}).get("Error") or data.get("Error")
    if err:
        raise RuntimeError(f"火山 API {action} 失败：{json.dumps(err, ensure_ascii=False)}")
    return data.get("Result", data)


# ------------------------------------------------------------------
# OSS 托管中转（CreateAsset 需要可访问 URL）
# ------------------------------------------------------------------
def _oss_config() -> dict[str, str]:
    env = _load_server_env()
    bucket = env.get("OSS_BUCKET", "ibi-private")
    region = env.get("OSS_REGION", "oss-cn-shanghai")
    for k in ("OSS_ACCESS_KEY_ID", "OSS_ACCESS_KEY_SECRET"):
        if not env.get(k):
            raise RuntimeError(f"server/.env 缺少 {k}，无法托管素材文件")
    return {
        "ak": env["OSS_ACCESS_KEY_ID"],
        "sk": env["OSS_ACCESS_KEY_SECRET"],
        "endpoint": f"https://{bucket}.{region}.aliyuncs.com",
        "bucket": bucket,
    }


def _oss_sign(secret: str, s: str) -> str:
    return base64.b64encode(hmac.new(secret.encode(), s.encode(), hashlib.sha1).digest()).decode()


def oss_stage_url(local_file: Path, *, prefix: str = "ark-assets", expire_seconds: int = 7200) -> str:
    """本地文件 PUT 到 OSS，返回带签名的临时 GET URL（供火山拉取入库）。"""
    cfg = _oss_config()
    content_type = mimetypes.guess_type(local_file.name)[0] or "application/octet-stream"
    key = f"{prefix}/{uuid.uuid4().hex[:8]}-{local_file.name}"
    resource = f"/{cfg['bucket']}/{key}"

    date = email.utils.formatdate(usegmt=True)
    string_to_sign = f"PUT\n\n{content_type}\n{date}\n{resource}"
    headers = {
        "Date": date,
        "Content-Type": content_type,
        "Authorization": f"OSS {cfg['ak']}:{_oss_sign(cfg['sk'], string_to_sign)}",
    }
    r = requests.put(f"{cfg['endpoint']}/{quote(key)}", data=local_file.read_bytes(),
                     headers=headers, timeout=120)
    if r.status_code >= 300:
        raise RuntimeError(f"OSS PUT 失败：HTTP {r.status_code} {r.text[:200]}")

    expires = str(int(time.time()) + expire_seconds)
    get_sign = _oss_sign(cfg["sk"], f"GET\n\n\n{expires}\n{resource}")
    return (
        f"{cfg['endpoint']}/{quote(key)}?Expires={expires}"
        f"&OSSAccessKeyId={cfg['ak']}&Signature={quote(get_sign, safe='')}"
    )


# ------------------------------------------------------------------
# Assets API 封装
# ------------------------------------------------------------------
def create_group(name: str, description: str = "") -> str:
    """创建素材资产组合，返回 group id。"""
    result = _volc_sign_and_call("CreateAssetGroup", {
        "Name": name, "Description": description, "GroupType": "AIGC",
    })
    group_id = result.get("Id")
    print(f"素材组已创建：{name} -> {group_id}")
    return group_id


def upload_asset(group_id: str, local_file: Path, *, name: str = "",
                 asset_type: str = "Image", timeout: float = 600.0) -> str:
    """本地文件经 OSS 中转入库，轮询至 Active，返回 asset id。"""
    print(f"上传中转：{local_file.name} -> OSS ...")
    url = oss_stage_url(local_file)
    result = _volc_sign_and_call("CreateAsset", {
        "GroupId": group_id, "URL": url, "AssetType": asset_type,
        "Name": name or local_file.stem,
    })
    asset_id = result.get("Id")
    print(f"已提交入库：{asset_id}，等待审核（Processing -> Active）...")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(5)
        info = _volc_sign_and_call("GetAsset", {"Id": asset_id})
        status = info.get("Status")
        if status == "Active":
            print(f"入库完成：{name or local_file.stem} -> asset://{asset_id}")
            return asset_id
        if status == "Failed":
            raise RuntimeError(f"入库审核失败：{asset_id} {json.dumps(info, ensure_ascii=False)[:300]}")
    raise TimeoutError(f"入库审核超时（{timeout}s）：{asset_id}")


def list_assets(group_id: str | None = None) -> None:
    body: dict = {"PageNumber": 1, "PageSize": 100, "Filter": {"GroupType": "AIGC"}}
    if group_id:
        body["Filter"]["GroupIds"] = [group_id]
    result = _volc_sign_and_call("ListAssets", body)
    for item in result.get("Items", []):
        print(f"{item.get('Status'):12} {item.get('Id')}  {item.get('Name') or ''}  ({item.get('AssetType')})")


def list_groups() -> None:
    result = _volc_sign_and_call("ListAssetGroups", {
        "PageNumber": 1, "PageSize": 100, "Filter": {"GroupType": "AIGC"}})
    for item in result.get("Items", []):
        print(f"{item.get('Id')}  {item.get('Name')}  ({item.get('GroupType')})")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m luckynemo.asset_pipeline",
                                     description="方舟私域虚拟人像素材库管理")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("create-group", help="创建素材组")
    p.add_argument("--name", required=True)
    p.add_argument("--desc", default="")

    p = sub.add_parser("upload", help="上传素材入库（轮询至 Active）")
    p.add_argument("--group", required=True)
    p.add_argument("--file", required=True, type=Path)
    p.add_argument("--name", default="")
    p.add_argument("--type", default="Image", choices=["Image", "Video", "Audio"])

    p = sub.add_parser("list-assets", help="列出素材")
    p.add_argument("--group", default=None)

    sub.add_parser("list-groups", help="列出素材组")

    args = parser.parse_args()
    if args.cmd == "create-group":
        create_group(args.name, args.desc)
    elif args.cmd == "upload":
        upload_asset(args.group, args.file, name=args.name, asset_type=args.type)
    elif args.cmd == "list-assets":
        list_assets(args.group)
    elif args.cmd == "list-groups":
        list_groups()
    return 0


if __name__ == "__main__":
    sys.exit(main())
