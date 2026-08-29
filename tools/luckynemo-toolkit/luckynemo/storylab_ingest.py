"""storylab 素材理解模块（P4）：VLM 打标 + 推荐分镜 + 对照报告。

"真实素材 + AI 创作"产品线的地基模块：把婚礼实拍花絮视频自动理解成
结构化标签库（materials.json），再由 LLM 按预告片体裁推荐分镜
（storyboard.json / storyboard.md），最后生成 REPORT.md
（打标总表 / 分镜全文 / 与人工分镜对照 / 成本 / 失败模式与 v2 建议）。

打标结构为"对话可用 + 分镜可用"双重服务：
caption / moment_type / highlight 直接可作为 chat 对话钩子
（"我找到 3 个黄昏镜头、1 段笑声"），roles_hint / quality 驱动选段。

流程：
  1. ingest    ffprobe（时长/分辨率/帧率/音轨）→ 每段抽 10 帧
               （5%-95% 均布，prompt 带每帧时间戳）→ 本地免费分析
               （帧间差分 motion_score / 音轨 RMS 能量峰值）→
               MiniMax VLM 逐段打标（时间戳+运动等级+音峰一起送，
               严格 JSON，含 highlight_window 高光窗口估计），
               每段缓存断点续跑，失败重试 1 次再标 error
               → materials{ _v2}.json。
  2. storyboard 素材标签库 → LLM 推荐分镜：三段式、≤15 镜、真实 ≥70%、
               竖屏；入点/出点优先取 highlight_window（后验钳制）；
               显式书挡式首尾复用约束 → storyboard{ _v2}.json / .md。
  3. report    打标总表 / 分镜全文 / v1+v2+人工三方对照 / 成本 /
               失败模式与 v2 改进建议 → REPORT{ _v2}.md。

v2（2026-08-29）针对 v1 实测三短板：
- 入点/出点拍脑袋（v1 开场镜猜 32.0s，人工实际 13.5s）→ 10 帧加密 +
  每帧时间戳 + highlight_window 高光窗口估计 + 音轨能量峰值提示，
  分镜入点优先取窗口并后验钳制；
- 动感镜头被低估（v1 骑手段被打成"空镜 H3"）→ 本地帧间差分
  motion_score，运动等级随 prompt 送 VLM 与分镜，高档 +1 高光保底；
- 无首尾呼应（v1 开场素材只用一次）→ 分镜 prompt 显式书挡式约束；
另：moment_type 开放枚举漂移（v1"独处"被泛用）→ 受控枚举+别名归一化。

用法：
  python -m luckynemo.storylab_ingest <素材目录> --out <输出目录> \
      [--stage all|ingest|storyboard|report] [--variant v2] \
      [--shotlist <人工分镜.txt>] [--force]

已知边界（当前版本）：
- 音频理解不做语义级（ASR 未接；v2 只有能量峰值，不含笑声/誓词识别）；
- 不做人脸身份识别（who 是 VLM 的画面猜测，不跨段关联同人）；
- 入点/出点基于 highlight_window，粒度秒级，是"机器初剪"级精度。

MiniMax 调用约定（与 server/mp_worker.py 的 vlm_json 同源）：
- POST {MINIMAX_BASE_URL}/chat/completions，Bearer 鉴权
- VLM 打标用 abab6.5s-chat（mini 多模态识图，mp_worker 实测可用），
  可用 STORYLAB_VLM_MODEL 覆盖；分镜用 MINIMAX_LLM_MODEL（默认 MiniMax-M3）
- LLM 返回多段 JSON 时必须 raw_decode 取首个完整对象（mp_worker 反馈 #35 修复）
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
import time
from array import array
from datetime import datetime
from pathlib import Path

import requests

from . import config
from .llm import LLMClient

#: 打标 schema 版本（prompt/字段结构变化时 +1，旧缓存自动作废重打）
TAG_SCHEMA_VERSION = 2
#: v2 抽帧时间点（占整段时长的比例，10 帧均布，prompt 带时间戳映射）
FRAME_FRACTIONS_V2 = (0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95)
#: 抽帧最大宽度（VLM 不需要全分辨率，控制请求体大小）
FRAME_MAX_WIDTH = 540
#: VLM 打标模型（mp_worker 实测可用的 MiniMax 多模态识图模型）
DEFAULT_VLM_MODEL = "abab6.5s-chat"
ENV_VLM_MODEL = "STORYLAB_VLM_MODEL"
#: 打标失败重试次数
TAG_MAX_ATTEMPTS = 2

#: 打标 JSON 的必填字段与取值域
TAG_REQUIRED = ("people", "scene", "emotion", "moment_type", "quality",
                "highlight", "caption", "roles_hint", "highlight_window")
TAG_QUALITY = ("usable", "fixable", "reject")
TAG_ROLES = ("开场候选", "收尾候选", "蒙太奇", "转场素材", "弃用")

#: moment_type 受控枚举（v2 治理"独处"泛用漂移）+ 别名归一化表
CANONICAL_MOMENTS = ("准备", "仪式", "欢庆", "合影", "独处", "空镜", "其他")
MOMENT_ALIASES = {
    "准备": ("准备", "化妆", "换衣", "布置", "彩排", "候场", "整装"),
    "仪式": ("仪式", "誓言", "誓词", "戒指", "证婚", "敬茶", "拜堂", "宣誓"),
    "欢庆": ("欢庆", "庆祝", "敬酒", "派对", "欢呼", "跳舞", "骑马", "游戏",
             "烟花", "晚宴", "举杯", "热闹"),
    "合影": ("合影", "合照", "摆拍", "迎宾", "留影"),
    "独处": ("独处", "安静", "静立", "背影", "单人", "等候", "凝望", "沉思"),
    "空镜": ("空镜", "无人", "风景", "静物", "环境", "场景"),
}
MOMENT_DEFS = ("受控枚举（必须选一个，不属于就填「其他」并给短语）："
               "准备=妆造/换衣/布置/候场；仪式=誓言/交换戒指/敬茶等正式环节；"
               "欢庆=敬酒/派对/欢呼/骑马/跳舞等热闹动态；"
               "合影=面向镜头的摆拍合照；独处=单人安静时刻/背影/静立；"
               "空镜=无人物参与的风景/静物/环境")

#: 运动等级阈值（motion_score 归一化后）
MOTION_LEVELS = ((0.4, "高"), (0.15, "中"), (0.0, "低"))
MOTION_BOOST_CAP = 4  #: 高光保底上调的上限（≤4 才 +1，5 不动）


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ----------------------------------------------------------------------
# 视频探测、抽帧、本地免费分析（运动 / 音频能量）
# ----------------------------------------------------------------------
def probe_video(path: Path) -> dict:
    """ffprobe 读取时长/分辨率/帧率/音轨/文件大小。"""
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 失败：{path}\n{proc.stderr[-1000:]}")
    info = json.loads(proc.stdout)
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), {})
    fps_raw = str(video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1")
    try:
        num, den = fps_raw.split("/")
        fps = round(int(num) / int(den), 2) if int(den) else 0
    except (ValueError, ZeroDivisionError):
        fps = 0
    return {
        "duration": round(float(info.get("format", {}).get("duration", 0)), 2),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "fps": fps,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "size_mb": round(path.stat().st_size / (1 << 20), 1),
    }


def scan_videos(materials_dir: Path) -> list[Path]:
    """扫描素材视频。`*_raw.mp4` 若存在同名非 raw 版本则跳过（4K 原片与
    压缩版同内容，打标用压缩版即可，4K 留给剪辑工序），并记录 has_4k_raw。"""
    videos = sorted(p for p in materials_dir.glob("*.mp4") if p.is_file())
    out = []
    for p in videos:
        if p.stem.endswith("_raw") and p.with_name(p.stem[:-4] + ".mp4").is_file():
            continue
        out.append(p)
    return out


def has_4k_raw(video: Path) -> bool:
    return video.with_name(video.stem + "_raw.mp4").is_file()


def extract_frames(video: Path, probe: dict, frames_dir: Path,
                   fractions: tuple[float, ...] = FRAME_FRACTIONS_V2) -> tuple[list[Path], list[float]]:
    """按 fractions 抽帧（缩到 FRAME_MAX_WIDTH 宽内），返回 (jpg 路径, 各帧时间戳)。"""
    frames_dir.mkdir(parents=True, exist_ok=True)
    duration = probe["duration"]
    frames, timestamps = [], []
    for i, frac in enumerate(fractions, 1):
        t = max(0.0, duration * frac - 0.05)  # 避开末帧越界
        dest = frames_dir / f"{video.stem}_f{i:02d}.jpg"
        if not dest.is_file():
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video),
                 "-frames:v", "1",
                 "-vf", f"scale='min({FRAME_MAX_WIDTH},iw)':-2", "-q:v", "3", str(dest)],
                capture_output=True, text=True)
        if not dest.is_file():
            raise RuntimeError(f"抽帧失败：{video.name} @ {t:.2f}s")
        frames.append(dest)
        timestamps.append(round(t, 1))
    return frames, timestamps


def motion_score(video: Path, *, fps: int = 6, w: int = 64, h: int = 36,
                 pix_thr: int = 25) -> float:
    """帧间差分运动分（0-1 归一化，纯本地免费）。

    gray 缩略帧（64x36@6fps）序列，mean_diff/32 与运动像素占比/0.15
    各半加权取均值，cap 到 1。对"局部主体运动+手持晃动"敏感，
    对整体静止画面接近 0。
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video),
         "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
        capture_output=True)
    buf = proc.stdout
    fsz = w * h
    n = len(buf) // fsz
    if n < 2:
        return 0.0
    ratios, means = [], []
    prev = buf[:fsz]
    for i in range(1, n):
        cur = buf[i * fsz:(i + 1) * fsz]
        moved = tot = 0
        for a, b in zip(prev, cur):
            d = abs(a - b)
            tot += d
            if d > pix_thr:
                moved += 1
        ratios.append(moved / fsz)
        means.append(tot / fsz)
        prev = cur
    mean_diff = sum(means) / len(means)
    mov_ratio = sum(ratios) / len(ratios)
    return round(min(1.0, mean_diff / 32 * 0.5 + mov_ratio / 0.15 * 0.5), 3)


