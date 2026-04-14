# 02_LLM 与 Prompt 设计

## 一、LLM 调用策略

### 1.1 支持的 LLM 后端

| 后端 | 部署方式 | VRAM | 适用场景 | 推荐度 |
|------|----------|------|----------|--------|
| **vLLM** | 本地进程 (:8080) | ~8GB (Qwen3-14B) | 主力推荐 | ⭐⭐⭐⭐⭐ |
| **llama.cpp** | 本地进程 (:8080) | ~10GB (Qwen3-14B Q4) | 备选 | ⭐⭐⭐ |
| **Ollama** | 本地进程 (:11434) | ~8GB | 简单部署 | ⭐⭐⭐ |
| **NVIDIA NIM** | 云端 API | 0GB | 快速原型 | ⭐⭐⭐ |
| **本地 diffusers** | 直接加载 | ~8GB | 不推荐 | ⭐⭐ |

**推荐配置**: vLLM + Qwen3-14B-AWQ，量化后约 8GB VRAM，支持 RoPE scaled attention。

### 1.2 LLM 分阶段调用

Phase 1 小说生成需要 5+1 次 LLM 调用：

| 步骤 | 名称 | 调用次数 | max_tokens | 依赖 |
|------|------|----------|------------|------|
| 1 | 世界观生成 | 1 | 4000 | 无 |
| 2 | 角色生成 | 1 | 4000 | Step 1 |
| 3 | 修炼体系 | 1 | 2000 | Step 1 |
| 4 | 情节结构 | 1 | 4000 | Step 1-3 |
| 5 | 章节规划 | ceil(chapters/5) | 4000 | Step 4 |
| 6 | 章节正文 | chapters × ceil(words/2000) | 8000 | Step 5 |
| 7 | 分镜脚本 | chapters × N | 16000 | Step 6 |

**总调用次数**: 约 7 + chapters × 3 次

### 1.3 VRAM 分时复用

LLM 调用（Phase 1）和 ComfyUI（Phase 2）在时间上分开，不同时占用 VRAM：

```
Phase 1: LLM 生成  →  llama.cpp/vLLM 独立进程，~8GB VRAM
Phase 2: ComfyUI   →  独立进程，~4-6GB VRAM
                               ↓
                         不同时运行
```

---

## 二、Prompt 设计原则

### 2.1 五大原则

#### 原则 1: 强格式约束

```yaml
# 错误示例
prompt: "请生成角色信息，包含姓名和描述"

# 正确示例
prompt: |
  请生成角色信息，必须严格按以下 JSON 格式输出，不允许添加任何其他内容：
  {
    "name": "角色名称（中文）",
    "description": "角色描述，50字以上"
  }
  如果无法按格式输出，返回 null。
```

#### 原则 2: 示例注入 (Few-shot)

```yaml
prompt: |
  判断文本情感类别。

  示例：
  输入："我今天太开心了！"
  输出：{"sentiment": "happy"}

  输入："这是个悲伤的故事"
  输出：{"sentiment": "sad"}

  请判断：
  输入："林云眼中闪过一丝寒光"
  输出：
```

#### 原则 3: 逐步推理 (Chain of Thought)

```yaml
prompt: |
  分析以下小说场景的爽点类型。

  场景：主角林云在家族大比中，一拳击败了曾经羞辱他的天才林浩。

  分析步骤：
  1. 确定主要冲突：主角 vs 天才的对抗关系
  2. 确定反转点：原本的弱者战胜了原来的强者
  3. 确定爽点类型：当众打脸、身份反转
  4. 确定强度：高（当着全族人的面，影响范围大）

  输出：
  {"shuangdian_type": "dalian", "intensity": "high", "reasoning": "..."}
```

#### 原则 4: 角色扮演

```yaml
prompt: |
  你是一位资深网文大神，专注于修仙爽文创作。

  你的特点：
  - 擅长"打脸"情节的设计
  - 善于设置"升级"爽点
  - 熟悉修仙体系的世界观
  - 文字描写生动，对话富有张力
```

