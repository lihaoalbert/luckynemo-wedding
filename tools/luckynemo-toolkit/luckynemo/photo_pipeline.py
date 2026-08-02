"""管线 A：AI 婚纱照 CLI。

用法：
    python -m luckynemo.photo_pipeline intake <素材目录> [--out report.json]
    python -m luckynemo.photo_pipeline generate --style indoor_main --refs <客户照片目录> --count 2 --out <输出目录> [--dry-run]
    python -m luckynemo.photo_pipeline contact-sheet --in <生成目录> --out <品控图墙.html>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from . import ark, config
from .config import TOOLKIT_ROOT

#: 风格模板目录
STYLE_DIR = TOOLKIT_ROOT / "templates" / "photo_styles"
#: 素材质检标准
INTAKE_MIN_COUNT = 4
INTAKE_MIN_SHORT_EDGE = 1024
INTAKE_EXTS = {".jpg", ".jpeg", ".png"}
#: Seedream 5.0 Pro 参考图上限
MAX_REFS = 10


def list_styles() -> list[str]:
    """可用的风格模板名（YAML 文件名去后缀）。"""
    return sorted(p.stem for p in STYLE_DIR.glob("*.yaml"))


def load_style(style: str) -> dict:
    """加载风格模板 YAML。"""
    path = STYLE_DIR / f"{style}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"风格模板不存在：{path}（可用：{', '.join(list_styles())}）")
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    for field in ("name", "prompt", "size"):
        if field not in data:
            raise ValueError(f"风格模板 {path} 缺少字段：{field}")
    return data


def collect_images(directory: str | Path, exts: set[str] = INTAKE_EXTS) -> list[Path]:
    """收集目录内图片（不递归），按文件名排序。"""
    root = Path(directory)
    if not root.is_dir():
        raise NotADirectoryError(f"目录不存在：{root}")
    return sorted(p for p in root.iterdir() if p.suffix.lower() in exts)


# ------------------------------------------------------------------
# 子命令：intake 素材质检
# ------------------------------------------------------------------
def cmd_intake(args: argparse.Namespace) -> int:
    """素材质检：图片数量 ≥4、格式 jpg/png、短边 ≥1024，输出质检报告 JSON。"""
    from PIL import Image

    photos = collect_images(args.dir)
    items = []
    qualified = 0
    for photo in photos:
        item: dict = {"file": photo.name}
        try:
            with Image.open(photo) as img:
                w, h = img.size
            item["width"], item["height"] = w, h
            item["short_edge"] = min(w, h)
            item["ok"] = min(w, h) >= INTAKE_MIN_SHORT_EDGE
            if not item["ok"]:
                item["reason"] = f"短边 {min(w, h)} < {INTAKE_MIN_SHORT_EDGE}"
        except Exception as exc:  # 损坏/非图片文件
            item.update(ok=False, reason=f"无法读取：{exc}")
        qualified += 1 if item["ok"] else 0
        items.append(item)

    report = {
        "dir": str(Path(args.dir).resolve()),
        "standard": {"min_count": INTAKE_MIN_COUNT, "min_short_edge": INTAKE_MIN_SHORT_EDGE,
                     "formats": sorted(INTAKE_EXTS)},
        "total": len(photos),
        "qualified": qualified,
        "pass": qualified >= INTAKE_MIN_COUNT,
        "items": items,
        "note": "人工还需过一遍：正脸清晰、无墨镜遮挡、光照均匀（见 checklists/photo_qc.md）",
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"\n质检报告已写入：{args.out}")
    if not report["pass"]:
        print(f"\n质检不通过：合格照片 {qualified}/{INTAKE_MIN_COUNT}，请通知客户补传。", file=sys.stderr)
        return 1
    return 0


# ------------------------------------------------------------------
# 子命令：generate 批量生成
# ------------------------------------------------------------------
def cmd_generate(args: argparse.Namespace) -> int:
    """按风格模板批量生成婚纱照并下载（统一走火山 Seedream）。"""
    style = load_style(args.style)
    refs = collect_images(args.refs)
    if len(refs) > MAX_REFS:
        print(f"参考图 {len(refs)} 张超过上限 {MAX_REFS}，只取前 {MAX_REFS} 张。")
        refs = refs[:MAX_REFS]
    if not refs:
        print("警告：参考图目录为空，将按纯文生图提交（人像一致性无法保证）。", file=sys.stderr)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    return _generate_seedream(args, style, refs, out_dir)


def _generate_seedream(args: argparse.Namespace, style: dict, refs: list[Path], out_dir: Path) -> int:
    """火山 Seedream 线（图片生成唯一通道）。"""
    client = _build_client(args)
    # 参考图本地路径由 ark.to_image_url 自动转 data URL，无需先传对象存储
    ref_urls = [str(p.resolve()) for p in refs]
    print(f"[seedream] 风格：{style['name']}｜参考图 {len(ref_urls)} 张｜生成 {args.count} 张 -> {out_dir}")
    for i in range(1, args.count + 1):
        urls = client.generate_image(
            prompt=style["prompt"],
            model=getattr(args, "model", None) or config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
            size=style.get("size", "2K"),
            reference_images=ref_urls or None,
            negative_prompt=style.get("negative_prompt"),
            watermark=False,  # 显式标识统一由 delivery.py 在交付时加
        )
        for j, url in enumerate(urls or [f"<dry-run-url-{i}>"], start=1):
            suffix = f"_{j}" if len(urls) > 1 else ""
            client.download(url, out_dir / f"{args.style}_{i:02d}{suffix}.png")
    print("生成完成。下一步：python -m luckynemo.photo_pipeline contact-sheet --in <生成目录> --out <图墙.html>")
    return 0


# ------------------------------------------------------------------
# 子命令：contact-sheet 品控图墙
# ------------------------------------------------------------------
def cmd_contact_sheet(args: argparse.Namespace) -> int:
    """生成品控图墙 HTML：缩略图网格 + 文件名，供人工勾选通过/打回。"""
    images = collect_images(args.input_dir, exts={".jpg", ".jpeg", ".png", ".webp"})
    if not images:
        print(f"目录里没有图片：{args.input_dir}", file=sys.stderr)
        return 1
    cells = "\n".join(
        f'      <figure><img src="{p.resolve().as_uri()}" loading="lazy">'
        f"<figcaption>{p.name}</figcaption>"
        f'<label><input type="checkbox"> 通过</label></figure>'
        for p in images
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>品控图墙 - {Path(args.input_dir).name}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", sans-serif; margin: 24px; background: #111; color: #eee; }}
  h1 {{ font-size: 20px; }}
  .hint {{ color: #999; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; margin-top: 16px; }}
  figure {{ margin: 0; background: #1d1d1d; border-radius: 8px; padding: 8px; }}
  img {{ width: 100%; border-radius: 4px; display: block; }}
  figcaption {{ font-size: 12px; color: #bbb; margin: 8px 0 4px; word-break: break-all; }}
  label {{ font-size: 13px; }}
</style>
</head>
<body>
  <h1>婚纱照品控图墙（{len(images)} 张）</h1>
  <p class="hint">对照 checklists/photo_qc.md 逐项检查：像本人 / 五官无畸变 / 手部正常 / 光影一致 / 无穿帮。勾选只作本地标记。</p>
  <div class="grid">
{cells}
  </div>
</body>
</html>
"""
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"品控图墙已生成：{out_path}（浏览器打开即可）")
    return 0


