"""环境配置：读取 .env / 环境变量。

约定：
- API Key 只从环境变量 ``ARK_API_KEY`` 取（.env 文件会在加载时注入环境变量）。
- 不在任何代码、日志、dry-run 输出里打印 Key 本体。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 环境变量名
ENV_API_KEY = "ARK_API_KEY"
ENV_BASE_URL = "ARK_BASE_URL"
#: MiniMax（音乐/TTS/声音克隆/分镜脚本）
ENV_MINIMAX_API_KEY = "MINIMAX_API_KEY"
ENV_MINIMAX_BASE_URL = "MINIMAX_BASE_URL"
DEFAULT_MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"

#: 项目根目录（tools/luckynemo-toolkit/）
TOOLKIT_ROOT = Path(__file__).resolve().parent.parent


def find_env_file(start: Path | None = None) -> Path | None:
    """从 ``start``（默认当前目录）向上查找 .env 文件，找不到返回 None。"""
    cur = (start or Path.cwd()).resolve()
    for directory in [cur, *cur.parents]:
        candidate = directory / ".env"
        if candidate.is_file():
            return candidate
    return None


def load_dotenv(path: Path | None = None) -> Path | None:
    """加载 .env 文件到环境变量（不覆盖已存在的变量）。

    只做最简解析：``KEY=VALUE`` 行，忽略空行与 ``#`` 注释，
    去掉值两端的空白与成对引号。返回实际加载的文件路径。
    """
    env_path = path or find_env_file()
    if env_path is None:
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return env_path


def get_api_key() -> str:
    """获取方舟 API Key；未配置时抛出带操作指引的异常。"""
    load_dotenv()
    key = os.environ.get(ENV_API_KEY, "").strip()
    if not key:
        raise RuntimeError(
            f"未配置 {ENV_API_KEY}。请在 tools/luckynemo-toolkit/ 下复制 "
            f".env.example 为 .env 并填入你的火山引擎方舟 API Key，"
            f"或直接 export {ENV_API_KEY}=<your-key>。"
            f"（--dry-run 模式不需要 Key）"
        )
    return key


def get_minimax_api_key() -> str:
    """获取 MiniMax API Key；未配置时抛出带操作指引的异常。"""
    load_dotenv()
    key = os.environ.get(ENV_MINIMAX_API_KEY, "").strip()
    if not key:
        raise RuntimeError(
            f"未配置 {ENV_MINIMAX_API_KEY}。请在 .env 中填入 MiniMax API Key，"
            f"或直接 export {ENV_MINIMAX_API_KEY}=<your-key>。"
            f"（--dry-run 模式不需要 Key）"
        )
    return key


def get_minimax_base_url() -> str:
    """获取 MiniMax Base URL；未配置时用默认 https://api.minimaxi.com/v1。"""
    load_dotenv()
    return os.environ.get(ENV_MINIMAX_BASE_URL, "").strip() or DEFAULT_MINIMAX_BASE_URL


def get_model(env_name: str, default: str) -> str:
    """读取模型/端点覆盖配置。

    企业账号常按端点 ID（ep-*）调用而非裸模型 ID（doubao-*），
    各管线默认模型可用环境变量覆盖：
    ``SEEDREAM_MODEL`` / ``SEEDANCE_MODEL_DRAFT`` / ``SEEDANCE_MODEL_FINAL``。
    """
    load_dotenv()
    return os.environ.get(env_name, "").strip() or default