#### 原则 5: 意图层输出（区别于技术参数）

```yaml
# Python/FastAPI 输出意图层数据，不输出技术参数
# 错误：输出 sampler、CFG、节点 ID
# 正确：输出 purpose、characters、scene、mood
```

---

## 三、分阶段 Prompt 模板

### 3.1 世界观生成

```yaml
# config/prompts_v2/llm_prompts/world_building.yaml
system: |
  你是一位资深仙侠小说架构师。你擅长构建庞大且逻辑自洽的修仙世界观。

  输出要求：
  1. 所有输出必须是合法的 JSON 格式
  2. setting 字段至少 200 字，描述历史、地理、当前局势
  3. factions 至少 3 个势力，包含正/邪/中三方
  4. rules 至少 2 条世界运行的核心规则
  5. 严禁输出 JSON 以外的内容

  输出格式：
  {
    "setting": "世界观背景描述（200字以上）",
    "factions": [
      {"name": "势力名称", "description": "势力描述", "type": "正/邪/中"}
    ],
    "rules": ["规则1", "规则2"]
  }

user: |
  小说标题：{title}
  小说类型：{genre}
  风格：{style}
  核心创意：{core_idea}

  请生成完整的世界观设定。
```

### 3.2 角色生成

```yaml
# config/prompts_v2/llm_prompts/characters.yaml
system: |
  你是一位顶级的小说角色设计师。你擅长创造有深度的角色。

  输出要求：
  1. 必须输出合法 JSON 格式
  2. 主角至少 1 个，role="protagonist"
  3. 反派至少 1 个，role="antagonist"
  4. 每个角色必须包含 appearance 字段，用于 AI 绘画
  5. 主角 appearance 要详细，便于生成角色定妆照（100字以上）

  输出格式：
  {
    "characters": [
      {
        "id": "角色唯一ID",
        "name": "角色名称",
        "role": "protagonist/antagonist/supporting",
        "description": "角色简介",
        "personality": "性格特点",
        "goals": "角色目标",
        "background": "角色背景",
        "appearance": "外貌描述（100字以上，用于AI绘画）"
      }
    ]
  }
```

### 3.3 分镜脚本生成（核心）

这是最容易出错的地方，需要最强的格式约束：

```yaml
# config/prompts_v2/llm_prompts/shot_list.yaml
system: |
  你是一位专业的影视分镜编剧。你擅长将小说文字转化为视觉脚本。

  输出要求：
  1. 必须输出 JSONL 格式，每行一个分镜，不允许其他内容
  2. 每行必须包含所有字段，字段缺失视为格式错误
  3. visual_prompt 必须使用英文，详细描述画面
  4. 每 5-10 句话生成一个分镜
  5. 对话和旁白分开处理

  每行 JSON 格式（严格，不允许添加额外字段）：
  {
    "scene_id": "SC01",
    "shot_id": "SC01_SH01",
    "role": "dialogue/narrator",
    "speaker": "角色名/旁白",
    "text": "实际对白或旁白文本",
    "emotion": "happy/sad/angry/calm/neutral/excited",
    "visual_prompt": "Detailed English description for image generation, including subject, action, setting, lighting, mood",
    "motion_prompt": "Camera movement description",
    "camera": "wide/medium/close-up/extreme close-up",
    "estimated_duration": 3.5
  }

user: |
  章节标题：{chapter_title}
  章节内容：
  {chapter_content}

  主要角色外观：
  {character_appearances}

  请将以上章节内容拆分为分镜脚本。
```

### 3.4 章节正文生成

```yaml
system: |
  你是一位资深网文作者，擅长创作修仙爽文。

  写作要求：
  1. 每章 5000 字左右
  2. 情节要爽点密集，打脸、升级、收获、反转要有序安排
  3. 对话要生动，符合角色性格
  4. 环境描写要有画面感
  5. 严禁使用省略号或概括性语言
  6. 严禁在正文输出任何 JSON 或结构化数据

  格式：纯文本小说正文，分段落。
```

### 3.5 镜头列表生成（意图层）

