"""LLM wrapper that logs every call (model, tokens, cost) to the database.

The design goal is auditability: *every* call made through :class:`LLMClient`
persists an :class:`~mathforge.schema.LLMCall` row, whether it hit a real
provider or the offline echo backend. Swap in a real provider by passing a
``backend`` callable (see :class:`Backend`) — the accounting is provider
agnostic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from mathforge import db
from mathforge.schema import LLMCall

__all__ = [
    "ModelPricing",
    "PRICING",
    "RawCompletion",
    "LLMResponse",
    "Backend",
    "echo_backend",
    "make_openai_backend",
    "make_anthropic_backend",
    "estimate_tokens",
    "LLMClient",
]


# --------------------------------------------------------------------------- #
# Pricing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ModelPricing:
    """USD price per 1M tokens."""

    input_per_1m: float
    output_per_1m: float

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (
            prompt_tokens / 1_000_000 * self.input_per_1m
            + completion_tokens / 1_000_000 * self.output_per_1m
        )


# A small, editable price book. Unknown models simply log cost 0.0.
PRICING: dict[str, ModelPricing] = {
    "gpt-4o": ModelPricing(2.50, 10.00),
    "gpt-4o-mini": ModelPricing(0.15, 0.60),
    "o3": ModelPricing(2.00, 8.00),
    "o4-mini": ModelPricing(1.10, 4.40),
    "claude-3-5-sonnet": ModelPricing(3.00, 15.00),
    "claude-3-5-haiku": ModelPricing(0.80, 4.00),
    "echo": ModelPricing(0.0, 0.0),
}


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) for backends without usage data."""
    if not text:
        return 0
    return max(1, len(text) // 4)


# --------------------------------------------------------------------------- #
# Backend protocol
# --------------------------------------------------------------------------- #
@dataclass
class RawCompletion:
    """What a backend returns: text plus optional exact token usage."""

    text: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    raw: Any = None


class Backend(Protocol):
    """Callable that turns a prompt into a :class:`RawCompletion`."""

    def __call__(
        self, prompt: str, system: Optional[str] = None, **kwargs: Any
    ) -> RawCompletion: ...


def echo_backend(
    prompt: str, system: Optional[str] = None, **kwargs: Any
) -> RawCompletion:
    """Offline backend: echoes the prompt so the pipeline runs without keys."""
    text = f"[echo] {prompt}"
    return RawCompletion(
        text=text,
        prompt_tokens=estimate_tokens((system or "") + prompt),
        completion_tokens=estimate_tokens(text),
        raw={"backend": "echo"},
    )


def make_openai_backend(
    model: str,
    *,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    api_key_env: str = "OPENAI_API_KEY",
    default_temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
) -> Backend:
    """A real backend over any OpenAI-compatible Chat Completions API.

    Works for OpenAI (GPT-5.x), Z.ai/GLM, DeepSeek, Qwen, and OpenRouter (which
    also proxies Anthropic/Gemini) — just set ``base_url`` and ``api_key_env``.
    Reasoning models that reject a ``temperature`` param are retried without it.
    """

    def backend(prompt: str, system: Optional[str] = None, **kwargs: Any) -> RawCompletion:
        import os

        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=api_key or os.environ.get(api_key_env))
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        params: dict[str, Any] = {"model": model, "messages": messages}
        temp = kwargs.get("temperature", default_temperature)
        if temp is not None:
            params["temperature"] = temp
        top_p = kwargs.get("top_p")
        if top_p is not None:
            params["top_p"] = top_p
        if max_output_tokens is not None:
            params["max_tokens"] = max_output_tokens

        try:
            resp = client.chat.completions.create(**params)
        except Exception:
            params.pop("temperature", None)  # some reasoning models reject it
            resp = client.chat.completions.create(**params)

        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        return RawCompletion(
            text=text,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            raw={
                "backend": "openai",
                "model": model,
                "finish_reason": getattr(resp.choices[0], "finish_reason", None),
                "request_id": getattr(resp, "id", None),
            },
        )

    return backend


