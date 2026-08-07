"""管线 B：爱情叙事短片 CLI。

流程（2026-08-04 起默认 r2v 范式）：分镜校验 → 分类参考资产（assets：人物/场景/道具）
→ 逐镜生成（Seedance/H3，草稿/定稿）→ ffmpeg 粗剪。首尾帧 i2v 为可选旧模式（--mode i2v）。

用法：
    python -m luckynemo.video_pipeline validate <分镜.json>
    python -m luckynemo.video_pipeline assets <分镜.json> --refs <客户照片目录> --out <资产目录> [--upload] [--dry-run]
    python -m luckynemo.video_pipeline frames <分镜.json> --refs <客户照片目录> --out <首帧目录> [--dry-run]  # 仅 i2v
    python -m luckynemo.video_pipeline draft <分镜.json> --manifest <资产目录/refs_manifest.json> --out <片段目录> [--dry-run]
    python -m luckynemo.video_pipeline final <分镜.json> --manifest <资产目录/refs_manifest.json> --resolution 720p --out <片段目录> [--dry-run]
    python -m luckynemo.video_pipeline roughcut <分镜.json> --clips <片段目录> --audio <旁白配乐.mp3> --out <成片.mp4> [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import ark, config
from . import asset_pipeline
from . import ffmpeg_utils
from . import minimax_client
from .config import TOOLKIT_ROOT

#: 分镜模板目录
STORYBOARD_DIR = TOOLKIT_ROOT / "templates" / "storyboards"
#: 分镜必填字段
SHOT_SCHEMA = {
    "id": int,
    "duration": int,
    "frame_prompt": str,
    "video_prompt": str,
    "narration": str,
    "mood": str,
}
#: 分镜可选资产声明（顶层 assets 块）的三类
ASSET_CATEGORIES = ("characters", "scenes", "props")


#: 人物资产（形象卡）统一版式尾缀（用户规范 2026-08-06）：人=脸+服装+妆容绑定，
#: 换装/换妆即新资产。版式：左脸特写 + 右侧全身三视图，纯白背景 16:9
CHAR_SHEET_LAYOUT = ("，左侧为脸部正面特写，右侧为三视图：正面、侧面、背面全身，"
                     "中等比例，站姿自然；纯白背景，无边框，16:9")
#: 形象卡保持身份一致的提示词尾缀（同 frames 的人物锚定）
CHAR_SHEET_IDENTITY = "，保持与参考图人物五官、脸型完全一致"
#: 人脸三视图身份锚定尾缀（反馈 #26：婚纱照大量侧脸对视，单正脸参考侧脸失真）。
#: 生成方式（2026-08-07 画质实测定稿）：三视角分镜 2K×3 + ffmpeg 横拼，
#: 优于 4.5@4K 单图（发丝/皮肤细节更好、画幅规范），与 server/mp_worker 同源
FACE_SHEET_IDENTITY = ("，保持与参考图人物五官、脸型完全一致，侧脸的鼻梁高度、下颌线、"
                       "耳朵形状严格按侧面参考照还原，不要美化成标准模板脸")


#: 场景资产四宫格规范（用户规范 2026-08-06）：2x2 四宫格，每格 9:16 竖版，
#: 同一空间四个方向关联视图（正面/反打/左立面/右立面），相机 1.6m/35mm，无人物
SCENE_GRID_TEMPLATE = """画面内容：输出一张（2X2）四宫格图片，必须内含4个9:16的竖版画面，每一格画面必须是竖版。四格之间有清晰黑色分割线，四格内容区域彼此相邻，禁止出现分割线以外的额外黑色外框、黑色留边或大块黑色间隔，展示同一空间的四个方向关联视图，四张图来自同一空间布局与同一空间中心点，四个方向全部为正面平视视角，相机高度1.6m，焦距35mm，景别为全景，地面连续一致，材质一致，光线方向一致，不出现人物；
场景特征描述：{desc}
四个视角：
* 左上角正面视角，{front}
* 右上角反打视角，推测出左上角图片的反打镜头，{back}
* 左下角左侧立面视角，主要视觉为{left}，墙面作为画面正面对象正对呈现，立面结构与画面边框完全平行，立面从画面顶部到画面底部连续铺满，立面占画面主要面积大于百分之七十。竖向朝上展示，建筑横向允许被画面裁切，严禁任何纵深方向延伸与前后空间层次，无纵深消失点。画面底部可见地面基线，画面顶部可见顶部结构与天空，纯立面正视全景。
* 右下角右侧立面视角，主要视觉为{right}，墙面作为画面正面对象正对呈现，立面结构与画面边框完全平行，立面从画面顶部到画面底部连续铺满，立面占画面主要面积大于百分之七十。竖向朝上展示，建筑横向允许被画面裁切，严禁任何纵深方向延伸与前后空间层次，无纵深消失点。画面底部可见地面基线，画面顶部可见顶部结构与天空，纯立面正视全景。
图片风格：{style}"""

#: 场景特征描述缺省的四视角写法（views 未显式给出时套用）
SCENE_VIEW_DEFAULTS = {
    "front": "主要视觉为空间向纵深延伸的透视与尽头顶点，纯立面正视全景，画面左侧为左侧立面边缘，画面右侧为右侧立面边缘",
    "back": "主要视觉为空间向相反方向延伸的纵深透视与远景，纯立面正视全景，画面左侧为右侧立面段，画面右侧为左侧立面段",
    "left": "左侧连续立面",
    "right": "右侧连续立面",
}
#: 场景资产缺省图片风格（院线电影写实风）
SCENE_STYLE_DEFAULT = "参考院线电影，真人电影风格，影视大片，真实透视比例，真实皮肤质感，细节清晰不过度锐化"


def build_scene_prompt(spec: dict) -> str:
    """按四宫格规范组装场景资产提示词。

    spec: {"desc": 场景特征描述（含地面/左右立面归属/中心点）,
           "views": {"front"/"back"/"left"/"right": 视角描述（可选，缺省用模板）},
           "style": 图片风格（可选）}
    """
    views = spec.get("views") or {}
    return SCENE_GRID_TEMPLATE.format(
        desc=spec["desc"],
        front=views.get("front") or SCENE_VIEW_DEFAULTS["front"],
        back=views.get("back") or SCENE_VIEW_DEFAULTS["back"],
        left=views.get("left") or SCENE_VIEW_DEFAULTS["left"],
        right=views.get("right") or SCENE_VIEW_DEFAULTS["right"],
        style=spec.get("style") or SCENE_STYLE_DEFAULT,
    )


def validate_assets_block(data: dict) -> list[str]:
    """校验顶层 assets 声明与 shots[].refs 引用（可选块，缺省不报错）。

    assets: {"characters": {名字: "照片文件名" | "gen:提示词" | {"base": 照片文件名, "prompt": 服装妆容描述}},
             "scenes": {名字: "gen:提示词"}, "props": {名字: "gen:提示词"}}
    shots[].refs: {"characters": [名字...], "scene": 名字, "props": [名字...]}

    人物资产规范：人=脸+服装+妆容绑定的形象卡（16:9：左脸特写+右侧全身三视图）。
    dict 形态以 base 照片为身份参考生成形象卡；换装/换妆应声明为新资产。
    """
    errors: list[str] = []
    assets = data.get("assets")
    declared: dict[str, set[str]] = {cat: set() for cat in ASSET_CATEGORIES}
    if assets is None:
        assets = {}
    if not isinstance(assets, dict):
        return ["assets 必须是对象（characters/scenes/props）"]
    for cat, table in assets.items():
        if cat not in ASSET_CATEGORIES:
            errors.append(f"assets.{cat} 不是合法类别（应为 {'/'.join(ASSET_CATEGORIES)}）")
            continue
        if not isinstance(table, dict):
            errors.append(f"assets.{cat} 必须是对象（名字 → 照片文件名 或 gen:提示词）")
            continue
        for name, value in table.items():
            if cat == "characters" and isinstance(value, dict):
                if not isinstance(value.get("base"), str) or not value["base"]:
                    errors.append(f"assets.characters.{name}.base 必须是照片文件名")
                if not isinstance(value.get("prompt"), str) or not value["prompt"]:
                    errors.append(f"assets.characters.{name}.prompt 必须是非空字符串（服装/妆容描述）")
                else:
                    declared[cat].add(name)
                side = value.get("side")
                if side is not None:
                    sides = side if isinstance(side, list) else [side]
                    if not all(isinstance(s, str) and s for s in sides):
                        errors.append(f"assets.characters.{name}.side 必须是照片文件名或文件名列表")
            elif cat == "scenes" and isinstance(value, dict):
                # 四宫格场景规范：{"desc": 特征描述, "views"?: {...}, "style"?: str}
                if not isinstance(value.get("desc"), str) or not value["desc"]:
                    errors.append(f"assets.scenes.{name}.desc 必须是非空字符串（场景特征描述）")
                else:
                    views = value.get("views")
                    if views is not None and not isinstance(views, dict):
                        errors.append(f"assets.scenes.{name}.views 必须是对象（front/back/left/right）")
                    declared[cat].add(name)
            elif not isinstance(value, str) or not value:
                errors.append(f"assets.{cat}.{name} 必须是非空字符串")
            elif cat != "characters" and not value.startswith("gen:"):
                errors.append(f"assets.{cat}.{name} 必须以 gen: 前缀给出生成提示词")
            else:
                declared[cat].add(name)
    for i, shot in enumerate(data.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        refs = shot.get("refs")
        if refs is None:
            continue
        where = f"shots[{i}].refs"
        if not isinstance(refs, dict):
            errors.append(f"{where} 必须是对象（characters/scene/props）")
            continue
        for name in refs.get("characters") or []:
            if name not in declared["characters"]:
                errors.append(f"{where}.characters 引用了未声明的人物资产：{name}")
        scene = refs.get("scene")
        if scene is not None and scene not in declared["scenes"]:
            errors.append(f"{where}.scene 引用了未声明的场景资产：{scene}")
        for name in refs.get("props") or []:
            if name not in declared["props"]:
                errors.append(f"{where}.props 引用了未声明的道具资产：{name}")
    return errors


# ------------------------------------------------------------------
# 分镜加载与校验
# ------------------------------------------------------------------
def load_storyboard(path: str | Path) -> dict:
    """读取分镜 JSON。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"分镜文件不存在：{p}")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def validate_storyboard(data: dict) -> list[str]:
    """校验分镜 schema，返回错误列表（空列表 = 通过）。

    schema: {"title": str, "shots": [{"id": int, "duration": int(4-15),
             "frame_prompt": str, "video_prompt": str, "narration": str, "mood": str}]}
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["分镜必须是 JSON 对象"]
    if not isinstance(data.get("title"), str) or not data["title"]:
        errors.append("缺少 title（字符串）")
    shots = data.get("shots")
    if not isinstance(shots, list) or not shots:
        errors.append("缺少 shots（非空数组）")
        return errors
    seen_ids: set[int] = set()
    for i, shot in enumerate(shots):
        where = f"shots[{i}]"
        if not isinstance(shot, dict):
            errors.append(f"{where} 不是对象")
            continue
        for field, ftype in SHOT_SCHEMA.items():
            if field not in shot:
                errors.append(f"{where} 缺少字段 {field}")
            elif not isinstance(shot[field], ftype) or (ftype is int and isinstance(shot[field], bool)):
                errors.append(f"{where}.{field} 类型应为 {ftype.__name__}")
        shot_id = shot.get("id")
        if isinstance(shot_id, int):
            if shot_id in seen_ids:
                errors.append(f"{where}.id 重复：{shot_id}")
            seen_ids.add(shot_id)
        duration = shot.get("duration")
        if isinstance(duration, int) and not ark.VIDEO_DURATION_RANGE[0] <= duration <= ark.VIDEO_DURATION_RANGE[1]:
            errors.append(f"{where}.duration={duration} 超出 {ark.VIDEO_DURATION_RANGE[0]}-{ark.VIDEO_DURATION_RANGE[1]} 秒")
    errors.extend(validate_assets_block(data))
    return errors


def _sorted_shots(data: dict) -> list[dict]:
    """按镜头 id 排序返回。"""
    return sorted(data["shots"], key=lambda s: s["id"])


def _frame_path(frames_dir: Path, shot_id: int) -> Path:
    """首帧图路径约定：shot_<id:02d>.png。"""
    return frames_dir / f"shot_{shot_id:02d}.png"


def _layout_path(layouts_dir: Path, shot_id: int) -> Path:
    """构图参考图路径约定：shot_<id:02d>.png（layouts 目录）。"""
    return layouts_dir / f"shot_{shot_id:02d}.png"


#: 男性/女性角色关键词（用于识别双人镜头）
_MALE_MARKERS = ("新郎", "男生", "男人", "男孩", "老公", "阿驰", "男士")
_FEMALE_MARKERS = ("新娘", "女生", "女人", "女孩", "老婆", "阿奔", "女士")
#: 泛人物关键词（含长辈等配角）
_PEOPLE_MARKERS = ("他", "她", "妈妈", "爸爸", "母亲", "父亲", "两人", "新郎", "新娘",
                   "男生", "女生", "男人", "女人")


def _load_ref_images(value: str | None) -> list[str]:
    """解析 --refs 人物参考图：逗号分隔的 asset://id 或本地路径/URL。

    真实客户照片建议先 asset_pipeline 入库传 asset://（裸传会被反 Deepfake 概率拦截）；
    本地路径由 ark.to_image_url 自动转 data URL。
    """
    if not value:
        return []
    refs = [item.strip() for item in value.split(",") if item.strip()]
    out: list[str] = []
    for ref in refs:
        if ref.startswith(("asset-",)):
            ref = f"asset://{ref}"
        out.append(ref)
    return out


#: r2v 模式追加的身份锚定约束（人物参考图由 manifest/旧 --char-refs 提供）
_IDENTITY_ANCHOR = "，人物五官脸型严格参照人物参考图，全程保持同一个人，禁止换成模板脸"
#: r2v 模式带场景参考图时追加的场景锚定约束
_SCENE_ANCHOR = "，场景环境与氛围严格参照场景参考图，不要切换到其他场景"
#: r2v 模式带构图参考图（简易图，不含人脸/服装细节）时追加的构图锚定约束
_LAYOUT_ANCHOR = "，最后一张图为构图示意图，仅参考其人物位置、朝向与景别，不参考其画风与内容细节"


def apply_video_constraints(video_prompt: str, *, refs_mode: bool = False) -> str:
    """生成视频前由代码强制追加约束（不依赖 LLM 自觉，见 templates/seedance_prompt_rules.md）。

    - 人物镜头：追加"人物五官与首帧保持一致"（refs_mode 时改为"与参考图保持一致"）
    - 双人镜头：追加"画面中仅这一男一女"（防分身）
    已包含对应约束时不重复追加；纯场景镜头（无人物关键词）不追加。
    """
    text = video_prompt
    has_people = any(k in text for k in _PEOPLE_MARKERS)
    is_couple = ("两人" in text) or (
        any(k in text for k in _MALE_MARKERS) and any(k in text for k in _FEMALE_MARKERS)
    )
    if has_people:
        anchor = "五官与参考图保持一致" if refs_mode else "五官与首帧保持一致"
        if anchor not in text:
            text += f"，人物{anchor}"
    if is_couple and "仅这一男一女" not in text:
        text += "，画面中仅这一男一女"
    return text


# ------------------------------------------------------------------
# 子命令
# ------------------------------------------------------------------
def cmd_validate(args: argparse.Namespace) -> int:
    """校验分镜表 schema。"""
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print(f"分镜校验未通过（{len(errors)} 个问题）：")
        for err in errors:
            print(f"  - {err}")
        return 1
    total = sum(s["duration"] for s in data["shots"])
    print(f"分镜校验通过：《{data['title']}》共 {len(data['shots'])} 个镜头，总时长约 {total} 秒。")
    return 0


def cmd_frames(args: argparse.Namespace) -> int:
    """逐镜头生成首帧图（角色一致性的锚，品控通过后再进视频生成）。

    首帧统一走火山 Seedream。
    """
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = sorted(Path(args.refs).iterdir()) if Path(args.refs).is_dir() else []
    ref_paths = [p for p in refs if p.suffix.lower() in {".jpg", ".jpeg", ".png"}][:10]

    client = _build_client(args)
    # 参考图本地路径由 ark.to_image_url 自动转 data URL，无需先传对象存储
    ref_urls = [str(p.resolve()) for p in ref_paths]
    for shot in _sorted_shots(data):
        prompt = shot["frame_prompt"] + "，保持与参考图人物五官、脸型完全一致"
        dest = _frame_path(out_dir, shot["id"])
        print(f"镜头 {shot['id']:02d} 首帧：{shot['frame_prompt'][:30]}...")
        urls = client.generate_image(
            prompt=prompt, size=args.size, reference_images=ref_urls or None,
            model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
            watermark=False)
        for url in urls or [f"<dry-run-url-shot-{shot['id']}>"]:
            client.download(url, dest)
    print(f"首帧生成完毕 -> {out_dir}。请人工品控锁定首帧后再跑 draft/final。")
    return 0


# ------------------------------------------------------------------
# 分类参考资产（r2v 默认范式：人物/场景/道具资产先生成，再生视频）
# ------------------------------------------------------------------
#: 资产清单文件名（assets 子命令产出，draft/final --manifest 消费）
MANIFEST_NAME = "refs_manifest.json"


def _load_manifest(path: str | Path) -> dict:
    """读取 refs_manifest.json：{"characters": {名字: {"file":..., "asset_id":...?}}, ...}。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    manifest: dict[str, dict] = {cat: dict(raw.get(cat) or {}) for cat in ASSET_CATEGORIES}
    if raw.get("group"):
        manifest["group"] = raw["group"]
    return manifest


