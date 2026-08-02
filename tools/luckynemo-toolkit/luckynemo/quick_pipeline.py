"""管线 C：领证纪念快道 CLI（极致模板化，2 小时交付）。

用法：
    python -m luckynemo.quick_pipeline c1 --template red_bg_upgrade --photo <登记照.jpg> --out <输出目录> [--dry-run]
    python -m luckynemo.quick_pipeline c2 --photos <照片目录> --date "2026.10.01 我们领证啦" --out <成片.mp4> [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import yaml

from . import ark, config
from . import ffmpeg_utils
from .config import TOOLKIT_ROOT

#: 快道模板目录
QUICK_DIR = TOOLKIT_ROOT / "templates" / "quick"
C1_TEMPLATES_FILE = QUICK_DIR / "c1_photo_templates.yaml"
C2_TEMPLATE_FILE = QUICK_DIR / "c2_video_template.yaml"


def _load_yaml(path: Path) -> dict:
    """读取 YAML 模板文件。"""
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def list_c1_templates() -> list[str]:
    """C1 纪念照模板名列表。"""
    return sorted(_load_yaml(C1_TEMPLATES_FILE)["templates"].keys())


def _build_client(args: argparse.Namespace) -> ark.ArkClient:
    """按 --dry-run 构造客户端（dry-run 不需要 API Key）。"""
    if getattr(args, "dry_run", False):
        return ark.ArkClient(dry_run=True)
    config.load_dotenv()
    return ark.ArkClient(api_key=config.get_api_key())


# ------------------------------------------------------------------
# C1：领证纪念照（SeedEdit/Seedream 直出，不走全流程）
# ------------------------------------------------------------------
def cmd_c1(args: argparse.Namespace) -> int:
    """按固定模板把登记照/现场照升级成纪念照。"""
    templates = _load_yaml(C1_TEMPLATES_FILE)["templates"]
    tpl = templates[args.template]
    photo = Path(args.photo)
    if not photo.is_file():
        print(f"照片不存在：{photo}", file=sys.stderr)
        return 1

    client = _build_client(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 注意：参考图需公网 URL（先上传对象存储），本地路径仅为占位。
    print(f"模板：{tpl['name']}｜输入：{photo.name} -> {out_dir}")
    urls = client.generate_image(
        prompt=tpl["prompt"],
        size=tpl.get("size", "2K"),
        reference_images=[str(photo.resolve())],
        watermark=False,  # 显式标识由 delivery.py 交付时统一加
    )
    for url in urls or ["<dry-run-url>"]:
        client.download(url, out_dir / f"c1_{args.template}.png")
    print("C1 出图完成。精简品控 3 条：像本人 / 无畸变 / 文字正确。交付前过 delivery.py 加标识。")
    return 0


# ------------------------------------------------------------------
# C2：15 秒领证小视频（Seedance Mini 1-2 镜 + ffmpeg 模板合成）
# ------------------------------------------------------------------
def cmd_c2(args: argparse.Namespace) -> int:
    """用照片生成 1-2 个 Mini 镜头，模板合成 15 秒小视频（叠日期字幕 + 固定片尾标识）。"""
    tpl = _load_yaml(C2_TEMPLATE_FILE)
    photos_dir = Path(args.photos)
    photos = sorted(
        p for p in photos_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ) if photos_dir.is_dir() else []
    if not photos:
        print(f"照片目录为空或不存在：{photos_dir}", file=sys.stderr)
        return 1

    shots = tpl["shots"][: tpl.get("max_shots", 2)]
    client = _build_client(args)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print(f"[dry-run] C2 合成计划：{len(shots)} 个 Mini 镜头 + 日期字幕「{args.date}」+ 片尾「{tpl['end_card_text']}」")
        for i, shot in enumerate(shots, start=1):
            print(f"[dry-run] 镜头 {i}：首帧={photos[min(i - 1, len(photos) - 1)].name}，{shot['duration']}s，{shot['video_prompt'][:40]}")
        print(f"[dry-run] ffmpeg：concat -> burn_subtitle(日期) -> add_end_card -> {out_path}")
        return 0

    # 1) 逐镜生成（Mini 仅 720p，成本约 0.5 元/秒）
    with tempfile.TemporaryDirectory() as tmp_dir:
        clips: list[Path] = []
        for i, shot in enumerate(shots, start=1):
            first_frame = photos[min(i - 1, len(photos) - 1)]
            task_id = client.create_video_task(
                model=config.get_model("SEEDANCE_MODEL_DRAFT", ark.SEEDANCE_2_MINI),
                text=shot["video_prompt"],
                first_frame=str(first_frame.resolve()),  # 本地路径自动转 data URL
                duration=shot["duration"],
                resolution="720p",
                ratio=tpl.get("ratio", "9:16"),
                generate_audio=False,
            )
            task = client.poll_task(task_id)
            clip = client.download(ark.ArkClient.extract_video_url(task), Path(tmp_dir) / f"shot_{i:02d}.mp4")
            clips.append(clip)
        # 2) ffmpeg 模板合成：拼接 -> 叠日期字幕 -> 固定片尾 AI 标识
        concat_out = Path(tmp_dir) / "concat.mp4"
        ffmpeg_utils.concat_segments(clips, concat_out)
        subbed = Path(tmp_dir) / "subtitled.mp4"
        ffmpeg_utils.burn_subtitle(concat_out, subbed, args.date,
                                   fontsize=tpl.get("subtitle_fontsize", 48))
        ffmpeg_utils.add_end_card(subbed, out_path,
                                  text=tpl.get("end_card_text", "本片由 AI 生成"),
                                  duration=max(tpl.get("end_card_duration", 2.5), 2.0))
    print(f"C2 成片完成：{out_path}")
    print("精简品控 3 条：像本人 / 无畸变 / 日期文字正确。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.quick_pipeline",
        description="管线 C：领证纪念快道（模板化，2 小时交付）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_c1 = sub.add_parser("c1", help="领证纪念照：登记照/现场照按固定模板升级")
    p_c1.add_argument("--template", required=True, choices=list_c1_templates(), help="模板名")
    p_c1.add_argument("--photo", required=True, help="结婚证照片/登记现场照")
    p_c1.add_argument("--out", required=True, help="输出目录")
    p_c1.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_c1.set_defaults(func=cmd_c1)

    p_c2 = sub.add_parser("c2", help="15 秒领证小视频：Mini 镜头 + ffmpeg 模板合成")
    p_c2.add_argument("--photos", required=True, help="照片目录（1-2 张登记照/合影）")
    p_c2.add_argument("--date", required=True, help='日期字幕文字，如 "2026.10.01 我们领证啦"')
    p_c2.add_argument("--out", required=True, help="成片输出路径（mp4）")
    p_c2.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用与命令，不真正请求/扣费")
    p_c2.set_defaults(func=cmd_c2)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ark.ArkAPIError, ffmpeg_utils.FFmpegNotFoundError, RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
