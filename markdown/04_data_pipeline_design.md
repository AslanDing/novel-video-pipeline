# 04_数据流水线详细设计

## 一、Phase 1: 预生产

### 1.1 流程总览

```
用户输入: NovelConcept {title, genre, core_idea, chapters, word_count}
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: 生成故事蓝图 (Story Blueprint)                     │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 1.1 世界观生成 (World Building)                      │  │
│  │ 1.2 角色生成 (Characters)                           │  │
│  │ 1.3 修炼体系 (Power System)                        │  │
│  │ 1.4 情节结构 (Plot Structure)                      │  │
│  │ 1.5 章节规划 (Chapter Plans)                       │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: story_bible.json                                   │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: 生成章节正文 (Chapter Content)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每章:                                               │  │
│  │   - 如果字数 > 2000, 自适应分块生成                    │  │
│  │   - 质量评估 + 可选重写 (最多 3 次)                   │  │
│  │   - 保存 chapter_xxx.md + chapter_xxx_summary.json   │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: data/chapters/chapter_*.md + chapter_*_summary.json │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3: 生成分镜脚本 (Shot List)                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每章:                                               │  │
│  │   - 调用 LLM 将章节正文拆分为分镜                     │  │
│  │   - 输出 JSONL 格式到 data/scripts/script_*.jsonl    │  │
│  │   - 每个分镜包含: scene_id, shot_id, role, speaker,   │  │
│  │     text, emotion, visual_prompt, motion_prompt,     │  │
│  │     camera, estimated_duration                        │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: data/scripts/script_*.jsonl                         │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 4: 生成角色资产包 (Character Pack)                    │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每个角色:                                           │  │
│  │   - 用角色 appearance 生成定妆照 (ComfyUI t2i)       │  │
│  │   - 可选: 表情组、服饰参考                           │  │
│  │   - 保存到 assets/characters/{char_id}/             │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: assets/characters/{char_id}/portrait.png            │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 5: 生成场景资产包 (Scene Pack)                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每个重要场景:                                        │  │
│  │   - 用 scene prompt 生成场景图 (ComfyUI t2i)         │  │
│  │   - 保存到 assets/scenes/{scene_id}/                 │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: assets/scenes/{scene_id}/                           │
└──────────────────────────────────────────────────────────────┘
```

### 1.2 故事蓝图生成详细流程

```python
async def generate_story_blueprint(concept: NovelConcept) -> StoryBlueprint:
    """分步生成故事蓝图"""

    # Step 1: 世界观
    world_data, ok = await robust_json_generate(
        llm_client=self.llm_client,
        prompt=render_prompt("world_building", **asdict(concept)),
        system_prompt=get_system_prompt("world_building"),
        max_tokens=4000,
        required_fields=["setting", "factions", "rules"]
    )
    if not ok:
        raise ValueError("世界观生成失败")

    world_building = WorldBuilding(**world_data)

    # Step 2: 角色 (依赖世界观的 setting)
    char_data, ok = await robust_json_generate(
        llm_client=self.llm_client,
        prompt=render_prompt("characters", setting=world_building.setting, ...),
        system_prompt=get_system_prompt("characters"),
        max_tokens=4000,
        required_fields=["characters"]
    )

    # Step 3: 修炼体系
    power_data, ok = await robust_json_generate(...)

    # Step 4: 情节结构
    plot_data, ok = await robust_json_generate(...)

    # Step 5: 章节规划
    plans_data, ok = await robust_json_generate(...)

    return StoryBlueprint(...)
```

### 1.3 章节正文分块生成

```python
CHUNK_WORD_COUNT = 2000

async def generate_chapter_with_chunking(
    chapter_plan: ChapterPlan,
    previous_content: str,
    blueprint: StoryBlueprint,
    target_words: int = 5000
) -> Chapter:
    """
    使用分块策略生成章节正文
    """
    num_chunks = ceil(target_words / CHUNK_WORD_COUNT)

    if num_chunks <= 1:
        # 单次生成
        return await _generate_single_chunk(chapter_plan, previous_content, blueprint)
    else:
        # 分块生成
        chunks = []
        for i in range(num_chunks):
            is_first = (i == 0)
            is_last = (i == num_chunks - 1)

            chunk = await _generate_chunk(
                chapter_plan=chapter_plan,
                previous_content="\n".join(chunks) if chunks else previous_content,
                blueprint=blueprint,
                chunk_index=i,
                is_first=is_first,
                is_last=is_last
            )
            chunks.append(chunk)

        content = "\n".join(chunks)

        # 质量评估
        score = await quality_controller.evaluate(content, blueprint)
        if score.overall < 5.0 and score.retry_count < 3:
            # 重写
            content = await quality_controller.rewrite(content, score.issues)

        return Chapter(content=content, ...)
```

