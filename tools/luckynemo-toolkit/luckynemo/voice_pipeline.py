"""声音管线 CLI：TTS 旁白 / 分镜配音 / 声音克隆 / 配乐生成（MiniMax 线）。

用法：
    python -m luckynemo.voice_pipeline tts --text "大家好" --out x.mp3 [--voice-id xx] [--emotion happy]
    python -m luckynemo.voice_pipeline narrate <分镜.json> --out <目录> [--voice-id xx]
    python -m luckynemo.voice_pipeline clone --audio <样本.mp3> [--voice-id-hint 名字]
    python -m luckynemo.voice_pipeline music --prompt "温暖钢琴" [--duration 30] --out bgm.mp3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .minimax_client import MiniMaxClient, MiniMaxAPIError
from .video_pipeline import load_storyboard, validate_storyboard

#: 默认音色（MiniMax 预置，婚礼旁白可先固定 3-5 个常用音色）
DEFAULT_VOICE_ID = "male-qn-qingse"


def _build_client(args: argparse.Namespace) -> MiniMaxClient:
    """按 --dry-run 构造客户端（dry-run 不需要 API Key）。"""
    if getattr(args, "dry_run", False):
        return MiniMaxClient(dry_run=True)
    return MiniMaxClient(api_key=config.get_minimax_api_key(),
                         base_url=config.get_minimax_base_url())


def cmd_tts(args: argparse.Namespace) -> int:
    """单句文本转语音，落盘 mp3。"""
    client = _build_client(args)
    out = client.synthesize(args.text, args.out, voice_id=args.voice_id, emotion=args.emotion,
                            speed=getattr(args, "speed", 1.0))
    print(f"TTS 完成：{out}")
    return 0


def cmd_narrate(args: argparse.Namespace) -> int:
    """按分镜逐镜头合成旁白 mp3，并生成 ffmpeg concat 列表文件供 roughcut 使用。"""
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先用 video_pipeline validate 检查：\n  - " + "\n  - ".join(errors),
              file=sys.stderr)
        return 1
    client = _build_client(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    shots = sorted(data["shots"], key=lambda s: s["id"])
    files: list[Path] = []
    for shot in shots:
        text = shot["narration"].strip()
        if not text:
            print(f"镜头 {shot['id']:02d} 无旁白，跳过。")
            continue
        dest = out_dir / f"shot_{shot['id']:02d}.mp3"
        print(f"镜头 {shot['id']:02d} 旁白：{text[:30]}{'...' if len(text) > 30 else ''}")
        client.synthesize(text, dest, voice_id=args.voice_id, emotion=args.emotion,
                          speed=getattr(args, "speed", 1.0))
        files.append(dest)

    # ffmpeg concat demuxer 列表（供 video_pipeline roughcut --audio 前置拼接用）
    list_file = out_dir / "narration_concat.txt"
    lines = [f"file '{p.resolve()}'" for p in files]
    if args.dry_run:
        print(f"[dry-run] 写 concat 列表 -> {list_file}（{len(files)} 条，跳过不落盘）")
    else:
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"旁白合成完毕（{len(files)} 条）-> {out_dir}")
    print("用法：ffmpeg -f concat -safe 0 -i narration_concat.txt -c copy narration.mp3，"
          "再交给 video_pipeline roughcut --audio narration.mp3")
    return 0


def cmd_clone(args: argparse.Namespace) -> int:
    """上传样本音频克隆音色，打印返回的 voice_id。"""
    client = _build_client(args)
    voice_id = client.clone_voice(args.audio, voice_id_hint=args.voice_id_hint)
    print(f"克隆成功，voice_id = {voice_id}")
    print(f"提示：请把它记入 .env（如 DEFAULT_VOICE_ID={voice_id}）或订单台账，"
          f"后续用 --voice-id {voice_id} 调用 TTS。")
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    """生成配乐并下载到本地（同步接口；官方不支持指定时长，--duration 仅作记录）。"""
    client = _build_client(args)
    if args.duration:
        print(f"提示：MiniMax 现行音乐接口不支持指定时长，--duration {args.duration} 将被忽略，长度由模型决定。")
    url = client.generate_music(args.prompt, instrumental=not args.vocals)
    dest = client.download(url or "<dry-run-music-url>", args.out)
    print(f"配乐完成：{dest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.voice_pipeline",
        description="声音管线：TTS 旁白 / 分镜配音 / 声音克隆 / 配乐生成（MiniMax 线）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_tts = sub.add_parser("tts", help="单句文本转语音，输出 mp3")
    p_tts.add_argument("--text", required=True, help="要合成的文本")
    p_tts.add_argument("--out", required=True, help="输出 mp3 路径")
    p_tts.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help=f"音色 ID（默认 {DEFAULT_VOICE_ID}）")
    p_tts.add_argument("--emotion", default=None, help="情绪（如 happy，可选）")
    p_tts.add_argument("--speed", type=float, default=1.0, help="语速 0.5-2.0（默认 1.0）")
    p_tts.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_tts.set_defaults(func=cmd_tts)

    p_nar = sub.add_parser("narrate", help="按分镜逐镜头合成旁白 mp3 + concat 列表")
    p_nar.add_argument("storyboard", help="分镜 JSON 路径（同 video_pipeline）")
    p_nar.add_argument("--out", required=True, help="输出目录")
    p_nar.add_argument("--voice-id", default=DEFAULT_VOICE_ID, help=f"音色 ID（默认 {DEFAULT_VOICE_ID}）")
    p_nar.add_argument("--emotion", default=None, help="情绪（如 happy，可选）")
    p_nar.add_argument("--speed", type=float, default=1.0, help="语速 0.5-2.0（默认 1.0；旁白超长时按 总长/片长 换算）")
    p_nar.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_nar.set_defaults(func=cmd_narrate)

    p_clone = sub.add_parser("clone", help="上传样本音频克隆音色（推荐 10s 干净人声）")
    p_clone.add_argument("--audio", required=True, help="样本音频（wav/mp3）")
    p_clone.add_argument("--voice-id-hint", default=None, help="自定义 voice_id 前缀（可选）")
    p_clone.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_clone.set_defaults(func=cmd_clone)

    p_music = sub.add_parser("music", help="生成配乐并下载")
    p_music.add_argument("--prompt", required=True, help="音乐描述（风格/情绪/乐器）")
    p_music.add_argument("--duration", type=int, default=30, help="期望时长秒数（注：现行官方接口不支持指定时长，此参数仅作记录，会被忽略）")
    p_music.add_argument("--out", required=True, help="输出音频路径（如 bgm.mp3）")
    p_music.add_argument("--vocals", action="store_true", help="生成带人声的歌曲（默认纯音乐）")
    p_music.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_music.set_defaults(func=cmd_music)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (MiniMaxAPIError, RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
