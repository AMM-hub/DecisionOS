"""Tool-bound agent loop.

The model chooses tools and narrates their results; it never computes numbers.
After generation every numeric token in the answer is checked against the tool
results and the user prompt. Ungrounded numbers are surfaced in a warning and
logged, never silently accepted.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .constants import SYSTEM_PROMPT
from .providers import ProviderError
from .tools import ToolContext, execute_tool, tool_schemas

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 6
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _numeric_tokens(text: str) -> list[str]:
    return [match.group(0) for match in _NUMBER_RE.finditer(text or "")]


def _normalise_token(token: str) -> str:
    cleaned = token.replace(",", "").strip()
    if "." in cleaned:
        cleaned = cleaned.rstrip("0").rstrip(".")
    return cleaned


def ungrounded_numbers(answer: str, tool_results: list[dict[str, Any]], user_prompt: str) -> list[str]:
    corpus = json.dumps(tool_results, default=str) + "\n" + (user_prompt or "")
    allowed = {_normalise_token(token) for token in _numeric_tokens(corpus)}
    ungrounded: list[str] = []
    for token in _numeric_tokens(answer):
        normalised = _normalise_token(token)
        if normalised and normalised not in allowed and token not in ungrounded:
            ungrounded.append(token)
    return ungrounded


def _assistant_message(response: dict[str, Any]) -> dict[str, Any]:
    tool_calls = [
        {
            "id": call["id"],
            "type": "function",
            "function": {"name": call["name"], "arguments": json.dumps(call.get("arguments") or {})},
        }
        for call in response.get("tool_calls") or []
    ]
    message: dict[str, Any] = {"role": "assistant", "content": response.get("content") or ""}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def run_agent(
    provider,
    *,
    model: str | None = None,
    tool_context: ToolContext,
    user_prompt: str | None = None,
    history: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
    model_id: str | None = None,
    registry: Any = None,
) -> dict[str, Any]:
    selected_model = model_id or model
    if not selected_model:
        raise ProviderError("no model configured for this provider", code="model_not_configured")

    if messages is not None:
        convo: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in messages:
            if item.get("role") in {"user", "assistant"} and item.get("content"):
                convo.append({"role": item["role"], "content": item["content"]})
        if user_prompt is None:
            user_prompt = next(
                (item["content"] for item in reversed(messages) if item.get("role") == "user" and item.get("content")),
                "",
            )
        working_messages = convo
    else:
        working_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history or []:
            if item.get("role") in {"user", "assistant"} and item.get("content"):
                working_messages.append({"role": item["role"], "content": item["content"]})
        working_messages.append({"role": "user", "content": user_prompt or ""})
        user_prompt = user_prompt or ""
    messages = working_messages

    tool_trace: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []
    usage_events: list[dict[str, Any]] = []
    prompt_tokens = 0
    completion_tokens = 0
    answer = ""

    for round_index in range(MAX_TOOL_ROUNDS):
        response = provider.chat(messages=messages, model=selected_model, tools=tool_schemas())
        usage = response.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        usage_events.append(
            {
                "model_id": selected_model,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "latency_ms": response.get("latency_ms"),
                "round": round_index,
            }
        )

        calls = response.get("tool_calls") or []
        if not calls:
            answer = response.get("content") or ""
            break

        messages.append(_assistant_message(response))
        for call in calls:
            result = execute_tool(tool_context, call["name"], call.get("arguments") or {})
            tool_results.append(result)
            tool_trace.append(
                {
                    "name": call["name"],
                    "input": call.get("arguments") or {},
                    "ok": bool(result.get("ok")),
                    "evidence_ref": result.get("evidence_ref"),
                    "refused": bool(result.get("refused")),
                    "code": result.get("code"),
                    "error": result.get("error"),
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "name": call["name"],
                    "content": json.dumps(result, default=str),
                }
            )
    else:
        response = provider.chat(messages=messages, model=selected_model, tools=None)
        usage = response.get("usage") or {}
        prompt_tokens += int(usage.get("prompt_tokens") or 0)
        completion_tokens += int(usage.get("completion_tokens") or 0)
        usage_events.append(
            {
                "model_id": selected_model,
                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                "completion_tokens": int(usage.get("completion_tokens") or 0),
                "latency_ms": response.get("latency_ms"),
                "round": MAX_TOOL_ROUNDS,
            }
        )
        answer = response.get("content") or "Tool round limit reached; no further tool calls were executed."

    ungrounded = ungrounded_numbers(answer, tool_results, user_prompt)
    warning: dict[str, Any] | None = None
    if ungrounded:
        warning = {"ungrounded_numbers": ungrounded}
        logger.warning(
            "AI answer contained ungrounded numbers",
            extra={"ungrounded_numbers": ungrounded},
        )

    result: dict[str, Any] = {
        "answer": answer,
        "tool_calls": tool_trace,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "usage_events": usage_events,
        "latency_ms": sum(int(event.get("latency_ms") or 0) for event in usage_events),
    }
    if warning is not None:
        result["warning"] = warning
        result["ungrounded_numbers"] = ungrounded
    return result


__all__ = ["MAX_TOOL_ROUNDS", "ProviderError", "run_agent", "ungrounded_numbers"]
