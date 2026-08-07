# LuckyNemo Toolkit

徐大恩（LuckyNemo）AI 婚庆影像工作室的生产工具包（Python，CLI 为主），服务三条产品线：

- **管线 A：AI 婚纱照**（`photo_pipeline`）— Seedream 图片生成
- **管线 B：爱情叙事短片**（`video_pipeline`）— Seedream 首帧 + Seedance 视频 + ffmpeg 粗剪
- **管线 C：领证纪念快道**（`quick_pipeline`）— 模板化快单，2 小时交付

底座：**火山引擎方舟（Ark）+ MiniMax 双通道**。

- 方舟（`luckynemo/ark.py`）：Seedream 图片 + Seedance 视频，是婚纱照/短片的主力线。所有 endpoint、模型 ID、payload 构造统一封装在 `ark.py`，带 `TODO(校准)` 注释。
- MiniMax（`luckynemo/minimax_client.py`）：分镜脚本（MiniMax-M3，走 `llm.py`）、音乐、TTS、声音克隆、**H3 视频（V2 接口 /v2 前缀，`--provider minimax` 接入 video_pipeline，2026-08-04 接入）**。接口已按另一项目的生产代码验证。**图片生成统一走火山 Seedream（`ark.py`），MiniMax 图片线因实测效果不佳已下架**。

## 安装

```bash
cd tools/luckynemo-toolkit
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

另需系统安装 `ffmpeg`（macOS: `brew install ffmpeg`），视频拼接/字幕/片尾卡依赖它。
可选依赖 `insightface + numpy`（人脸相似度初筛），不装也能跑，`qc_face` 会自动跳过。

## 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 ARK_API_KEY 和 MINIMAX_API_KEY
```

或直接 `export ARK_API_KEY=... MINIMAX_API_KEY=...`。**所有命令都支持 `--dry-run`：只打印将执行的 API 调用与命令，不发请求、不扣费、不需要 Key**——联调前先跑 dry-run 检查 payload。

`.env` 支持的变量：

| 变量 | 用途 | 必填 |
|---|---|---|
| `ARK_API_KEY` | 火山方舟（Seedream 图片 + Seedance 视频） | 火山线必填 |
| `ARK_BASE_URL` | 覆盖方舟 base URL（默认 https://ark.cn-beijing.volces.com） | 否 |
| `MINIMAX_API_KEY` | MiniMax（分镜脚本 M3/音乐/TTS/声音克隆/H3 视频） | MiniMax 线必填 |
| `MINIMAX_BASE_URL` | 覆盖 MiniMax base URL（默认 https://api.minimaxi.com/v1） | 否 |
| `SEEDREAM_MODEL` | 覆盖图片模型（企业端点 ep-* 时用） | 否 |
| `SEEDANCE_MODEL_DRAFT` / `SEEDANCE_MODEL_FINAL` | 覆盖视频草稿/定稿模型 | 否 |
| `MINIMAX_LLM_MODEL` | 分镜脚本生成用的大模型（默认 MiniMax-M3） | 否 |

**图片生成统一走火山 Seedream**：`generate` / `frames` 直接调用方舟线；企业账号若走端点 ID，在 `.env` 配 `SEEDREAM_MODEL=ep-xxx` 即可。MiniMax 只保留分镜脚本（M3）、TTS、声音克隆、配乐。

## 管线 A：AI 婚纱照

```bash
# 1. 素材质检（≥4 张、jpg/png、短边 ≥1024），输出报告 JSON
python -m luckynemo.photo_pipeline intake ./素材/客户A --out report.json

# 2. 按风格模板批量生成（6 套模板见 templates/photo_styles/，走火山 Seedream）
python -m luckynemo.photo_pipeline generate --style indoor_main --refs ./素材/客户A --count 2 --out ./生成/客户A
python -m luckynemo.photo_pipeline generate --style forest --refs ./素材/客户A --count 2 --out ./生成/客户A --dry-run

# 3. 生成品控图墙（浏览器打开，对照 checklists/photo_qc.md 人工勾选）
python -m luckynemo.photo_pipeline contact-sheet --in ./生成/客户A --out ./品控/客户A.html
```

