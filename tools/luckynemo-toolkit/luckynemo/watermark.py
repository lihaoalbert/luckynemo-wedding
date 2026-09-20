"""AI 生成角标工具：给图片右下角加半透明「AI 生成」圆角标识块。

所有外发素材（推广图、对比图）统一过这一层，合规兜底逻辑见 delivery.py
（交付物的图尾标识条/片尾标识卡由那边负责，这里是轻量角标，不改动画面尺寸）。

用法：
    python -m luckynemo.watermark <输入图片> <输出图片>
    python -m luckynemo.watermark <输入目录> <输出目录>   # 批量，保留文件名
代码调用：add_ai_badge(img_path, out_path)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import ffmpeg_utils

#: 角标文字（与 delivery.py 的显式标识一致）
BADGE_TEXT = "AI 生成"
#: 字号占图宽比例（3-4% 取中间值）
FONT_RATIO = 0.035
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def load_cjk_font(size: int):
    """加载中文字体；找不到系统字体时退回 Pillow 默认字体（与 delivery.py 同一套候选）。"""
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


def add_ai_badge(img_path: str | Path, out_path: str | Path, *, text: str = BADGE_TEXT) -> Path:
    """图片右下角加半透明黑底白字「AI 生成」圆角块，返回输出路径。

    字号约为图宽 3.5%（下限 18px），右/下边距一致；不改变画布尺寸。
    """
    from PIL import Image, ImageDraw

    src = Path(img_path)
    dst = Path(out_path)
    img = Image.open(src)
    w, h = img.size
    font_size = max(int(w * FONT_RATIO), 18)
    margin = font_size  # 右下留白边距一致
    pad_x, pad_y = int(font_size * 0.9), int(font_size * 0.5)

    canvas = img.convert("RGBA")
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = load_cjk_font(font_size)
    tw = draw.textlength(text, font=font)
    # 文字块尺寸（ascent+descent 近似行高）
    ascent, descent = font.getmetrics()
    th = ascent + descent
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    x1 = w - margin - box_w
    y1 = h - margin - box_h
    draw.rounded_rectangle(
        [x1, y1, x1 + box_w, y1 + box_h],
        radius=font_size * 0.45,
        fill=(0, 0, 0, 140),
    )
    draw.text(
        (x1 + box_w / 2, y1 + box_h / 2),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        anchor="mm",
    )
    result = Image.alpha_composite(canvas, overlay)

    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.suffix.lower() in (".jpg", ".jpeg"):
        result.convert("RGB").save(dst, quality=95)
    else:
        result.save(dst)
    return dst


def _iter_images(directory: Path) -> list[Path]:
    return sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="luckynemo.watermark",
        description="给图片右下角加「AI 生成」角标（输入为目录时批量处理，保留文件名）",
    )
    parser.add_argument("input", help="输入图片或目录")
    parser.add_argument("output", help="输出图片或目录")
    parser.add_argument("--text", default=BADGE_TEXT, help=f"角标文字（默认「{BADGE_TEXT}」）")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    src, dst = Path(args.input), Path(args.output)
    if not src.exists():
        print(f"错误：输入不存在：{src}", file=sys.stderr)
        return 2
    if src.is_dir():
        images = _iter_images(src)
        if not images:
            print(f"错误：目录里没有图片：{src}", file=sys.stderr)
            return 2
        dst.mkdir(parents=True, exist_ok=True)
        ok = 0
        for img in images:
            try:
                add_ai_badge(img, dst / img.name, text=args.text)
                ok += 1
                print(f"  -> {img.name} 完成", flush=True)
            except (OSError, ValueError) as exc:
                print(f"  !! {img.name} 失败：{exc}", file=sys.stderr)
        print(f"批量结束：{ok}/{len(images)} 成功。")
        return 0 if ok == len(images) else 1
    try:
        add_ai_badge(src, dst, text=args.text)
    except (OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
    print(f"-> {dst} 完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
