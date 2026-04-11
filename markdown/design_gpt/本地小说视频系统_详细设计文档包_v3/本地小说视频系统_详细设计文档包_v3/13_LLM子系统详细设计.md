# 13_LLM子系统详细设计

## 1. 子系统目标

LLM 子系统不是一个“统一聊天入口”，而是承担以下多个角色：

- 故事策划器：生成 story bible、角色设定、章节大纲
- 小说生成器：生成章节正文
- 改编器：把正文改写为可生产脚本
- 提示词重写器：把镜头说明改写成图像与视频模型友好的 prompt
- 审校器：做一致性检查、摘要、回顾和修复建议

因此，LLM 子系统应当内部再分成多个能力角色，而不是所有任务共用一个 prompt。

---

## 2. 内部能力模块

```mermaid
flowchart LR
A[Concept Input] --> B[Planner Prompt Chain]
B --> C[Story Bible Generator]
C --> D[Outline Generator]
D --> E[Novel Generator]
E --> F[Adaptation Generator]
F --> G[Prompt Rewrite Generator]
G --> H[Consistency Checker]
```

---

## 3. 任务划分

### 3.1 GenerateStoryBible
输入：
- 用户构思
- 风格要求
- 篇幅目标
- 禁忌项

输出：
- 世界观
- 主题
- 主线
- 支线
- 时间线
- 角色约束
- 风格约束

### 3.2 GenerateEpisodeOutline
输入：
- story bible
- 目标章节范围

输出：
- 章节梗概
- 章节冲突
- cliffhanger
- 出场角色
- 关键场景

### 3.3 GenerateChapterNovel
输入：
- story bible
- 上下文摘要
- 当前章节 outline
- 文风要求

输出：
- 章节正文 markdown

### 3.4 GenerateScript
输入：
- 章节正文
- 角色设定
- 节奏策略
- 视频生产约束

输出：
- 场景列表
- 镜头列表
- 台词
- 旁白
- 视觉说明
- 动作说明
- 目标时长

### 3.5 RewritePrompt
输入：
- shot spec
- visual profile
- video style profile

输出：
- image prompt
- negative prompt
- motion prompt
- camera prompt

### 3.6 ConsistencyCheck
输入：
- 当前章节正文
- 角色档案
- 前文摘要

输出：
- 一致性警告
- 逻辑冲突点
- 建议修复项

---

## 4. Prompt Chain 设计原则

### 4.1 一阶段只完成一类任务
不要让一个 prompt 同时生成：
- 章节正文
- 角色设定
- 分镜脚本
- prompt 重写

这会造成：
- 输出格式不稳
- 可重跑粒度太粗
- 难以做质量控制

### 4.2 必须显式输出结构
所有生产型任务都先输出 JSON，再生成给人看的 markdown。
原因：
- JSON 便于下游消费
- markdown 便于人工审阅

### 4.3 长文本要通过摘要上下文传递
不要把所有前文原样塞入上下文。要维护：
- `running_summary`
- `character_memory`
- `open_loops`
- `forbidden_conflicts`

---

## 5. 上下文构建器

### 5.1 Context Pack
为不同任务动态构造 context pack：

```json
{
  "story_core": "...",
  "character_constraints": [...],
  "prior_episode_summary": "...",
  "open_questions": [...],
  "current_goal": "...",
  "format_contract": {...}
}
```

### 5.2 上下文来源
- story bible 当前版本
- outline 当前版本
- 上一章摘要
- 角色记忆摘要
- 用户手工修订内容
- 风格模板

### 5.3 长度控制
按优先级裁剪：
1. 当前章节 outline
2. 角色硬约束
3. 前文摘要
4. 风格参考
5. 远期支线摘要

---

## 6. 输出契约

### 6.1 Story Bible JSON

```json
{
  "theme": "",
  "world_rules": [],
  "major_factions": [],
  "timeline": [],
  "characters": [],
  "narrative_constraints": [],
  "style_rules": []
}
```

### 6.2 Script JSONL
每行一个 shot 或 narration 段：

```json
{
  "scene_id": "SC01",
  "shot_id": "SC01_SH02",
  "segment_type": "dialogue",
  "speaker": "女剑客",
  "text": "……",
  "emotion": ["cold", "restrained"],
  "visual_intent": "close-up in tavern",
  "motion_intent": "slow lift head",
  "duration_hint_sec": 3.8
}
```

---

## 7. 失败模式

### 7.1 格式失败
模型没有输出合法 JSON。
处理：
- 尝试 repair parser
- 失败则 fallback 到强结构化 prompt 重试

### 7.2 内容失败
输出内容违反角色或世界观约束。
处理：
- 进入 consistency check
- 若严重，任务失败并产出修复建议

### 7.3 节奏失败
脚本拆分过长，不适合 I2V。
处理：
- 自动触发 script splitter，把 6 秒以上镜头继续拆分

---

## 8. Prompt 模板体系

建议把模板拆成：
- `story_bible.system.j2`
- `story_bible.user.j2`
- `outline.system.j2`
- `novel.system.j2`
- `script.system.j2`
- `rewrite_image_prompt.system.j2`
- `rewrite_motion_prompt.system.j2`
- `consistency_check.system.j2`

模板变量统一由 context pack 提供，不允许随意拼接自由字符串。

---

## 9. 质量评分

对每个 LLM 结果做轻量评分：
- JSON 合法性
- 字段完整性
- 角色引用合法性
- 时长预估合理性
- 风格匹配度（可选）

评分不足则自动重试或人工审批。

---

## 10. 版本管理

LLM 结果建议区分：
- raw_output
- repaired_output
- normalized_output
- approved_output

只有 approved 版本可以进入下游。

---

## 11. 接口设计

### 请求
`POST /internal/llm/tasks`

```json
{
  "task_type": "generate_script",
  "project_id": "p1",
  "scope_id": "ep01",
  "input_refs": [...],
  "context_pack": {...},
  "output_contract": "script_v1"
}
```

### 响应
```json
{
  "task_id": "t123",
  "status": "accepted"
}
```

### 完成回调
```json
{
  "task_id": "t123",
  "status": "succeeded",
  "artifact_refs": [...],
  "metrics": {
    "tokens_in": 12000,
    "tokens_out": 3600,
    "latency_ms": 8120
  }
}
```

---

## 12. 详细 workflow

1. 读取 story bible
2. 构建 context pack
3. 加载 prompt 模板
4. 调用本地 vLLM
5. 尝试 JSON parse
6. normalize 字段
7. 做一致性检查
8. 写入 artifact version
9. 返回任务结果

---

## 13. 实现建议

- LLM 调用层与模板层分离
- 解析与 normalize 独立模块
- consistency check 不要依赖同一 prompt 混在主生成中
- 所有输出带 `model_name`、`prompt_template_version`、`temperature`、`seed`

---

## 14. 评审 checklist

- 是否拆分成多任务而非一个超长 prompt
- 是否统一 JSON 契约
- 是否有 context pack builder
- 是否有输出 repair 与 normalize
- 是否有内容一致性检查
- 是否支持 approved 版本选择
