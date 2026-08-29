#!/usr/bin/env python3
"""火山人像融合 3.6 测试：job#175 成片为模板，奔奔/徐驰原图直出照为源脸。
签名：volc HMAC-SHA256（service=cv, region=cn-north-1, visual.volcengineapi.com）。"""
import base64, datetime, hashlib, hmac, json, sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

def load_env():
    env = {}
    for line in open(Path(__file__).resolve().parent / ".env"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env

ENV = load_env()
AK, SK = ENV["VOLC_ACCESS_KEY"], ENV["VOLC_SECRET_KEY"]
HOST = "visual.volcengineapi.com"
REGION, SERVICE = "cn-north-1", "cv"
QUERY = "Action=CVProcess&Version=2022-08-31"


def sign(body: bytes) -> dict:
    now = datetime.datetime.now(datetime.timezone.utc)
    xdate = now.strftime("%Y%m%dT%H%M%SZ")
    short = now.strftime("%Y%m%d")
    content_type = "application/json"
    payload_hash = hashlib.sha256(body).hexdigest()
    canonical_headers = f"content-type:{content_type}\nhost:{HOST}\n"
    signed_headers = "content-type;host"
    canonical = ("POST\n/\n" + QUERY + "\n" + canonical_headers + "\n" + signed_headers + "\n" + payload_hash)
    scope = f"{short}/{REGION}/{SERVICE}/request"
    to_sign = "HMAC-SHA256\n" + xdate + "\n" + scope + "\n" + hashlib.sha256(canonical.encode()).hexdigest()
    k_date = hmac.new(SK.encode(), short.encode(), hashlib.sha256).digest()
    k_region = hmac.new(k_date, REGION.encode(), hashlib.sha256).digest()
    k_service = hmac.new(k_region, SERVICE.encode(), hashlib.sha256).digest()
    k_signing = hmac.new(k_service, b"request", hashlib.sha256).digest()
    signature = hmac.new(k_signing, to_sign.encode(), hashlib.sha256).hexdigest()
    return {
        "Content-Type": content_type,
        "Host": HOST,
        "X-Date": xdate,
        "Authorization": (f"HMAC-SHA256 Credential={AK}/{scope}, "
                          f"SignedHeaders={signed_headers}, Signature={signature}"),
    }


def b64(p: Path) -> str:
    return base64.b64encode(p.read_bytes()).decode()


def main():
    base = Path("/tmp/fb52_local")
    # 素材图（本人正脸）：女在前男在后；模板= job#175 成片（左男右女）
    body = json.dumps({
        "req_key": "face_swap3_6",
        "binary_data_base64": [
            b64(base / "anchorA_groom.jpg"),   # 新娘 奔奔
            b64(base / "anchorB_bride.jpg"),   # 新郎 徐驰
            b64(base / "result.jpg"),          # 模板：成片
        ],
        "face_type": "l2r",
        "merge_infos": [
            {"location": 1, "template_location": 2},   # 女脸 → 模板右（新娘）
            {"location": 2, "template_location": 1},   # 男脸 → 模板左（新郎）
        ],
        "source_similarity": "1",
    }).encode()
    r = requests.post(f"https://{HOST}/?{QUERY}", data=body, headers=sign(body), timeout=120)
    data = r.json()
    print("code:", data.get("code"), "message:", data.get("message"), "elapsed:", data.get("time_elapsed"))
    if data.get("code") != 10000:
        print(json.dumps(data, ensure_ascii=False)[:500])
        sys.exit(1)
    out = base64.b64decode(data["data"]["binary_data_base64"][0])
    dest = Path("/tmp/fb52_ab/F1_volc_fusion.jpg")
    dest.write_bytes(out)
    print(f"融合完成 -> {dest} ({len(out)//1024}KB)")


if __name__ == "__main__":
    main()
