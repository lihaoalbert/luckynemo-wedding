"""系列模卡换脸（v3 分组首批 8 系列）：用虚拟模特替换精选客片中的人物，神态/光影严格保持原照片。
情侣 → 陆辰野×黎泠娜。输出到 assets/moka/series_draft/<系列id>/（审片通过后入正式库）。

源片：/Users/lihao/Desktop/moka_series_src/<sid>/<tid>.jpg（真实客片，勿入 git）
用法：python gen_series.py            # 全部（已存在自动跳过）
      python gen_series.py hyd sak    # 只生成指定系列
      python gen_series.py --strong   # 加强重跑（换脸未生效的）
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "series_draft"
REF = ROOT / "referrence"
SRC = Path("/Users/lihao/Desktop/moka_series_src")

#: 系列定义：id -> (中文名, 一级分组)
SERIES = {
    "hyd": ("蓝绣球花墙", "flower"),
    "sak": ("樱花隧道", "flower"),
    "muh": ("粉黛乱子草", "flower"),
    "lig": ("悬崖灯塔", "sea"),
    "han": ("韩服古祠", "city"),
    "hor": ("以梦为马", "creative"),
    "min": ("白色极简", "ceremony"),
    "spk": ("暮色仙女棒", "sea"),
}

PROMPT = (
    "最后一张参考图是完整的摄影作品模板，前面的参考图是要替换上去的人物。"
    "把模板中的人物替换为参考图的人物（按性别一一对应替换），"
    "严格保持模板的构图、场景、服装、妆容、道具、姿势、神态、表情、光影、色调、背景完全不变，"
    "只替换人物的五官与面部特征，真实人体比例约7.5头身，与场景自然融合有投影，"
    "摄影级质感，无文字无水印"
)

#: 重跑加强词：针对换脸未生效（侧脸/遮挡/小脸/墨镜）的范本
STRONG = ("；特别强调：模板中每一个人物的脸都必须完整替换为参考图人物的五官，"
          "无论是正脸、侧脸、低头、远距离小脸，还是被墨镜/头发/手部分遮挡的脸，"
          "都不能保留原照片人物的任何面部特征；每个人的动作、手部位置也必须与原模板完全一致")

MODELS = ["陆辰野", "黎泠娜"]


def shrink(src: Path) -> Path:
    """范本总像素超过方舟上限（36M）时等比缩到 ~24M，返回可用路径（缓存到 _small/）。"""
    import subprocess
    info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)],
                          capture_output=True, text=True).stdout
    w = h = 0
    for line in info.splitlines():
        if "pixelWidth" in line:
            w = int(line.split()[-1])
        if "pixelHeight" in line:
            h = int(line.split()[-1])
    if not w or not h or w * h <= 30_000_000:
        return src
    small_dir = OUT / "_small"
    small_dir.mkdir(exist_ok=True)
    out = small_dir / src.name
    if not out.exists():
        scale = (24_000_000 / (w * h)) ** 0.5
        subprocess.run(["sips", "-Z", str(int(max(w, h) * scale)), str(src), "--out", str(out)],
                       check=True, capture_output=True)
    return out


def refs_for(names: list[str]) -> list[str]:
    files = []
    for n in names:
        d = REF / n
        pics = sorted([p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        if pics:
            files.append(str(pics[0].resolve()))
    return files


def main() -> None:
    only = {a for a in sys.argv[1:] if not a.startswith("--")}
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    refs = refs_for(MODELS)

    for sid in SERIES:
        if only and sid not in only:
            continue
        src_dir = SRC / sid
        out_dir = OUT / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        for src in sorted(src_dir.glob("*.jpg")):
            tid = src.stem
            dest = out_dir / f"{tid}.png"
            if dest.exists():
                print(f"{tid} 已存在，跳过")
                continue
            prompt = PROMPT + (STRONG if "--strong" in sys.argv else "")
            print(f"{tid}（{SERIES[sid][0]}）生成中...", flush=True)
            try:
                urls = client.generate_image(
                    prompt=prompt, size="2K", reference_images=refs + [str(shrink(src))],
                    model=model, watermark=False)
                client.download(urls[0], dest)
                print(f"  -> {sid}/{dest.name} 完成", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"  !! {tid} 失败：{exc}", flush=True)
            time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
