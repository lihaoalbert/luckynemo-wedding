"""M2 照相馆：30 个微剧情场景图生成（空场景无人物，16:9）。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent
SUFFIX = "，空场景无人物，电影感构图，光线氛围精准，16:9横向构图，无文字无水印"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    scenes = json.loads((OUT / "scenes.json").read_text())["scenes"]
    img_dir = OUT / "img"
    img_dir.mkdir(exist_ok=True)
    for sc in scenes:
        dest = img_dir / f"{sc['id']}.png"
        if dest.exists():
            print(f"{sc['id']} 已存在，跳过")
            continue
        print(f"{sc['id']} {sc['name']} 生成中...", flush=True)
        try:
            urls = client.generate_image(prompt=sc["prompt"] + SUFFIX, size="2K",
                                         reference_images=None, model=model, watermark=False)
            for url in urls:
                client.download(url, dest)
            print(f"{sc['id']} 完成")
        except Exception as e:
            print(f"{sc['id']} 失败：{str(e)[:150]}")
        time.sleep(1)
    print("场景库生成结束")


if __name__ == "__main__":
    main()
