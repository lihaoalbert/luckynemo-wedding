"""MiniMax API 客户端（音乐 / TTS / 声音克隆）。

图片生成已统一走火山 Seedream（:mod:`luckynemo.ark`），MiniMax 图片线
因实测效果不佳已下架；本客户端只保留音乐、TTS、声音克隆能力。
接口规范来自另一项目的生产代码（已验证），实现风格对齐 :mod:`luckynemo.ark`。

====================================================================
已验证接口（Base: https://api.minimaxi.com/v1，Bearer 鉴权）：
- 音乐：POST /music_generation（2026-07-20 按官方文档+实测重写为**同步**接口）
    现行模型：music-3.0（推荐）/ music-2.6 / music-cover 及各自 -free 限免版；
    旧资料里的 music-01 异步任务制（task_id + /query/music 轮询）已被官方下线，
    实测报 "cannot use music-02 params on music-01 model"
    body {"model":"music-3.0","prompt":...,"is_instrumental":true,"output_format":"url",
          "audio_setting":{"sample_rate":44100,"bitrate":256000,"format":"mp3"}}
    → data.audio 即音频 URL（output_format=url；默认 hex 则返回 hex 字符串）；
    data.status=2 表示完成。付费模型不可用时自动降级到 -free 限免版
    注意：官方接口不支持指定时长，长度由模型/歌词决定
- TTS：POST /t2a_v2
    body {"model":"speech-01-turbo","text":...,"stream":false,
          "voice_setting":{"voice_id":...,"speed":1.0,"vol":1.0,"pitch":0,"emotion":...?},
          "audio_setting":{"sample_rate":32000,"bitrate":128000,"format":"mp3"}}
    → data.audio.url 直接下载；或 data.audio 为 hex 字符串，hex 解码后落盘 mp3
- 声音克隆：两步（2026-07-20 真实调用校准）：
    1. POST /files/upload（multipart：file + purpose=voice_clone）→ file_id
    2. POST /voice_clone（form：model="speech-01-turbo" 必须 turbo、file_id、
       可选 voice_id 自定义）→ 成功；自定义 voice_id 时响应不回显，直接用自定义值。
    注意：样本过短会报 voice duration too short（实测 5s 被拒，≥10s 干净人声稳妥）。
====================================================================
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

#: 模型 ID
MUSIC_MODEL = "music-3.0"           # 现行同步接口（music-01 异步制已被官方下线）
MUSIC_MODEL_FALLBACK = "music-3.0-free"  # 付费模型不可用时降级到限免版（RPM 3）
TTS_MODEL = "speech-01-turbo"  # 声音克隆也必须 turbo


class MiniMaxAPIError(RuntimeError):
    """MiniMax API 错误，message 含 HTTP 状态码与响应 body（不含请求头，不泄露 Key）。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        detail = message
        if status_code is not None:
            detail += f"（HTTP {status_code}）"
        if body:
            detail += f"\n响应 body：{body[:2000]}"
        super().__init__(detail)


class MiniMaxClient:
    """MiniMax API 客户端，全部方法支持 dry_run（只打印不请求、不扣费）。"""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = "https://api.minimaxi.com/v1",
        dry_run: bool = False,
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        if not dry_run and not api_key:
            raise ValueError("非 dry-run 模式必须提供 api_key")
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.dry_run = dry_run
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        # 只放鉴权头；Content-Type 按请求类型在 _request 里设置
        # （multipart 必须让 requests 自己生成 boundary）
        self._session.headers.update({"Authorization": f"Bearer {self.api_key}"})

    # ------------------------------------------------------------------
    # 底层请求（3 次指数退避重试；错误不泄露 Key）
    # ------------------------------------------------------------------
    def _log_dry_run(self, method: str, url: str, payload: Any) -> None:
        print(f"[dry-run] {method} {url}")
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    def _check_business_error(self, data: Any, context: str) -> None:
        """MiniMax 常见错误包装 base_resp.status_code != 0 时视为业务错误抛出。"""
        if isinstance(data, dict):
            base_resp = data.get("base_resp")
            if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
                raise MiniMaxAPIError(
                    f"MiniMax 业务错误：{context}",
                    body=json.dumps(data, ensure_ascii=False),
                )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        files: dict | None = None,
        data: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        """发送请求；网络错误重试（指数退避），HTTP ≥400 / 业务错误抛 MiniMaxAPIError。

        :param timeout: 单次请求超时秒数（默认用客户端 timeout；音乐生成等慢接口传更大值）
        """
        url = f"{self.base_url}{path}"
        if self.dry_run:
            shown: Any = json_body
            if files:
                shown = {"form_fields": data or {}, "files": {k: f"<{v[0]} 二进制>" for k, v in files.items()}}
            self._log_dry_run(method, url, shown if shown is not None else params)
            return {"_dry_run": True}

        req_timeout = timeout if timeout is not None else self.timeout
        headers = {"Content-Type": "application/json"} if json_body is not None else None
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.request(
                    method, url, json=json_body, files=files, data=data,
                    params=params, headers=headers, timeout=req_timeout,
                )
            except requests.RequestException as exc:  # 网络层错误才重试
                last_exc = exc
                wait = 2 ** (attempt - 1)
                print(f"[minimax] 网络错误（第 {attempt}/{self.max_retries} 次）：{exc}，{wait}s 后重试")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise MiniMaxAPIError(
                    f"MiniMax API 调用失败：{method} {path}",
                    status_code=resp.status_code,
                    body=resp.text,
                )
            try:
                result = resp.json()
            except ValueError as exc:
                raise MiniMaxAPIError(f"MiniMax 返回非 JSON：{method} {path}", body=resp.text) from exc
            self._check_business_error(result, f"{method} {path}")
            return result
        raise MiniMaxAPIError(f"MiniMax 网络错误，重试 {self.max_retries} 次仍失败：{method} {path}\n{last_exc}")

    # ------------------------------------------------------------------
    # 音乐生成（同步接口，2026-07-20 按官方文档+实测重写）
    # ------------------------------------------------------------------
    def _music_once(self, prompt: str, *, model: str, instrumental: bool,
                    lyrics: str | None) -> str:
        """单次同步生成音乐，返回音频 URL。"""
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "is_instrumental": instrumental,
            "output_format": "url",  # 默认 hex；url 有效期 24h，立即下载
            "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
        }
        if lyrics:
            payload["lyrics"] = lyrics
        # 音乐是同步长任务（实测常超过 60s），单次请求超时放宽到 300s
        result = self._request("POST", "/music_generation", json_body=payload, timeout=300.0)
        data = result.get("data") or {}
        status = data.get("status")
        if status not in (None, 2):  # 官方文档：status=2 表示完成
            raise MiniMaxAPIError(f"音乐生成未完成（status={status}）",
                                  body=json.dumps(result, ensure_ascii=False)[:2000])
        audio = data.get("audio")
        if isinstance(audio, str) and audio:
            return audio
        if isinstance(audio, dict) and audio.get("url"):
            return str(audio["url"])
        raise MiniMaxAPIError("音乐生成成功但未找到音频 URL",
                              body=json.dumps(result, ensure_ascii=False)[:2000])

    def generate_music(self, prompt: str, *, instrumental: bool = True,
                       lyrics: str | None = None, model: str = MUSIC_MODEL) -> str:
        """同步生成音乐，返回音频 URL（有效期 24h，请立即 download）。

        官方接口不支持指定时长，长度由模型/歌词决定。
        付费模型不可用（未开通/权限不足）时自动降级到 -free 限免版。
        """
        if self.dry_run:
            self._log_dry_run("POST", f"{self.base_url}/music_generation", {
                "model": model, "prompt": prompt, "is_instrumental": instrumental,
                "output_format": "url",
                "audio_setting": {"sample_rate": 44100, "bitrate": 256000, "format": "mp3"},
                **({"lyrics": lyrics} if lyrics else {}),
            })
            return ""
        try:
            return self._music_once(prompt, model=model, instrumental=instrumental, lyrics=lyrics)
        except MiniMaxAPIError as exc:
            if model == MUSIC_MODEL:
                print(f"[minimax] 音乐模型 {model} 不可用（{exc}），降级到 {MUSIC_MODEL_FALLBACK}")
                return self._music_once(prompt, model=MUSIC_MODEL_FALLBACK,
                                        instrumental=instrumental, lyrics=lyrics)
            raise

    # ------------------------------------------------------------------
    # TTS（同步）
    # ------------------------------------------------------------------
    def synthesize(
        self,
        text: str,
        out_path: str | Path,
        *,
        voice_id: str = "male-qn-qingse",
        emotion: str | None = None,
        speed: float = 1.0,
        model: str = TTS_MODEL,
    ) -> Path:
        """文本转语音，落盘为本地 mp3，返回文件路径。

        :param speed: 语速 0.5-2.0（MiniMax t2a_v2 支持）；旁白总长超过片长时
            按 总长/片长 换算提速，注意 >1.3 会明显不自然

        响应两种形态都真实处理：
        - ``data.audio`` 为 dict 且含 url → 下载落盘
        - ``data.audio`` 为 hex 字符串 → bytes.fromhex 解码后写 mp3
        """
        voice_setting: dict[str, Any] = {
            "voice_id": voice_id, "speed": speed, "vol": 1.0, "pitch": 0,
        }
        if emotion:
            voice_setting["emotion"] = emotion
        payload = {
            "model": model,
            "text": text,
            "stream": False,
            "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3"},
        }
        dest = Path(out_path)
        if self.dry_run:
            self._log_dry_run("POST", f"{self.base_url}/t2a_v2", payload)
            print(f"[dry-run] TTS 结果落盘 -> {dest}（跳过，不写文件）")
            return dest
        result = self._request("POST", "/t2a_v2", json_body=payload)
        audio = (result.get("data") or {}).get("audio")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(audio, dict) and audio.get("url"):
            self.download(audio["url"], dest)
        elif isinstance(audio, str) and audio:
            # hex 字符串路径：真实解码落盘（不可用占位）
            try:
                dest.write_bytes(bytes.fromhex(audio))
            except ValueError as exc:
                raise MiniMaxAPIError("TTS 返回的 audio 既不是 URL 也不是合法 hex 字符串",
                                      body=audio[:500]) from exc
        else:
            raise MiniMaxAPIError("TTS 响应中未找到音频（data.audio 缺失）",
                                  body=json.dumps(result, ensure_ascii=False)[:2000])
        return dest

    # ------------------------------------------------------------------
    # 声音克隆
    # ------------------------------------------------------------------
    def clone_voice(self, audio_path: str | Path, *, voice_id_hint: str | None = None,
                    model: str = TTS_MODEL) -> str:
        """克隆音色，返回 voice_id。

        实测流程（2026-07-20 真实调用校准）：
        1. ``POST /files/upload``（multipart，purpose=voice_clone）拿到 ``file_id``
           ——直接把文件放 voice_clone 的 multipart ``file`` 字段会报
           ``file_id or audio_url is required``，必须先走上传接口
        2. ``POST /voice_clone``（form 字段：model / file_id / 可选 voice_id）
        3. 自定义 voice_id（hint）成功时响应不回显 voice_id，直接返回 hint；
           不传 hint 时从响应里取系统分配的 voice_id

        :param audio_path: 样本音频（wav/mp3，实测 5s 会报 voice duration too short，
            请用 ≥10s 干净人声）
        :param voice_id_hint: 可选自定义 voice_id
        :param model: 必须 speech-01-turbo（克隆只认 turbo）
        """
        src = Path(audio_path)
        if not src.is_file():
            raise FileNotFoundError(f"样本音频不存在：{src}")
        if self.dry_run:
            self._log_dry_run("POST", f"{self.base_url}/files/upload",
                              {"purpose": "voice_clone", "file": f"<{src.name} 二进制>"})
            self._log_dry_run("POST", f"{self.base_url}/voice_clone",
                              {"model": model, "file_id": "<上传返回>", "voice_id": voice_id_hint})
            return voice_id_hint or "dry-run-voice-id"
        # 1) 上传样本拿 file_id
        with open(src, "rb") as fh:
            up = self._request("POST", "/files/upload",
                               files={"file": (src.name, fh)},
                               data={"purpose": "voice_clone"})
        file_id = (up.get("file") or {}).get("file_id")
        if not file_id:
            raise MiniMaxAPIError("样本上传成功但未返回 file_id", body=json.dumps(up, ensure_ascii=False))
        # 2) 用 file_id 克隆
        form: dict[str, Any] = {"model": model, "file_id": file_id}
        if voice_id_hint:
            form["voice_id"] = voice_id_hint
        result = self._request("POST", "/voice_clone", data=form)
        # 3) 自定义 hint 成功时不回显；否则取系统分配的 voice_id
        voice_id = result.get("voice_id") or (result.get("data") or {}).get("voice_id")
        if not voice_id:
            if voice_id_hint:
                return voice_id_hint
            raise MiniMaxAPIError("声音克隆成功但未返回 voice_id", body=json.dumps(result, ensure_ascii=False))
        return str(voice_id)

    # ------------------------------------------------------------------
    # 下载
    # ------------------------------------------------------------------
    def download(self, url: str, dest: str | Path) -> Path:
        """下载文件到本地，网络错误重试 3 次（指数退避）。"""
        dest_path = Path(dest)
        if self.dry_run:
            print(f"[dry-run] 下载 {url} -> {dest_path}（跳过，不落盘）")
            return dest_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with self._session.get(url, stream=True, timeout=self.timeout) as resp:
                    if resp.status_code >= 400:
                        raise MiniMaxAPIError(f"下载失败：{url}", status_code=resp.status_code,
                                              body=resp.text[:500])
                    with open(dest_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            fh.write(chunk)
                return dest_path
            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** (attempt - 1)
                print(f"[minimax] 下载网络错误（第 {attempt}/{self.max_retries} 次）：{exc}，{wait}s 后重试")
                time.sleep(wait)
        raise MiniMaxAPIError(f"下载失败，重试 {self.max_retries} 次仍失败：{url}\n{last_exc}")
