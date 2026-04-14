"""
api_service/task_manager.py
轻量级内存任务状态管理
支持后台异步任务的状态追踪和结果存储
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, Optional

from api_service.models import TaskResult, TaskStatus


class TaskManager:
    """内存任务管理器（单进程适用；多进程可替换为 Redis 后端）"""

    def __init__(self):
        self._tasks: Dict[str, TaskResult] = {}
        self._lock = asyncio.Lock()

    def _new_id(self, prefix: str = "task") -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    async def create_task(self, prefix: str = "task") -> str:
        """创建一个 queued 状态的任务，返回 task_id"""
        task_id = self._new_id(prefix)
        async with self._lock:
            self._tasks[task_id] = TaskResult(
                task_id=task_id,
                status=TaskStatus.queued,
            )
        return task_id

    async def get_task(self, task_id: str) -> Optional[TaskResult]:
        async with self._lock:
            return self._tasks.get(task_id)

    async def set_running(self, task_id: str):
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = TaskStatus.running

    async def set_completed(self, task_id: str, result: Any, elapsed: float = 0.0):
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = TaskStatus.completed
                self._tasks[task_id].result = result
                self._tasks[task_id].elapsed_seconds = elapsed

    async def set_failed(self, task_id: str, error: str, elapsed: float = 0.0):
        async with self._lock:
            if task_id in self._tasks:
                self._tasks[task_id].status = TaskStatus.failed
                self._tasks[task_id].error = error
                self._tasks[task_id].elapsed_seconds = elapsed

    async def run_background(
        self,
        task_id: str,
        coro: Coroutine,
    ) -> None:
        """在后台运行协程，自动更新任务状态"""
        start = time.monotonic()
        await self.set_running(task_id)
        try:
            result = await coro
            elapsed = time.monotonic() - start
            await self.set_completed(task_id, result, elapsed)
        except Exception as e:
            elapsed = time.monotonic() - start
            await self.set_failed(task_id, str(e), elapsed)


# 全局单例
_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _manager
    if _manager is None:
        _manager = TaskManager()
    return _manager
