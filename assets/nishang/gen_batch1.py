"""霓裳阁第一批：20 套套装对应的女装+男装样板图（40 张）。

人台样板图：无头人台模特正面全身、浅灰纯色背景、柔光、产品摄影质感。
中式/汉服女装入 中式/，其余女装入 婚纱/，男装全部入 礼服/。
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config  # noqa: E402

OUT = Path(__file__).resolve().parent

# (set_id, 女装文件名分类, 女装描述, 男装描述)
SETS = [
    ("set-01", "婚纱", "象牙白A字缎面主纱，抹胸，高腰大摆，缎面光泽", "黑色塔士多礼服，缎面青果领，白衬衫黑领结"),
    ("set-02", "婚纱", "白色蕾丝鱼尾主纱，长袖，修身包臀鱼尾摆", "深灰色三件套西装，修身，马甲同色系"),
    ("set-03", "婚纱", "象牙白波西米亚轻纱长裙，V领蕾丝上身，飘逸薄纱裙摆", "浅米色亚麻西装，无领带，休闲两粒扣"),
    ("set-04", "婚纱", "白色露背长拖尾婚纱，细吊带，大露背，轻盈雪纺长拖尾", "白色亚麻衬衫挽袖配深色西裤，无外套"),
    ("set-05", "婚纱", "象牙白复古方领缎面连衣裙，1950年代风格，伞裙中长", "酒红色天鹅绒礼服外套，黑西裤，复古油头造型"),
    ("set-06", "婚纱", "白色吊带极简长裙，直筒垂坠，无装饰", "浅灰色修身西装，极简无领结"),
    ("set-07", "婚纱", "法式碎花茶歇裙，浅黄底小花，V领裹身中长裙", "米色休闲西装配白T恤"),
    ("set-08", "婚纱", "银色亮片晚礼服，吊带，修身开衩长裙，闪亮", "午夜蓝修身西装，黑衬衫"),
    ("set-09", "中式", "正红色金丝刺绣秀禾服，龙凤纹样，立领对襟，红色百褶裙", "暗红色长袍马褂，黑色马蹄袖，传统中式男装"),
    ("set-10", "中式", "红金龙凤褂，金银线龙凤刺绣，直筒裙褂", "黑色中山装，立领四口袋"),
    ("set-11", "中式", "墨绿色旗袍，1930年代民国风格，高领盘扣，修身开衩", "深灰色中山装，民国风格"),
    ("set-12", "中式", "竹青色改良旗袍，新中式，斜襟盘扣，及踝", "新中式立领男装，米白色，盘扣"),
    ("set-13", "婚纱", "白色针织连衣裙，秋冬款，温柔简约", "驼色长款羊毛大衣配高领毛衣"),
    ("set-14", "婚纱", "白色衬衫配浅蓝A字裙，学院风", "学院风毛衣背心配白衬衫和休闲西裤"),
    ("set-15", "婚纱", "白色短款轻纱裙配黑色皮夹克，个性混搭", "黑色T恤配修身牛仔裤"),
    ("set-16", "婚纱", "白色蓬蓬公主裙，多层薄纱大蓬裙，童话风", "白色王子风礼服，金色刺绣肩章"),
    ("set-17", "中式", "唐制齐胸襦裙，石榴红上襦配月白长裙，唐风印花", "唐制圆领袍，深红色，革带"),
    ("set-18", "中式", "宋制褙子套装，藕粉色长褙子配白色宋裤", "宋代圆领袍，天青色"),
    ("set-19", "婚纱", "酒红色缎面吊带裙，港风复古，修身及膝", "复古花衬衫配黑色西装外套，港风"),
    ("set-20", "婚纱", "白色长袖缎面主纱，高领，优雅保守款", "白色修身西装"),
]

STYLE_SUFFIX = "，无头人台模特正面全身展示，浅灰纯色背景，柔和摄影棚灯光，服装产品摄影，版型完整细节清晰，无文字无水印，3:4竖版"


def main() -> None:
    config.load_dotenv()
    client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    for cat in ("婚纱", "礼服", "中式"):
        (OUT / cat).mkdir(exist_ok=True)

    for idx, (set_id, cat, dress, suit) in enumerate(SETS, 1):
        for kind, c, desc in (("dress", cat, dress), ("suit", "礼服", suit)):
            fid = f"{'nz' if kind == 'dress' else 'lf'}-{idx:03d}"
            dest = OUT / c / f"{fid}.png"
            if dest.exists():
                print(f"{fid} 已存在，跳过")
                continue
            prompt = desc + STYLE_SUFFIX
            print(f"{fid}（{set_id} {kind}）生成中...", flush=True)
            try:
                urls = client.generate_image(prompt=prompt, size="2K", reference_images=None,
                                             model=model, watermark=False)
                for url in urls:
                    client.download(url, dest)
                print(f"{fid} 完成")
            except Exception as e:
                print(f"{fid} 失败：{str(e)[:150]}")
            time.sleep(1)
    print("第一批结束")


if __name__ == "__main__":
    main()
