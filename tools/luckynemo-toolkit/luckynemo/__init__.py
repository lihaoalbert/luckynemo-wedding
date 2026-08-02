"""LuckyNemo AI 婚庆影像生产工具包。

三条产品线共用同一套底座：
- 管线 A：AI 婚纱照（photo_pipeline）
- 管线 B：爱情叙事短片（video_pipeline）
- 管线 C：领证纪念快道（quick_pipeline）

所有火山引擎方舟（Ark）API 的 endpoint、模型 ID、payload 构造
统一封装在 :mod:`luckynemo.ark`，请勿在管线里硬编码。
"""

__version__ = "0.1.0"
