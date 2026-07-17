"""Minimal streaming client for the Anthropic Messages API.

Uses httpx (already a dependency via mcp) — no SDK required. Supports
streaming text deltas and tool-use blocks, which is everything the
assistant needs.
"""

from __future__ import annotations

import json
import os

import httpx

DEFAULT_MODEL = "claude-sonnet-5"
MODELS = [
    ("claude-sonnet-5", "Claude Sonnet 5 — fast, recommended"),
    ("claude-opus-4-8", "Claude Opus 4.8 — most capable"),
    ("claude-haiku-4-5-20251001", "Claude Haiku 4.5 — cheapest"),
]
_API = "https://api.anthropic.com/v1/messages"
_VERSION = "2023-06-01"


class AiError(Exception):
    pass


class AuthError(AiError):
    pass


def resolve_api_key(cfg) -> str | None:
    """Env var wins (never stored); falls back to the config file."""
    return (os.environ.get("ANTHROPIC_API_KEY")
            or cfg.get("ai", "api_key", default=None)
            or None)


class AnthropicClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL,
                 transport: httpx.BaseTransport | None = None):
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=httpx.Timeout(120, connect=15),
                                    transport=transport)

    def close(self):
        self._client.close()

    def stream_message(self, system: str, messages: list[dict],
                       tools: list[dict], max_tokens: int = 8192,
                       on_text=None, should_stop=None) -> dict:
        """Stream one assistant message.

        Returns {"content": [blocks], "stop_reason": str, "usage": {...}}.
        `on_text(delta)` fires per text fragment; `should_stop()` aborts
        the stream early when it returns True.
        """
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "tools": tools,
            "stream": True,
        }
        headers = {"x-api-key": self.api_key,
                   "anthropic-version": _VERSION,
                   "content-type": "application/json"}
        try:
            with self._client.stream("POST", _API, json=payload,
                                     headers=headers) as resp:
                if resp.status_code == 401:
                    raise AuthError(
                        "The API key was rejected. Check it in Settings "
                        "-> Assistant (or the ANTHROPIC_API_KEY env var).")
                if resp.status_code >= 400:
                    body = resp.read().decode(errors="replace")
                    raise AiError(_friendly_http_error(resp.status_code,
                                                       body))
                return self._consume(resp, on_text, should_stop)
        except httpx.ConnectError as exc:
            raise AiError(f"Could not reach api.anthropic.com: {exc}") \
                from exc
        except httpx.TimeoutException as exc:
            raise AiError("The API request timed out.") from exc

    # ------------------------------------------------------------- SSE

    def _consume(self, resp, on_text, should_stop) -> dict:
        blocks: list[dict] = []
        partial_json: dict[int, str] = {}
        stop_reason = None
        usage: dict = {}
        for event, data in _sse_events(resp.iter_lines()):
            if should_stop and should_stop():
                resp.close()
                stop_reason = "aborted"
                break
            if event == "content_block_start":
                idx = data["index"]
                block = dict(data["content_block"])
                while len(blocks) <= idx:
                    blocks.append(None)
                blocks[idx] = block
                if block["type"] == "tool_use":
                    partial_json[idx] = ""
            elif event == "content_block_delta":
                idx = data["index"]
                delta = data["delta"]
                if delta["type"] == "text_delta":
                    blocks[idx]["text"] = (blocks[idx].get("text", "")
                                           + delta["text"])
                    if on_text:
                        on_text(delta["text"])
                elif delta["type"] == "input_json_delta":
                    partial_json[idx] += delta["partial_json"]
                elif delta["type"] == "thinking_delta":
                    pass
            elif event == "message_delta":
                stop_reason = data["delta"].get("stop_reason", stop_reason)
                usage.update(data.get("usage") or {})
            elif event == "message_start":
                usage.update(data.get("message", {}).get("usage") or {})
            elif event == "error":
                err = data.get("error", {})
                raise AiError(err.get("message", "stream error"))
        for idx, raw in partial_json.items():
            try:
                blocks[idx]["input"] = json.loads(raw) if raw.strip() else {}
            except json.JSONDecodeError as exc:
                raise AiError(
                    f"Model produced invalid tool input JSON: {exc}") \
                    from exc
        return {"content": [b for b in blocks if b is not None],
                "stop_reason": stop_reason, "usage": usage}


def _sse_events(lines):
    """Yield (event, parsed_data) pairs from an SSE line iterator."""
    event = None
    for line in lines:
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = line[5:].strip()
            if data:
                yield event, json.loads(data)
        elif not line:
            event = None


def _friendly_http_error(status: int, body: str) -> str:
    try:
        msg = json.loads(body)["error"]["message"]
    except Exception:                                         # noqa: BLE001
        msg = body[:300]
    if status == 429:
        return f"Rate limited by the API: {msg}"
    if status == 529:
        return "The API is overloaded right now — try again in a moment."
    return f"API error {status}: {msg}"