def _save_manifest(out_dir: Path, manifest: dict) -> None:
    """写 refs_manifest.json（group 与三类资产平铺）。"""
    payload: dict = {}
    if manifest.get("group"):
        payload["group"] = manifest["group"]
    for cat in ASSET_CATEGORIES:
        if manifest.get(cat):
            payload[cat] = manifest[cat]
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_ref(entry: dict, *, prefer_asset: bool) -> str:
    """取资产引用：ark 且已入库优先 asset://，否则本地文件路径。"""
    if prefer_asset and entry.get("asset_id"):
        asset_id = entry["asset_id"]
        return asset_id if asset_id.startswith("asset://") else f"asset://{asset_id}"
    return str(Path(entry["file"]).resolve())


def cmd_assets(args: argparse.Namespace) -> int:
    """按分镜 assets 声明生成/登记三类参考资产（人物/场景/道具），产出 refs_manifest.json。

    - characters：值以 gen: 开头走 Seedream 生成；否则视为 --refs 目录里的照片文件名，直接登记
    - scenes/props：一律 gen: 提示词走 Seedream（场景自动追加"空镜无人物"）
    - --upload：逐资产入方舟素材库（真实人物资产过反 Deepfake 的正规通道）
    """
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    declared = data.get("assets") or {}
    if not any(declared.get(cat) for cat in ASSET_CATEGORIES):
        print("分镜没有 assets 声明（characters/scenes/props），无需生成资产。", file=sys.stderr)
        return 1
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    refs_dir = Path(args.refs) if args.refs else None
    manifest_path = out_dir / MANIFEST_NAME
    manifest: dict = _load_manifest(manifest_path) if manifest_path.is_file() else {}
    for cat in ASSET_CATEGORIES:
        manifest.setdefault(cat, {})

    client = _build_client(args)
    group_id = args.group or manifest.get("group")
    if args.upload and not group_id:
        if args.dry_run:
            print("[dry-run] 将创建方舟素材组并逐资产入库")
        else:
            group_id = asset_pipeline.create_group(f"film-{data['title'][:20]}")
            manifest["group"] = group_id
    elif group_id:
        manifest["group"] = group_id

    for cat in ASSET_CATEGORIES:
        cat_dir = out_dir / cat
        cat_dir.mkdir(exist_ok=True)
        for name, spec in (declared.get(cat) or {}).items():
            entry = manifest[cat].setdefault(name, {})
            # 人物形象卡：{"base": 照片文件名, "prompt": 服装/妆容描述}
            # ——人=脸+服装+妆容绑定，以 base 照片为身份参考，按统一版式生成 16:9 形象卡
            if cat == "characters" and isinstance(spec, dict):
                if refs_dir is None:
                    print(f"characters/{name} 需要 base 照片但缺 --refs 目录", file=sys.stderr)
                    continue
                base = refs_dir / spec["base"]
                if not base.is_file():
                    print(f"characters/{name} base 照片不存在：{base}", file=sys.stderr)
                    continue
                dest = cat_dir / f"{name}.png"
                if dest.is_file():
                    print(f"characters/{name} 已存在，跳过（断点续跑）。")
                else:
                    prompt = spec["prompt"] + CHAR_SHEET_LAYOUT + CHAR_SHEET_IDENTITY
                    print(f"characters/{name} 形象卡生成：{spec['prompt'][:30]}...（base={base.name}）")
                    urls = client.generate_image(
                        prompt=prompt, size=args.char_size, reference_images=[str(base.resolve())],
                        model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
                        watermark=False)
                    for url in urls or [f"<dry-run-url-characters-{name}>"]:
                        client.download(url, dest)
                entry.update({"file": str(dest), "source": spec})
                # 人脸三视图（可选）：声明 side 侧面原照后生成，只有脸部特写不参考服装，
                # 专治侧脸对视镜头失真（反馈 #26）
                # 生成方式（2026-08-07 画质实测定稿）：三视角分镜 2K×3 + ffmpeg 横拼，
                # 优于 4.5@4K 单图（发丝/皮肤细节更好、画幅规范），与 server/mp_worker 同源
                side = spec.get("side")
                if side:
                    sides = side if isinstance(side, list) else [side]
                    side_paths = []
                    for s in sides:
                        p = refs_dir / s
                        if not p.is_file():
                            print(f"characters/{name} side 照片不存在：{p}", file=sys.stderr)
                            continue
                        side_paths.append(p)
                    face_dest = cat_dir / f"{name}_face.png"
                    if not side_paths:
                        pass
                    elif face_dest.is_file():
                        print(f"characters/{name}_face 已存在，跳过（断点续跑）。")
                    else:
                        view_files = []
                        for tag, view in (("front", "正面脸部特写"), ("left", "左侧脸特写"), ("right", "右侧脸特写")):
                            refs = [base] if tag == "front" else [base] + side_paths
                            prompt = (f"同一人物{view}，只有头部特写，不显示服装与身体，"
                                      f"纯白背景，无边框，竖版" + FACE_SHEET_IDENTITY)
                            vdest = cat_dir / f"{name}_face_{tag}.png"
                            print(f"characters/{name}_face 人脸三视图 {tag} 生成（参考图 {len(refs)} 张）...")
                            urls = client.generate_image(
                                prompt=prompt, size="1440x2560",
                                reference_images=[str(p.resolve()) for p in refs],
                                model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
                                watermark=False)
                            for url in urls or [f"<dry-run-url-characters-{name}-face-{tag}>"]:
                                client.download(url, vdest)
                            view_files.append(vdest)
                        if args.dry_run:
                            print(f"[dry-run] ffmpeg hstack 拼接 3 视角 -> {face_dest}（跳过）")
                        else:
                            cmd = ["ffmpeg", "-y", "-loglevel", "error"]
                            for vf in view_files:
                                cmd += ["-i", str(vf)]
                            cmd += ["-filter_complex", "[0][1][2]hstack=3", str(face_dest)]
                            subprocess.run(cmd, check=True)
                            for vf in view_files:
                                vf.unlink()
                    if side_paths and face_dest.is_file():
                        entry["face_file"] = str(face_dest)
            # 场景四宫格：{"desc": 特征描述, "views"?: {...}, "style"?: str}
            # ——2x2 四宫格同空间四方向关联视图，版式/视角/风格由模板组装
            elif cat == "scenes" and isinstance(spec, dict):
                dest = cat_dir / f"{name}.png"
                if dest.is_file():
                    print(f"scenes/{name} 已存在，跳过（断点续跑）。")
                else:
                    prompt = build_scene_prompt(spec)
                    print(f"scenes/{name} 四宫格生成：{spec['desc'][:30]}...")
                    urls = client.generate_image(
                        prompt=prompt, size=args.scene_size,
                        model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
                        watermark=False)
                    for url in urls or [f"<dry-run-url-scenes-{name}>"]:
                        client.download(url, dest)
                entry.update({"file": str(dest), "source": spec})
            elif isinstance(spec, str) and spec.startswith("gen:"):
                dest = cat_dir / f"{name}.png"
                prompt = spec[len("gen:"):]
                if cat == "scenes" and "无人物" not in prompt:
                    prompt += "，空镜，画面中不要出现人物"
                if cat == "characters":
                    # gen: 人物（无 base 的虚拟人物）同样按形象卡版式
                    prompt += CHAR_SHEET_LAYOUT
                if dest.is_file():
                    print(f"{cat}/{name} 已存在，跳过（断点续跑）。")
                else:
                    print(f"{cat}/{name} 生成：{prompt[:40]}...")
                    size = args.char_size if cat == "characters" else args.size
                    urls = client.generate_image(
                        prompt=prompt, size=size,
                        model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
                        watermark=False)
                    for url in urls or [f"<dry-run-url-{cat}-{name}>"]:
                        client.download(url, dest)
                entry.update({"file": str(dest), "source": spec})
            else:
                if refs_dir is None:
                    print(f"{cat}/{name} 是照片文件名但缺 --refs 目录：{spec}", file=sys.stderr)
                    continue
                src = refs_dir / spec
                if not src.is_file():
                    print(f"{cat}/{name} 照片不存在：{src}", file=sys.stderr)
                    continue
                dest = cat_dir / f"{name}{src.suffix.lower()}"
                if not dest.is_file():
                    shutil.copyfile(src, dest)
                print(f"{cat}/{name} 登记照片：{src.name}")
                entry.update({"file": str(dest), "source": spec})
            if args.upload and entry.get("file") and not entry.get("asset_id"):
                if args.dry_run:
                    print(f"[dry-run] {cat}/{name} 将入库方舟素材库")
                else:
                    entry["asset_id"] = asset_pipeline.upload_asset(
                        group_id, Path(entry["file"]), name=f"{cat}_{name}")
            if args.upload and entry.get("face_file") and not entry.get("face_asset_id"):
                if args.dry_run:
                    print(f"[dry-run] {cat}/{name}_face 将入库方舟素材库")
                else:
                    entry["face_asset_id"] = asset_pipeline.upload_asset(
                        group_id, Path(entry["face_file"]), name=f"{cat}_{name}_face")
            manifest[cat][name] = entry
            _save_manifest(out_dir, manifest)
    print(f"资产准备完毕 -> {out_dir}/{MANIFEST_NAME}。请人工品控资产图后再跑 draft/final。")
    return 0


