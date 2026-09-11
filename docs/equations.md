# 등식·불일치 코드·판정 규칙

설계 문서 v2 §4.7 의 E1~E9 를 05 검토서 §4 에 따라 고친 판본. 구현: `itx/reconcile/equations.py`.

## 표기

- `commit(x) = H(salt || H(canonical(x)))`. 솔트는 U 가 요청마다 생성, R·M 에 대역 내 전달, T 에 비공개 전달. 로그에 올리지 않음 (§4.6).
- 모든 등식은 `pass / fail / not_evaluable`. `not_evaluable` 은 사유 필수.
- 신뢰 등급: `externally_corroborable`(두 당사자 진술 비교) · `self_asserted`(한 당사자 주장) · `third_party_salted`(솔트 보유자만 재계산).

## 등식

| ID | 구간 | 검사 | 필요 증거 | 비고 |
|---|---|---|---|---|
| E1 | U | `contract.req_commit == commit(salt, request_hash)` | 계약 + U 비공개 증거 | T·권한 감사자만 |
| E2 | U→R | `R.in_commit == U.req_commit` | 계약 + 중계 | 불일치는 모순(어느 쪽이 거짓인지 미확정) |
| E3 | R→M | `R.out_commit == M.request_commit` | 중계 + 영수증 | 진술 간 일치만. **변조 여부가 아님** |
| E4 | R | M 이 받은 요청 커밋 ∈ {승인 변환의 재계산 결과} | 계약 + (영수증 또는 중계) | 선언 식별자가 아니라 재계산 결과와 비교. 재계산 불가 변환은 `not_evaluable` |
| E5 | R | `M.eat_nonce == U.nonce`, `R.nonce_forwarded == U.nonce` | 계약 + (영수증/중계) | 재전송·nonce 제거 |
| E6 | M→R | `M.response_commit == R.resp_in_commit` | 영수증 + 중계 | 진술 간 일치만 |
| E7 | R→U | `R.resp_out_commit == U.resp_commit` | 중계 + 수신 | 진술 간 일치만 |
| E8 | R | 실제 모델(M.model_id 우선) ∈ 계약 허용 집합. 요청 모델과 다르면 폴백 정책·선언 검사 | 계약 + (영수증/중계) | 선언된 비승인 / 미선언 / 승인 폴백을 구분 |
| E9 | M | `M.model_hash == reference(M.model_id)` | 영수증 + 기준 해시 | **실제 사용 모델**의 기준값과 비교 (§4.4). 아티팩트 ≠ 실행 |
| **E10** | M⇢U | `M.response_commit == U.resp_commit` (응답 무변환 정책) | 영수증 + 수신 | **§4.1 반례를 잡는 종단 등식** |
| E11 | 전체 | 모든 진술의 `attempt_id` 일치 | 2개 이상 진술 | 재전송·다른 시도 |
| E12 | U | `received_at <= contract.expires_at` | 계약 + 수신 | 만료 |

### 반례 (05 검토서 §4.1) 와 E10

M 이 A 를 생성, R 이 B 로 바꾸고 `resp_in = commit(A)`, `resp_out = commit(B)` 를 정직하게 적음. U 는 B 수신.

```
E6: commit(A) == commit(A)  → pass
E7: commit(B) == commit(B)  → pass
E10: commit(A) == commit(B) → FAIL  → D-RESP-UNAPPROVED, 귀속 R (TM1)
```

`tests/test_reconcile.py::test_response_modified_with_honest_hashes_is_caught_by_E10`, 시나리오 S03.

## 불일치 코드

| 코드 | 성격 | 등식 | 귀속 |
|---|---|---|---|
| D-USER-SELF | contradiction | E1 | U 증거 묶음 |
| D-REQ-CONTRADICT | contradiction | E2, E3 | 구간의 두 당사자 (미확정) |
| D-REQ-UNAPPROVED | **violation** | E4 | R (TM1) |
| D-NONCE | violation | E5 | R |
| D-RESP-CONTRADICT | contradiction | E6, E7 | 구간의 두 당사자 (미확정) |
| D-RESP-UNAPPROVED | **violation** | E10 | R (TM1). R+M 공모 시 보이지 않음 |
| D-ROUTE-UNAPPROVED | violation | E8 | R |
| D-ROUTE-UNDECLARED | violation | E8 | R |
| D-MODEL-ART | violation | E9 | M 또는 R |
| D-ATTEMPT-MISMATCH | violation | E11 | R (재전송 후보) |
| D-EXPIRED | violation | E12 | R(지연) 또는 정책 |
| D-SIG-INVALID | contradiction | — | 해당 발행자 |
| D-ISSUER-UNAUTHORIZED | violation | — | 해당 발행자 |
| D-RECEIPT-PRESENTED-DIFFERS | contradiction | — | R |
| D-GAP | observation | — | 귀속 없음 |
| D-LATE | observation | — | 귀속 없음 |

## 판정 상태

```
failed                 : violation 또는 contradiction 이 하나라도 있음, 또는 어떤 등식이 fail
passed                 : fail 없음 AND {E1, E4, E5, E8, E9, E10, E11, E12} 모두 pass
insufficient_evidence  : 그 외 (증거 부족)
```

- E4 와 E10 은 각각 요청·응답 쪽의 종단 결합이다. 계약이 재계산 불가한 변환을 허용하면 그쪽
  등식은 `not_evaluable` 이 되고 판정은 `passed` 가 아니라 `insufficient_evidence` 가 된다.
- `completeness` 는 별도 축: `complete / gap / not_observable`. `gap` 은 위반이 아니다.
- `established_assurance`: `passed` 이고 영수증이 있을 때만 `air-local`. 그 외 `none`. TEE 값은 타입에 없다.
- 판정에는 `policy_hash`, `checker_version`, `trust_keys_version`, `transform_definitions`(승인 변환 정의의 해시), `evidence_refs`(진술 해시·로그 인덱스), `threat_model` 을 고정한다.

## 사용자 게이트의 로컬 검사 (T 없이)

`not_expired`, `receipt_present`, `receipt_signature`, `nonce_match`, `request_binding`, `response_binding`,
`attempt_match`, `model_hash_reference`, `route_allowed`, `tool_policy`.

- protect: 모두 pass → accept. fail → quarantine. 핵심 검사(`receipt_present`, `request_binding`,
  `response_binding`, `nonce_match`)가 `not_evaluable` → quarantine. 요청·응답 결합 중 하나라도
  확인할 수 없으면 수용하지 않는다.
- strict: protect 조건 + T 판정 `passed`. 기한 내 판정 없으면 `reject_timeout`. **로컬 실패는 T 판정보다 우선.**
- observe: 항상 `accept_unverified`, 수신 즉시 소비 (피해 노출 측정용 기준선).
- 응답 자체가 없으면(중개자 거부·M 거부) `no_response`. 수용도 격리도 아니므로 오차단 분모에서 제외한다.
