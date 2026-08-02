"""红妆阁：生成标准模特「小霓」素颜锚点图（model_anchor.png）。

纯文生图（虚拟人物，无肖像权问题）。后续 12 款妆造图都以它为参考图，
保证用户选妆时唯一变量是妆容本身。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent

PROMPT = (
    "中国年轻女性，25岁，完全素颜无妆容，正面肩部以上肖像特写，"
    "黑色长直发自然中分垂落肩后，露出完整额头和耳朵，"
    "清秀自然的五官，皮肤真实有质感带轻微毛孔和肤色不均，不磨皮，"
    "表情放松自然嘴角微扬，直视镜头，"
    "浅灰色纯色背景，柔和均匀的摄影棚灯光，专业妆前照（before photo）风格，"
    "无任何饰品、无眼镜、无文字无水印，3:4竖版"
)


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    dest = OUT / "model_anchor.png"
    urls = client.generate_image(prompt=PROMPT, size="2K", reference_images=None,
                                 model=model, watermark=False)
    client.download(urls[0], dest)
    print(f"锚点图已生成：{dest}")


if __name__ == "__main__":
    main()
