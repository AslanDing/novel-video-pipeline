"""
api_service/config.py
从 config/api_services.json 读取服务配置
"""
import json
import os
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "api_services.json"


def _expand_env(obj: Any) -> Any:
    """递归替换配置中的 ${ENV_VAR} 环境变量占位符"""
    if isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            var = obj[2:-1]
            return os.environ.get(var, "")
        return obj
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(i) for i in obj]
    return obj


@lru_cache(maxsize=1)
def get_config() -> Dict:
    """加载并缓存服务配置（只读一次）"""
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return _expand_env(raw)


def gateway_config() -> Dict:
    return get_config()["gateway"]


def backend_config(name: str) -> Dict:
    """获取指定后端配置，name 可为 llm / image / video / tts / bgm"""
    return get_config()["backends"][name]
