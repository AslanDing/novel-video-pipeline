"""
api_service/backends/nvidia_nim.py
NVIDIA NIM LLM 后端封装
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Dict, List, Optional

import httpx

from api_service.config import backend_config
from api_service.models import ChatMessage, LLMRequest, LLMResponse, LLMUsage


class NVIDIA_NIM_Backend:
    """NVIDIA NIM LLM 后端"""

    def __init__(self):
        cfg = backend_config("llm")
        self.base_url = cfg.get("base_url", "https://integrate.api.nvidia.com/v1").rstrip("/")
        self.api_key = cfg.get("api_key", "")
        self.model = cfg.get("model", "nvidia/nemotron-3-super-120b-a12b")
        self.timeout = cfg.get("timeout_seconds", 300)
        self.max_retries = cfg.get("max_retries", 3)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(self.timeout, connect=10.0),
        )

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

    async def generate(self, req: LLMRequest) -> LLMResponse:
        """非流式生成"""
        payload = self._build_payload(req)
        payload["stream"] = False

        last_err = Exception("unknown")
        for attempt in range(self.max_retries):
            try:
                resp = await self._client.post("/chat/completions", json=payload)
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                usage_raw = data.get("usage", {})
                # gpt-oss-120b returns content in reasoning_content when content is null
                message = choice["message"]
                content = message.get("content") or message.get("reasoning_content") or ""
                return LLMResponse(
                    content=content,
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
        raise RuntimeError(f"NVIDIA NIM generate failed after {self.max_retries} retries: {last_err}")

    async def stream(self, req: LLMRequest) -> AsyncGenerator[str, None]:
        """流式生成"""
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
        return [self.model]

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/models", timeout=5.0)
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()


# ── 单例 ──────────────────────────────────────────────────────────────────────
_backend: Optional[NVIDIA_NIM_Backend] = None


def get_llm_backend() -> NVIDIA_NIM_Backend:
    global _backend
    if _backend is None:
        _backend = NVIDIA_NIM_Backend()
    return _backend