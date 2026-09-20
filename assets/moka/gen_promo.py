"""种草素材工厂（自动化推广 v1 P1）：按模卡系列产出小红书/视频号素材包。

机器产、人工审、人工发——站外发布环节不自动化，本脚本只把素材准备到"一键复制"程度。

每系列产出一个素材包到 promo/<YYYYMMDD>/<series_id>/：
1. card_badged.png  系列首模板图 + 「AI 生成」角标
2. selfie.png       Seedream 生成的虚拟模特"手机自拍素颜照"（before 图，杜绝真实客片）
3. compare.png      左自拍/右大片的 1:1 对比拼图（等比放入不裁人，整体带 AI 角标）
4. copy.md          MiniMax M3 种草文案：3 个候选标题 + 正文 + 话题标签（prompt 内置合规红线）
5. manifest.json    生成参数/源模板/模型/时间戳留痕

用法：
    python gen_promo.py --series hyd muh   # 指定系列
    python gen_promo.py --top 3            # 按 index.json hot_base 取 Top N
    python gen_promo.py --series hyd --force   # 覆盖已有产物重跑
    （--top 本地只有 hot_base 运营基数；真实生成热度在服务端 mp_jobs，见 app.py _moka_hot_counts）
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools/luckynemo-toolkit"))
from luckynemo import ark, config, llm, watermark  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "promo"
REF = ROOT / "referrence"
INDEX = Path(__file__).resolve().parent / "index.json"

MODELS = {"couple": ["陆辰野", "黎泠娜"], "solo_f": ["沈念卿"], "solo_m": ["陈奕辰"]}

SELFIE_PROMPTS = {
    "couple": (
        "参考图中的一对年轻情侣用手机前置摄像头自拍合影，半身构图，两人都看向手机屏幕方向，"
        "素颜无妆感，穿日常休闲便服，生活场景（家中客厅窗边），自然光，表情放松自然带笑意，"
        "真实生活气息，手机摄影质感略带噪点，不要影楼布光不要精致妆造，竖版构图，"
        "参考图中人物五官保持一致，无文字无水印"),
    "solo_f": (
        "参考图中的年轻女性用手机前置摄像头自拍，半身构图，素颜无妆感，穿日常休闲便服，"
        "生活场景（家中客厅窗边），自然光，表情放松自然，真实生活气息，手机摄影质感略带噪点，"
        "不要影楼布光不要精致妆造，竖版构图，参考图中人物五官保持一致，无文字无水印"),
    "solo_m": (
        "参考图中的年轻男性用手机前置摄像头自拍，半身构图，素颜无妆感，穿日常休闲便服，"
        "生活场景（家中客厅窗边），自然光，表情放松自然，真实生活气息，手机摄影质感略带噪点，"
        "不要影楼布光不要精致妆造，竖版构图，参考图中人物五官保持一致，无文字无水印"),
}

#: 文案红线（广告法/平台合规），写进 system prompt 强制约束
COPY_SYSTEM = """你是 LuckyNemo 微信小程序的小红书种草文案写手。LuckyNemo 是 AI 婚纱照/写真生成小程序：
用户上传自己的照片，选一个模板系列，AI 一键把用户换进模板生成同款大片。

红线（必须严格遵守，违反任何一条的文案不可用）：
1. 必须明示素材与效果图为 AI 生成（如"图为 AI 生成效果"），不得伪装成真实拍摄客片。
2. 只描述"上传照片 → 选模板 → 生成大片"的使用过程和体验，禁止任何功效/效果承诺
   与对比（如"比影楼好看""秒变女神""拯救废片"这类承诺结果的表述都不行）。
3. 价格只能写事实：新用户免费体验 1 张、4 元/张、52 元/20 张。不得编造其他价格、折扣或优惠。
4. 禁止使用"最、第一、100%、百分百、全网、史上"等极限词与绝对化用语。
5. 不得提及竞品，不得虚构用户评价。"""

COPY_USER_TMPL = """为模板系列「{title}」写一篇小红书种草笔记。

系列信息：
- 场景：{scene}
- 服装：{costume}
- 风格标签：{tags}
- 适合节点：{moments}
- 模板描述：{desc}

配图是"手机自拍 vs AI 同款大片"的对比图（左：素颜自拍原图，右：AI 生成的系列成片）。

输出格式（严格遵守，不要输出其他内容）：
## 候选标题
1. （20 字以内，小红书口吻）
2. ...
3. ...
## 正文
（小红书口吻，200-300 字，emoji 适度，口语化，说明图为 AI 生成效果，
描述上传照片→选系列→生成同款的过程，结尾引导"微信小程序搜 LuckyNemo"）
## 话题标签
（8-10 个 # 话题标签，含 #AI婚纱照 #LuckyNemo）"""


