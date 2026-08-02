"""FFmpeg 封装：拼接、竖版转换、字幕烧录、AI 标识片尾卡。

需要系统已安装 ffmpeg / ffprobe（macOS: brew install ffmpeg）。
未安装时所有函数抛出带安装指引的 FFmpegNotFoundError。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

#: macOS / Linux 常见中文字体，按顺序尝试（drawtext 烧录中文必须指定 fontfile）
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]


class FFmpegNotFoundError(RuntimeError):
    """系统未安装 ffmpeg/ffprobe。"""


def _require_ffmpeg() -> None:
    """检查 ffmpeg/ffprobe 存在，否则抛出带安装指引的异常。"""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        raise FFmpegNotFoundError(
            f"未找到系统命令：{', '.join(missing)}。请先安装 ffmpeg"
            f"（macOS: brew install ffmpeg；Ubuntu: apt install ffmpeg）。"
        )


def _run(cmd: list[str]) -> None:
    """执行命令；失败时抛出含 stderr 的异常。"""
    print("[ffmpeg]", " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 执行失败（exit {proc.returncode}）：\n{proc.stderr[-3000:]}")


def _find_font() -> str | None:
    """找一个可用的中文字体文件；找不到返回 None。"""
    for font in FONT_CANDIDATES:
        if Path(font).is_file():
            return font
    return None


def _render_text_png(text: str, *, fontsize: int, dest: Path,
                     color: tuple[int, int, int] = (255, 255, 255),
                     stroke: int = 2) -> Path:
    """用 PIL 把文字渲染成带透明底的 PNG（描边黑边）。

    不依赖 ffmpeg 的 drawtext 滤镜（部分 ffmpeg 构建未带 libfreetype），
    中文字体由 PIL 控制，跨环境稳定。找不到中文字体时退回默认字体并警告。
    """
    from PIL import Image, ImageDraw, ImageFont

    font = None
    font_path = _find_font()
    if font_path:
        try:
            font = ImageFont.truetype(font_path, fontsize)
        except OSError:
            font = None
    if font is None:
        print(f"[ffmpeg_utils] 警告：未找到中文字体，使用默认字体（中文可能变形）：{text[:20]}")
        try:
            font = ImageFont.load_default(size=fontsize)  # Pillow ≥10 支持 size
        except TypeError:
            font = ImageFont.load_default()
    # 量出文字尺寸，四周留白 + 描边余量
    probe = Image.new("RGBA", (8, 8))
    bbox = ImageDraw.Draw(probe).textbbox((0, 0), text, font=font, stroke_width=stroke)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = stroke * 2 + 4
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=(*color, 255),
              stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    img.save(dest)
    return dest


def probe_video(path: str | Path) -> dict:
    """读取视频宽/高/是否有音频流。"""
    _require_ffmpeg()
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_streams", "-show_format", str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败：{path}\n{proc.stderr[-2000:]}")
    info = json.loads(proc.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    return {
        "width": int(video.get("width", 1920)),
        "height": int(video.get("height", 1080)),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def concat_segments(
    clips: list[str | Path],
    out: str | Path,
    *,
    audio: str | Path | None = None,
    bgm: str | Path | None = None,
    bgm_volume: float = 0.25,
) -> Path:
    """按顺序拼接视频片段为一条成片。

    :param clips: 片段路径列表（按分镜顺序排好）
    :param audio: 可选旁白音轨；给了就以它为主音轨并 -shortest 截齐
    :param bgm: 可选背景音乐；与 audio 同时给时用 amix 混流（旁白 1.0，BGM 0.25）
    :param bgm_volume: BGM 音量（默认 0.25，避免压过旁白）
    """
    _require_ffmpeg()
    if not clips:
        raise ValueError("clips 不能为空")
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as fh:
        for clip in clips:
            fh.write(f"file '{Path(clip).resolve()}'\n")
        list_file = fh.name
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file]
    if audio and bgm:
        # 旁白（1:a）音量 1.0 + BGM（2:a）音量 bgm_volume，amix 混流
        cmd += [
            "-i", str(audio), "-i", str(bgm),
            "-filter_complex",
            f"[1:a]volume=1.0[nar];[2:a]volume={bgm_volume}[m];[nar][m]amix=inputs=2:duration=longest[aout]",
            "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-shortest",
        ]
    elif audio or bgm:
        only = audio or bgm
        cmd += ["-i", str(only), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-shortest"]
    else:
        cmd += ["-an"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(out_path)]
    _run(cmd)
    Path(list_file).unlink(missing_ok=True)
    return out_path


def make_vertical_916(src: str | Path, out: str | Path, *, width: int = 1080, height: int = 1920) -> Path:
    """横版转 9:16 竖版（等比缩放 + 黑边填充），用于朋友圈/抖音版交付。"""
    _require_ffmpeg()
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
    )
    _run(["ffmpeg", "-y", "-i", str(src), "-vf", vf, "-c:v", "libx264",
          "-pix_fmt", "yuv420p", "-c:a", "aac", str(out_path)])
    return out_path


def burn_subtitle(
    src: str | Path,
    out: str | Path,
    text: str,
    *,
    fontsize: int = 48,
    bottom_margin: int = 80,
) -> Path:
    """把单行文字烧录到画面底部居中（如日期字幕）。

    用 PIL 渲染文字 PNG + overlay 滤镜实现，不依赖 ffmpeg drawtext
    （部分 ffmpeg 构建未带 libfreetype，drawtext 不可用）。
    """
    _require_ffmpeg()
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp_dir:
        text_png = _render_text_png(text, fontsize=fontsize, dest=Path(tmp_dir) / "text.png")
        overlay = f"overlay=(main_w-overlay_w)/2:main_h-overlay_h-{bottom_margin}"
        _run(["ffmpeg", "-y", "-i", str(src), "-i", str(text_png),
              "-filter_complex", f"[0:v][1:v]{overlay}",
              "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out_path)])
    return out_path


def add_end_card(
    src: str | Path,
    out: str | Path,
    *,
    text: str = "本片由 AI 生成",
    duration: float = 2.5,
) -> Path:
    """在片尾追加黑底白字"AI 生成"标识卡（合规要求 ≥2 秒，GB 45438-2025）。

    实现：先生成与源同分辨率的黑底字幕卡，再用 concat 滤镜拼接
    （源无音轨时补静音轨，保证 concat 滤镜 a=1 不失败）。
    """
    _require_ffmpeg()
    if duration < 2.0:
        raise ValueError(f"AI 标识卡时长必须 ≥2 秒（GB 45438-2025），收到 {duration}")
    src_path = Path(src)
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta = probe_video(src_path)
    w, h = meta["width"], meta["height"]

    with tempfile.TemporaryDirectory() as tmp_dir:
        card = Path(tmp_dir) / "card.mp4"
        src_norm = Path(tmp_dir) / "src_norm.mp4"
        fontsize = max(int(min(w, h) * 0.05), 24)  # 文字高度 ≥ 最短边 5%（GB 45438-2025）
        text_png = _render_text_png(text, fontsize=fontsize, dest=Path(tmp_dir) / "text.png")
        # 1) 生成标识卡：黑底 + 文字 PNG 居中 + 静音轨（不依赖 drawtext）
        _run([
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:d={duration}:r=30",
            "-i", str(text_png),
            "-f", "lavfi", "-i", "anullsrc=cl=stereo:r=44100",
            "-filter_complex", "[0:v][1:v]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest", str(card),
        ])
        # 2) 源片归一化（统一编码参数；无音轨则补静音轨）
        norm_cmd = ["ffmpeg", "-y", "-i", str(src_path)]
        if not meta["has_audio"]:
            norm_cmd += ["-f", "lavfi", "-i", "anullsrc=cl=stereo:r=44100", "-shortest"]
        norm_cmd += ["-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src_norm)]
        _run(norm_cmd)
        # 3) concat 滤镜拼接
        _run([
            "ffmpeg", "-y", "-i", str(src_norm), "-i", str(card),
            "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]",
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out_path),
        ])
    return out_path
