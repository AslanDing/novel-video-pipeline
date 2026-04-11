"""
流式JSON生成处理器

提供健壮的LLM JSON生成流程：
1. 断点续传 - 从不完整处继续生成
2. 智能修复 - 自动修复截断的JSON
3. 状态检查点 - 保存生成进度
4. 稳定性保障 - 全流程异常处理
"""
import json
import re
import asyncio
from typing import Dict, List, Optional, Union, Any, Tuple, Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import hashlib


class GenerationState(Enum):
    """生成状态"""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"  # 检测到不完整，需要续传
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class GenerationCheckpoint:
    """生成检查点 - 保存生成进度"""
    # 唯一标识
    session_id: str
    # 生成参数哈希
    prompt_hash: str
    # 已生成的完整内容
    generated_content: str = ""
    # JSON修复后的有效内容（如果有）
    repaired_content: str = ""
    # 已解析的部分数据
    partial_data: Dict = field(default_factory=dict)
    # 还需要生成的字段路径
    remaining_paths: List[str] = field(default_factory=list)
    # 当前状态
    state: GenerationState = GenerationState.IDLE
    # 尝试次数
    attempt_count: int = 0
    # 最大尝试次数
    max_attempts: int = 5
    # 创建时间戳
    created_at: float = field(default_factory=lambda: asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0)


@dataclass
class JSONRepairResult:
    """JSON修复结果"""
    # 修复后的JSON字符串
    repaired_json: str
    # 是否成功修复
    is_repairable: bool
    # 修复前的截断位置
    truncation_point: int
    # 修复类型: 'complete_object', 'close_brackets', 'remove_partial', 'none'
    repair_type: str
    # 原始内容中删除的部分
    removed_content: str = ""
    # 添加的闭合字符
    added_closing: str = ""
    # 解析后的数据（如果成功）
    parsed_data: Optional[Dict] = None