def _shot_references(shot: dict, manifest: dict, *, prefer_asset: bool) -> tuple[list[str], bool, bool]:
    """按镜头 refs 标签从 manifest 组装参考图列表。

    返回 (参考图列表, 是否含人物资产, 是否含场景资产)。
    人物缺省带全部已声明人物；scene/props 按 refs 标签。
    """
    refs_tag = shot.get("refs") or {}
    characters = manifest.get("characters") or {}
    char_names = refs_tag.get("characters") or list(characters)
    refs: list[str] = []
    for name in char_names:
        entry = characters.get(name)
        if entry:
            refs.append(_manifest_ref(entry, prefer_asset=prefer_asset))
    # 人脸三视图紧随其后（形象卡锁服装身形，人脸三视图锁正/侧脸五官，反馈 #26）
    for name in char_names:
        entry = characters.get(name) or {}
        face_ref = None
        if prefer_asset and entry.get("face_asset_id"):
            fid = entry["face_asset_id"]
            face_ref = fid if fid.startswith("asset://") else f"asset://{fid}"
        elif entry.get("face_file"):
            face_ref = str(Path(entry["face_file"]).resolve())
        if face_ref:
            refs.append(face_ref)
    has_scene = False
    scene_name = refs_tag.get("scene")
    if scene_name and (manifest.get("scenes") or {}).get(scene_name):
        refs.append(_manifest_ref(manifest["scenes"][scene_name], prefer_asset=prefer_asset))
        has_scene = True
    for name in refs_tag.get("props") or []:
        entry = (manifest.get("props") or {}).get(name)
        if entry:
            refs.append(_manifest_ref(entry, prefer_asset=prefer_asset))
    return refs, bool(char_names and characters), has_scene


