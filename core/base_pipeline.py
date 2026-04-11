"""
管道基类 - 所有阶段的抽象基类
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from pathlib import Path
import json
import asyncio
from datetime import datetime


class PipelineStage(ABC):
    """
    管道阶段基类
    
    所有阶段（小说生成、图像生成、音频生成、视频合并）
    都应继承此类
    """
    
    def __init__(self, stage_name: str, config: Optional[Dict] = None):
        self.stage_name = stage_name
        self.config = config or {}
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.metrics: Dict[str, Any] = {}
        
    @abstractmethod
    async def process(self, input_data: Any) -> Any:
        """
        处理输入数据
        
        Args:
            input_data: 阶段输入数据
            
        Returns:
            阶段输出数据
        """
        pass
    
    @abstractmethod
    def validate_input(self, input_data: Any) -> bool:
        """
        验证输入数据
        
        Args:
            input_data: 输入数据
            
        Returns:
            是否有效
        """
        pass
    
    async def execute(self, input_data: Any) -> Any:
        """
        执行阶段（带验证和度量）
        
        Args:
            input_data: 输入数据
            
        Returns:
            输出数据
        """
        print(f"\n{'='*60}")
        print(f"🚀 开始执行阶段: {self.stage_name}")
        print(f"{'='*60}\n")
        
        # 验证输入
        if not self.validate_input(input_data):
            raise ValueError(f"阶段 {self.stage_name} 的输入验证失败")
        
        # 记录开始时间
        self.start_time = datetime.now()
        
        try:
            # 执行处理
            result = await self.process(input_data)
            
            # 记录结束时间
            self.end_time = datetime.now()
            
            # 计算指标
            duration = (self.end_time - self.start_time).total_seconds()
            self.metrics = {
                "duration_seconds": duration,
                "start_time": self.start_time.isoformat(),
                "end_time": self.end_time.isoformat(),
            }
            
            print(f"\n{'='*60}")
            print(f"✅ 阶段完成: {self.stage_name}")
            print(f"⏱️  耗时: {duration:.2f} 秒")
            print(f"{'='*60}\n")
            
            return result
            
        except Exception as e:
            self.end_time = datetime.now()
            duration = (self.end_time - self.start_time).total_seconds()
            
            print(f"\n{'='*60}")
            print(f"❌ 阶段失败: {self.stage_name}")
            print(f"⏱️  耗时: {duration:.2f} 秒")
            print(f"💥 错误: {str(e)}")
            print(f"{'='*60}\n")
            
            raise


class Pipeline:
    """
    完整管道编排器
    
    按顺序执行所有阶段
    """
    
    def __init__(self, stages: List[PipelineStage]):
        self.stages = stages
        self.results: Dict[str, Any] = {}
        self.pipeline_metrics: Dict[str, Any] = {}
        
    async def run(self, initial_input: Any) -> Dict[str, Any]:
        """
        运行完整管道
        
        Args:
            initial_input: 初始输入数据
            
        Returns:
            包含所有阶段结果的字典
        """
        print(f"\n{'#'*70}")
        print(f"#{'':^68}#")
        print(f"#{'🎬 开始执行 AI爽文创作流水线':^58}#")
        print(f"#{'':^68}#")
        print(f"{'#'*70}\n")
        
        current_input = initial_input
        pipeline_start = datetime.now()
        
        try:
            for i, stage in enumerate(self.stages, 1):
                print(f"\n📊 进度: {i}/{len(self.stages)} 阶段")
                
                # 执行阶段
                result = await stage.execute(current_input)
                
                # 保存结果
                self.results[stage.stage_name] = {
                    "output": result,
                    "metrics": stage.metrics,
                }
                
                # 更新下一阶段的输入
                current_input = result
            
            pipeline_end = datetime.now()
            total_duration = (pipeline_end - pipeline_start).total_seconds()
            
            self.pipeline_metrics = {
                "total_duration_seconds": total_duration,
                "start_time": pipeline_start.isoformat(),
                "end_time": pipeline_end.isoformat(),
                "stages_count": len(self.stages),
            }
            
            print(f"\n{'#'*70}")
            print(f"#{'':^68}#")
            print(f"#{'🎉 流水线执行完成！':^58}#")
            print(f"#{'':^68}#")
            print(f"#{'⏱️  总耗时: ' + f'{total_duration:.2f} 秒':^58}#")
            print(f"#{'📦 阶段数: ' + str(len(self.stages)):^58}#")
            print(f"#{'':^68}#")
            print(f"{'#'*70}\n")
            
            return self.results
            
        except Exception as e:
            pipeline_end = datetime.now()
            total_duration = (pipeline_end - pipeline_start).total_seconds()
            
            print(f"\n{'#'*70}")
            print(f"#{'':^68}#")
            print(f"#{'💥 流水线执行失败！':^58}#")
            print(f"#{'':^68}#")
            print(f"#{'⏱️  已耗时: ' + f'{total_duration:.2f} 秒':^58}#")
            print(f"#{'❌ 错误: ' + str(e)[:50]:^58}#")
            print(f"#{'':^68}#")
            print(f"{'#'*70}\n")
            
            raise
    
    def save_results(self, output_dir: Path):
        """保存所有阶段结果到JSON"""
        output_path = output_dir / "pipeline_results.json"
        
        # 序列化结果（简化版）
        serializable_results = {}
        for stage_name, data in self.results.items():
            serializable_results[stage_name] = {
                "metrics": data.get("metrics", {}),
                # 不保存实际输出内容（可能很大）
                "output_type": type(data.get("output")).__name__,
            }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "pipeline_metrics": self.pipeline_metrics,
                "stage_results": serializable_results,
            }, f, ensure_ascii=False, indent=2)
        
        print(f"📁 流水线结果已保存: {output_path}")


# ========== 便捷函数 ==========

async def quick_generate(
    prompt: str,
    system_prompt: Optional[str] = None,
    use_mock: bool = False,
) -> str:
    """
    快速生成文本的便捷函数
    
    Args:
        prompt: 提示词
        system_prompt: 系统提示词
        use_mock: 是否使用模拟客户端
    
    Returns:
        生成的文本
    """
    if use_mock or not NVIDIA_NIM_CONFIG.get("api_key"):
        print("⚠️  使用Mock LLM响应")
        return f"【模拟响应】这是根据提示词生成的内容: {prompt[:50]}..."
    
    client = NVIDIA_NIM_Client()
    try:
        response = await client.generate(
            prompt=prompt,
            system_prompt=system_prompt,
        )
        return response.content
    finally:
        await client.close()


# ========== 测试代码 ==========

async def test_llm_client():
    """测试LLM客户端"""
    print("🧪 测试LLM客户端...")
    
    # 测试Mock客户端
    print("\n1. 测试Mock客户端:")
    mock_response = await quick_generate(
        prompt="写一个修仙小说的开头",
        use_mock=True,
    )
    print(f"响应: {mock_response[:100]}...")
    
    # 测试真实客户端（如果配置了API Key）
    if NVIDIA_NIM_CONFIG.get("api_key"):
        print("\n2. 测试真实NVIDIA NIM客户端:")
        try:
            response = await quick_generate(
                prompt="用一句话描述一个修仙故事的开头",
                use_mock=False,
            )
            print(f"✅ 响应: {response}")
        except Exception as e:
            print(f"❌ 错误: {e}")
    else:
        print("\n2. 跳过真实客户端测试（未配置API Key）")
    
    print("\n✅ LLM客户端测试完成!")


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_llm_client())
