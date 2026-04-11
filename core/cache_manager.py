"""
缓存管理器 - 统一管理各级缓存
支持内存缓存、磁盘缓存和输出缓存
"""

import json
import hashlib
import time
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

from core.logger import get_logger

logger = get_logger("cache_manager")


class CacheManager:
    """缓存管理器 - 统一管理各级缓存"""

    def __init__(self, cache_dir: str, max_memory_size: int = 100 * 1024 * 1024):
        """
        初始化缓存管理器

        Args:
            cache_dir: 缓存目录路径
            max_memory_size: 最大内存缓存大小（字节），默认100MB
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 内存缓存
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self.max_memory_size = max_memory_size
        self.current_memory_size = 0
        
        logger.debug(f"缓存管理器初始化完成，缓存目录: {self.cache_dir}")

    def get(self, key: str, level: str = "all") -> Optional[Any]:
        """
        获取缓存

        Args:
            key: 缓存键
            level: 缓存级别 ("memory", "disk", "all")

        Returns:
            缓存数据，如果不存在则返回None
        """
        # L1: 内存缓存
        if level in ("memory", "all"):
            if key in self.memory_cache:
                logger.debug(f"从内存缓存获取: {key}")
                return self.memory_cache[key]['data']

        # L2: 磁盘缓存
        if level in ("disk", "all"):
            cache_path = self._get_disk_cache_path(key)
            if cache_path.exists():
                try:
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        cache_data = json.load(f)
                    
                    data = cache_data.get('data')
                    
                    # 同时存入内存缓存
                    if level == "all":
                        self._set_memory_cache(key, data, cache_data.get('metadata'))
                    
                    logger.debug(f"从磁盘缓存获取: {key}")
                    return data
                except Exception as e:
                    logger.warning(f"读取缓存失败 {key}: {e}")

        return None

    def set(
        self,
        key: str,
        data: Any,
        level: str = "all",
        metadata: Dict = None
    ) -> None:
        """
        设置缓存

        Args:
            key: 缓存键
            data: 缓存数据
            level: 缓存级别 ("memory", "disk", "all")
            metadata: 额外元数据
        """
        # L1: 内存缓存
        if level in ("memory", "all"):
            self._set_memory_cache(key, data, metadata)

        # L2: 磁盘缓存
        if level in ("disk", "all"):
            self._set_disk_cache(key, data, metadata)

    def invalidate(self, pattern: str) -> int:
        """
        失效匹配pattern的缓存

        Args:
            pattern: 匹配模式

        Returns:
            失效的缓存数量
        """
        count = 0

        # 清理内存缓存
        keys_to_remove = [k for k in self.memory_cache if pattern in k]
        for k in keys_to_remove:
            self.current_memory_size -= self.memory_cache[k]['size']
            del self.memory_cache[k]
            count += 1

        # 清理磁盘缓存
        for cache_file in self.cache_dir.rglob("*.json"):
            if pattern in cache_file.stem:
                cache_file.unlink()
                count += 1

        logger.info(f"失效 {count} 个缓存项 (模式: {pattern})")
        return count

    def clear_all(self) -> int:
        """
        清空所有缓存

        Returns:
            清空的缓存数量
        """
        # 清空内存缓存
        count = len(self.memory_cache)
        self.memory_cache.clear()
        self.current_memory_size = 0

        # 清空磁盘缓存
        for cache_file in self.cache_dir.rglob("*.json"):
            if cache_file.is_file():
                cache_file.unlink()
                count += 1

        logger.info(f"清空所有缓存，共 {count} 项")
        return count

    def get_stats(self) -> Dict:
        """
        获取缓存统计

        Returns:
            缓存统计信息字典
        """
        disk_size = sum(
            f.stat().st_size
            for f in self.cache_dir.rglob("*.json")
            if f.is_file()
        )

        return {
            "memory_entries": len(self.memory_cache),
            "memory_size_mb": self.current_memory_size / (1024 * 1024),
            "disk_entries": len(list(self.cache_dir.rglob("*.json"))),
            "disk_size_mb": disk_size / (1024 * 1024),
        }

    # ========== 内部方法 ==========

    def _set_memory_cache(
        self,
        key: str,
        data: Any,
        metadata: Dict = None
    ) -> None:
        """设置内存缓存"""
        # 估算数据大小
        try:
            data_size = len(json.dumps(data, ensure_ascii=False).encode('utf-8'))
        except (TypeError, ValueError):
            # 如果无法序列化，使用估算值
            data_size = 1024  # 默认1KB

        # 检查是否超出限制
        if self.current_memory_size + data_size > self.max_memory_size:
            self._evict_memory_cache(data_size)

        # 存入缓存
        self.memory_cache[key] = {
            'data': data,
            'metadata': metadata or {},
            'size': data_size,
            'timestamp': time.time()
        }
        self.current_memory_size += data_size
        
        logger.debug(f"设置内存缓存: {key} ({data_size} bytes)")

    def _set_disk_cache(
        self,
        key: str,
        data: Any,
        metadata: Dict = None
    ) -> None:
        """设置磁盘缓存"""
        cache_path = self._get_disk_cache_path(key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        cache_data = {
            'data': data,
            'metadata': metadata or {},
            'created_at': datetime.now().isoformat(),
            'version': '1.0'
        }

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
            logger.debug(f"设置磁盘缓存: {key} -> {cache_path}")
        except Exception as e:
            logger.error(f"写入磁盘缓存失败 {key}: {e}")

    def _evict_memory_cache(self, required_size: int) -> None:
        """淘汰内存缓存"""
        # 按时间戳排序，淘汰最旧的
        sorted_items = sorted(
            self.memory_cache.items(),
            key=lambda x: x[1]['timestamp']
        )

        freed_size = 0
        for key, item in sorted_items:
            if freed_size >= required_size:
                break

            del self.memory_cache[key]
            freed_size += item['size']
            self.current_memory_size -= item['size']
            
            logger.debug(f"淘汰内存缓存: {key}")

    def _get_disk_cache_path(self, key: str) -> Path:
        """
        获取磁盘缓存路径
        使用哈希分布避免单目录文件过多
        """
        hash_prefix = hashlib.md5(key.encode()).hexdigest()[:2]
        safe_key = "".join(c for c in key if c.isalnum() or c in ('_', '-'))
        return self.cache_dir / hash_prefix / f"{safe_key}.json"


# ========== 便捷函数 ==========

def generate_cache_key(*parts: str) -> str:
    """
    生成缓存键

    Args:
        *parts: 键的组成部分

    Returns:
        组合后的缓存键
    """
    return ":".join(str(p) for p in parts)


def hash_content(content: str) -> str:
    """
    对内容进行哈希，用于缓存键

    Args:
        content: 要哈希的内容

    Returns:
        哈希值（前16位）
    """
    return hashlib.md5(content.encode('utf-8')).hexdigest()[:16]
