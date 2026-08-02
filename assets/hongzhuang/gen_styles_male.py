"""红妆阁男士线：6 款男士妆造图批量生成（锚点 model_male_anchor.png「小朗」）。

男士妆造原则：克制为上——均匀肤色、眉毛塑形、轻修容、唇部润色，
绝不出现眼影/腮红/口红等女性化妆感（韩系欧巴款也保持清爽）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent
ANCHOR = OUT / "model_male_anchor.png"
STYLES_DIR = OUT / "styles"

# (编号, 名称, 妆容描述)
STYLES = [
    ("hz101", "男士清透裸妆",
     "男士伪素颜妆：哑光轻薄底妆均匀肤色遮住倦容但保留皮肤质感，"
     "眉毛梳理整齐填补空缺，唇部润唇膏自然润色，完全看不出妆感"),
    ("hz102", "男士立体骨相妆",
     "男士立体修容妆：雾面底妆，眉峰清晰眉形利落，"
     "鼻侧影和下颌线轻扫修容突出骨相轮廓，唇部自然，上镜脸型更立体"),
    ("hz103", "新郎经典妆",
     "男士新郎妆：干净匀净的底妆提亮气色，剑眉修整有型，"
     "轻微遮盖胡青，唇部自然红润，整体精神挺拔，婚礼当天上镜不出错"),
    ("hz104", "韩系欧巴妆",
     "男士韩系妆：奶油肌底妆带一点自然光泽，平直一字眉，"
     "眼下微微提亮，唇色淡淡的珊瑚粉润色，清爽温柔不油腻，绝不娘"),
    ("hz105", "中式礼服妆",
     "男士中式妆：端正匀净底妆，眉形刚毅浓整，"
     "轮廓干净利落，唇部自然，配长袍马褂中山装的端正大气感"),
    ("hz106", "复古港风妆",
     "男士港风妆：哑光底妆，浓眉有棱角，"
     "眼窝轻微加深，哑光自然唇，90年代港星的硬朗质感"),
]

PROMPT_TMPL = (
    "严格保持参考图中男性人物的五官、脸型、发型、肤色基底、构图和背景完全不变，"
    "只为他化上指定男士妆容：{makeup}。"
    "正面肩部以上肖像特写，浅灰纯色背景，柔和摄影棚灯光，"
    "专业妆后照（after photo）质感，妆容细节清晰真实，"
    "不要改变脸型和五官结构，不要加饰品，不要眼镜，无文字无水印，3:4竖版"
)

NEGATIVE = "改变脸型，改变五官，磨皮过度，眼影，腮红，口红，女性化妆容，妆面脏，油光满面"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    STYLES_DIR.mkdir(exist_ok=True)

    for code, name, makeup in STYLES:
        dest = STYLES_DIR / f"{code}.png"
        if dest.exists():
            print(f"{code} {name} 已存在，跳过")
            continue
        prompt = PROMPT_TMPL.format(makeup=makeup)
        print(f"{code} {name} 生成中...", flush=True)
        try:
            urls = client.generate_image(
                prompt=prompt, size="2K", reference_images=[str(ANCHOR)],
                model=model, watermark=False, negative_prompt=NEGATIVE)
            client.download(urls[0], dest)
            print(f"  -> {dest.name} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001 - 单款失败不中断整批
            print(f"  !! {code} 失败：{exc}", flush=True)
        time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