def load_index() -> dict:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def refs_for(names: list[str]) -> list[str]:
    """虚拟模特参考图（与 gen_templates.py 同一取法：每人目录里第一张）。"""
    files = []
    for n in names:
        d = REF / n
        pics = sorted([p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])
        if pics:
            files.append(str(pics[0].resolve()))
    return files


def pick_series(data: dict, series_ids: list[str], top: int) -> list[dict]:
    series = data.get("series", [])
    picked: list[dict] = []
    seen: set[str] = set()
    if series_ids:
        by_id = {s["id"]: s for s in series}
        for sid in series_ids:
            s = by_id.get(sid)
            if s is None:
                print(f"!! 系列不存在：{sid}（index.json 里没有）", file=sys.stderr)
                continue
            picked.append(s)
            seen.add(sid)
    if top > 0:
        ranked = sorted(
            (s for s in series if s.get("status", "normal") == "normal"),
            key=lambda s: int(s.get("hot_base", 0) or 0), reverse=True)
        for s in ranked[:top]:
            if s["id"] not in seen:
                picked.append(s)
                seen.add(s["id"])
    return picked


def _fit_inside(img, box_w: int, box_h: int):
    """等比缩放到盒内（contain），不裁剪，保证人物完整。"""
    w, h = img.size
    scale = min(box_w / w, box_h / h)
    return img.resize((max(int(w * scale), 1), max(int(h * scale), 1)))


def build_compare(selfie_path: Path, card_path: Path, series_title: str, dest: Path) -> Path:
    """1:1 对比拼图：左「手机自拍」右「AI 同款大片」，等比放入不裁剪，中间箭头分隔。"""
    from PIL import Image, ImageDraw

    W = H = 2048
    bg = (247, 244, 238)
    margin, label_h, gap, bottom_h = 64, 128, 72, 96
    panel_w = (W - margin * 2 - gap) // 2
    panel_y0 = margin + label_h + 24
    panel_h = H - bottom_h - margin - panel_y0

    canvas = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(canvas)
    font_label = watermark.load_cjk_font(52)
    font_title = watermark.load_cjk_font(44)

    panels = [
        (margin, selfie_path, "手机自拍", (255, 255, 255), (90, 90, 90)),
        (margin + panel_w + gap, card_path, "AI 同款大片", (30, 30, 30), (255, 255, 255)),
    ]
    for x0, path, label, pill_bg, pill_fg in panels:
        img = _fit_inside(Image.open(path).convert("RGB"), panel_w, panel_h)
        px = x0 + (panel_w - img.size[0]) // 2
        py = panel_y0 + (panel_h - img.size[1]) // 2
        canvas.paste(img, (px, py))
        # 标签 pill 居中于面板顶部
        tw = draw.textlength(label, font=font_label)
        pad_x, pad_y = 34, 14
        ascent, descent = font_label.getmetrics()
        bw, bh = tw + pad_x * 2, ascent + descent + pad_y * 2
        bx = x0 + (panel_w - bw) / 2
        by = margin + (label_h - bh) / 2
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=bh / 2, fill=pill_bg)
        draw.text((bx + bw / 2, by + bh / 2), label, font=font_label, fill=pill_fg, anchor="mm")

    # 中间箭头圆钮
    cx, cy, r = W / 2, panel_y0 + panel_h / 2, 52
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(30, 30, 30))
    draw.text((cx, cy), "→", font=watermark.load_cjk_font(64), fill=(255, 255, 255), anchor="mm")

    # 底部系列名
    draw.text((W / 2, H - margin - bottom_h / 2), f"{series_title} · AI 生成效果图",
              font=font_title, fill=(120, 115, 105), anchor="mm")

    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest)
    return dest