风格模板：`indoor_main`（室内主纱）/ `forest`（森系外景）/ `chinese_xiuhe`（中式秀禾）/ `seaside`（旅拍海边）/ `korean_minimal`（韩式极简）/ `retro_film`（复古胶片）。

## 管线 B：爱情叙事短片

> 写/改分镜提示词前先读 `templates/seedance_prompt_rules.md`（I2V 规则、锁定与防分身、音画策略、套话改写表）；
> 重拍判词与尝试预算见 `checklists/video_qc.md` 的「重拍纪律」。

### 第 0 步：客户故事 → 分镜脚本（script_pipeline，M3 生成）

```bash
# 客户故事素材按 templates/story_intake_example.txt 的格式收集（新人信息/相识/相恋/求婚/想说的话）
python -m luckynemo.script_pipeline storyboard --template love_story \
    --input ./素材/客户B故事.txt --out ./分镜/客户B.json
# 输出与 video_pipeline 分镜 schema 完全一致；校验失败会自动带错误信息重试 1 次
# --shots N 可覆盖模板镜头数；--dry-run 打印完整 prompt 不请求
```

**客户确认脚本后再进生成**——这是省 reroll 钱的关键闸门。

### 生成与合成（video_pipeline）

**默认范式（2026-08-04 起）：r2v 多模态参考生视频，分类资产先行。** 不用首尾帧；人物/场景/道具资产先由 `assets` 子命令生成并入库，draft/final 按镜头 refs 标签组装参考图。

```bash
SB=./分镜/客户B.json   # script_pipeline 的产出；或模板 templates/storyboards/prewedding_film.json

# 1. 校验分镜 schema（含 assets 声明与 refs 标签检查）
python -m luckynemo.video_pipeline validate $SB

# 2. 生成分类参考资产（人物=客户照片登记/gen 生成；场景/道具=Seedream 生成，场景自动空镜）
#    --upload：逐资产入方舟素材库（真实人物资产过反 Deepfake 的正规通道），品控资产图后再往下走
python -m luckynemo.video_pipeline assets $SB --refs ./素材/客户B --out ./资产/客户B --upload

# 2b. （可选）构图参考：首帧图转剪影（简易图不含人脸/服装细节，防污染画面）
python -m luckynemo.video_pipeline layouts $SB --frames ./首帧/客户B --out ./构图/客户B

# 3a. 草稿：Mini 模型逐镜生成（约 0.5 元/秒，仅 720p；默认 --mode r2v）
python -m luckynemo.video_pipeline draft $SB --manifest ./资产/客户B/refs_manifest.json --layouts ./构图/客户B --out ./片段草稿/客户B

# 3b. 定稿：标准版（约 0.95 元/秒）
python -m luckynemo.video_pipeline final $SB --manifest ./资产/客户B/refs_manifest.json --layouts ./构图/客户B --resolution 720p --out ./片段/客户B

# 4. 粗剪：按分镜顺序拼接 + 旁白（--audio）+ 可选 BGM 混流（--bgm，amix：旁白 1.0 / BGM 0.25）
python -m luckynemo.video_pipeline roughcut $SB --clips ./片段/客户B --audio ./旁白.mp3 --bgm ./bgm.mp3 --out ./成片/客户B.mp4
```

分镜资产声明（顶层 `assets` 块 + 每镜 `refs` 标签，见模板 `prewedding_film.json`）：
- `characters`：**人物资产=脸+服装+妆容绑定的形象卡**（16:9：左脸正面特写+右侧全身正/侧/背三视图，纯白背景无边框；换装/换妆即新资产，如新造型声明新名字）。三种形态：`{"base": "照片文件名", "prompt": "服装妆容描述"}` → 以 base 照片为身份参考生成形象卡；`gen:提示词` → 无参考生成（虚拟人物）；`"照片文件名"` → 直接登记不生成。人物缺省全带。
- `scenes`：**场景资产=同空间四方向关联视图四宫格**（2x2，每格 9:16 竖版：正面/反打/左立面/右立面，相机 1.6m/35mm，无人物）。dict 形态：`{"desc": "场景特征描述（时代地点/时间/天气/季节 + 地面材质/左右立面归属/中心点）", "views": {...可选四视角描述}, "style": "...可选图片风格"}`，版式与视角写法由 `SCENE_GRID_TEMPLATE` 自动组装；旧 `gen:提示词` 单图形态仍兼容。
- `props`：一律 `gen:提示词`。
- 每镜 `refs`：`{"characters": [...], "scene": "名字", "props": [...]}`，引用必须在 assets 中声明。

