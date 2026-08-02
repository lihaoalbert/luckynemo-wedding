"""MiniMax 大模型（M3）客户端，走 OpenAI 兼容接口。

已验证事实（另一项目生产代码确认，2026-07）：
- POST {MINIMAX_BASE_URL}/chat/completions（默认 https://api.minimaxi.com/v1）
- 鉴权 Header ``Authorization: Bearer $MINIMAX_API_KEY``
- model 默认 ``MiniMax-M3``，可用环境变量 ``MINIMAX_LLM_MODEL`` 覆盖
- body 标准 OpenAI 格式：messages[]、temperature、max_tokens
- 响应取 choices[0].message.content；token 用量在 usage 字段
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import requests

from . import config

DEFAULT_LLM_MODEL = "MiniMax-M3"
ENV_LLM_MODEL = "MINIMAX_LLM_MODEL"


class LLMError(RuntimeError):
    """LLM API 错误，message 含 HTTP 状态码与响应 body（不含请求头，不泄露 Key）。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        detail = message
        if status_code is not None:
            detail += f"（HTTP {status_code}）"
        if body:
            detail += f"\n响应 body：{body[:2000]}"
        super().__init__(detail)


class LLMClient:
    """MiniMax M3 对话客户端（OpenAI 兼容），支持 dry_run（只打印不请求、不扣费）。"""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        dry_run: bool = False,
        timeout: float = 600.0,
        max_retries: int = 3,
    ) -> None:
        if not dry_run and not api_key:
            raise ValueError("非 dry-run 模式必须提供 api_key")
        self.api_key = api_key or ""
        self.base_url = (base_url or config.get_minimax_base_url()).rstrip("/")
        config.load_dotenv()
        self.model = model or os.environ.get(ENV_LLM_MODEL, "").strip() or DEFAULT_LLM_MODEL
        self.dry_run = dry_run
        self.timeout = timeout
        self.max_retries = max_retries
        #: 最近一次真实调用的 usage 字段（{"prompt_tokens":…,"completion_tokens":…,"total_tokens":…}）
        self.last_usage: dict[str, Any] | None = None
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # 底层请求（3 次指数退避重试；错误不泄露 Key）
    # ------------------------------------------------------------------
    def _log_dry_run(self, url: str, payload: dict) -> None:
        print(f"[dry-run] POST {url}")
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        if self.dry_run:
            self._log_dry_run(url, payload)
            return {"_dry_run": True}
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.post(url, json=payload, timeout=self.timeout)
            except requests.RequestException as exc:  # 网络层错误才重试
                last_exc = exc
                wait = 2 ** (attempt - 1)
                print(f"[llm] 网络错误（第 {attempt}/{self.max_retries} 次）：{exc}，{wait}s 后重试")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise LLMError("MiniMax LLM 调用失败", status_code=resp.status_code, body=resp.text)
            try:
                return resp.json()
            except ValueError as exc:
                raise LLMError("MiniMax LLM 返回非 JSON", body=resp.text) from exc
        raise LLMError(f"MiniMax LLM 网络错误，重试 {self.max_retries} 次仍失败\n{last_exc}")

    # ------------------------------------------------------------------
    # 对话
    # ------------------------------------------------------------------
    def chat_messages(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """多轮消息对话，返回 assistant 文本。

        :param messages: OpenAI 格式 [{"role": "system"/"user"/"assistant", "content": str}]
        :param json_mode: True 时加 response_format=json_object（兼容性未经实测，
            分镜生成目前靠 prompt 约束 + 围栏剥离，未启用此参数）
        """
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}  # TODO(校准)：兼容性未实测
        result = self._post(payload)
        if self.dry_run:
            self.last_usage = None
            return ""
        self.last_usage = result.get("usage")
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("MiniMax LLM 响应中未找到 choices[0].message.content",
                           body=json.dumps(result, ensure_ascii=False)[:2000]) from exc
        return str(content)

    def chat(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """单轮 system + user 对话，返回 assistant 文本。

        注意：MiniMax-M3 是推理模型，返回内容可能以 ``<think>...</think>``
        思维链开头，且思维链占用 max_tokens 预算；需要纯 JSON 的调用方请
        自行剥离 think 段（参考 script_pipeline.strip_json_fence）并留足 token 余量。
        """
        return self.chat_messages(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )
