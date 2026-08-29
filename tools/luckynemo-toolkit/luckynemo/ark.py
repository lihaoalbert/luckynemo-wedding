"""火山引擎方舟（Ark）API 客户端。

====================================================================
【校准说明】全项目唯一的 API 封装层。
所有 endpoint、模型 ID、payload 构造集中在本模块，管线里禁止硬编码。
视频侧（Seedance）payload 已与 KidsAI 项目实测代码交叉校准（2026-07-20）。
图片侧（Seedream）以下细节仍待首次真实调用校准，标了 ``TODO(校准)``：
  1. 图片生成参考图字段名（这里用 ``image`` 传 URL 列表，OpenAI Images 风格）。
  2. 图片 ``size`` 是否接受 "1K"/"2K" 字样还是必须 "2048x2048" 像素串。
====================================================================

已核实事实（2026-07 调研 + KidsAI 项目 video_adapter.rs 实测代码交叉确认）：
- 鉴权：Header ``Authorization: Bearer $ARK_API_KEY``
- 图片：POST /api/v3/images/generations，返回图片 URL（24 小时有效，需及时下载）
- 视频：POST /api/v3/contents/generations/tasks 创建异步任务，
  GET /api/v3/contents/generations/tasks/{id} 轮询。
  【已确认】创建响应取 ``id``；状态枚举 queued/running/succeeded/failed/cancelled；
  成片取 ``content.video_url``；封面取 ``content.last_frame_url`` / ``cover_image_url``
- 图片/视频的 image_url 均支持 http(s) URL 与 ``data:`` base64 内联（KidsAI 实测），
  本地客户照片无需先传对象存储，本模块自动转 data URL
- 图片 watermark 默认 true；视频 watermark 默认 false（合规标识由 delivery.py 兜底）
- model 字段同时接受模型 ID（doubao-*）与企业端点 ID（ep-*）
"""

from __future__ import annotations

import base64
import json
import mimetypes
import time
from pathlib import Path
from typing import Any

import requests


def to_image_url(value: str) -> str:
    """把本地图片路径转成 data URL；http(s)/data: 开头的原样返回。

    方舟 image_url 支持 data:base64 内联（KidsAI 实测确认），客户本地照片
    走这个通道即可做参考图/首帧，无需先传对象存储拿公网 URL。
    """
    if value.startswith(("http://", "https://", "data:", "asset://")):
        return value
    path = Path(value)
    if not path.is_file():
        raise FileNotFoundError(f"参考图既不是 URL 也不是存在的本地文件：{value}")
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"

# ------------------------------------------------------------------
# 模型 ID（已核实，2026-07）
# ------------------------------------------------------------------
#: Seedream 5.0 Pro：主用图片模型。参考图 ≤10 张，1K/2K。0.30 元/张（≤236 万像素），更大 0.60 元/张
SEEDREAM_5_PRO = "doubao-seedream-5-0-pro-260628"
#: Seedream 4.5：备选，0.25 元/张，支持 4K
SEEDREAM_4_5 = "doubao-seedream-4-5-251128"
#: Seedream 5.0 Lite：0.22 元/张
SEEDREAM_5_LITE = "doubao-seedream-5-0-lite-260128"

#: Seedance 2.0 标准版：唯一支持 4K，≈0.95 元/秒。定稿用
SEEDANCE_2_STD = "doubao-seedance-2-0-260128"
#: Seedance 2.0 Fast：无 1080p
SEEDANCE_2_FAST = "doubao-seedance-2-0-fast-260128"
#: Seedance 2.0 Mini：仅 720p，≈0.5 元/秒。草稿用（ID 经 KidsAI 项目实测确认）
SEEDANCE_2_MINI = "doubao-seedance-2-0-mini-260615"
#: Seedance 2.5：2026-08-12 ifocus 通道开放（1001 项目已验证，doubao-seedance-2-5-260628）。
#: 仅 720p；时长 ≤30s（duration=-1 模型自动）；全能参考 50 槽（30 图+10 视频+10 音频）；
#: 新增 reference_video / reference_audio 角色与 omni_reference_task_type（edit/extend）
SEEDANCE_2_5 = "doubao-seedance-2-5-260628"

DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com"

#: 视频单条时长合法范围（秒）；2.5 上限 30s 且支持 -1（模型自动时长）
VIDEO_DURATION_RANGE = (4, 15)
VIDEO_DURATION_RANGE_2_5 = (4, 30)

#: 全能参考槽位上限（图片/视频/音频）：2.0 系按 9/3/3，2.5 按 30/10/10（1001 项目文档核实）
REF_LIMITS_2_0 = (9, 3, 3)
REF_LIMITS_2_5 = (30, 10, 10)

#: omni_reference_task_type=edit/extend 的 prompt 关键词（缺了会异步报错，调用前置为同步校验）
TASK_EDIT_KEYWORDS = ("编辑", "增加", "删除", "修改", "替换", "改成")
TASK_EXTEND_KEYWORDS = ("向前", "向后延长", "延续", "续写")


class ArkAPIError(RuntimeError):
    """方舟 API 错误，message 中含 HTTP 状态码与响应 body，便于定位。"""

    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        self.status_code = status_code
        self.body = body
        detail = message
        if status_code is not None:
            detail += f"（HTTP {status_code}）"
        if body:
            detail += f"\n响应 body：{body[:2000]}"
        super().__init__(detail)


class ArkClient:
    """方舟 API 客户端，全部方法支持 dry_run（只打印不请求、不扣费）。"""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        dry_run: bool = False,
        timeout: float = 300.0,
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
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # 底层请求（含 3 次指数退避重试）
    # ------------------------------------------------------------------
    def _img_url(self, value: str) -> str:
        """dry-run 下原样透传（不校验文件存在），真实调用时转 data URL。"""
        return value if self.dry_run else to_image_url(value)

    @staticmethod
    def _media_url(value: str, label: str) -> str:
        """【2.5】参考视频/音频 URL 校验：仅公网 http(s) 或 asset://。

        平台不支持本地文件 base64 内联（1001 项目实测），本地片先传 OSS 或入素材库。
        """
        if value.startswith(("http://", "https://", "asset://")):
            return value
        raise ValueError(f"[ark] {label}仅支持公网 URL 或 asset://（不支持本地文件），收到：{value}")

    def _log_dry_run(self, method: str, url: str, payload: Any) -> None:
        print(f"[dry-run] {method} {url}")
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False, indent=2))

    def _request(self, method: str, path: str, *, json_body: dict | None = None) -> dict:
        """发送请求；网络错误重试（指数退避），4xx/5xx 直接抛 ArkAPIError。"""
        url = f"{self.base_url}{path}"
        if self.dry_run:
            self._log_dry_run(method, url, json_body)
            return {"_dry_run": True}

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.request(method, url, json=json_body, timeout=self.timeout)
            except requests.RequestException as exc:  # 网络层错误才重试
                last_exc = exc
                wait = 2 ** (attempt - 1)
                print(f"[ark] 网络错误（第 {attempt}/{self.max_retries} 次）：{exc}，{wait}s 后重试")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                raise ArkAPIError(
                    f"方舟 API 调用失败：{method} {path}",
                    status_code=resp.status_code,
                    body=resp.text,
                )
            try:
                return resp.json()
            except ValueError as exc:
                raise ArkAPIError(f"方舟 API 返回非 JSON：{method} {path}", body=resp.text) from exc
        raise ArkAPIError(f"方舟 API 网络错误，重试 {self.max_retries} 次仍失败：{method} {path}\n{last_exc}")

    # ------------------------------------------------------------------
    # 图片生成（Seedream）
    # ------------------------------------------------------------------
    def generate_image(
        self,
        prompt: str,
        *,
        model: str = SEEDREAM_5_PRO,
        size: str = "2k",
        reference_images: list[str] | None = None,
        negative_prompt: str | None = None,
        watermark: bool = False,
        seed: int | None = None,
    ) -> list[str]:
        """生成图片，返回图片 URL 列表（24 小时有效，请立即 download）。

        :param prompt: 中文提示词
        :param model: 模型 ID，默认 Seedream 5.0 Pro
        :param size: "1K"/"2K" 或 "2048x2048"（TODO(校准)：官方接受的写法）
        :param reference_images: 参考图 URL 列表（≤10 张）。
            TODO(校准)：字段名按 OpenAI Images 风格暂用 ``image``；
            本地文件需先上传对象存储拿到公网 URL。
        :param watermark: 是否在右下角加"AI 生成"水印（图片默认 true，
            这里显式传 False，交付标识统一由 delivery.py 加，避免双标）
        """
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
            "watermark": watermark,
        }
        if reference_images:
            payload["image"] = [self._img_url(u) for u in reference_images]  # TODO(校准)：参考图字段名
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt  # TODO(校准)：是否支持
        if seed is not None:
            payload["seed"] = seed
        data = self._request("POST", "/api/v3/images/generations", json_body=payload)
        if self.dry_run:
            return []
        return [item["url"] for item in data.get("data", []) if item.get("url")]

    # ------------------------------------------------------------------
    # 视频生成（Seedance，异步任务制）
    # ------------------------------------------------------------------
    def create_video_task(
        self,
        *,
        model: str = SEEDANCE_2_STD,
        text: str | None = None,
        first_frame: str | None = None,
        last_frame: str | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
        task_type: str | None = None,
        duration: int = 5,
        resolution: str = "720p",
        ratio: str = "16:9",
        watermark: bool = False,
        generate_audio: bool = False,
        return_last_frame: bool = False,
        callback_url: str | None = None,
    ) -> str:
        """创建视频生成任务，返回任务 ID（任务 ID 保留 7 天）。

        :param text: 视频提示词
        :param first_frame: 首帧图 URL（本地文件需先上传拿公网 URL）
        :param last_frame: 尾帧图 URL（首尾帧接龙用）
        :param reference_images: 多模态参考图（role=reference_image，官方文档确认）；
            提示词里按顺序用"图片1/图片2"指代。人物参考原则上需先入素材库（asset://），
            未入库裸传会被反 Deepfake 按图概率拦截。
            【实测 2026-08-04】首尾帧与参考图互斥，同传会被 400 拒绝
            （first/last frame content cannot be mixed with reference media content）
        :param reference_videos: 【2.5】参考视频（role=reference_video），仅公网 URL 或
            asset://——不支持本地 base64，本地片先传 OSS/素材库
        :param reference_audios: 【2.5】参考音频（role=reference_audio），同上
        :param task_type: 【2.5】omni_reference_task_type：edit（视频编辑）/extend（视频延长）。
            edit 需 ratio=adaptive + duration=-1 + prompt 含编辑类关键词；
            extend 需 ratio=adaptive + prompt 含延长类关键词（1001 项目规范，缺了异步报错）
        :param duration: 秒。2.0 系 4-15；2.5 为 4-30 或 -1（模型自动）
        :param resolution: 480p/720p/1080p/4K（Mini 仅 720p，Fast 无 1080p，2.5 仅 480p/720p）
        :param generate_audio: 是否生成原生音频（默关闭，配音单独做可控性更高）
        :param watermark: 平台显式水印默认 false；交付标识由 delivery.py 兜底
        """
        is_2_5 = model == SEEDANCE_2_5
        dur_range = VIDEO_DURATION_RANGE_2_5 if is_2_5 else VIDEO_DURATION_RANGE
        if duration == -1:
            if not is_2_5:
                raise ValueError("[ark] duration=-1（模型自动时长）仅 Seedance 2.5 支持")
        elif not dur_range[0] <= duration <= dur_range[1]:
            raise ValueError(f"duration 必须在 {dur_range[0]}-{dur_range[1]} 秒之间（-1=自动，仅 2.5），收到 {duration}")
        # 平台限制调用前校验（避免白烧一次请求）：
        # - 首尾帧与参考图互斥（2026-08-04 实测 400）
        # - 参考槽位按模型分档：2.0 系 9 图/3 视频/3 音频，2.5 为 30/10/10
        if (first_frame or last_frame) and (reference_images or reference_videos or reference_audios):
            raise ValueError("[ark] 首尾帧与参考媒体互斥（平台实测 400），不能同传")
        max_img, max_vid, max_aud = REF_LIMITS_2_5 if is_2_5 else REF_LIMITS_2_0
        if reference_images and len(reference_images) > max_img:
            raise ValueError(f"[ark] 参考图最多 {max_img} 张（{model}），收到 {len(reference_images)} 张")
        if (reference_videos or reference_audios) and not is_2_5:
            raise ValueError("[ark] reference_video/reference_audio 仅 Seedance 2.5 支持")
        if reference_videos and len(reference_videos) > max_vid:
            raise ValueError(f"[ark] 参考视频最多 {max_vid} 条，收到 {len(reference_videos)} 条")
        if reference_audios and len(reference_audios) > max_aud:
            raise ValueError(f"[ark] 参考音频最多 {max_aud} 条，收到 {len(reference_audios)} 条")
        if is_2_5 and resolution not in ("480p", "720p"):
            raise ValueError(f"[ark] Seedance 2.5 分辨率仅支持 480p/720p，收到 {resolution}")
        if task_type:
            if not is_2_5:
                raise ValueError("[ark] omni_reference_task_type 仅 Seedance 2.5 支持")
            if task_type not in ("edit", "extend"):
                raise ValueError(f"[ark] task_type 仅支持 edit/extend，收到 {task_type}")
            if ratio != "adaptive":
                raise ValueError(f"[ark] task_type={task_type} 要求 ratio=adaptive，收到 {ratio}")
            if task_type == "edit":
                if duration != -1:
                    raise ValueError("[ark] task_type=edit 要求 duration=-1（模型自动时长）")
                if text and not any(k in text for k in TASK_EDIT_KEYWORDS):
                    raise ValueError(f"[ark] task_type=edit 的 prompt 必须含编辑类关键词：{'/'.join(TASK_EDIT_KEYWORDS)}")
            if task_type == "extend" and text and not any(k in text for k in TASK_EXTEND_KEYWORDS):
                raise ValueError(f"[ark] task_type=extend 的 prompt 必须含延长类关键词：{'/'.join(TASK_EXTEND_KEYWORDS)}")

        content: list[dict[str, Any]] = []
        if text:
            content.append({"type": "text", "text": text})
        # role 规则（KidsAI 实测代码确认）：单图 i2v 不写 role 即首帧；
        # 首尾帧模式才显式写 first_frame / last_frame
        if first_frame and last_frame:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._img_url(first_frame)},
                    "role": "first_frame",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._img_url(last_frame)},
                    "role": "last_frame",
                }
            )
        elif first_frame:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._img_url(first_frame)},
                }
            )
        elif last_frame:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._img_url(last_frame)},
                    "role": "last_frame",
                }
            )
        for ref in reference_images or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._img_url(ref)},
                    "role": "reference_image",
                }
            )
        # 【2.5】参考视频/音频：仅公网 URL 或 asset://（本地文件不支持 base64 内联）
        for ref in reference_videos or []:
            content.append(
                {
                    "type": "video_url",
                    "video_url": {"url": self._media_url(ref, "参考视频")},
                    "role": "reference_video",
                }
            )
        for ref in reference_audios or []:
            content.append(
                {
                    "type": "audio_url",
                    "audio_url": {"url": self._media_url(ref, "参考音频")},
                    "role": "reference_audio",
                }
            )
        payload: dict[str, Any] = {
            "model": model,
            "content": content,
            "duration": duration,
            "resolution": resolution,
            "ratio": ratio,
            "watermark": watermark,
            "generate_audio": generate_audio,
            "return_last_frame": return_last_frame,
        }
        if task_type:
            payload["omni_reference_task_type"] = task_type
        if callback_url:
            payload["callback_url"] = callback_url
        data = self._request("POST", "/api/v3/contents/generations/tasks", json_body=payload)
        if self.dry_run:
            return "dry-run-task-id"
        # 已确认：直连方舟响应顶层 id；ifocus 路由可能包 data（与 get_task 同一差异）
        task_obj = data["data"] if isinstance(data.get("data"), dict) else data
        task_id = task_obj.get("id") or task_obj.get("task_id") or data.get("id") or data.get("task_id")
        if not task_id:
            raise ArkAPIError("创建视频任务成功但未返回任务 ID", body=json.dumps(data, ensure_ascii=False))
        return str(task_id)

    def get_task(self, task_id: str) -> dict:
        """查询单个任务状态。

        ifocus 路由会把任务对象包在 ``data`` 字段里（与方舟直连不同，1001 项目实测），
        这里统一解包，上层拿到的永远是任务本体。
        """
        if self.dry_run:
            self._log_dry_run("GET", f"{self.base_url}/api/v3/contents/generations/tasks/{task_id}", None)
            return {"id": task_id, "status": "succeeded", "_dry_run": True}
        data = self._request("GET", f"/api/v3/contents/generations/tasks/{task_id}")
        if isinstance(data.get("data"), dict) and ("status" in data["data"] or "content" in data["data"]):
            return data["data"]
        return data

    def poll_task(
        self,
        task_id: str,
        *,
        interval: float = 5.0,
        timeout: float = 1800.0,
        verbose: bool = True,
    ) -> dict:
        """轮询任务直到 succeeded / failed / 超时。"""
        if self.dry_run:
            print(f"[dry-run] 跳过轮询任务 {task_id}，直接视为 succeeded")
            return self.get_task(task_id)
        deadline = time.monotonic() + timeout
        while True:
            task = self.get_task(task_id)
            status = task.get("status", "unknown")
            if verbose:
                print(f"  任务 {task_id} 状态：{status}")
            if status == "succeeded":
                return task
            if status == "failed":
                raise ArkAPIError(f"视频任务失败：{task_id}", body=json.dumps(task, ensure_ascii=False))
            if time.monotonic() > deadline:
                raise TimeoutError(f"轮询任务超时（{timeout}s）：{task_id}，最后状态 {status}")
            time.sleep(interval)

    @staticmethod
    def extract_video_url(task: dict) -> str:
        """从任务结果中取成片 URL。

        直连方舟为 ``content.video_url``；ifocus 路由需三级回退
        ``content.video_url → video_url → result.video_url``（1001 项目实测差异点）。
        """
        if isinstance(task.get("data"), dict):  # 未过 get_task 解包的 ifocus 原始响应兜底
            task = task["data"]
        content = task.get("content") or {}
        result = task.get("result") or {}
        url = content.get("video_url") or task.get("video_url") or result.get("video_url")
        if not url:
            raise ArkAPIError("任务成功但未找到成片 URL", body=json.dumps(task, ensure_ascii=False)[:2000])
        return str(url)

    @staticmethod
    def extract_last_frame_url(task: dict) -> str | None:
        """取无水印尾帧 URL（首尾帧接龙用；已确认字段 content.last_frame_url）。"""
        content = task.get("content") or {}
        url = content.get("last_frame_url") or content.get("cover_image_url")
        return str(url) if url else None

    # ------------------------------------------------------------------
    # 下载（生成结果 URL 24 小时有效，需及时下载）
    # ------------------------------------------------------------------
    def download(self, url: str, dest: str | Path) -> Path:
        """下载文件到本地，网络错误重试 3 次（指数退避）。

        注意不能用带 Bearer 头的 session：生成结果是对象存储签名 URL
        （ifocus 走天翼云 S3，2026-08-13 实测），多带 Authorization 头会被 S3 判 400。
        """
        dest_path = Path(dest)
        if self.dry_run:
            print(f"[dry-run] 下载 {url} -> {dest_path}（跳过，不落盘）")
            return dest_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with requests.get(url, stream=True, timeout=self.timeout) as resp:
                    if resp.status_code >= 400:
                        raise ArkAPIError(f"下载失败：{url}", status_code=resp.status_code, body=resp.text[:500])
                    with open(dest_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=1 << 20):
                            fh.write(chunk)
                return dest_path
            except requests.RequestException as exc:
                last_exc = exc
                wait = 2 ** (attempt - 1)
                print(f"[ark] 下载网络错误（第 {attempt}/{self.max_retries} 次）：{exc}，{wait}s 后重试")
                time.sleep(wait)
        raise ArkAPIError(f"下载失败，重试 {self.max_retries} 次仍失败：{url}\n{last_exc}")
