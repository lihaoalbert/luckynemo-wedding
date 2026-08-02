"""一次性脚本：给 ibi-private 配置 CORS（允许官网域名浏览器直传）。

用法：python3 setup_oss_cors.py  （在项目根，凭据读 server/.env 或环境变量）
生产部署后在 ECS 上执行一次即可；重复执行幂等。
"""

from __future__ import annotations

import base64
import email.utils
import hashlib
import hmac
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app import OSS_AK, OSS_SK, OSS_BUCKET, OSS_REGION  # noqa: E402

CORS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<CORSConfiguration>
  <CORSRule>
    <AllowedOrigin>https://luckynemo.ibi.ren</AllowedOrigin>
    <AllowedMethod>POST</AllowedMethod>
    <AllowedMethod>PUT</AllowedMethod>
    <AllowedMethod>GET</AllowedMethod>
    <AllowedMethod>HEAD</AllowedMethod>
    <AllowedHeader>*</AllowedHeader>
    <ExposeHeader>ETag</ExposeHeader>
    <MaxAgeSeconds>600</MaxAgeSeconds>
  </CORSRule>
</CORSConfiguration>
"""


def main() -> int:
    if not (OSS_AK and OSS_SK):
        print("缺少 OSS_ACCESS_KEY_ID/OSS_ACCESS_KEY_SECRET（server/.env）", file=sys.stderr)
        return 1
    body = CORS_XML.encode("utf-8")
    content_type = "application/xml"
    date = email.utils.formatdate(usegmt=True)
    content_md5 = base64.b64encode(hashlib.md5(body).digest()).decode()
    resource = f"/{OSS_BUCKET}/?cors"
    string_to_sign = f"PUT\n{content_md5}\n{content_type}\n{date}\n{resource}"
    signature = base64.b64encode(
        hmac.new(OSS_SK.encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    r = requests.put(
        f"https://{OSS_BUCKET}.{OSS_REGION}.aliyuncs.com/?cors",
        data=body,
        headers={
            "Date": date,
            "Content-Type": content_type,
            "Content-MD5": content_md5,
            "Authorization": f"OSS {OSS_AK}:{signature}",
        },
        timeout=20,
    )
    print(f"putBucketCors -> HTTP {r.status_code}")
    if r.status_code >= 300:
        print(r.text[:500], file=sys.stderr)
        return 1
    print("CORS 已配置：允许 https://luckynemo.ibi.ren 的 POST/PUT/GET/HEAD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
