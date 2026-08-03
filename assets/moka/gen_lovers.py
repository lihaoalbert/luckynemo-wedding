"""lovers 范本换脸：用我们的虚拟模特替换范本照片中的男女，神态/表情/光影严格保持原照片。
情侣 → 陆辰野×黎泠娜；男单 → 陈奕辰；女单 → 沈念卿。
输出到 assets/moka/lovers_draft/（审片通过后再入正式库）。

用法：python gen_lovers.py            # 全部（已存在自动跳过）
      python gen_lovers.py lv001      # 只生成指定 id
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "lovers_draft"
REF = ROOT / "referrence"
SRC = Path("/Users/lihao/Desktop/lovers")

PROMPT_COUPLE = (
    "最后一张参考图是完整的摄影作品模板，前面的参考图是要替换上去的人物。"
    "把模板中的人物替换为参考图的人物（按性别一一对应替换），"
    "严格保持模板的构图、场景、服装、妆容、道具、姿势、神态、表情、光影、色调、背景完全不变，"
    "只替换人物的五官与面部特征，真实人体比例约7.5头身，与场景自然融合有投影，"
    "摄影级质感，无文字无水印"
)
PROMPT_SOLO = (
    "最后一张参考图是完整的摄影作品模板，前面的参考图是要替换上去的人物。"
    "只把模板中的主体人物替换为参考图的人物，"
    "严格保持模板的构图、场景、服装、妆容、道具、姿势、神态、表情、光影、色调、背景完全不变，"
    "只替换主体人物的五官与面部特征，真实人体比例约7.5头身，与场景自然融合有投影，"
    "摄影级质感，无文字无水印"
)

# (id, 范本文件名, "couple"/"solo_m"/"solo_f")
T = [
    ("lv001", "farzin-yarahmadi--NBtbsB0Tdo-unsplash.jpg", "couple"),
    ("lv002", "farzin-yarahmadi-FRW1T9Up2Do-unsplash.jpg", "couple"),
    ("lv003", "henry-ravenscroft-6zGfuF27Nwc-unsplash.jpg", "couple"),
    ("lv004", "jonathan-borba-9GkapULEiTE-unsplash.jpg", "couple"),
    ("lv005", "kevin-zhong-yXvRKY13EUs-unsplash.jpg", "solo_m"),
    ("lv006", "micah-sammie-chaffin-mQEGvXR7doM-unsplash.jpg", "couple"),
    ("lv007", "mubariz-mehdizadeh-KRrsoIOHmIc-unsplash.jpg", "couple"),
    ("lv008", "pexels-2081218-3715080.jpg", "couple"),
    ("lv009", "pexels-_ofarias-g-530112232-16933321.jpg", "couple"),
    ("lv010", "pexels-abedalbaset-11215185.jpg", "couple"),
    ("lv011", "pexels-abedalbaset-11215190.jpg", "couple"),
    ("lv012", "pexels-anastasiia-klochko-2131279587-38707942.jpg", "couple"),
    ("lv013", "pexels-anastasiia-klochko-2131279587-38707950.jpg", "couple"),
    ("lv014", "pexels-anastasiia-klochko-2131279587-38707952.jpg", "couple"),
    ("lv015", "pexels-anastasiia-klochko-2131279587-38707953.jpg", "couple"),
    ("lv016", "pexels-anastasiia-klochko-2131279587-38707954.jpg", "couple"),
    ("lv017", "pexels-anastasiia-klochko-2131279587-38707958.jpg", "couple"),
    ("lv018", "pexels-anastasiia-klochko-2131279587-38707960.jpg", "couple"),
    ("lv019", "pexels-anastasiia-klochko-2131279587-38707961.jpg", "couple"),
    ("lv020", "pexels-anastasiia-klochko-2131279587-38707983.jpg", "couple"),
    ("lv021", "pexels-anastasiia-klochko-2131279587-38708013.jpg", "couple"),
    ("lv022", "pexels-anastasiia-klochko-2131279587-38708014.jpg", "couple"),
    ("lv023", "pexels-birseydaha-20256735.jpg", "couple"),
    ("lv024", "pexels-bphet-14283864.jpg", "couple"),
    ("lv025", "pexels-caner-kokcu-636242728-19717686.jpg", "couple"),
    ("lv026", "pexels-chu-cuong-172080595-11017491.jpg", "couple"),
    ("lv027", "pexels-danikprihodko-15878545.jpg", "couple"),
    ("lv028", "pexels-el-gringo-photo-116752370-13394393.jpg", "couple"),
    ("lv029", "pexels-firvntivcus-34001911.jpg", "couple"),
    ("lv030", "pexels-gabii-fernandez-199438359-28127501.jpg", "couple"),
    ("lv031", "pexels-hubert-kolucki-3667638-16280336.jpg", "couple"),
    ("lv032", "pexels-ilse-fernandez-202979727-12204992.jpg", "couple"),
    ("lv033", "pexels-ivanxolod-8602105.jpg", "couple"),
    ("lv034", "pexels-jonathanborba-28206851.jpg", "couple"),
    ("lv035", "pexels-kari-alfonso-2151442665-31738010.jpg", "couple"),
    ("lv036", "pexels-kate-andreeshcheva-35129697-7102717.jpg", "couple"),
    ("lv037", "pexels-kenzero14-21849238.jpg", "couple"),
    ("lv038", "pexels-klaudia-kmak-791120880-19080753.jpg", "couple"),
    ("lv039", "pexels-lilen-diaz-1025474869-32936170.jpg", "couple"),
    ("lv040", "pexels-lucas-agustin-303343526-29091303.jpg", "couple"),
    ("lv041", "pexels-maide-arslan-128712163-28208841.jpg", "couple"),
    ("lv042", "pexels-manzano-30695962.jpg", "couple"),
    ("lv043", "pexels-maynor-marin-985240220-35348352.jpg", "couple"),
    ("lv044", "pexels-mizunokozuki-13931254.jpg", "couple"),
    ("lv045", "pexels-moss-studio-34161744-7204681.jpg", "couple"),
    ("lv046", "pexels-n-c-h-2158028276-35110670.jpg", "couple"),
    ("lv047", "pexels-n-c-h-2158028276-35110678.jpg", "couple"),
    ("lv048", "pexels-nguy-n-quang-b-o-2160161631-36536741.jpg", "couple"),
    ("lv049", "pexels-nguy-n-quang-b-o-2160161631-36536771.jpg", "couple"),
    ("lv050", "pexels-nguy-n-quang-b-o-2160161631-36634532.jpg", "couple"),
    ("lv051", "pexels-nina-hill-76946523-13293963.jpg", "couple"),
    ("lv052", "pexels-nuptune-12933825.jpg", "couple"),
    ("lv053", "pexels-rebornfilmes-32195285.jpg", "couple"),
    ("lv054", "pexels-rebornfilmes-38788830.jpg", "couple"),
    ("lv055", "pexels-rizkysabriansyah-36210950.jpg", "couple"),
    ("lv056", "pexels-seljansalim-26898072.jpg", "couple"),
    ("lv057", "pexels-seljansalim-37842588.jpg", "couple"),
    ("lv058", "pexels-serhattugg-30279957.jpg", "couple"),
    ("lv059", "pexels-skylake-20220643.jpg", "couple"),
    ("lv060", "pexels-studio-dreamview-2155988023-34187159.jpg", "couple"),
    ("lv061", "pexels-studio-dreamview-2155988023-34537987.jpg", "couple"),
    ("lv062", "pexels-thamyres-silva-2024441-16767472.jpg", "couple"),
    ("lv063", "pexels-toan-van-1745332-17894673.jpg", "couple"),
    ("lv064", "pexels-tr-n-long-3093985-14930184.jpg", "couple"),
    ("lv065", "pexels-truc-giang-530101831-34689151.jpg", "couple"),
    ("lv066", "pexels-yasir-11923571-6205954.jpg", "couple"),
    ("lv067", "pexels-yulia-polyakova-73722901-10095638.jpg", "couple"),
    ("lv068", "sina-rezakhani-H3ts3S8b_xo-unsplash.jpg", "couple"),
]

# 已分类跳过的范本（人物太小/遮挡严重/过曝遮脸/非一男一女/无正脸）：
# pexels-anastasiia-klochko-2131279587-38707984 / pexels-cottonbro-8272150 / pexels-cottonbro-9388999
# pexels-h-nh-ph-m-724202179-20134684 / pexels-vitalyagorbachev-14201613
# pexels-yudi-ding-2155130552-37238919 / phong-duong-RVXf_T3tvxc-unsplash / kevin-zhong-b3ZA7MhYA2c（空镜）

MODELS = {"couple": ["陆辰野", "黎泠娜"], "solo_m": ["陈奕辰"], "solo_f": ["沈念卿"]}

#: 重跑加强词：针对换脸未生效（侧脸/遮挡/小脸）的范本
STRONG = ("；特别强调：模板中每一个人物的脸都必须完整替换为参考图人物的五官，"
          "无论是正脸、侧脸、低头、远距离小脸，还是被墨镜/头发/手部分遮挡的脸，"
          "都不能保留原照片人物的任何面部特征；每个人的动作、手部位置也必须与原模板完全一致")


def shrink(src: Path) -> Path:
    """范本总像素超过方舟上限（36M）时等比缩到 ~24M，返回可用路径（缓存到 _small/）。"""
    import subprocess
    info = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(src)],
                          capture_output=True, text=True).stdout
    w = h = 0
    for line in info.splitlines():
        if "pixelWidth" in line:
            w = int(line.split()[-1])
        if "pixelHeight" in line:
            h = int(line.split()[-1])
    if not w or not h or w * h <= 30_000_000:
        return src
    small_dir = OUT / "_small"
    small_dir.mkdir(exist_ok=True)
    out = small_dir / src.name
    if not out.exists():
        scale = (24_000_000 / (w * h)) ** 0.5
        subprocess.run(["sips", "-Z", str(int(max(w, h) * scale)), str(src), "--out", str(out)],
                       check=True, capture_output=True)
    return out


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
    OUT.mkdir(exist_ok=True)

    for tid, fname, mode in T:
        if only and tid not in only:
            continue
        dest = OUT / f"{tid}.png"
        if dest.exists():
            print(f"{tid} 已存在，跳过")
            continue
        src = SRC / fname
        if not src.is_file():
            print(f"!! {tid} 范本不存在：{src}")
            continue
        refs = refs_for(MODELS[mode]) + [str(shrink(src))]
        prompt = PROMPT_COUPLE if mode == "couple" else PROMPT_SOLO
        if "--strong" in sys.argv:
            prompt += STRONG
        print(f"{tid} {fname}（{mode}）生成中...", flush=True)
        try:
            urls = client.generate_image(
                prompt=prompt, size="2K", reference_images=refs,
                model=model, watermark=False)
            client.download(urls[0], dest)
            print(f"  -> {dest.name} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {tid} 失败：{exc}", flush=True)
        time.sleep(2)
    print("全部结束。")


if __name__ == "__main__":
    main()
