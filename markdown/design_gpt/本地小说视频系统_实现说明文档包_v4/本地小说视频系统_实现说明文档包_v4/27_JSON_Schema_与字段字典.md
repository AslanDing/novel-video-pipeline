# 27 JSON Schema 与字段字典

## 1. 目标

本文件给出 v1 核心 JSON 契约，供：

- FastAPI 请求/响应
- Worker 入参与出参
- 文件落盘结构
- 调试工具与 review console
- 后续 Pydantic 模型生成

---

## 2. ProjectConfig Schema

```json
{
  "project_id": "proj_001",
  "name": "边城女剑客",
  "language": "zh-CN",
  "target_runtime_min": 10,
  "target_style": "dark cinematic wuxia",
  "llm_profile": "qwen3_14b_instruct_awq",
  "tts_profile": "fish_s2_pro_default",
  "image_profile": "sd35m_ipadapter_v1",
  "video_profile": "hunyuan_i2v_480p_sd_v1",
  "review_mode": "script_and_final",
  "created_at": "2026-03-29T12:00:00Z"
}
```

字段字典：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| project_id | string | 是 | 项目标识 |
| language | string | 是 | 主语言，如 zh-CN |
| target_runtime_min | int | 是 | 目标成片分钟数 |
| llm_profile | string | 是 | 模型配置档名称 |
| review_mode | enum | 是 | `none/script_only/script_and_final/full` |

---

## 3. ShotSpec Schema

```json
{
  "episode_id": "ep01",
  "scene_id": "sc02",
  "shot_id": "ep01_sc02_sh05",
  "shot_index": 5,
  "shot_type": "dialogue_closeup",
  "speaker": "女剑客",
  "narration_text": "她抬起眼时，烛火在瞳孔里轻轻颤了一下。",
  "dialogue_text": "我不记得自己是谁。",
  "emotion": ["cold", "restrained"],
  "visual_focus": "close-up on face and blood-stained sleeve",
  "camera": {
    "framing": "close-up",
    "movement": "slow push-in",
    "lens_hint": "50mm",
    "angle": "eye-level"
  },
  "duration_hint_sec": 4.0,
  "requires_keyframe_review": true,
  "tags": ["tavern", "night", "blood", "memory_loss"]
}
```

---

## 4. AudioSegment Schema

```json
{
  "segment_id": "aud_ep01_sc02_sh05_dlg",
  "shot_id": "ep01_sc02_sh05",
  "speaker": "女剑客",
  "text": "我不记得自己是谁。",
  "voice_profile": "swordswoman_v1",
  "style_tags": ["low", "restrained"],
  "sample_rate": 44100,
  "duration_ms": 3180,
  "wav_path": "audio/raw/aud_ep01_sc02_sh05_dlg.wav",
  "transcript_check": {
    "enabled": true,
    "status": "passed",
    "asr_text": "我不记得自己是谁。"
  }
}
```

---

## 5. KeyframeSpec Schema

```json
{
  "keyframe_id": "kf_ep01_sc02_sh05_v2",
  "shot_id": "ep01_sc02_sh05",
  "source_type": "generated",
  "character_refs": [
    "assets/characters/swordswoman/front.png"
  ],
  "scene_refs": [
    "assets/backgrounds/tavern_night_v1.png"
  ],
  "control_refs": {
    "pose": null,
    "depth": null,
    "edge": null
  },
  "prompt_ref": "prompts/image/ep01_sc02_sh05_v2.json",
  "image_path": "assets/keyframes/ep01_sc02_sh05_v2.png",
  "review_status": "approved"
}
```

---

## 6. ShotVideoSchema

```json
{
  "video_id": "vid_ep01_sc02_sh05_v1",
  "shot_id": "ep01_sc02_sh05",
  "input_keyframe_id": "kf_ep01_sc02_sh05_v2",
  "video_profile": "hunyuan_i2v_480p_sd_v1",
  "fps": 24,
  "frame_count": 97,
  "duration_ms": 4041,
  "video_path": "video/shots/ep01_sc02_sh05_v1.mp4",
  "qc": {
    "flicker_score": 0.11,
    "face_consistency_score": 0.82,
    "motion_match_score": 0.76,
    "overall_score": 0.79,
    "passed": true
  }
}
```

---

## 7. StageResult Schema

所有 worker 必须返回统一结果结构：

```json
{
  "job_id": "job_123",
  "task_id": "task_456",
  "stage": "image_generate",
  "status": "succeeded",
  "started_at": "2026-03-29T12:10:00Z",
  "finished_at": "2026-03-29T12:13:21Z",
  "inputs": {
    "shot_id": "ep01_sc02_sh05"
  },
  "outputs": {
    "artifact_ids": ["kf_ep01_sc02_sh05_v2"]
  },
  "metrics": {
    "gpu_seconds": 135,
    "retry_count": 1
  },
  "warnings": [],
  "errors": []
}
```

---

## 8. 字段命名约定

- ID 一律使用 snake_case 前缀：`proj_`、`ep_`、`sc_`、`sh_`、`kf_`、`vid_`
- 时间统一 ISO 8601 UTC
- 时长统一使用毫秒字段 `*_ms`
- 布尔字段使用 `is_` 或语义性名词，如 `passed`
- 文件路径一律存相对路径，由 `artifact_root` 解析

---

## 9. 演进原则

- 新增字段只能追加，不能直接删除旧字段
- 破坏性变更必须提升 `schema_version`
- worker 必须在响应中回传 `schema_version`
- review-console 只读取公开字段，不读取模型私有输出
