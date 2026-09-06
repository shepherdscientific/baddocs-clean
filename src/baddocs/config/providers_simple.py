"""Simple provider registry backed by any OpenAI-compatible endpoint.

The richer multi-provider layer this project was originally designed around isn't
shipped in this tree. This module provides the small surface the web server
actually uses (``providers_config``, ``SimpleProvidersConfigManager``,
``SimpleProviderRegistry``) wired to a single OpenAI-compatible endpoint via the
same env the CLI generator uses:

    AI_PROVIDER   provider label (default "openai")
    AI_BASE_URL   base URL (default https://api.openai.com/v1)
    AI_MODEL      model name (default gpt-4o-mini)
    AI_API_KEY    API key (falls back to OPENAI_API_KEY)

Works with OpenAI, OpenRouter, DeepSeek, a local llama.cpp/Ollama, or a LiteLLM
hub — anything that speaks /chat/completions.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.request
from typing import Dict, List

from ..mcp_servers.llm.providers.base import BaseProvider, LLMRequest, LLMResponse


def _config() -> dict:
    return {
        "provider": os.getenv("AI_PROVIDER") or "openai",
        "base_url": (os.getenv("AI_BASE_URL") or "https://api.openai.com/v1").rstrip("/"),
        "model": os.getenv("AI_MODEL") or "gpt-4o-mini",
        "api_key": os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
    }


class OpenAICompatibleProvider(BaseProvider):
    """Talks to any OpenAI-compatible /chat/completions endpoint."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        cfg = self.config or _config()
        model = request.model or cfg["model"]

        def _call() -> LLMResponse:
            t0 = time.time()
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": request.system or "You are a precise documentation writer."},
                    {"role": "user", "content": request.prompt},
                ],
                "temperature": request.temperature,
                "max_tokens": request.max_tokens,
            }).encode()
            headers = {"Content-Type": "application/json"}
            if cfg.get("api_key"):
                headers["Authorization"] = f"Bearer {cfg['api_key']}"
            req = urllib.request.Request(f"{cfg['base_url']}/chat/completions", data=payload, headers=headers)
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read())
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage") or {}
            return LLMResponse(
                content=content,
                model=model,
                provider=self.name,
                processing_time_ms=int((time.time() - t0) * 1000),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )

        try:
            return await asyncio.to_thread(_call)
        except Exception as e:  # noqa: BLE001
            return LLMResponse(error=str(e), model=model, provider=self.name)


class SimpleProviderRegistry:
    """Holds the configured providers and routes generate() to one."""

    def __init__(self, providers: Dict[str, BaseProvider]) -> None:
        self.providers = providers or {}

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.providers:
            return LLMResponse(error="No LLM providers configured (set AI_API_KEY / AI_BASE_URL / AI_MODEL).")
        # MVP: a single endpoint. Honor request.model's provider if named, else first.
        provider = self.providers.get(getattr(request, "provider", None)) or next(iter(self.providers.values()))
        return await provider.generate(request)

    async def shutdown(self) -> None:
        for p in self.providers.values():
            try:
                await p.shutdown()
            except Exception:  # noqa: BLE001
                pass


class SimpleProvidersConfigManager:
    """Builds a SimpleProviderRegistry from AI_* env and answers info/cost queries."""

    def __init__(self) -> None:
        self._cfg = _config()

    async def create_registry_for_mvp(self, mvp_tier: str = "budget") -> SimpleProviderRegistry:
        cfg = _config()
        name = cfg["provider"] or "openai"
        return SimpleProviderRegistry({name: OpenAICompatibleProvider(name, cfg)})

    def get_provider_info(self) -> List[dict]:
        c = _config()
        return [{
            "name": c["provider"],
            "base_url": c["base_url"],
            "model": c["model"],
            "configured": bool(c["api_key"]),
        }]

    def get_available_mvp_configs(self) -> List[dict]:
        return [{"tier": "budget", "description": "Single OpenAI-compatible endpoint from AI_* env"}]

    def get_cost_estimate(self, mvp_config: str, monthly_requests: int = 1000) -> dict:
        return {
            "mvp_config": mvp_config,
            "monthly_requests": monthly_requests,
            "estimate_usd": None,
            "note": "Cost estimation is not modeled in this build; depends on the configured endpoint.",
        }


# Module-level singleton used by web/main.py.
providers_config = SimpleProvidersConfigManager()
