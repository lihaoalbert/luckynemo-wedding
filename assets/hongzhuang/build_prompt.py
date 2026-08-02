"""红妆阁：按款式编号组装「五维配方」定妆提示词。

用法：
    python build_prompt.py hz002            # 打印定妆提示词
    python build_prompt.py hz002 --keep-glasses   # 保留眼镜

模板说明（源自妆容指南.jpg 的五维拆解：底妆/眼妆/腮红/唇妆/发型）：
    定妆提示词 = 人物锁定 + 摘镜声明 + 五维配方 + 摄影规格 + 红线
"""
import argparse
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

TEMPLATE = (
    "以参考照片中的{person}为人物，严格保持{ta}的五官、脸型、下颌线、发型完全不变，"
    "{glasses}只为{ta}化上「{name}」妆容，配方如下：\n"
    "{recipe}\n"
    "整体妆感要求：{vibe}。妆容清透自然，绝不老气。\n"
    "正面肩部以上肖像，浅灰色纯色背景，柔和均匀的摄影棚灯光，专业妆面照质感，"
    "不要改变脸型和五官结构，不要加任何饰品，无文字无水印，3:4竖版"
)

NEGATIVE = "改变脸型，瘦脸，尖下巴，改变五官，磨皮过度，油光满面，浓妆艳抹，老气，假面感，腮红过重"


def build(style_id: str, keep_glasses: bool = False) -> tuple[str, str]:
    data = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
    style = next((s for s in data["styles"] if s["id"] == style_id), None)
    if style is None:
        ids = ", ".join(s["id"] for s in data["styles"])
        raise SystemExit(f"未找到款式 {style_id}（可用：{ids}）")
    parts = style["spec"]["parts"]
    recipe = "\n".join(f"{k}：{v}" for k, v in parts.items() if k != "发型")
    male = style.get("gender") == "male"
    prompt = TEMPLATE.format(
        person="男性" if male else "女性", ta="他" if male else "她",
        name=style["name"], vibe=style["vibe"], recipe=recipe,
        glasses="" if keep_glasses else "卸掉眼镜，",
    )
    return prompt, NEGATIVE


def main() -> None:
    ap = argparse.ArgumentParser(description="组装五维配方定妆提示词")
    ap.add_argument("style_id", help="款式编号，如 hz002")
    ap.add_argument("--keep-glasses", action="store_true", help="保留眼镜（默认摘镜）")
    args = ap.parse_args()
    prompt, negative = build(args.style_id, args.keep_glasses)
    print("=== 正向提示词 ===")
    print(prompt)
    print("\n=== 负向提示词 ===")
    print(negative)


if __name__ == "__main__":
    main()
