# 18_工作流DSL与模板系统设计

## 1. 为什么要有 Workflow DSL

你之前强调过一个核心诉求：用户希望高度控制 workflow，而不是完全交给 agent 自主规划。要实现这一点，系统不能把流程硬编码在 Python 里，而是要有一套：

- 可读
- 可编辑
- 可验证
- 可调试
- 可扩展

的 workflow 描述方式。

---

## 2. 设计目标

- 用户可通过 markdown / yaml 描述流程
- 支持阶段、依赖、分支、重试、人工审批
- 支持参数引用与变量注入
- 支持模板复用
- 支持渲染成实际任务 DAG

---

## 3. 建议形式：Markdown Front Matter + YAML Block

示例：

```markdown
# workflow: novel_to_video_v1

## meta
name: 本地小说到视频标准流程
version: 1.0
entrypoint: generate_episode

## steps
- id: story_bible
  uses: llm.generate_story_bible
  output: story_bible

- id: outline
  uses: llm.generate_outline
  needs: [story_bible]
  output: episode_outline

- id: novel
  uses: llm.generate_novel
  needs: [outline]
  output: chapter_novel

- id: script
  uses: llm.generate_script
  needs: [novel]
  output: script_jsonl

- id: tts
  foreach: script.segments
  uses: tts.synthesize_segment
  needs: [script]

- id: keyframe
  foreach: script.shots
  uses: image.generate_keyframe
  needs: [script]

- id: i2v
  foreach: script.shots
  uses: i2v.generate_shot_video
  needs: [keyframe]

- id: compose
  uses: compose.compose_episode
  needs: [tts, i2v]
```

---

## 4. DSL 核心能力

### 4.1 step
一个可执行节点。

字段：
- `id`
- `uses`
- `needs`
- `if`
- `foreach`
- `with`
- `retries`
- `approval`
- `on_fail`

### 4.2 uses
指向一个稳定的能力标识：
- `llm.generate_story_bible`
- `tts.synthesize_segment`
- `image.generate_keyframe`

这样 workflow 不依赖某个具体模型实现。

### 4.3 with
给 step 注入参数。

### 4.4 foreach
把一个 step 映射成多个任务实例。
例如：
- 对每个 shot 生成关键帧
- 对每个 segment 生成 TTS

### 4.5 if
条件执行。
例如：
- 如果没有角色参考图，则先执行角色基础图生成

### 4.6 approval
标记该 step 是否需要人工审批。

---

## 5. Workflow 编译过程

```mermaid
flowchart LR
A[Markdown Workflow] --> B[Parser]
B --> C[AST]
C --> D[Validator]
D --> E[Expanded DAG]
E --> F[Task Instances]
```

---

## 6. 验证规则

- step id 唯一
- `needs` 依赖必须存在
- `uses` 必须映射到已注册 plugin
- `foreach` 的数据路径必须合法
- `approval` 节点后必须定义继续条件
- 不允许循环依赖

---

## 7. 模板系统

### 7.1 系统模板
- `novel_to_video_standard`
- `novel_to_video_dialogue_heavy`
- `novel_to_video_visual_first`
- `audio_novel_only`

### 7.2 项目模板
用户可在系统模板基础上派生项目模板。

### 7.3 变量注入
模板中可引用：
- `project.style_profile`
- `episode.target_duration`
- `runtime.default_resolution`

---

## 8. 调试能力

Workflow UI 要支持：
- 查看展开前模板
- 查看展开后 DAG
- 查看每个 step 实例化结果
- 查看 skipped / waiting / approved 状态

---

## 9. 示例：带人工审批的流程

```yaml
- id: character_reference_images
  uses: image.generate_character_reference
  approval: manual

- id: script
  uses: llm.generate_script
  needs: [character_reference_images]
```

含义：
- 只有角色设定图被人工确认后，才允许往后生成脚本或关键帧

---

## 10. 实现建议

- 先支持有限 DSL，不要一开始做成通用编程语言
- parser、validator、expander 分层实现
- workflow 文件也要版本化
- 把运行时展开结果保存下来，便于复现

---

## 11. 评审 checklist

- DSL 是否足够表达你的 workflow 控制诉求
- 是否避免把编排逻辑硬编码
- 是否支持 foreach / if / approval / retries
- 是否能编译成 task DAG
- 是否可视化和可调试
