"""红妆阁发型库：12 款发型图（MiniMax image-01 + 标准模特锚点）。

女 8 款（小霓锚点）+ 男 4 款（小朗锚点）。
subject_reference 锁模特脸，提示词只改发型。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import config  # noqa: E402
from luckynemo.minimax_client import MiniMaxClient, images_to_subject_reference  # noqa: E402

OUT = Path(__file__).resolve().parent
HAIR_DIR = OUT / "hairstyles"

# (编号, 性别, 名称, 发型描述, 适配场景)
STYLES = [
    ("fx001", "female", "低盘发", "优雅低盘发，颅顶微蓬松，几缕碎发垂在脸侧，经典新娘发型", "白纱/仪式"),
    ("fx002", "female", "公主半扎发", "上半部分头发扎起带微卷，下半部分自然垂落，甜美公主风", "甜美/花海"),
    ("fx003", "female", "大波浪长卷", "浪漫大波浪长卷发，光泽感强，女神气场", "夜景/时尚"),
    ("fx004", "female", "中式发髻", "中式古典发髻，光洁整齐，可插发簪步摇，配秀禾旗袍", "中式/秀禾"),
    ("fx005", "female", "法式低马尾", "慵懒法式低马尾，发尾微卷，额前碎发自然", "街拍/法式"),
    ("fx006", "female", "灵动丸子头", "蓬松丸子头，青春俏皮，额前胎毛碎发", "活泼/日常"),
    ("fx007", "female", "侧分直发", "侧分顺滑长直发，干净利落，气质挂", "极简/气质"),
    ("fx008", "female", "复古手推波", "1930年代复古手推波浪，贴头皮波纹，港风名媛", "复古/港风"),
    ("fx101", "male", "侧分油头", "经典侧分油头，整齐有光泽，新郎标配", "正装/仪式"),
    ("fx102", "male", "清爽短碎发", "清爽短碎发带纹理感，干净阳光", "日常/清新"),
    ("fx103", "male", "韩系逗号刘海", "韩系逗号刘海短发，温柔减龄", "韩系/清新"),
    ("fx104", "male", "复古背头", "复古大背头，成熟稳重，港风绅士", "复古/港风"),
]

PROMPT_TMPL = (
    "保持参考图中人物的五官、脸型、肤色、构图和背景完全不变，素颜状态，"
    "只把发型变成：{hair}。正面肩部以上肖像特写，浅灰纯色背景，"
    "柔和摄影棚灯光，发质真实有细节，无饰品无文字无水印"
)


def main() -> None:
    config.load_dotenv()
    client = MiniMaxClient(api_key=config.get_minimax_api_key(),
                           base_url=config.get_minimax_base_url())
    HAIR_DIR.mkdir(exist_ok=True)
    anchors = {
        "female": images_to_subject_reference([OUT / "model_anchor.png"]),
        "male": images_to_subject_reference([OUT / "model_male_anchor.png"]),
    }
    for code, gender, name, hair, fit in STYLES:
        dest = HAIR_DIR / f"{code}.png"
        if dest.exists():
            print(f"{code} {name} 已存在，跳过")
            continue
        prompt = PROMPT_TMPL.format(hair=hair)
        print(f"{code} {name}（{gender}）生成中...", flush=True)
        try:
            url = client.generate_image(prompt=prompt, aspect_ratio="3:4",
                                        subject_reference=anchors[gender])
            client.download(url or f"<dry-{code}>", dest)
            print(f"  -> {dest.name} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {code} 失败：{exc}", flush=True)
        time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
