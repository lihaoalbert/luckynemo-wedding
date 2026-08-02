"""模卡库 P1：12 张市场最受欢迎风格的模板图（虚拟模特，最佳艺术效果）。

情侣：陆辰野×黎泠娜；女单：沈念卿；男单：陈奕辰。
纯文生+人物参考，艺术指导优先，不受现有服装/场景资产约束。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REF = ROOT / "referrence"

# (id, 模式, 标题, 参考人物目录列表, 提示词)
T = [
    ("mk001", "couple", "教堂彩窗 · 誓言", ["陆辰野", "黎泠娜"],
     "宏伟哥特式教堂内，一对新婚夫妻站在红毯中央深情对视微笑，新娘穿象牙白缎面抹胸A字主纱，新郎穿黑色塔士多礼服，"
     "彩色玻璃窗的光斑洒在两人身上和裙摆上，庄严神圣又温柔，电影级光影，全身竖版构图，真实人体比例约7.5头身，"
     "人物与地面有自然接触和投影，摄影级质感，参考图中人物五官保持一致"),
    ("mk002", "couple", "江南雨巷 · 共伞", ["陆辰野", "黎泠娜"],
     "江南古镇雨巷，青石板路湿滑反光，红灯笼暖光，一对情侣共撑一把黑伞依偎而行，新郎的手真实握住伞柄，"
     "新娘穿浅色连衣裙，新郎穿深色休闲西装，细雨丝清晰，冷调青灰与灯笼暖光对比，电影感构图，全身竖版，"
     "摄影级质感，参考图中人物五官保持一致"),
    ("mk003", "couple", "海边落日 · 逆光", ["陆辰野", "黎泠娜"],
     "海边落日金色逆光，一对新婚夫妻在沙滩上牵手漫步，新娘白色轻纱裙摆被海风吹起，新郎挽起白衬衫袖子，"
     "逆光剪影感与面部补光平衡，海面金光闪闪，浪漫电影海报感，全身竖版构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk004", "couple", "中式洞房 · 挑盖头", ["陆辰野", "黎泠娜"],
     "中式婚房，红烛红灯笼暖光，新郎穿暗红长袍马褂正轻轻挑起新娘的红盖头一角，新娘穿正红金丝刺绣秀禾服低头浅笑，"
     "囍字红绸背景，喜庆又含蓄，电影级布光，全身竖版构图，摄影级质感，参考图中人物五官保持一致，不出现任何证件文书"),
    ("mk005", "solo_f", "花海回眸 · 春日", ["沈念卿"],
     "春日油菜花田小径，一位年轻女性穿白色连衣裙侧身回眸浅笑，微风吹动长发和裙摆，金黄花海延伸到天边，"
     "逆光通透感，清新治愈，全身竖版构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk006", "solo_f", "城市夜景 · 霓虹", ["沈念卿"],
     "城市夜景天台，一位时尚女性穿黑色吊带裙凭栏而立，身后是璀璨的城市灯海与霓虹光斑，"
     "冷调蓝光与暖光交织，她侧脸看向远方，电影感时尚大片，半身到全身构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk007", "solo_f", "森林晨雾 · 精灵", ["沈念卿"],
     "清晨森林，薄雾未散，光束穿过高大树林洒下，一位穿浅色长裙的女性走在林间小路上回头微笑，"
     "晨雾柔光，仙气飘渺，清新自然，全身竖版构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk008", "solo_f", "复古港风 · 红裙", ["沈念卿"],
     "90年代港风街头夜景，一位明艳女性穿酒红色缎面吊带裙，黑色大波浪卷发，复古红唇，"
     "霓虹招牌光晕，胶片颗粒感，王家卫电影色调，半身构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk009", "solo_m", "都市街拍 · 雅痞", ["陈奕辰"],
     "都市老街午后阳光，一位年轻男性穿浅米色休闲西装内搭白T，单手插兜走在斑马线上，"
     "眼神自信带一点笑意，景深虚化街景，时尚街拍大片感，全身竖版构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk010", "solo_m", "棚拍正装 · 质感", ["陈奕辰"],
     "高级灰调摄影棚，一位年轻男性穿深灰三件套西装，单手整理袖扣，眼神沉稳看向镜头，"
     "戏剧化侧光勾出轮廓，杂志封面级质感，半身构图，摄影级布光，参考图中人物五官保持一致"),
    ("mk011", "solo_m", "港风花衬衫 · 夜色", ["陈奕辰"],
     "90年代港风大排档夜景，一位年轻男性穿复古花衬衫配黑西装外套，靠在霓虹灯下微笑，"
     "胶片颗粒，暖黄与霓虹红绿对比，港片氛围，半身构图，摄影级质感，参考图中人物五官保持一致"),
    ("mk012", "solo_m", "山野户外 · 远方", ["陈奕辰"],
     "秋日山野草甸，一位年轻男性穿卡其色户外夹克站在高处远眺群山，微风吹动，"
     "金色斜阳，自由辽阔感，旅行大片，全身竖版构图，摄影级质感，参考图中人物五官保持一致"),
]


def refs_for(names: list[str]) -> list[str]:
    files = []
    for n in names:
        d = REF / n
        pics = sorted([p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        if pics:
            files.append(str(pics[0].resolve()))
    return files


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    (OUT / "templates").mkdir(exist_ok=True)

    for tid, mode, title, names, prompt in T:
        dest = OUT / "templates" / f"{tid}.png"
        if dest.exists():
            print(f"{tid} 已存在，跳过")
            continue
        refs = refs_for(names)
        print(f"{tid} {title}（{mode}，参考{len(refs)}人）生成中...", flush=True)
        try:
            urls = client.generate_image(
                prompt=prompt, size="2K", reference_images=refs or None,
                model=model, watermark=False)
            client.download(urls[0], dest)
            print(f"  -> {dest.name} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {tid} 失败：{exc}", flush=True)
        time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
