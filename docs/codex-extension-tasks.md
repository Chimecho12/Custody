# itx 차세대 기능 확장 태스크 명세서 (Codex 구현용)

본 문서는 OpenAI Codex (`gpt-6-astra xhigh`)가 본 프로젝트에 즉시 투입되어 구현할 수 있도록 작성된 모듈별 상세 요구사항 및 설계서입니다.

---

## Task 1. OpenAI 호환 로컬 프록시 게이트웨이 (`itx-proxy`)
> **목적**: 기존 AI 애플리케이션(OpenAI Python SDK, LangChain, LlamaIndex 등)이 코드 변경 없이 `base_url="http://localhost:8080/v1"` 설정만으로 itx의 무결성 검증을 거치도록 지원.

### 1.1 대상 파일
* **신규 생성**: `itx/runtime/proxy.py`
* **수정**: `runtime.py` (서브커맨드 `proxy` 추가)
* **테스트**: `tests/test_proxy.py`

### 1.2 요구사항
1. **서버 사양**:
   - Python 표준 라이브러리 `http.server.ThreadingHTTPServer` 기반 구현 (추가 의존성 없음).
   - 기본 바인드: `127.0.0.1:8080`.
2. **지원 엔드포인트**:
   - `POST /v1/chat/completions` (OpenAI 표준 요청 형식 수신).
   - `GET /health` (상태 확인 및 연결된 U-Agent 상태 반환).
3. **처리 흐름**:
   - 클라이언트로부터 OpenAI 형식의 JSON(`{"model": "...", "messages": [{"role": "user", "content": "..."}]}`) 수신.
   - 마지막 user 메시지를 추출하여 itx의 `UserGate` 및 U-Agent 파이프라인 호출.
   - U 계약 서명 -> R 중개 요청 -> M 추론 -> 로컬 검증(`receipt_present`, `response_binding` 등) 수행.
   - **검증 성공 시 (`action == "accept"`)**:
     OpenAI 호환 응답 반환:
     ```json
     {
       "id": "chatcmpl-itx-<sub_id>",
       "object": "chat.completion",
       "created": 1726000000,
       "model": "<actual_model_id>",
       "choices": [{
         "index": 0,
         "message": {"role": "assistant", "content": "<verified_text>"},
         "finish_reason": "stop"
       }],
       "itx": {
         "verified": true,
         "mode": "protect",
         "sub": "<sub_id>",
         "checks": {"request_binding": "pass", "response_binding": "pass"}
       }
     }
     ```
   - **검증 실패/격리 시 (`action in ("quarantine", "reject", "reject_timeout")`)**:
     HTTP 403 Forbidden 반환:
     ```json
     {
       "error": {
         "message": "itx integrity verification failed: response quarantined",
         "type": "itx_integrity_violation",
         "code": "response_binding_failed",
         "sub": "<sub_id>"
       }
     }
     ```
4. **CLI 진입점 (`runtime.py`)**:
   - `python runtime.py proxy --data-dir <dir> --config <config_path> [--port 8080] [--mode protect]`

---

## Task 2. SSE 스트리밍 청크 체인 검증기 (`StreamingGate`)
> **목적**: `docs/limits.md` Limit 9 ("스트리밍 응답의 청크 단위 검증 미구현") 해소. 실시간 SSE 스트림에서 토큰 단위 무결성을 검증하고 중간 변조 즉시 차단(Early Abort).

### 2.1 대상 파일
* **신규 생성**: `itx/enforce/streaming_gate.py`
* **테스트**: `tests/test_streaming_gate.py`

### 2.2 요구사항
1. **청크 해시 체인 알고리즘**:
   - 초기 체인 해시: $h_0 = \text{SHA256}(\text{request\_hash} \parallel \text{nonce})$
   - 각 청크 $i$ 수신 시:
     $$h_i = \text{SHA256}(h_{i-1} \parallel \text{uint32\_be}(i) \parallel \text{chunk\_bytes})$$
2. **검증 메커니즘**:
   - 각 청크에 동봉된 시퀀스 번호의 연속성($i = i-1 + 1$) 검증.
   - 마지막 청크(`[DONE]`)에 포함된 최종 체인 다이제스트 $h_{\text{final}}$와 모델(M)의 서명된 영수증 내 `streaming_root_digest` 대조.
   - 중간에 비순차 청크, 누락 청크, 또는 기대 해시 불일치가 발생할 경우 즉시 예외(`StreamTamperedError`)를 발생시키고 스트림을 강제 종료하여 애플리케이션으로의 오염 전파를 선제 차단.
3. **제공 인터페이스**:
   ```python
   class StreamingGate:
       def __init__(self, expected_root_hash: str, request_hash: str, nonce: str): ...
       def feed_chunk(self, index: int, chunk_bytes: bytes) -> bool: ...
       def finalize(self, expected_final_hash: str) -> bool: ...
   ```

---

## Task 3. RFC 3161 공인 타임스탬프(TSA) 외부 앵커 (`anchor_tsa.py`)
> **목적**: `docs/limits.md` Limit 6 ("체크포인트 앵커는 파일 기반 모사다") 해소. 투명성 로그(T)의 Merkle Tree Head를 실제 공개 타임스탬프 권한(TSA)에 고정하여 과거 로그 재작성 방지.

### 3.1 대상 파일
* **신규 생성**: `itx/audit/anchor_tsa.py`
* **수정**: `itx/audit/anchor.py`
* **테스트**: `tests/test_anchor_tsa.py`

### 3.2 요구사항
1. **타임스탬프 요청 생성 및 전송**:
   - Merkle Log의 `root_hash`를 SHA-256 메시지 다이제스트로 하는 RFC 3161 `TimeStampReq` ASN.1 바이너리 생성 (Python `cryptography` 또는 표준 바이트 패킹 활용).
   - 공개 TSA 서버(기본값: `https://freetsa.org/tsr` 또는 `http://timestamp.digicert.com`)에 `Content-Type: application/timestamp-query`로 POST 요청.
2. **응답 검증 및 저장**:
   - 수신된 `TimeStampResp`의 PKIStatus가 'granted'(0)인지 확인하고 `.tsr` 토큰 저장.
   - 토큰 내의 SignedData에서 타임스탬프 시각(genTime)과 해시 값을 추출하여 체크포인트 메타데이터에 기록.
3. **독립 감사자 연동**:
   - `replay_audit` 수행 시 로컬 파일 외에 `.tsr` 토큰을 검증하여, T가 주장하는 체크포인트가 해당 시각 이전에 실제로 존재했음을 수학적으로 입증.
