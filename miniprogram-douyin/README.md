# 徐大恩 LuckyNemo 抖音小程序

由微信小程序版（`miniprogram/`）移植，tt.* 体系（TTML/TTSS）。用**抖音开发者工具**导入本目录。规划见 `research/2026-08-抖音小程序版规划.md`。

## 与微信版的差异

| 项 | 微信版 | 抖音版 |
|---|---|---|
| 登录 | wx.login → /api/mp/login（openid 前缀 wx-） | tt.login → /api/dy/login（前缀 dy-） |
| 支付 | 虚拟支付代币模式（金币钱包） | **担保支付按单支付**（/api/dy/pay/*，tt.pay 收银台 service=5） |
| iOS | 支持虚拟支付 | **无虚拟支付通道**：canPay=false，付费入口全隐藏，禁止任何引导文案（审核红线） |
| 客服 | open-type="contact" 微信客服 | 无 → 「我的 → 意见反馈」留言 |
| 语音输入 | WechatSI 同声传译插件 | 已下线（入口注释在 chat.ttml），待接抖音 ASR |
| 分享海报小程序码 | wxacode.getUnlimited | 暂缺，走无码版海报（qrPath=null 退化） |
| 站外引流 | 客服微信兜底 | **禁止**：不放任何微信号/外链 |

## 移植注意

- 页面/样式与微信版同源，改 UI 时考虑双向同步（或接受分叉，按组内约定）
- codemod 规则：`wx.` → `tt.`、`wx:` → `tt:`、`.wxml/.wxss` → `.ttml/.ttss`
- `project.config.json` 的 `appid` 为占位 `TODO_DOUYIN_APPID`，注册完成后替换
- 后端端点除 /api/dy/* 外全部复用 /api/mp/*（worker/catalog/OSS 与平台无关）

## 待办

1. 抖音开放平台企业主体注册 → 填 appid
2. 深度合成类目申请（算法备案已完成）
3. 担保支付进件 → 后端配 DOUYIN_PAY_SALT 等
4. 人脸核身链路：微信真人认证 H5 在抖音端改为浏览器打开（已实现），长期方案待调研
5. 抖音小程序码接口接入（恢复海报带码 + 裂变归因）
