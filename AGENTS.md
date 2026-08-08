# LuckyNemo 项目工作约定

## 项目状态记录（每个工作会话必须遵守）

`PROJECT_STATE.md` 是项目状态的唯一权威来源，恢复上下文靠它。机制如下：

1. **会话开始**：先读 `PROJECT_STATE.md` 对齐进度。
2. **会话中**：每完成一件有状态变化的事（新功能上线、管线调通、客户进展、线上配置变更、新增待办），**当场**更新 `PROJECT_STATE.md`，不要攒到结束。
3. **更新内容**：
   - 头部"最后更新"改为当天日期；
   - 对应章节改为最新事实（不要保留过期描述）；
   - 在文末「更新日志」追加一条：`日期 + 一句话干了什么 + 涉及路径`。
4. **粒度**：只记"换人接手也能接着干"级别的事实——线上地址、服务名、文件路径、未完成步骤、坑。不记过程性流水账。
5. 线上（ECS）发生的变更，除了改文件还要在文中标注生产端状态（如"已同步 /opt/luckynemo"）。

## 并行开发规范（2026-08-04 起，三组并行）

### 分支模型

- `main`：主干，始终保持可部署状态。**只有 main 能上生产**，禁止从功能分支直接部署 ECS。
- `miniprogram`：小程序组（miniprogram/ 前端 + server/ mp 接口）。
- `moka`：模版组（模卡/妆造资产与生成管线）。**独立工作区 `/Users/app/LuckyNemo-Wedding-moka`（git worktree，2026-08-07 建）**，模卡优化都在那边做。
- `video`：视频组（视频管线与视频相关 worker）。
- `xhs`：小红书小程序组（`miniprogram-xhs/` 前端 + server/ 小红书登录与支付通道）。独立 worktree：`/Users/app/LuckyNemo-Wedding-xhs`。
- 功能分支从 main 拉，完成后 PR 回 main；定期（至少每次开工前）把 main 合回自己的分支，避免长漂移。
- worktree 不带 `.env`（凭据不进库）：新工作区要用 server/toolkit 时，自己从主仓拷贝对应 `.env`。

### 文件归属（减少冲突）

| 组 | 主责文件 |
|---|---|
| 小程序组 | `miniprogram/`、`server/app.py`（/api/mp/* 接口与 chat）、`server/mp_worker.py` 的 mp 任务 |
| 模版组 | `assets/moka/`（模板/index.json/生成脚本）、`assets/hongzhuang/` |
| 视频组 | `tools/luckynemo-toolkit/`、`server/mp_worker.py` 的视频任务部分 |
| 小红书组 | `miniprogram-xhs/`（小红书小程序前端，独立框架不复用微信小程序代码）、`server/app.py` 的 xhs 登录/支付通道 |

- **跨组文件**（`server/app.py`、`server/mp_worker.py`、各 `index.json`、`PROJECT_STATE.md`）：改动前在群里同步一句，合并时先沟通再合。
- `PROJECT_STATE.md` 每组各自维护自己领域的章节，更新日志按时间追加不覆盖别人的。
- 凭据（`.env`、密钥）永远不进库，各组自己本地配置（见 `.env.example`）。

### 合并与部署纪律

1. PR 回 main 前：代码自审 + 本地验证（能跑通的必须跑通，生成类的必须看产出物）。
2. 合并后由当次合并人负责部署验证（服务 active + 接口冒烟），并在 PROJECT_STATE.md 更新日志注明。
3. 小程序前端改动合并后，在群里提醒负责人去微信开发者工具上传发布。
4. 生产事故回滚：`git revert` 对应提交 → 重新部署，不直接在生产机上改文件。

## 目录速览

- `website/` 静态站点源（部署到 ECS `/var/www/luckynemo/`）
- `miniprogram/` 微信小程序工程
- `server/` FastAPI 后端 + 小程序 worker（生产在 ECS `/opt/luckynemo/server/`）
- `assets/` 生成资产库（hongzhuang/nishang/moka/scenes）
- `tools/luckynemo-toolkit/` AI 管线 CLI（凭据在其 `.env`，勿提交）
- `referrence/` 虚拟模特 & 客户素材
- `research/` 调研与规划文档
