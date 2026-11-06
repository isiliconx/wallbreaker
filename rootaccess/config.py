"""Campaign configuration; resolve environment references without exposing values."""
from __future__ import annotations

import os
from pathlib import Path
import re

import yaml

from .assets import resolve_asset
from .providers import IpeenkProv, OpenAICompat

_ENV = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_environment(value):
    if isinstance(value, str):
        def replace(match):
            key = match.group(1)
            if not os.environ.get(key):
                raise ValueError(f"Missing environment variable: {key}")
            return os.environ[key]
        return _ENV.sub(replace, value)
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    return value


def load_campaign(filename: str) -> tuple[dict, Path]:
    path = resolve_asset(filename)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        raise ValueError("Campaign YAML must contain an object")
    cfg = expand_environment(cfg)
    for role in ("target", "brain", "judge"):
        if role in cfg and not isinstance(cfg[role], dict):
            raise ValueError(f"Campaign {role} must contain an object")
    return cfg, path.parent


def provider_for(role: str, block: dict | None = None):
    block = block or {}
    role = role.upper()
    def setting(key, suffix, default=""):
        return block.get(key, os.environ.get(f"WB_{role}_{suffix}",
                                             os.environ.get(f"WB_TARGET_{suffix}", default)))
    url = setting("base_url", "URL")
    model = setting("model", "MODEL")
    key = setting("api_key", "KEY")
    if "ipeenk" in url:
        return IpeenkProv(model, api_key=key)
    return OpenAICompat(url, key, model, timeout=float(block.get("timeout", 120)),
                        backend=setting("backend", "BACKEND", "chat"),
                        ua=setting("ua", "UA", "rootaccess/1.0"),
                        protocol=setting("protocol", "PROTOCOL", "openai"),
                        auth_style=setting("auth_style", "AUTH_STYLE", "x-api-key"))
