# 徐大恩 LuckyNemo 小程序（P1 照相馆 MVP）

微信小程序前端 + ECS FastAPI 后端。对话流引导：上传照片 → 定妆 → 选装 → 免费生成 1 张 → 付费（4 元/张 或 52 套餐 · 20 张）→ 短片升级。（真人认证 2026-08-11 起下线：chat.js AUTH_ENABLED=false + 后端 MP_REQUIRE_AUTH=0，视频上线时恢复）

## 结构

```
miniprogram/            # 微信小程序工程（微信开发者工具直接导入本目录）
├── app.json / app.js / app.wxss   # 设计系统：暖粉底 + 衬线标题 + 珊瑚金点缀
├── pages/chat/         # 对话流主页（AI 引导全流程，步进式 dock）
├── pages/upload/       # 拍摄指引 + 直传 OSS（复用 /api/uploads/sign）
├── pages/wardrobe/     # 霓裳阁套装 + 微剧情场景（数据走 /api/mp/catalog）
├── pages/generating/   # 提交免费任务 + 轮询
└── pages/result/       # 成片 + 付费入口 + 短片升级 + 保存/分享
```

## 后端端点（已上线，ECS /opt/luckynemo/server）

| 端点 | 作用 |
|---|---|
| POST /api/mp/order | 创建/恢复订单（v1 设备 token） |
| GET /api/mp/order/{order_no} | 订单 + 最近任务状态 |
| GET /api/mp/auth-link | 真人认证链接（带 order 参数） |
| POST /api/mp/auth-pass | 认证通过回写 |
| GET /api/mp/catalog | 霓裳阁/场景目录（读站点 data.js） |
| POST /api/mp/job | 提交生成任务（free_photo 等，auth_ok 闸门） |

## 待办（按依赖排序）

1. **AppID**：注册后填 project.config.json 的 appid；`wx.login` 换 openid 替换 open_token
2. **服务器域名白名单**：小程序后台 → 开发管理 → request/uploadFile/downloadFile 域名加 `https://luckynemo.ibi.ren`
3. **生成 worker**：mp_jobs 目前是队列，需要 worker 执行（toolkit 部署到 ECS + 轮询脚本，下一步做）
4. **支付**：微信支付商户号；开通前 result 页走客服微信核销（已内置引导 LuckyNemo2026）
5. **真人认证回调**：认证服务商回调地址对接到 /api/mp/auth-pass（当前为人工/客服核验）
6. 真机预览：`project.config.json` 里 `urlCheck:false` 仅供开发，发布前必须配域名白名单

## npm 构建（证件照 BlazeFace 依赖）

证件照拍摄页（pkg_idphoto 分包）用 tfjs + BlazeFace 做端侧人脸检测。因 @tensorflow 依赖约 1.6MB（压缩后），主包会超 2MB 限制，**证件照整体放在 `pkg_idphoto/` 分包，npm 也构建进分包**（project.config.json 已配 `packNpmManually` + `packNpmRelationList`）：

1. 在 `miniprogram/pkg_idphoto/` 目录执行 `npm install`（依赖包本身不进包体积，模型权重网络加载）。
2. 微信开发者工具 → 菜单「工具」→「构建 npm」（每次新增/升级依赖后都要重新构建；构建产物在 `pkg_idphoto/miniprogram_npm/`）。
3. tfjs 依赖官方插件 `tfjsPlugin`（已在 app.json 的 subpackages.pkg_idphoto 内声明，provider `wx6afed118d9e81df9`），首次使用需在小程序管理后台「设置 → 第三方服务 → 插件管理」添加该插件。
4. 未构建 npm / 插件未添加 / 模型加载失败时，拍摄页自动降级为手动模式（无自动判定，可手动按快门），不阻塞功能。