### 1.4 分镜脚本生成

**必须恢复 `_adapt_to_script` 方法**：

```python
async def generate_script_for_chapter(
    chapter: Chapter,
    characters: List[Character]
) -> List[ScriptLine]:
    """
    将章节正文拆分为分镜脚本

    这是数据流断裂的核心修复点！
    必须确保 script_*.jsonl 被正确生成。
    """
    # 构建角色外观描述（用于 visual_prompt）
    character_appearances = {
        c.name: c.appearance for c in characters
    }

    # 调用 LLM 生成分镜
    system_prompt, user_prompt = render_prompt("shot_list",
        chapter_title=chapter.title,
        chapter_content=chapter.content,
        character_appearances=yaml.dump(character_appearances)
    )

    response = await self.llm_client.generate(
        prompt=user_prompt,
        system_prompt=system_prompt,
        max_tokens=16000,
        response_format={"type": "json_object"}
    )

    # 解析 JSONL
    script_lines = []
    raw_content = response.content

    # 方法1: 直接按行解析（每行一个 JSON）
    for line in raw_content.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            # 尝试解析行
            data = json.loads(line)
            script_lines.append(ScriptLine(**data))
        except json.JSONDecodeError:
            # 方法2: 尝试提取 markdown 代码块
            match = re.search(r'\{[^{}]*"shot_id"[^{}]*\}', line)
            if match:
                try:
                    data = json.loads(match.group(0))
                    script_lines.append(ScriptLine(**data))
                except:
                    logger.warning(f"无法解析分镜行: {line[:100]}")
            else:
                logger.warning(f"无法解析分镜行: {line[:100]}")

    # 写入标准位置
    script_path = self.storage.get_scripts_dir() / f"script_{chapter.number:03d}.jsonl"
    with open(script_path, 'w', encoding='utf-8') as f:
        for line in script_lines:
            f.write(json.dumps(asdict(line), ensure_ascii=False) + '\n')

    return script_lines
```

---

## 二、Phase 2: 正式生产

### 2.1 流程总览

```
Phase 1 产出:
  - data/scripts/script_*.jsonl
  - assets/characters/{char_id}/portrait.png
  - assets/scenes/{scene_id}/
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: TTS 先生成 (Audio-First)                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 读取 script_*.jsonl                                   │  │
│  │ 对每个 shot:                                          │  │
│  │   - 调用 EdgeTTS / Fish Audio 生成音频               │  │
│  │   - 保存到 audio/chapter_xxx/segments/               │  │
│  │   - 生成 timeline_manifest.json                       │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: audio/chapter_xxx/segments/*.mp3 + timeline.json    │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: 生成关键帧 (Keyframes)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每个 shot:                                          │  │
│  │   - 读取 visual_prompt                                │  │
│  │   - 读取角色/场景资产引用                             │  │
│  │   - 调用 ComfyUI t2i 生成关键帧                       │  │
│  │   - 保存到 images/chapter_xxx/                        │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: images/chapter_xxx/keyframe_*.png                   │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3: 生成视频片段 (Shot Videos)                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 对每个 shot:                                          │  │
│  │   - 读取关键帧 + motion_prompt                        │  │
│  │   - 调用 ComfyUI i2v (SVD) 生成视频                  │  │
│  │   - 保存到 videos/chapter_xxx/                        │  │
│  └──────────────────────────────────────────────────────┘  │
│  输出: videos/chapter_xxx/shot_*.mp4                      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 TTS 先生成的理由

```
传统流程 (错误):
  图像生成 → 视频生成 → TTS 配音
  问题: 视频长度和音频长度不匹配

新流程 (正确):
  TTS 先生成 → 得到精确的音频时长 → 视频片段数量和时长已知
  TTS → 关键帧 → 视频 (每个视频片段时长 = 对应音频时长)
