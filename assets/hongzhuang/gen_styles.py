"""红妆阁：12 款标准妆造图批量生成。

以 model_anchor.png（标准模特「小霓」素颜照）为参考图，逐款生成。
唯一变量是妆容：构图/背景/发型/人物保持一致，方便用户纯粹比妆。

设计原则（来自小徐试点反馈：显老气 = 失败）：
- 减龄优先：奶油肌/水光肌、低饱和、毛流感眉毛、卧蚕、玻璃唇
- 避免：厚重正红唇（港风款除外）、强修容、粗黑眼线、过度磨皮
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent
ANCHOR = OUT / "model_anchor.png"
STYLES_DIR = OUT / "styles"

# (编号, 系列, 名称, 妆容描述)
STYLES = [
    ("hz001", "清新系", "氧气素颜妆",
     "伪素颜妆感：轻薄奶油肌底妆透出自然皮肤质感，野生眉带毛流感，"
     "妈生感根根分明睫毛，淡奶茶色玻璃唇，几乎看不出化妆但气色很好"),
    ("hz002", "清新系", "韩系水光妆",
     "韩系水光肌底妆带自然光泽感，平直眉，粉橘珊瑚色系眼妆突出可爱卧蚕，"
     "果汁感水润唇妆，整体通透减龄"),
    ("hz003", "清新系", "蜜桃少女妆",
     "蜜桃粉色调妆容：杏粉色微醺腮红打在苹果肌上，淡粉棕眼影，"
     "纤长卷翘睫毛，蜜桃色唇蜜，甜美少女感"),
    ("hz004", "清新系", "奶茶温柔妆",
     "奶茶杏色系妆容：柔雾底妆，浅棕雾面眉，奶咖色眼影自然晕染，"
     "杏桃色唇釉，温柔气质，妆感清淡"),
    ("hz005", "气质系", "清冷白开水妆",
     "冷调白开水妆容：冷白皮雾面底妆非常干净，灰棕色细眉，"
     "几乎无眼影只加深睫毛根部，裸粉色哑光唇，低饱和高级感"),
    ("hz006", "气质系", "法式微醺妆",
     "法式慵懒妆容：自然毛流感浓眉，大地色眼影轻扫，眼下一丢丢微醺红晕，"
     "豆沙玫瑰色唇膏手指晕染边缘，随性慵懒氛围"),
    ("hz007", "气质系", "千金大小姐妆",
     "精致贵气妆容：细腻缎光底妆，自然眉形干净利落，香槟金棕眼影微微提亮，"
     "玫瑰茶色唇妆，精致但不浓艳，富家千金感"),
    ("hz008", "新娘系", "白纱主纱妆",
     "经典白纱新娘妆：透亮奶油肌，温柔粉棕色眼影，根根分明太阳花睫毛，"
     "淡玫瑰色唇妆，眼下轻微珠光提亮，甜美减龄不显老气。"
     "只化妆，绝对不要出现头纱、发饰、发夹、皇冠等任何头部装饰，保持黑长直发完全不变"),
    ("hz009", "新娘系", "新中式秀禾妆",
     "减龄版中式新娘妆：柳叶细眉，杏红色眼影淡淡的，"
     "樱桃红咬唇妆内深外浅晕染，脸颊淡扫绯红，古典韵味但年轻清秀，绝不老气"),
    ("hz010", "新娘系", "敬酒微醺红妆",
     "元气敬酒妆：光泽感底妆，暖棕眼影，"
     "番茄红唇带一点水光感（不是厚重正红），苹果肌淡扫橘粉腮红，喜庆又年轻"),
    ("hz013", "气质系", "自然清透氛围感妆",
     "自然清透氛围感妆容：轻薄透亮底妆提亮肤色并保留自然光泽感，自然眉形眉尾微微拉长，"
     "大地色眼影打底，自然卧蚕提亮，柔和细眼线，睫毛轻盈上翘，"
     "淡粉色腮红打在苹果肌向颧骨斜上方自然晕染，水润豆沙蜜桃色唇妆带自然水光感，"
     "整体清冷温柔有亲和力"),
    ("hz011", "个性系", "复古港风妆",
     "90年代港风妆容：哑光雾面底妆，浓黑英气眉，大地色哑光眼影加深眼窝，"
     "复古哑光红唇，黑发配红唇的经典港星感"),
    ("hz012", "个性系", "混血浓颜妆",
     "轻欧美混血感妆容：立体修容提亮骨相，挑眉，"
     "截断式眼影（cut crease）带闪片，裸棕色唇线饱满的唇妆，浓颜但不脏"),
]

PROMPT_TMPL = (
    "严格保持参考图中人物的五官、脸型、发型、肤色基底、构图和背景完全不变，"
    "只为她化上指定妆容：{makeup}。"
    "正面肩部以上肖像特写，浅灰纯色背景，柔和摄影棚灯光，"
    "专业妆后照（after photo）质感，妆容细节清晰真实，"
    "不要改变脸型和五官结构，不要加饰品，不要眼镜，无文字无水印，3:4竖版"
)

NEGATIVE = "改变脸型，改变五官，磨皮过度，妆面脏，油光满面，厚重假面感，老气"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    STYLES_DIR.mkdir(exist_ok=True)

    for code, series, name, makeup in STYLES:
        dest = STYLES_DIR / f"{code}.png"
        if dest.exists():
            print(f"{code} {name} 已存在，跳过")
            continue
        prompt = PROMPT_TMPL.format(makeup=makeup)
        print(f"{code} {name}（{series}）生成中...", flush=True)
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
