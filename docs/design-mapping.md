# 기획 문서 → 구현 대응표

기준: `추론투명성서비스_설계문서_v2.md`(v2), `05_추론투명성서비스_v2_설계검토와_개선방향_2026-09-10.md`(검토),
`04_종합노트_타당성검토와_개선전략_2026-09-09.md`(종합검토).

## 검토서 §3 — 외부 검증자도 방어에 참여한다

| 검토 항목 | 구현 |
|---|---|
| §3.1 U 전송 직전 집행 | 요청 계약 서명 (`User.request`), 허용 모델·변환·폴백·만료 고정 |
| §3.1 M 실행 직전 집행 | `ModelOperator._pre_exec_check` — T 에서 계약 조회 후 커밋 비교, 실패 시 거부 (S17) |
| §3.1 U 응답 수용 직전 집행 | `UserGate.local_checks` + `decide` (S03·S05·S06·S08 격리) |
| §3.1 이후 요청 제외·대체 경로 | **미구현** (strict 의 `reject_timeout` 에 "대체 경로 미구현" 명시) |
| §3.2 탐지·차단·피해 억제 분리 측정 | `itx/metrics.py`: detection / defense_before_use / harm_exposed / false_block / consumed_before_decision |

## 검토서 §4 — 구현 전 고쳐야 하는 논리

| 항목 | 구현 |
|---|---|
| §4.1 E2~E7 통과해도 응답 변조 가능 | **E10** 종단 응답 결합 신설. `test_response_modified_with_honest_hashes_is_caught_by_E10`, S03 |
| §4.2 변환 식별자는 증명이 아님 | `reconcile/transforms.py`: identity 와 공개 결정적 변환만 재계산. 비공개 변환은 `not_evaluable`. 변환 정의 해시를 판정에 기록 |
| §4.3 D-REQ-MOD 조건 불명확 | contradiction(E2·E3) 과 violation(E4) 을 다른 코드로 분리 |
| §4.4 폴백 선언 ≠ 승인 | 계약의 `allowed_models`·`fallback_policy`; E8 은 실제 경로가 승인 집합에 속하는지 검사; E9 는 실제 모델의 기준 해시와 비교 (S04·S05·S06) |
| §4.5 불일치 위치 ≠ 가해자 | `attribution_basis` 에 TM1 가정 명시. contradiction 은 'R 또는 M' |
| §4.6 비솔트 해시의 공개 | 모든 진술 값은 솔트 커밋. 솔트는 로그에 없음. U 비공개 증거는 T 에게만 (`PrivateEvidence`) |
| §4.7 매니페스트의 한계 | `completeness.py` 는 "합의된 증거 집합 제출" 로 한정. `refused` 선언은 `not_observable` 이지 미실행 확인 아님 |
| §4.8 재전송·시간 | `attempt_id` 분리(E11), nonce(E5), `D-LATE` 는 관측 상태 |
| §4.9 스트리밍 | **미구현** (limits 9) |
| §4.10 보증 수준과 검증 결과 분리 | 판정 필드 `verification_status` / `established_assurance` / `deployment_mode` 분리. 통과 시에만 `air-local` |
| §4.11 통계 검증은 보조 | 미구현, 범위 밖 명시 |
| §4.12 U 응답 수신 진술 | `observation` 진술 신설 (+ `presented_receipt`) |
| §4.12 statement_refs 는 해시·버전 고정 | `evidence_refs` (진술 해시·로그 인덱스), `policy_hash`, `checker_version`, `trust_keys_version` |
| §4.12 정책 진술 형식 | `CT_POLICY` 진술이 로그 0번. `trusted_keys`(kid→iss·공개키)와 `issuer_content_types`(iss→낼 수 있는 진술 유형) 포함 |
| §4.12 감사용 순차 열거 | `TransparencyLog.export` (전체 재생 자료), `consistency_proof` |