```

### 2.3 TTS 处理逻辑

```python
async def process_tts_for_chapter(
    chapter_number: int,
    script_lines: List[ScriptLine],
    voice_map: Dict[str, str]  # character_name -> voice_id
) -> TimelineManifest:
    """
    TTS 处理核心逻辑
    """
    segments = []
    timeline_entries = []
    current_time = 0.0

    for shot in script_lines:
        # 确定使用的 voice
        if shot.role == "narrator":
            voice = voice_map.get("narrator", "zh-CN-XiaoxiaoNeural")
        else:
            voice = voice_map.get(shot.speaker, "zh-CN-XiaoxiaoNeural")

        # 调用 TTS
        audio_data = await tts_engine.generate(
            text=shot.text,
            voice=voice,
            emotion=shot.emotion,
            speed=1.0
        )

        # 保存音频片段
        segment_path = audio_dir / f"segment_{shot.shot_id}.mp3"
        with open(segment_path, 'wb') as f:
            f.write(audio_data)

        # 获取实际音频时长
        duration = get_audio_duration(segment_path)

        # 添加 timeline entry
        timeline_entries.append(TimelineEntry(
            shot_id=shot.shot_id,
            scene_id=shot.scene_id,
            audio_file=str(segment_path),
            start_time=current_time,
            end_time=current_time + duration,
            text=shot.text,
            subtitle=shot.text[:50] + "..." if len(shot.text) > 50 else shot.text
        ))

        current_time += duration

    # 合并音频
    combined_path = audio_dir / "combined.mp3"
    await merge_audio_segments([e.audio_file for e in timeline_entries], combined_path)

    # 保存 timeline manifest
    manifest = TimelineManifest(
        chapter=chapter_number,
        total_duration=current_time,
        entries=timeline_entries
    )

    manifest_path = audio_dir / f"timeline_ch{chapter_number:03d}.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(asdict(manifest), f, ensure_ascii=False)

    return manifest
```

### 2.4 关键帧生成逻辑

```python
async def generate_keyframes_for_chapter(
    chapter_number: int,
    script_lines: List[ScriptLine],
    character_packs: Dict[str, CharacterPack],
    scene_packs: Dict[str, ScenePack]
) -> List[GeneratedImage]:
    """
    关键帧生成核心逻辑

    使用 InstantID 保持角色一致性
    """
    images = []

    for shot in script_lines:
        # 构建 visual_prompt
        prompt = build_visual_prompt(
            shot.visual_prompt,
            shot.characters,  # 需要在 shot 中添加 characters 字段
            character_packs,
            scene_packs
        )

        # 确定角色参考图
        character_refs = []
        if shot.characters:
            for char_name in shot.characters:
                char_pack = character_packs.get(char_name)
                if char_pack and char_pack.portrait:
                    character_refs.append(char_pack.portrait)

        # 确定场景参考图
        scene_ref = None
        if shot.scene in scene_packs:
            scene_ref = scene_packs[shot.scene].wide

        # 调用 ComfyUI
        image_paths = await image_backend.generate(
            prompt=prompt,
            character_refs=character_refs,  # InstantID
            scene_ref=scene_ref,
            width=1024,
            height=1024,
            steps=30
        )

        # 保存
        for i, path in enumerate(image_paths):
            dest_path = images_dir / f"keyframe_{shot.shot_id}_{i}.png"
            shutil.copy(path, dest_path)
            images.append(GeneratedImage(
                image_id=f"ch{chapter_number}_img_{shot.shot_id}",
                shot_id=shot.shot_id,
                file_path=str(dest_path),
                width=1024,
                height=1024
            ))

    return images
```

### 2.5 视频片段生成逻辑

```python
async def generate_videos_for_chapter(
    chapter_number: int,
    keyframes: List[GeneratedImage],
    timeline: TimelineManifest
) -> List[Path]:
    """
    视频片段生成核心逻辑

    使用 SVD 图生视频
    """
    videos = []

    for entry in timeline.entries:
        # 查找对应的关键帧
        kf_path = find_keyframe_for_shot(entry.shot_id, keyframes)
        if not kf_path:
            logger.warning(f"未找到 shot {entry.shot_id} 的关键帧")
            continue

        # 计算视频时长 = 音频时长
        duration = entry.end_time - entry.start_time
        num_frames = min(25, max(14, int(duration * 10)))  # SVD 支持 14-25 帧

        # 生成视频
        video_path = videos_dir / f"shot_{entry.shot_id}.mp4"

        await video_backend.generate(
            image_path=kf_path,
            motion_prompt=get_motion_prompt_for_shot(entry.shot_id),
            num_frames=num_frames,
            fps=24,
            output_path=video_path
        )

        videos.append(video_path)

    return videos
```

---

## 三、Phase 3: 后期合成

### 3.1 流程总览

```
Phase 2 产出:
  - videos/chapter_xxx/shot_*.mp4
  - audio/chapter_xxx/combined.mp3
  - audio/chapter_xxx/timeline_ch*.json
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 1: 视频拼接 (Video Concatenation)                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 按 timeline 时间线拼接视频片段                         │  │
│  │ 生成: chapter_xxx_raw.mp4 (无音频)                  │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 2: 音频混合 (Audio Mixing)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 混合: combined.mp3 (对白) + BGM + SFX               │  │
│  │ 生成: chapter_xxx_audio_mixed.mp3                   │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 3: 音视频合并 (Combine AV)                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 合并视频 + 混合音频                                   │  │
│  │ 生成: chapter_xxx_av.mp4                            │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
                │
                ▼
┌──────────────────────────────────────────────────────────────┐
│  Step 4: 字幕烧录 (Subtitle Burn-in)                        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ 从 timeline 生成 SRT 字幕                             │  │
│  │ 烧录到视频中                                          │  │
│  │ 生成: final/chapter_xxx.mp4                         │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 FFmpeg 合成命令

