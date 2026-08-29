"""storylab_film.py —「故事片场」短片组装（2026-08-29，worker 内使用）。

移植自 films/benben-xuchi/_storylab_auto/assemble.py（P4 端到端验收版）：
纯 ffmpeg/PIL、0 生成调用——720x1280 / 24fps / yuv420p，片名卡 → 硬切镜组
（cover 裁切，入出点越界自动钳制/兜底）→ 情绪字幕（PIL 烧录）→ 片尾 AI 标识卡
（GB 45438-2025：≥2s，标识文字高度 ≥ 短边 5%）→ BGM 淡入淡出 + 原声混流。

与原版差异：字体/BGM/工作目录全部参数化（worker 从 OSS 下载到 tmpdir）；
片名卡通用化（无客户姓名输入，用「故事片场」）；字幕按情绪基调从词池挑 3-5 条。

Python 3.11 语法红线；依赖 Pillow（ECS venv 已有 12.3.0）+ 系统 ffmpeg。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

W, H, FPS = 720, 1280, 24
GOLD = (201, 162, 99)
WHITE = (245, 245, 245)
GRAY = (200, 200, 200)
BLACK = (12, 12, 14)

#: 情绪字幕词池：按 tone 偏好选一组，取镜表前 N 个关键位烧录（3-5 条）
SUBTITLE_POOLS = {
    "funny": [
        "哈哈哈哈就是这一幕",
        "名场面预定",
        "笑点已就位，预备——",
        "这段必须反复观看",
        "未完待续，笑料管够",
    ],
    "warm": [
        "这一刻，心动了",
        "像风一样自由",
        "身边是你就好",
        "从今以后",
        "我们的故事，未完待续",
    ],
}


def log(msg: str) -> None:
    print(f"[storylab_film] {msg}", flush=True)


def run(cmd: list, what: str = "") -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError("{} 失败（exit {}）：\n{}".format(
            what or "ffmpeg", proc.returncode, proc.stderr[-2000:]))


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def load_font(font_path: Path, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(font_path), size)


def draw_centered(draw, y: int, text: str, font, fill) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = (W - (bbox[2] - bbox[0])) // 2 - bbox[0]
    draw.text((x, y), text, font=font, fill=fill)


def title_card_png(font_path: Path, dest: Path) -> None:
    """黑金片名卡（通用版：「故事片场」）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    name_f, sub_f = load_font(font_path, 96), load_font(font_path, 40)
    cy = H // 2 - 130
    d.line([(W // 2 - 250, cy - 60), (W // 2 + 250, cy - 60)], fill=GOLD, width=3)
    draw_centered(d, cy, "故事片场", name_f, WHITE)
    d.line([(W // 2 - 250, cy + 140), (W // 2 + 250, cy + 140)], fill=GOLD, width=3)
    draw_centered(d, cy + 210, "真实素材 × AI 创作", sub_f, GRAY)
    img.save(dest)


def end_card_png(font_path: Path, dest: Path) -> None:
    """片尾 AI 标识卡（≥2s，标识文字 ≥ 短边 5% = 36px，取 40px 留余量）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), BLACK)
    d = ImageDraw.Draw(img)
    main_f, small_f = load_font(font_path, 40), load_font(font_path, 30)
    draw_centered(d, H // 2 - 90, "本片由真实影像与 AI 生成画面结合", main_f, WHITE)
    draw_centered(d, H // 2 + 10, "LuckyNemo · 故事片场", small_f, GRAY)
    d.line([(W // 2 - 200, H // 2 + 90), (W // 2 + 200, H // 2 + 90)], fill=GOLD, width=2)
    img.save(dest)


def subtitle_png(font_path: Path, text: str, dest: Path) -> Path:
    """底部情绪字幕透明底 PNG（高度 160，底部安全区内）。"""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, 160), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = load_font(font_path, 46)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=2)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (W - tw) // 2 - bbox[0], (160 - th) // 2 - bbox[1]
    d.text((x, y), text, font=font, fill=(255, 255, 255, 255),
           stroke_width=3, stroke_fill=(0, 0, 0, 180))
    img.save(dest)
    return dest


def card_segment(png: Path, duration: float, dest: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(duration), "-i", str(png),
         "-f", "lavfi", "-i", "anullsrc=cl=stereo:r=48000",
         "-vf", "fps={},format=yuv420p".format(FPS), "-c:v", "libx264", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", "-shortest", str(dest)],
        "卡片段 " + png.name)


def cut_segment(src: Path, start: float, duration: float,
                subtitle: Path | None, dest: Path) -> None:
    """截取一镜：cover 裁满 720x1280，保留原声。"""
    base = ("scale={}:{}:force_original_aspect_ratio=increase,crop={}:{},"
            "fps={},format=yuv420p").format(W, H, W, H, FPS)
    if subtitle:
        vf = "[0:v]{}[b];[b][1:v]overlay=0:{}[v]".format(base, H - 220)
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "{:.2f}".format(start), "-i", str(src),
               "-i", str(subtitle), "-t", "{:.2f}".format(duration),
               "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
               "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "128k", str(dest)]
    else:
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "{:.2f}".format(start), "-i", str(src),
               "-t", "{:.2f}".format(duration), "-vf", base,
               "-c:v", "libx264", "-crf", "20", "-c:a", "aac", "-b:a", "128k", str(dest)]
    run(cmd, "截取 {} +{:.1f}s".format(src.name, duration))


def pick_subtitles(tone: str, n: int) -> list:
    pool = SUBTITLE_POOLS["funny"] if any(
        w in (tone or "") for w in ("搞笑", "爆笑", "欢乐", "吐槽", "幽默", "无厘头")) \
        else SUBTITLE_POOLS["warm"]
    return pool[:max(3, min(5, n))]


def assemble(shots: list, materials: dict, bgm_path: Path, font_path: Path,
             work_dir: Path, out_path: Path, subtitles: list | None = None) -> dict:
    """镜表 → 成片。

    shots: [{"oss_key","in","out"}...]（in/out 已钳制到素材范围内）
    materials: {oss_key: 本地文件 Path}
    返回 {duration, width, height, fps, shots: n, segments: [...]}。
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    segments: list = []

    tpng = work_dir / "title.png"
    title_card_png(font_path, tpng)
    card_segment(tpng, 2.0, work_dir / "seg_title.mp4")
    segments.append({"kind": "card", "label": "片名卡 2.0s", "file": "seg_title.mp4"})

    subs = subtitles if subtitles is not None else pick_subtitles("", len(shots))
    for i, shot in enumerate(shots):
        sid = i + 1
        src = materials.get(shot["oss_key"])
        if not src or not Path(src).is_file():
            raise RuntimeError("素材缺失：{}".format(shot["oss_key"]))
        start = max(0.0, float(shot.get("in") or 0.0))
        end = min(float(shot.get("out") or 0.0), probe_duration(src))
        if end - start < 0.8:  # 窗口塌缩/越界 → 兜底素材中段 3s
            dur_src = probe_duration(src)
            start = max(0.0, dur_src / 2 - 1.5)
            end = min(dur_src, start + 3.0)
        dur = round(end - start, 2)
        sub = None
        if sid <= len(subs):
            sub = subtitle_png(font_path, subs[sid - 1], work_dir / "sub_{:02d}.png".format(sid))
        dest = work_dir / "seg_{:02d}.mp4".format(sid)
        cut_segment(Path(src), start, dur, sub, dest)
        segments.append({"kind": "real", "label": "第{}镜 {:.1f}-{:.1f}s".format(sid, start, end),
                         "file": dest.name})

    epng = work_dir / "end.png"
    end_card_png(font_path, epng)
    card_segment(epng, 2.5, work_dir / "seg_end.mp4")
    segments.append({"kind": "card", "label": "AI 标识卡 2.5s", "file": "seg_end.mp4"})

    list_file = work_dir / "concat.txt"
    list_file.write_text("".join(
        "file '{}'\n".format((work_dir / s["file"]).as_posix()) for s in segments))
    mixed = work_dir / "mixed.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c", "copy", str(mixed)], "拼接")
    total = probe_duration(mixed)
    bgm_fade = ("[1:a]afade=t=in:st=0:d=1.5,afade=t=out:st={:.2f}:d=3,"
                "volume=0.35[bgm];[0:a]volume=0.9[orig];"
                "[orig][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
                ).format(max(0, total - 3))
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mixed), "-i", str(bgm_path),
         "-filter_complex", bgm_fade, "-map", "0:v", "-map", "[aout]",
         "-vf", "fps={},format=yuv420p".format(FPS), "-c:v", "libx264", "-crf", "20",
         "-video_track_timescale", "24000",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out_path)],
        "BGM 混流")

    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams",
         "-show_format", str(out_path)], capture_output=True, text=True).stdout)
    vstream = next(s for s in probe["streams"] if s["codec_type"] == "video")
    astream = next((s for s in probe["streams"] if s["codec_type"] == "audio"), None)
    meta = {"duration": float(probe["format"]["duration"]),
            "width": vstream["width"], "height": vstream["height"],
            "fps": eval(vstream["avg_frame_rate"]), "audio": bool(astream),
            "shots": len(shots), "segments": segments}
    log("完成：{}（{:.1f}s，{}x{}@{}fps，音轨{}）".format(
        out_path, meta["duration"], meta["width"], meta["height"], meta["fps"],
        "在位" if astream else "缺失"))
    return meta
