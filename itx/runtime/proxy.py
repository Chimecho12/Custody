"""OpenAI 호환 로컬 프록시: 기존 앱이 base_url 만 바꿔 itx 검증 경로를 거치게 한다.

이 프록시는 새로운 보증을 만들지 않는다. `/v1/chat/completions` 로 들어온 요청을
U Agent 의 요청 계약 → R 중개 → M 추론 → 로컬 검증 경로에 그대로 태우고,
게이트가 공개한 응답만 200 으로 돌려준다. 격리·거부된 응답의 본문은 어떤 필드로도
나가지 않는다 — 403 과 실패한 검사 이름만 나간다.

경계 (docs/limits.md 와 같은 규율):
- 스트리밍(`"stream": true`)은 거부한다. 청크 단위 검증기는 있으나 이 전송 경로에
  연결되지 않았다 (Limit 9). 되는 척하고 버퍼링해 한 번에 흘리지 않는다.
- 클라이언트가 보낸 `model` 은 경로 선택에 쓰지 않는다. 실제 모델은 배포 합의에 고정돼
  있으므로 응답의 `model` 에는 실제 모델 id 를 적고, 클라이언트가 요청한 값은
  `itx.requested_model` 에 그대로 두며 다르면 `itx.model_substituted` 로 알린다.
- `usage` 는 만들지 않는다. 세지 않은 토큰 수를 지어내지 않는다.
- 루프백에만 바인드한다. 같은 데이터 디렉터리를 쓰는 앱·SDK 와 동시에 실행할 수 없다
  (OS 저장소 잠금). 로컬 프로세스면 누구나 서명된 요청을 만들 수 있으므로
  `--api-key` 로 공유 비밀을 걸 수 있다.
- U Agent 는 한 번에 한 요청만 처리한다. 프록시는 요청을 줄 세우고, 대기가 길어지면
  503 을 돌려준다. 동시 처리량을 늘리지 않는다.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
from pathlib import Path

MAX_BODY = 1 << 20          # 1 MiB. 요청 상한은 Agent 가 다시 검사한다.
BUSY_TIMEOUT_S = 30.0       # 앞 요청이 끝나기를 기다리는 한계
RELEASED = ("accept", "accept_unverified")
BLOCKED = ("quarantine", "reject", "reject_timeout")
MODES = ("observe", "protect", "strict")
BLOCK_MESSAGE = {
    "quarantine": "itx integrity verification failed: response quarantined",
    "reject": "itx integrity verification failed: response rejected",
    "reject_timeout": "itx integrity verification failed: T verdict deadline exceeded",
}


class ProxyError(Exception):
    """HTTP 상태와 OpenAI 호환 오류 본문을 함께 나르는 예외."""

    def __init__(self, status: int, message: str, kind: str, code: str, **extra):
        super().__init__(message)
        self.status, self.message, self.kind, self.code, self.extra = status, message, kind, code, extra

    def payload(self) -> dict:
        return {"error": {"message": self.message, "type": self.kind, "code": self.code, **self.extra}}


# ---------- 요청 해석 ----------
def extract_prompt(body: dict) -> str:
    """OpenAI 요청에서 마지막 user 메시지를 꺼낸다. 형식이 어긋나면 400 으로 끝낸다."""
    if not isinstance(body, dict):
        raise ProxyError(400, "request body must be a JSON object", "invalid_request_error", "invalid_body")
    if body.get("stream"):
        raise ProxyError(400, "itx proxy does not support streaming: chunk-level verification is not wired "
                              "into this transport (docs/limits.md Limit 9)",
                         "invalid_request_error", "streaming_unsupported")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ProxyError(400, "messages must be a non-empty array", "invalid_request_error", "invalid_messages")
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            # 비전 형식의 부분 목록. 텍스트 조각만 쓰고 나머지는 거절한다 — 조용히 버리지 않는다.
            parts = [p.get("text") for p in content if isinstance(p, dict) and p.get("type") == "text"]
            if len(parts) != len(content) or not all(isinstance(p, str) for p in parts):
                raise ProxyError(400, "only text content parts are supported", "invalid_request_error",
                                 "unsupported_content")
            text = "".join(parts)
        else:
            raise ProxyError(400, "message content must be a string or text parts", "invalid_request_error",
                             "invalid_content")
        if not text.strip():
            raise ProxyError(400, "the last user message is empty", "invalid_request_error", "empty_prompt")
        return text
    raise ProxyError(400, "no user message found", "invalid_request_error", "no_user_message")


def resolve_mode(default: str, header: str | None) -> str:
    if header is None or header == "":
        return default
    if header not in MODES:
        raise ProxyError(400, f"unknown enforcement mode: {header}", "invalid_request_error", "invalid_mode")
    return header


# ---------- 응답 구성 ----------
def _check_results(record: dict) -> dict:
    return {name: value.get("result") for name, value in (record.get("checks") or {}).items()}


def _short_sub(record: dict) -> str:
    return str(record.get("sub", "")).rsplit(":", 1)[-1]


def completion_payload(record: dict, requested_model: str | None, actual_model: str | None) -> dict:
    """게이트가 공개한 응답만 담는다. 검증 여부는 꾸미지 않고 집행 결과 그대로 적는다."""
    return {
        "id": "chatcmpl-itx-" + _short_sub(record),
        "object": "chat.completion",
        "created": int(record.get("started_at", 0)) // 1000,
        "model": actual_model or record.get("model_kind"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": record.get("response") or ""},
                     "finish_reason": "stop"}],
        "itx": {
            # observe 의 accept_unverified 는 '검증됨' 이 아니다. 둘을 같은 칸에 섞지 않는다.
            "verified": record.get("state") == "accept",
            "action": record.get("state"),
            "mode": record.get("mode"),
            "sub": record.get("sub"),
            "elapsed_ms": record.get("elapsed_ms"),
            "checks": _check_results(record),
            "t_verdict": (record.get("t_verdict") or {}).get("payload", {}).get("verification_status"),
            "requested_model": requested_model,
            "model_substituted": bool(requested_model and actual_model and requested_model != actual_model),
        },
    }


def rejection_payload(record: dict) -> dict:
    """차단된 요청의 오류 본문. 격리한 응답 원문은 어떤 필드에도 넣지 않는다."""
    state = record.get("state", "reject")
    failed = [name for name, value in (record.get("checks") or {}).items() if value.get("result") == "fail"]
    return {"error": {
        "message": BLOCK_MESSAGE.get(state, "itx integrity verification failed"),
        "type": "itx_integrity_violation",
        "code": (failed[0] + "_failed") if failed else state,
        "sub": record.get("sub"),
        "action": state,
        "failed_checks": failed,
    }}


def response_for(record: dict, requested_model: str | None, actual_model: str | None) -> tuple[int, dict]:
    state = record.get("state")
    if state in RELEASED:
        if not isinstance(record.get("response"), str):
            # 공개 결정인데 본문이 없으면 통과시키지 않는다.
            raise ProxyError(502, "itx released a decision without a response body", "itx_upstream_error",
                             "missing_response", sub=record.get("sub"))
        return 200, completion_payload(record, requested_model, actual_model)
    if state in BLOCKED:
        return 403, rejection_payload(record)
    if state in ("cancelled", "interrupted"):
        return 409, {"error": {"message": "itx did not release this response: " + state,
                               "type": "itx_request_interrupted", "code": state, "sub": record.get("sub")}}
    return 502, {"error": {"message": record.get("error") or "itx request failed before a decision",
                           "type": "itx_upstream_error", "code": "agent_error", "sub": record.get("sub")}}


# ---------- U Agent 연결 ----------
class Gateway:
    """Desktop 실행기를 그대로 쓴다. 프록시는 전송 형식만 바꾸고 집행은 바꾸지 않는다."""

    def __init__(self, data_directory, config=None, *, mode="protect", api_key=None, lab=False):
        if mode not in MODES:
            raise ValueError("unknown enforcement mode: " + str(mode))
        if not config and not lab:
            raise ValueError("고정한 U 설정(--config)을 주거나 --lab 으로 실험실을 명시하세요.")
        from .desktop import Desktop
        self.mode, self.api_key = mode, api_key
        self.turn = threading.Lock()
        self.desktop = Desktop(data_directory, lambda event: None)  # 진행 이벤트는 HTTP 로 내보내지 않는다
        if config:
            self.desktop.execute("connect", {"path": str(Path(config).resolve(strict=True))})
        else:
            self.desktop.execute("status", {})

    def status(self) -> dict:
        from .common import now_ms
        s = self.desktop.execute("status", {})
        expired = now_ms() >= s["policy_expires_at"]
        return {"status": "degraded" if expired else "ok",
                "mode": self.mode, "streaming_supported": False,
                "itx": {"source": s["source"], "model_id": s["model_id"], "model_kind": s["model_kind"],
                        "governance": s["governance"], "policy_expires_at": s["policy_expires_at"],
                        "policy_expired": expired, "pending_evidence": s["pending_evidence"],
                        "epoch": s.get("epoch"), "deployment_hash": s.get("deployment_hash")}}

    def model_id(self) -> str | None:
        try:
            return self.desktop.execute("status", {})["model_id"]
        except Exception:
            return None

    def complete(self, prompt: str, mode: str) -> dict:
        # Agent 는 한 번에 한 요청만 받는다. 동시 요청은 줄 세우고, 오래 기다리면 거절한다.
        if not self.turn.acquire(timeout=BUSY_TIMEOUT_S):
            raise ProxyError(503, "itx agent is busy with another request", "itx_unavailable", "agent_busy")
        try:
            return self.desktop.execute("request", {"token": secrets.token_hex(12), "prompt": prompt, "mode": mode})
        except ValueError as exc:
            raise ProxyError(400, str(exc), "invalid_request_error", "agent_rejected_request") from None
        except RuntimeError as exc:
            raise ProxyError(503, str(exc), "itx_unavailable", "agent_unavailable") from None
        finally:
            self.turn.release()

    def close(self):
        self.desktop.cancel_all()
        self.desktop.close()


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "itx-proxy"
    protocol_version = "HTTP/1.1"
    timeout = 65

    @property
    def gateway(self) -> Gateway:
        return self.server.gateway  # type: ignore[attr-defined]

    def log_message(self, fmt, *args):  # 요청 본문·프롬프트를 로그로 흘리지 않는다
        pass

    def _send(self, status: int, payload: dict, *, close=False):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        if close:
            self.send_header("Connection", "close")
            self.close_connection = True
        self.end_headers()
        self.wfile.write(raw)

    def _guard(self):
        """루프백 밖의 연결과 공유 비밀 불일치를 먼저 끊는다."""
        try:
            if not ip_address(self.client_address[0]).is_loopback:
                raise ValueError
        except ValueError:
            raise ProxyError(403, "itx proxy accepts loopback connections only", "invalid_request_error",
                             "not_loopback") from None
        expected = self.gateway.api_key
        if not expected:
            return
        header = self.headers.get("Authorization", "")
        presented = header[7:] if header.startswith("Bearer ") else ""
        if not hmac.compare_digest(presented, expected):
            raise ProxyError(401, "invalid api key", "invalid_request_error", "invalid_api_key")

    def _read_body(self) -> dict:
        if self.headers.get("Transfer-Encoding"):
            raise ProxyError(411, "chunked request bodies are not supported", "invalid_request_error",
                             "length_required")
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            raise ProxyError(411, "Content-Length is required", "invalid_request_error", "length_required") from None
        if length < 0 or length > MAX_BODY:
            raise ProxyError(413, "request body is too large", "invalid_request_error", "body_too_large")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise ProxyError(400, "incomplete request body", "invalid_request_error", "incomplete_body")
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ProxyError(400, "request body must be valid UTF-8 JSON", "invalid_request_error",
                             "invalid_json") from None

    def do_GET(self):
        try:
            self._guard()
            if self.path.split("?")[0] != "/health":
                raise ProxyError(404, "unknown endpoint", "invalid_request_error", "not_found")
            body = self.gateway.status()
        except ProxyError as exc:
            self._send(exc.status, exc.payload(), close=True)
        except Exception as exc:
            self._send(503, {"status": "unavailable", "error": {"message": str(exc), "type": "itx_unavailable",
                                                                "code": "agent_unavailable"}}, close=True)
        else:
            self._send(200 if body["status"] == "ok" else 503, body)

    def do_POST(self):
        try:
            self._guard()
            if self.path.split("?")[0] != "/v1/chat/completions":
                raise ProxyError(404, "unknown endpoint", "invalid_request_error", "not_found")
            body = self._read_body()
            prompt = extract_prompt(body)
            mode = resolve_mode(self.gateway.mode, self.headers.get("X-Itx-Mode"))
            requested_model = body.get("model") if isinstance(body.get("model"), str) else None
            record = self.gateway.complete(prompt, mode)
            status, payload = response_for(record, requested_model, self.gateway.model_id())
        except ProxyError as exc:
            self._send(exc.status, exc.payload(), close=True)
        except Exception as exc:  # 예기치 못한 실패도 본문을 흘리지 않고 끝낸다
            self._send(500, {"error": {"message": type(exc).__name__, "type": "itx_internal_error",
                                       "code": "internal_error"}}, close=True)
        else:
            self._send(status, payload)


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False  # 같은 포트를 조용히 가로채지 않는다

    def __init__(self, address, gateway: Gateway):
        self.gateway = gateway
        super().__init__(address, Handler)


def build_server(gateway: Gateway, host="127.0.0.1", port=8080) -> ProxyServer:
    if not ip_address(host).is_loopback:
        raise ValueError("itx proxy binds to loopback addresses only")
    return ProxyServer((host, port), gateway)


def serve(data_directory, config=None, *, host="127.0.0.1", port=8080, mode="protect",
          api_key=None, lab=False) -> None:
    from .common import ProcessLock
    directory = Path(data_directory)
    directory.mkdir(parents=True, exist_ok=True)
    with ProcessLock(directory / "app.lock"):
        gateway = Gateway(directory, config, mode=mode, api_key=api_key, lab=lab)
        server = build_server(gateway, host, port)
        bound = server.server_address
        print(f"itx proxy: http://{bound[0]}:{bound[1]}/v1  (mode={mode}, "
              f"auth={'on' if api_key else 'off'}, streaming=unsupported)", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
            gateway.close()
