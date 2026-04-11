"""
JSON 工具类
用于处理 LLM 返回的不规范 JSON 数据
"""
import re
import json
from typing import Any, Dict, Optional, Union


def extract_json(text: str) -> Optional[Union[Dict, list]]:
    """
    从文本中提取并解析 JSON
    
    支持:
    1. markdown 代码块 ```json ... ```
    2. 只有括号包裹的内容 { ... } 或 [ ... ]
    3. 清理常见的 LLM 错误 (如末尾逗号, 占位符 ... 等)
    """
    if not text:
        return None
    
    # 1. 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 2. 尝试正则提取 JSON 部分
    # 优先匹配最外层的 { } 或 [ ]
    json_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
    if not json_match:
        # 尝试匹配 markdown 代码块
        code_block = re.search(r'```(?:json)?\s*(.*?)\s*```', text, re.DOTALL)
        if code_block:
            json_text = code_block.group(1)
        else:
            return None
    else:
        json_text = json_match.group(1)
    
    # 3. 清理 JSON 文本
    cleaned_text = clean_json_string(json_text)
    
    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError as e:
        # 如果还是失败，尝试更激进的清理
        try:
            # 移除末尾多余的逗号
            cleaned_text = re.sub(r',\s*([}\]])', r'\1', cleaned_text)
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            print(f"❌ JSON 清理后解析依然失败: {e}")
            print(f"待处理文本: {cleaned_text[:200]}...")
            return None


def clean_json_string(json_str: str) -> str:
    """清理 JSON 字符串中的常见错误"""
    # 移除 LLM 常见的占位符 ... (通常出现在列表或对象末尾)
    # 注意不要误删正常内容中的 ...，所以我们只处理 key 或 value 位置的 ...
    
    # 处理 "key": ... 这种形式
    json_str = re.sub(r':\s*\.\.\.\s*([,}])', r': null\1', json_str)
    
    # 处理列表中的 ... [1, 2, ...]
    json_str = re.sub(r',\s*\.\.\.\s*([\]])', r'\1', json_str)
    
    # 处理孤立的 ...
    json_str = json_str.replace('...', '""')
    
    # 移除控制字符
    json_str = re.sub(r'[\x00-\x1F\x7F]', '', json_str)
    
    return json_str


def safe_json_loads(text: str, default: Any = None) -> Any:
    """安全的 JSON 解析，失败时返回默认值"""
    result = extract_json(text)
    return result if result is not None else default