```yaml
# config/prompts_v2/llm_prompts/shot_list.yaml (续)
system: |
  你是一位专业的视频分镜规划师。
  你的任务是将小说章节转化为结构化的镜头列表。

  重要原则：
  1. 只输出"创作意图"数据，不输出技术参数
  2. 不指定 sampler、CFG、节点 ID 等技术参数
  3. Focus on: 角色、场景、情绪、镜头类型、时长

  输出格式（意图层 JSON）：
  {
    "chapter_id": "ch01",
    "shots": [
      {
        "shot_id": "ch01_s001",
        "purpose": "establish tavern atmosphere",
        "characters": ["lin_yun"],
        "scene": "tavern_night",
        "shot_type": "wide",
        "mood": "mysterious, tense",
        "dialogue": null,
        "narrator": "夜幕降临，酒馆中灯火昏暗。",
        "needs_character_consistency": false,
        "needs_scene_consistency": false,
        "video_mode": "t2v"
      }
    ]
  }
```

---

## 四、JSON 输出保护机制

### 4.1 三层防护 `robust_json_generate`

所有 LLM JSON 输出必须通过以下三层防护：

```python
async def robust_json_generate(
    llm_client,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    required_fields: List[str],
    max_attempts: int = 3,
) -> Tuple[Optional[Dict], bool]:
    """
    鲁棒的 JSON 生成函数

    三层防护:
    1. 直接解析 json.loads()
    2. 提取 markdown 代码块
    3. 结构化恢复
    """

    for attempt in range(max_attempts):
        try:
            response = await llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}  # 强制 JSON 模式
            )

            raw_content = response.content

            # 第一层: 直接解析
            try:
                return json.loads(raw_content), True
            except json.JSONDecodeError:
                pass

            # 第二层: 提取 markdown 代码块
            match = re.search(
                r'```(?:json)?\s*([\s\S]*?)\s*```',
                raw_content
            )
            if match:
                try:
                    data = json.loads(match.group(1))
                    if all(f in data for f in required_fields):
                        return data, True
                except json.JSONDecodeError:
                    pass

            # 第三层: 结构化恢复（JSONRepairTool）
            recovered = _recover_structured_data(raw_content, required_fields)
            if recovered:
                return recovered, True

        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed: {e}")

    return None, False
```

### 4.2 `response_format` 参数

如果 LLM API 支持 `response_format={"type": "json_object"}`，必须使用。这强制 LLM 输出纯 JSON，不包含 markdown。

```python
# 使用 vLLM / NVIDIA NIM 时
response = await llm_client.generate(
    prompt=prompt,
    system_prompt=system_prompt,
    max_tokens=max_tokens,
    response_format={"type": "json_object"}  # 关键参数
)
```

### 4.3 JSONRepairTool 修复策略

`utils/streaming_json_generator.py` 中的 `JSONRepairTool` 提供四种修复策略：

| 策略 | 触发条件 | 修复方式 |
|------|----------|----------|
| `complete_object` | 截断在对象中间 | 智能闭合括号 |
| `close_brackets` | 截断在数组中间 | 补全数组闭合 |
| `remove_partial` | 部分字段损坏 | 移除损坏部分 |
| `none` | 无法修复 | 返回原始内容 |

### 4.4 验证函数

每次 JSON 解析后必须验证 `required_fields`：

```python
def validate_json_output(data: Dict, required_fields: List[str]) -> Tuple[bool, List[str]]:
    """
    验证 JSON 输出是否包含所有必需字段

    Returns:
        (是否有效, 缺失字段列表)
    """
    missing = [f for f in required_fields if f not in data]
    return len(missing) == 0, missing
```

---

## 五、Prompt 配置分离

### 5.1 配置目录结构

```
config/
├── prompts_v2/
│   ├── llm_prompts/
│   │   ├── world_building.yaml
│   │   ├── characters.yaml
│   │   ├── power_system.yaml
│   │   ├── plot_structure.yaml
│   │   ├── chapter_plans.yaml
│   │   └── shot_list.yaml
│   └── image_prompts/
│       ├── character_portrait.yaml
│       └── scene_generation.yaml
```

