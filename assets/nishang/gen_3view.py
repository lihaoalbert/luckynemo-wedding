"""霓裳阁补充：为每件已入库服装生成 16:9 三视图（正面/侧面/背面同框）。

单视图样板图保留作展示；三视图 *_3view.png 作为生产参考（定妆照/婚纱照/短片换装引用）。
读取 index.json 与 gen_batch1.py 的服装描述，逐件生成。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402
from gen_batch1 import SETS, OUT  # noqa: E402

SUFFIX = ("，以参考图中的服装为准，一张图内并排展示这同一款服装的正面、侧面、背面三个视角，"
          "无头人台模特全身，三视角服装款式、颜色、纹样细节与参考图完全一致，浅灰纯色背景，"
          "柔和摄影棚灯光，服装产品摄影，无文字无水印，16:9横向构图")


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)

    for idx, (set_id, cat, dress, suit) in enumerate(SETS, 1):
        for kind, c, desc in (("dress", cat, dress), ("suit", "礼服", suit)):
            fid = f"{'nz' if kind == 'dress' else 'lf'}-{idx:03d}"
            dest = OUT / c / f"{fid}_3view.png"
            src = OUT / c / f"{fid}.png"
            if dest.exists():
                print(f"{fid}_3view 已存在，跳过")
                continue
            if not src.exists():
                print(f"{fid} 缺单视图原图，跳过")
                continue
            prompt = desc + SUFFIX
            print(f"{fid}_3view（{set_id} {kind}，垫图）生成中...", flush=True)
            try:
                urls = client.generate_image(prompt=prompt, size="2K",
                                             reference_images=[str(src.resolve())],
                                             model=model, watermark=False)
                for url in urls:
                    client.download(url, dest)
                print(f"{fid}_3view 完成")
            except Exception as e:
                print(f"{fid}_3view 失败：{str(e)[:150]}")
            time.sleep(1)
    print("三视图批处理结束")


if __name__ == "__main__":
    main()
