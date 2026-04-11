"""
NVIDIA NIM LLM 客户端
支持流式输出和批量请求
"""

import os
import json
import aiohttp
import asyncio
from typing import Dict, List, Optional, AsyncGenerator, Union
from dataclasses import dataclass
from pathlib import Path

# 导入配置
import sys
sys.path.append(str(Path(__file__).parent.parent))
from config.settings import NVIDIA_NIM_CONFIG
from core.logger import get_logger

logger = get_logger("llm_client")


@dataclass
class LLMResponse:
    """LLM响应封装"""
    content: str
    usage: Dict[str, int]
    model: str
    finish_reason: str


@dataclass
class Message:
    """消息格式"""
    role: str  # system, user, assistant
    content: str


class NVIDIA_NIM_Client:
    """
    NVIDIA NIM LLM 客户端
    
    使用说明:
    1. 设置环境变量: NVIDIA_NIM_API_KEY
    2. 或在初始化时传入api_key
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 0.9,
    ):
        self.api_key = api_key or NVIDIA_NIM_CONFIG["api_key"]
        self.base_url = base_url or NVIDIA_NIM_CONFIG["base_url"]
        self.model = model or NVIDIA_NIM_CONFIG["model"]
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        
        # 验证配置
        if not self.api_key:
            logger.warning("NVIDIA_NIM_API_KEY 未设置，LLM功能将无法使用")
            logger.warning("请在环境变量中设置或传入api_key参数")
        
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        """确保aiohttp会话已创建"""
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
            )
    
    def _build_messages(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
    ) -> List[Dict]:
        """构建消息列表"""
        messages = []
        
        # 系统提示词
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # 历史对话
        if history:
            for msg in history:
                messages.append({"role": msg.role, "content": msg.content})
        
        # 当前提示词
        messages.append({"role": "user", "content": prompt})
        
        return messages
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
    ) -> LLMResponse:
        """
        生成文本（非流式）
        
        Args:
            prompt: 用户提示词
            system_prompt: 系统提示词
            history: 对话历史
            temperature: 温度（覆盖默认）
            max_tokens: 最大token数（覆盖默认）
            response_format: 响应格式约束，如 {"type": "json_object"}
        """
        await self._ensure_session()
        
        messages = self._build_messages(prompt, system_prompt, history)
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "top_p": self.top_p,
            "stream": False,
        }
        
        if response_format:
            payload["response_format"] = response_format
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API错误 (HTTP {response.status}): {error_text}")
                
                data = await response.json()
                
                # 解析响应
                choice = data["choices"][0]
                message = choice["message"]
                
                return LLMResponse(
                    content=message["content"],
                    usage=data.get("usage", {}),
                    model=data.get("model", self.model),
                    finish_reason=choice.get("finish_reason", "unknown"),
                )
        
        except Exception as e:
            logger.error(f"LLM生成失败: {str(e)}", exc_info=True)
            raise Exception(f"LLM生成失败: {str(e)}")
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Message]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式生成文本
        
        Yields:
            生成的文本片段
        """
        await self._ensure_session()
        
        messages = self._build_messages(prompt, system_prompt, history)
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "top_p": self.top_p,
            "stream": True,
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"API错误 (HTTP {response.status}): {error_text}")
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line or line == "data: [DONE]":
                        continue
                    
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if "choices" in data and len(data["choices"]) > 0:
                                delta = data["choices"][0].get("delta", {})
                                if "content" in delta:
                                    yield delta["content"]
                        except json.JSONDecodeError:
                            continue
        
        except Exception as e:
            logger.error(f"流式生成失败: {str(e)}", exc_info=True)
            raise Exception(f"流式生成失败: {str(e)}")
    
    async def close(self):
        """关闭会话"""
        if self.session and not self.session.closed:
            await self.session.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


class MockLLMClient:
    """
    模拟LLM客户端（用于测试或API未配置时）
    返回预设的响应
    """
    
    def __init__(self):
        self.mock_responses = {
            "故事": "这是一个精彩的故事开头...",
            "章节": "第一章：惊天奇遇\n\n夜幕降临，乌云密布...",
        }
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        **kwargs
    ) -> LLMResponse:
        """模拟生成"""
        # 根据prompt关键词返回不同响应
        content = "【模拟响应】这是一个生成的文本示例。"
        
        for key, response in self.mock_responses.items():
            if key in prompt:
                content = response
                break
        
        # 如果prompt很长，返回更多内容
        if len(prompt) > 100:
            content += "\n\n" + "这是根据您的详细提示生成的扩展内容..." * 5
        
        return LLMResponse(
            content=content,
            usage={"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            model="mock-llm",
            finish_reason="stop",
        )
    
    async def close(self):
        pass


# 便捷函数：获取LLM客户端实例
async def get_llm_client(use_mock: bool = False) -> Union[NVIDIA_NIM_Client, MockLLMClient]:
    """
    获取LLM客户端实例
    
    Args:
        use_mock: 是否使用模拟客户端（用于测试）
    
    Returns:
        LLM客户端实例
    """
    # if use_mock or not NVIDIA_NIM_CONFIG.get("api_key"):
    #     print("⚠️  使用Mock LLM客户端（API未配置）")
    #     return MockLLMClient()
    
    return NVIDIA_NIM_Client()
