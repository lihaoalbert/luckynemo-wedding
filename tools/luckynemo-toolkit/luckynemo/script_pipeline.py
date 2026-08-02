"""脚本管线 CLI：客户故事素材 → LLM 生成分镜脚本（MiniMax M3）。

用法：
    python -m luckynemo.script_pipeline storyboard --template love_story \
        --input templates/story_intake_example.txt --out ./分镜.json [--shots 10] [--dry-run]

生成的分镜 JSON 与 video_pipeline 的分镜 schema 完全一致，可直接接
frames / draft / final / narrate / roughcut 后续工序。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

from . import config
from .config import TOOLKIT_ROOT
from .llm import LLMClient, LLMError
from .video_pipeline import load_storyboard, validate_storyboard

#: 分镜模板目录（与 video_pipeline 共用）
STORYBOARD_DIR = TOOLKIT_ROOT / "templates" / "storyboards"

#: MiniMax-M3 参考单价（元/百万 tokens，官方发布口径 ≤512K 档；
#: 上线促销期可能更低）TODO(校准)：以 MiniMax 官方计费页现行价为准
PRICE_INPUT_PER_MTOK = 4.2
PRICE_OUTPUT_PER_MTOK = 16.8

#: system prompt：资深婚礼短片编剧人设与硬性要求
SYSTEM_PROMPT = """你是一位资深婚礼短片编剧，为 AI 婚庆影像工作室撰写短片分镜脚本。

硬性要求：
1. 镜头画面必须"可拍"：frame_prompt / video_prompt 写具体的场景、人物动作、光线、镜头语言（焦距、景别、运镜），不要写抽象情绪词堆砌（情绪要外化为身体细节：低头、攥紧衣角、眼眶泛红）；视频生成模型要照着它出画面。
2. video_prompt 遵守 I2V 规则：只写首帧画面里没有的东西（动作、运镜、光线变化），动作必须从首帧状态接着演；每镜最多 2-3 个动作节拍，关键情绪节拍至少给 2 秒；一镜一个场景不跳场；双人镜头末尾加"画面中仅这一男一女"，人物镜头加"人物五官与首帧保持一致"。
3. 口型红线：本片旁白为后期克隆音色画外音，凡 narration 是角色现场台词的镜头（求婚、誓词等），video_prompt 禁止出现"说/读/告白/哽咽着说"，改写为"无人说话，用眼神和动作交流"；narration 为回忆讲述时，画面环境性交谈允许保留。
4. 旁白（narration）要口语、真挚、像新人在婚礼现场亲口讲述，避免 AI 腔与套话（禁止"见证幸福""时光荏苒""岁月静好"这类陈词）；用故事素材里的真实细节（地名、物件、习惯、口头禅）。
5. 单镜时长 duration 为 4-15 秒的整数；旁白长度与时长匹配，按每秒约 4-5 个汉字控制（duration×4 ~ duration×5 字）。
6. 情绪（mood）用 2-4 个汉字概括，全片要有起承转合的节奏曲线。
7. 只输出纯 JSON，不要 markdown 围栏、不要任何解释性文字。"""

USER_PROMPT_TEMPLATE = """【结构参照模板】《{template_title}》的完整分镜 JSON 如下，请参照它的镜头数、节奏曲线与字段结构，但内容必须全部来自客户故事素材，不要照抄模板的具体情节：

```json
{template_json}
```

【客户故事素材】
{story}

【本次要求】
- 生成 {shots} 个镜头
- 输出 schema（与模板完全一致）：
  {{"title": 字符串, "shots": [{{"id": 整数（从1连续）, "duration": 整数（4-15秒）, "frame_prompt": 字符串（首帧画面描述）, "video_prompt": 字符串（动态化描述）, "narration": 字符串（旁白）, "mood": 字符串}}]}}
- 只输出纯 JSON"""


def list_templates() -> list[str]:
    """可用的分镜模板名（JSON 文件名去后缀）。"""
    return sorted(p.stem for p in STORYBOARD_DIR.glob("*.json"))


def strip_json_fence(text: str) -> str:
    """清洗 LLM 输出，返回 JSON 子串。

    处理三种实测情况：
    1. MiniMax-M3 是推理模型，输出带 ``<think>...</think>`` 思维链段，先剥掉
       （含被 max_tokens 截断的未闭合 think 段）
    2. 可能的 ```json markdown 围栏
    3. 围栏/思维链之外的前后杂文本（截取第一个 { 到最后一个 }）
    """
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL)  # 截断的未闭合 think
    cleaned = cleaned.strip()
    if cleaned.startswith("```"):
        # 去掉首行 ```json / ``` 与结尾 ```
        lines = cleaned.splitlines()
        lines = lines[1:] if lines else []
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    # 兜底：截取第一个 { 到最后一个 }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start:end + 1]
    return cleaned