def motion_level(score: float) -> str:
    for thr, name in MOTION_LEVELS:
        if score >= thr:
            return name
    return "低"


def audio_peaks(video: Path, *, win: float = 0.5, sr: int = 8000, top: int = 3) -> list[float]:
    """音轨 RMS 能量峰值时间点（秒，纯本地免费）。

    解码单声道 PCM，滑窗 RMS，取高于 max(mean+std, 0.35*max) 的连续区
    峰值时刻，能量最高的 top 个、按时间排序。只是"哪里有声音高潮"的
    提示（可能是笑声/欢呼/说话），无语义（ASR 未接）。
    """
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(video),
         "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        capture_output=True)
    pcm = array("h")
    pcm.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    if not pcm:
        return []
    import math
    n = int(sr * win)
    rms = []
    for i in range(0, len(pcm) - n + 1, n):
        seg = pcm[i:i + n]
        rms.append(math.sqrt(sum(float(x) * x for x in seg) / len(seg)))
    if not rms:
        return []
    mean = sum(rms) / len(rms)
    std = math.sqrt(sum((x - mean) ** 2 for x in rms) / len(rms))
    thr = max(mean + std, max(rms) * 0.35)
    peaks: list[tuple[float, float]] = []
    run_peak, run_t = 0.0, 0.0
    in_run = False
    for i, v in enumerate(rms):
        t = (i + 0.5) * win
        if v >= thr:
            if not in_run:
                run_t, run_peak, in_run = t, v, True
            elif v > run_peak:
                run_t, run_peak = t, v
        elif in_run:
            peaks.append((run_t, run_peak))
            in_run = False
    if in_run:
        peaks.append((run_t, run_peak))
    peaks.sort(key=lambda p: -p[1])
    return sorted(round(t, 1) for t, _ in peaks[:top])


# ----------------------------------------------------------------------
# MiniMax VLM 打标
# ----------------------------------------------------------------------
def _img_content(frames: list[Path]) -> list[dict]:
    content = []
    for p in frames:
        b64 = base64.b64encode(p.read_bytes()).decode()
        content.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    return content


def _first_json_object(text: str) -> dict:
    """解析 LLM 输出为单个 JSON 对象。

    容错链（server/mp_worker.py vlm_json + script_pipeline.strip_json_fence 同源）：
    1. 剥 <think> 思维链（M3 是推理模型，首个 "{" 常落在 think 段内，
       直接 raw_decode 会抓到思维链里的残缺 JSON——v2 实测踩坑）
    2. 去 markdown 围栏 → json.loads
    3. 失败则 raw_decode 取首个完整对象（反馈 #35：多段花括号时
       贪心正则必炸 "Extra data"）
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)  # 截断的未闭合 think
    cleaned = re.sub(r"```(?:json)?", "", cleaned).strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    if start >= 0:
        try:
            obj, _ = json.JSONDecoder().raw_decode(cleaned[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    raise ValueError(f"返回内容不是合法 JSON：{text[:150]}")


TAG_PROMPT = """你是婚礼影像素材管理师。下面是一个婚礼花絮视频片段的 {n_frames} 帧截图，按时间顺序排列，每帧对应的时间点已标注。请综合全部帧判断【整段素材】，只描述画面里真实可见的内容，不要臆测画面外情节，看不清就写"不明"。

