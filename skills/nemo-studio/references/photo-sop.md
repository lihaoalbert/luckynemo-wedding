# 【照相馆】SOP

> 场景库为"微剧情场景"：每个场景配一句剧情引子，静态照片也要有故事感。

## 流程

1. **前置**：定妆照已确认（`wardrobe/selection.json` 非空）
2. **选场景**：用户从场景库挑选（网页或对话），每个场景展示：场景图 + 剧情引子一句话；选择结果存 `scenes/selection.json`
3. **生成**：`python -m luckynemo.photo_pipeline generate --style <风格> --refs <定妆照/identity> --count N --out photos/`
   - 人物参考用定妆照（人物+服装一致）；场景按用户所选
   - 防分身：提示词含"画面中仅这一对新婚男女两人"
4. **品控**：`photo_pipeline contact-sheet` 出图墙，按 `checklists/photo_qc.md` 过检；不合格按重拍纪律处理
5. **交付**：通过的照片统一 `luckynemo.delivery`（图尾 AI 标识 + aimeta + manifest）→ `delivery/`

## 微剧情场景设计规范（扩充场景库时）

- 每个场景 = 场景描述（给生成模型）+ 剧情引子（给用户看的一句话）
- 反例（空场景）："海边""草坪""教堂"
- 正例（微剧情）："初雪便利店的暖光，两人分一杯热饮""图书馆同一排书架的两端，同时抽同一本书""天台那碗泡面的热气，冬天里分着吃"
- 场景图预生成为空场景（无人物），人物在拍摄时以定妆照锚入
