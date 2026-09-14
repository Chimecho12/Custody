from __future__ import annotations

import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request

from itx.crypto import canonical_json, verify
from .common import MAX_WIRE, now_ms, json_loads


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        fp.close()
        raise ValueError("redirects are not permitted")


class Peer:
    def __init__(self, config, key):
        self.config, self.key = config, key
        self.openers = {}
        for role in config["endpoints"]:
            context = ssl.create_default_context(cafile=config.get("ca_files", {}).get(role, config["ca_file"]))
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            self.openers[role] = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                                             urllib.request.HTTPSHandler(context=context))

    def call(self, target, operation, payload, timeout=3):
        endpoint = self.config["endpoints"][target]
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("an explicit HTTPS endpoint is required")
        rpc = {"actor": self.config["role"], "target": target, "operation": operation,
               "id": secrets.token_hex(16), "time": now_ms(), "payload": payload}
        rpc["signature"] = self.key.sign(canonical_json(rpc)).hex()
        req = urllib.request.Request(endpoint.rstrip("/") + "/rpc", data=canonical_json(rpc),
                                     headers={"Content-Type": "application/json"})
        try:
            with self.openers[target].open(req, timeout=max(0.05, timeout)) as response:
                raw = response.read(MAX_WIRE + 1)
            if len(raw) > MAX_WIRE:
                raise ValueError("response too large")
            result = json_loads(raw)
        except urllib.error.HTTPError as e:
            e.close()
            raise RuntimeError(f"{target}: HTTP {e.code}") from e
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "remote operation failed"))
        return result["result"]


def verify_rpc(config, rpc):
    if not isinstance(rpc, dict) or set(rpc) != {"actor", "target", "operation", "id", "time", "payload", "signature"}:
        raise ValueError("invalid RPC")
    actor = rpc["actor"]
    if actor not in config["identities"] or rpc["target"] != config["role"]:
        raise ValueError("invalid RPC identity or audience")
    if type(rpc["time"]) is not int or abs(now_ms() - rpc["time"]) > 60000:
        raise ValueError("expired RPC")
    body = {k: v for k, v in rpc.items() if k != "signature"}
    if not verify(bytes.fromhex(config["identities"][actor]["public_key"]),
                  canonical_json(body), bytes.fromhex(rpc["signature"])):
        raise ValueError("invalid RPC signature")
    allowed = {"T": {"U": {"submit", "verdict", "audit", "audit_head", "audit_page", "consistency", "health"},
                     "R": {"submit"}, "M": {"submit"}, "W": {"audit_head", "consistency"}},
               "R": {"U": {"infer", "health"}}, "M": {"R": {"infer"}, "U": {"health"}},
               "W": {"U": {"witness", "witness_status", "health"}}}
    if rpc["operation"] not in allowed[config["role"]].get(actor, set()):
        raise ValueError("RPC operation not authorized")
    return actor, rpc["operation"], rpc["payload"]
