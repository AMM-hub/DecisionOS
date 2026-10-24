"""Shared AI-layer constants."""

from __future__ import annotations

MODEL_ROLES: tuple[str, ...] = ("primary", "fast", "reasoning", "coding", "embedding", "fallback")

SYSTEM_PROMPT = (
    "You are DecisionOS Intelligence. You may only state numbers that appear in tool results "
    "in this conversation. If a tool refuses or returns no data, say so plainly and never "
    "estimate. Cite the evidence_ref of each result you use."
)
