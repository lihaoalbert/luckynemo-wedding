"""红妆阁 V2 妆造库：参考《彩妆造型合集》103 款中最受欢迎的 12 款新娘妆造。

两位标准模特分工：
- 小霓（清秀柔和）：韩系/日杂/白开水/甜美/森系/轻泰
- 沈念卿（明艳大气）：法式/贵气千金/新中式/港风气质款
含发型与饰品（头纱/花环/珍珠/皇冠），替换原 hz001-hz013 女妆库。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NI = OUT / "model_anchor.png"                       # 小霓
SN = ROOT / "referrence" / "沈念卿" / "GPT Image 2_1782208332905_0 (1).png"  # 沈念卿

# (id, 模特, 系列, 名称, 妆造+发型+饰品 完整艺术指导)
LOOKS = [
    ("hz201", "ni", "韩系", "韩系水光婚妆",
     "韩系水光肌婚妆：透亮水光底妆带自然光泽，平直眉，粉橘珊瑚色眼妆突出饱满卧蚕，西柚色水润嘟嘟唇；"
     "发型为优雅低盘发，佩戴白色蕾丝头纱和珍珠耳钉，白色缎面婚纱肩部以上构图"),
    ("hz202", "ni", "日杂", "日杂少女婚妆",
     "日杂少女风婚妆：奶油肌，橘调元气眼妆带亮片卧蚕，太阳花卷翘睫毛，橘粉色玻璃唇；"
     "发型为蓬松空气感卷发半扎，佩戴小碎花发夹，白色露肩轻纱肩部以上构图，暖米色背景"),
    ("hz203", "ni", "白开水", "白开水新娘妆",
     "白开水极简新娘妆：冷调雾面底妆非常干净，灰棕细眉，几乎无眼影只加深睫毛根部，裸粉色哑光唇；"
     "发型为自然顺直披发，不佩戴任何饰品，白色简约吊带婚纱肩部以上构图"),
    ("hz204", "ni", "甜美减龄", "甜美减龄妆",
     "甜美减龄婚妆：蜜桃粉调底妆，粉色微醺腮红打在苹果肌，纤长卷翘睫毛，蜜桃色唇蜜；"
     "发型为浪漫大波浪卷发，佩戴满天星花环，粉色纱裙肩部以上构图"),
    ("hz205", "ni", "森系", "森系新娘妆",
     "森系清新新娘妆：清透奶油肌，淡粉棕眼影，淡玫瑰唇，眼下轻微珠光提亮；"
     "发型为侧边松散编发，发间点缀白色小雏菊和尤加利叶，白色蕾丝轻纱肩部以上构图，浅绿调背景"),
    ("hz206", "ni", "轻泰", "轻泰新娘妆",
     "轻泰式新娘妆：光泽感底妆，毛流感浓眉带眉峰，大地色眼影加深眼窝轮廓，番茄红水光唇；"
     "发型为高发髻盘发，佩戴珍珠花发饰和珍珠耳环，白色蕾丝婚纱肩部以上构图"),
    ("hz207", "sn", "法式", "法式复古新娘妆",
     "法式复古新娘妆：缎光底妆，野生毛流感浓眉，大地色眼影轻扫，复古玫瑰豆沙唇边缘晕染；"
     "发型为光洁低盘发，佩戴珍珠耳钉和短款头纱，白色蕾丝长袖婚纱肩部以上构图，暖黄复古光线"),
    ("hz208", "sn", "贵气千金", "贵气千金妆",
     "贵气千金婚妆：细腻缎光肌，干净利落的自然眉形，香槟金棕眼影微微提亮，玫瑰茶色唇妆；"
     "发型为高贵皇冠盘发，佩戴珍珠皇冠和珍珠耳坠，白色缎面泡泡袖婚纱肩部以上构图，暖金华丽光线"),
    ("hz209", "sn", "新中式", "新中式旗袍妆",
     "新中式旗袍妆：净透雾光底妆，柳叶细眉，杏红色眼影淡扫，樱桃红咬唇妆内深外浅；"
     "发型为侧分低发髻，佩戴珍珠流苏发簪，粉色刺绣旗袍肩部以上构图"),
    ("hz210", "sn", "新中式", "新中式秀禾妆",
     "新中式秀禾新娘妆：白皙净透底妆，细长柳叶眉，淡雅杏红眼影，正红色饱满唇妆但不显老气；"
     "发型为中分低髻盘发，佩戴金色凤冠和红色玛瑙耳坠，正红金丝秀禾服肩部以上构图"),
    ("hz211", "sn", "韩系", "韩系气质新娘妆",
     "韩系气质婚妆：水光奶油肌，平直浅棕眉，香槟色细闪眼影配精致卧蚕，玫瑰色镜面唇釉；"
     "发型为侧分黑长直，佩戴白色蝴蝶结发夹，白色缎面婚纱肩部以上构图"),
    ("hz212", "sn", "法式", "法式低盘珍珠妆",
     "法式优雅婚妆：柔雾底妆带一点脸颊光泽，柔和细眉，奶咖色眼影三段晕染，杏桃奶茶唇；"
     "发型为法式慵懒低盘发带几缕碎发，佩戴复古珍珠耳环，白色V领缎面婚纱肩部以上构图"),
]

PROMPT_TMPL = (
    "保持参考图中人物的五官、脸型完全不变，为她完成以下新娘妆造：{look}。"
    "正面或微侧面肩部以上肖像，专业新娘妆面照质感，妆容发型饰品细节清晰精致，"
    "摄影棚柔和灯光，无文字无水印，3:4竖版"
)

NEGATIVE = "改变脸型，改变五官，磨皮过度，妆面脏，油光满面，老气，假面感，多人，手部畸形"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    out_dir = OUT / "styles_v2"
    out_dir.mkdir(exist_ok=True)
    anchors = {"ni": str(NI), "sn": str(SN)}

    for lid, who, series, name, look in LOOKS:
        dest = out_dir / f"{lid}.png"
        if dest.exists():
            print(f"{lid} 已存在，跳过")
            continue
        prompt = PROMPT_TMPL.format(look=look)
        print(f"{lid} {name}（{series}，{who}）生成中...", flush=True)
        try:
            urls = client.generate_image(
                prompt=prompt, size="2K", reference_images=[anchors[who]],
                model=model, watermark=False, negative_prompt=NEGATIVE)
            client.download(urls[0], dest)
            print(f"  -> {dest.name} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {lid} 失败：{exc}", flush=True)
        time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