## 검토서 §5 — 제3자의 신용

| 신뢰 질문 | 구현 |
|---|---|
| 누가 진술을 냈는가 | kid→iss 결합, 등록 정책의 서명 검증 |
| 그 발행자가 그 진술을 낼 수 있는가 | `issuer_content_types` 를 등록(`check_policy`)과 대조(`ReconciliationEngine.gather`) 양쪽에서 강제. 키 소유만 보면 중개자가 자기 키로 모델 영수증·판정을 서명할 수 있다 |
| 판정이 증거·정책에서 도출되는가 | 결정적 엔진, `replay_audit` 독립 재실행 (S13) |
| 과거 기록을 몰래 바꾸는가 | RFC 9162 일관성 증명 + 외부 앵커 (S14) |
| 일부 사건을 숨겼는가 | 매니페스트, D-GAP, 큐 드롭 기록 (S09·S12) |
| T 가 원문을 남용하는가 | T 는 평문을 받지 않음. 커밋과 비공개 해시만 |
| T 가 악성 정책으로 업무를 멈추는가 | T 는 차단 권한 없음. U 정책이 우선 (S13 에서 T 오판 무시) |

## 검토서 §6 — 블록체인

| 시점 | 구현 |
|---|---|
| 전송 전 | 사용자 서명 요청 계약 |
| 처리·수신 중 | 영수증·수신 진술, 게이트 |
| 처리 후 | 서명 진술·Merkle 로그·판정 진술 |
| 주기적 외부 고정 | `CheckpointAnchor` (mock). 평가 질문: "T 가 다른 과거를 제시하면 발견되는가" → S14 |

## 검토서 §7 — 무결성 대 가용성

| 항목 | 구현 |
|---|---|
| §7.1 계층별 검증 단위 | 패킷이 아니라 승인 요청·인증 응답의 연결(커밋) |
| §7.2 관찰·보호·엄격 모드 | `UserGate` 세 모드. T 장애 시 정책별 동작 (S10·S11) |
| §7.2 용량 제한 큐·포화 | `EvidenceQueue` (S12) |
| §7.3 지표와 분모 | `metrics.aggregate` 는 분자/분모/제외 건수 동반 |

## 검토서 §8 — 화면

`itx/report/assets/` (조립은 `itx/report/html.py`): 경로(홉 지도) · 증거 · 비교(계약/선언/관측/수신) · 결론(사실·모순·부족·관측 구분) ·
집행 · 시점(시간선의 소비/결정 표시) · T 검증. 종합 위험 점수 없음, 부재는 `null` 로 렌더, 색은 판정에만.

## 검토서 §10.2 필수 실험 사건 → 시나리오

| 검토서 사건 | 시나리오 |
|---|---|
| 정상 요청·응답 | S01 |
| R 요청 변경, 해시 정직 | S02 (+ S17 M 집행) |
| R 응답 변경, 해시 정직 | S03 |
| U 승인 폴백 | S04 |
| R 일방 선언 폴백 | S05 (+ S06 미선언) |
| 정상 재시도 / 과거 응답 재사용 | S07 / S08 |
| 중개 증거 누락 / 거부 선언만 | S09 / S07 1차 |
| T 정지 / 로그 지연 / 큐 포화 | S10 / S11 / S12 |
| T 가 잘못된 판정 | S13 |
| R·M 공모 | S15 |
| (추가) 서명·경로 통과, 도구 정책 거부 | S16 |
| (추가) T 기록 재작성 | S14 |

## 종합검토(04) 에서 계승한 원칙

- P0-5 수집 순서 ≠ 인과: 등록 시각을 상한으로만 표기, `issued_at`(자기 주장) 과 분리.
- P0-9 로컬 해시 체인의 한계: 앵커·감사 재실행으로 보완, "조작 불가" 표현 금지.
- 주장 규율: `mock_result` / `planned` / `hypothesis` 표기 (README, limits).
