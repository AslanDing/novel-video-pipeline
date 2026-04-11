"""
核心模块

提供缓存管理、工作流、日志、LLM客户端等核心功能
"""
from core.logger import setup_logger, get_logger, log_info, log_warning, log_error, log_debug
from core.cache_manager import CacheManager, generate_cache_key, hash_content
from core.workflow import (
    WorkflowManager,
    WorkflowState,
    StageStatus,
    WorkflowStatus,
    WorkflowResult
)
from core.llm_client import (
    NVIDIA_NIM_Client,
    MockLLMClient,
    LLMResponse,
    Message,
    get_llm_client
)
from core.local_llm_client import (
    OllamaClient,
    VLLMClient,
    LocalLLMResponse,
    get_local_llm_client
)
from core.base_pipeline import PipelineStage, Pipeline

__all__ = [
    # 日志
    'setup_logger',
    'get_logger',
    'log_info',
    'log_warning',
    'log_error',
    'log_debug',
    # 缓存
    'CacheManager',
    'generate_cache_key',
    'hash_content',
    # 工作流
    'WorkflowManager',
    'WorkflowState',
    'StageStatus',
    'WorkflowStatus',
    'WorkflowResult',
    # LLM客户端
    'NVIDIA_NIM_Client',
    'MockLLMClient',
    'LLMResponse',
    'Message',
    'get_llm_client',
    # 本地LLM客户端
    'OllamaClient',
    'VLLMClient',
    'LocalLLMResponse',
    'get_local_llm_client',
    # 管道
    'PipelineStage',
    'Pipeline',
]
