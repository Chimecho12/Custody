"""Model-provider calls, separate from signed receipts and role RPC handling."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from .common import MAX_RESPONSE, MAX_WIRE
from .transport import NoRedirect


def model_reply(config, body):
    """Return complete text using only the operator's pinned model configuration."""
    if config["model_kind"] == "deterministic_mock":
        return {"text": "모형 모델의 응답: " + body["prompt"]}
    if config["model_kind"] != "ollama":
        raise ValueError("unsupported model adapter")
    return ollama_reply(config, body["prompt"])


def validate_model_endpoint(endpoint):
    """Validate an operator-configured origin before opening any connection."""
    # Endpoint is operator configuration, never taken from a prompt or RPC payload.
    url = urlsplit(endpoint)
    if (not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/")
            or (url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")))):
        raise ValueError("model endpoint must use HTTPS or explicit loopback")
    return endpoint.rstrip("/")


def ollama_reply(config, prompt):
    endpoint = validate_model_endpoint(config["model_endpoint"])
    data = json.dumps({"model": config["model_name"], "prompt": prompt, "stream": False}).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(urllib.request.Request(endpoint + "/api/generate", data=data,
                                               headers={"Content-Type": "application/json"}), timeout=18) as response:
            raw = response.read(MAX_WIRE + 1)
    except urllib.error.HTTPError as exc:
        exc.close()
        raise ValueError("model endpoint returned HTTP " + str(exc.code)) from None
    if len(raw) > MAX_WIRE:
        raise ValueError("model response too large")
    return parse_ollama_response(raw, config["model_name"])


def parse_ollama_response(raw, model_name):
    # Provider metadata may contain finite floats, unlike signed ITX JSON.
    def unique_object(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate model response key")
            obj[key] = value
        return obj
    def invalid_constant(value):
        raise ValueError("non-finite model response number")
    result = json.loads(raw, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    if not isinstance(result, dict) or result.get("model") != model_name:
        raise ValueError("model response name differs from the configured canonical name")
    text = result.get("response")
    if not isinstance(text, str) or len(text) > MAX_RESPONSE or result.get("done") is not True:
        raise ValueError("model did not return a complete text response")
    return {"text": text}
