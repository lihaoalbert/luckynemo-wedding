"""upload_storylab_assets.py —「故事片场」交付资产上传 OSS（一次性运维脚本）。

BGM 与中文字体是 storylab_film worker 任务的运行时依赖（ECS 上从 OSS 下载到
tmpdir），资产体积大不进 git——仓库只留本脚本，交付通道是 OSS：
- OSS assets/storylab/bgm.mp3   ← films/benben-xuchi/bgm.mp3（婚礼 BGM，5MB）
- OSS assets/storylab/font.ttc  ← macOS 内置中文字体（PIL 字幕/卡片用）

用法：python3 upload_storylab_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
REPO = SERVER_DIR.parent
sys.path.insert(0, str(SERVER_DIR))

import app  # noqa: E402  载入 .env + OSS 凭据

ASSETS = [
    (REPO / "films" / "benben-xuchi" / "bgm.mp3",
     "assets/storylab/bgm.mp3", "audio/mpeg"),
    (Path("/System/Library/Fonts/STHeiti Light.ttc"),
     "assets/storylab/font.ttc", "font/ttc"),
]


def main() -> None:
    for local, key, ctype in ASSETS:
        if not local.is_file():
            raise SystemExit(f"资产缺失：{local}")
        app.oss_put_object(key, local.read_bytes(), content_type=ctype)
        size_mb = local.stat().st_size / 1024 / 1024
        print(f"OK {key} <- {local}（{size_mb:.1f}MB）")


if __name__ == "__main__":
    main()
