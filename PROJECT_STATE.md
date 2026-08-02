# 徐大恩（LuckyNemo）项目状态存档

> 最后更新：2026-08-01
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
| 小程序工程 | 本地 `miniprogram/` | AppID wxfab69c703920891e；后端端点 /api/mp/*；待：微信支付、认证回调、真机体验 |
| 飞书订单台 | https://acn56kbby6qx.feishu.cn/base/FQNsbNZsfaQGfUsjET8cXGNJnvH | 两张表：「订单」（tblHSraRw4jSN5vv）、「故事问卷」（tblAyGGg6ySGZJY8）。**故事问卷在 Base 顶部第二个表标签页**，直达链接：`https://acn56kbby6qx.feishu.cn/base/FQNsbNZsfaQGfUsjET8cXGNJnvH?table=tblAyGGg6ySGZJY8` |

服务器：阿里云 ECS 8.133.241.103（与 ibi.ren 同机），SSH `ssh -i /Users/app/intfocus-albert.pem root@8.133.241.103`
- 站点文件 `/var/www/luckynemo/`；后端 `/opt/luckynemo/server/`；nginx 配置 `/etc/nginx/conf.d/luckynemo.ibi.ren.conf`
- **防火墙**：iptables 只放行 22/80/443（已持久化到 `/etc/sysconfig/iptables`，2026-07-24 修复）。2026-07-24 重启后曾因规则未持久化导致 80/443 全拒（"connection refused" 但 SSH 正常就是此症状）
- 正式域名 luckynemo.com **备案未完成，未启用**；备案下来后加 server block + 证书即可切换

## 二、能力管线（tools/luckynemo-toolkit/，全部真实调通）

凭据在 `tools/luckynemo-toolkit/.env`（git 勿传）：

| 能力 | 通道 | 状态 |
|---|---|---|
| 视频 | 火山 Seedance 2.0（新火山账号） | Mini（草稿）+ 标准版（定稿）均出片 ✓ |
| 图片 | 火山 Seedream 5.0 Pro（新账号） | 出图 ✓；真人参考图路径 ✓；`size` 用小写 2k。**MiniMax 生图线 2026-08-01 已下架（效果不好），图片统一走 Seedream** |
| 脚本 | MiniMax M3 | 分镜生成 ✓（思维链已处理，单条 ≈0.1-0.2 元） |
| 旁白/克隆 | MiniMax t2a_v2 / voice_clone | ✓（克隆样本需 ≥10s） |
| 配乐 | MiniMax music-3.0 | ✓（不可指定时长；商用条款未确认） |
| 字幕 ASR | 豆包语音识别 | 未接，待补 |

- 管线 CLI：photo_pipeline（婚纱照 6 风格模板）/ video_pipeline（分镜→首帧→draft/final→roughcut）/ quick_pipeline（领证快道）/ voice_pipeline / script_pipeline
- 客户照片走 base64 内联直传，无需对象存储
- 交付合规：delivery.py 强制片尾 AI 标识卡 ≥2s + 图尾标识 + manifest

## 三、模卡（一键同款，2026-08-01 引入）

概念：每张模卡 = 一张高艺术完成度的成品摄影模板（虚拟模特出镜），内置默认场景/姿势/神态/妆容/服装/道具；用户只需"换人"即可一键同款，也可微调换服装/换妆容。

**系列化架构（v2，2026-08-01 定）**：12 个系列 × 3 变体 = 36 张。系列=主题场景（场景/服装/色调锁定），变体=同系列不同瞬间/姿势/构图。ID 规则：mk0xx=首发变体，mk1xx=第2变体，mk2xx=第3变体。

- 模板资产：`assets/moka/`（`index.json` v2 含 series 分组 + templates 平铺；`templates/mk*.png`；生成脚本 `gen_templates.py` 首批12 / `gen_variants.py` 批次2、3共24）
- 12 系列三 tab 各 4：情侣=教堂婚礼/江南雨巷/海边落日/中式婚礼；女单=花海春日/城市夜景/森林晨雾/复古港风；男单=都市街拍/棚拍正装/港风花衬衫/山野户外
- 小程序入口：`miniprogram/pages/moka/`（选模板 → 校验定妆照 → 可换妆容(选定妆照)/换服装(选套装) → `template_photo` 任务；UI 按系列分组未做，catalog 已返回 series 字段与 moka_series 列表）
- 后端：`/api/mp/catalog` 返回 moka 列表 + moka_series（app.py:1228）；worker `template_photo` 分支（mp_worker.py:409）：定妆照锚点+模板图送 Seedream，提示词"只换人，模板其他全保持"；缺定妆照自动回退原始上传照片
- 依赖前置：用户需先完成定妆（makeup 页出定妆照），情侣模板需新娘新郎都有
- 生产已同步（2026-08-01）：36 张模板 + index.json v2 在 ECS `/var/www/luckynemo/moka/`，生产 app.py 已更新并重启，catalog 线上验证 36 模板/12 系列 ✓

**自定义模卡（DIY，2026-08-01 上线）**：用户在 chat 页发范例图(可选)+文字描述 → M3 识别意图产出 `custom_moka` 动作 → worker 三段式：VLM 安全审核+意图规格化（范例图有人脸只取风格不进参考图，防肖像权风险）→ Seedream 生成（固定画质尾缀与公共模卡同骨架）→ VLM 质检（人数/畸形/文字，最多重试 2 次）→ 存 OSS `diy_moka/{order_no}/`，chat 页轮询出图后给「用这张出片」按钮 → `template_photo` 支持 `custom_template_key` 复用一键同款链路出终图。配额：每单免费 3 次（app.py custom_moka 分支控制）。DIY 卡默认私有不进公共库。
- 已验证：正常描述一次通过（规格→生成→质检→OSS→DB 全链路）；名人脸请求被安全审核正确拦截
- worker 的 MiniMax 生图（image-01 定妆第三引擎 `minimax_image`）随本次部署一并下架，引擎只余 seedream/vidu；小程序 makeup 页引擎列表早已不含 minimax

## 四、客户进展：刘奔奔 & 徐驰（样品首单）

- 素材目录：`referrence/刘奔奔&徐驰/`（照片、13 段花絮视频、2 段 4K、老公声音 58s 样本）
- 部分素材已经上传页进入 OSS `materials/20260721/13585697734/`（3 个文件）
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

- 2026-08-01 自定义模卡（DIY）上线：worker 新增 `custom_moka` 任务（VLM 审核/规格化/质检重试，存 OSS diy_moka/），`template_photo` 支持 custom_template_key；app.py chat 新增 custom_moka 动作（每单免费 3 次）；chat.js 轮询出图 + 「用这张出片」按钮；本地 E2E 正常+安全拦截均验证；生产 app.py/mp_worker.py 已更新重启；顺带下架生产 worker 的 MiniMax 生图引擎（minimax_image），清理 makeup.js minimax hint 死代码；测试数据（OSS diy_moka/TESTDIY、本地测试行）已清理
- 2026-08-01 模卡 36 张部署上线：rsync `assets/moka/` → ECS `/var/www/luckynemo/moka/`（排除 gen_*.py），生产 app.py 更新 catalog 并重启 luckynemo.service；线上验证 catalog 返回 36 模板 + 12 系列，mk208.png 可访问

- 2026-08-01 下架 MiniMax 生图：`tools/luckynemo-toolkit` 删除 minimax_client.generate_image/images_to_subject_reference、photo/video_pipeline 的 --provider minimax 分支，README/.env.example/config.py 同步；MiniMax 仅保留 M3脚本/TTS/克隆/配乐
- 2026-08-01 模卡系列化（v2）：12 系列 × 3 变体 = 36 张架构落地，`assets/moka/index.json` 升 v2（series 分组 + 每卡带 series 字段），catalog 接口透传 moka_series；`gen_variants.py` 生成批次2/3（mk101-112、mk201-212）24 张全部完成，品控后 mk208（海报墙杂脸）/mk212（剪影改余晖）重出，其余 22 张一次通过；注意模板内场景文字（囍字/霓虹招牌/COFFEE）判定为风格元素予以保留
- 2026-08-01 引入「模卡」一键同款：新增 `assets/moka/`（12 张模板 mk001-012 + index.json + gen_templates.py）、小程序 `pages/moka/`、后端 catalog moka 字段与 worker `template_photo` 分支；同日建立状态记录机制（根目录 `AGENTS.md`），本文件头部日期修正为 08-01
- 2026-07-29 小程序 worker E2E 通过（mp_jobs → Seedream → OSS results/，单张 ≈44s）
- 2026-07-24 修复 ECS iptables 80/443 未持久化问题（已写入 /etc/sysconfig/iptables）
