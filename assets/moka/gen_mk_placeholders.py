"""mk 老系列「同款大片」占位变体图生成（MiniMax image-01）。

为 12 个 mk 系列（每系列现有 3 变体）各补 6 个占位变体，凑成九宫格。
新 ID：系列 NN（01-12）的第 4-9 变体 = mk3NN..mk8NN。
产物存 assets/moka/mk_draft/mkXNN.png，manifest.json 记录每张的提示词与状态。

这些是占位稿，上线前会用 Seedream 重出替换——主题/场景/服装与系列一致、
画质可接受即可，不追求与现有 3 张画风完全统一。

用法：
    python3 gen_mk_placeholders.py                 # 全量（断点续跑，跳过已存在文件）
    python3 gen_mk_placeholders.py --series church # 只跑一个系列（便于重试）
    python3 gen_mk_placeholders.py --dry-run       # 只打印提示词不调用

凭据：MINIMAX_API_KEY / MINIMAX_BASE_URL，从环境变量或 .env 读取
（候选：本仓库 tools/luckynemo-toolkit/.env → 兄弟检出 /Users/app/LuckyNemo-Wedding/...）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent          # assets/moka
REPO = HERE.parents[1]                          # 仓库根
OUT_DIR = HERE / "mk_draft"
MANIFEST = OUT_DIR / "manifest.json"
INDEX = HERE / "index.json"

MODEL = "image-01"
ASPECT = "2:3"  # 现有模板 1664x2496 = 2:3 竖版
MAX_TRIES = 3   # 1 次 + 最多重试 2 次
WORKERS = 2     # 限速：小并发

ENV_CANDIDATES = [
    REPO / "tools/luckynemo-toolkit/.env",
    Path("/Users/app/LuckyNemo-Wedding/tools/luckynemo-toolkit/.env"),
]

# 每系列的场景细节（在 index.json components 基础上补充环境要素，保证与系列一致）
SCENE_DETAIL = {
    "church":      "哥特式教堂内，高耸拱顶、彩色玻璃窗洒下斑斓光斑、红毯与烛光",
    "jiangnan":    "江南古镇雨巷，青石板路、白墙黛瓦、细雨蒙蒙、一把油纸伞",
    "seaside":     "海边沙滩落日，金色逆光、海浪、海风拂动",
    "chinese":     "中式喜堂/婚房，红烛高照、囍字红绸、暖红光线",
    "flowerfield": "春日油菜花田，金色花海、柔和阳光",
    "citynight":   "城市夜景高处（天台/天桥），身后万家灯火与霓虹光斑、车流光轨",
    "forest":      "晨雾森林，丁达尔光束穿过树隙、薄雾、青苔",
    "hongkong_f":  "复古港风街头夜景，霓虹招牌、旧海报墙、潮湿路面反光",
    "street":      "都市老街午后，斑马线、老建筑、咖啡店门口，光影斑驳",
    "studio":      "灰调摄影棚，纯色背景、戏剧性侧光勾勒轮廓",
    "hongkong_m":  "港风大排档/霓虹小巷夜景，折叠桌、招牌灯光、潮湿反光",
    "outdoor":     "秋日山野草甸，金黄草甸、远山辽阔、斜阳金光",
}

# 每系列 6 个新变体的构图/瞬间（避开现有 3 张已用过的动作）
SHOTS = {
    "couple": [
        "全景：两人牵手漫步走向场景深处，裙摆轻扬，环境氛围完整呈现",
        "中景：面对面深情对视而笑，双手交握",
        "特写：交握的手与温柔的侧脸，浅景深背景虚化",
        "远景背影：两人依偎的背影望向场景主体，构图留白",
        "坐姿：两人并肩坐下，头轻轻靠在一起，自然甜蜜的互动",
        "动态瞬间：新郎抱起新娘旋转，裙摆飞扬，欢笑",
    ],
    "solo_f": [
        "全景：全身立于场景之中，裙摆随风，环境氛围完整呈现",
        "中景：侧身回眸微笑，发丝被风轻拂",
        "特写：肩部以上侧脸特写，浅景深，妆容与发丝细节",
        "远景背影：背影走向场景深处，构图留白",
        "坐姿：优雅地坐在场景中，姿态放松自然",
        "动态瞬间：轻提裙摆旋转，发丝与裙角飞扬",
    ],
    "solo_m": [
        "全景：全身站立，单手插兜，环境氛围完整呈现",
        "中景：行走中自然回头，松弛有型",
        "特写：肩部以上侧脸特写，眼神锐利，浅景深",
        "远景背影：背影望向场景主体，构图留白",
        "坐姿：放松地坐在场景中（椅子/台阶/岩石），姿态从容",
        "动态瞬间：一边行走一边整理袖口，抓拍感",
    ],
}

STYLE_SUFFIX = (
    "婚纱照/写真实拍风格，高级感人像摄影，真实摄影质感，电影感光影，"
    "构图精致，色调和谐，画面中无任何文字、无水印、无边框"
)


def load_env() -> None:
    """从候选 .env 文件加载 MINIMAX_* 到 os.environ（不覆盖已有环境变量）。"""
    for path in ENV_CANDIDATES:
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            return


def subject_phrase(mode: str, attire: str) -> str:
    if mode == "couple":
        parts = [p.strip() for p in attire.split("+", 1)]
        bride = parts[0]
        groom = parts[1] if len(parts) > 1 else "深色西装"
        return f"一对年轻亚洲新婚情侣，新娘穿{bride}，新郎穿{groom}"
    if mode == "solo_f":
        return f"一位年轻亚洲女性，穿{attire}"
    return f"一位年轻亚洲男性，穿{attire}"


def build_plan() -> list[dict]:
    """从 index.json 读出 12 个 mk 系列，生成 72 张的任务清单。"""
    index = json.loads(INDEX.read_text())
    series_info = {s["id"]: s for s in index["series"] if s["id"] in SCENE_DETAIL}
    # 每系列的服装取 mk0NN（第一个变体）的 components
    attire = {}
    for t in index["templates"]:
        if t["id"].startswith("mk0") and t["series"] in series_info:
            attire[t["series"]] = t["components"].get("服装", "")
    plan = []
    for s in series_info.values():
        nn = s["variants"][0][-2:]  # mk001 -> 01
        mode = s["mode"]
        for i, shot in enumerate(SHOTS[mode]):
            vid = f"mk{i + 3}{nn}"  # mk3NN..mk8NN
            prompt = (
                f"{subject_phrase(mode, attire[s['id']])}，{shot}。"
                f"场景：{SCENE_DETAIL[s['id']]}。{STYLE_SUFFIX}"
            )
            plan.append({
                "id": vid, "series": s["id"], "mode": mode,
                "prompt": prompt, "file": f"mk_draft/{vid}.png",
            })
    return plan


def gen_one(client: requests.Session, base: str, item: dict, dry_run: bool) -> str:
    """生成单张，返回 ok/failed。最多 MAX_TRIES 次。"""
    dest = OUT_DIR / f"{item['id']}.png"
    if dest.exists() and dest.stat().st_size > 0:
        return "ok"  # 断点跳过
    if dry_run:
        print(f"[dry-run] {item['id']} {item['prompt']}")
        return "dry"
    payload = {
        "model": MODEL,
        "prompt": item["prompt"],
        "aspect_ratio": ASPECT,
        "response_format": "url",
        "n": 1,
        "prompt_optimizer": False,
        "aigc_watermark": False,
    }
    for attempt in range(1, MAX_TRIES + 1):
        try:
            resp = client.post(f"{base}/image_generation", json=payload, timeout=180)
            data = resp.json()
            base_resp = data.get("base_resp") or {}
            if resp.status_code >= 400 or base_resp.get("status_code") not in (None, 0):
                raise RuntimeError(f"HTTP {resp.status_code} base_resp={base_resp}")
            urls = (data.get("data") or {}).get("image_urls") or []
            if not urls:
                raise RuntimeError(f"无 image_urls：{json.dumps(data, ensure_ascii=False)[:300]}")
            with client.get(urls[0], timeout=120, stream=True) as dl:
                dl.raise_for_status()
                tmp = dest.with_suffix(".tmp")
                with open(tmp, "wb") as fh:
                    for chunk in dl.iter_content(1 << 20):
                        fh.write(chunk)
            tmp.rename(dest)
            return "ok"
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)[:200]
            wait = 25 * attempt if ("1002" in msg or "1004" in msg or "429" in msg) else 6 * attempt
            print(f"[{item['id']}] 第 {attempt}/{MAX_TRIES} 次失败：{msg}；{wait}s 后重试", flush=True)
            time.sleep(wait)
    return "failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", nargs="*", help="只跑指定系列（如 church jiangnan）")
    ap.add_argument("--retry-ids", nargs="*",
                    help="强制重跑指定变体 ID（删除旧图，并在提示词末尾追加强力禁文字条款）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    load_env()
    key = os.environ.get("MINIMAX_API_KEY", "").strip()
    base = os.environ.get("MINIMAX_BASE_URL", "").strip() or "https://api.minimaxi.com/v1"
    if not args.dry_run and not key:
        sys.exit("未找到 MINIMAX_API_KEY（环境变量或候选 .env 均无）")

    plan = build_plan()
    if args.series:
        plan = [p for p in plan if p["series"] in args.series]
    if args.retry_ids:
        plan = [p for p in plan if p["id"] in args.retry_ids]
        for p in plan:
            old = OUT_DIR / f"{p['id']}.png"
            old.unlink(missing_ok=True)  # 强制重生成
            p["prompt"] += (
                "。请务必保证画面干净：绝对不要出现任何文字、字母、数字、"
                "签名、水印、logo，背景中的招牌和海报一律虚化不可辨认"
            )
    if not plan:
        sys.exit("没有匹配的任务")

    OUT_DIR.mkdir(exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}

    client = requests.Session()
    client.headers["Authorization"] = f"Bearer {key}"

    t0 = time.time()
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(gen_one, client, base, item, args.dry_run): item for item in plan}
        for fut in as_completed(futs):
            item = futs[fut]
            status = fut.result()
            if not args.dry_run:
                manifest[item["id"]] = {
                    "series": item["series"],
                    "prompt": item["prompt"],
                    "file": item["file"],
                    "status": status,
                }
                MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
            done += 1
            elapsed = time.time() - t0
            print(f"[{done}/{len(plan)}] {item['id']} -> {status}（已用 {elapsed:.0f}s）", flush=True)
            time.sleep(1)

    ok = sum(1 for v in manifest.values() if v["status"] == "ok")
    failed = [k for k, v in manifest.items() if v["status"] == "failed"]
    print(f"完成：ok={ok} failed={len(failed)} {failed}；总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
