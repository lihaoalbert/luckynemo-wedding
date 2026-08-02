"""模卡库 P2/P3：系列化变体批次。首批 12 张（mk001-012）各作为一个系列的首发变体，
本脚本为每个系列补第 2 变体（mk101-112）和第 3 变体（mk201-212），共 24 张。
同系列保持场景/服装/色调一致，只换瞬间、姿势与构图。

用法：python gen_variants.py            # 全部（已存在自动跳过）
      python gen_variants.py mk101 mk102  # 只生成指定 id
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REF = ROOT / "referrence"

COUPLE = ["陆辰野", "黎泠娜"]
SOLO_F = ["沈念卿"]
SOLO_M = ["陈奕辰"]

TAIL = "真实人体比例约7.5头身，人物与地面有自然接触和投影，摄影级质感，参考图中人物五官保持一致"

# (id, 系列, mode, 标题, 参考人物, 提示词)
T = [
    # ---- 批次2：每系列第 2 变体 ----
    ("mk101", "church", "couple", "教堂婚礼 · 出场", COUPLE,
     "宏伟哥特式教堂大门口，一对新婚夫妻手牵手步出教堂，逆光金边轮廓，空中飘落白色花瓣，"
     "新娘穿象牙白缎面抹胸A字主纱裙摆被光打透，新郎穿黑色塔士多礼服，两人开心大笑，"
     "神圣又喜悦，电影级光影，全身竖版构图，" + TAIL),
    ("mk102", "jiangnan", "couple", "江南雨巷 · 桥头", COUPLE,
     "江南古镇石拱桥上，细雨蒙蒙，一对情侣共撑一把黑伞站在桥顶相望而笑，新郎的手真实握住伞柄，"
     "新娘穿浅色连衣裙，新郎穿深色休闲西装，桥下乌篷船划过，青瓦白墙倒影在河面，"
     "冷调青灰与灯笼暖光对比，电影感远景构图，全身竖版，" + TAIL),
    ("mk103", "seaside", "couple", "海边落日 · 旋转", COUPLE,
     "海边落日金色逆光，新郎挽起白衬衫袖子笑着把穿白色轻纱的新娘抱起旋转，裙摆大幅飞扬，"
     "海浪轻拍沙滩，金色波光，两人笑容灿烂，浪漫电影海报感，全身竖版构图，" + TAIL),
    ("mk104", "chinese", "couple", "中式婚礼 · 拜堂", COUPLE,
     "中式喜堂，红烛红灯笼暖光，囍字红绸背景前，新郎穿暗红长袍马褂与穿正红金丝刺绣秀禾服的新娘相对行拜堂礼，"
     "两人躬身对拜瞬间，喜庆庄重，电影级布光，全身竖版构图，摄影级质感，参考图中人物五官保持一致，不出现任何证件文书"),
    ("mk105", "flowerfield", "solo_f", "花海春日 · 奔跑", SOLO_F,
     "春日油菜花田小径，一位年轻女性穿白色连衣裙在花田间奔跑回头大笑，长发和裙摆飞扬，"
     "金黄花海延伸到天边，逆光通透感，动态瞬间抓拍，清新治愈，全身竖版构图，" + TAIL),
    ("mk106", "citynight", "solo_f", "城市夜景 · 天桥", SOLO_F,
     "城市夜景人行天桥上，一位时尚女性穿黑色吊带裙行走中回头，长发被夜风吹起，"
     "身后是车流光轨与璀璨城市灯海，冷调蓝光与暖光交织，电影感时尚大片，全身竖版构图，" + TAIL),
    ("mk107", "forest", "solo_f", "森林晨雾 · 光束", SOLO_F,
     "清晨森林，薄雾未散，丁达尔光束穿过高大树林洒下，一位穿浅色长裙的女性在光束中提裙轻盈旋转，"
     "晨雾柔光，仙气飘渺，清新自然，全身竖版构图，" + TAIL),
    ("mk108", "hongkong_f", "solo_f", "复古港风 · 电话亭", SOLO_F,
     "90年代港风街头夜景，一位明艳女性穿酒红色缎面吊带裙，黑色大波浪卷发，复古红唇，"
     "倚在老式红色电话亭里手拿听筒浅笑，霓虹招牌光晕映在玻璃上，胶片颗粒感，王家卫电影色调，半身构图，" + TAIL),
    ("mk109", "street", "solo_m", "都市街拍 · 咖啡", SOLO_M,
     "都市老街街角咖啡店门口，一位年轻男性穿浅米色休闲西装内搭白T，单手拿咖啡杯倚墙而立，"
     "午后阳光斜照，眼神松弛带笑意，景深虚化街景，时尚街拍大片感，全身竖版构图，" + TAIL),
    ("mk110", "studio", "solo_m", "棚拍正装 · 反坐", SOLO_M,
     "高级灰调摄影棚，一位年轻男性穿深灰三件套西装，反坐在木质靠背椅上，双臂自然搭在椅背，"
     "眼神锐利看向镜头，戏剧化侧光勾出轮廓，杂志封面级质感，半身构图，摄影级布光，" + TAIL),
    ("mk111", "hongkong_m", "solo_m", "港风花衬衫 · 大排档", SOLO_M,
     "90年代港风大排档夜景，一位年轻男性穿复古花衬衫配黑西装外套，坐在折叠桌旁举杯微笑，"
     "桌上摆着啤酒瓶和搪瓷碟，胶片颗粒，暖黄与霓虹红绿对比，港片氛围，半身构图，" + TAIL),
    ("mk112", "outdoor", "solo_m", "山野户外 · 岩石", SOLO_M,
     "秋日山野草甸，一位年轻男性穿卡其色户外夹克坐在巨大岩石上，手搭膝盖远眺群山，"
     "金色斜阳洒满草甸，自由辽阔感，旅行大片，全身竖版构图，" + TAIL),
    # ---- 批次3：每系列第 3 变体 ----
    ("mk201", "church", "couple", "教堂婚礼 · 戒指", COUPLE,
     "宏伟哥特式教堂祭坛前，彩色玻璃窗光斑洒落，新郎穿黑色塔士多礼服正为穿象牙白缎面主纱的新娘戴上戒指，"
     "两人低头注视交握的双手，神情温柔庄重，神圣瞬间特写，电影级光影，半身竖版构图，" + TAIL),
    ("mk202", "jiangnan", "couple", "江南雨巷 · 屋檐", COUPLE,
     "江南古镇雨巷屋檐下，一对情侣挨着躲雨，新娘穿浅色连衣裙，新郎穿深色休闲西装，"
     "两人相视而笑，檐角雨珠成线落下，青石板路湿滑反光，红灯笼暖光，"
     "冷调青灰与暖光对比，生活气息与浪漫并存，近景竖版构图，" + TAIL),
    ("mk203", "seaside", "couple", "海边落日 · 相拥", COUPLE,
     "海边落日余晖中，一对新婚夫妻相拥而立额头相抵，双眼轻闭，新娘白色轻纱被海风轻拂，"
     "新郎挽袖白衬衫环住新娘，逆光剪影与面部补光平衡，海面金光，温柔至极，特写竖版构图，" + TAIL),
    ("mk204", "chinese", "couple", "中式婚礼 · 合卺", COUPLE,
     "中式婚房红烛光中，新郎穿暗红长袍马褂与穿正红金丝刺绣秀禾服的新娘手臂相交饮合卺酒，"
     "红绳相连的双杯，两人眼含笑意，囍字红绸背景，喜庆含蓄，电影级布光，近景竖版构图，摄影级质感，"
     "参考图中人物五官保持一致，不出现任何证件文书"),
    ("mk205", "flowerfield", "solo_f", "花海春日 · 嗅花", SOLO_F,
     "春日油菜花田里，一位年轻女性穿白色连衣裙蹲下身轻嗅一枝油菜花，闭眼浅笑，"
     "阳光洒在发丝上形成金边，金黄花海虚化背景，逆光通透，清新治愈，近景竖版构图，" + TAIL),
    ("mk206", "citynight", "solo_f", "城市夜景 · 倚栏", SOLO_F,
     "城市夜景天台栏杆旁，一位时尚女性穿黑色吊带裙侧身倚栏，手肘撑在栏杆上托腮，"
     "看向镜头眼神有故事感，身后霓虹光斑虚化，冷调蓝光与暖光交织，电影感时尚大片，半身构图，" + TAIL),
    ("mk207", "forest", "solo_f", "森林晨雾 · 溪边", SOLO_F,
     "清晨森林小溪边，薄雾缭绕，一位穿浅色长裙的女性赤足站在浅溪中，双手轻轻提起裙摆，"
     "低头看水中倒影微笑，晨雾柔光穿过树林，仙气飘渺，全身竖版构图，" + TAIL),
    ("mk208", "hongkong_f", "solo_f", "复古港风 · 霓虹墙", SOLO_F,
     "90年代港风街头，一位明艳女性穿酒红色缎面吊带裙，黑色大波浪卷发，复古红唇，"
     "背倚深色卷帘门，头顶霓虹招牌红绿光晕洒在脸上，眼神慵懒看向镜头，"
     "背景干净不出现任何海报文字和其他人物面孔，胶片颗粒感，王家卫电影色调，半身构图，" + TAIL),
    ("mk209", "street", "solo_m", "都市街拍 · 回眸", SOLO_M,
     "都市老街转角，午后阳光，一位年轻男性穿浅米色休闲西装内搭白T，走过街角时侧身回眸，"
     "眼神自信带一点笑意，墙面光影斑驳，景深虚化，时尚街拍大片感，半身竖版构图，" + TAIL),
    ("mk210", "studio", "solo_m", "棚拍正装 · 领带", SOLO_M,
     "高级灰调摄影棚，一位年轻男性穿深灰三件套西装，双手调整领带结，低眉垂眼神情专注，"
     "戏剧化侧光勾出下颌线与手部轮廓，杂志封面级质感，近景构图，摄影级布光，" + TAIL),
    ("mk211", "hongkong_m", "solo_m", "港风花衬衫 · 巷行", SOLO_M,
     "90年代港风霓虹小巷，一位年轻男性穿复古花衬衫配黑西装外套，行走中回头看向镜头微笑，"
     "两侧霓虹招牌红绿交错，地面潮湿反光，胶片颗粒，港片氛围，全身竖版构图，" + TAIL),
    ("mk212", "outdoor", "solo_m", "山野户外 · 余晖", SOLO_M,
     "秋日山野草甸黄昏，一位年轻男性穿卡其色户外夹克迎着落日行走回头看向镜头，"
     "逆金光洒在肩头和发梢形成金边，面部补光柔和五官清晰，草甸被染成金色，远山层叠，"
     "自由辽阔感，旅行大片，全身竖版构图，" + TAIL),
]

SERIES_TITLE = {
    "church": "教堂婚礼", "jiangnan": "江南雨巷", "seaside": "海边落日", "chinese": "中式婚礼",
    "flowerfield": "花海春日", "citynight": "城市夜景", "forest": "森林晨雾", "hongkong_f": "复古港风",
    "street": "都市街拍", "studio": "棚拍正装", "hongkong_m": "港风花衬衫", "outdoor": "山野户外",
}


def refs_for(names: list[str]) -> list[str]:
    files = []
    for n in names:
        d = REF / n
        pics = sorted([p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        if pics:
            files.append(str(pics[0].resolve()))
    return files


def main() -> None:
    only = set(sys.argv[1:])
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    (OUT / "templates").mkdir(exist_ok=True)

    todo = [t for t in T if not only or t[0] in only]
    for tid, series, mode, title, names, prompt in todo:
        dest = OUT / "templates" / f"{tid}.png"
        if dest.exists():
            print(f"{tid} 已存在，跳过")
            continue
        refs = refs_for(names)
        print(f"{tid} {title}（{SERIES_TITLE[series]}/{mode}，参考{len(refs)}人）生成中...", flush=True)
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
