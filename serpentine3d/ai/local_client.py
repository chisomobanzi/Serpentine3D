"""LM Studio discovery and OpenAI-compatible streaming, without cloud credentials.

The agent keeps one provider-independent transcript. This adapter translates
tool results and images at the HTTP boundary, retaining every tool-call ID.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import httpx

from .client import AiError, _friendly_http_error

DEFAULT_ENDPOINT = "http://127.0.0.1:1234"


def server_root(endpoint: str) -> str:
    root = endpoint.strip().rstrip("/")
    for suffix in ("/api/v1", "/v1"):
        if root.endswith(suffix):
            root = root[:-len(suffix)]
            break
    parsed = urlsplit(root)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise AiError("Enter an HTTP server URL, such as http://127.0.0.1:1234.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise AiError("Use a server URL without credentials, query, or fragment.")
    return root


def discover_models(endpoint: str) -> list[dict]:
    """Fetch native capability metadata, falling back to standard model IDs.

    Call on a worker thread. Unknown capabilities remain conservative: a
    standard /v1/models response alone does not establish image support.
    """
    root = server_root(endpoint)
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5)) as client:
            response = client.get(root + "/api/v1/models")
            native = response.status_code not in (404, 405, 501)
            if not native:
                response = client.get(root + "/v1/models")
            if response.status_code >= 400:
                raise AiError(_friendly_http_error(response.status_code, response.text))
            data = response.json()
            entries = data.get("models" if native else "data")
            if not isinstance(entries, list):
                raise AiError("The server returned an invalid model list.")
            models = []
            for entry in entries:
                model_id = entry.get("key" if native else "id", "")
                kind = str(entry.get("type", "")).lower()
                if (not model_id or kind in ("embedding", "embeddings")
                        or (not native and "embed" in model_id.lower())):
                    continue
                capabilities = entry.get("capabilities") or {}
                models.append({"id": model_id,
                               "label": entry.get("display_name") or model_id,
                               "vision": capabilities.get("vision") is True,
                               "tool_use": capabilities.get("trained_for_tool_use"),
                               "capabilities_known": native})
            return models
    except httpx.RequestError as exc:
        raise AiError(f"Could not reach LM Studio: {exc}. Start its local server and check the URL.") from exc
    except (ValueError, AttributeError) as exc:
        raise AiError("The server returned an invalid model list.") from exc


class LocalClient:
    def __init__(self, endpoint: str, model: str, *, vision: bool = False):
        self.endpoint = server_root(endpoint)
        self.model = model
        self.vision = vision
        self._client = httpx.Client(timeout=httpx.Timeout(120, connect=10))

    def close(self):
        self._client.close()

    def _messages(self, system: str, messages: list[dict]) -> list[dict]:
        converted = [{"role": "system", "content": system}]
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, str):
                converted.append(dict(message))
                continue
            if message["role"] == "assistant":
                text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
                item = {"role": "assistant", "content": text or None}
                calls = [{"id": b["id"], "type": "function", "function": {
                    "name": b["name"], "arguments": json.dumps(b.get("input") or {})}}
                    for b in content if b.get("type") == "tool_use"]
                if calls:
                    item["tool_calls"] = calls
                converted.append(item)
                continue
            images = []
            text_parts = []
            for block in content:
                if block.get("type") != "tool_result":
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    continue
                result = block.get("content", "")
                if isinstance(result, list):
                    notes = []
                    for part in result:
                        if part.get("type") == "image" and self.vision:
                            source = part["source"]
                            images.append({"type": "image_url", "image_url": {
                                "url": f"data:{source['media_type']};base64,{source['data']}"}})
                            notes.append("Viewport image follows in a user message.")
                        elif part.get("type") == "text":
                            notes.append(part.get("text", ""))
                        elif part.get("type") == "image":
                            notes.append("This model does not support vision.")
                    result = "\n".join(notes)
                converted.append({"role": "tool", "tool_call_id": block["tool_use_id"],
                                  "content": str(result)})
            # All tool replies precede the image-bearing user message, including
            # replies to multiple calls issued in the same assistant message.
            if images:
                converted.append({"role": "user", "content": [
                    {"type": "text", "text": "Viewport screenshot from the preceding tool result."}, *images]})
            if text_parts:
                converted.append({"role": "user", "content": "\n".join(text_parts)})
        return converted

    def stream_message(self, system, messages, tools, max_tokens=4096,
                       on_text=None, should_stop=None):
        payload = {"model": self.model, "messages": self._messages(system, messages),
                   "tools": [{"type": "function", "function": {
                       "name": t["name"], "description": t.get("description", ""),
                       "parameters": t["input_schema"]}} for t in tools],
                   "max_tokens": max_tokens, "stream": True,
                   "stream_options": {"include_usage": True}}
        try:
            with self._client.stream("POST", self.endpoint + "/v1/chat/completions",
                                     json=payload) as response:
                if response.status_code >= 400:
                    raise AiError(_friendly_http_error(response.status_code,
                                                       response.read().decode(errors="replace")))
                return self._consume(response, on_text, should_stop)
        except httpx.RequestError as exc:
            raise AiError(f"LM Studio request failed: {exc}. Check that its local server and model are running.") from exc

    def _consume(self, response, on_text, should_stop):
        text, calls, usage, finish = "", {}, {}, None
        for line in response.iter_lines():
            if should_stop and should_stop():
                return {"content": [], "stop_reason": "aborted", "usage": usage}
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            if not raw:
                continue
            try:
                data = json.loads(raw)
                if data.get("error"):
                    raise AiError(f"LM Studio: {data['error']}")
                tokens = data.get("usage") or {}
                if tokens:
                    usage = {"input_tokens": tokens.get("prompt_tokens", 0),
                             "output_tokens": tokens.get("completion_tokens", 0)}
                for choice in data.get("choices", []):
                    if choice.get("index", 0) != 0:
                        continue
                    delta = choice.get("delta") or {}
                    fragment = delta.get("content") or ""
                    text += fragment
                    if fragment and on_text:
                        on_text(fragment)
                    for part in delta.get("tool_calls") or []:
                        call = calls.setdefault(part["index"], {"id": "", "name": "", "arguments": ""})
                        if part.get("id"):
                            call["id"] += part["id"]
                        function = part.get("function") or {}
                        call["name"] += function.get("name") or ""
                        call["arguments"] += function.get("arguments") or ""
                    finish = choice.get("finish_reason") or finish
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise AiError("LM Studio returned a malformed response stream.") from exc
        if should_stop and should_stop():
            return {"content": [], "stop_reason": "aborted", "usage": usage}
        if not finish:
            raise AiError("LM Studio's response ended early. Please retry.")
        blocks = [{"type": "text", "text": text}] if text else []
        if calls and finish != "tool_calls":
            raise AiError("The model's tool arguments were incomplete. Please retry.")
        seen_ids = set()
        for index in sorted(calls):
            call = calls[index]
            try:
                arguments = json.loads(call["arguments"])
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                if not call["id"] or call["id"] in seen_ids or not call["name"]:
                    raise ValueError("missing or duplicated tool call identity")
            except (ValueError, TypeError) as exc:
                raise AiError(f"The model produced invalid tool arguments: {exc}") from exc
            seen_ids.add(call["id"])
            blocks.append({"type": "tool_use", "id": call["id"],
                           "name": call["name"], "input": arguments})
        if not blocks:
            if finish == "length":
                raise AiError("The model reached its output limit before returning an answer. "
                              "Try a shorter request or disable reasoning in LM Studio.")
            raise AiError("The model returned an empty response. Please retry.")
        return {"content": blocks, "stop_reason": "tool_use" if calls else finish,
                "usage": usage}
