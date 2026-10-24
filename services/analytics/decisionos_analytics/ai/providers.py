"""OpenAI-compatible provider adapter.

Covers DeepSeek, OpenAI, OpenRouter, vLLM, llama.cpp server, and any other
server exposing ``POST /chat/completions`` with tool calling. The adapter is
deliberately small: it normalises transport responses and classifies failures
into a typed :class:`ProviderError` so route handlers can return a stable
``provider_error`` contract instead of leaking a stack trace.
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from typing import Any

_REQUEST_TIMEOUT_SECONDS = 30.0
_MAX_ATTEMPTS = 2


class ProviderError(Exception):
    def __init__(self, message: str, *, code: str = "provider_error", status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.status = status
        self.retryable = retryable


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - configured provider URL
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(
            f"provider returned HTTP {exc.code}",
            status=exc.code,
            retryable=500 <= exc.code < 600,
        ) from exc
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderError("provider request timed out", code="provider_timeout", retryable=True) from exc
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            raise ProviderError("provider request timed out", code="provider_timeout", retryable=True) from exc
        raise ProviderError("provider is unreachable", code="provider_unreachable") from exc
    except OSError as exc:
        raise ProviderError("provider connection failed", code="provider_unreachable") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProviderError("provider returned malformed JSON", code="provider_invalid_response") from exc
    if not isinstance(decoded, dict):
        raise ProviderError("provider returned an unexpected response", code="provider_invalid_response")
    return decoded


def _normalise_arguments(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _normalise_response(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("provider response contained no choices", code="provider_invalid_response")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    content = message.get("content")
    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)

    tool_calls: list[dict[str, Any]] = []
    raw_calls = message.get("tool_calls")
    if isinstance(raw_calls, list):
        for index, call in enumerate(raw_calls):
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            name = function.get("name")
            if not isinstance(name, str) or not name:
                continue
            tool_calls.append(
                {
                    "id": str(call.get("id") or f"call_{index}"),
                    "name": name,
                    "arguments": _normalise_arguments(function.get("arguments")),
                }
            )

    usage_raw = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    usage = {
        "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
        "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
    }
    return {"content": content, "tool_calls": tool_calls, "usage": usage}


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str,
        models: list[str] | None = None,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.models = list(models or [])
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: ProviderError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return _http_post_json(self._url("/chat/completions"), self._headers(), payload, self.timeout)
            except ProviderError as exc:
                last_error = exc
                if exc.retryable and attempt < _MAX_ATTEMPTS - 1:
                    continue
                raise
        raise last_error or ProviderError("provider request failed")

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        selected_model = model or (self.models[0] if self.models else None)
        if not selected_model:
            raise ProviderError("no model configured for this provider", code="model_not_configured")
        payload: dict[str, Any] = {
            "model": selected_model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        started = time.perf_counter()
        result = _normalise_response(self._post(payload))
        result["latency_ms"] = int((time.perf_counter() - started) * 1000)
        result["model"] = selected_model
        return result

    def test_connection(self, model: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            self.chat(
                [{"role": "user", "content": "Reply with the single word OK."}],
                model=model,
                max_tokens=1,
            )
        except ProviderError as exc:
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": str(exc),
            }
        except Exception:  # noqa: BLE001 - a failed probe is data, never a 500
            return {
                "ok": False,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "error": "provider connection test failed",
            }
        return {
            "ok": True,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "error": None,
        }
