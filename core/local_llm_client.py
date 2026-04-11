"""
本地LLM客户端 - 支持Ollama和vLLM
"""

import json
import aiohttp
import asyncio
from typing import Dict, List, Optional, AsyncGenerator, Union
from dataclasses import dataclass
from pathlib import Path

from core.logger import get_logger

logger = get_logger("local_llm_client")


@dataclass
class LocalLLMResponse:
    """本地LLM响应封装"""
    content: str
    usage: Dict[str, int]
    model: str
    finish_reason: str


class OllamaClient:
    """Ollama本地LLM客户端"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:14b",
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
    ) -> LocalLLMResponse:
        """生成文本（非流式）"""
        await self._ensure_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        
        # Ollama 强制 JSON 模式通过 format 字段实现
        if response_format and response_format.get("type") == "json_object":
            payload["format"] = "json"
        
        try:
            async with self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Ollama API错误 (HTTP {response.status}): {error_text}")
                
                data = await response.json()
                message = data.get("message", {})
                
                return LocalLLMResponse(
                    content=message.get("content", ""),
                    usage=data.get("usage", {}),
                    model=self.model,
                    finish_reason=data.get("done_reason", "stop"),
                )
        except Exception as e:
            logger.error(f"Ollama生成失败: {str(e)}")
            raise
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        await self._ensure_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/api/chat",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Ollama API错误 (HTTP {response.status}): {error_text}")
                
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Ollama流式生成失败: {str(e)}")
            raise
    
    async def list_models(self) -> List[str]:
        """列出可用的模型"""
        await self._ensure_session()
        try:
            async with self.session.get(f"{self.base_url}/api/tags") as response:
                if response.status == 200:
                    data = await response.json()
                    return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
        return []
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


class VLLMClient:
    """vLLM本地LLM客户端 (OpenAI兼容API)"""
    
    def __init__(
        self,
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "EMPTY",
        model: str = "Qwen/Qwen3-14B-AWQ",
        temperature: float = 0.7,
        max_tokens: int = 32768,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def _ensure_session(self):
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.api_key}"}
            )
    
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict] = None,
    ) -> LocalLLMResponse:
        """生成文本（非流式）"""
        await self._ensure_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
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
                    raise Exception(f"vLLM API错误 (HTTP {response.status}): {error_text}")
                
                data = await response.json()
                message = data["choices"][0]["message"]
                
                return LocalLLMResponse(
                    content=message.get("content", ""),
                    usage=data.get("usage", {}),
                    model=self.model,
                    finish_reason=data["choices"][0].get("finish_reason", "stop"),
                )
        except Exception as e:
            logger.error(f"vLLM生成失败: {str(e)}")
            raise
    
    async def generate_stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """流式生成文本"""
        await self._ensure_session()
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": True,
        }
        
        try:
            async with self.session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"vLLM API错误 (HTTP {response.status}): {error_text}")
                
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
            logger.error(f"vLLM流式生成失败: {str(e)}")
            raise
    
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()


def get_local_llm_client(
    provider: str = "vllm",
    **kwargs
) -> Union[OllamaClient, VLLMClient]:
    """获取本地LLM客户端实例"""
    if provider == "ollama":
        return OllamaClient(**kwargs)
    elif provider == "vllm":
        return VLLMClient(**kwargs)
    else:
        raise ValueError(f"不支持的本地LLM提供商: {provider}")