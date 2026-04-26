"""
api_service/logging_config.py
统一的日志系统，为 API Service 和 Pipeline 提供日志记录能力

日志文件位置: outputs/logs/
日志格式: JSON Lines (每行一条日志，方便解析和分析)

日志级别:
  - DEBUG: 详细调试信息
  - INFO: 一般信息
  - WARNING: 警告
  - ERROR: 错误
  - CRITICAL: 严重错误
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
from functools import wraps
import asyncio
import threading

# 全局日志配置
_loggers: Dict[str, "PipelineLogger"] = {}
_log_lock = threading.Lock()

# 日志目录（项目根目录/outputs/logs）
_LOG_DIR = Path("outputs") / "logs"


def get_logger(name: str = "api_service") -> "PipelineLogger":
    """获取或创建日志记录器（单例模式）"""
    global _loggers
    with _log_lock:
        if name not in _loggers:
            _loggers[name] = PipelineLogger(name)
        return _loggers[name]


class PipelineLogger:
    """
    统一的日志记录器，支持：
    1. 控制台输出（带颜色）
    2. JSON Lines 文件输出
    3. 结构化日志字段
    4. 异步安全
    """

    # 日志级别映射
    LEVELS = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }

    # 控制台颜色
    COLORS = {
        "DEBUG": "\033[36m",      # 青色
        "INFO": "\033[32m",       # 绿色
        "WARNING": "\033[33m",    # 黄色
        "ERROR": "\033[31m",      # 红色
        "CRITICAL": "\033[35m",   # 紫色
        "RESET": "\033[0m",
    }

    def __init__(self, name: str, level: str = "DEBUG"):
        self.name = name
        self.level = level
        self._log_dir = _LOG_DIR
        self._log_dir.mkdir(parents=True, exist_ok=True)

        # 创建 logger
        self._logger = logging.getLogger(name)
        self._logger.setLevel(self.LEVELS.get(level, logging.DEBUG))
        self._logger.handlers.clear()

        # 日志文件（JSON Lines 格式）
        self._log_file = self._log_dir / f"{name}.jsonl"
        self._file_handler: Optional[logging.FileHandler] = None

        # 控制台 handler
        self._console_handler = logging.StreamHandler(sys.stdout)
        self._console_handler.setLevel(logging.DEBUG)

        # 格式器
        self._formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        self._console_handler.setFormatter(self._formatter)

        self._logger.addHandler(self._console_handler)
        self._setup_file_handler()

        # 异步锁
        self._lock = threading.Lock()

        # 上下文信息（可被覆盖）
        self._context: Dict[str, Any] = {}

    def _setup_file_handler(self):
        """设置文件 handler（JSON Lines 格式）"""
        try:
            self._file_handler = logging.FileHandler(
                self._log_file, mode="a", encoding="utf-8"
            )
            self._file_handler.setLevel(logging.DEBUG)
            # JSON Lines formatter
            self._logger.addHandler(self._file_handler)
        except Exception as e:
            print(f"[WARNING] Cannot create log file {self._log_file}: {e}")

    def set_context(self, **kwargs):
        """设置日志上下文信息（如 project_id, task_id 等）"""
        self._context.update(kwargs)

    def clear_context(self):
        """清除日志上下文"""
        self._context = {}

    def _format_json(self, level: str, message: str, **kwargs) -> str:
        """格式化为 JSON Line"""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
            "context": self._context.copy(),
        }
        # 添加额外字段
        log_entry.update(kwargs)
        return json.dumps(log_entry, ensure_ascii=False, default=str)

    def _write_to_file(self, json_line: str):
        """写入文件（线程安全）"""
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(json_line + "\n")
        except Exception:
            pass  # 忽略写入错误，避免日志系统本身出错

    def _log(self, level: str, message: str, **kwargs):
        """内部日志方法"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        color = self.COLORS.get(level, "")
        reset = self.COLORS["RESET"]

        # 控制台输出（带颜色）
        if level in ("ERROR", "CRITICAL"):
            print(f"{color}{timestamp} [{level}] {self.name}: {message}{reset}", file=sys.stderr)
        else:
            print(f"{color}{timestamp} [{level}] {self.name}: {message}{reset}")

        # JSON Lines 文件输出
        json_line = self._format_json(level, message, **kwargs)
        self._write_to_file(json_line)

    def debug(self, message: str, **kwargs):
        self._log("DEBUG", message, **kwargs)

    def info(self, message: str, **kwargs):
        self._log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self._log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs):
        self._log("ERROR", message, **kwargs)

    def critical(self, message: str, **kwargs):
        self._log("CRITICAL", message, **kwargs)

    def exception(self, message: str, exc: Exception = None, **kwargs):
        """记录异常信息和堆栈跟踪"""
        exc_info = traceback.format_exc() if exc else None
        self._log("ERROR", message, exception=str(exc), traceback=exc_info, **kwargs)

    def log_api_request(self, method: str, path: str, params: Dict = None,
                       body: Dict = None, task_id: str = None):
        """记录 API 请求"""
        self.debug(
            f"API Request: {method} {path}",
            type="api_request",
            method=method,
            path=path,
            params=params,
            body=body,
            task_id=task_id,
        )

    def log_api_response(self, method: str, path: str, status_code: int,
                         response_time_ms: float, task_id: str = None, error: str = None):
        """记录 API 响应"""
        level = "ERROR" if status_code >= 400 else "INFO"
        self._log(
            level,
            f"API Response: {method} {path} -> {status_code} ({response_time_ms:.0f}ms)",
            type="api_response",
            method=method,
            path=path,
            status_code=status_code,
            response_time_ms=round(response_time_ms, 2),
            task_id=task_id,
            error=error,
        )

    def log_backend_call(self, backend: str, operation: str, duration_ms: float,
                         success: bool, error: str = None, **extra):
        """记录后端调用（如 ComfyUI、LLM 等）"""
        level = "ERROR" if not success else "DEBUG"
        self._log(
            level,
            f"Backend Call: {backend}.{operation} ({duration_ms:.0f}ms) {'FAILED' if not success else 'OK'}",
            type="backend_call",
            backend=backend,
            operation=operation,
            duration_ms=round(duration_ms, 2),
            success=success,
            error=error,
            **extra,
        )

    def log_task_start(self, task_id: str, task_type: str, params: Dict = None):
        """记录任务开始"""
        self.info(
            f"Task Started: {task_type} ({task_id})",
            type="task_start",
            task_id=task_id,
            task_type=task_type,
            params=params,
        )

    def log_task_complete(self, task_id: str, task_type: str, duration_ms: float,
                          result: Any = None, error: str = None):
        """记录任务完成"""
        level = "ERROR" if error else "INFO"
        self._log(
            level,
            f"Task Completed: {task_type} ({task_id}) in {duration_ms:.0f}ms",
            type="task_complete",
            task_id=task_id,
            task_type=task_type,
            duration_ms=round(duration_ms, 2),
            success=error is None,
            error=error,
            result=result,
        )

    def log_pipeline_stage(self, stage: str, step: str, status: str,
                          duration_ms: float = None, **extra):
        """记录 Pipeline 阶段"""
        self.info(
            f"Pipeline Stage: {stage} > {step} [{status}]",
            type="pipeline_stage",
            stage=stage,
            step=step,
            status=status,
            duration_ms=round(duration_ms, 2) if duration_ms else None,
            **extra,
        )

    def log_workflow(self, workflow_name: str, action: str, **params):
        """记录 Workflow 操作"""
        self.debug(
            f"Workflow: {workflow_name} - {action}",
            type="workflow",
            workflow=workflow_name,
            action=action,
            **params,
        )

    def log_comfyui_node(self, node_type: str, node_id: str, inputs: Dict = None,
                         outputs: Any = None, duration_ms: float = None):
        """记录 ComfyUI 节点执行"""
        self.debug(
            f"ComfyUI Node: {node_type} ({node_id})",
            type="comfyui_node",
            node_type=node_type,
            node_id=node_id,
            inputs=inputs,
            outputs=outputs,
            duration_ms=round(duration_ms, 2) if duration_ms else None,
        )