**构图参考（layouts）**：简易图（首帧转剪影，不含人脸/服装细节，防污染画面；2026-08-06 双路线实验剪影版胜出线稿版）。先跑 `frames` 出首帧，再 `layouts` 批量转剪影；`draft`/`final` 加 `--layouts` 后参考列表末位自动追加 +"仅参考构图"锚定提示词。

**i2v 旧模式**（首帧锚，可选兜底）：`draft`/`final` 加 `--mode i2v --frames ./首帧/客户B`；首帧由 `frames` 子命令生成；拟真人首帧需先用 `asset_pipeline` 入库拿 assets_registry.json 加 `--assets` 走 asset://。

**防变脸**：r2v 模式下代码自动追加身份锚定提示词（"人物五官脸型严格参照人物参考图"）与场景锚定（"场景环境严格参照场景参考图"）；参考图 ≤9 张为平台上限（两 client 调用前校验）。

**MiniMax-H3 引擎（2026-08-04 接入，待账号开通）**：`draft`/`final` 加 `--provider minimax`，模型 `MiniMax-H3`（`MINIMAX_VIDEO_MODEL` 可覆盖），分辨率自动映射 720p→768P / 1080p·4K→2K；asset:// 仅方舟可用，走 MiniMax 时 manifest 资产自动改用本地路径（自动转 data URL）。

竖屏婚照电影（模板 `templates/storyboards/prewedding_film.json`，纯 BGM 无旁白）：`draft`/`final` 加 `--ratio 9:16`；`roughcut` 只传 `--bgm`；已有片段的镜头自动跳过（断点续跑）。

## 声音管线（MiniMax 线）

TTS 旁白、分镜配音、声音克隆、配乐生成，统一走 `voice_pipeline`：

```bash
# 单句 TTS（--voice-id 可选预置或克隆音色，--emotion 可选）
python -m luckynemo.voice_pipeline tts --text "从此，三餐四季，都有你。" --out vo.mp3 --emotion happy

# 按分镜逐镜头合成旁白 shot_01.mp3... + narration_concat.txt
python -m luckynemo.voice_pipeline narrate templates/storyboards/love_story.json --out ./旁白/客户B --voice-id xxx
# 合成一整条旁白：ffmpeg -f concat -safe 0 -i narration_concat.txt -c copy narration.mp3

# 声音克隆（wav/mp3 样本，推荐 10s 干净人声；model 必须 speech-01-turbo）
python -m luckynemo.voice_pipeline clone --audio ./样本.mp3 --voice-id-hint bride01
# → 打印 voice_id，记入 .env 或订单台账，后续 tts/narrate 用 --voice-id 引用

# 配乐生成（同步接口 music-3.0，默认纯音乐；--vocals 生成带人声歌曲）
# 注意：官方接口不支持指定时长（--duration 会被忽略），长度由模型决定（实测常为数分钟完整曲目）
python -m luckynemo.voice_pipeline music --prompt "温暖钢琴弦乐，婚礼誓词氛围，渐强收尾" --out bgm.mp3
```

## 典型全流程串法（短片单一气呵成版）

