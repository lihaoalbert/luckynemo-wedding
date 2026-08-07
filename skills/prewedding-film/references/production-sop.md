# 【婚照电影】生产 SOP

> 完整规则：`tools/luckynemo-toolkit/templates/seedance_prompt_rules.md` + `checklists/video_qc.md`
> toolkit venv：`source tools/luckynemo-toolkit/.venv/bin/activate`，命令均为 `python -m luckynemo.*`

## 阶段 0：素材与授权

1. 新人照片目录 ≥6 张：正脸特写 ≥2、半身 ≥2、双人照更佳；样例 `referrence/刘奔奔&徐驰/intake_20260724/`（取前 10 张作参考图）
2. 确认项目文件夹 `profile.json` 的 `consent.face == true`
3. 收集定制信息：新人姓名、婚期（片尾字卡用）、想替换的场景/道具（可选）

## 阶段 1：定制分镜

1. 复制锚点分镜：`tools/luckynemo-toolkit/templates/storyboards/prewedding_film.json` → 项目文件夹 `film/prewedding_storyboard.json`
2. 定制原则：保留六段骨架与 18-22 镜；只改中间幕的场景/道具/服装描述；frame_prompt 必带风格尾缀，narration 全部留空
3. 校验：`video_pipeline validate film/prewedding_storyboard.json`（总时长应落在 80-100s）
4. 把分镜表（镜号/画面/动作，不给提示词原文）发给客户确认

## 阶段 2：首帧（像不像本人在这一步定生死）

```bash
python -m luckynemo.video_pipeline frames film/prewedding_storyboard.json \
  --refs <新人照片目录> --size 1440x2560 --out film/frames/
```

- 显式尺寸被接口拒绝时回退默认 `--size 2K`
- 逐镜人工品控：①像不像本人（第一优先）②竖构图与景别 ③色调统一（奶油色/黑白段影调）
- 不像的镜：换 refs 里更清晰的正脸照重跑该镜；同缺陷 2 次改 prompt 不抽卡

## 阶段 3：草稿 → 定稿（默认闸门：草稿给客户看过才进定稿）

**先入库再生成**（2026-08-04 实测教训）：拟真人首帧裸传 data URL 会被反 Deepfake 按图拦截（`InputImageSensitiveContentDetected.PrivacyInformation`），人脸特写几乎必拦。入库后走 `asset://` 首帧可过审：

```bash
# 入库：建组（每单一次）→ 逐镜上传（CreateAsset 有 QPM 限流，间隔 ≥15s + 限流重试）
python -m luckynemo.asset_pipeline create-group --name "婚照电影-<新人>-首帧"
python -m luckynemo.asset_pipeline upload --group <group-id> --file film/frames/shot_XX.png --name shot_XX
# 映射写入 film/assets_registry.json：{"group": "...", "frames": {"shot_01": "asset-xxx", ...}}

python -m luckynemo.video_pipeline draft film/prewedding_storyboard.json \
  --frames film/frames/ --assets film/assets_registry.json --ratio 9:16 --out film/clips_draft/
python -m luckynemo.video_pipeline final film/prewedding_storyboard.json \
  --frames film/frames/ --assets film/assets_registry.json --ratio 9:16 --resolution 1080p --out film/clips_final/
```

- draft/final 支持断点续跑：已有片段的镜头自动跳过，重跑某镜先删对应 mp4
- 草稿抽帧品控：五官漂移、手部畸形、防分身（`checklists/video_qc.md` 重拍纪律）
- 本片无台词，口型红线天然规避；仍禁 video_prompt 出现"说/笑出声"等带声音暗示的词（动作可写"笑"）

## 阶段 4：BGM 与合成

```bash
python -m luckynemo.voice_pipeline music --prompt "韩式婚礼钢琴曲，弦乐铺底，温柔浪漫，无歌词" --out film/bgm.mp3
python -m luckynemo.video_pipeline roughcut film/prewedding_storyboard.json \
  --clips film/clips_final/ --bgm film/bgm.mp3 --out film/roughcut.mp4
```

- 不传 `--audio`（无旁白）；BGM 不可指定时长，长了用 ffmpeg 截断并淡出
- 片尾字卡：PIL 生成（不用 drawtext），黑底白字细体——新人姓名 + 婚期，≥3s，拼在 roughcut 后

## 阶段 5：交付

`luckynemo.delivery`（片尾 AI 标识卡 ≥2s + aimeta + manifest）→ `delivery/`。本片型只出 9:16 竖版，不做横版。

## 成本参考（以官方计费页为准）

- 首帧 20 张 Seedream + 草稿 20 镜 × 4-5s Mini（≈0.5 元/秒 ≈ 45 元）+ 定稿标准版（≈0.95 元/秒 ≈ 86 元）
- 草稿前给客户报价区间，草稿确认是默认闸门
