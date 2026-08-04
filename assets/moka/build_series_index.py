"""index.json 升 v3：一级分组（groups）+ 二级系列（series，每系列 9 变体=九宫格）。

做的事：
1. 下架 lv* 模板与系列（56 张平铺，由新 9 变体系列替代）；
2. mk 12 系列保留并编入一级分组（补 previews 没有的类目：教堂/中式/江南/夜景/港风/街拍/棚拍）；
3. 登记新系列：series_draft/<sid>/<tid>.png → templates/，每系列 9 变体；
4. 输出 groups 层。

用法：python build_series_index.py            # 全部新系列
      python build_series_index.py hyd sak    # 只登记指定系列
"""
import json
import shutil
import sys
from pathlib import Path

MOKA = Path(__file__).resolve().parent
DRAFT = MOKA / "series_draft"
TPL = MOKA / "templates"
INDEX = MOKA / "index.json"

#: 一级分组（顺序=小程序 tab 顺序）；mk 系列在编组里用原 id 引用
GROUPS = [
    {"id": "flower", "title": "花海浪漫", "subtitle": "把春天穿在身上",
     "series": ["hyd", "sak", "muh", "flowerfield"]},
    {"id": "nature", "title": "森林与原野", "subtitle": "去山野里撒野",
     "series": ["forest", "outdoor"]},
    {"id": "sea", "title": "海", "subtitle": "陪你去看海",
     "series": ["lig", "spk", "seaside"]},
    {"id": "city", "title": "城市与人文", "subtitle": "在街上，在故事里",
     "series": ["han", "citynight", "hongkong_f", "hongkong_m", "street"]},
    {"id": "ceremony", "title": "仪式与经典", "subtitle": "人生这一刻",
     "series": ["min", "church", "chinese", "jiangnan", "studio"]},
    {"id": "creative", "title": "个性创意", "subtitle": "朋友圈最特别的那张",
     "series": ["hor"]},
]

#: mk 老系列 → 一级分组归属
MK_GROUP = {
    "flowerfield": "flower", "forest": "nature", "outdoor": "nature",
    "seaside": "sea", "citynight": "city", "hongkong_f": "city",
    "hongkong_m": "city", "street": "city",
    "church": "ceremony", "chinese": "ceremony", "jiangnan": "ceremony", "studio": "ceremony",
}

#: 新系列元数据：id -> (名称, 分组, desc, components)
NEW_SERIES = {
    "hyd": ("蓝绣球花墙", "flower", "无尽夏蓝绣球花墙与森林湖畔，济州岛最出片的花墙",
            {"场景": "蓝绣球花墙/森林湖畔", "服装": "缎面主纱+浅色西装", "动作": "花墙前互动"}),
    "sak": ("樱花隧道", "flower", "樱花隧道纵深构图，春天限定的粉白长廊",
            {"场景": "樱花隧道/油菜花田", "服装": "白纱+深色西装", "动作": "隧道漫步牵手"}),
    "muh": ("粉黛乱子草", "flower", "粉雾草海把人包围，温柔到失焦的粉",
            {"场景": "粉黛乱子草海", "服装": "轻纱+休闲西装", "动作": "草海相拥"}),
    "lig": ("悬崖灯塔", "sea", "涉地可支灯塔与黑礁石海岸，一张大场景镇住九宫格",
            {"场景": "悬崖灯塔/黑礁石海岸", "服装": "主纱+西装", "动作": "海岸远眺"}),
    "han": ("韩服古祠", "city", "韩服与韩式古祠，一秒穿越的东方仪式感",
            {"场景": "韩式古祠/杉林", "服装": "传统韩服", "动作": "携手同行"}),
    "hor": ("以梦为马", "creative", "马场骏马与林间公路，婚纱照里的电影海报",
            {"场景": "马场/林间公路", "服装": "骑士风婚纱", "动作": "马上对视"}),
    "min": ("白色极简", "ceremony", "韩式白色拱门与极简光影，高级感不需要堆料",
            {"场景": "白色拱门极简空间", "服装": "缎面主纱+黑西装", "动作": "拱门剪影"}),
    "spk": ("暮色仙女棒", "sea", "暮色海边的仙女棒光绘，九宫格的浪漫收尾",
            {"场景": "暮色海边", "服装": "红裙/黑裙+西装", "动作": "仙女棒光绘"}),
}


def main() -> None:
    only = set(sys.argv[1:])
    data = json.loads(INDEX.read_text(encoding="utf-8"))

    # 1. 下架 lv*
    templates = [t for t in data["templates"] if not t["id"].startswith("lv")]
    series = [s for s in data["series"] if not s["id"].startswith("lv")]
    dropped = len(data["templates"]) - len(templates)

    # 2. mk 系列归属分组
    for s in series:
        if s["id"] in MK_GROUP:
            s["group"] = MK_GROUP[s["id"]]

    # 3. 登记新系列（draft → templates/）
    added = 0
    for sid, (title, group, desc, comp) in NEW_SERIES.items():
        if only and sid not in only:
            continue
        draft_dir = DRAFT / sid
        if not draft_dir.is_dir():
            print(f"!! {sid} 无 draft 目录，跳过")
            continue
        variant_ids = []
        for png in sorted(draft_dir.glob(f"{sid}*.png")):
            tid = png.stem
            dest = TPL / png.name
            if not dest.exists():
                shutil.copy2(png, dest)
            variant_ids.append(tid)
            if not any(t["id"] == tid for t in templates):
                templates.append({
                    "id": tid, "series": sid, "mode": "couple",
                    "title": f"{title} · {len(variant_ids):02d}",
                    "file": f"templates/{tid}.png",
                    "desc": desc,
                    "components": comp,
                })
                added += 1
        if not variant_ids:
            print(f"!! {sid} draft 为空，跳过")
            continue
        existing = next((s for s in series if s["id"] == sid), None)
        if existing:
            existing["variants"] = variant_ids
        else:
            series.append({"id": sid, "group": group, "mode": "couple",
                           "title": title, "variants": variant_ids})
        print(f"{sid} {title}：{len(variant_ids)} 变体")

    # 4. groups 层（只引用存在的系列）
    series_ids = {s["id"] for s in series}
    groups = [{**g, "series": [sid for sid in g["series"] if sid in series_ids]}
              for g in GROUPS]
    groups = [g for g in groups if g["series"]]

    out = {
        "name": "模卡库",
        "version": "3.0",
        "note": ("一键同款模板，v3 分组架构：一级分组（group，6 大类引导）→ 二级系列（series，"
                 "每系列 9 变体=朋友圈九宫格，场景/服装/色调锁定）→ 变体（template）。"
                 "新系列 ID=系列码+序号（如 hyd01-09）；mk 老系列 3 变体待扩充。lv 系列 2026-08-04 下架。"),
        "groups": groups,
        "series": series,
        "templates": templates,
    }
    INDEX.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"完成：下架 lv {dropped} 张，新增模板 {added} 张；"
          f"共 {len(templates)} 模板 / {len(series)} 系列 / {len(groups)} 分组")


if __name__ == "__main__":
    main()