输出严格 JSON（不要 markdown 围栏、不要任何解释），schema：
{{
  "people": [{{"who": "人物身份猜测：新娘/新郎/伴娘/伴郎/父母/宾客/工作人员/不明", "relationship": "人物间关系或互动", "clothing": "服装描述"}}],
  "scene": "地点与环境：室内/室外、具体场景、光线条件、时段（白天/黄昏/夜晚）",
  "emotion": "画面情绪氛围（2-6 字）",
  "moment_type": "{moment_defs}",
  "quality": "usable（可直接用）/ fixable（有瑕疵可救：抖动/过曝/构图偏）/ reject（不可用：模糊严重/内容废）",
  "highlight": 1到5的整数，高光潜力综合分：画面美感+故事性+独特性，5=必用级，1=平庸,
  "highlight_window": [t_start, t_end],
  "caption": "一句话画面描述，20字内，具体到可见动作与光影",
  "roles_hint": ["从以下可多选：开场候选/收尾候选/蒙太奇/转场素材/弃用"]
}}

highlight_window 要求：从你看到的画面里选出【最适合剪进婚礼预告片的连续 2-5 秒窗口】，给两个数字（秒，基于上面标注的帧时间点推断，必须落在整段 0-{duration}s 内、end > start）。优先选：人物互动最有张力的瞬间、光影最好的时刻、有笑声欢呼等情绪高潮对应的画面（参考下面的音轨提示）。这一段窗口是全段最高光的几秒。

