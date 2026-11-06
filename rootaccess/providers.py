"""Providers: OpenAI-compatible + Cloudflare-gated ipeenk. Keys from env, never repo."""
from __future__ import annotations

import os
import urllib.request
import json
from urllib.parse import urlsplit


class ProviderError(RuntimeError):
    pass


class OpenAICompat:
    """OpenAI-compatible chat + Responses provider over urllib.

    backend: "chat" (default, /chat/completions) or "responses" (/responses).
    ua: User-Agent. Codex-everywhere grok lane historically 403'd without
    "codex-cli/1.0"; set it always, it is cheap even when ungated.
    """

    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120,
                 backend: str = "chat", ua: str = "codex-cli/1.0",
                 protocol: str = "openai", auth_style: str = "x-api-key"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.backend = (backend or os.environ.get("WB_TARGET_BACKEND", "chat")).lower()
        self.ua = ua or os.environ.get("WB_TARGET_UA", "codex-cli/1.0")
        self.protocol = protocol
        self.auth_style = auth_style
        self.last_stop_reason = "stop"
        self.last_completion_empty = False
        self.last_raw_status = None
        self.last_model = None

    def _headers(self):
        h = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}
        if self.ua:
            h["User-Agent"] = self.ua
        return h

    @staticmethod
    def _text_from_chat(data):
        try:
            msg = data["choices"][0]["message"]
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = "".join(item.get("text", "") for item in content
                                  if isinstance(item, dict) and item.get("type") == "text")
            if not isinstance(content, str):
                raise ValueError("Non-text response content")
            return content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("Invalid target response structure") from exc

    @staticmethod
    def _text_from_responses(data):
        if not isinstance(data, dict):
            return str(data)[:4000]
        if data.get("output_text"):
            return data["output_text"]
        chunks = []
        for item in data.get("output") or []:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for c in item.get("content") or []:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        chunks.append(c.get("text") or "")
        return "".join(chunks)

    def complete(self, messages, system=None, max_tokens=8000, temperature=0.7):
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or not self.model:
            raise ProviderError("Configure a valid target HTTP(S) URL and model")
        if self.protocol == "anthropic":
            return self._complete_anthropic(messages, system, max_tokens, temperature)
        if self.protocol not in ("openai", "xai"):
            raise ProviderError(f"Unsupported protocol: {self.protocol}")
        if self.backend in ("responses", "response"):
            return self._complete_responses(messages, system, max_tokens, temperature)
        return self._complete_chat(messages, system, max_tokens, temperature)

    def _complete_anthropic(self, messages, system, max_tokens, temperature):
        """Reuse the retained workbench's Anthropic protocol and authentication support."""
        import asyncio
        from wallbreaker.agent.messages import Message, TextBlock
        from wallbreaker.config import Endpoint
        from wallbreaker.providers.factory import build_provider

        async def request():
            endpoint = Endpoint("rootaccess", "anthropic", self.base_url, self.model,
                                api_key=self.api_key, auth_style=self.auth_style)
            provider = build_provider(endpoint, timeout=self.timeout)
            wire = [Message(m["role"], [TextBlock(m["content"])]) for m in messages]
            try:
                text = await provider.complete(wire, system=system, max_tokens=max_tokens,
                                               temperature=temperature)
                self.last_stop_reason = getattr(provider, "last_stop_reason", "stop")
                self.last_completion_empty = not bool(text.strip())
                self.last_model = self.model
                return text
            finally:
                await provider.aclose()
        return asyncio.run(request())

    def _complete_chat(self, messages, system, max_tokens, temperature):
        wire = []
        if system:
            wire.append({"role": "system", "content": system})
        for m in messages:
            if isinstance(m, dict):
                wire.append({"role": m.get("role", "user"), "content": m.get("content", "")})
            else:
                wire.append({"role": "user", "content": str(m)})
        body = json.dumps({"model": self.model, "messages": wire,
                           "max_tokens": max_tokens, "temperature": temperature,
                           "stream": False}).encode()
        url = self.base_url.rstrip("/") + "/chat/completions"
        req = urllib.request.Request(url, data=body, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.last_raw_status = r.status
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            self.last_stop_reason = "error"
            raise ProviderError(f"Target request failed: {type(e).__name__}") from e
        self.last_model = data.get("model")
        if data.get("error") or not data.get("choices"):
            raise ProviderError("Target returned an error or no choices")
        text = self._text_from_chat(data)
        self.last_completion_empty = not bool(text and str(text).strip())
        self.last_stop_reason = data["choices"][0].get("finish_reason") or "stop"
        return text

    def _complete_responses(self, messages, system, max_tokens, temperature):
        # Responses API: system lives in `instructions`. Input is the conversation.
        input_items = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
            else:
                role, content = "user", str(m)
            if role == "system" and not system:
                system = content
                continue
            input_items.append({"role": role if role in ("user", "assistant") else "user",
                                "content": content})
        body = {
            "model": self.model,
            "input": input_items if input_items else " ",
            "max_output_tokens": max_tokens,
        }
        if system:
            body["instructions"] = system
        if temperature is not None:
            body["temperature"] = temperature
        req = urllib.request.Request(self.base_url + "/responses",
                                     data=json.dumps(body).encode(), headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                self.last_raw_status = r.status
                data = json.loads(r.read().decode("utf-8", "replace"))
        except Exception as e:
            self.last_stop_reason = "error"
            raise ProviderError(f"Target request failed: {type(e).__name__}") from e
        self.last_model = data.get("model")
        if data.get("error"):
            self.last_stop_reason = "error"
            raise ProviderError("Target returned an API error")
        text = self._text_from_responses(data)
        self.last_completion_empty = not bool(text and str(text).strip())
        self.last_stop_reason = data.get("status") or "stop"
        return text


class IpeenkProv(OpenAICompat):
    """Ipeenk gateway: Cloudflare 1010 needs chrome impersonation + cf_clearance cookie."""

    def __init__(self, model: str, cf_clearance: str = "", api_key: str = "", timeout: int = 120):
        self.cf_clearance = cf_clearance or os.environ.get("IPEENK_CF_CLEARANCE", "")
        self._api_key = api_key or os.environ.get("IPEENK_API_KEY", "")
        super().__init__("https://ai.ipeenk.com/v1", self._api_key, model, timeout)

    def complete(self, messages, system=None, max_tokens=8000, temperature=0.7):
        try:
            from curl_cffi import requests as cr
        except ImportError:
            raise ProviderError("Install curl-cffi for the Ipeenk adapter")
        wire = []
        if system:
            wire.append({"role": "system", "content": system})
        for m in messages:
            wire.append({"role": m.get("role", "user"), "content": m.get("content", "")} if isinstance(m, dict)
                        else {"role": "user", "content": str(m)})
        s = cr.Session(impersonate="chrome124")
        if self.cf_clearance:
            s.cookies.set("cf_clearance", self.cf_clearance, domain="ai.ipeenk.com")
        s.headers.update({"Authorization": "Bearer " + self._api_key, "Content-Type": "application/json",
                          "Origin": "https://ai.ipeenk.com/", "Referer": "https://ai.ipeenk.com/"})
        try:
            r = s.post("https://ai.ipeenk.com/v1/chat/completions",
                       json={"model": self.model, "messages": wire, "max_tokens": max_tokens,
                             "temperature": temperature, "stream": False}, timeout=self.timeout)
        except Exception as e:
            raise ProviderError(f"Target request failed: {type(e).__name__}") from e
        if r.status_code == 403 and "1010" in r.text:
            raise ProviderError("Cloudflare rejected the configured Ipeenk session")
        if r.status_code >= 400:
            raise ProviderError(f"Target HTTP status: {r.status_code}")
        try:
            data = r.json()
            return data["choices"][0]["message"]["content"] or ""
        except Exception as e:
            raise ProviderError("Invalid target response") from e


def from_env(role: str, default_model: str = ""):
    """Build provider from env: WB_<ROLE>_URL, WB_<ROLE>_KEY, WB_<ROLE>_MODEL. IPEENK_* for ipeenk."""
    from .config import provider_for
    return provider_for(role, {"model": default_model} if default_model else {})