def strip_think(text: str) -> str:
    """剥离 M3 思维链（<think>...</think>）。"""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def gen_series_pack(s: dict, data: dict, out_dir: Path, img_client: ark.ArkClient,
                    llm_client: llm.LLMClient, img_model: str, force: bool) -> dict:
    sid = s["id"]
    mode, title = s.get("mode", "couple"), s.get("title", sid)
    tpl_by_id = {t["id"]: t for t in data.get("templates", [])}
    tpl = tpl_by_id.get((s.get("variants") or [""])[0])
    if tpl is None:
        raise RuntimeError(f"系列 {sid} 没有可用首变体模板")
    tpl_path = INDEX.parent / tpl["file"]
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "series_id": sid, "series_title": title, "mode": mode,
        "template": {"id": tpl["id"], "file": tpl["file"]},
        "models": {"image": img_model, "llm": llm_client.model},
        "hot_base": s.get("hot_base", 0),
        "prompts": {}, "files": {},
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # 1. 模板成片 + AI 角标
    card = out_dir / "card_badged.png"
    if card.exists() and not force:
        print(f"  card_badged.png 已存在，跳过")
    else:
        watermark.add_ai_badge(tpl_path, card)
        print(f"  -> card_badged.png（源 {tpl['id']}）")
    manifest["files"]["card_badged"] = card.name

    # 2. 虚拟模特素颜自拍（before 图）
    selfie = out_dir / "selfie.png"
    selfie_prompt = SELFIE_PROMPTS.get(mode, SELFIE_PROMPTS["couple"])
    manifest["prompts"]["selfie"] = selfie_prompt
    if selfie.exists() and not force:
        print(f"  selfie.png 已存在，跳过")
    else:
        refs = refs_for(MODELS.get(mode, MODELS["couple"]))
        print(f"  自拍生成中（{mode}，参考{len(refs)}人）...", flush=True)
        urls = img_client.generate_image(
            prompt=selfie_prompt, size="2K", reference_images=refs or None,
            model=img_model, watermark=False)
        img_client.download(urls[0], selfie)
        print(f"  -> selfie.png 完成")
    manifest["files"]["selfie"] = selfie.name

    # 3. 对比拼图（带 AI 角标）
    compare = out_dir / "compare.png"
    if compare.exists() and not force:
        print(f"  compare.png 已存在，跳过")
    else:
        build_compare(selfie, card, title, compare)
        watermark.add_ai_badge(compare, compare)
        print(f"  -> compare.png 完成")
    manifest["files"]["compare"] = compare.name

    # 4. 种草文案（MiniMax M3）
    copy_md = out_dir / "copy.md"
    moments = {m["id"]: m["title"] for m in data.get("moments", [])}
    comp = tpl.get("components", {})
    copy_user = COPY_USER_TMPL.format(
        title=title,
        scene=comp.get("场景", ""), costume=comp.get("服装", ""),
        tags="、".join(s.get("tags", [])), desc=tpl.get("desc", ""),
        moments="、".join(moments.get(m, m) for m in s.get("moments", [])),
    )
    manifest["prompts"]["copy_system"] = COPY_SYSTEM
    manifest["prompts"]["copy_user"] = copy_user
    if copy_md.exists() and not force:
        print(f"  copy.md 已存在，跳过")
    else:
        print(f"  文案生成中（{llm_client.model}）...", flush=True)
        text = strip_think(llm_client.chat(
            COPY_SYSTEM, copy_user, temperature=0.8, max_tokens=4096))
        copy_md.write_text(
            "<!-- AI 生成文案草稿，发布前须人工终审 -->\n\n" + text + "\n", encoding="utf-8")
        manifest["llm_usage"] = llm_client.last_usage
        print(f"  -> copy.md 完成")
    manifest["files"]["copy"] = copy_md.name

    # 5. 留痕
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["files"]["manifest"] = "manifest.json"
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--series", nargs="+", default=[], help="指定系列 id（如 hyd muh）")
    parser.add_argument("--top", type=int, default=0, help="按 hot_base 取 Top N（与 --series 可叠加）")
    parser.add_argument("--force", action="store_true", help="覆盖已有产物重跑")
    args = parser.parse_args()
    if not args.series and args.top <= 0:
        parser.error("需要 --series 或 --top 至少一个")

    config.load_dotenv()
    # 兜底：从 assets/moka 下直接运行时 cwd 不在 toolkit 树下，显式加载 toolkit .env
    config.load_dotenv(ROOT / "tools/luckynemo-toolkit" / ".env")
    data = load_index()
    picked = pick_series(data, args.series, args.top)
    if not picked:
        print("没有选中任何系列，结束。")
        return

    img_client = ark.ArkClient(api_key=config.get_api_key(), timeout=300.0)
    img_model = config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO)
    llm_client = llm.LLMClient(api_key=config.get_minimax_api_key())

    date_dir = datetime.now().strftime("%Y%m%d")
    print(f"选中 {len(picked)} 个系列：{[s['id'] for s in picked]}，输出 promo/{date_dir}/")
    fails = []
    for s in picked:
        out_dir = OUT_ROOT / date_dir / s["id"]
        print(f"[{s['id']}] {s.get('title', '')} 素材包生成中...", flush=True)
        try:
            gen_series_pack(s, data, out_dir, img_client, llm_client, img_model, args.force)
        except Exception as exc:  # noqa: BLE001
            print(f"  !! {s['id']} 失败：{exc}", flush=True)
            fails.append(s["id"])
        time.sleep(2)
    print(f"全部结束。{'失败系列：' + ','.join(fails) if fails else '无失败。'}")


if __name__ == "__main__":
    main()