def _load_frame_assets(path: str | None) -> dict[int, str]:
    """读取首帧入库映射（assets_registry.json），返回 {镜头号: asset://id}。

    真人/拟真人首帧裸传会被反 Deepfake 按图拦截，先入方舟素材库再引用可过审。
    兼容两种 JSON 形态：{"frames": {"shot_01": "asset-xxx"}} 或 {"shot_01": "asset-xxx"}。
    """
    if not path:
        return {}
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    table = raw.get("frames", raw)
    out: dict[int, str] = {}
    for key, value in table.items():
        m = re.fullmatch(r"shot_(\d+)", str(key))
        if m and isinstance(value, str):
            out[int(m.group(1))] = value if value.startswith("asset://") else f"asset://{value}"
    return out


#: MiniMax H3 分辨率映射（方舟档位 → H3 仅 768P/2K 两档）
_MINIMAX_RESOLUTION = {"480p": "768P", "720p": "768P", "1080p": "2K", "4K": "2K"}


def _run_seedance(args: argparse.Namespace, *, model: str, label: str) -> int:
    """draft/final 共用：逐镜创建视频任务并轮询下载（--provider 选方舟 Seedance 或 MiniMax H3）。"""
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    provider = getattr(args, "provider", "ark")
    is_minimax = provider == "minimax"
    client = _build_client(args)
    if is_minimax:
        model = config.get_model("MINIMAX_VIDEO_MODEL", minimax_client.VIDEO_MODEL)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = getattr(args, "mode", "r2v")
    legacy_refs = _load_ref_images(getattr(args, "char_refs", None))
    if is_minimax:
        # asset:// 是方舟私域素材库，MiniMax 不认识；MiniMax 走本地路径（自动转 data URL）
        legacy_refs = [r for r in legacy_refs if not r.startswith("asset://")]
        if getattr(args, "char_refs", None):
            print("[minimax] 注意：asset:// 素材仅方舟可用，--char-refs 请传本地路径/公网 URL")

    # ---- r2v（默认）：分类资产 manifest 组装参考图，不用首尾帧 ----
    # ---- i2v（旧模式）：首帧 frames 目录 + 可选 --assets 入库映射 ----
    manifest: dict = {}
    frame_assets: dict[int, str] = {}
    frames_dir: Path | None = None
    if mode == "r2v":
        if not getattr(args, "manifest", None) and not legacy_refs:
            print("r2v 模式需要 --manifest refs_manifest.json（先跑 assets 子命令）", file=sys.stderr)
            return 1
        if getattr(args, "manifest", None):
            manifest = _load_manifest(args.manifest)
    else:
        if not getattr(args, "frames", None):
            print("i2v 模式需要 --frames 首帧目录", file=sys.stderr)
            return 1
        frames_dir = Path(args.frames)
        frame_assets = _load_frame_assets(getattr(args, "assets", None))
        if is_minimax:
            frame_assets = {}
            if getattr(args, "assets", None):
                print("[minimax] 注意：asset:// 素材仅方舟可用，已改用本地首帧图")

    for shot in _sorted_shots(data):
        dest = out_dir / f"shot_{shot['id']:02d}.mp4"
        if dest.is_file() and not args.dry_run:
            print(f"镜头 {shot['id']:02d} 片段已存在，跳过（断点续跑）。")
            continue
        if mode == "r2v":
            references, has_chars, has_scene = _shot_references(
                shot, manifest, prefer_asset=not is_minimax)
            references += legacy_refs
            # 构图参考（简易图，不含人脸/服装细节）：--layouts 目录下按 shot_<id>.png 约定
            has_layout = False
            layout = _layout_path(Path(args.layouts), shot["id"]) if getattr(args, "layouts", None) else None
            if layout and layout.is_file():
                references.append(str(layout.resolve()))
                has_layout = True
            if not references and not args.dry_run:
                print(f"镜头 {shot['id']:02d} 无可用参考资产（检查 --manifest 与 refs 标签），跳过。", file=sys.stderr)
                continue
            first_frame = None
            prompt = apply_video_constraints(shot["video_prompt"], refs_mode=True)
            if has_chars and any(k in prompt for k in _PEOPLE_MARKERS) and "严格参照人物参考图" not in prompt:
                prompt += _IDENTITY_ANCHOR
            if has_scene and "严格参照场景参考图" not in prompt:
                prompt += _SCENE_ANCHOR
            if has_layout and "构图示意图" not in prompt:
                prompt += _LAYOUT_ANCHOR
        else:
            assert frames_dir is not None
            frame = _frame_path(frames_dir, shot["id"])
            asset_url = frame_assets.get(shot["id"])
            if not frame.is_file() and not asset_url and not args.dry_run:
                print(f"镜头 {shot['id']:02d} 缺首帧图：{frame}，跳过。", file=sys.stderr)
                continue
            # 首帧：优先 asset://（入库过反 Deepfake）；本地路径由客户端自动转 data URL
            first_frame = asset_url or str(frame.resolve())
            references = None
            prompt = apply_video_constraints(shot["video_prompt"])
        print(f"镜头 {shot['id']:02d}（{shot['duration']}s，{label}）：{shot['video_prompt'][:30]}...")
        try:
            if is_minimax:
                task_id = client.create_video_task(
                    model=model,
                    text=prompt,
                    first_frame=first_frame,
                    reference_images=references,
                    duration=shot["duration"],
                    resolution=_MINIMAX_RESOLUTION.get(args.resolution, "768P"),
                    ratio=args.ratio,
                )
                task = client.poll_video_task(task_id)
            else:
                task_id = client.create_video_task(
                    model=model,
                    text=prompt,
                    first_frame=first_frame,
                    reference_images=references,
                    duration=shot["duration"],
                    resolution=args.resolution,
                    ratio=args.ratio,
                    generate_audio=False,  # 配音单独做（豆包 TTS），可控性更高
                    return_last_frame=True,  # 方便首尾帧接龙
                )
                task = client.poll_task(task_id)
        except (ark.ArkAPIError, minimax_client.MiniMaxAPIError, RuntimeError) as exc:
            # 单镜失败（常见：输出审核误伤）不中断整批，记录后断点续跑可补
            print(f"镜头 {shot['id']:02d} 生成失败：{exc}。跳过，可断点续跑补镜。", file=sys.stderr)
            continue
        if args.dry_run:
            url = "<dry-run-video-url>"
        elif is_minimax:
            url = minimax_client.MiniMaxClient.extract_video_url(task)
        else:
            url = ark.ArkClient.extract_video_url(task)
        client.download(url, dest)
    print(f"{label}片段生成完毕 -> {out_dir}")
    return 0


