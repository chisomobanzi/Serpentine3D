"""OpenAI API-key transport using the shared Chat Completions adapter."""

import re

import httpx

from .client import AiError, AuthError, _friendly_http_error
from .local_client import LocalClient

DEFAULT_MODEL = "gpt-5.4"
MODELS = [("gpt-5.4", "gpt-5.4"), ("gpt-4.1", "gpt-4.1")]


class OpenAIClient(LocalClient):
    provider_label = "OpenAI"
    token_limit_parameter = "max_completion_tokens"

    def __init__(self, api_key, model=DEFAULT_MODEL):
        # Cloud credentials can only be sent to OpenAI's fixed HTTPS endpoint.
        super().__init__("https://api.openai.com", model, vision=True)
        self.api_key = api_key

    def _headers(self):
        return {"Authorization": "Bearer " + self.api_key}

    def _http_error(self, status, body):
        if status == 401:
            return AuthError("OpenAI rejected the API key. Check it in connection options "
                             "or Settings → Assistant (or OPENAI_API_KEY).")
        if status == 403:
            return AiError("OpenAI denied access. Check your API key permissions and model access.")
        return AiError("OpenAI: " + _friendly_http_error(status, body))

    def _request_error(self, exc):
        if isinstance(exc, httpx.TimeoutException):
            return AiError("The OpenAI request timed out. Please retry.")
        return AiError("Could not connect to OpenAI. Check your network connection and retry.")

    def stream_message(self, *args, **kwargs):
        try:
            return super().stream_message(*args, **kwargs)
        except AiError as exc:
            # Provider error bodies may echo credentials, including another key.
            message = str(exc).replace(self.api_key, "[redacted]")
            message = re.sub(r"sk-[A-Za-z0-9_-]+", "[redacted]", message)
            if "openai" not in message.lower():
                message = "OpenAI: " + message
            raise type(exc)(message) from None
