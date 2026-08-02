# 项目文件夹 Schema（单客档案，唯一事实源）

路径约定：`couples/<订单号>_<新郎>&<新娘>/`（订单号为 LN 开头或内部编号）

```
couples/<订单号>_<新郎>&<新娘>/
├── profile.json          # 基础参数 + 授权状态（见下）
├── intake/               # 用户输入：问卷原文、生活照（符合拍摄指引）、声音样本
├── identity/             # 身份资产：正脸特写、三视图、assets_registry.json（方舟 asset:// 登记）
├── wardrobe/             # 试衣间：选择的服装组合（selection.json）+ 定妆照
├── scenes/               # 照相馆：选中的场景资产图
├── photos/               # 婚纱照产出（含品控记录 qc/）
├── film/                 # 短片：story_intake.txt、storyboard.json、assets/、clips_*、narration、bgm、成片
└── delivery/             # 交付物 + manifest.json + *.aimeta.json
```

## profile.json

```json
{
  "version": 1,
  "order_no": "LN20260722-XXX",
  "groom": { "name": "", "contact": "" },
  "bride": { "name": "", "contact": "" },
  "wedding_date": "",
  "style_preference": "",
  "consent": { "face": false, "voice": false, "marketing": false },
  "created_at": "",
  "status": "intake | identity | wardrobe | photos | film | delivered"
}
```

规则：
- `consent.face` / `consent.voice` 为 false 时，对应生成一律不得发起；`marketing: true` 才允许作品对外展示
- 所有时间用 ISO 8601；`status` 每次推进一个阶段时更新
- schema 变更必须递增 `version` 并保留旧字段可读（老订单文件夹不能失效）
