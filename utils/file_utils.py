"""
文件工具类
提供常用的文件操作功能
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional


def ensure_dir(path: Path | str) -> Path:
    """
    确保目录存在，不存在则创建

    Args:
        path: 目录路径

    Returns:
        Path对象
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def safe_remove(path: Path | str) -> bool:
    """
    安全删除文件或目录

    Args:
        path: 路径

    Returns:
        是否成功删除
    """
    try:
        path_obj = Path(path)
        if path_obj.is_file():
            path_obj.unlink()
        elif path_obj.is_dir():
            shutil.rmtree(path_obj)
        return True
    except Exception:
        return False


def list_files(dir_path: Path | str, pattern: str = "*", recursive: bool = False) -> List[Path]:
    """
    列出目录下的文件

    Args:
        dir_path: 目录路径
        pattern: 文件匹配模式
        recursive: 是否递归

    Returns:
        文件路径列表
    """
    dir_obj = Path(dir_path)
    if not dir_obj.exists():
        return []
    
    if recursive:
        return list(dir_obj.rglob(pattern))
    else:
        return list(dir_obj.glob(pattern))


def get_file_size(path: Path | str) -> int:
    """
    获取文件大小（字节）

    Args:
        path: 文件路径

    Returns:
        文件大小，不存在则返回0
    """
    try:
        return Path(path).stat().st_size
    except Exception:
        return 0


def copy_file(src: Path | str, dst: Path | str) -> bool:
    """
    复制文件

    Args:
        src: 源文件
        dst: 目标文件

    Returns:
        是否成功
    """
    try:
        shutil.copy2(Path(src), Path(dst))
        return True
    except Exception:
        return False


def read_text(path: Path | str, encoding: str = "utf-8") -> Optional[str]:
    """
    读取文本文件

    Args:
        path: 文件路径
        encoding: 编码

    Returns:
        文件内容，失败返回None
    """
    try:
        return Path(path).read_text(encoding=encoding)
    except Exception:
        return None


def write_text(path: Path | str, content: str, encoding: str = "utf-8") -> bool:
    """
    写入文本文件

    Args:
        path: 文件路径
        content: 内容
        encoding: 编码

    Returns:
        是否成功
    """
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding=encoding)
        return True
    except Exception:
        return False