class JSONRepairTool:
    """
    JSON修复工具

    智能修复不完整的JSON：
    1. 检测截断位置
    2. 智能决定修复策略
    3. 生成合法的JSON
    """

    def __init__(self):
        # 配对符号映射
        self.bracket_pairs = {
            '{': '}',
            '[': ']',
            '"': '"',
        }
        self.opening_brackets = set(self.bracket_pairs.keys())
        self.closing_brackets = set(self.bracket_pairs.values())

    def analyze_structure(self, json_str: str) -> Tuple[List[str], int, str]:
        """
        分析JSON结构，找出未闭合的括号

        Returns:
            stack: 未闭合的括号栈
            truncation_point: 截断位置
            state: 当前解析状态
        """
        stack = []
        i = 0
        n = len(json_str)
        in_string = False
        escape_next = False
        last_valid_pos = 0

        while i < n:
            char = json_str[i]

            # 处理转义
            if escape_next:
                escape_next = False
                i += 1
                continue

            if char == '\\':
                escape_next = True
                i += 1
                continue

            # 处理字符串
            if char == '"':
                if not in_string:
                    in_string = True
                    stack.append('"')
                else:
                    if stack and stack[-1] == '"':
                        stack.pop()
                    in_string = False
                    last_valid_pos = i
                i += 1
                continue

            # 如果在字符串内，跳过
            if in_string:
                i += 1
                continue

            # 处理括号
            if char in self.opening_brackets:
                stack.append(char)
            elif char in self.closing_brackets:
                if stack:
                    opening = stack[-1]
                    if self.bracket_pairs.get(opening) == char:
                        stack.pop()
                        last_valid_pos = i

            # 记录有效位置（逗号、冒号等分隔符）
            if char in [',', ':', '{', '['] and not stack:
                last_valid_pos = i

            i += 1

        # 确定截断点
        if stack:
            # 有未闭合的括号，从最后一个完整结构后截断
            truncation_point = last_valid_pos + 1 if last_valid_pos > 0 else len(json_str)
        else:
            # 结构完整但可能缺少内容
            truncation_point = len(json_str)

        return stack, truncation_point, "incomplete" if stack else "complete"

    def repair_json(self, json_str: str) -> JSONRepairResult:
        """
        修复不完整的JSON

        策略：
        1. 分析未闭合的括号
        2. 决定最佳截断点
        3. 移除不完整的部分
        4. 添加闭合字符
        """
        if not json_str or not json_str.strip():
            return JSONRepairResult(
                repaired_json="{}",
                is_repairable=False,
                truncation_point=0,
                repair_type="empty_input"
            )

        # 清理常见的LLM前缀
        json_str = self._clean_llm_prefix(json_str)

        # 分析结构
        stack, truncation_point, state = self.analyze_structure(json_str)

        # 如果结构完整，直接返回
        if not stack and state == "complete":
            try:
                parsed = json.loads(json_str)
                return JSONRepairResult(
                    repaired_json=json_str,
                    is_repairable=True,
                    truncation_point=len(json_str),
                    repair_type="already_complete",
                    parsed_data=parsed
                )
            except json.JSONDecodeError:
                # 有语法错误，继续修复
                pass

        # 需要修复
        return self._perform_repair(json_str, stack, truncation_point)

    def _clean_llm_prefix(self, text: str) -> str:
        """清理LLM常见的前缀"""
        prefixes = [
            r'^\s*```\s*json\s*',
            r'^\s*```\s*',
            r'^\s*Here\s+is\s+the\s+JSON:\s*',
            r'^\s*JSON:\s*',
        ]
        for pattern in prefixes:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        return text.strip()

    def _perform_repair(self, json_str: str, stack: List[str], truncation_point: int) -> JSONRepairResult:
        """执行修复操作"""

        # 截取有效部分
        valid_part = json_str[:truncation_point].rstrip()
        removed = json_str[truncation_point:]

        # 根据未闭合的栈决定修复策略
        closing_chars = []
        repair_type = "close_brackets"

        # 逆序处理未闭合的括号
        temp_stack = stack.copy()
        while temp_stack:
            opening = temp_stack.pop()
            if opening == '"':
                # 字符串未闭合
                if temp_stack and temp_stack[-1] in ['{', '[']:
                    # 可能是键名，补全引号+值
                    closing_chars.append('": null')
                else:
                    closing_chars.append('"')
            elif opening in self.bracket_pairs:
                closing_chars.append(self.bracket_pairs[opening])

        # 构建修复后的JSON
        if closing_chars:
            repaired = valid_part + ''.join(closing_chars)
        else:
            # 没有未闭合的括号，但可能结构不完整
            # 尝试补全为对象
            if not valid_part.startswith('{'):
                repaired = '{' + valid_part + '}'
            else:
                repaired = valid_part + '}'

        # 尝试解析
        parsed_data = None
        try:
            parsed_data = json.loads(repaired)
            is_repairable = True
        except json.JSONDecodeError:
            is_repairable = False

        return JSONRepairResult(
            repaired_json=repaired,
            is_repairable=is_repairable,
            truncation_point=truncation_point,
            repair_type=repair_type,
            removed_content=removed[:100] + "..." if len(removed) > 100 else removed,
            added_closing=''.join(closing_chars),
            parsed_data=parsed_data
        )


