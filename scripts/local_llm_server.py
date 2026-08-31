#!/usr/bin/env python3
"""Tiny OpenAI-compatible local LLM server (llama-cpp-python, CPU).

Serves GET /health, GET /v1/models, POST /v1/chat/completions, POST /v1/completions.
Bind 127.0.0.1:8088. A copy may already be running via llama_cpp.server;
do not start a second process on this port.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI
from llama_cpp import Llama
from pydantic import BaseModel, Field

MODEL_PATH = "/workspace/eve-miro/models/qwen2.5-0.5b-instruct-q4_k_m.gguf"
MODEL_ID = "qwen2.5-0.5b-instruct"
HOST = "127.0.0.1"
PORT = 8088

llm = Llama(
    model_path=MODEL_PATH,
    n_ctx=2048,
    n_threads=4,
    n_gpu_layers=0,
    verbose=False,
)

app = FastAPI(title="eve-miro local LLM")


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatRequest(BaseModel):
    model: str | None = None
    messages: list[ChatMessage]
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


class CompletionRequest(BaseModel):
    model: str | None = None
    prompt: str | list[str] = ""
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": MODEL_ID}


@app.get("/v1/models")
def list_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [{"id": MODEL_ID, "object": "model", "owned_by": "local"}],
    }


def _chat_content(messages: list[ChatMessage]) -> str:
    out = llm.create_chat_completion(
        messages=[{"role": m.role, "content": m.content} for m in messages],
        max_tokens=256,
        temperature=0.7,
    )
    return out["choices"][0]["message"].get("content") or ""


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest) -> dict[str, Any]:
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    result = llm.create_chat_completion(
        messages=messages,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    content = (result["choices"][0]["message"].get("content") or "")
    usage = result.get("usage") or {}
    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": req.model or MODEL_ID,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": result["choices"][0].get("finish_reason", "stop"),
            }
        ],
        "usage": usage,
    }


@app.post("/v1/completions")
def completions(req: CompletionRequest) -> dict[str, Any]:
    prompt = req.prompt if isinstance(req.prompt, str) else "".join(req.prompt)
    result = llm.create_completion(
        prompt=prompt,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
    )
    text = result["choices"][0].get("text") or ""
    usage = result.get("usage") or {}
    return {
        "id": f"cmpl-{uuid.uuid4()}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": req.model or MODEL_ID,
        "choices": [
            {
                "index": 0,
                "text": text,
                "finish_reason": result["choices"][0].get("finish_reason", "stop"),
            }
        ],
        "usage": usage,
    }


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
