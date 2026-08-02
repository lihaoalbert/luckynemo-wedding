"""红妆阁：通用定妆照生成器 —— 任意款式 × 任意客户照片。

用法（从 tools/luckynemo-toolkit/ 目录下运行）：
    python ../../assets/hongzhuang/gen_dingzhuang.py hz002 \
        --ref /path/客户照片.jpg --out /path/输出目录 --count 2

生成的定妆照需人工对照客户照片验收「像本人」后方可作为脸部锚点。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_prompt import build  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="通用定妆照生成器")
    ap.add_argument("style_id", help="红妆阁款式编号，如 hz002")
    ap.add_argument("--ref", required=True, help="客户照片路径（清晰正脸最佳）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--count", type=int, default=2, help="生成张数（默认 2）")
    ap.add_argument("--keep-glasses", action="store_true", help="保留眼镜（默认摘镜）")
    args = ap.parse_args()

    prompt, negative = build(args.style_id, args.keep_glasses)
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(1, args.count + 1):
        dest = out_dir / f"定妆照_{args.style_id}_{i}.png"
        print(f"{args.style_id} 第 {i}/{args.count} 张生成中...", flush=True)
        urls = client.generate_image(
            prompt=prompt, size="2K", reference_images=[str(Path(args.ref).resolve())],
            model=model, watermark=False, negative_prompt=negative)
        client.download(urls[0], dest)
        print(f"  -> {dest}", flush=True)
    print("完成。请人工对照客户照片验收：像本人是硬门槛。")


if __name__ == "__main__":
    main()
