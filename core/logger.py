"""
统一日志配置模块
"""

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 日志目录
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logger(
    name: str = "ai-novel",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    console: bool = True,
) -> logging.Logger:
    """
    创建并配置日志记录器

    Args:
        name: 日志记录器名称
        level: 日志级别
        log_file: 日志文件路径（可选）
        console: 是否输出到控制台

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 日志格式
    detailed_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s"
    simple_format = "%(asctime)s | %(levelname)-8s | %(message)s"

    formatter = logging.Formatter(detailed_format, datefmt="%Y-%m-%d %H:%M:%S")

    # 控制台处理器
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(logging.Formatter(simple_format, datefmt="%H:%M:%S"))
        logger.addHandler(console_handler)

    # 文件处理器
    if log_file is None:
        log_file = LOG_DIR / f"ai-novel-{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


# 创建默认日志记录器
logger = setup_logger()


def get_logger(name: str = None) -> logging.Logger:
    """
    获取子模块日志记录器

    Args:
        name: 子模块名称，如 "image_generator"

    Returns:
        子模块日志记录器
    """
    if name:
        return logging.getLogger(f"ai-novel.{name}")
    return logger


# 便捷函数
def log_info(msg: str, **kwargs):
    """记录信息日志"""
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.info(f"{msg} | {extra}" if extra else msg)


def log_warning(msg: str, **kwargs):
    """记录警告日志"""
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.warning(f"{msg} | {extra}" if extra else msg)


def log_error(msg: str, exc: Optional[Exception] = None, **kwargs):
    """记录错误日志"""
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    if exc:
        logger.exception(f"{msg} | {extra} | Exception: {type(exc).__name__}: {exc}")
    else:
        logger.error(f"{msg} | {extra}" if extra else msg)


def log_debug(msg: str, **kwargs):
    """记录调试日志"""
    extra = " | ".join(f"{k}={v}" for k, v in kwargs.items()) if kwargs else ""
    logger.debug(f"{msg} | {extra}" if extra else msg)