def _build_client(args: argparse.Namespace) -> ark.ArkClient:
    """按 --dry-run 构造方舟客户端（dry-run 不需要 API Key）。"""
    if args.dry_run:
        return ark.ArkClient(dry_run=True)
    config.load_dotenv()
    return ark.ArkClient(api_key=config.get_api_key())


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.photo_pipeline",
        description="管线 A：AI 婚纱照（素材质检 → 批量生成 → 品控图墙）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_intake = sub.add_parser("intake", help="素材质检：数量/格式/分辨率检查，输出报告 JSON")
    p_intake.add_argument("dir", help="客户素材目录")
    p_intake.add_argument("--out", help="质检报告 JSON 输出路径（可选）")
    p_intake.set_defaults(func=cmd_intake)

    p_gen = sub.add_parser("generate", help="按风格模板批量生成婚纱照")
    p_gen.add_argument("--style", required=True, choices=list_styles(), help="风格模板名")
    p_gen.add_argument("--refs", required=True, help="客户照片目录（≤10 张，清晰正脸最佳）")
    p_gen.add_argument("--count", type=int, default=2, help="生成张数（默认 2）")
    p_gen.add_argument("--out", required=True, help="输出目录")
    p_gen.add_argument("--model", default=None, help=f"图片模型 ID（默认读 SEEDREAM_MODEL 或 {ark.SEEDREAM_5_PRO}）")
    p_gen.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_gen.set_defaults(func=cmd_generate)

    p_sheet = sub.add_parser("contact-sheet", help="生成品控图墙 HTML（缩略图网格供人工勾选）")
    p_sheet.add_argument("--in", dest="input_dir", required=True, help="生成结果目录")
    p_sheet.add_argument("--out", required=True, help="输出 HTML 路径")
    p_sheet.set_defaults(func=cmd_contact_sheet)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ark.ArkAPIError, RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
