# 06 API 与服务接口设计

## 6.1 设计原则

1. API 只处理控制与查询，不直接承载大文件
2. 模型 worker 通过内部接口接收结构化 payload
3. 二进制文件路径由 orchestrator 分配
4. 所有请求带 `project_id` 与 `trace_id`
5. 接口幂等，重复调用可安全返回已有结果

---

## 6.2 顶层 API 列表

## 项目管理
- `POST /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/status`

## 文本阶段
- `POST /projects/{project_id}/generate/story-bible`
- `POST /projects/{project_id}/generate/character-bible`
- `POST /projects/{project_id}/generate/outline`
- `POST /projects/{project_id}/generate/chapter`
- `POST /projects/{project_id}/generate/script`

## 语音阶段
- `POST /projects/{project_id}/tts/episode/{episode_id}`
- `POST /projects/{project_id}/tts/line/{line_id}/retry`

## 图像阶段
- `POST /projects/{project_id}/images/character-refs`
- `POST /projects/{project_id}/images/keyframes/{episode_id}`
- `POST /projects/{project_id}/images/keyframes/{shot_id}/retry`

## 视频阶段
- `POST /projects/{project_id}/videos/shots/{episode_id}`
- `POST /projects/{project_id}/videos/shots/{shot_id}/retry`

## 合成阶段
- `POST /projects/{project_id}/compose/{episode_id}`
- `POST /projects/{project_id}/publish/{episode_id}`

## 质检与回滚
- `POST /projects/{project_id}/qc/{episode_id}`
- `POST /projects/{project_id}/rollback`
- `POST /projects/{project_id}/rerun/affected`

---

## 6.3 API 示例

## 6.3.1 创建项目

### Request
```json
{
  "name": "边城失忆剑客",
  "language": "zh-CN",
  "concept": "一个失忆的女剑客在边城酒馆醒来，发现自己被三方势力追杀。",
  "novel_style": "中文网文，电影感，略阴郁",
  "video_style": "写实，动态分镜",
  "target_duration_minutes": 8
}
```

### Response
```json
{
  "project_id": "proj_20260329_ab12cd",
  "status": "created",
  "next_actions": [
    "generate_story_bible",
    "generate_character_bible"
  ]
}
```

---

## 6.3.2 生成 story bible

### Request
```json
{
  "project_id": "proj_20260329_ab12cd",
  "config_override": {
    "theme_intensity": "medium"
  }
}
```

### Response
```json
{
  "task_id": "task_001",
  "status": "queued"
}
```

---

## 6.3.3 查询项目状态

### Response
```json
{
  "project_id": "proj_20260329_ab12cd",
  "status": "running",
  "current_stage": "video_generation",
  "progress": {
    "total_tasks": 84,
    "succeeded": 52,
    "failed": 2,
    "running": 1,
    "pending": 29
  },
  "episode_status": {
    "ep01": {
      "script": "succeeded",
      "tts": "succeeded",
      "keyframes": "running",
      "shots": "pending",
      "compose": "pending"
    }
  }
}
```

---

## 6.4 内部 worker 接口

### 6.4.1 LLM Worker

`POST /internal/llm/generate`

```json
{
  "task_type": "generate_script",
  "project_id": "proj_...",
  "context_files": [
    "text/story_bible/v1.json",
    "text/character_bible/v1.json",
    "text/chapters/ep01_draft_v1.md"
  ],
  "template_version": "script_v3",
  "output_schema": "ScriptLine[]",
  "output_path": "scripts/ep01/script_v1.jsonl"
}
```

### 6.4.2 TTS Worker

`POST /internal/tts/synthesize`

```json
{
  "line_id": "line_00031",
  "speaker": "沈鸦",
  "text": "我不记得自己是谁，但我知道，这不是我的血。",
  "voice_profile": {
    "engine": "fish_s2_pro",
    "ref_audio": "inputs/voice_refs/shenya.wav",
    "style_tags": ["[low voice]", "[restrained]"]
  },
  "output_path": "audio/ep01/raw/line_00031.wav"
}
```

### 6.4.3 Image Worker

`POST /internal/image/keyframe`

```json
{
  "shot_id": "S01_SH03",
  "visual_prompt": "close-up, female swordswoman, candlelight, blood on sleeve, cinematic realism",
  "negative_prompt": "deformed hands, extra fingers, blurry face",
  "character_refs": ["images/characters/shenya_ref_v2.png"],
  "control_inputs": {
    "pose": null,
    "depth": null
  },
  "output_path": "images/keyframes/ep01/S01_SH03/v1.png"
}
```

### 6.4.4 Video Worker

`POST /internal/video/i2v`

```json
{
  "shot_id": "S01_SH03",
  "image_path": "images/keyframes/ep01/S01_SH03/v1.png",
  "motion_prompt": "slow push-in, subtle breathing, candle flicker, restrained anger",
  "preset": "i2v_480p_fast",
  "duration_hint_sec": 4.0,
  "output_path": "videos/ep01/shots/S01_SH03/v1.mp4"
}
```

---

## 6.5 错误返回规范

统一结构：

```json
{
  "error_code": "GPU_OOM",
  "message": "Video generation failed due to out of memory.",
  "retryable": true,
  "task_id": "task_093",
  "details": {
    "preset": "i2v_720p",
    "fallback": "i2v_480p_fast"
  }
}
```

建议错误码：
- `INVALID_INPUT`
- `SCHEMA_VALIDATION_FAILED`
- `GPU_OOM`
- `MODEL_TIMEOUT`
- `ARTIFACT_NOT_FOUND`
- `DEPENDENCY_NOT_READY`
- `QC_FAILED`
- `COMPOSE_FAILED`

---

## 6.6 Webhook / 事件模型（可选）

v1 可以不做 webhook。  
如果后续扩展 UI，可以引入事件总线：

- `task.created`
- `task.started`
- `task.finished`
- `artifact.created`
- `artifact.activated`
- `qc.failed`
- `project.published`

---

## 6.7 权限与安全（本地版）

本地单用户版本可简化为：
- 仅本机访问
- CLI 或 localhost API
- 不做复杂鉴权

但仍建议：
- 限制 API 监听地址
- 不暴露内部 worker 到公网
- 文件路径做白名单限制