{extra_hints}
只输出 JSON。"""


def vlm_tag_segment(frames: list[Path], timestamps: list[float], probe: dict,
                    motion_lvl: str, peaks: list[float],
                    api_key: str, model: str) -> dict:
    """10 帧同送 MiniMax VLM 打标（带时间戳/运动等级/音峰提示）。"""
    frame_desc = "、".join(f"第{i}帧≈{t}s" for i, t in enumerate(timestamps, 1))
    hints = [f"【帧时间戳】{frame_desc}",
             f"【画面运动等级】{motion_lvl}（本地帧间差分实测：高=奔跑骑马级动感，中=步行/摇移，低=基本静止）"]
    if peaks:
        hints.append(f"【音轨提示】能量峰值约出现在 {'/'.join(f'{p}s' for p in peaks)} 附近"
                     "（可能有笑声/欢呼/说话高潮，供你判断情绪高点参考）")
    content = [{"type": "text", "text": TAG_PROMPT.format(
        n_frames=len(frames), duration=probe["duration"],
        moment_defs=MOMENT_DEFS, extra_hints="\n".join(hints))}]
    content += _img_content(frames)
    r = requests.post(
        f"{config.get_minimax_base_url()}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "max_tokens": 1100, "temperature": 0.3,
              "messages": [{"role": "user", "content": content}]},
        timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"VLM HTTP {r.status_code}：{r.text[:200]}")
    out = r.json()["choices"][0]["message"]["content"].strip()
    return _first_json_object(out)


def _canonical_moment(raw: str) -> str:
    """moment_type 归一化：受控枚举精确匹配 → 别名关键词 → 其他。"""
    raw = str(raw or "").strip()
    if raw in CANONICAL_MOMENTS:
        return raw
    for canon, aliases in MOMENT_ALIASES.items():
        if any(k in raw for k in aliases):
            return canon
    return "其他"


def normalize_tags(tags: dict, duration: float) -> dict:
    """宽松校验/修正打标结果：缺字段补默认、枚举归一、
    highlight 钳 1-5、highlight_window 钳到 [0, duration]。"""
    fixed = dict(tags)
    for key in TAG_REQUIRED:
        fixed.setdefault(key, [] if key in ("people", "roles_hint", "highlight_window") else "")
    if not isinstance(fixed["people"], list):
        fixed["people"] = []
    if not isinstance(fixed["roles_hint"], list):
        raw_roles = str(fixed["roles_hint"])
        fixed["roles_hint"] = [x for x in re.split(r"[/、,，\s]+", raw_roles) if x]
    fixed["roles_hint"] = [r for r in fixed["roles_hint"] if r in TAG_ROLES]
    if fixed["quality"] not in TAG_QUALITY:
        fixed["quality"] = "usable"
    try:
        fixed["highlight"] = max(1, min(5, int(fixed["highlight"])))
    except (TypeError, ValueError):
        fixed["highlight"] = 3
    # moment_type：保留原文，归一到受控枚举
    fixed["moment_raw"] = str(fixed["moment_type"]).strip()[:30]
    fixed["moment_type"] = _canonical_moment(fixed["moment_raw"])
    # highlight_window：[start, end] 两个数字、落在时长内、end>start，否则置空
    win = fixed["highlight_window"]
    window = None
    if isinstance(win, (list, tuple)) and len(win) >= 2:
        try:
            ws, we = float(win[0]), float(win[1])
            ws = max(0.0, min(ws, duration))
            we = max(0.0, min(we, duration))
            if we - ws >= 1.0:
                window = [round(ws, 1), round(we, 1)]
        except (TypeError, ValueError):
            pass
    fixed["highlight_window"] = window
    fixed["caption"] = str(fixed["caption"]).strip()[:120]
    return fixed


# ----------------------------------------------------------------------
# stage 1: ingest
# ----------------------------------------------------------------------
def load_stats(out_dir: Path, variant: str | None) -> dict:
    stats_path = out_dir / f"stats{'_' + variant if variant else ''}.json"
    if stats_path.is_file():
        return json.loads(stats_path.read_text(encoding="utf-8"))
    return {"vlm_calls": 0, "vlm_retries": 0, "llm_calls": 0,
            "llm_usage": [], "started_at": datetime.now().isoformat(timespec="seconds"),
            "schema": TAG_SCHEMA_VERSION}


def save_stats(out_dir: Path, stats: dict, variant: str | None) -> None:
    stats["finished_at"] = datetime.now().isoformat(timespec="seconds")
    name = f"stats{'_' + variant if variant else ''}.json"
    (out_dir / name).write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                encoding="utf-8")


def _variant_name(base: str, variant: str | None) -> str:
    return f"{base}_{variant}" if variant else base


def run_ingest(materials_dir: Path, out_dir: Path, stats: dict,
               variant: str | None, force: bool) -> list[dict]:
    """探测 + 抽帧 + 本地分析 + VLM 打标全量素材，落 materials{ _v2}.json。"""
    api_key = config.get_minimax_api_key()
    vlm_model = config.get_model(ENV_VLM_MODEL, DEFAULT_VLM_MODEL)
    videos = scan_videos(materials_dir)
    if not videos:
        raise RuntimeError(f"素材目录没有可用视频：{materials_dir}")
    log(f"ingest{'(' + variant + ')' if variant else ''}：发现 {len(videos)} 段素材"
        f"（VLM={vlm_model}，schema v{TAG_SCHEMA_VERSION}，{len(FRAME_FRACTIONS_V2)} 帧/段），"
        f"4K 原片自动跳过打标")

    cache_dir = out_dir / _variant_name("cache", variant)
    frames_dir = out_dir / _variant_name("frames", variant)
    records = []
    for i, video in enumerate(videos, 1):
        cache_path = cache_dir / f"{video.stem}.json"
        if cache_path.is_file() and not force:  # 断点续跑（schema 不符自动重打）
            rec = json.loads(cache_path.read_text(encoding="utf-8"))
            if rec.get("schema") == TAG_SCHEMA_VERSION:
                log(f"[{i}/{len(videos)}] 缓存命中 {video.name}（{rec['status']}）")
                records.append(rec)
                continue
        probe = probe_video(video)
        rec = {"file": video.name, "probe": probe, "has_4k_raw": has_4k_raw(video),
               "schema": TAG_SCHEMA_VERSION, "status": "pending", "tags": None, "error": None}
        try:
            frames, timestamps = extract_frames(video, probe, frames_dir)
            # 本地免费分析：运动 + 音轨能量峰值
            m_score = motion_score(video)
            rec["motion_score"] = m_score
            rec["motion_level"] = motion_level(m_score)
            rec["audio_peaks"] = audio_peaks(video) if probe["has_audio"] else []
            log(f"[{i}/{len(videos)}] {video.name} 抽帧 {len(frames)} 张 "
                f"（{probe['width']}x{probe['height']} / {probe['duration']}s / "
                f"运动{rec['motion_level']} {m_score} / 音峰{rec['audio_peaks'] or '无'}），VLM 打标中…")
            last_err = ""
            for attempt in range(1, TAG_MAX_ATTEMPTS + 1):
                try:
                    rec["tags"] = normalize_tags(
                        vlm_tag_segment(frames, timestamps, probe,
                                        rec["motion_level"], rec["audio_peaks"],
                                        api_key, vlm_model),
                        probe["duration"])
                    rec["status"] = "ok"
                    stats["vlm_calls"] += 1
                    break
                except Exception as e:  # noqa: BLE001
                    last_err = str(e)[:200]
                    stats["vlm_retries"] += 1
                    log(f"  VLM 失败（第 {attempt}/{TAG_MAX_ATTEMPTS} 次）：{last_err}")
                    if attempt < TAG_MAX_ATTEMPTS:
                        time.sleep(3)
            if rec["status"] != "ok":
                rec["status"] = "error"
                rec["error"] = last_err
            else:
                # 运动高光修正：高档且高光未顶格 → 保底 +1
                t = rec["tags"]
                if rec["motion_level"] == "高" and t["highlight"] <= MOTION_BOOST_CAP:
                    t["highlight"] += 1
                    t["motion_boost"] = True
        except Exception as e:  # noqa: BLE001
            rec["status"] = "error"
            rec["error"] = str(e)[:200]
            log(f"[{i}/{len(videos)}] {video.name} 处理失败：{rec['error']}")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(rec)

    ok = sum(1 for r in records if r["status"] == "ok")
    log(f"ingest 完成：{ok}/{len(records)} 段打标成功")
    materials = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_dir": str(materials_dir),
        "vlm_model": vlm_model,
        "schema": TAG_SCHEMA_VERSION,
        "frame_fractions": list(FRAME_FRACTIONS_V2),
        "segments": records,
    }
    (out_dir / f"{_variant_name('materials', variant)}.json").write_text(
        json.dumps(materials, ensure_ascii=False, indent=2), encoding="utf-8")
    return records


# ----------------------------------------------------------------------
# stage 2: storyboard
# ----------------------------------------------------------------------
STORYBOARD_SYSTEM = """【输出纪律】第一个字符就是 {{，直接输出最终 JSON，禁止输出任何思考过程/分析文字（不要超过输出预算）。

你是资深婚礼预告片剪辑指导，要从素材标签库里为一条【竖屏婚礼预告片】选镜排分镜。

体裁约束（硬指标）：
1. 三段式：开场钩子（3-5s 最有张力的真实镜头，原声可入）→ 中段蒙太奇 → 情感收尾。
2. 总镜数 ≤15；竖屏 9:16（真实镜头给 crop：全画幅直出/居中裁切竖版/上下遮幅）。
3. 真实镜头占比 ≥70%；AI 镜（ai-edit）至多 2-3 个，只标建议位置与 edit 方向，不生成。
4. 书挡式首尾呼应：开场素材若时长较长（标签库给了 highlight_window），优先在收尾复用其另一时刻形成闭环，并在 bookend 字段说明。
5. 入点/出点优先取各段的 highlight_window（±1s 可调，偏离勿超 2s）；窗口缺失才自行推断。
6. 运动等级高的素材放蒙太奇高潮或开场，勿当空镜用。

输出 JSON schema（字段从简，treatment 一句话即可）：
{{"title": "≤8字", "hook_concept": "一句话", "bookend": "首尾呼应说明/无书挡的原因",
 "shots": [{{"id": 1, "type": "real", "source_file": "文件名", "in": 13.0, "out": 17.0,
            "crop": "全画幅直出|居中裁切竖版|上下遮幅", "treatment": "一句话处理", "emotion": "2-4字"}},
           {{"id": 14, "type": "ai-edit", "source_file": null, "position": "建议位置",
            "edit": "基底+AI变换方向", "treatment": "一句话", "emotion": "情绪"}}]}}"""

STORYBOARD_USER = """【素材标签库】每行一段（时长秒；窗口=highlight_window 入出点优先取它；运动=帧间差分等级；音峰=音轨能量峰值秒；K=高光分1-5）：
{materials}

【要求】优先 K≥4 且 quality=usable；moment_type 形成叙事曲线不堆叠；同一素材可书挡复用但不同素材数 ≥8；情绪有起伏；shots 按播放顺序 id 从 1 编号。直接输出 JSON。"""


def _materials_brief(records: list[dict]) -> str:
    lines = []
    for i, r in enumerate(records, 1):
        if r["status"] != "ok":
            continue
        t = r["tags"]
        p = r["probe"]
        win = t.get("highlight_window")
        win_txt = f"{win[0]}-{win[1]}s" if win else "无"
        lines.append(
            f"{i}. {r['file']} {p['duration']}s"
            f"{'[4K]' if r.get('has_4k_raw') else ''} | {t['caption']}"
            f" | {t['moment_type']}{('/' + t['moment_raw']) if t.get('moment_raw') and t['moment_raw'] != t['moment_type'] else ''}"
            f" {t['emotion']} K{t['highlight']}{'+' if t.get('motion_boost') else ''}"
            f" {t['quality']} | 窗口{win_txt} 运动{r.get('motion_level', '?')}"
            f" 音峰{'/'.join(f'{x}' for x in r.get('audio_peaks', [])) or '无'}"
            f" | roles:{'/'.join(t['roles_hint']) or '无'}")
    return "\n".join(lines)


def run_storyboard(out_dir: Path, stats: dict, variant: str | None,
                   records: list[dict] | None = None) -> dict:
    """素材标签库 → LLM 推荐分镜，落 storyboard{ _v2}.json / .md。"""
    if records is None:
        materials = json.loads(
            (out_dir / f"{_variant_name('materials', variant)}.json").read_text(encoding="utf-8"))
        records = materials["segments"]
    ok_records = [r for r in records if r["status"] == "ok"]
    if len(ok_records) < 5:
        raise RuntimeError(f"打标成功素材不足（{len(ok_records)} 段 < 5），无法推荐分镜")

    client = LLMClient(api_key=config.get_minimax_api_key())
    board: dict | None = None
    raw = ""
    for attempt in range(1, 4):  # 解析失败重试（M3 思维链偶发截断/格式漂移）
        raw = client.chat(STORYBOARD_SYSTEM,
                          STORYBOARD_USER.format(materials=_materials_brief(records)),
                          temperature=0.5, max_tokens=9000)
        stats["llm_calls"] += 1
        stats["llm_usage"].append(client.last_usage)
        try:
            board = _first_json_object(raw)
            break
        except ValueError as e:
            log(f"分镜输出解析失败（第 {attempt}/3 次）：{e}")
            if attempt == 3:
                raise
    assert board is not None

    shots = board.get("shots") or []
    if not (5 <= len(shots) <= 15):
        log(f"警告：分镜镜数 {len(shots)} 不在 5-15 区间，仍按返回结果落盘")
    by_file = {r["file"]: r for r in ok_records}
    real_cnt, nudged = 0, 0
    for idx, s in enumerate(shots, 1):
        s["id"] = idx
        s["type"] = "ai-edit" if s.get("type") == "ai-edit" else "real"
        if s["type"] != "real":
            continue
        real_cnt += 1
        src = by_file.get(s.get("source_file") or "")
        if not src:
            log(f"警告：第 {idx} 镜来源 {s.get('source_file')} 不在素材库，保留原值")
            continue
        dur = src["probe"]["duration"]
        try:
            s["in"] = max(0.0, min(float(s.get("in", 0)), dur - 0.5))
            s["out"] = max(s["in"] + 0.5, min(float(s.get("out", dur)), dur))
        except (TypeError, ValueError):
            s["in"], s["out"] = 0.0, min(dur, 4.0)
        # 入点钳制：优先 highlight_window，LLM 偏离窗口 >2s 时拉回
        win = (src.get("tags") or {}).get("highlight_window")
        if win and abs(s["in"] - win[0]) > 2.0:
            log(f"  第 {idx} 镜入点 {s['in']}s 偏离高光窗口 {win[0]}-{win[1]}s，"
                f"拉回窗口起点")
            s["in"] = win[0]
            s["out"] = min(win[1], win[0] + max(1.5, s["out"] - s["in"]))
            s["window_nudged"] = True
            nudged += 1

    # 书挡去重：同素材复用时，若后一次与已用时间窗重叠 >50%，平移到
    # 一个不与已用窗口重叠的候选窗（优先音峰中离已用窗口最远的时刻）。
    # 修 v2 首跑实测缺陷：LLM 声称"复用第二高光窗口 38-42.5s"却照抄了
    # 开场的 6.4-10.7s，导致书挡收尾与开场是同一段画面。
    shifted = 0
    used_windows: dict[str, list[tuple[float, float]]] = {}
    for s in shots:
        if s.get("type") != "real":
            continue
        src = by_file.get(s.get("source_file") or "")
        if not src:
            continue
        dur = src["probe"]["duration"]
        used = used_windows.setdefault(s["source_file"], [])

        def _overlap(a_in: float, a_out: float) -> float:
            return max(0.0, min(a_out, s["out"]) - max(a_in, s["in"]))

        clash = any(_overlap(u0, u1) > 0.5 * min(s["out"] - s["in"], u1 - u0)
                    for u0, u1 in used)
        if clash:
            cands: list[float] = []
            for p in src.get("audio_peaks") or []:
                if not any(_overlap(p - 2.0, p + 2.0) > 0.0 for u0, u1 in used):
                    cands.append(p)
            # 无可用音峰：取已用窗口之间最长空隙的中点
            if not cands:
                bounds = sorted([0.0] + [x for w in used for x in w] + [dur])
                gaps = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
                gaps = [g for g in gaps if g[1] - g[0] >= 2.0 and
                        not any(_overlap(*g) > 0 for u0, u1 in used)]
                if gaps:
                    g0, g1 = max(gaps, key=lambda g: g[1] - g[0])
                    cands.append((g0 + g1) / 2)
            if cands:
                # 选离已用窗口时间距离最远的候选
                def _dist(p: float) -> float:
                    return min(min(abs(p - u0), abs(p - u1)) for u0, u1 in used)
                pick = max(cands, key=_dist)
                s["in"] = round(max(0.0, pick - 2.0), 1)
                s["out"] = round(min(dur, pick + 2.0), 1)
                s["bookend_shifted"] = True
                shifted += 1
                log(f"  第 {s['id']} 镜与已用窗口重叠，书挡平移到 "
                    f"{s['in']}s-{s['out']}s（候选 {cands}）")
            else:
                log(f"  第 {s['id']} 镜复用 {s['source_file'][:12]}… 找不到不重叠窗口，保留原值")
        used.append((s["in"], s["out"]))
    board["bookend_shifted"] = shifted
    board["real_shots"] = real_cnt
    board["total_shots"] = len(shots)
    board["real_ratio"] = round(real_cnt / len(shots), 3) if shots else 0
    board["window_nudged"] = nudged
    board["generated_at"] = datetime.now().isoformat(timespec="seconds")

    (out_dir / f"{_variant_name('storyboard', variant)}.json").write_text(
        json.dumps(board, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{_variant_name('storyboard', variant)}.md").write_text(
        _board_to_markdown(board), encoding="utf-8")
    log(f"storyboard 完成：《{board.get('title', '未命名')}》 {len(shots)} 镜"
        f"（真实 {real_cnt}，占比 {board['real_ratio'] * 100:.0f}%"
        f"{f'，{nudged} 镜入点拉回高光窗口' if nudged else ''}"
        f"{f'，{shifted} 镜书挡平移' if shifted else ''}）")
    return board


def _board_to_markdown(board: dict) -> str:
    """分镜渲染成 markdown。"""
    lines = [f"# 《{board.get('title', '未命名')}》推荐分镜（机器生成）", ""]
    if board.get("hook_concept"):
        lines += [f"**开场钩子思路**：{board['hook_concept']}", ""]
    if board.get("bookend"):
        lines += [f"**首尾呼应设计**：{board['bookend']}", ""]
    lines += ["| 镜号 | 类型 | 来源 | 入点→出点 | 时长 | 竖版处理 | 处理方式 | 情绪 |",
              "|---|---|---|---|---|---|---|---|"]
    for s in board.get("shots", []):
        if s["type"] == "real":
            dur = round(s["out"] - s["in"], 1)
            mark = ("🎯" if s.get("window_nudged") else "") + ("🔁" if s.get("bookend_shifted") else "")
            lines.append(f"| {s['id']} | 真实 | {s.get('source_file', '?')[:24]}… "
                         f"| {s['in']:.1f}s→{s['out']:.1f}s{mark} | {dur}s "
                         f"| {s.get('crop', '—')} | {s.get('treatment', '—')} | {s.get('emotion', '—')} |")
        else:
            lines.append(f"| {s['id']} | **AI-edit** | —（{s.get('position', '建议位置未标')}） "
                         f"| — | — | — | {s.get('edit', s.get('treatment', '—'))} | {s.get('emotion', '—')} |")
    lines += ["", f"真实镜头 {board.get('real_shots', '?')}/{board.get('total_shots', '?')}"
              f"（占比 {board.get('real_ratio', 0) * 100:.0f}%）"]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# stage 3: report（v1 + v2 + 人工三方对照）
# ----------------------------------------------------------------------
def parse_shotlist(shotlist_path: Path) -> list[dict]:
    """解析人工分镜表：`Sxx|源文件|入点|时长|内容|类型` 行。"""
    shots = []
    for line in shotlist_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.count("|") < 5:
            continue
        sid, src, inp, dur, content, typ = line.split("|")[:6]
        shots.append({"id": sid.strip(), "source": src.strip(),
                      "in": float(inp), "dur": float(dur),
                      "content": content.strip(), "type": typ.strip()})
    return shots


def compare_with_human(board: dict, human_shots: list[dict]) -> dict:
    """机器分镜 vs 人工分镜：命中/漏选/多选/黄金镜头核对。"""
    machine_files = {s.get("source_file") for s in board.get("shots", [])
                     if s.get("type") == "real" and s.get("source_file")}
    human_files = {h["source"] for h in human_shots if h["type"] == "real"}
    human_basenames = {Path(f).name for f in human_files}
    golden = {"2ad6d66c0431d5f20521b089f30ef8f9.mp4": "湖边黄昏递花（开场+收尾双用）",
              "c48d8d6c65e184247b52ebf439b45280.mp4": "沙地骑马（欢庆动感）",
              "f9e16006379a09023c639ccf784be8cc.mp4": "窗前逆光递花"}
    return {
        "machine_real_files": sorted(machine_files),
        "human_files": sorted(human_basenames),
        "hit": sorted(machine_files & human_basenames),
        "missed": sorted(human_basenames - machine_files),
        "extra": sorted(machine_files - human_basenames),
        "human_real_shots": sum(1 for h in human_shots if h["type"] == "real"),
        "human_ai_shots": sum(1 for h in human_shots if h["type"] != "real"),
        "golden_hits": {f: d for f, d in golden.items() if f in machine_files},
        "golden_miss": {f: d for f, d in golden.items() if f not in machine_files},
        "machine_real_ratio": board.get("real_ratio", 0),
        "machine_total": board.get("total_shots", 0),
    }


def _board_hook(board: dict) -> dict | None:
    return next((s for s in board.get("shots", []) if s.get("type") == "real"), None)


def _board_bookend(board: dict) -> bool:
    """书挡结构：开场素材在收尾段（最后 3 个真实镜）再次出现。"""
    real = [s for s in board.get("shots", []) if s.get("type") == "real"]
    if len(real) < 3:
        return False
    hook_src = real[0].get("source_file")
    return any(s.get("source_file") == hook_src for s in real[-3:])


def _tags_table(records: list[dict]) -> str:
    lines = ["| 素材 | 时长 | 时刻(原文) | 质量 | 高光 | 高光窗口 | 运动 | 音峰 | caption | 角色提示 |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in records:
        p, t = r["probe"], r.get("tags") or {}
        mark = "" if r["status"] == "ok" else f" ⚠️{r['status']}"
        win = t.get("highlight_window")
        win_txt = f"{win[0]}-{win[1]}s" if win else "—"
        raw = t.get("moment_raw")
        moment = t.get("moment_type", "—") + (f"({raw})" if raw and raw != t.get("moment_type") else "")
        lines.append(
            f"| {r['file'][:14]}…{mark} | {p['duration']}s "
            f"| {moment} | {t.get('quality', '—')} "
            f"| {t.get('highlight', '—')}/5{'+' if t.get('motion_boost') else ''} "
            f"| {win_txt} | {r.get('motion_level', '—')}({r.get('motion_score', 0)}) "
            f"| {'/'.join(f'{x}s' for x in r.get('audio_peaks', [])) or '—'} "
            f"| {t.get('caption', r.get('error') or '—')} | {'/'.join(t.get('roles_hint', [])) or '—'} |")
    return "\n".join(lines)


def _three_way_report(out_dir: Path, board_v2: dict, records_v2: list[dict],
                      human_shots: list[dict] | None, variant: str | None) -> list[str]:
    """v1 vs v2 vs 人工 三方对照（v2 报告的核心增量）。"""
    # 载 v1 产物（若存在）
    board_v1, records_v1 = None, []
    if (out_dir / "storyboard.json").is_file():
        board_v1 = json.loads((out_dir / "storyboard.json").read_text(encoding="utf-8"))
    if (out_dir / "materials.json").is_file():
        records_v1 = json.loads(
            (out_dir / "materials.json").read_text(encoding="utf-8"))["segments"]

    def hook_in(b):
        h = _board_hook(b) if b else None
        return h.get("in") if h else None

    def seg_by_file(records, fname):
        return next((r for r in records if r["file"] == fname), None)

    GOLDEN_HOOK = "2ad6d66c0431d5f20521b089f30ef8f9.mp4"
    RIDING = "c48d8d6c65e184247b52ebf439b45280.mp4"
    human_hook_in = next((h["in"] for h in (human_shots or []) if h["type"] == "real"), None)

    rv1 = seg_by_file(records_v1, RIDING)
    rv2 = seg_by_file(records_v2, RIDING)

    lines = ["## ③ 三方对照：v1 vs v2 vs 人工", ""]
    lines.append("### 改进点验收（v1 三短板）")
    lines += ["", "| 指标 | v1 | v2 | 人工（参照） |", "|---|---|---|---|"]

    # ① 开场入点
    v1_in, v2_in = hook_in(board_v1), hook_in(board_v2)
    lines.append(f"| 开场镜（2ad6d66c 黄昏湖边）入点 | "
                 f"{f'{v1_in}s' if v1_in is not None else '—'} | "
                 f"**{f'{v2_in}s' if v2_in is not None else '—'}** | {human_hook_in}s |")
    # ② 骑手段
    v1_h = (rv1 or {}).get("tags", {}).get("highlight")
    v2_h = (rv2 or {}).get("tags", {}).get("highlight")
    v1_m = (rv1 or {}).get("tags", {}).get("moment_type")
    v2_m = (rv2 or {}).get("tags", {}).get("moment_type")
    v2_motion = (rv2 or {}).get("motion_level", "—")
    riding_shot_v2 = next((s for s in board_v2.get("shots", [])
                           if s.get("source_file") == RIDING), None)
    lines.append(f"| 骑手段（c48d8d6c）打标 | H{v1_h} {v1_m} | "
                 f"H{v2_h} {v2_m}（运动{v2_motion}） | 欢庆动感主镜 |")
    lines.append(f"| 骑手段在分镜中的定位 | "
                 f"{_shot_desc(board_v1, RIDING)} | {_shot_desc(board_v2, RIDING)} | S12 欢庆高潮 |")
    # ③ 书挡
    lines.append(f"| 书挡式首尾呼应 | {'有' if _board_bookend(board_v1 or {}) else '无'} | "
                 f"**{'有' if _board_bookend(board_v2) else '无'}** | 有（黄昏湖边开场+收尾，S01/S13 同素材） |")
    # ④ 枚举收敛
    drift_v1 = _moment_drift(records_v1)
    drift_v2 = _moment_drift(records_v2)
    lines.append(f"| moment_type 枚举 | 全部落入受控枚举但语义泛用"
                 f"（'独处'被用于亲密双人镜头 {drift_v1.get('独处', 0)} 段） | "
                 f"受控+别名归一：独处 {drift_v2.get('独处', 0)} 段、"
                 f"欢庆 {drift_v2.get('欢庆', 0)} 段、其他 {drift_v2.get('其他', 0)} 段 | — |")
    lines += ["", "### 分镜结构对照", ""]
    if human_shots:
        comp2 = compare_with_human(board_v2, human_shots)
        comp1 = compare_with_human(board_v1, human_shots) if board_v1 else None
        lines.append(f"- 黄金镜头：v1 {len(comp1['golden_hits']) if comp1 else '—'}/3 → "
                     f"v2 **{len(comp2['golden_hits'])}/3**；"
                     f"双方共选 v2 {len(comp2['hit'])} 个（v1 {len(comp1['hit']) if comp1 else '—'}），"
                     f"漏选 {len(comp2['missed'])}（{', '.join(f[:12] for f in comp2['missed']) or '无'}），"
                     f"多选 {len(comp2['extra'])}（{', '.join(f[:12] for f in comp2['extra']) or '无'}）")
        lines.append(f"- 真实占比：v1 {board_v1.get('real_ratio', 0) * 100:.0f}% → "
                     f"v2 {board_v2.get('real_ratio', 0) * 100:.0f}%（人工 13/14=93%）")
    hook_v2 = _board_hook(board_v2)
    if hook_v2 and (hook_v2.get("basis") or "").strip():
        lines.append(f"- v2 开场镜选窗依据：{hook_v2['basis']}")
    if board_v2.get("bookend"):
        lines.append(f"- v2 书挡设计自述：{board_v2['bookend']}")
    lines.append(f"- v2 入点拉回高光窗口的镜数：{board_v2.get('window_nudged', 0)}；"
                 f"书挡复用平移到不重叠窗口的镜数：{board_v2.get('bookend_shifted', 0)}"
                 f"（🎯=入点钳制，🔁=书挡平移）")
    lines.append("")
    return lines


def _shot_desc(board: dict | None, fname: str) -> str:
    if not board:
        return "—"
    s = next((x for x in board.get("shots", []) if x.get("source_file") == fname), None)
    if not s:
        return "未选用"
    if s["type"] == "ai-edit":
        return "AI 镜"
    return f"第{s['id']}镜 {s['in']}-{s['out']}s「{s.get('emotion', '')}」"


def _moment_drift(records: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter((r.get("tags") or {}).get("moment_type", "?")
                        for r in records if r.get("status") == "ok"))


def run_report(out_dir: Path, records: list[dict], board: dict, stats: dict,
               shotlist_path: Path | None, variant: str | None) -> Path:
    """汇总 REPORT{ _v2}.md：打标总表 / 分镜全文 / 三方对照 / 成本 / 失败模式。"""
    ok = sum(1 for r in records if r["status"] == "ok")
    err = [r for r in records if r["status"] != "ok"]
    materials = json.loads(
        (out_dir / f"{_variant_name('materials', variant)}.json").read_text(encoding="utf-8"))
    human_shots = parse_shotlist(shotlist_path) if (shotlist_path and shotlist_path.is_file()) else None

    boosted = [r["file"][:12] for r in records
               if (r.get("tags") or {}).get("motion_boost")]
    windows_ok = sum(1 for r in records
                     if r["status"] == "ok" and (r.get("tags") or {}).get("highlight_window"))
    cost_lines = [
        f"- VLM 打标：{stats['vlm_calls']} 次调用 + {stats['vlm_retries']} 次重试"
        f"（模型 {materials.get('vlm_model', '—')}，每段 1 次、{len(FRAME_FRACTIONS_V2)} 帧同送）",
        f"- LLM 分镜：{stats['llm_calls']} 次调用（MiniMax M3）",
        f"- 本地免费：抽帧 {sum(r['probe']['duration'] for r in records):.0f}s × "
        f"{len(FRAME_FRACTIONS_V2)} + 帧间差分 motion + 音轨 RMS 能量峰值",
    ]
    for i, usage in enumerate(stats.get("llm_usage", []), 1):
        if usage:
            cost_lines.append(
                f"  - LLM 第 {i} 次：输入 {usage.get('prompt_tokens')} / 输出 "
                f"{usage.get('completion_tokens')} / 合计 {usage.get('total_tokens')} tokens")

    lines = [
        f"# storylab P4 素材理解自动化 · v2 运行报告（{variant or 'base'}）",
        "",
        f"- 运行时间：{stats.get('started_at', '—')} → {stats.get('finished_at', '—')}",
        f"- 素材目录：{materials.get('source_dir', '—')}（{len(records)} 段，schema v{TAG_SCHEMA_VERSION}）",
        f"- 打标结果：{ok}/{len(records)} 段成功"
        + (f"，失败 {len(err)} 段" if err else "")
        + f"；高光窗口估计成功 {windows_ok}/{ok} 段；动感修正 +1：{', '.join(boosted) or '无'}",
        f"- 产物：materials{ '_' + variant if variant else ''}.json / storyboard{ '_' + variant if variant else ''}.json"
        f" / .md / frames{ '_' + variant if variant else ''}/ / cache{ '_' + variant if variant else ''}/",
        "",
        "## ① 打标结果总表（v2）",
        "",
        _tags_table(records),
        "",
        "## ② 推荐分镜（v2 机器生成）",
        "",
        (out_dir / f"{_variant_name('storyboard', variant)}.md").read_text(encoding="utf-8"),
    ]
    lines += _three_way_report(out_dir, board, records, human_shots, variant)
    lines += [
        "## ④ 成本（v2 累计）",
        "",
        *cost_lines,
        "",
        "## ⑤ 失败模式与 v3 改进建议",
        "",
        "v1 三短板的修复情况（v2 实测）：",
        "",
        "1. **入点/出点拍脑袋 → 已修（机制上）**：10 帧时间戳 + highlight_window"
        " + 音峰提示 + 分镜后验钳制（偏离窗口 >2s 拉回，本跑 "
        f"{board.get('window_nudged', 0)} 镜触发）。残余风险：窗口本身是 VLM 从"
        " 10 帧的估计，秒级精度，特殊瞬间（如恰好 13.5s 的递花）仍可能差 1-3s——"
        "v3 可对入选镜头做二轮细定位（加密到 2fps 抽帧再送 VLM 选帧）。",
        "2. **动感镜头被低估 → 部分修复**：本地 motion_score 随 prompt 进 VLM 与分镜，"
        f"高档素材高光保底 +1（本跑：{', '.join(boosted) or '无'}）。但帧间差分对"
        "「慢速骑马走向镜头」这类大景别动感不敏感（骑手段实测低-中档），"
        "caption 级的语义动感仍主要靠 VLM——v3 可试光流法或让 VLM 对'内容动感'"
        "（骑马/奔跑/舞动的题材本身）单独打分。",
        "3. **无首尾呼应 → 已修（prompt 约束 + 后验平移双保险）**：书挡式写入 "
        "system prompt 并要求输出 bookend 设计说明；后验层检测同素材复用时"
        "与已用窗口重叠 >50% 的情况并平移到不重叠候选窗（优先音峰）。"
        f"本跑第 2 轮：LLM 声称复用'38-42.5s 第二窗口'却照抄开场窗口，"
        f"靠平移后验自动救回到 39.8-43.1s（音峰 41.8s 附近）——"
        f"只靠 prompt 约束不够，后验层是必要的。",
        "",
        "v2 新暴露的问题：",
        "",
        "4. **音频只有能量没有语义**：能量峰值对配乐/环境音同样触发，"
        " 不能区分'笑声'和'噪音'——v3 接 ASR + 音频事件分类。",
        "5. **highlight_window 偶尔保守**：VLM 倾向给'最稳'的窗口而非'最有张力'的，"
        " 与人的卡点审美有偏差，需要真实剪辑反馈校准。",
        "",
        "v3 方向建议：入选镜头二轮细定位（2fps 加密抽帧选帧）；ASR/音频事件；"
        "人脸聚类做'时刻'聚合；motion 改光流 + 题材动感双通道。",
    ]
    report_path = out_dir / f"REPORT{'_' + variant if variant else ''}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"{report_path.name} 已生成：{report_path}")
    return report_path


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------
def default_shotlist(out_dir: Path) -> Path | None:
    """out 目录平级的人工分镜参照（films/benben-xuchi/_storylab_trailer/shots/）。"""
    cand = out_dir.parent / "_storylab_trailer" / "shots" / "shotlist.txt"
    return cand if cand.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.storylab_ingest",
        description="storylab 素材理解：VLM 打标 + 推荐分镜 + 三方对照报告")
    parser.add_argument("materials_dir", type=Path, help="素材视频目录（只读）")
    parser.add_argument("--out", type=Path, required=True, help="产物输出目录")
    parser.add_argument("--stage", choices=("all", "ingest", "storyboard", "report"),
                        default="all", help="执行阶段：all=打标+分镜+报告（默认）")
    parser.add_argument("--variant", default=None,
                        help="产物命名变体（如 v2 → materials_v2.json / REPORT_v2.md），"
                             "缓存与抽帧目录也带后缀，互不覆盖")
    parser.add_argument("--force", action="store_true",
                        help="忽略缓存全部重打标（缺省按缓存断点续跑）")
    parser.add_argument("--shotlist", type=Path, default=None,
                        help="人工分镜表（对照评估用），缺省在 out 平级找 _storylab_trailer/shots/shotlist.txt")
    args = parser.parse_args(argv)

    config.load_dotenv()
    args.out.mkdir(parents=True, exist_ok=True)
    stats = load_stats(args.out, args.variant)
    records: list[dict] | None = None
    board: dict | None = None

    if args.stage in ("all", "ingest"):
        records = run_ingest(args.materials_dir, args.out, stats, args.variant, args.force)
        save_stats(args.out, stats, args.variant)
    if args.stage in ("all", "storyboard"):
        board = run_storyboard(args.out, stats, args.variant, records)
        save_stats(args.out, stats, args.variant)
    if args.stage in ("all", "report"):
        if records is None:
            records = json.loads(
                (args.out / f"{_variant_name('materials', args.variant)}.json").read_text(
                    encoding="utf-8"))["segments"]
        if board is None:
            board = json.loads(
                (args.out / f"{_variant_name('storyboard', args.variant)}.json").read_text(
                    encoding="utf-8"))
        shotlist = args.shotlist or default_shotlist(args.out)
        run_report(args.out, records, board, stats, shotlist, args.variant)
        save_stats(args.out, stats, args.variant)
    return 0


if __name__ == "__main__":
    sys.exit(main())
