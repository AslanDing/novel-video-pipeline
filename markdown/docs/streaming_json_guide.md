# 流式JSON生成器使用指南

## 概述

流式JSON生成器提供了**断点续传**和**智能修复**能力，解决了LLM生成JSON时常见的截断和不完整问题。

## 核心特性

1. **断点续传** - 从JSON截断处继续生成
2. **智能修复** - 自动修复不完整的JSON结构
3. **状态检查点** - 保存和恢复生成进度
4. **稳定性保障** - 多次尝试和回退策略

## 快速开始

### 1. 基础使用

```python
from utils.streaming_json_generator import robust_json_generate

# 简单调用
result, metadata = await robust_json_generate(
    llm_client=your_llm_client,
    prompt="请生成一个角色设定JSON...",
    system_prompt="你是创作助手",
    max_tokens=2000,
    required_fields=["name", "age", "description"],
    max_attempts=5
)

if result:
    print(f"生成成功: {result}")
    print(f"尝试次数: {metadata['attempt_count']}")
    print(f"是否完整: {metadata['is_complete']}")
```

### 2. 高级用法 - 手动控制流式生成

```python
from utils.streaming_json_generator import StreamingJSONGenerator

# 创建生成器
generator = StreamingJSONGenerator(llm_client)

# 开始流式生成
result, checkpoint = await generator.generate_json_streaming(
    prompt="生成复杂的故事蓝图JSON...",
    system_prompt="你是架构师",
    max_tokens=8000,
    required_fields=["world_building", "characters", "plot_structure"],
    max_attempts=5,
    session_id="my_session_001"  # 指定会话ID，支持断点续传
)

# 检查生成状态
if checkpoint.state.value == "completed":
    print("✓ 生成完成")
elif checkpoint.state.value == "paused":
    print(f"⚠️  生成暂停，剩余字段: {checkpoint.remaining_paths}")
    # 可以继续生成...
```

### 3. 在小说生成器中使用

```python
from stage1_novel.streaming_novel_generator import create_novel_generator
from core.llm_client import get_llm_client

# 获取LLM客户端
llm_client = await get_llm_client()

# 创建流式生成器
generator = create_novel_generator(
    llm_client,
    use_streaming=True,  # 启用流式生成
    config=None
)

# 正常使用...
concept = NovelConcept(
    title="测试小说",
    genre="修仙",
    total_chapters=10,
    # ...
)

novel = await generator.process(concept)
```

## JSON修复工具独立使用

```python
from utils.streaming_json_generator import JSONRepairTool

repair_tool = JSONRepairTool()

# 测试各种截断情况
test_cases = [
    '{"name": "张三", "age": 25',  # 对象未闭合
    '{"name": "张三',  # 字符串未闭合
    '{"items": ["a", "b", "c"',  # 数组未闭合
]

for json_str in test_cases:
    result = repair_tool.repair_json(json_str)
    print(f"输入: {json_str}")
    print(f"修复: {result.repaired_json}")
    print(f"可解析: {result.is_repairable}")
```

## 工作原理

### 1. 检测截断

```
输入: {"name": "张三", "age": 25
分析:
  - 遇到 '{' 入栈
  - 遇到 '"' 入栈（字符串开始）
  - 遇到 '"' 出栈（字符串结束）
  - ...
  - 栈中剩余: ['{'] （对象未闭合）
  - 截断点: 字符串末尾
```

### 2. 智能修复

根据未闭合的栈决定修复策略：

| 未闭合栈 | 修复动作 | 示例 |
|---------|---------|------|
| `{` | 添加 `}` | `{...` → `{...}` |
| `[` | 添加 `]` | `[...` → `[...]` |
| `"` | 添加 `"` | `"...` → `"..."` |
| `{` + `"` | 添加 `"}` | `{"key...` → `{"key..."}` |

### 3. 断点续传

```python
# 第一次生成
result, checkpoint = await generator.generate_json_streaming(
    prompt="...",
    session_id="session_001"
)
# 假设生成被截断，checkpoint.state = "paused"

# 第二次调用（使用相同的session_id）
result, checkpoint = await generator.generate_json_streaming(
    prompt="...",
    session_id="session_001"  # 相同ID，自动续传
)
# 从上次的断点继续生成
```

## 配置建议

### 1. 调整最大尝试次数

```python
# 对于复杂内容，增加尝试次数
result, metadata = await robust_json_generate(
    llm_client=client,
    prompt=complex_prompt,
    max_attempts=10,  # 增加到10次
    required_fields=[...]
)
```

### 2. 设置合理的token限制

```python
# 预留足够的token用于JSON格式
content_tokens = target_word_count * 2  # 中文约2 tokens/字
json_overhead = int(content_tokens * 0.3)  # JSON格式开销30%
buffer = 1000  # 预留缓冲

max_tokens = content_tokens + json_overhead + buffer
```

### 3. 处理特定字段缺失

```python
# 检查关键字段
required = ["world_building.setting", "characters.0.name", "plot_structure"]

result, metadata = await robust_json_generate(
    ...,
    required_fields=required
)

if not metadata['is_complete']:
    missing = metadata['remaining_paths']
    print(f"缺失字段: {missing}")
    # 针对性地补充生成
```

