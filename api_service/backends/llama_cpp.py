"""
api_service/backends/llama_cpp.py
llama.cpp OpenAI 兼容协议封装

llama.cpp server 已原生兼容 OpenAI /v1/chat/completions 接口，
此模块只做薄封装：HTTP 会话复用、重试、SSE 透传。
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from api_service.config import backend_config
from api_service.models import ChatMessage, LLMRequest, LLMResponse, LLMUsage


class LlamaCppBackend:
    """llama.cpp 推理后端客户端"""

    def __init__(self):
        cfg = backend_config("llm")
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = cfg.get("model", "")
        self.timeout = cfg.get("timeout_seconds", 300)
        self.max_retries = cfg.get("max_retries", 3)
        # 共享 HTTP client（连接池）
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

    # ── internal ──────────────────────────────────────────────────────────────

    def _build_payload(self, req: LLMRequest) -> Dict:
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        payload: Dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "stream": req.stream,
        }
        if req.response_format:
            payload["response_format"] = req.response_format
        return payload

    # ── public ────────────────────────────────────────────────────────────────

    async def generate(self, req: LLMRequest) -> LLMResponse:
        """非流式生成，自动重试"""
        payload = self._build_payload(req)
        payload["stream"] = False

        last_err: Exception = RuntimeError("unknown")
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                usage_raw = data.get("usage", {})
                return LLMResponse(
                    content=choice["message"]["content"],
                    usage=LLMUsage(
                        prompt_tokens=usage_raw.get("prompt_tokens", 0),
                        completion_tokens=usage_raw.get("completion_tokens", 0),
                        total_tokens=usage_raw.get("total_tokens", 0),
                    ),
                    model=data.get("model", self.model),
                    finish_reason=choice.get("finish_reason", "stop"),
                )
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        raise RuntimeError(f"llama.cpp generate failed after {self.max_retries} retries: {last_err}")

    async def stream(self, req: LLMRequest) -> AsyncGenerator[str, None]:
        """流式生成，产出文本 token"""
        payload = self._build_payload(req)
        payload["stream"] = True

        async with self._client.stream("POST", "/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line or line == "data: [DONE]":
                    continue
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        text = delta.get("content")
                        if text:
                            yield text
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    async def list_models(self) -> List[str]:
        """列出 llama.cpp 加载的模型"""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]
        except Exception:
            return [self.model]

    async def health(self) -> bool:
        """健康检查"""
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()


# 全局单例
_backend: Optional[LlamaCppBackend] = None


def get_llm_backend() -> LlamaCppBackend:
    global _backend
    if _backend is None:
        _backend = LlamaCppBackend()
    return _backend
