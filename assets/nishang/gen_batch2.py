"""霓裳阁第二批：配饰 + 鞋履样板图（特写产品图，浅灰背景）。

小物件不做三视图（README 规则：鞋履/配饰可特写）。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent

ACCESSORIES = [
    ("ps-001", "珍珠耳钉一对配短款新娘头纱"),
    ("ps-002", "长款教堂式新娘头纱，及地薄纱"),
    ("ps-003", "鲜花花环头饰，白玫瑰与满天星"),
    ("ps-004", "贝壳与海星发饰一套，海边婚礼"),
    ("ps-005", "1950年代鸟笼网纱头饰配小礼帽"),
    ("ps-006", "极简银色金属耳饰一对"),
    ("ps-007", "草编宽檐帽，法式田园"),
    ("ps-008", "星芒水钻发冠"),
    ("ps-009", "中式凤冠，鎏金珠钗步摇，红金配色"),
    ("ps-010", "鎏金珠钗发簪一对，中式"),
    ("ps-011", "白玉发簪，民国风"),
    ("ps-012", "竹节造型发簪，新中式"),
    ("ps-013", "米白色毛线帽"),
    ("ps-014", "学院风蝴蝶结发带"),
    ("ps-015", "短款头纱配珍珠发梳"),
    ("ps-016", "水晶公主皇冠"),
    ("ps-017", "唐风花钿面饰与鎏金步摇"),
    ("ps-018", "宋代珍珠妆面头饰套装"),
    ("ps-019", "复古大波浪假发片，港风"),
    ("ps-020", "羊绒保暖披肩，米白色"),
]

SHOES = [
    ("xl-001", "象牙白缎面婚鞋，中跟"),
    ("xl-002", "水晶透明高跟鞋，童话风"),
    ("xl-003", "裸色平底芭蕾鞋"),
    ("xl-004", "裸色平底凉鞋"),
    ("xl-005", "复古玛丽珍鞋，象牙白"),
    ("xl-006", "裸色细高跟鞋"),
    ("xl-007", "编织坡跟凉鞋，度假风"),
    ("xl-008", "银色亮片高跟鞋"),
    ("xl-009", "正红色中式绣花鞋"),
    ("xl-010", "黑色缎面低跟婚鞋"),
    ("xl-011", "复古低跟搭扣鞋，民国风"),
    ("xl-012", "素色布鞋，新中式"),
    ("xl-013", "棕色短靴"),
    ("xl-014", "学院风乐福鞋"),
    ("xl-015", "唐风云头履"),
    ("xl-016", "宋代弓鞋"),
    ("xl-017", "复古漆皮高跟鞋，港风"),
    ("xl-018", "棕色户外皮靴"),
]

SUFFIX = "，产品特写摄影，浅灰纯色背景，柔和摄影棚灯光，细节清晰，无文字无水印，1:1方形构图"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    for cat, items in (("配饰", ACCESSORIES), ("鞋履", SHOES)):
        (OUT / cat).mkdir(exist_ok=True)
        for fid, desc in items:
            dest = OUT / cat / f"{fid}.png"
            if dest.exists():
                print(f"{fid} 已存在，跳过")
                continue
            print(f"{fid}（{desc[:15]}...）生成中...", flush=True)
            try:
                urls = client.generate_image(prompt=desc + SUFFIX, size="2K",
                                             reference_images=None, model=model, watermark=False)
                for url in urls:
                    client.download(url, dest)
                print(f"{fid} 完成")
            except Exception as e:
                print(f"{fid} 失败：{str(e)[:150]}")
            time.sleep(1)
    print("第二批结束")


if __name__ == "__main__":
    main()