### 5.2 Prompt 加载器

```python
from pathlib import Path
import yaml

class PromptLoader:
    """Prompt 加载器，支持热更新"""

    def __init__(self, prompts_dir: Path):
        self.prompts_dir = prompts_dir
        self._cache = {}

    def load(self, name: str) -> Dict[str, str]:
        """加载指定名称的 prompt"""
        if name in self._cache:
            return self._cache[name]

        path = self.prompts_dir / f"{name}.yaml"
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        self._cache[name] = data
        return data

    def reload(self, name: str):
        """重新加载（热更新）"""
        if name in self._cache:
            del self._cache[name]
        return self.load(name)

    def render(self, name: str, **kwargs) -> Tuple[str, str]:
        """
        渲染 prompt 模板

        Returns:
            (system_prompt, user_prompt)
        """
        data = self.load(name)
        system = data.get('system', '')
        user = data.get('prompt', '')

        # 简单模板渲染
        for key, value in kwargs.items():
            placeholder = f"{{{key}}}"
            system = system.replace(placeholder, str(value))
            user = user.replace(placeholder, str(value))

        return system, user
```

### 5.3 使用示例

```python
from core.prompt_loader import PromptLoader

loader = PromptLoader(Path("config/prompts_v2/llm_prompts"))

# 加载并渲染
system, user = loader.render("world_building",
    title="绝世剑仙",
    genre="修仙",
    core_idea="废材逆袭"
)

# 调用 LLM
result, ok = await robust_json_generate(
    llm_client=self.llm_client,
    prompt=user,
    system_prompt=system,
    max_tokens=4000,
    required_fields=["setting", "factions", "rules"]
)
```

---

## 六、防止 LLM 输出格式错误的策略

### 6.1 prompt 中明确禁止项

```yaml
prompt: |
  输出要求：
  1. 只输出 JSON，不允许输出任何其他内容
  2. 不允许输出 markdown 代码块标记（```json 等）
  3. 不允许输出解释性文字
  4. 不允许输出空行或多余空格
  5. 如果无法按格式输出，直接返回 null
```

### 6.2 使用 `ensure_ascii` 避免转义

Python 端 JSON 解析时使用 `ensure_ascii=False` 保留中文：

```python
# 序列化时
json_str = json.dumps(data, ensure_ascii=False)

# 反序列化时
data = json.loads(json_str)
```

### 6.3 分段生成策略

对于超长输出（如章节正文），使用分段生成：

```python
async def generate_chapter分段(
    target_words: int = 5000,
    chunk_words: int = 2000
) -> str:
    """
    分段生成小说章节，避免单次生成过长导致截断
    """
    num_chunks = ceil(target_words / chunk_words)
    all_content = []

    for i in range(num_chunks):
        is_first = (i == 0)
        is_last = (i == num_chunks - 1)

        prompt = build_chunk_prompt(
            chunk_index=i,
            is_first=is_first,
            is_last=is_last,
            previous_content="\n".join(all_content) if not is_first else ""
        )

        chunk = await llm_client.generate(prompt=prompt, max_tokens=8000)
        all_content.append(chunk.content)

    return "\n".join(all_content)
```

---

## 七、质量评分标准

### 7.1 章节质量评分

| 维度 | 权重 | 评分标准 |
|------|------|----------|
| 爽点密度 | 30% | 打脸/升级/收获/反转的出现频率 |
| 连贯性 | 25% | 与前文一致性，情节流畅度 |
| 可读性 | 20% | 语言通顺，无语法错误 |
| 完整性 | 15% | 有头有尾，情节完整 |
| 长度达标 | 10% | 字数是否达到目标 |

### 7.2 评分触发条件

```
字数不足触发重写: word_count < target_word_count * 0.6
质量不足触发重写: overall_score < 5.0
最大重写次数: 3次
```

---

*文档版本: v1.0*
*创建时间: 2026-04-14*
