"""
工作流引擎 - 协调四个Stage的执行
管理状态流转，实现完整的缓存机制支持断点续传
"""

import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass

from core.logger import get_logger
from core.cache_manager import CacheManager

logger = get_logger("workflow")


class WorkflowState(Enum):
    """工作流状态枚举"""
    IDLE = "idle"
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(Enum):
    """Stage状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CACHED = "cached"


@dataclass
class WorkflowStatus:
    """工作流状态"""
    state: WorkflowState
    current_stage: Optional[int]
    stage_status: Dict[int, StageStatus]
    progress: float


@dataclass
class WorkflowResult:
    """工作流执行结果"""
    success: bool
    novel_name: str
    elapsed_time: float = 0.0
    error: Optional[str] = None
    stage_status: Optional[Dict[int, StageStatus]] = None
    outputs: Optional[Dict[int, Any]] = None


class WorkflowManager:
    """工作流管理器 - 协调四个Stage的执行"""

    def __init__(self, config: Dict):
        """
        初始化工作流管理器

        Args:
            config: 应用配置字典
        """
        self.config = config
        self.cache_dir = config.get("cache", {}).get("cache_dir", "./cache")
        self.cache_manager = CacheManager(self.cache_dir)
        self.state = WorkflowState.IDLE
        self.current_stage: Optional[int] = None
        self.stage_status = {
            1: StageStatus.PENDING,
            2: StageStatus.PENDING,
            3: StageStatus.PENDING,
            4: StageStatus.PENDING
        }
        self.force_regenerate = config.get("force_regenerate", False)
        
        # Stage执行器（延迟初始化）
        self._stage_executors: Dict[int, Any] = {}
        
        logger.info("工作流管理器初始化完成")

    def run(
        self,
        novel_name: str,
        start_stage: int = 1,
        end_stage: int = 4,
        novel_params: Dict = None,
        video_params: Dict = None,
    ) -> WorkflowResult:
        """
        运行工作流

        Args:
            novel_name: 小说名称
            start_stage: 起始Stage
            end_stage: 结束Stage
            novel_params: 小说生成参数
            video_params: 视频生成参数

        Returns:
            WorkflowResult: 工作流执行结果
        """
        self.state = WorkflowState.RUNNING
        start_time = time.time()

        try:
            # 检查缓存状态
            if start_stage == 1 and not self.force_regenerate:
                cached = self._check_complete_cache(novel_name)
                if cached:
                    logger.info(f"找到完整缓存: {novel_name}")
                    self.state = WorkflowState.COMPLETED
                    return WorkflowResult(
                        success=True,
                        novel_name=novel_name,
                        elapsed_time=0,
                        stage_status={i: StageStatus.CACHED for i in range(1, 5)},
                        outputs=cached
                    )

            # 执行各Stage
            context = {
                'novel_name': novel_name,
                'novel_params': novel_params or {},
                'video_params': video_params or {},
                'outputs': {}
            }

            for stage_num in range(start_stage, end_stage + 1):
                if self.state == WorkflowState.CANCELLED:
                    break
                    
                self.current_stage = stage_num
                self.stage_status[stage_num] = StageStatus.RUNNING

                logger.info(f"开始执行 Stage {stage_num}")

                # 检查Stage缓存
                if not self.force_regenerate:
                    stage_cached = self._check_stage_cache(stage_num, context)
                    if stage_cached:
                        logger.info(f"Stage {stage_num} 使用缓存")
                        self.stage_status[stage_num] = StageStatus.CACHED
                        context['outputs'][stage_num] = stage_cached
                        continue

                # 执行Stage
                try:
                    executor = self._get_stage_executor(stage_num)
                    result = executor.execute(context)

                    self.stage_status[stage_num] = StageStatus.COMPLETED
                    context['outputs'][stage_num] = result
                    logger.info(f"Stage {stage_num} 完成")
                    
                    # 保存Stage缓存
                    self._save_stage_cache(stage_num, context, result)
                    
                except Exception as e:
                    self.stage_status[stage_num] = StageStatus.FAILED
                    logger.error(f"Stage {stage_num} 失败: {e}")
                    raise

            # 工作流完成
            self.state = WorkflowState.COMPLETED
            elapsed_time = time.time() - start_time

            return WorkflowResult(
                success=True,
                novel_name=novel_name,
                elapsed_time=elapsed_time,
                stage_status=self.stage_status.copy(),
                outputs=context['outputs']
            )

        except Exception as e:
            self.state = WorkflowState.FAILED
            logger.error(f"工作流失败: {e}")

            return WorkflowResult(
                success=False,
                novel_name=novel_name,
                error=str(e),
                stage_status=self.stage_status.copy()
            )

    def pause(self) -> None:
        """暂停工作流"""
        if self.state == WorkflowState.RUNNING:
            self.state = WorkflowState.PAUSED
            logger.info("工作流已暂停")

    def resume(self) -> None:
        """恢复工作流"""
        if self.state == WorkflowState.PAUSED:
            self.state = WorkflowState.RUNNING
            logger.info("工作流已恢复")

    def cancel(self) -> None:
        """取消工作流"""
        self.state = WorkflowState.CANCELLED
        logger.info("工作流已取消")

    def get_status(self) -> WorkflowStatus:
        """
        获取当前状态

        Returns:
            WorkflowStatus: 当前工作流状态
        """
        return WorkflowStatus(
            state=self.state,
            current_stage=self.current_stage,
            stage_status=self.stage_status.copy(),
            progress=self._calculate_progress()
        )

    # ========== 内部方法 ==========

    def _get_stage_executor(self, stage_num: int) -> Any:
        """获取Stage执行器"""
        if stage_num not in self._stage_executors:
            # 延迟加载以避免循环依赖
            if stage_num == 1:
                from stage1_novel import NovelGenerationStage
                self._stage_executors[stage_num] = NovelGenerationStage(self.config)
            elif stage_num == 2:
                from stage2_visual import ImageGenerationStage
                self._stage_executors[stage_num] = ImageGenerationStage(self.config)
            elif stage_num == 3:
                from stage3_audio import AudioGenerationStage
                self._stage_executors[stage_num] = AudioGenerationStage(self.config)
            elif stage_num == 4:
                from stage4_merge import VideoCompositionStage
                self._stage_executors[stage_num] = VideoCompositionStage(self.config)
        
        return self._stage_executors[stage_num]

    def _check_complete_cache(self, novel_name: str) -> Optional[Dict]:
        """检查完整缓存"""
        cache_key = f"complete:{novel_name}"
        return self.cache_manager.get(cache_key)

    def _check_stage_cache(self, stage_num: int, context: Dict) -> Optional[Any]:
        """检查Stage缓存"""
        novel_name = context['novel_name']
        cache_key = f"stage:{stage_num}:{novel_name}"
        return self.cache_manager.get(cache_key)

    def _save_stage_cache(self, stage_num: int, context: Dict, result: Any) -> None:
        """保存Stage缓存"""
        novel_name = context['novel_name']
        cache_key = f"stage:{stage_num}:{novel_name}"
        self.cache_manager.set(cache_key, result)

    def _calculate_progress(self) -> float:
        """计算整体进度"""
        if not self.current_stage:
            return 0.0

        # Stage权重
        stage_weights = {1: 0.4, 2: 0.3, 3: 0.2, 4: 0.1}

        completed_stages = sum(
            1 for status in self.stage_status.values()
            if status in (StageStatus.COMPLETED, StageStatus.CACHED)
        )

        current_stage_progress = 0.0
        if (
            self.current_stage 
            and self.stage_status.get(self.current_stage) == StageStatus.RUNNING
        ):
            current_stage_progress = 0.5

        total_progress = (
            sum(stage_weights[i] for i in range(1, completed_stages + 1)) +
            stage_weights.get(self.current_stage, 0) * current_stage_progress
        )

        return min(total_progress, 1.0)
