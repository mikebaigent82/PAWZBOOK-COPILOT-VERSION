"""Chat-completions client for any OpenAI/OpenRouter-compatible endpoint.

Only tool-calling is used: the model is given the tool list and must fetch all
numbers through tools.
"""
from __future__ import annotations

import json

import httpx

from ..config import Settings


class LLMError(RuntimeError):
    pass


class ChatProvider:
    def __init__(self, settings: Settings):
        self.base_url = settings.ai_base_url.rstrip("/")
        self.api_key = settings.ai_api_key
        self.model = settings.ai_model

    def complete(self, messages: list[dict], tools: list[dict]) -> dict:
        """Returns {"content": str, "tool_calls": [{"id", "name", "arguments"}]}."""
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": [{"type": "function", "function": t} for t in tools],
            "tool_choice": "auto",
            "temperature": 0.2,
        }
        try:
            resp = httpx.post(f"{self.base_url}/chat/completions", json=payload, timeout=60,
                              headers={"Authorization": f"Bearer {self.api_key}"})
            resp.raise_for_status()
            msg = resp.json()["choices"][0]["message"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"The AI service could not be reached ({type(exc).__name__}).") from exc
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append({"id": c.get("id") or f"call_{len(calls)}", "name": c["function"]["name"],
                          "arguments": args if isinstance(args, dict) else {}})
        return {"content": msg.get("content") or "", "tool_calls": calls}
