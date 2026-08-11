"""红妆阁：hz108（男士原图直出版）卡图重出 —— 全身照改统一半身正脸照。

起因（2026-08-11 用户反馈）：hz108 卡图是全身照，与 hz107/hz213/hz214 等
其他卡的半身正脸版式不统一。以现有 hz108 为人物参考重出胸部以上半身正脸肖像，
输出尺寸对齐其他卡（1776x2368）。

用法（从 tools/luckynemo-toolkit/ 目录下运行）：
    python ../../assets/hongzhuang/gen_hz108_halfbody.py --out /tmp/hz108_draft
确认合格后人工替换 styles/hz108.png 并同步 ECS。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

STYLES = Path(__file__).resolve().parent / "styles"

PROMPT = (
    "同一人物的胸部以上半身正面肖像照：正脸直视镜头，自然放松微笑，"
    "保持参考图人物的五官、脸型、发型完全一致，黑色T恤不变，"
    "浅灰纯色背景，柔和均匀棚拍光线，专业肖像照质感，竖版构图，无文字无水印"
)


def main() -> None:
    ap = argparse.ArgumentParser(description="hz108 卡图重出（半身正脸版）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--count", type=int, default=2, help="生成张数（默认 2，便于挑选）")
    args = ap.parse_args()

    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    ref = STYLES / "hz108.png"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, args.count + 1):
        dest = out_dir / f"hz108_halfbody_{i}.png"
        print(f"第 {i}/{args.count} 张生成中...", flush=True)
        urls = client.generate_image(
            prompt=PROMPT, size="1776x2368", reference_images=[str(ref)],
            model=model, watermark=False)
        client.download(urls[0], dest)
        print(f"  -> {dest}", flush=True)
    print("完成。挑选合格后替换 styles/hz108.png。")


if __name__ == "__main__":
    main()
