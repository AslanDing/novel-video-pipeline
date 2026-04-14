"""
api_service/routers/llm.py
LLM 文本生成路由

端点：
  POST /llm/generate     → 非流式，返回完整响应
  POST /llm/stream       → Server-Sent Events 流式
  GET  /llm/models       → 列出可用模型
  GET  /llm/health       → 健康检查
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api_service.backends.llama_cpp import get_llm_backend
from api_service.models import LLMRequest, LLMResponse

router = APIRouter(prefix="/llm", tags=["LLM"])


@router.post("/generate", response_model=LLMResponse)
async def generate(req: LLMRequest) -> LLMResponse:
    """
    非流式 LLM 文本生成。
    等待模型完整响应后返回。
    """
    backend = get_llm_backend()
    try:
        return await backend.generate(req)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/stream")
async def stream(req: LLMRequest) -> StreamingResponse:
    """
    流式 LLM 文本生成（Server-Sent Events）。
    客户端以 text/event-stream 接收 token。
    """
    backend = get_llm_backend()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            async for token in backend.stream(req):
                # SSE 格式：data: <text>\n\n
                yield f"data: {token}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {str(e)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/models")
async def list_models():
    """列出 llama.cpp 加载的可用模型"""
    backend = get_llm_backend()
    models = await backend.list_models()
    return {"models": models}


@router.get("/health")
async def health():
    """llama.cpp 后端健康检查"""
    backend = get_llm_backend()
    ok = await backend.health()
    return {"healthy": ok, "backend": "llama_cpp"}