# ── 装饰器 ──────────────────────────────────────────────────────────────────────

def log_function_call(logger: PipelineLogger = None, level: str = "DEBUG"):
    """装饰器：记录函数调用和执行时间"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            log = logger or get_logger()
            start = time.monotonic()
            log.debug(f"Calling {func.__name__}", function=func.__name__, args=args, kwargs=kwargs)
            try:
                result = await func(*args, **kwargs)
                duration = (time.monotonic() - start) * 1000
                log.debug(f"{func.__name__} completed in {duration:.0f}ms", function=func.__name__, duration_ms=duration)
                return result
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                log.exception(f"{func.__name__} failed after {duration:.0f}ms", e, function=func.__name__, duration_ms=duration)
                raise

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            log = logger or get_logger()
            start = time.monotonic()
            log.debug(f"Calling {func.__name__}", function=func.__name__, args=args, kwargs=kwargs)
            try:
                result = func(*args, **kwargs)
                duration = (time.monotonic() - start) * 1000
                log.debug(f"{func.__name__} completed in {duration:.0f}ms", function=func.__name__, duration_ms=duration)
                return result
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                log.exception(f"{func.__name__} failed after {duration:.0f}ms", e, function=func.__name__, duration_ms=duration)
                raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


class LogCapture:
    """上下文管理器：捕获日志块"""

    def __init__(self, logger: PipelineLogger, level: str = "INFO", message: str = ""):
        self.logger = logger
        self.level = level
        self.message = message
        self.start_time = None

    def __enter__(self):
        self.start_time = time.monotonic()
        self.logger.info(f"▶ {self.message}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (time.monotonic() - self.start_time) * 1000
        if exc_type:
            self.logger.error(
                f"✗ {self.message} FAILED after {duration:.0f}ms",
                error=str(exc_val),
                exception=traceback.format_exc(),
            )
        else:
            self.logger.info(f"✓ {self.message} completed in {duration:.0f}ms")
        return False  # 不要抑制异常


# ── 便捷函数 ────────────────────────────────────────────────────────────────────

def log_api_request_response(func):
    """装饰器：自动记录 API 请求/响应"""
    @wraps(func)
    async def wrapper(request: Any, *args, **kwargs):
        logger = get_logger("api_service")
        start = time.monotonic()

        # 记录请求
        req_dict = {}
        if hasattr(request, "dict"):
            req_dict = request.dict()
        elif hasattr(request, "model_dump"):
            req_dict = request.model_dump()

        logger.log_api_request(
            method="POST",
            path=request.url.path if hasattr(request, "url") else "",
            params=req_dict,
        )

        try:
            response = await func(request, *args, **kwargs)
            duration = (time.monotonic() - start) * 1000

            # 记录响应
            status = getattr(response, "status_code", 200) if hasattr(response, "status_code") else 200
            logger.log_api_response(
                method="POST",
                path=request.url.path if hasattr(request, "url") else "",
                status_code=status,
                response_time_ms=duration,
            )
            return response
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            logger.log_api_response(
                method="POST",
                path=request.url.path if hasattr(request, "url") else "",
                status_code=500,
                response_time_ms=duration,
                error=str(e),
            )
            raise

    return wrapper


# ── 日志分析工具 ────────────────────────────────────────────────────────────────

def parse_logs(log_file: Path = None, limit: int = None) -> list:
    """解析日志文件，返回结构化数据"""
    if log_file is None:
        log_file = _LOG_DIR / "api_service.jsonl"

    if not log_file.exists():
        return []

    logs = []
    with open(log_file, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            try:
                logs.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return logs


def filter_logs(level: str = None, type: str = None, task_id: str = None,
                start_time: datetime = None, end_time: datetime = None) -> list:
    """过滤日志"""
    logs = parse_logs()

    filtered = []
    for log in logs:
        if level and log.get("level") != level:
            continue
        if type and log.get("type") != type:
            continue
        if task_id and log.get("context", {}).get("task_id") != task_id:
            continue

        log_time = log.get("timestamp", "")
        if start_time and log_time < start_time.isoformat():
            continue
        if end_time and log_time > end_time.isoformat():
            continue

        filtered.append(log)

    return filtered