def parse_and_validate(raw: str) -> tuple[dict | None, list[str]]:
    """解析 LLM 输出并校验分镜 schema，返回 (分镜, 错误列表)。"""
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as exc:
        return None, [f"JSON 解析失败：{exc}"]
    return data, validate_storyboard(data)


def estimate_cost(usage: dict | None) -> str:
    """按 usage 估算本次调用成本（元）。"""
    if not usage:
        return "（响应无 usage 字段，无法估算）"
    in_tok = usage.get("prompt_tokens", 0)
    out_tok = usage.get("completion_tokens", 0)
    cost = in_tok / 1e6 * PRICE_INPUT_PER_MTOK + out_tok / 1e6 * PRICE_OUTPUT_PER_MTOK
    return (f"输入 {in_tok} / 输出 {out_tok} tokens，"
            f"估算成本 ≈{cost:.4f} 元（按 {PRICE_INPUT_PER_MTOK}/{PRICE_OUTPUT_PER_MTOK} 元每百万 tokens，TODO(校准)）")


def _build_client(args: argparse.Namespace) -> LLMClient:
    """按 --dry-run 构造客户端（dry-run 不需要 API Key）。"""
    if getattr(args, "dry_run", False):
        return LLMClient(dry_run=True)
    return LLMClient(api_key=config.get_minimax_api_key())


def cmd_storyboard(args: argparse.Namespace) -> int:
    """读取模板 + 客户故事素材，调 M3 生成分镜 JSON，校验后写盘。"""
    template_path = STORYBOARD_DIR / f"{args.template}.json"
    template = load_storyboard(template_path)
    story_path = Path(args.input)
    if not story_path.is_file():
        print(f"故事素材文件不存在：{story_path}", file=sys.stderr)
        return 1
    story = story_path.read_text(encoding="utf-8").strip()
    if not story:
        print(f"故事素材为空：{story_path}", file=sys.stderr)
        return 1
    shots = args.shots or len(template["shots"])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        template_title=template.get("title", args.template),
        template_json=json.dumps(template, ensure_ascii=False, indent=2),
        story=story,
        shots=shots,
    )
    out_path = Path(args.out)

    if args.dry_run:
        print("========== [dry-run] system prompt ==========")
        print(SYSTEM_PROMPT)
        print("========== [dry-run] user prompt ==========")
        print(user_prompt)
        print(f"========== [dry-run] 将写输出 -> {out_path}（跳过，不落盘）==========")
        return 0

    client = _build_client(args)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
    # M3 是推理模型，<think> 思维链会占用输出 token 预算，给足余量
    t0 = time.monotonic()
    raw = client.chat_messages(messages, max_tokens=16384)
    data, errors = parse_and_validate(raw)
    if errors:
        # 校验失败：把错误反馈给 LLM 自动重试 1 次
        print(f"首次生成未通过校验（{len(errors)} 个问题），反馈给 LLM 重试 1 次...")
        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": ("上次输出未通过分镜校验，问题如下：\n- " + "\n- ".join(errors)
                        + "\n请修正后重新输出完整的纯 JSON（不要围栏、不要解释）。"),
        })
        raw = client.chat_messages(messages, max_tokens=16384)
        data, errors = parse_and_validate(raw)
    elapsed = time.monotonic() - t0

    if errors:
        print(f"分镜生成失败，重试后仍未通过校验（{len(errors)} 个问题）：", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        print(f"原始输出已保存供排查：{out_path}.raw.txt", file=sys.stderr)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        Path(str(out_path) + ".raw.txt").write_text(raw, encoding="utf-8")
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(s["duration"] for s in data["shots"])
    print(f"分镜生成成功：《{data['title']}》共 {len(data['shots'])} 个镜头，总时长约 {total} 秒。")
    print(f"已写入：{out_path}｜耗时 {elapsed:.1f}s｜{estimate_cost(client.last_usage)}")
    print("下一步：python -m luckynemo.video_pipeline validate " + str(out_path))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器（中文帮助）。"""
    parser = argparse.ArgumentParser(
        prog="python -m luckynemo.script_pipeline",
        description="脚本管线：客户故事素材 → M3 生成分镜脚本（接 video_pipeline 后续工序）",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="子命令")

    p_sb = sub.add_parser("storyboard", help="按模板 + 故事素材生成分镜 JSON")
    p_sb.add_argument("--template", required=True, choices=list_templates(),
                      help="分镜模板名（结构参照，见 templates/storyboards/）")
    p_sb.add_argument("--input", required=True, help="客户故事素材文本文件（txt）")
    p_sb.add_argument("--out", required=True, help="输出分镜 JSON 路径")
    p_sb.add_argument("--shots", type=int, default=None, help="镜头数（默认取模板镜头数）")
    p_sb.add_argument("--dry-run", action="store_true",
                      help="只打印 system/user prompt 全文与输出路径，不请求 API")
    p_sb.set_defaults(func=cmd_storyboard)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (LLMError, RuntimeError, OSError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