## 故障排除

### 问题1: 多次尝试后仍然失败

**原因**: JSON结构太复杂或LLM输出不稳定

**解决方案**:
```python
# 1. 简化要求
simplified_prompt = original_prompt + "\n（请保持JSON结构简洁，优先返回核心字段）"

# 2. 分步骤生成
step1_prompt = "先只生成 world_building 部分"
step2_prompt = "再生成 characters 部分"
# ... 然后合并

# 3. 使用更强的模型或参数
response = await llm_client.generate(
    prompt=prompt,
    temperature=0.2,  # 降低随机性
    max_tokens=8000   # 增加token限制
)
```

### 问题2: 修复后的JSON丢失数据

**原因**: 截断位置计算不准确，删除了有效内容

**解决方案**:
```python
# 使用更保守的修复策略
repair_result = repair_tool.repair_json(content)

if repair_result.truncation_point < len(content) * 0.5:
    # 如果截断太早，可能是误判
    # 尝试只修复明显的结构问题
    manual_fix = content.rstrip()
    if not manual_fix.endswith('}'):
        manual_fix += '}'
    # 再次验证
    try:
        data = json.loads(manual_fix)
        return data
    except json.JSONDecodeError:
        pass
```

### 问题3: 断点续传后内容重复

**原因**: 合并逻辑未正确处理重叠部分

**解决方案**:
```python
# 在continuation_prompt中明确指示
continuation_prompt += """
【重要】请遵循以下规则：
1. 不要重复之前已经生成的内容
2. 从上一个JSON键值对之后继续
3. 只输出剩余部分，我会自动合并
4. 确保你输出的部分可以与之前的内容组成完整JSON
"""

# 使用更好的合并策略
def smart_merge(old: str, new: str) -> str:
    # 尝试找到最大公共子串
    for i in range(min(len(old), len(new)), 0, -1):
        if old.endswith(new[:i]):
            return old + new[i:]
    # 没有重叠，尝试语义合并
    if new.strip().startswith('{'):
        # 新内容是完整对象，尝试合并键
        try:
            old_data = json.loads(old + '}')  # 临时闭合
            new_data = json.loads(new)
            merged = {**old_data, **new_data}
            return json.dumps(merged)
        except:
            pass
    return old + new
```

## 性能考虑

### 1. Token使用优化

```python
# 流式生成可能使用更多token（因为需要续传）
# 可以通过以下方式优化：

# 1. 合理设置max_tokens
# 预留20%用于可能的续传
actual_needed = target_word_count * 2.5  # 2.5 tokens/字（含JSON开销）
max_tokens = int(actual_needed * 1.2)

# 2. 限制续传次数
max_attempts = 3  # 最多续传2次（初次+2次续传）

# 3. 使用更小的分批
# 对于长内容，分多个小批次生成
chunks = split_content(content, chunk_size=3000)  # 每块3000字
for i, chunk_prompt in enumerate(chunks):
    result = await robust_json_generate(...)
```

### 2. 内存管理

```python
# 检查点可能占用内存，需要定期清理
generator = StreamingJSONGenerator(llm_client)

# 手动清理旧检查点
def cleanup_old_checkpoints(generator, max_age_seconds=3600):
    current_time = asyncio.get_event_loop().time()
    to_remove = []
    for session_id, checkpoint in generator._checkpoints.items():
        if current_time - checkpoint.created_at > max_age_seconds:
            to_remove.append(session_id)
    for session_id in to_remove:
        del generator._checkpoints[session_id]
        print(f"清理过期检查点: {session_id}")
```

## 迁移指南

### 从原有代码迁移

#### 原有代码：
```python
from stage1_novel.novel_generator import NovelGenerator

generator = NovelGenerator(llm_client)
blueprint = await generator._create_blueprint(concept)
```

#### 新代码：
```python
from stage1_novel.streaming_novel_generator import create_novel_generator

# 方式1: 自动选择（默认启用流式）
generator = create_novel_generator(llm_client, use_streaming=True)

# 方式2: 显式创建
from stage1_novel.streaming_novel_generator import StreamingNovelGenerator
generator = StreamingNovelGenerator(llm_client)

# 使用方式相同
blueprint = await generator._create_blueprint_streaming(concept)
# 或者直接调用process会自动选择
novel = await generator.process(concept)
```

### 保持向后兼容

如果你暂时不想切换，原有代码继续可用：

```python
# 原有代码无需修改，继续工作
from stage1_novel.novel_generator import NovelGenerator
generator = NovelGenerator(llm_client)
```

新的流式功能是**可选增强**，不是**替代**。

## 总结

流式JSON生成器提供了以下关键能力：

1. **自动修复截断JSON** - 无需手动处理格式错误
2. **断点续传** - 长内容分多次生成，自动合并
3. **状态持久化** - 检查点机制保存进度
4. **向后兼容** - 原有代码无需修改

适合场景：
- 生成大型JSON结构（如完整故事蓝图）
- 网络不稳定，可能中断的环境
- 需要高可靠性的批处理任务
- 长章节内容生成（5000字以上）