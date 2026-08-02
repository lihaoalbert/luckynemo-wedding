"""管线 B：爱情叙事短片 CLI。

流程：分镜校验 → 首帧图（Seedream）→ 逐镜生成（Seedance，草稿 Mini / 定稿标准版）→ ffmpeg 粗剪。

用法：
    python -m luckynemo.video_pipeline validate <分镜.json>
    python -m luckynemo.video_pipeline frames <分镜.json> --refs <客户照片目录> --out <首帧目录> [--dry-run]
    python -m luckynemo.video_pipeline draft <分镜.json> --frames <首帧目录> --out <片段目录> [--dry-run]
    python -m luckynemo.video_pipeline final <分镜.json> --frames <首帧目录> --resolution 720p --out <片段目录> [--dry-run]
    python -m luckynemo.video_pipeline roughcut <分镜.json> --clips <片段目录> --audio <旁白配乐.mp3> --out <成片.mp4> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import ark, config
from . import ffmpeg_utils
from .config import TOOLKIT_ROOT

#: 分镜模板目录
STORYBOARD_DIR = TOOLKIT_ROOT / "templates" / "storyboards"
#: 分镜必填字段
SHOT_SCHEMA = {
    "id": int,
    "duration": int,
    "frame_prompt": str,
    "video_prompt": str,
    "narration": str,
    "mood": str,
}


# ------------------------------------------------------------------
# 分镜加载与校验
# ------------------------------------------------------------------
def load_storyboard(path: str | Path) -> dict:
    """读取分镜 JSON。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"分镜文件不存在：{p}")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def validate_storyboard(data: dict) -> list[str]:
    """校验分镜 schema，返回错误列表（空列表 = 通过）。

    schema: {"title": str, "shots": [{"id": int, "duration": int(4-15),
             "frame_prompt": str, "video_prompt": str, "narration": str, "mood": str}]}
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["分镜必须是 JSON 对象"]
    if not isinstance(data.get("title"), str) or not data["title"]:
        errors.append("缺少 title（字符串）")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("缺少 shots（非空数组）")
        return errors
    seen_ids: set[int] = set()
    for i, shot in enumerate(shots):
        where = f"shots[{i}]"
        if not isinstance(shot, dict):
            errors.append(f"{where} 不是对象")
            continue
        for field, ftype in SHOT_SCHEMA.items():
            if field not in shot:
                errors.append(f"{where} 缺少字段 {field}")
            elif not isinstance(shot[field], ftype) or (ftype is int and isinstance(shot[field], bool)):
                errors.append(f"{where}.{field} 类型应为 {ftype.__name__}")
        shot_id = shot.get("id")
        if isinstance(shot_id, int):
            if shot_id in seen_ids:
                errors.append(f"{where}.id 重复：{shot_id}")
            seen_ids.add(shot_id)
        duration = shot.get("duration")
        if isinstance(duration, int) and not ark.VIDEO_DURATION_RANGE[0] <= duration <= ark.VIDEO_DURATION_RANGE[1]:
            errors.append(f"{where}.duration={duration} 超出 {ark.VIDEO_DURATION_RANGE[0]}-{ark.VIDEO_DURATION_RANGE[1]} 秒")
    return errors


def _sorted_shots(data: dict) -> list[dict]:
    """按镜头 id 排序返回。"""
    return sorted(data["shots"], key=lambda s: s["id"])


def _frame_path(frames_dir: Path, shot_id: int) -> Path:
    """首帧图路径约定：shot_<id:02d>.png。"""
    return frames_dir / f"shot_{shot_id:02d}.png"


#: 男性/女性角色关键词（用于识别双人镜头）
_MALE_MARKERS = ("新郎", "男生", "男人", "男孩", "老公", "阿驰", "男士")
_FEMALE_MARKERS = ("新娘", "女生", "女人", "女孩", "老婆", "阿奔", "女士")
#: 泛人物关键词（含长辈等配角）
_PEOPLE_MARKERS = ("他", "她", "妈妈", "爸爸", "母亲", "父亲", "两人", "新郎", "新娘",
                   "男生", "女生", "男人", "女人")


def apply_video_constraints(video_prompt: str) -> str:
    """生成视频前由代码强制追加约束（不依赖 LLM 自觉，见 templates/seedance_prompt_rules.md）。

    - 人物镜头：追加"人物五官与首帧保持一致"
    - 双人镜头：追加"画面中仅这一男一女"（防分身）
    已包含对应约束时不重复追加；纯场景镜头（无人物关键词）不追加。
    """
    text = video_prompt
    has_people = any(k in text for k in _PEOPLE_MARKERS)
    is_couple = ("两人" in text) or (
        any(k in text for k in _MALE_MARKERS) and any(k in text for k in _FEMALE_MARKERS)
    )
    if has_people and "五官与首帧保持一致" not in text:
        text += "，人物五官与首帧保持一致"
    if is_couple and "仅这一男一女" not in text:
        text += "，画面中仅这一男一女"
    return text


# ------------------------------------------------------------------
# 子命令
# ------------------------------------------------------------------
def cmd_validate(args: argparse.Namespace) -> int:
    """校验分镜表 schema。"""
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print(f"分镜校验未通过（{len(errors)} 个问题）：")
        for err in errors:
            print(f"  - {err}")
        return 1
    total = sum(s["duration"] for s in data["shots"])
    print(f"分镜校验通过：《{data['title']}》共 {len(data['shots'])} 个镜头，总时长约 {total} 秒。")
    return 0


def cmd_frames(args: argparse.Namespace) -> int:
    """逐镜头生成首帧图（角色一致性的锚，品控通过后再进视频生成）。

    首帧统一走火山 Seedream。
    """
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = sorted(Path(args.refs).iterdir()) if Path(args.refs).is_dir() else []
    ref_paths = [p for p in refs if p.suffix.lower() in {".jpg", ".jpeg", ".png"}][:10]

    client = _build_client(args)
    # 参考图本地路径由 ark.to_image_url 自动转 data URL，无需先传对象存储
    ref_urls = [str(p.resolve()) for p in ref_paths]
    for shot in _sorted_shots(data):
        prompt = shot["frame_prompt"] + "，保持与参考图人物五官、脸型完全一致"
        dest = _frame_path(out_dir, shot["id"])
        print(f"镜头 {shot['id']:02d} 首帧：{shot['frame_prompt'][:30]}...")
        urls = client.generate_image(
            prompt=prompt, size="2K", reference_images=ref_urls or None,
            model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
            watermark=False)
        for url in urls or [f"<dry-run-url-shot-{shot['id']}>"]:
            client.download(url, dest)
    print(f"首帧生成完毕 -> {out_dir}。请人工品控锁定首帧后再跑 draft/final。")
    return 0


def _run_seedance(args: argparse.Namespace, *, model: str, label: str) -> int:
    """draft/final 共用：逐镜创建 Seedance 任务并轮询下载。"""
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    client = _build_client(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = Path(args.frames)

    for shot in _sorted_shots(data):
        frame = _frame_path(frames_dir, shot["id"])
        if not frame.is_file() and not args.dry_run:
            print(f"镜头 {shot['id']:02d} 缺首帧图：{frame}，跳过。", file=sys.stderr)
            continue
        # 首帧本地路径由 ark.to_image_url 自动转 data URL，无需先传对象存储
        print(f"镜头 {shot['id']:02d}（{shot['duration']}s，{label}）：{shot['video_prompt'][:30]}...")
        task_id = client.create_video_task(
            model=model,
            text=apply_video_constraints(shot["video_prompt"]),
            first_frame=str(frame.resolve()),
            duration=shot["duration"],
            resolution=args.resolution,
            ratio="16:9",
            generate_audio=False,  # 配音单独做（豆包 TTS），可控性更高
            return_last_frame=True,  # 方便首尾帧接龙
        )
        task = client.poll_task(task_id)
        url = "<dry-run-video-url>" if args.dry_run else ark.ArkClient.extract_video_url(task)
        client.download(url, out_dir / f"shot_{shot['id']:02d}.mp4")
    print(f"{label}片段生成完毕 -> {out_dir}")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    """用 Mini 模型出草稿（约 0.5 元/秒，仅 720p），确认后再用 final 出定稿。"""
    args.resolution = "720p"  # Mini 仅支持 720p
    return _run_seedance(args, model=config.get_model("SEEDANCE_MODEL_DRAFT", ark.SEEDANCE_2_MINI), label="Mini 草稿")


def cmd_final(args: argparse.Namespace) -> int:
    """用标准版出定稿（约 0.95 元/秒）。"""
    return _run_seedance(args, model=config.get_model("SEEDANCE_MODEL_FINAL", ark.SEEDANCE_2_STD), label="标准版定稿")


def cmd_roughcut(args: argparse.Namespace) -> int:
    """ffmpeg 按分镜顺序拼接片段 + 旁白（+ 可选 BGM 混流），输出粗剪成片。"""
    data = load_storyboard(args.storyboard)
    clips_dir = Path(args.clips)
    clips = [clips_dir / f"shot_{shot['id']:02d}.mp4" for shot in _sorted_shots(data)]
    missing = [str(c) for c in clips if not c.is_file()]
    if args.dry_run:
        print(f"[dry-run] 粗剪：按分镜顺序拼接 {len(clips)} 个片段 -> {args.out}")
        if missing:
            print(f"[dry-run] 注意：以下片段当前不存在（真实执行会失败）：{missing}")
        print(f"[dry-run] 旁白音轨：{args.audio or '无'}｜BGM：{args.bgm or '无'}（混流时旁白 1.0 / BGM 0.25）")
        return 0
    if missing:
        print(f"缺少片段：{missing}，请先跑 draft/final。", file=sys.stderr)
        return 1
    out = ffmpeg_utils.concat_segments(clips, args.out, audio=args.audio, bgm=args.bgm)
    print(f"粗剪完成：{out}")
    print("提醒：对外交付前必须走 delivery.py 加片尾 AI 标识卡（≥2 秒）。")
    return 0


def _build_client(args: argparse.Namespace) -> ark.ArkClient:
    """按 --dry-run 构造客户端（dry-run 不需要 API Key）。"""
    if getattr(args, "dry_run", False):
        return ark.ArkClient(dry_run=True)
    config.load_dotenv()
    return ark.ArkClient(api_key=config.get_api_key())


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.video_pipeline",
        description="管线 B：爱情叙事短片（分镜 → 首帧 → 逐镜生成 → 粗剪）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_val = sub.add_parser("validate", help="校验分镜 JSON 的 schema")
    p_val.add_argument("storyboard", help=f"分镜 JSON 路径（模板见 {STORYBOARD_DIR}）")
    p_val.set_defaults(func=cmd_validate)

    p_frames = sub.add_parser("frames", help="逐镜头生成首帧图（火山 Seedream）")
    p_frames.add_argument("storyboard", help="分镜 JSON 路径")
    p_frames.add_argument("--refs", required=True, help="客户照片目录（角色一致性参考）")
    p_frames.add_argument("--out", required=True, help="首帧输出目录")
    p_frames.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_frames.set_defaults(func=cmd_frames)

    p_draft = sub.add_parser("draft", help="用 Mini 模型逐镜生成草稿（约 0.5 元/秒，仅 720p）")
    p_draft.add_argument("storyboard", help="分镜 JSON 路径")
    p_draft.add_argument("--frames", required=True, help="首帧目录（frames 子命令的输出）")
    p_draft.add_argument("--out", required=True, help="片段输出目录")
    p_draft.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_draft.set_defaults(func=cmd_draft)

    p_final = sub.add_parser("final", help="用标准版逐镜生成定稿（约 0.95 元/秒）")
    p_final.add_argument("storyboard", help="分镜 JSON 路径")
    p_final.add_argument("--frames", required=True, help="首帧目录（frames 子命令的输出）")
    p_final.add_argument("--resolution", default="720p", choices=["480p", "720p", "1080p", "4K"],
                         help="分辨率（默认 720p；4K 仅标准版）")
    p_final.add_argument("--out", required=True, help="片段输出目录")
    p_final.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_final.set_defaults(func=cmd_final)

    p_cut = sub.add_parser("roughcut", help="ffmpeg 按分镜顺序拼接 + 旁白/BGM 混流，输出粗剪成片")
    p_cut.add_argument("storyboard", help="分镜 JSON 路径")
    p_cut.add_argument("--clips", required=True, help="片段目录（draft/final 的输出）")
    p_cut.add_argument("--audio", default=None, help="旁白音频文件（可选）")
    p_cut.add_argument("--bgm", default=None, help="背景音乐文件（可选，与旁白 amix 混流：旁白 1.0 / BGM 0.25）")
    p_cut.add_argument("--out", required=True, help="成片输出路径（mp4）")
    p_cut.add_argument("--dry-run", action="store_true", help="只打印将执行的 ffmpeg 命令，不真正执行")
    p_cut.set_defaults(func=cmd_roughcut)
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
