"""交付打包：所有对外交付物必须过这一层（合规兜底）。

做的事：
1. 复制成片/成图到交付目录结构（out/final/）
2. 显式标识：图片底部加"AI 生成"条（文字高度 ≥ 最短边 5%）；
   视频片尾追加 ≥2 秒"AI 生成"标识卡（走 ffmpeg_utils.add_end_card）
3. 隐式标识：写 metadata 占位（预留 cnTC260 国标五要素写入接口）
4. 生成 manifest.json 交付清单

豁免说明：客户要"无水印纯净版"时，须按《标识办法》第 9 条走豁免流程
（协议明确用户义务 + 日志留存 ≥6 个月），不能简单跳过本模块。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import ffmpeg_utils

#: 显式标识文字（GB 45438-2025）
AI_MARK_TEXT = "AI 生成"
AI_VIDEO_END_CARD_TEXT = "本片由 AI 生成"
#: 视频片尾标识卡时长（秒），合规要求 ≥2
AI_END_CARD_DURATION = 2.5

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTS = {".mp4", ".mov", ".m4v"}


def _load_cjk_font(size: int):
    """加载中文字体；找不到系统字体时退回 Pillow 默认字体。"""
    from PIL import ImageFont

    for font_path in ffmpeg_utils.FONT_CANDIDATES:
        if Path(font_path).is_file():
            try:
                return ImageFont.truetype(font_path, size)
            except OSError:
                continue
    try:
        return ImageFont.load_default(size=size)  # Pillow ≥10 支持 size
    except TypeError:
        return ImageFont.load_default()


def add_image_mark(src: str | Path, dst: str | Path, *, text: str = AI_MARK_TEXT) -> Path:
    """图片底部加黑底白字"AI 生成"条，文字高度 ≥ 画面最短边 5%。"""
    from PIL import Image, ImageDraw

    img = Image.open(src).convert("RGB")
    w, h = img.size
    font_size = max(int(min(w, h) * 0.05), 20)
    bar_h = int(font_size * 1.8)
    font = _load_cjk_font(font_size)

    canvas = Image.new("RGB", (w, h + bar_h), (0, 0, 0))
    canvas.paste(img, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((w / 2, h + bar_h / 2), text, font=font, fill=(255, 255, 255), anchor="mm")

    dst_path = Path(dst)
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst_path, quality=95)
    return dst_path


def write_metadata_placeholder(media_path: str | Path) -> Path:
    """隐式元数据写入接口（占位实现，交付流程的合规挂点）。

    TODO(合规)：接入开源 cnTC260（https://github.com/OPN48/cnTC260）
    在文件内部写入 GB 45438-2025 隐式标识五要素；同时建议在方舟控制台
    开通隐式水印（Beta 限时免费）做双保险。当前先写 sidecar JSON 占位。
    """
    media = Path(media_path)
    sidecar = media.with_name(media.name + ".aimeta.json")
    payload = {
        "standard": "GB 45438-2025",
        "ai_generated": True,
        "producer": "LuckyNemo",
        "media_file": media.name,
        "implicit_mark": None,
        "todo": "接入 cnTC260 在文件内部写入国标隐式标识五要素",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    sidecar.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return sidecar


def deliver(
    files: list[str | Path],
    out_dir: str | Path,
    *,
    title: str = "交付包",
    end_card_text: str = AI_VIDEO_END_CARD_TEXT,
    end_card_duration: float = AI_END_CARD_DURATION,
    dry_run: bool = False,
) -> Path:
    """把成片/成图打包成合规交付包，返回 manifest.json 路径。

    :param files: 待交付文件（图片走加图尾标识，视频走加片尾标识卡）
    :param out_dir: 交付目录（结构：out_dir/final/ + out_dir/manifest.json）
    """
    out_path = Path(out_dir)
    final_dir = out_path / "final"
    manifest: dict = {
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "explicit_mark": {"image_text": AI_MARK_TEXT, "video_end_card": end_card_text,
                          "end_card_duration": end_card_duration},
        "items": [],
    }

    if dry_run:
        print(f"[dry-run] 交付打包 -> {out_path}（{len(files)} 个文件）")

    for f in files:
        src = Path(f)
        ext = src.suffix.lower()
        dst = final_dir / src.name
        item: dict = {"source": str(src), "delivered": str(dst)}
        if ext in IMAGE_EXTS:
            item["type"] = "image"
            if dry_run:
                print(f"[dry-run] 图片加图尾标识：{src} -> {dst}")
            else:
                add_image_mark(src, dst)
        elif ext in VIDEO_EXTS:
            item["type"] = "video"
            if dry_run:
                print(f"[dry-run] 视频加片尾 AI 标识卡（{end_card_duration}s）：{src} -> {dst}")
            else:
                ffmpeg_utils.add_end_card(src, dst, text=end_card_text, duration=end_card_duration)
        else:
            item["type"] = "other"
            if dry_run:
                print(f"[dry-run] 原样复制：{src} -> {dst}")
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        item["metadata_sidecar"] = str(dst) + ".aimeta.json"
        if not dry_run:
            write_metadata_placeholder(dst)
        manifest["items"].append(item)

    manifest_path = out_path / "manifest.json"
    if dry_run:
        print(f"[dry-run] 写交付清单：{manifest_path}")
    else:
        out_path.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path