```bash
C=客户B
# 0. 脚本：客户故事 → M3 分镜（客户确认后才往下走）
python -m luckynemo.script_pipeline storyboard --template love_story --input ./素材/${C}故事.txt --out ./分镜/$C.json
SB=./分镜/$C.json
# 1. 首帧
python -m luckynemo.video_pipeline frames $SB --refs ./素材/$C --out ./首帧/$C
# 2. 视频：先 Mini 草稿品控，再标准版定稿
python -m luckynemo.video_pipeline draft $SB --frames ./首帧/$C --out ./片段草稿/$C
python -m luckynemo.video_pipeline final $SB --frames ./首帧/$C --resolution 720p --out ./片段/$C
# 3. 旁白 + 配乐
python -m luckynemo.voice_pipeline narrate $SB --out ./旁白/$C
ffmpeg -f concat -safe 0 -i ./旁白/$C/narration_concat.txt -c copy ./旁白/$C.mp3
python -m luckynemo.voice_pipeline music --prompt "温暖钢琴弦乐，婚礼氛围" --out ./bgm_$C.mp3
# 4. 粗剪混流
python -m luckynemo.video_pipeline roughcut $SB --clips ./片段/$C --audio ./旁白/$C.mp3 --bgm ./bgm_$C.mp3 --out ./成片/$C.mp4
# 5. 合规交付（必经，加 AI 标识）
python -c "from luckynemo.delivery import deliver; deliver(['./成片/$C.mp4'], './交付/$C', title='${C}短片')"
```

## 管线 C：领证纪念快道

```bash
# C1 纪念照（模板：red_bg_upgrade 红底升级 / illustration_poster 插画海报 / polaroid 拍立得风）
python -m luckynemo.quick_pipeline c1 --template red_bg_upgrade --photo ./登记照.jpg --out ./出图

# C2 15 秒小视频（Mini 1-2 镜 + 日期字幕 + 固定片尾标识）
python -m luckynemo.quick_pipeline c2 --photos ./领证照片 --date "2026.10.01 我们领证啦" --out ./成片/领证15s.mp4
```

## 成本提示（按 2026-07 官方价）

- 图片（火山）：Seedream 5.0 Pro 0.30 元/张（≤236 万像素）/ 0.60 元/张（更大）；备选 4.5（0.25 元）、Lite（0.22 元）。10 张套图算力 ≈ 10-15 元。
- 视频：标准版 ≈0.95 元/秒，Mini ≈0.5 元/秒。**策略：草稿一律走 Mini，品控确认后再用标准版出定稿**；每镜头限 reroll 3 次。3 分钟短片算力 ≈ 300 元。
- 声音（MiniMax 线）：TTS（`/t2a_v2`）按字符计费、配乐（`music-3.0`）按次计费、声音克隆（`/voice_clone`）按音色计费——均以 MiniMax 官方计费页为准；克隆客户声音须本人授权（合规红线，见下）。
- 脚本（MiniMax M3）：官方发布口径 ≤512K 档输入 4.2 元 / 输出 16.8 元每百万 tokens（促销期可能更低）；单条分镜生成约数千输入 + 两千输出 tokens，成本分级，以 `storyboard` 命令打印的 usage 估算为准。
- 生成结果 URL 有时效，脚本会立即下载落盘。

## 合规提示（必须读）

- **一切对外交付物必须走 `delivery.py`**：图片加图尾"AI 生成"标识（文字 ≥ 最短边 5%）、视频加片尾 ≥2 秒标识卡（GB 45438-2025），并生成隐式元数据占位（`*.aimeta.json`，预留 cnTC260 国标五要素写入接口）+ `manifest.json` 清单。不要绕过。
- 客户要"无水印纯净版"：走《标识办法》第 9 条豁免（协议明确义务 + 日志留存 ≥6 个月），不是简单关掉标识。
- Seedance 真人素材需先在方舟控制台「录入真人形象素材」（人脸核验 + 肖像授权），这是每单的标准前置动作。
- 品控 checklist：`checklists/photo_qc.md` / `checklists/video_qc.md`，行业无公开验收标准，这是我们自己的质量资产。

## 已知待校准项（接入真实账号后）

- 方舟侧见 `luckynemo/ark.py` 顶部注释：参考图字段名、size 写法等，标了 `TODO(校准)`；视频侧 payload 已与实测代码交叉校准。
- MiniMax 侧：TTS（`/t2a_v2`）、声音克隆（`/files/upload` + `/voice_clone`）、音乐（`/music_generation`，同步 music-3.0）三个接口均已于 2026-07-20 真实调用验证；与早期资料的不一致处均已按实测修正并写入 `luckynemo/minimax_client.py` 注释。MiniMax 图片生成（`/image_generation`）因实测效果不佳已下架，图片统一走火山 Seedream。
