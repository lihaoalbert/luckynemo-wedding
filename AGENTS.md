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

## 目录速览

- `website/` 静态站点源（部署到 ECS `/var/www/luckynemo/`）
- `miniprogram/` 微信小程序工程
- `server/` FastAPI 后端 + 小程序 worker（生产在 ECS `/opt/luckynemo/server/`）
- `assets/` 生成资产库（hongzhuang/nishang/moka/scenes）
- `tools/luckynemo-toolkit/` AI 管线 CLI（凭据在其 `.env`，勿提交）
- `referrence/` 虚拟模特 & 客户素材
- `research/` 调研与规划文档