class StreamingJSONGenerator:
    """
    流式JSON生成处理器

    提供断点续传能力的JSON生成：
    1. 检测生成中断
    2. 智能修复不完整JSON
    3. 从未完成处继续生成
    4. 合并多次生成结果
    """

    def __init__(self, llm_client):
        self.llm_client = llm_client
        self.repair_tool = JSONRepairTool()
        self._checkpoints: Dict[str, GenerationCheckpoint] = {}

    async def generate_json_streaming(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int,
        session_id: str = None,
        required_fields: List[str] = None,
        max_attempts: int = 5,
        response_format: Optional[Dict] = None
    ) -> Tuple[Optional[Dict], GenerationCheckpoint]:
        """
        流式生成JSON，支持断点续传

        Args:
            prompt: 生成提示
            system_prompt: 系统提示
            max_tokens: 最大token数
            session_id: 会话ID（用于断点续传）
            required_fields: 必需的字段列表
            max_attempts: 最大尝试次数

        Returns:
            (解析后的JSON数据, 检查点信息)
        """
        # 生成或获取session_id
        if not session_id:
            session_id = self._generate_session_id(prompt)

        # 检查是否有现有的检查点
        checkpoint = self._checkpoints.get(session_id)
        if not checkpoint:
            checkpoint = GenerationCheckpoint(
                session_id=session_id,
                prompt_hash=self._hash_prompt(prompt),
                max_attempts=max_attempts
            )
            self._checkpoints[session_id] = checkpoint

        # 如果已完成，直接返回
        if checkpoint.state == GenerationState.COMPLETED and checkpoint.partial_data:
            return checkpoint.partial_data, checkpoint

        # 开始生成流程
        attempt = 0
        accumulated_content = checkpoint.generated_content or ""

        while attempt < max_attempts:
            attempt += 1
            checkpoint.attempt_count = attempt
            checkpoint.state = GenerationState.RUNNING

            try:
                # 构建续传提示（如果有已有内容）
                current_prompt = self._build_continuation_prompt(
                    prompt, accumulated_content, checkpoint.remaining_paths
                )

                # 调用LLM生成
                response = await self.llm_client.generate(
                    prompt=current_prompt,
                    system_prompt=system_prompt,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )

                content = response.content if hasattr(response, 'content') else str(response)

                # 合并内容
                if accumulated_content:
                    accumulated_content = self._merge_content(accumulated_content, content)
                else:
                    accumulated_content = content

                checkpoint.generated_content = accumulated_content

                # 尝试解析和修复
                repair_result = self.repair_tool.repair_json(accumulated_content)

                if repair_result.is_repairable and repair_result.parsed_data:
                    # 成功修复并解析
                    checkpoint.partial_data = repair_result.parsed_data
                    checkpoint.repaired_content = repair_result.repaired_json

                    # 检查是否包含所有必需字段
                    missing_fields = self._check_required_fields(
                        repair_result.parsed_data, required_fields
                    )

                    if not missing_fields:
                        # 所有字段都已生成
                        checkpoint.state = GenerationState.COMPLETED
                        return repair_result.parsed_data, checkpoint
                    else:
                        # 还有字段需要生成
                        checkpoint.remaining_paths = missing_fields
                        checkpoint.state = GenerationState.PAUSED
                        # 继续下一轮生成
                        continue
                else:
                    # 无法修复，记录状态并尝试继续生成
                    checkpoint.state = GenerationState.PAUSED
                    # 分析还需要生成什么
                    checkpoint.remaining_paths = self._analyze_remaining_paths(
                        accumulated_content
                    )

                    # 如果内容增长不明显，可能是LLM无法继续
                    if len(content.strip()) < 50:
                        # 尝试用更激进的方式修复
                        fallback_result = self._fallback_repair(accumulated_content)
                        if fallback_result:
                            checkpoint.partial_data = fallback_result
                            checkpoint.state = GenerationState.COMPLETED
                            return fallback_result, checkpoint

            except Exception as e:
                checkpoint.state = GenerationState.FAILED
                print(f"⚠️  生成尝试 {attempt} 失败: {e}")

        # 所有尝试都失败
        checkpoint.state = GenerationState.FAILED

        # 尝试最后修复
        final_repair = self.repair_tool.repair_json(accumulated_content)
        if final_repair.is_repairable and final_repair.parsed_data:
            return final_repair.parsed_data, checkpoint

        return None, checkpoint

    def _generate_session_id(self, prompt: str) -> str:
        """生成会话ID"""
        content = f"{prompt}:{asyncio.get_event_loop().time()}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def _hash_prompt(self, prompt: str) -> str:
        """计算提示的哈希"""
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    def _build_continuation_prompt(
        self,
        original_prompt: str,
        accumulated_content: str,
        remaining_paths: List[str]
    ) -> str:
        """
        构建续传提示

        策略：
        1. 如果有已有内容，要求LLM继续生成未完成部分
        2. 明确指定还需要生成哪些字段
        """
        if not accumulated_content or not accumulated_content.strip():
            return original_prompt

        # 分析已有内容的结构
        repair_result = self.repair_tool.repair_json(accumulated_content)

        continuation_prompt = f"""{original_prompt}

【续传指令】
之前的生成内容已保存，请继续完成以下JSON。

【已生成的部分】
```json
{accumulated_content[:2000] if len(accumulated_content) > 2000 else accumulated_content}
```
{"...(内容已截断)" if len(accumulated_content) > 2000 else ""}

【修复后的有效JSON】
```json
{repair_result.repaired_json if repair_result.is_repairable else "[修复失败]"}
```

【还需要生成的内容】
"""
        if remaining_paths:
            for path in remaining_paths[:10]:  # 最多显示10个
                continuation_prompt += f"- {path}\n"
        else:
            continuation_prompt += "- 请补全剩余字段，确保JSON完整\n"

        continuation_prompt += """
【重要要求】
1. 从断点处继续生成，不要重复已生成的内容
2. 只需输出剩余部分，我会将其与之前的内容合并
3. 确保最终JSON格式正确，所有括号闭合
4. 如果键值对不完整，请补全或移除

请继续生成：
"""
        return continuation_prompt

    def _merge_content(self, accumulated: str, new_content: str) -> str:
        """
        智能合并累积内容和新内容

        处理重复和重叠
        """
        # 清理新内容
        new_clean = self.repair_tool._clean_llm_prefix(new_content).strip()
        acc_clean = accumulated.strip()

        if not acc_clean:
            return new_clean

        if not new_clean:
            return acc_clean

        # 检测重复（新内容完全包含在旧内容中）
        if new_clean in acc_clean:
            return acc_clean

        # 检测重叠（新内容开头与旧内容结尾重叠）
        # 尝试找到最大重叠
        max_overlap = min(len(acc_clean), len(new_clean)) // 2
        for overlap_len in range(max_overlap, 0, -1):
            if acc_clean[-overlap_len:] == new_clean[:overlap_len]:
                return acc_clean + new_clean[overlap_len:]

        # 无重叠，尝试智能合并
        # 如果新内容以 { 或 [ 开头，可能是重新开始
        if new_clean[0] in '{[' and acc_clean[-1] in '}]':
            # 尝试合并JSON对象
            merged = self._try_merge_json(acc_clean, new_clean)
            if merged:
                return merged

        # 简单拼接（新内容应该是续接）
        return acc_clean + new_clean

    def _try_merge_json(self, json1: str, json2: str) -> Optional[str]:
        """尝试合并两个JSON对象"""
        try:
            # 尝试解析两个JSON
            repair1 = self.repair_tool.repair_json(json1)
            repair2 = self.repair_tool.repair_json(json2)

            if repair1.parsed_data and repair2.parsed_data:
                # 合并两个字典
                merged = {**repair1.parsed_data, **repair2.parsed_data}
                return json.dumps(merged, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return None

    def _check_required_fields(self, data: Dict, required_fields: Optional[List[str]]) -> List[str]:
        """检查缺失的必需字段"""
        if not required_fields:
            return []

        # 特殊放宽：如果期望的外层字段只有1个，且实际上模型直接返回了一个列表
        if isinstance(data, list) and len(required_fields) == 1:
            if data:
                return []
            return required_fields

        missing = []
        for field in required_fields:
            if not self._has_field(data, field):
                missing.append(field)
        return missing

    def _has_field(self, data: Dict, field_path: str) -> bool:
        """检查是否包含字段（支持路径如 'world_building.setting'）"""
        parts = field_path.split('.')
        current = data

        for part in parts:
            if isinstance(current, dict):
                if part not in current:
                    return False
                current = current[part]
            elif isinstance(current, list) and part.isdigit():
                idx = int(part)
                if idx >= len(current):
                    return False
                current = current[idx]
            else:
                return False

        # 检查值是否非空
        if current is None:
            return False
        if isinstance(current, (str, list, dict)) and len(current) == 0:
            return False

        return True

    def _analyze_remaining_paths(self, content: str) -> List[str]:
        """分析还需要生成的字段路径"""
        repair_result = self.repair_tool.repair_json(content)

        if not repair_result.parsed_data:
            # 无法解析，假设需要完整生成
            return ["(完整JSON结构)"]

        data = repair_result.parsed_data
        missing = []

        # 定义关键字段结构
        required_structure = {
            "world_building": ["setting", "power_system", "factions", "rules"],
            "characters": ["id", "name", "role", "description"],
            "plot_structure": [],
            "chapter_plans": []
        }

        for top_key, sub_keys in required_structure.items():
            if top_key not in data:
                missing.append(top_key)
            elif sub_keys and isinstance(data[top_key], dict):
                for sub_key in sub_keys:
                    if sub_key not in data[top_key]:
                        missing.append(f"{top_key}.{sub_key}")

        return missing if missing else ["(补充完善现有内容)"]

    def _fallback_repair(self, content: str) -> Optional[Dict]:
        """
        最后的修复尝试 - 使用激进策略
        """
        try:
            # 策略0: 尝试提取完整的 JSON 数组 [...]
            array_matches = re.findall(r'\[[\s\S]*?\]', content)
            for match in sorted(array_matches, key=len, reverse=True):
                try:
                    data = json.loads(match)
                    if isinstance(data, list) and data:
                        return data
                except json.JSONDecodeError:
                    continue

            # 策略1: 提取所有可能的JSON对象
            # 查找 {...} 模式
            matches = re.findall(r'\{[\s\S]*?\}', content)
            for match in matches:
                try:
                    data = json.loads(match)
                    if data:  # 确保非空
                        return data
                except json.JSONDecodeError:
                    continue

            # 策略2: 逐行解析
            lines = content.split('\n')
            json_lines = []
            in_json = False
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('{') or stripped.startswith('['):
                    in_json = True
                if in_json:
                    json_lines.append(line)
                if stripped.endswith('}') or stripped.endswith(']'):
                    in_json = False

            if json_lines:
                try:
                    return json.loads('\n'.join(json_lines))
                except json.JSONDecodeError:
                    pass

        except Exception as e:
            print(f"Fallback repair failed: {e}")

        return None


# 便捷函数
async def robust_json_generate(
    llm_client,
    prompt: str,
    system_prompt: str,
    max_tokens: int,
    required_fields: List[str] = None,
    max_attempts: int = 5,
    session_id: str = None,
    response_format: Optional[Dict] = None
) -> Tuple[Optional[Dict], dict]:
    """
    健壮的JSON生成函数（便捷接口）

    Returns:
        (解析后的数据, 元数据字典)
    """
    generator = StreamingJSONGenerator(llm_client)

    result, checkpoint = await generator.generate_json_streaming(
        prompt=prompt,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        session_id=session_id,
        required_fields=required_fields,
        max_attempts=max_attempts,
        response_format=response_format
    )

    # 构建元数据
    metadata = {
        "session_id": checkpoint.session_id,
        "attempt_count": checkpoint.attempt_count,
        "state": checkpoint.state.value,
        "is_complete": checkpoint.state == GenerationState.COMPLETED,
        "repaired_content": checkpoint.repaired_content,
        "remaining_paths": checkpoint.remaining_paths
    }

    return result, metadata