```python
async def compose_final_video(
    timeline: TimelineManifest,
    video_dir: Path,
    audio_dir: Path,
    output_dir: Path,
    resolution: Tuple[int, int] = (1280, 720),
    fps: int = 24
) -> Path:
    """
    使用 FFmpeg 合成最终视频
    """

    # Step 1: 构建 concat 输入文件（按 timeline 顺序拼接视频）
    with open("video_list.txt", 'w') as f:
        for entry in timeline.entries:
            video_path = video_dir / f"shot_{entry.shot_id}.mp4"
            if not video_path.exists():
                logger.warning(f"视频不存在: {video_path}")
                continue
            duration = entry.end_time - entry.start_time
            safe_path = str(video_path).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")
            f.write(f"duration {duration}\n")
        # 最后一帧重复以结束视频
        last_video = video_dir / f"shot_{timeline.entries[-1].shot_id}.mp4"
        if last_video.exists():
            f.write(f"file '{str(last_video).replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")

    # Step 2: 拼接视频
    raw_video = output_dir / "chapter_raw.mp4"
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", "video_list.txt",
        "-c:v", "libx264", "-preset", "fast",
        "-r", str(fps),
        "-i", "chapter_raw.mp4"  # 占位
    ]
    await run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                   "-i", "video_list.txt", "-c", "copy", str(raw_video)])

    # Step 3: 合并音视频
    av_video = output_dir / "chapter_av.mp4"
    cmd_av = [
        "ffmpeg", "-y",
        "-i", str(raw_video),
        "-i", str(audio_dir / "combined.mp3"),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(av_video)
    ]
    await run_cmd(cmd_av)

    # Step 4: 生成字幕
    srt_path = output_dir / "chapter.srt"
    generate_srt(timeline, srt_path)

    # Step 5: 烧录字幕
    final_video = output_dir / "final" / f"chapter_{timeline.chapter:03d}.mp4"
    final_video.parent.mkdir(parents=True, exist_ok=True)

    cmd_subtitle = [
        "ffmpeg", "-y",
        "-i", str(av_video),
        "-vf", f"subtitles={srt_path}:force_style='FontName=Noto Sans CJK SC,FontSize=24'",
        "-c:a", "copy",
        str(final_video)
    ]
    await run_cmd(cmd_subtitle)

    return final_video
```

### 3.3 字幕生成

```python
def generate_srt(timeline: TimelineManifest, output_path: Path) -> Path:
    """生成 SRT 格式字幕"""

    lines = []
    for i, entry in enumerate(timeline.entries, 1):
        start = format_srt_time(entry.start_time)
        end = format_srt_time(entry.end_time)
        text = entry.subtitle or entry.text

        lines.extend([
            str(i),
            f"{start} --> {end}",
            text,
            ""
        ])

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path

def format_srt_time(seconds: float) -> str:
    """格式化 SRT 时间: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
```

---

## 四、数据格式规范

### 4.1 ScriptLine 数据类

```python
@dataclass
class ScriptLine:
    scene_id: str          # "SC01"
    shot_id: str           # "SC01_SH01"
    role: str              # "dialogue" / "narrator"
    speaker: str           # "林云" / "旁白"
    text: str              # 实际对白/旁白
    emotion: str           # "happy" / "sad" / "angry" / "calm" / "neutral" / "excited"
    visual_prompt: str     # 英文图像 prompt
    motion_prompt: str     # 镜头运动描述
    camera: str            # "wide" / "medium" / "close-up" / "extreme close-up"
    estimated_duration: float  # 预估时长(秒)

    # 新增字段（用于 Phase 2）
    characters: List[str] = field(default_factory=list)  # 出现的角色名列表
```

### 4.2 TimelineManifest 数据类

```python
@dataclass
class TimelineManifest:
    chapter: int
    total_duration: float
    entries: List[TimelineEntry]

@dataclass
class TimelineEntry:
    shot_id: str
    scene_id: str
    audio_file: str
    start_time: float
    end_time: float
    text: str
    subtitle: str
```

### 4.3 CharacterPack 数据类

```python
@dataclass
class CharacterPack:
    character_id: str
    name: str
    portrait: Optional[Path] = None       # 定妆照
    face_ref: Optional[Path] = None      # 脸部参考
    expressions_dir: Optional[Path] = None  # 表情组目录

    @property
    def portrait_prompt(self) -> str:
        """从定妆照提取 IP-Adapter prompt"""
        if self.portrait:
            return f"<ipadapter:path={self.portrait}:weight=0.8>"
        return ""
```

---

*文档版本: v1.0*
*创建时间: 2026-04-14*
