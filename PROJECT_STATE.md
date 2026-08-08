# 徐大恩（LuckyNemo）项目状态存档

> 最后更新：2026-08-07
> 恢复方式：把这个文件给 Kimi 看，或直接说"继续 LuckyNemo 项目"
> 记录机制：见根目录 `AGENTS.md`——会话中状态有变化就当更新本文件，文末追加更新日志

---

## 一、线上资产（都在运行中）

| 资产 | 地址 | 说明 |
|---|---|---|
| 官网 | https://luckynemo.ibi.ren/ | 静态页，图片全部 Seedream 自生成（本地 assets） |
| 故事问卷页 | https://luckynemo.ibi.ren/story/ | 提交 → 飞书「故事问卷」表 + OSS stories/ |
| 素材上传页 | https://luckynemo.ibi.ren/upload/ | 浏览器直传 OSS ibi-private，凭微信号/订单号关联；含拍摄指引区块 |
| 试衣间 | https://luckynemo.ibi.ren/wardrobe/ | 霓裳阁选装（套装/单选）→ POST /api/wardrobe/selection → OSS selections/ |
| 照相馆 | https://luckynemo.ibi.ren/scenes/ | 30 微剧情场景多选 → 同一 selection API；与试衣间互相跳转 |
| 样片中心 | https://luckynemo.ibi.ren/demo2/ | 三条产品线 demo（/demo/ 为旧 LuckyNemo Studio 作品集） |
| 战略路线图 | 本地 `website/roadmap/index.html` | 私有版，状态源 `state.js`（用户勾选/口述后由 Kimi 更新）；线上版已下线 |
| 后端 API | https://luckynemo.ibi.ren/api/health | FastAPI，ECS 127.0.0.1:8090，systemd `luckynemo.service`（Restart=always，重启 ECS 会自启） |
| 小程序 worker | systemd `luckynemo-worker.service` | `/opt/luckynemo/server/mp_worker.py`，轮询 mp_jobs → Seedream → OSS results/，单张 ≈44s（2026-07-29 E2E 通过） |
| 小程序工程 | 本地 `miniprogram/` | **AppID wx213d47a529c7055c**（2026-08-04 更正，旧记录 wxfab69c703920891e 作废；ECS MP_APPID 与 project.config.json 均为新号）；后端端点 /api/mp/*；待：认证回调、真机体验 |
| 虚拟支付 | /api/mp/vpay/* | 代币模式「金币」**1 元 = 1 币**（MP 后台已配并「联调发布」；价格须整数元：单张 3.9 已改 4 元）。4币→1张 / 49币→50 张。prepare/confirm（幂等）/notify 三端点已上线。**密钥已配 ECS `.env`（OfferID 1450606065，现网+沙箱 AppKey），当前 VP_ENV=1 沙箱**。**Android 沙箱真机联调已通过（2026-08-06，AXEZ 4 元充值到账，paySig 前缀 bug 已修，main a98a51e）**。待：①**VP_ENV 改 0 切现网（现网测试必须用正式版小程序，env=0）**②**iOS 开通：虚拟支付→基础配置页（前置：先配小程序简称）；iOS 不开通则 iPhone 完全无法支付（独立开关默认关闭）；iOS 仅现网可测（无沙箱）、iOS15+/微信8.0.68+/大陆 Apple ID/最低 1 元；iOS 费率 Apple 12%（腾讯 5% 2026 减免）；iOS 退款走 App Store，退款问询 3 秒应答接口 xpay_subscribe_ios_refund_query_notify 待补** ③沙箱 Midas 不推发货通知属正常，到账靠 confirm 补偿闭环（已验证）。注：vp 通知走小程序「消息推送」通道而非 vp 后台独立配置，notify 端点非必需；对账用 MP「交易订单」或 query_order API |
| 飞书订单台 | https://acn56kbby6qx.feishu.cn/base/FQNsbNZsfaQGfUsjET8cXGNJnvH | 两张表：「订单」（tblHSraRw4jSN5vv）、「故事问卷」（tblAyGGg6ySGZJY8）。**故事问卷在 Base 顶部第二个表标签页**，直达链接：`https://acn56kbby6qx.feishu.cn/base/FQNsbNZsfaQGfUsjET8cXGNJnvH?table=tblAyGGg6ySGZJY8` |

服务器：阿里云 ECS 8.133.241.103（与 ibi.ren 同机），SSH `ssh -i /Users/app/intfocus-albert.pem root@8.133.241.103`
- 站点文件 `/var/www/luckynemo/`；后端 `/opt/luckynemo/server/`；nginx 配置 `/etc/nginx/conf.d/luckynemo.ibi.ren.conf`
- **防火墙**：iptables 只放行 22/80/443（已持久化到 `/etc/sysconfig/iptables`，2026-07-24 修复）。2026-07-24 重启后曾因规则未持久化导致 80/443 全拒（"connection refused" 但 SSH 正常就是此症状）
- 正式域名 luckynemo.com **备案未完成，未启用**；备案下来后加 server block + 证书即可切换

## 二、能力管线（tools/luckynemo-toolkit/，全部真实调通）

凭据在 `tools/luckynemo-toolkit/.env`（git 勿传）。**生图/视频供应端双通道（2026-08-04 命名定）**：`ark-ifocus` = iFocusing 路由 `router.i-focusing.com`（`IFOCUS_API_KEY`，Ark 全兼容——文档确认生图 `/api/v3/images/generations`、视频 `/api/v3/contents/generations/tasks` 只需换 Host+Key；另有平台兼容 `/v1/*` 路径）；`ark-direct` = 火山直连 `ark.cn-beijing.volces.com`（`ARK_API_KEY`）。**小程序 worker 生图默认走 ark-ifocus，异常自动 failover 到 ark-direct**（mp_worker.py `_ark_channels()`，`ARK_CHANNEL` 环境变量可强制主通道）；toolkit 走 ark-direct，要切 ifocus 只需 `ARK_BASE_URL`+`ARK_API_KEY` 换成 ifocus 的。注意两通道是独立账户独立账单（2026-08-04 直连欠费时 ifocus 不受影响）

| 能力 | 通道 | 状态 |
|---|---|---|
| 视频 | 火山 Seedance 2.0（新火山账号） | Mini（草稿）+ 标准版（定稿）均出片 ✓ |
| 视频 | MiniMax-H3（V2 接口） | 已接入 video_pipeline `--provider minimax`（2026-08-04）；**账号侧阻塞：现有 TokenPlan/Credit 不支持 H3（错误 2013），需在 MiniMax 控制台开通/购买后校准** |
| 图片 | 火山 Seedream 5.0 Pro（新账号） | 出图 ✓；真人参考图路径 ✓；`size` 用小写 2k。**MiniMax 生图线 2026-08-01 已下架（效果不好），图片统一走 Seedream** |
| 脚本 | MiniMax M3 | 分镜生成 ✓（思维链已处理，单条 ≈0.1-0.2 元） |
| 旁白/克隆 | MiniMax t2a_v2 / voice_clone | ✓（克隆样本需 ≥10s） |
| 配乐 | MiniMax music-3.0 | ✓（不可指定时长；商用条款未确认） |
| 字幕 ASR | 豆包语音识别 | 未接，待补 |

- 管线 CLI：photo_pipeline（婚纱照 6 风格模板）/ video_pipeline（分镜→首帧→draft/final→roughcut；2026-08-04 起 `frames --size`、`draft/final --ratio` 支持竖屏 9:16）/ quick_pipeline（领证快道）/ voice_pipeline / script_pipeline
- 客户照片走 base64 内联直传，无需对象存储
- 交付合规：delivery.py 强制片尾 AI 标识卡 ≥2s + 图尾标识 + manifest

## 二点五、婚照电影（prewedding-film，2026-08-04，video 分支）

- 新产品线：Studio Wonkyu 风韩式婚照电影——用新人真实照片生成 9:16 竖屏 ≈90s 短片（高调白纱室内→黑白间奏→夜街吻收尾，纯 BGM 无旁白）
- 参考片拆解：`referrence/刘奔奔&徐驰/new/205cddc99c5220686670c28ec79ac81b_raw.mp4`（87.6s/28 镜/纯音乐）
- Skill：`skills/prewedding-film/`（SKILL.md + references/style-bible.md 风格圣经 + references/production-sop.md 生产 SOP）
- 锚点分镜：`tools/luckynemo-toolkit/templates/storyboards/prewedding_film.json`（20 镜 91 秒，已过 validate；script_pipeline `--template prewedding_film` 可直接引用）
- **视频生成规范（2026-08-06 用户定）**：①不用首尾帧，默认 r2v 多模态参考生视频；②人物/场景/道具资产先生成（assets 子命令 → refs_manifest.json）才能生视频；③多参数接口按模型精准适配（方舟/MiniMax 各自 client 校验：互斥、≤9 张、分辨率档位）。i2v 旧模式保留为 `--mode i2v` 兜底。**人物资产规范：人=脸+服装+妆容绑定的形象卡（换装/换妆即新资产），版式 16:9：左脸正面特写+右侧全身正/侧/背三视图、纯白背景无边框（代码常量 CHAR_SHEET_LAYOUT 自动套用）；声明 `{"base": 照片, "prompt": 服装妆容}` 即以本人照片为身份参考生成**。**场景资产规范：2x2 四宫格同空间四方向关联视图（每格 9:16 竖版：正面/反打/左立面/右立面，1.6m/35mm 全景无人物，SCENE_GRID_TEMPLATE 自动组装；尺寸 1440x2560，勿超 Seedream 462 万像素）**。**构图参考（layouts，实验中）：简易图（剪影/火柴人线稿）不含人脸服装细节，--layouts 目录按 shot_XX.png 约定，参考列表末位 +"仅参考构图"锚定**
- 状态：分镜与管线（--ratio/--size）已 dry-run 验证；2026-08-04 首样 E2E 首跑 draft 发现**视频变脸**（首帧正常、片中漂成模板脸，根因：i2v 只传首帧无身份锚点 + Mini 保持力弱）。已实测三条路（shot_05 对照）：①首帧+参考图混传 → 方舟 400 互斥，接口层不支持；②**标准版 i2v（仅首帧）身份保持合格**；③**Mini r2v（首帧降为图片1参考 + 新人照片身份锚点）也稳**，pipeline 已加 `--char-refs` 支持该模式。v1 废片存档 `film/clips_draft_v1_变脸废弃/`。结论：draft=Mini r2v（--char-refs）、final=标准版 i2v；新人正面照已入库素材库（新娘 asset-20260804102400-5lg5m / 新郎 asset-20260804102408-qzbhg，组 group-20260804093915-slq4k）。**注意：r2v 模式参考图会把场景往参考图带（海滩照片曾致 shot_16 中段棚景漂成海滩），场景敏感的镜头走 i2v**。全量 20 镜 Mini r2v 草稿已完成并逐镜品控：19/20 通过无变脸，shot_16 场景漂移用标准版 i2v 单独补出（进 clips_final/）；草稿粗剪 `film/roughcut_draft.mp4`（91.8s 带 BGM）已交用户审阅，确认后跑剩余 19 镜定稿
- r2v 新范式落地（2026-08-06）：分镜加顶层 assets 声明（characters/scenes/props）+ 每镜 refs 标签；`assets` 子命令生成 3 场景（white_studio/dark_studio/night_street，四宫格竖版 1440x2560 已品控合规）+ 3 道具（bouquet/ring/veil）并入新素材组 group-20260806222635-z8mjw；manifest `film/refs_assets/refs_manifest.json`；人物形象卡（bride_gown/groom_suit，asset-20260806225621-242d7 / asset-20260806225706-84ktz）shot_05 服装锁定验证通过；构图参考定为剪影版（`layouts` 子命令首帧转剪影，20 镜已生成 `film/layouts/`）；每镜 refs.characters 精确化（单人镜单卡）。分镜按用户要求剪到 17 镜 76s；全量 17 镜草稿品控 16/17 通过后补齐，76.7s 粗剪 `film/roughcut_draft_v2.mp4` 已出。**2026-08-07 用户审片结论：不满意，细节待讨论——①人物不像（侧脸镜头为主，与反馈 #26 同源：人脸三视图资产已生成入库待验证——bride_gown_face asset-20260807082318-f6x2h / groom_suit_face asset-20260807082405-2d5j6，正/左/右脸部特写、不参考服装、侧脸原照参考，版式品控合格；r2v 组装自动紧随形象卡。characters 声明支持可选 side 侧面原照列表）②运镜奇怪（待用户具体指出镜头）。暂停生成类投入，等细节讨论后再迭代**

## 三、模卡（一键同款，2026-08-01 引入）

概念：每张模卡 = 一张高艺术完成度的成品摄影模板（虚拟模特出镜），内置默认场景/姿势/神态/妆容/服装/道具；用户只需"换人"即可一键同款，也可微调换服装/换妆容。

**系列化架构（v2，2026-08-01 定）**：系列=主题场景（场景/服装/色调锁定），变体=同系列不同瞬间/姿势/构图。mk 卡 ID 规则：mk0xx=首发变体，mk1xx=第2变体，mk2xx=第3变体。**当前规模（2026-08-02）：92 张模板 / 68 系列 = mk 12 系列×3 变体（36 张）+ lovers 56 张（每卡独立系列，lv0xx）**。

- 模板资产：`assets/moka/`（`index.json` v2 含 series 分组 + templates 平铺；`templates/mk*.png`；生成脚本 `gen_templates.py` 首批12 / `gen_variants.py` 批次2、3共24）
- 12 系列三 tab 各 4：情侣=教堂婚礼/江南雨巷/海边落日/中式婚礼；女单=花海春日/城市夜景/森林晨雾/复古港风；男单=都市街拍/棚拍正装/港风花衬衫/山野户外
- 小程序入口：`miniprogram/pages/moka/`（选模板 → 校验定妆照 → 可换妆容(选定妆照)/换服装(选套装) → `template_photo` 任务；UI 按系列分组未做，catalog 已返回 series 字段与 moka_series 列表）
- 后端：`/api/mp/catalog` 返回 moka 列表 + moka_series（app.py:1228）；worker `template_photo` 分支（mp_worker.py:409）：定妆照锚点+模板图送 Seedream，提示词"只换人，模板其他全保持"；缺定妆照自动回退原始上传照片
- 依赖前置：用户需先完成定妆（makeup 页出定妆照），情侣模板需新娘新郎都有
- 生产已同步（2026-08-01）：36 张模板 + index.json v2 在 ECS `/var/www/luckynemo/moka/`，生产 app.py 已更新并重启，catalog 线上验证 36 模板/12 系列 ✓
- **v3 分组设计（2026-08-04，moka 分支，设计方案待实施）**：基于新样例库 `/Users/lihao/Downloads/previews`（267 组真实客片/4459 张，全量勘察）设计「6 一级大类 × 30 二级系列（每系列 9 变体=九宫格）」，方案与选取清单见 `research/2026-08-模卡分组设计.md`。要点：lv 56 张拟全下架、mk 12 系列保留补类目（previews 全 couple 且无中式/教堂/夜景）；previews 是真实客片须先换脸虚拟模特再入库；批量九宫格需新增 template_series 任务类型
- **v3 实施进展（2026-08-04，moka 分支，未提交未部署）**：首批 8 系列（hyd蓝绣球/sak樱花隧道/muh粉黛/lig悬崖灯塔/han韩服古祠/hor以梦为马/min白色极简/spk暮色仙女棒）各精选 9 张源片（存 `~/Desktop/moka_series_src/`，真实客片不入库）→ `assets/moka/gen_series.py` 换脸生成到 `series_draft/`；`build_series_index.py` 负责 index.json v3（groups 层 + 下架 lv* + mk 编组）；后端 app.py 新增 catalog `moka_groups` 透传 + `template_series` 任务（按变体数扣额度，`_moka_series_size`）；worker 新增 `run_template_series`（同锚点逐变体生成，进度写 result_json.urls）；小程序 moka 页改分组+系列九宫格 UI（无 groups 时回退老版平铺）、generating 页显示 x/9 进度、result 页九宫格+全部保存
- **v3 品控与入库（2026-08-04，全部完成）**：72 张换脸底片 4 路审片 71 通过；lig09（"Save the Date" 文字牌）账户充值后加去文字词重跑通过（文字牌换花束、墨镜保留、脸已换）。**index.json v3 终态：108 模板（36 mk + 72 新）/ 20 系列 / 6 分组，lv 56 张全下架**；本地起服务验证 catalog 返回 moka_groups 6 组 ✓。注：方舟账户曾欠费导致全部生图 403，充值后恢复
- **v3 已上线（2026-08-04）**：main 合并 631af75（无 gh，本地 ff 合并推 origin/main）；ECS `/var/www/luckynemo/moka/` 已同步 108 模板 + index.json v3（lv 文件已删，线上 404），`/opt/luckynemo/server/` app.py/mp_worker.py 已更新，luckynemo + luckynemo-worker 重启 active；线上冒烟 catalog=108 模板/20 系列/6 分组 ✓ hyd01.png 200 ✓。待办：微信开发者工具上传小程序（moka/generating/result 三页）

- **v4 已上线（2026-08-07）**：main 合并 f845f8e → 96822e1（含 fav 鉴权收紧）；ECS `/var/www/luckynemo/moka/` 180 模板 + index.json v4、`/opt/luckynemo/server/` app.py/mp_worker.py 已同步，两服务 active；线上冒烟 catalog=180模板/20系列(全9变体)/6分组/4节点、mk301.png 200、lv001.png 404、fav 伪造 token 401 ✓。发现并修复：仓库 templates/ 残留 56 张 lv 旧卡被 rsync 误回线上，已删线上+删库（7908671，lovers_draft 存档保留）。**待办：微信开发者工具上传小程序（v4 三新页面+首页重构，未经验证）；占位稿 Seedream 重出替换**
- v4 规划文档（已定稿实施）：`research/2026-08-模卡内容体验规划.md` + H5 demo `research/moka-h5-demo/index.html`（发现首页/系列详情独立页/结果页朋友圈预览三屏，图片用线上模板）。核心主张：系列即九宫格、节点语言入口（领证/婚纱/旅拍/写真）、详情页价格前置+效果预期、上新日历驱动复购

- **小程序人脸三视图（2026-08-07 上线，反馈 #26/#27）**：`face_sheet` 任务（me 页入口选正脸底照+侧脸原照 → 脸部三视图卡，不参考服装），template_photo/duo_photo/template_series 自动注入做侧脸身份锚定；chat 说身高（"他183我165"）→ selection.heights → 双人照还原身高差
- **me 页改版（2026-08-07，前端待发布）**：生成的照片挪二级页 `pages/photos/`（网格 + 长按保存/删除，me 页只留入口行，防几十张图撑长页面）；全屏预览改整组 urls 传参，系统自带左右滑动（上传照片/生成照片都支持）

**自定义模卡（DIY，2026-08-01 上线）**：用户在 chat 页发范例图(可选)+文字描述 → M3 识别意图产出 `custom_moka` 动作 → worker 三段式：VLM 安全审核+意图规格化（范例图有人脸只取风格不进参考图，防肖像权风险）→ Seedream 生成（固定画质尾缀与公共模卡同骨架）→ VLM 质检（人数/畸形/文字，最多重试 2 次）→ 存 OSS `diy_moka/{order_no}/`，chat 页轮询出图后给「用这张出片」按钮 → `template_photo` 支持 `custom_template_key` 复用一键同款链路出终图。配额：每单免费 3 次（app.py custom_moka 分支控制）。DIY 卡默认私有不进公共库。
- 已验证：正常描述一次通过（规格→生成→质检→OSS→DB 全链路）；名人脸请求被安全审核正确拦截
- worker 的 MiniMax 生图（image-01 定妆第三引擎 `minimax_image`）随本次部署一并下架，引擎只余 seedream/vidu；小程序 makeup 页引擎列表早已不含 minimax

## 四、客户进展：刘奔奔 & 徐驰（样品首单）

- 素材目录：`referrence/刘奔奔&徐驰/`（照片、13 段花絮视频、2 段 4K、老公声音 58s 样本）
- 上传页素材已回收本地：`referrence/刘奔奔&徐驰/上传素材/`（11 张 IMG_14xx 海滩/生活照 + 07-21 手机号入口 3 个文件，均已下载；OSS 源：`materials/20260724/刘奔奔/`、`materials/20260721/13585697734/`）
- **等问卷答案**：问卷已发给用户（templates/story_intake_questionnaire.md），还没回收
- 计划：爱情故事短片 + 老公克隆声音旁白；真实花絮视频打底 + AI 镜头补叙事
- 执行步骤存档：①克隆声音（58s 样本）②4K 抽帧补素材 ③M3 分镜→人工打磨→客户确认 ④frames→draft→品控→final ⑤narrate+music→roughcut→精剪 ⑥delivery 双版交付

## 五、待办清单（重启后接着干）

1. **奔奔徐驰问卷回收** → 跑样品首单（最先做：克隆声音试听）
2. OSS 控制台配生命周期：`materials/` `stories/` 前缀 30 天自动删（兑现"交付即删"）
3. 清理测试数据：飞书 4 条"测试"记录（订单表 LN20260721-IHA/U6M/3DD 等、问卷表 2 条）、OSS 4 个测试对象、奔奔徐驰目录之外的 LN20260721-* 前缀
4. /api/ 加限流/验证码（正式投放前）
5. ArcFace 相似度阈值用真实单校准（insightface 可选装）
6. MiniMax 音乐商用授权确认；lark-cli master key 曾短暂外露，介意可 config init 轮换
7. luckynemo.com 备案推进 + 商标 41/45 类注册（市场调研遗留）
8. 用户测试数据（查大师 LN20260721-U6M、大白&小李问卷）保留观察，别误删

## 六、关键文档

- `research/2026-07-市场调研报告.md`（市场结论与定价）
- `research/2026-07-生产工具链设计方案.md`（§10 为接口最新状态，以它为准）
- `tools/luckynemo-toolkit/README.md`（管线用法）
- `server/`（后端本地副本，ECS /opt/luckynemo/server 为生产）

## 更新日志

- 2026-08-07 模卡内容体验规划 v4 讨论稿（未提交入库）：产出 `research/2026-08-模卡内容体验规划.md`（现状7条体验问题、外部调研结论、v4信息架构/内容补齐/上新日历/分期路线）+ H5 demo `research/moka-h5-demo/index.html`（三屏已截图验证）；等用户讨论拍板后再定实施与入库
- 2026-08-07 同款大片 v4 前后端落地完成（moka 分支，**未提交未部署**）：①后端见上条（catalog v4/fav 接口/variant_ids 子集扣费，本地冒烟过）；②小程序前端重构——新增 `utils/moka.js` 公共构建、`pages/moka_series/`（详情独立页：九宫格+成分表+价格前置+相册式选片多选+收藏钮）、`pages/moka_fav/`（我的收藏），moka 页改发现首页（搜索/主推轮播/人生节点/热门/分组），generating 进度 N 泛化，result 页加朋友圈 mock+模板对比，me 页加收藏入口；7 JS node --check 全过，**未经微信开发者工具验证**；③mk 12 系列 72 张 MiniMax 占位图（`gen_mk_placeholders.py`，11.6s/张共78次调用，832×1248 同 2:3 比例）已品控（24 抽+4 水印重跑全过）并登记 index.json：`templates/mk3NN..mk8NN.png` 带 `placeholder:true` 打标、标题「xx · 占位4-9」，**20 系列全部凑齐 9 变体（180 模板）**，catalog 冒烟 placeholder 透传 ✓；**上线前须用 Seedream 逐张重出替换占位稿**（MiniMax 画风与正式版不一致）。待：用户确认后提交 moka 分支 → 合并 main → 部署 ECS → 微信开发者工具上传小程序
- 2026-08-07 同款大片 v4 后端落地（moka 分支，未提交未部署）：index.json 升 v4（series 加 moments/tags/hot_base/status + 顶层 moments 4 节点入口）；app.py catalog 透传 v4 字段并计算 hot=hot_base+真实生成数（_moka_hot_counts：template_series 每单+template_photo 每张）、新增 mp_favs 表与 /api/mp/fav（POST）/api/mp/favs（GET，openid 取自 open_token wx- 前缀）、_moka_series_size 支持 variant_ids 选片子集扣费；mp_worker run_template_series 支持 variant_ids 只生成选中变体；本地冒烟全过（catalog v4 字段/收藏增删查/_moka_series_size 整组9/子集3/单张1）
- 2026-08-07 规划 v4 第一轮拍板（文档 §九决策记录）：①详情页独立页 ✅ ②mk 系列用 MiniMax 生图先补 9 格占位、上线前 Seedream 重出替换（占位须打标）③节点入口 4 个命名定稿 ④"N人拍过"=运营基数+真实计数；demo 按反馈加「只拍单张」相册式多选模式（右上角圆圈、CTA 与价格联动）

- 2026-08-06 虚拟支付 Android 沙箱真机联调通过：AXEZ 充值 4 元（4币→1张）成功，prepare→沙箱支付→confirm 到账闭环验证（mp_pay_orders VP178603085047614C paid，18s 到账，沙箱无 Midas 推送属正常，confirm 补偿通道生效）；代码已提交 main/payment a98a51e 推 origin，miniprogram/app.js 同步到上传工作树（moka 分支未提交态，仅 3 行诊断改动）；剩：VP_ENV 改 0 切现网（须正式版小程序验证）、iOS IAP 开通
- 2026-08-06 修复反馈 #24（充值选 4元/张 报"支付未完成"，Android 真机）：根因=prepare 的 paySig 少拼官方固定前缀（正确公式 `hmac_sha256(appKey, "requestVirtualPayment&"+signData)`，signature 用 session_key 原样 HMAC 是对的未动）；server/app.py 已改并部署 ECS 重启 active，prepare 冒烟正常；小程序 app.js 支付失败时改弹窗展示 errCode/errMsg（-15006=paySig 错/-15009=代币未发布/-15011=现网版不可用沙箱 env=1），**待微信开发者工具重新上传小程序**；注意沙箱联调只能用开发版/体验版，线上正式版 env=1 会报 -15011；反馈已回复 done
- 2026-08-06 确认虚拟支付 MP 后台状态（用户提供截图）：沙箱 AppKey + 现网 AppKey 均已签发，OfferID 1450606065 与 ECS 配置一致；「是否启用苹果IAP支付」开关仍为关闭，「是否启用平台路径」亦关闭。剩余待办不变：代币配置页点「联调发布」金币 → Android 沙箱真机联调 → VP_ENV 改 0 切现网；iOS 需先配小程序简称再开 IAP 开关（无沙箱，只能现网测）
- 2026-08-04 修复反馈 #23（原图直出把汗珠也保留了）：use_original 提示词加"皮肤清理"（去汗珠/油光/瑕疵，五官不动、痣保留、不过度磨皮）；chat makeup_photo 动作新增 note 字段透传用户修饰要求（worker 以"仅限皮肤层面"约束附加进提示词）；用新娘照片重出验证：汗珠去除、长相未动 ✓（job#91）；反馈已回复，未处理清零
- 2026-08-04 修复反馈 #22（"还是没法新增底图，前面说改好了"）：根因=add_base_photo 全表去重，chat 上传先登记 -chat 暂存相册导致目标相册永远 added=0——改为只按目标相册去重；另新增 chat 动作 `makeup_photo`（发照片说"修一张定妆照"→ 直接建定妆任务，底图入对应相册+原图直出版兜底，限额与 /api/mp/job 一致），chat.js 导航定妆页（自动恢复等待页）；线上原话实测通过（job#87 hz108 原图直出版 role=A，脸不动换灰棚 ✓）；新郎海滩照已补录 A 相册；反馈已回复，未处理清零
- 2026-08-04 修复反馈 #21（新娘新底图被误判定制模卡 + 求"原图只换背景"选项）：①M3 提示词加硬约束——消息含"底图/新底图/上传/补传/重新上传"一律 add_base_photo，严禁 custom_moka；②红妆阁新增「原图」系列 hz214（女）/hz108（男）原图直出版（spec.use_original：人物 100% 不动仅换浅灰棚拍背景），app.py `_compose_makeup_prompt` 新分支、worker 该模式只用底图一张且不融合妆容建议/不改发型/不走 vidu；新娘面部特写已补录 B 相册（原来只在 chat 暂存）；用该照片实测 hz214 出图：脸完全不动、海滩背景换灰棚 ✓；反馈已回复。注：误触发的 custom_moka 占了 AXEZ 一次 DIY 免费额度（剩 2 次）
- 2026-08-04 虚拟支付密钥上线：OfferID/AppKey（现网+沙箱）配入 ECS `.env`，VP_ENV=1 沙箱，luckynemo 重启 active，prepare 端点线上验证 401（配置生效）；更正小程序 AppID 为 wx213d47a529c7055c（旧 wxfab69c703920891e 作废）；待 MP 后台配代币+发货推送地址、iOS 开通、沙箱真机联调
- 2026-08-04 微信虚拟支付对接（代币模式）：app.py 新增 mp_sessions/mp_pay_orders 表 + /api/mp/vpay/prepare（signData/paySig/signature 三要素）/confirm（幂等到账+归属校验）/notify（验签到账）；mp_login 存 session_key；小程序 app.js `vpay()` 统一支付入口（未配置回退客服），result/me 页接入；本地 E2E（签名校验/到账/幂等/403）通过；app.py 已部署 ECS 重启 active（VP_* 未配置，线上现为回退态）；待：MP 控制台 offerId/AppKey 配 .env、沙箱真机联调、小程序上传
- 2026-08-04 生图双通道上线：命名 ark-ifocus（iFocusing 路由 router.i-focusing.com，默认）/ ark-direct（火山直连，备用）；实测 ifocus 路由 Ark 全兼容（生图真实出图 ✓、Seedance 文档确认同路径）；mp_worker `seedream()` 改双通道自动 failover，ECS 实测主通道出图 ✓ + 坏 key 注入 failover 到 direct ✓；worker 已重启；main/moka 合并 6c247c8。此前欠费的是 ark-direct 账户（已充值），与 ifocus 相互独立
- 2026-08-04 模卡 v3 合并上线：lig09 充值后重跑通过，8 系列 72 张全入库（index.json v3 终态 108 模板/20 系列/6 分组）；提交曾误落 miniprogram 分支（共享工作树被他组切换），已 fast-forward 归位 moka 并复原 miniprogram；无 gh，main 本地 ff 合并 631af75 推 origin；ECS 同步 `/var/www/luckynemo/moka/`（108 模板，lv 文件删除 404）+ `/opt/luckynemo/server/` 两文件，luckynemo/luckynemo-worker 重启 active，线上 catalog 冒烟 108/20/6 ✓；待微信开发者工具上传小程序
- 2026-08-04 模卡 v3 落地（moka 分支，未提交）：8 系列精选 72 张源片 → `gen_series.py` 换脸全出 → 4 路审片 71/72 过（lig09 文字牌 FAIL，重跑遇**方舟账户欠费**待充值）→ `build_series_index.py` 登记 7 系列 63 张，index.json v3=99 模板/19 系列/6 分组、lv 56 张下架；app.py 加 moka_groups+template_series 扣费、mp_worker 加 run_template_series、小程序 moka/generating/result 三页改九宫格链路；本地 catalog 验证通过
- 2026-08-04 接入 MiniMax-H3 视频（video 方向）：`minimax_client.py` 新增 V2 视频方法（create/get/poll/extract，/v2 前缀，content 结构对齐方舟），video_pipeline draft/final 新增 `--provider minimax`（分辨率映射 768P/2K，asset:// 自动回退本地路径）；dry-run 验证通过；真实校准被账号拦下：TokenPlan/Credit 暂不支持 MiniMax-H3（2013），待控制台开通后跑 shot_05 单镜校准
- 2026-08-06 视频生成范式切换 r2v 默认化（video 方向，用户规范：不用首尾帧/资产先行/双模型精准适配）：分镜 schema 加顶层 assets 声明 + 每镜 refs 标签；video_pipeline 新增 `assets`/`layouts` 子命令与 draft/final `--mode r2v`（默认）/`--manifest`/`--layouts`；ark.py/minimax_client.py 各加调用前限制校验；人物形象卡规范（CHAR_SHEET_LAYOUT）+ 场景四宫格规范（SCENE_GRID_TEMPLATE）落地；prewedding_film.json（模板+工作版）已迁移；README 同步
- 2026-08-07 裂变奖励规则上线：受邀新用户（分享卡片 ?ref= / 海报小程序码 scene=r_<share_token> 归因，order.ref 落库）**首次生成成功** → 邀请人 free_quota +1（ref_rewarded 列保证只奖一次，worker 完成钩子在公共尾部 + template_series）；新增 `/api/mp/qrcode`（wxacode.getUnlimited + OSS qrcodes/ 缓存）+ `oss_put`；海报品牌条右侧画小程序码（失败退化无码版），app.js onLaunch 解析 scene。已部署冒烟（AXEZ 码已生成 qrcodes/0eccb758670d5ab3.png）；前端待发布
- 2026-08-07 定价调整 + P1 两项：①定价改 4 元/张 + 52 元/20 张套餐（原 49 元/50 张；VP_PRODUCTS pack52=52币→20张，result/me 页与 README 同步；iOS/Android 同价，费率差异当获客成本——MP 后台金币商品发布后不可改故未动）；②品控兜底：`seedream_qc`（VLM 质检人数/畸形/文字/与参考图一致，带问题重试 1 次，最终不过也交付并留痕，VLM 异常静默退化直出）接入 template_photo/duo_photo/solo/婚纱照/template_series 全链路，生产真单 hyd04 验证通过（57s 含质检）；③裂变：photos 页长按加「生成分享海报」（canvas 成品图+品牌条存相册），chat/me/photos 分享卡片带图（photos 页用最新成品图）。后端已部署重启；前端待发布
- 2026-08-07 体验优化 P0 五项（按用户确认顺序全做）：④「我的」照片列表排除 face_sheet（三视图退化为内部资产，用户不可见）；⑤「模卡」改名「同款大片」（UI 文案全改，代码标识不动）；③上传页槽位化（正脸必传 + 左/右侧脸/全身建议，uploads 表加 slot 列 + `/api/mp/face_sheet/auto` 幂等触发，凑齐正脸+侧脸自动后台出三视图，用户无感知）；①首次进入落地页 pages/landing（效果展示/三步流程/隐私承诺，landing_seen 标记只看一次）；②chat 跳转按钮图片卡片化（PAGE_CARDS 映射：上传/定妆/同款大片/高级定制配效果图）。后端已部署 ECS（me photos/slot/auto 端点冒烟通过）；**前端待发布累计 4 批（三视图入口、照片二级页、标签修复、本次 P0 五项）**
- 2026-08-07 反馈 #28/#29/#30 处理：#29（不能生成新娘三视图）根因是 me 页标签假定 A=她，但该订单创建者 A=新郎 → 相册与按钮标签改中性「我的/伴侣的、为我/为 TA 生成」（前端待发布）；#28（模卡没换成我们的模特）抽查 muh 系列 4 张 + hyd 2 张均已换脸成功，回复解释模板预览是虚拟模特+请用户指认具体卡；#30（生图要选三视图吗）回复自动参考无需手选；三条均已回复 done
- 2026-08-07 人脸三视图画质升级：实测对比 4.5@4K 单图 vs 5.0 Pro 三视角分镜 2K×3+拼接，分镜路线全胜（发丝/皮肤细节、画幅规范、相似度）→ `run_face_sheet` 改分镜生成+Pillow 横拼（ECS venv 新装 pillow 12.3.0），toolkit 侧同步改 ffmpeg hstack；AXEZ 两人三视图已按新路线重出（B=2e7ad85e 已目验 4320x2560 合格）；已推 main（d5cf911）
- 2026-08-07 人脸三视图小程序线上线（反馈 #26/#27 闭环）：worker 新增 `face_sheet` 任务（正脸底照+侧脸原照 → Seedream 16:9 正/左/右脸部特写卡，规范与 toolkit video_pipeline 同源）并自动注入 template_photo/duo_photo/template_series（参考图追加 + 侧脸锚定尾缀）；chat update_selection 新增 heights 自由文本（双人照 prompt 还原身高差）；app.py face_sheet 按成员鉴权不扣额度、me 页 label「人脸三视图」；me 页新增生成入口（选底照+侧脸照）。已部署 ECS 并真单冒烟：AXEZ 两人三视图已生成（results/MP20260729-AXEZ/7aa1f896.jpg、7a60c888.jpg），hyd07 验证片参考图 5 张注入生效、新郎侧脸还原良好；两条反馈已回复 done。**提醒：me 页前端改动需负责人在微信开发者工具上传发布**
- 2026-08-06 修复反馈 #25（点了整组9张但「我的」页一张没有）：根因 `/api/mp/me` 只聚合 result.url 单张，template_series 的 result.urls 数组漏读；已修复并部署 ECS（已同步 /opt/luckynemo，服务重启，线上验证 9 张系列组图返回正常）；顺带发现生产 app.py 比本地多一条 #24 支付签名修复（paySig 加 "requestVirtualPayment&" 前缀），已回灌本地副本；反馈已回复 done
- 2026-08-06 婚照电影全要素草稿（video 方向）：分镜按用户要求剪到 17 镜 76s（去 18/19/20 夜街段）；全量 Mini r2v（形象卡+场景四宫格+道具+剪影构图）17/17 生成成功；逐镜品控 16/17 通过（身份/服装/构图/人数全达标，无变脸），shot_15 提示词与构图不符（站姿变俯拍躺姿）已修正提示词重出并通过；**76.7s 粗剪 `film/roughcut_draft_v2.mp4` 已出（含 BGM），待用户审阅后跑标准版定稿**；旧片段存档 `film/clips_draft_v2_旧r2v范式/`
- 2026-08-04 婚照电影 draft 变脸修复（video 方向）：shot_05 三路对照实测——首帧+参考图混传被方舟 400 拒绝（互斥，ark.py 已注释此限制）；标准版 i2v 身份保持合格；Mini r2v（首帧降为图片1 + 新人照片锚点）同样稳。video_pipeline draft/final 新增 `--char-refs`（r2v 模式，`tools/luckynemo-toolkit/luckynemo/video_pipeline.py`），新人正面照入库（asset-20260804102400-5lg5m / asset-20260804102408-qzbhg）；v1 废片存档 `couples/刘奔奔&徐驰/film/clips_draft_v1_变脸废弃/`，全量 20 镜 Mini r2v 草稿重跑中。期间方舟账号曾欠费（已充值恢复）：全量勘察新样例 `/Users/lihao/Downloads/previews`（267 组/4459 张，8 路并行看图打标）→ 产出 `research/2026-08-模卡分组设计.md`：6 一级大类 × 30 二级系列（每系列 9 变体对应朋友圈九宫格）、24 个新系列选定来源组、mk 老系列保留待扩充、lv 56 张拟下架；尚未动 index.json/前后端
- 2026-08-04 新增婚照电影产品线（video 分支）：调研 Wonkyu 风参考片 → 新建 `skills/prewedding-film/`（风格圣经+生产SOP）+ 锚点分镜 `tools/luckynemo-toolkit/templates/storyboards/prewedding_film.json`（20镜91s竖屏，validate通过）；video_pipeline 新增 `frames --size` 与 `draft/final --ratio` 支持 9:16；真实出片 E2E 待跑
- 2026-08-04 开启三组并行开发：分支 `main`（主干，唯一可部署）/ `miniprogram`（小程序组）/ `moka`（模版组）/ `video`（视频组）均已推送 GitHub；并行规范（分支模型、文件归属、跨组文件同步、合并部署纪律）见根目录 `AGENTS.md`

- 2026-08-04 修复反馈 #20（奔奔素颜定妆照不像本人）：素颜版提示词加"相似度第一优先，宁可朴素绝不美化、不往标准模板靠"；用她的修正意见（眼睛鼻子还原、牙齿调小）重出一版定妆照（role=B base=海滩照，results/MP20260729-AXEZ/4f230ce5.jpg，自查相似度明显改善）；反馈已回复。注：奔奔夫妇即 AXEZ 测试订单的真实客户（昊哥=徐驰？代操作）
- 2026-08-03 修复反馈 #18/#19（moka 页定妆照行错配）：男单模板错显示女生定妆照行——锚点选择改为跟模板性别走（女单→女生/男单→男生/情侣→双行）；男生行消失根因是 mp_order_get jobs LIMIT 10 把老定妆照挤出窗口，放宽到 30；反馈已回复，未处理清零
- 2026-08-03 修复反馈 #16/#17（定妆选不到伴侣照片 + 身份标签不清）：定妆页底照改为本人+伴侣双相册并列（缩略图标注 我的/伴侣的），选哪张就给谁定妆（payload.role=底照相册 baseRole）；身份标签按性别而非 role；反馈已回复，未处理清零。注意：给伴侣定妆（role=B）要求伴侣本人已完成真人认证（同意链）
- 2026-08-03 修复反馈 #15（发照片"已收到"却没保存）：`add_base_photo` 增加 who 字段（me/partner → A/B 相册分开存），M3 提示词强制"说明是谁的照片时必须触发保存、严禁只回已收到"，回复附保存张数；已把 AXEZ 8-03 的 5 张补录（新郎2→A、新娘3→B）；反馈已回复，未处理清零
- 2026-08-03 定妆照新增「素颜干净版」：红妆阁 hz213（女）/hz107（男），不化妆只统一浅灰背景与棚光（spec.no_makeup 标记）；app.py `_compose_makeup_prompt` 素颜专用提示词分支，worker vidu 通道素颜只发底图+文字（不发妆面参考图）；卡图用沈念卿/陈奕辰生成；已同步 ECS 并验证 catalog
- 2026-08-03 修复反馈 #13/#14：①新增 `duo_photo` 双人合照任务（两张单人照/一张合照直接真人合拍，含 M3 路由规则"真人合照→duo_photo，要模板→custom_moka"及防照抄示例文本）；②moka 页定妆照按性别分组（女生/男生位，不再按 role A 默认新娘），缺一方定妆照从硬拦改为知情继续（worker 原始照片回退）或去定妆；③全链路 新娘/新郎 标签中性化（创建者/伴侣、你/TA）；order jobs 接口新增 gender 字段。duo_photo 本地 E2E（mk005+mk009 合拍）+ 线上原话验证均通过；反馈已回复，未处理清零
- 2026-08-02 lovers 底片 56 张入库上线：用户审定 lovers_draft 余下 56 张（55 情侣 + lv005 男单，含 lv022b 外滩变体；lv008/lv009/lv026/lv028/lv034/lv035/lv063 被用户终审淘汰）→ `build_lovers_index.py` 登记进 index.json（每卡独立系列）并复制到 templates/ → rsync 到 ECS；线上模卡共 **92 张模板 / 68 系列**（36 mk + 56 lv），catalog 验证通过；注意情侣 tab 现 59 张平铺偏长，系列分组 UI 优先级上升
- 2026-08-02 lovers 范本换脸底片 62 张：源 `/Users/lihao/Desktop/lovers`（76 张）→ 分类 63 couple 可换（7 张遮挡/空镜/无脸跳过 + 1 男单）→ Seedream 换脸（陆辰野×黎泠娜/陈奕辰，gen_lovers.py，含 >36M 像素自动缩图与 --strong 加强重跑）→ 全量品控 60 通过 + 加强重跑救回 2 → **62 张合格底片在 `assets/moka/lovers_draft/`**；6 张（lv027/029/033/052/067/068）侧脸/墨镜/暗光场景换脸两次均不生效，已删（模型遮挡场景保留原脸的已知限制）；待用户挑选入正式库（可作 lovers 情侣系列）
- 2026-08-02 修复反馈 #12（改成片被误判回定妆）：新增 `edit_photo` 任务——以最新成片为底 + 用户指令局部修图（Seedream 编辑模式），chat 动作区分 edit_photo（改成片）/regenerate_makeup（改定妆照）；本地 E2E（mk001 加头纱，其余不变）+ 线上原话验证均通过；反馈已回复 done
- 2026-08-01 修复反馈 #11（chat"光答应不做事"）：chat 新增 `generate_photo` 动作——用户说"用这张出片"时把刚发的图/最近聊天图/DIY 模卡当模板 + 最新定妆照锚点，跳 generating 页出图（进度可见）；M3 提示词加"禁止光说不给按钮"规则；用反馈订单 MP20260730-S23T 原话线上验证通过；反馈已回复标记 done（10/10 全清）
- 2026-08-01 代码入库 GitHub：`git@github.com:lihaoalbert/luckynemo-wedding.git` main 分支首提交（494 文件 ~206MB）。`.gitignore` 排除：.env 凭据、referrence/ production/ server/data/（客户隐私）、showcase/assets/（大视频）、.venv、seedance-2.0-skill（内嵌三方 git 仓）

- 2026-08-01 自定义模卡（DIY）上线：worker 新增 `custom_moka` 任务（VLM 审核/规格化/质检重试，存 OSS diy_moka/），`template_photo` 支持 custom_template_key；app.py chat 新增 custom_moka 动作（每单免费 3 次）；chat.js 轮询出图 + 「用这张出片」按钮；本地 E2E 正常+安全拦截均验证；生产 app.py/mp_worker.py 已更新重启；顺带下架生产 worker 的 MiniMax 生图引擎（minimax_image），清理 makeup.js minimax hint 死代码；测试数据（OSS diy_moka/TESTDIY、本地测试行）已清理
- 2026-08-01 模卡 36 张部署上线：rsync `assets/moka/` → ECS `/var/www/luckynemo/moka/`（排除 gen_*.py），生产 app.py 更新 catalog 并重启 luckynemo.service；线上验证 catalog 返回 36 模板 + 12 系列，mk208.png 可访问

- 2026-08-01 下架 MiniMax 生图：`tools/luckynemo-toolkit` 删除 minimax_client.generate_image/images_to_subject_reference、photo/video_pipeline 的 --provider minimax 分支，README/.env.example/config.py 同步；MiniMax 仅保留 M3脚本/TTS/克隆/配乐
- 2026-08-01 模卡系列化（v2）：12 系列 × 3 变体 = 36 张架构落地，`assets/moka/index.json` 升 v2（series 分组 + 每卡带 series 字段），catalog 接口透传 moka_series；`gen_variants.py` 生成批次2/3（mk101-112、mk201-212）24 张全部完成，品控后 mk208（海报墙杂脸）/mk212（剪影改余晖）重出，其余 22 张一次通过；注意模板内场景文字（囍字/霓虹招牌/COFFEE）判定为风格元素予以保留
- 2026-08-01 引入「模卡」一键同款：新增 `assets/moka/`（12 张模板 mk001-012 + index.json + gen_templates.py）、小程序 `pages/moka/`、后端 catalog moka 字段与 worker `template_photo` 分支；同日建立状态记录机制（根目录 `AGENTS.md`），本文件头部日期修正为 08-01
- 2026-07-29 小程序 worker E2E 通过（mp_jobs → Seedream → OSS results/，单张 ≈44s）
- 2026-07-24 修复 ECS iptables 80/443 未持久化问题（已写入 /etc/sysconfig/iptables）