def make_anthropic_backend(
    model: str,
    *,
    base_url: Optional[str] = None,
    base_url_env: str = "ANTHROPIC_BASE_URL",
    auth_token: Optional[str] = None,
    auth_token_env: str = "ANTHROPIC_AUTH_TOKEN",
    api_key_env: str = "ANTHROPIC_API_KEY",
    anthropic_version: str = "2023-06-01",
    default_temperature: Optional[float] = None,
    max_output_tokens: int = 8192,
    effort: Optional[str] = None,
    timeout: float = 180.0,
) -> Backend:
    """A real backend over the Anthropic Messages API (``/v1/messages``).

    Works against Anthropic directly or any Anthropic-compatible gateway (e.g. a
    TrueFoundry/promptlens proxy) — set ``ANTHROPIC_BASE_URL``. Auth is a bearer
    ``ANTHROPIC_AUTH_TOKEN`` (gateway tokens) or, if that's absent, an
    ``x-api-key`` from ``ANTHROPIC_API_KEY``. Uses stdlib ``urllib`` so no extra
    dependency is required.
    """

    def backend(prompt: str, system: Optional[str] = None, **kwargs: Any) -> RawCompletion:
        import json as _json
        import os
        import urllib.error
        import urllib.request

        url = (
            base_url or os.environ.get(base_url_env) or "https://api.anthropic.com"
        ).rstrip("/") + "/v1/messages"
        headers = {"content-type": "application/json", "anthropic-version": anthropic_version}
        tok = auth_token or os.environ.get(auth_token_env)
        key = os.environ.get(api_key_env)
        if tok:
            headers["authorization"] = "Bearer " + tok
        elif key:
            headers["x-api-key"] = key

        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system
        eff = kwargs.get("effort", effort)
        if eff is not None:
            # Opus 4.8 adaptive extended thinking (gateway form); temperature is
            # not sent with thinking.
            body["thinking"] = {"type": "adaptive"}
            body["output_config"] = {"effort": eff}
        else:
            temp = kwargs.get("temperature", default_temperature)
            if temp is not None:
                body["temperature"] = temp
            top_p = kwargs.get("top_p")
            if top_p is not None:
                body["top_p"] = top_p

        def _post(b: dict[str, Any]) -> dict:
            req = urllib.request.Request(
                url, data=_json.dumps(b).encode(), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _json.loads(r.read())

        try:
            payload = _post(body)
        except urllib.error.HTTPError:
            # Some models (e.g. claude-opus-4-8 via the gateway) reject temperature.
            if "temperature" in body:
                body.pop("temperature")
                payload = _post(body)
            else:
                raise

        text = "".join(
            b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
        )
        usage = payload.get("usage") or {}
        return RawCompletion(
            text=text,
            prompt_tokens=usage.get("input_tokens"),
            completion_tokens=usage.get("output_tokens"),
            raw={
                "backend": "anthropic",
                "model": model,
                "stop_reason": payload.get("stop_reason"),
                "request_id": payload.get("id"),
            },
        )

    return backend


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #
@dataclass
class LLMResponse:
    """The client's return value; ``call_id`` is the persisted log row id."""

    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: float
    call_id: Optional[int] = None
    raw: Any = field(default=None, repr=False)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
_PREVIEW_CHARS = 500


class LLMClient:
    """A thin, logging wrapper around a text-completion backend."""

    def __init__(
        self,
        model: str = "echo",
        *,
        provider: Optional[str] = None,
        backend: Optional[Backend] = None,
        pricing: Optional[ModelPricing] = None,
        db_url: Optional[str] = None,
        purpose: Optional[str] = None,
    ) -> None:
        self.model = model
        self.provider = provider
        self.backend: Backend = backend or echo_backend
        self.pricing = pricing or PRICING.get(model)
        self.db_url = db_url
        self.default_purpose = purpose

    def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        purpose: Optional[str] = None,
        related_id: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Run one completion and persist an :class:`LLMCall` audit row."""
        start = time.perf_counter()
        completion = self.backend(prompt, system=system, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000.0

        prompt_tokens = (
            completion.prompt_tokens
            if completion.prompt_tokens is not None
            else estimate_tokens((system or "") + prompt)
        )
        completion_tokens = (
            completion.completion_tokens
            if completion.completion_tokens is not None
            else estimate_tokens(completion.text)
        )
        total_tokens = prompt_tokens + completion_tokens
        cost = self.pricing.cost(prompt_tokens, completion_tokens) if self.pricing else 0.0

        log_meta = dict(meta or {})
        if isinstance(completion.raw, dict):
            # Persist only small, non-payload transport metadata.  Full provider
            # responses can contain sensitive or very large content.
            for key in ("backend", "stop_reason", "finish_reason", "request_id"):
                value = completion.raw.get(key)
                if value is not None:
                    log_meta.setdefault(key, value)

        call_id = self._log(
            prompt=prompt,
            system=system,
            response_text=completion.text,
            purpose=purpose or self.default_purpose,
            related_id=related_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost=cost,
            latency_ms=latency_ms,
            meta=log_meta,
        )

        return LLMResponse(
            text=completion.text,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            call_id=call_id,
            raw=completion.raw,
        )

    def _log(
        self,
        *,
        prompt: str,
        system: Optional[str],
        response_text: str,
        purpose: Optional[str],
        related_id: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost: float,
        latency_ms: float,
        meta: dict[str, Any],
    ) -> Optional[int]:
        req_preview = (system + "\n\n" if system else "") + prompt
        record = LLMCall(
            provider=self.provider,
            model=self.model,
            purpose=purpose,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
            request_preview=req_preview[:_PREVIEW_CHARS],
            response_preview=response_text[:_PREVIEW_CHARS],
            related_id=related_id,
            meta=meta,
        )
        db.init_db(self.db_url)
        with db.session_scope(self.db_url) as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return record.id
