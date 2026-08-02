# 【爱情短片】SOP

> 完整规则：`tools/luckynemo-toolkit/templates/seedance_prompt_rules.md` + `checklists/video_qc.md`

## 阶段 0：剧本共创（质量感的来源）

1. 引导客户填 `https://luckynemo.ibi.ren/story/` 故事问卷（或对话收集），存 `film/story_intake.txt`
2. **先出故事梗概**（不分镜）：一页纸讲清"这支片子的叙事线"，给用户确认"这是我们的故事"；用户可对话修改，改到认可为止
3. 用 `script_pipeline storyboard` 生成分镜（模板库 6 套骨架选最贴合的），人工打磨后存 `film/storyboard.json`
4. 校验：`video_pipeline validate`

## 阶段 1：资产

1. **身份**：从 intake 照片裁正脸特写；生成三视图（Seedream）；`asset_pipeline` 入方舟素材库，ID 写 `identity/assets_registry.json`
2. **场景**：按分镜逐镜生成场景资产图（空场景无人物，Seedream）→ `film/assets/`
3. **服装**：默认用定妆照造型；特殊年代/主题造型在提示词中描述

## 阶段 2：拍摄（reference_image 模式）

- 视频任务固定参数顺序：图片1=新郎 asset://、图片2=新娘 asset://、图片3=场景 URL
- 先 Mini 草稿全镜，抽帧品控（人脸一致性、动作节拍、口型红线）
- 重拍纪律执行；锁定后再定标准版（默认闸门：草稿预览给操作员看过才进定稿）

## 阶段 3：声音与合成

1. 旁白：`voice_pipeline narrate`（克隆音色需 `consent.voice == true`；总长超片长用 `--speed 总长/片长` 修正）
2. BGM：`voice_pipeline music`，混流时旁白 1.0 / BGM 0.25
3. 精剪：片名卡（PIL 生成，不用 drawtext）+ 拼接

## 阶段 4：交付

`luckynemo.delivery`（片尾 AI 标识卡 ≥2s + aimeta + manifest）→ `delivery/`；16:9 横版 + 9:16 竖版双版本

## 禁止事项

- narration 是角色台词的镜头，video_prompt 禁止出现说话动作（口型红线）
- 未入库人像素材不得提交视频任务（必被拦）
- 不得绕过 delivery 直接交付
