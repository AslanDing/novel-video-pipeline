# 32 FFmpeg 合成管线与命令模板

## 1. 目标

定义章节视频合成阶段的标准管线，包括：

- 镜头拼接
- 旁白/对白/BGM 混音
- 字幕烧录或外挂
- 封面与预览图导出
- 最终母版与发布版生成

---

## 2. 输入资产

- `video/shots/*.mp4`
- `audio/mix/dialogue_bus.wav`
- `audio/mix/narration_bus.wav`
- `audio/mix/bgm_bus.wav`
- `subtitles/ep01.ass`
- `metadata/episode_timeline.json`

---

## 3. 章节拼接策略

### 3.1 视频拼接

推荐使用 concat demuxer：

`concat_shots.txt`

```text
file 'video/shots/ep01_sc01_sh01.mp4'
file 'video/shots/ep01_sc01_sh02.mp4'
file 'video/shots/ep01_sc01_sh03.mp4'
```

命令模板：

```bash
ffmpeg -y -f concat -safe 0 -i concat_shots.txt -c copy video/intermediate/ep01_concat.mp4
```

如果各镜头编码参数不一致，则改为 re-encode：

```bash
ffmpeg -y -f concat -safe 0 -i concat_shots.txt -vf fps=24 -c:v libx264 -pix_fmt yuv420p video/intermediate/ep01_concat.mp4
```

---

## 4. 音频混音策略

### 4.1 基本混音

```bash
ffmpeg -y   -i audio/mix/dialogue_bus.wav   -i audio/mix/narration_bus.wav   -i audio/mix/bgm_bus.wav   -filter_complex "[2:a]volume=0.18[bgm];[0:a][1:a][bgm]amix=inputs=3:duration=longest:normalize=0[aout]"   -map "[aout]"   audio/mix/episode_mix.wav
```

### 4.2 ducking

对白出现时压低 BGM：

- 先生成对白 activity envelope
- 再对 BGM 应用 sidechaincompress

---

## 5. 视频与音频合并

```bash
ffmpeg -y   -i video/intermediate/ep01_concat.mp4   -i audio/mix/episode_mix.wav   -c:v copy -c:a aac -b:a 192k   video/intermediate/ep01_av.mp4
```

---

## 6. 字幕方案

### 6.1 外挂字幕

优点：便于修改

```bash
ffmpeg -y -i video/intermediate/ep01_av.mp4 -i subtitles/ep01.ass -c copy -c:s ass video/final/ep01_with_subs.mkv
```

### 6.2 烧录字幕

优点：分发简单

```bash
ffmpeg -y -i video/intermediate/ep01_av.mp4 -vf "ass=subtitles/ep01.ass" -c:a copy video/final/ep01_burned.mp4
```

---

## 7. 预览版与母版

建议同时导出两套：

- 母版：高码率、保留字幕外挂
- 预览版：H.264、较低码率、烧录字幕

示例：

```bash
ffmpeg -y -i video/intermediate/ep01_av.mp4 -c:v libx264 -crf 18 -preset slow -c:a aac -b:a 256k video/final/ep01_master.mp4
ffmpeg -y -i video/intermediate/ep01_av.mp4 -vf scale=1280:-2 -c:v libx264 -crf 24 -preset medium -c:a aac -b:a 128k video/final/ep01_preview.mp4
```

---

## 8. 片头片尾策略

v1 不建议做复杂包装，但可预留：

- 片头 3 秒 logo
- 片尾 3 秒 credits

由 compose-worker 在 timeline 上自动插入。

---

## 9. 时间线文件建议

`episode_timeline.json` 应记录：

- 镜头起止时间
- 旁白起止时间
- 对白起止时间
- BGM cue 点
- 字幕起止时间

这样 FFmpeg 命令不需要重新从零推导。

---

## 10. 常见失败与修复

| 问题 | 原因 | 修复 |
|---|---|---|
| concat 失败 | 编码参数不一致 | 统一转码 |
| 音频不同步 | 片段时长误差 | 以音频为准调整视频 |
| 字幕偏移 | 时间轴生成错误 | 重建 ass 时间戳 |
| 音量爆音 | bus 未限幅 | 最终加 limiter |