def cmd_draft(args: argparse.Namespace) -> int:
    """用 Mini 模型出草稿（约 0.5 元/秒，仅 720p），确认后再用 final 出定稿。"""
    args.resolution = "720p"  # Mini 仅支持 720p
    return _run_seedance(args, model=config.get_model("SEEDANCE_MODEL_DRAFT", ark.SEEDANCE_2_MINI), label="Mini 草稿")


def cmd_final(args: argparse.Namespace) -> int:
    """用标准版出定稿（约 0.95 元/秒）。"""
    return _run_seedance(args, model=config.get_model("SEEDANCE_MODEL_FINAL", ark.SEEDANCE_2_STD), label="标准版定稿")


#: 构图参考（layouts）剪影转换提示词（2026-08-06 实验定稿：剪影版胜出线稿版）
#: 从首帧图编辑转换——人物变无五官无服装细节的剪影，场景只留色块光线，构图零偏差
LAYOUT_SILHOUETTE_PROMPT = ("把这张照片中的人物替换为无五官、无服装细节的纯灰色剪影，"
                            "场景与物体只保留大色块和光线方向，去除所有纹理与材质细节，"
                            "整体变成极简构图示意图，保持原图构图、人物位置与姿态完全不变")


def cmd_layouts(args: argparse.Namespace) -> int:
    """逐镜把首帧图转成剪影构图参考图（layouts 目录，draft/final --layouts 消费）。

    构图参考只用简易图（不含人脸/服装细节，防污染画面）；2026-08-06 双路线实验：
    剪影版（首帧转剪影）构图零偏差且不会引入多余人物，胜出线稿版，定为规范。
    """
    data = load_storyboard(args.storyboard)
    errors = validate_storyboard(data)
    if errors:
        print("分镜校验未通过，请先 validate：\n  - " + "\n  - ".join(errors), file=sys.stderr)
        return 1
    frames_dir = Path(args.frames)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    client = _build_client(args)
    for shot in _sorted_shots(data):
        frame = _frame_path(frames_dir, shot["id"])
        dest = _layout_path(out_dir, shot["id"])
        if dest.is_file():
            print(f"镜头 {shot['id']:02d} 构图剪影已存在，跳过（断点续跑）。")
            continue
        if not frame.is_file():
            print(f"镜头 {shot['id']:02d} 缺首帧图：{frame}，跳过。", file=sys.stderr)
            continue
        print(f"镜头 {shot['id']:02d} 构图剪影：{shot['frame_prompt'][:30]}...")
        urls = client.generate_image(
            prompt=LAYOUT_SILHOUETTE_PROMPT, size=args.size, reference_images=[str(frame.resolve())],
            model=config.get_model("SEEDREAM_MODEL", ark.SEEDREAM_5_PRO),
            watermark=False)
        for url in urls or [f"<dry-run-url-layout-{shot['id']}>"]:
            client.download(url, dest)
    print(f"构图参考生成完毕 -> {out_dir}（draft/final 加 --layouts 使用）。")
    return 0


