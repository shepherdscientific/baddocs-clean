"""LLM provider base types.

Minimal, dependency-free request/response dataclasses and a provider base class,
shared by the concrete providers and the simple registry (config/providers_simple).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMRequest:
    prompt: str
    model: Optional[str] = None
    temperature: float = 0.2
    max_tokens: int = 2048
    context_type: Optional[str] = None
    language: Optional[str] = None
    file_path: Optional[str] = None
    system: Optional[str] = None


@dataclass
class LLMResponse:
    content: str = ""
    model: Optional[str] = None
    provider: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: Optional[int] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None


class BaseProvider:
    """Interface for an LLM provider."""

    def __init__(self, name: str, config: Optional[dict] = None) -> None:
        self.name = name
        self.config = config or {}

    async def generate(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - interface
        raise NotImplementedError

    async def shutdown(self) -> None:
        pass
