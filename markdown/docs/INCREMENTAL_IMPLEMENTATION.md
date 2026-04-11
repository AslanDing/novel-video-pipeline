# 增量实现进度总结 (2026-03-30)

## 本次实现的新功能

### 1. 跨阶段数据模型 ✅
**文件**: `stages/models.py`
- `ScriptLine` - 分镜脚本行
- `TimelineEntry` / `TimelineManifest` - 时间线清单
- `CharacterPortrait` - 角色定妆照
- 加载/保存函数

### 2. Stage 2: 图像生成 ✅
**新增文件**: `stages/stage2_visual/script_adapter.py`
- `ScriptAdapter` - 读取 Stage 1 产出的 `script_x.jsonl`
- `CharacterPortraitManager` - 角色定妆照管理
- `load_story_bible()` - 加载故事圣经

### 3. Stage 3: 音频生成 ✅
**新增文件**: `stages/stage3_audio/tts_script_adapter.py`
- `TTSScriptAdapter` - 解析 script_x.jsonl 进行逐行生成
- `TimelineGenerator` - 生成 `timeline_manifest.json`
- `BGMMatcher` - 根据情感自动匹配 BGM
- `SFXMatcher` - 根据场景关键词自动添加音效

### 4. Stage 4: 视频合成 ✅
**新增文件**: `stages/stage4_merge/timeline_composer.py`
- `TimelineComposer` - 读取 timeline_manifest.json
- `TimelineVideoComposer` - 基于时间线的视频合成
- SRT 字幕生成

## 流程改进

### 改进前 (各阶段独立)
```
Stage 1: 小说生成 → novel.json
Stage 2: 从 LLM 提取场景 → images/
Stage 3: 按段落生成音频 → audio/
Stage 4: 均分时长合成视频 → videos/
```

### 改进后 (数据驱动)
```
Stage 1: 小说生成 → script_x.jsonl (包含 visual_prompt, text, speaker)
Stage 2: 读取 script_x.jsonl → 使用 visual_prompt 生成图片
Stage 3: 读取 script_x.jsonl → 逐行生成音频 + timeline_chXX.json (真实时长)
Stage 4: 读取 timeline_chXX.json → 精确对齐音视频合成
```

## 新增文件列表

```
stages/
├── models.py                          # 跨阶段共享数据模型
├── stage2_visual/
│   └── script_adapter.py             # 脚本读取 + 角色定妆照
├── stage3_audio/
│   └── tts_script_adapter.py         # TTS脚本适配 + 时间线 + BGM/SFX
└── stage4_merge/
    └── timeline_composer.py          # 时间线驱动的视频合成
```

## 使用方式

### Stage 2 读取脚本
```python
from stages.stage2_visual.script_adapter import ScriptAdapter

adapter = ScriptAdapter("小说标题", data_dir)
script_lines = adapter.load_script_lines(chapter_number=1)
prompts = adapter.extract_visual_prompts(script_lines)
```

### Stage 3 生成时间线
```python
from stages.stage3_audio.tts_script_adapter import TimelineGenerator

generator = TimelineGenerator(audio_dir)
manifest = generator.create_timeline(chapter_number, script_lines, audio_files)
generator.save_timeline(manifest, chapter_number)
```

### Stage 4 使用时间线
```python
from stages.stage4_merge.timeline_composer import TimelineComposer

composer = TimelineComposer("小说标题", output_dir)
timeline = composer.load_timeline(chapter_number, audio_dir)
segments = composer.build_video_segments(images_dir)
```

## 后续任务

- [ ] 在 ImageGenerator.process() 中集成 ScriptAdapter
- [ ] 在 TTSEngine.process() 中集成 TTSScriptAdapter
- [ ] 在 VideoComposer 中集成 TimelineComposer
- [ ] 端到端测试完整流程