def cmd_roughcut(args: argparse.Namespace) -> int:
    """ffmpeg 按分镜顺序拼接片段 + 旁白（+ 可选 BGM 混流），输出粗剪成片。"""
    data = load_storyboard(args.storyboard)
    clips_dir = Path(args.clips)
    clips = [clips_dir / f"shot_{shot['id']:02d}.mp4" for shot in _sorted_shots(data)]
    missing = [str(c) for c in clips if not c.is_file()]
    if args.dry_run:
        print(f"[dry-run] 粗剪：按分镜顺序拼接 {len(clips)} 个片段 -> {args.out}")
        if missing:
            print(f"[dry-run] 注意：以下片段当前不存在（真实执行会失败）：{missing}")
        print(f"[dry-run] 旁白音轨：{args.audio or '无'}｜BGM：{args.bgm or '无'}（混流时旁白 1.0 / BGM 0.25）")
        return 0
    if missing:
        print(f"缺少片段：{missing}，请先跑 draft/final。", file=sys.stderr)
        return 1
    out = ffmpeg_utils.concat_segments(clips, args.out, audio=args.audio, bgm=args.bgm)
    print(f"粗剪完成：{out}")
    print("提醒：对外交付前必须走 delivery.py 加片尾 AI 标识卡（≥2 秒）。")
    return 0


def _build_client(args: argparse.Namespace):
    """按 --provider/--dry-run 构造客户端（dry-run 不需要 API Key）。"""
    provider = getattr(args, "provider", "ark")
    dry_run = getattr(args, "dry_run", False)
    if provider == "minimax":
        if dry_run:
            return minimax_client.MiniMaxClient(dry_run=True)
        config.load_dotenv()
        return minimax_client.MiniMaxClient(
            api_key=config.get_minimax_api_key(),
            base_url=config.get_minimax_base_url(),
            timeout=300.0,
        )
    if dry_run:
        return ark.ArkClient(dry_run=True)
    config.load_dotenv()
    return ark.ArkClient(api_key=config.get_api_key())


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.video_pipeline",
        description="管线 B：爱情叙事短片（分镜 → 首帧 → 逐镜生成 → 粗剪）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_val = sub.add_parser("validate", help="校验分镜 JSON 的 schema")
    p_val.add_argument("storyboard", help=f"分镜 JSON 路径（模板见 {STORYBOARD_DIR}）")
    p_val.set_defaults(func=cmd_validate)

    p_frames = sub.add_parser("frames", help="逐镜头生成首帧图（火山 Seedream；i2v 旧模式用）")
    p_frames.add_argument("storyboard", help="分镜 JSON 路径")
    p_frames.add_argument("--refs", required=True, help="客户照片目录（角色一致性参考）")
    p_frames.add_argument("--out", required=True, help="首帧输出目录")
    p_frames.add_argument("--size", default="2K",
                          help="首帧尺寸（默认 2K；竖屏婚照电影用 1440x2560，接口拒绝时回退 2K）")
    p_frames.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_frames.set_defaults(func=cmd_frames)

    p_assets = sub.add_parser("assets", help="生成分类参考资产（人物/场景/道具 → refs_manifest.json，r2v 前置）")
    p_assets.add_argument("storyboard", help="分镜 JSON 路径（需含顶层 assets 声明）")
    p_assets.add_argument("--refs", default=None, help="客户照片目录（characters 声明照片文件名时必填）")
    p_assets.add_argument("--out", required=True, help="资产输出目录（含 refs_manifest.json）")
    p_assets.add_argument("--size", default="2K", help="生成资产图尺寸（默认 2K）")
    p_assets.add_argument("--char-size", dest="char_size", default="2560x1440",
                          help="人物形象卡尺寸（默认 2560x1440 横版 16:9）")
    p_assets.add_argument("--scene-size", dest="scene_size", default="1440x2560",
                          help="场景四宫格尺寸（默认 1440x2560 竖版 = 2x2 个 9:16 竖格；勿超 Seedream 462万像素上限）")
    p_assets.add_argument("--upload", action="store_true",
                          help="逐资产入方舟素材库（真实人物资产过反 Deepfake 的正规通道）")
    p_assets.add_argument("--group", default=None, help="已有素材组 ID（不传则新建组）")
    p_assets.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_assets.set_defaults(func=cmd_assets)

    p_layouts = sub.add_parser("layouts", help="逐镜把首帧图转成剪影构图参考图（防污染的简易图，draft/final --layouts 消费）")
    p_layouts.add_argument("storyboard", help="分镜 JSON 路径")
    p_layouts.add_argument("--frames", required=True, help="首帧目录（frames 子命令的输出）")
    p_layouts.add_argument("--out", required=True, help="构图参考输出目录")
    p_layouts.add_argument("--size", default="1440x2560", help="构图参考尺寸（默认 1440x2560 竖版）")
    p_layouts.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_layouts.set_defaults(func=cmd_layouts)

    p_draft = sub.add_parser("draft", help="用 Mini 模型逐镜生成草稿（约 0.5 元/秒，仅 720p）")
    p_draft.add_argument("storyboard", help="分镜 JSON 路径")
    p_draft.add_argument("--provider", default="ark", choices=["ark", "minimax"],
                         help="视频引擎：ark=火山 Seedance（默认）；minimax=MiniMax-H3（V2 接口）")
    p_draft.add_argument("--mode", default="r2v", choices=["r2v", "i2v"],
                         help="生成模式：r2v=多模态参考生视频（默认，需 --manifest）；i2v=首帧模式（需 --frames）")
    p_draft.add_argument("--manifest", default=None,
                         help="分类资产清单 refs_manifest.json（assets 子命令产出；r2v 模式必填）")
    p_draft.add_argument("--frames", default=None, help="首帧目录（frames 子命令的输出；仅 i2v 模式）")
    p_draft.add_argument("--out", required=True, help="片段输出目录")
    p_draft.add_argument("--ratio", default="16:9", choices=["16:9", "9:16", "1:1", "4:3", "3:4"],
                         help="画面比例（默认 16:9；竖屏婚照电影用 9:16）")
    p_draft.add_argument("--assets", default=None,
                         help="首帧入库映射 assets_registry.json（仅 i2v 模式，asset:// 首帧过反 Deepfake）")
    p_draft.add_argument("--char-refs", dest="char_refs", default=None,
                         help="（旧版兼容）额外人物参考图，逗号分隔 asset://id 或本地路径，追加进 r2v 参考列表")
    p_draft.add_argument("--layouts", default=None,
                         help="构图参考目录（r2v 模式，shot_XX.png 简易构图示意图，仅传递人物位置/景别）")
    p_draft.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_draft.set_defaults(func=cmd_draft)

    p_final = sub.add_parser("final", help="用标准版逐镜生成定稿（约 0.95 元/秒）")
    p_final.add_argument("storyboard", help="分镜 JSON 路径")
    p_final.add_argument("--provider", default="ark", choices=["ark", "minimax"],
                         help="视频引擎：ark=火山 Seedance（默认）；minimax=MiniMax-H3（V2 接口）")
    p_final.add_argument("--mode", default="r2v", choices=["r2v", "i2v"],
                         help="生成模式：r2v=多模态参考生视频（默认，需 --manifest）；i2v=首帧模式（需 --frames）")
    p_final.add_argument("--manifest", default=None,
                         help="分类资产清单 refs_manifest.json（assets 子命令产出；r2v 模式必填）")
    p_final.add_argument("--frames", default=None, help="首帧目录（frames 子命令的输出；仅 i2v 模式）")
    p_final.add_argument("--resolution", default="720p", choices=["480p", "720p", "1080p", "4K"],
                         help="分辨率（默认 720p；4K 仅标准版；MiniMax 自动映射 768P/2K）")
    p_final.add_argument("--out", required=True, help="片段输出目录")
    p_final.add_argument("--ratio", default="16:9", choices=["16:9", "9:16", "1:1", "4:3", "3:4"],
                         help="画面比例（默认 16:9；竖屏婚照电影用 9:16）")
    p_final.add_argument("--assets", default=None,
                         help="首帧入库映射 assets_registry.json（仅 i2v 模式，asset:// 首帧过反 Deepfake）")
    p_final.add_argument("--char-refs", dest="char_refs", default=None,
                         help="（旧版兼容）额外人物参考图，逗号分隔 asset://id 或本地路径，追加进 r2v 参考列表")
    p_final.add_argument("--layouts", default=None,
                         help="构图参考目录（r2v 模式，shot_XX.png 简易构图示意图，仅传递人物位置/景别）")
    p_final.add_argument("--dry-run", action="store_true", help="只打印将执行的 API 调用，不真正请求/扣费")
    p_final.set_defaults(func=cmd_final)

    p_cut = sub.add_parser("roughcut", help="ffmpeg 按分镜顺序拼接 + 旁白/BGM 混流，输出粗剪成片")
    p_cut.add_argument("storyboard", help="分镜 JSON 路径")
    p_cut.add_argument("--clips", required=True, help="片段目录（draft/final 的输出）")
    p_cut.add_argument("--audio", default=None, help="旁白音频文件（可选）")
    p_cut.add_argument("--bgm", default=None, help="背景音乐文件（可选，与旁白 amix 混流：旁白 1.0 / BGM 0.25）")
    p_cut.add_argument("--out", required=True, help="成片输出路径（mp4）")
    p_cut.add_argument("--dry-run", action="store_true", help="只打印将执行的 ffmpeg 命令，不真正执行")
    p_cut.set_defaults(func=cmd_roughcut)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ark.ArkAPIError, ffmpeg_utils.FFmpegNotFoundError, RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
