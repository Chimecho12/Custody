# itx — 독립 제3자 기반 AI 서비스 경로 검증·정책 집행 플랫폼 (참조 구현)

사용자(U) ↔ 중개자(R, 클라우드 대행) ↔ 모델 운영자(M) 경로에서 일어나는 공격을
**시각화·통제·방어**하는 플랫폼의 첫 버전이다. 세 당사자가 각자 서명한 진술을 독립
제3자(T)가 추가 전용 로그에 등록·대조하고, 그 판정과 사용자 자신의 검증으로 사용자 측
집행 모듈이 변조된 응답을 업무에 쓰기 **전에** 거부한다. T 의 판정 자체도 서명·등록되며
독립 감사자가 재실행해 T 를 검증한다.

기획 문서 `추론투명성서비스_설계문서_v2.md` 와 그 검토서 `05_…_설계검토와_개선방향_2026-09-10.md`
의 권장 MVP(§10.1)를 그대로 구현 대상으로 삼았다. 어떤 검토 항목이 어디에 반영됐는지는
[docs/design-mapping.md](docs/design-mapping.md) 에 있다.

> 기존 `run.py`·HTML 보고서는 모의 시계의 `mock_result`다. 새 `runtime.py`·Tauri 앱은
> 별도 R/M/T 프로세스 사이에서 **실제 TLS 통신**을 수행하고 시간을 실측한다. 기본 모델은
> 결정적 모형이며, 한 PC의 단일 운영자 실험이다. 독립 사업자나 실제 LLM 검증 결과가 아니다.
> COSE/SCITT/AIR 표준 적합성을 주장하지 않으며 자체 JSON 프로파일을 쓴다. 한계는 [docs/limits.md](docs/limits.md).

## Windows 설치 앱 — v0.3

설치 파일: `desktop/src-tauri/target/release/bundle/nsis/itx_0.3.0_x64-setup.exe`.
설치 후 **itx**를 실행하면 동봉 Agent와 로컬 TLS 실험실이 시작된다. 사용자에게 Python·Node·Rust 설치를 요구하지 않는다.

- 앱 내부 AI 요청에서 observe/protect/strict 적용, 응답 공개 전 검증·격리
- 실제 R 요청/응답 변조·영수증 제거, T 중단·복구 실험
- Windows DPAPI 보호 저장, SQLite 로그·증거 큐, 재시작 복구
- 고정된 T 신원·정책 및 이전 체크포인트를 사용한 감사
- 사건 기록·E1~E12 근거·기존 17개 참조 시나리오 실행
- 역할별 키·TLS CA 생성, 전원 서명 배포, 이전/새 키 승인 교체와 이전 세대 폐기
- 별도 목격자 W, 모든 과거 판정 검사, 정책 이력·암호화 오프라인 감사
- 외부 앱 Python SDK, U 본문 보관 정리, 3모드 반복 TLS 평가

[v0.3 설치·검증 결과와 한계](docs/desktop-runtime-v0.3.md), [운영자 배포·키 교체·SDK·외부 감사](docs/operator-deployment.md)를 제공한다.
원격 호스트·실제 독립 운영자·실제 LLM·새 PC 설치·외부 배포 서명은 별도 환경 검증 항목이다. 실제 체인 게시 기능은 포함하지 않는다.

## 표준 적합성과 키 보관

같은 진술을 자체 JSON 프로파일과 **RFC 9052 COSE_Sign1**(alg -8 EdDSA, CWT 클레임은 RFC 9597 라벨 15,
본문은 RFC 8949 결정적 CBOR)로 나란히 낸다. 적합성은 주장이 아니라 **실행한 벡터 수**로 적는다.

서명 키는 보관처가 아니라 **평문 노출 여부**로 판단한다. `itx.keys.CommandSigner` 로 외부
서명자(KMS·HSM·스마트카드)에 위임하면 사설키가 이 프로세스에 들어오지 않는다. 다만 순수
Ed25519 는 메시지 전체에 서명하므로 「해시만 전송」은 prehash 방식에서만 참이고, 무엇을 보내는지는
화면에 그대로 표시된다.

적합성 주장이 순환하지 않도록 **제3자 구현이 같은 바이트를 읽는지** 교차 검증한다. `cbor2` 는 canonical
재인코딩이 바이트 동일한지 보고, `pycose` 는 서명을 검증하고 변조된 서명을 거부하는지 본다. 두 도구가
없으면 '미실행' 으로 남고 주장 상태가 `planned` 로 내려간다. 자세한 범위는
[docs/limits.md](docs/limits.md) 한계 13·14.

```powershell
pip install -e .[conformance]          # 교차 검증용 cbor2 · pycose (선택)
python runtime.py conformance          # 적합성 벡터 + 제3자 구현 교차 검증
python runtime.py conformance --no-external   # 우리 벡터만
python runtime.py key-inventory --config <U 설정>   # 키 보관처·평문 노출·회전 기한
python runtime.py proxy --data-dir <폴더> --lab      # OpenAI 호환 루프백 게이트웨이 (base_url 만 바꿔 붙는다, 스트리밍 거부)
python runtime.py endurance --output <json>          # T 정지·복구를 낀 연속 요청: 구간별 서비스·적체·회복 시간·사후 판정 (실측, 루프백)
```

## 기존 시뮬레이션 실행

Python 3.10 이상, 추가 패키지 없음. (`cryptography` 가 설치돼 있으면 서명에 자동으로 사용한다.)

```powershell
python run.py doctor     # 환경 점검
python run.py test       # 단위·시나리오 테스트
python run.py all        # 시나리오 18종 × 모드 3종 실행 → artifacts/results.json, report.html, 독립 감사
```

`artifacts/report.html` 을 브라우저로 연다. 서버가 필요 없다.

### 코드 점검

```powershell
python run.py test                       # 단위·시나리오·IPC·콘솔 동기화
node --test scripts/test-console.cjs     # 재생/스크러버 상호작용 (데스크톱 + 보고서 스크립트)
cd desktop; pnpm build                   # tsc --noEmit + vite build
node scripts/check-ui.cjs                # 빌드된 미리보기의 레이아웃·콘솔 오류 (playwright 필요)
ruff check .                             # 설정은 pyproject.toml
python -m pip wheel . --no-deps -w .build/wheels
python scripts/check-package.py .build/wheels/itx-0.1.0-py3-none-any.whl # 저장소 밖에서 import·보고서 자산 검사
```

## 사용자의 두 질문에 이 구현이 답하는 방식

**1. 충분한 신용을 가진 제3자가 방어를 해낼 수 있는가?**

T 는 경로 밖에 있으므로 본문을 차단하지 않는다. 대신 다음 세 겹으로 방어가 성립한다.

| 겹 | 누가 | 무엇을 | 코드 |
|---|---|---|---|
| 전송 전 | U | 허용 모델·폴백·변환·만료를 **서명한 요청 계약**으로 고정 | `itx/statements/schemas.py` contract |
| 수신 직전 | U 집행 모듈 | 동봉된 M 영수증으로 nonce·요청 결합·응답 결합·경로를 로컬 검증. 실패면 격리 | `itx/enforce/user_gate.py` |
| 실행 직전 (선택) | M | T 에서 계약을 조회해 변조 요청을 실행 전 거부 | `ModelOperator._pre_exec_check` |
| 사후 | T | 3당사자 진술 대조 → 서명·등록된 판정. 결손·모순·위반을 구분 | `itx/reconcile/` |
| T 검증 | 감사자 | 로그 내보내기·앵커·**제출자가 보관한 등록 영수증**으로 트리·판정·포함을 재검사. T 오판·기록 재작성·기록 누락 발견 | `itx/audit/replay.py`, `itx/ts/anchor.py` |

T 의 신용은 "믿게 만들기" 가 아니라 **틀리거나 침해되어도 드러나고 교체할 수 있게 만들기** 로
확보한다. 시나리오 S13(T 오판)·S14(T 기록 재작성)·S18(T 기록 누락)이 이를 시험한다. U 는 T 가 '통과' 라고
해도 로컬 검증이 실패하면 격리한다. 감사는 두 질문을 구분한다 — "T 가 보여 준 자료가 일관적인가" 는
트리·헤드·앵커가, "T 가 보여 줘야 할 자료를 다 보여 줬는가" 는 U 가 등록 때 받아 보관한 영수증의
포함 검사(RFC 9162 §11.3)가 답한다. 영수증을 버린 감사자는 뒤의 질문을 물을 수 없다.

**2. 패킷이 무결성을 유지하면서 가용성도 지킬 수 있는가?**

무결성 검증 단위는 패킷 바이트가 아니라 **사용자가 승인한 요청과 실제 서비스가 반환한 응답의
인증된 연결**이다 (중개를 거치면 연결·프레이밍이 바뀌므로). 가용성은 세 모드로 선택한다.

| 모드 | 응답 수용 | T 장애 시 | 비용 |
|---|---|---|---|
| observe | 모두 허용, 상태 표시 | 계속 | 공격이 업무에 노출됨 |
| protect | 로컬 검증 후 허용, 실패는 격리 | 로컬 증거로 계속, 증거는 큐에 남겨 재제출 | 영수증 없는 M 과는 업무 불가 |
| strict | 로컬 검증 + T 판정 후 수용 | 기한 내 판정 없으면 명시적 거부 | 등록 지연만큼 대기 |

S10(T 정지)·S11(등록 지연)·S12(큐 포화)가 각 모드의 비용을 실측(모의)한다. 가용성은 별도 축으로
센다(`availability_legit`, 압박 조건 아래의 `availability_under_pressure`): R 이 진술을 보류하는 것(S09)만으로
정상 응답이 격리되면 그것은 R 이 쥔 서비스 거부 스위치이므로, 결손은 위반이 아니라 gap 으로 두고 U+M 증거로
계속한다. 큐 포화 뒤의 동작과 R 진술 필수 여부는 명시적 정책이다 (`docs/threat-model.md` 가용성 정책).

**블록체인의 자리.** 전송 이전의 신용은 사용자 서명 계약이, 전송 이후의 기록 불변성은
Merkle 로그와 등록 영수증이 담당한다. 블록체인 후보 자리는 하나다: T 가 나중에 다른 과거를
제시하지 못하게 하는 **외부 체크포인트**(`itx/ts/anchor.py`). 첫 버전은 파일 기반 목격자 모사이며
인터페이스만 고정했다. RFC 3161·Rekor·테스트넷으로 교체할 수 있다. 요청 단위 온체인 기록,
원문·비솔트 해시 게시는 하지 않는다.

## 시나리오 (S01~S18)

| ID | 사건 | 기대 결과 |
|---|---|---|
| S01 | 정상, 셋 협조 | passed · complete · accept |
| S02 | R 요청 변경(해시 정직) | E3 pass, **E4 fail** → D-REQ-UNAPPROVED · U 격리 |
| S03 | R 응답 변경(해시 정직) | E6·E7 pass, **E10 fail** → D-RESP-UNAPPROVED · 사용 전 격리 |
| S04 | U 승인 폴백 | passed (원 모델 해시와 다르다는 이유로 차단하지 않음) |
| S05 | R 일방 폴백 | D-ROUTE-UNAPPROVED |
| S06 | 숨은 폴백 | D-ROUTE-UNDECLARED |
| S07 | 정상 재시도 | 1차 not_observable, 2차 passed |
| S08 | 과거 응답 재사용 | D-NONCE, D-ATTEMPT-MISMATCH · 격리 |
| S09 | R 비협조 | passed 이지만 completeness=gap. 가해자 단정 없음. protect 는 서비스 계속 (가용성 축) |
| S10 | T 정지 | protect 계속, strict 거부. 복구 후 사후 판정 |
| S11 | T 지연 | strict 만 대기 비용 |
| S12 | 큐 포화 | 증거 유실 → gap |
| S13 | T 오판 | U 로컬 격리 + 독립 감사가 불일치 발견 |
| S14 | T 기록 재작성 | 앵커·일관성 증명 불일치로 발견 |
| S15 | R+M 공모 | **탐지 불가** 로 정직하게 표시 (TM1 밖) |
| S16 | 프롬프트 인젠션 | 무결성 passed, 도구 실행 정책이 격리 (무결성 ≠ 안전성) |
| S17 | M 실행 전 검사 | 변조 요청이 실행 전 거부 |
| S18 | T 기록 누락 (앵커 이전) | 트리·헤드·앵커·재실행 전부 일관. **U·R·M 이 각자 보관한 영수증의 포함 검사만** 누락을 발견 |

Q1 매트릭스: S02·S03·S05·S06·S08 을 협조 집합 {U, U+M, U+R, U+R+M} 에서 실행해
어떤 증거가 있을 때 무엇이 확립되는지 보인다.

**T 기여 실험 (`run_t_contribution`, 보고서 §4b):** 같은 18 사건을 (a) T 없이 U 로컬 검증만, (b) U+T
protect, (c) U+T strict 로 돌려 나란히 놓는다. 결과(모의)는 정직하다 — **사용 전 차단은 18/18 에서 T 유무와
무관**하다. 차단은 U 의 로컬 검증이 하기 때문이다. T 가 더하는 것은 M 의 실행 전 거부(S17: T 없이는 변조
요청이 실행된 뒤에야 격리된다), 서명·등록된 탐지 기록(6건), 감사 발견(S13·S14·S18)이고, strict 는 차단을
더하지 못한 채 T 정지·큐 포화에서 가용성만 잃는다. "제3자가 필요하다" 는 주장은 이 표의 오른쪽 열에만
근거를 둔다.

**인센티브 원장 (`itx/sim/incentives.py`, 보고서 §4c):** "모든 노드가 손해보지 않는 구조" 를 검증 가능한 두 질문으로
바꿨다. (1) 부당한 책임 없음 — 판정·감사가 지목한 당사자가 실제 가해자인가. 54 실행에서 0건이고, 단위 파라미터와
무관하다. R 의 공격은 R 에게, T 의 오판·재작성·누락은 독립 감사가 T 에게 돌리며, 정직한 M 은 R 이 지목될 때
면책된다. 공모(S15)는 미해결로 남는다. (2) 정직 참여의 편익 > 비용 — 가설 단위로만 계산하며, R·M·T 의 수수료·평판이
모형에 없어 순편익이 음수다. 채워지지 않은 자리를 숫자로 보인다.

## 디렉터리

```
Pproject/
├── run.py  runtime.py         진입점 (얇은 껍데기 — 실제 구현은 itx/cli/)
├── itx/
│   ├── cli/                   simulation (doctor/test/run/report/audit/all) · runtime (사이드카·배포·감사 CLI)
│   ├── crypto/                sha256·솔트 커밋, JCS 부분집합 정규화, Ed25519(순수 Python 또는 cryptography)
│   ├── statements/            진술 봉투(iss·sub·content_type·kid 서명)와 7종 페이로드 스키마
│   ├── ts/                    RFC 9162 Merkle 트리·포함/일관성 증명, 추가 전용 로그·등록 정책·영수증, 앵커, 장애 주입
│   ├── reconcile/             등식 E1~E12, 불일치 D-코드, 완전성, 승인 변환, 대조 엔진
│   ├── enforce/               사용자 게이트 (observe / protect / strict)
│   ├── cose/                  결정적 CBOR(RFC 8949) · COSE_Sign1(RFC 9052) · 적합성 벡터
│   ├── keys/                  서명 키 보관처·평문 노출·회전·계보, 외부 서명자 어댑터
│   ├── sim/                   시뮬레이션 시계·모형 모델·시나리오·실행기
│   │   └── parties/           U/R/M/T 역할별 구현, 전송 메시지, 증거 큐
│   ├── runtime/               실제 TLS 통신 서비스·에이전트·배포 합의·감사 패키지
│   │   └── desktop/           연결·취소 제어, IPC, 허용 명령, 등록·COSE 내보내기
│   ├── audit/                 독립 판정 재실행
│   ├── metrics.py             탐지·방어·오차단·안전 완료·피해 노출·대기
│   ├── report/
│   │   ├── html.py            패키지 자산을 읽어 독립 HTML 조립
│   │   └── assets/            report.html · report.css · report.js
│   └── ui/                    데스크톱·보고서 공통 tokens.css · console.css (wheel 포함)
├── desktop/
│   ├── src/
│   │   ├── main.ts            스타일 로드와 앱 시작
│   │   ├── app/               앱 조립·화면 전환·테마
│   │   ├── features/          request · history · connection · deployment · evidence · audit · simulation · standards · keys
│   │   ├── services/          Tauri IPC·Agent 기능 확인·브라우저 미리보기
│   │   ├── shared/            타입·DOM·작업 버튼·콘솔·경로·추적 컴포넌트
│   │   └── styles/            앱 전용 CSS
│   └── src-tauri/             Rust 실행 껍데기·권한·패키징
├── scripts/                   빌드·개발 실행·UI 점검·스모크
├── tests/                     RFC 8032 벡터, Merkle, 등록 정책, 대조 반례, 시나리오 기대치, 콘솔 동기화
├── docs/                      threat-model · equations · limits · design-mapping · 디자인 시스템
└── artifacts/                 실행 결과 (results.json, summary.json, report.html, log-export-S01.json)
```

화면은 두 곳(데스크톱 TypeScript, 보고서 `report.js`)에 있지만 **CSS 는 `itx/ui/` 하나**이고,
두 구현이 공유해야 하는 상수·표(홉 지연, 등식 이름, 검사↔등식 대응)는
`tests/test_report_assets.py` 가 값이 갈라지는 순간 실패한다.

**확장 모듈의 상태 (정확한 표현):** 스트리밍 청크 체인 검증기(`itx/enforce/streaming_gate.py`)와 RFC 3161 TSA
앵커(`itx/audit/anchor_tsa.py`)는 **모듈과 테스트는 있으나 기본 경로에 연결되어 있지 않다.** 프록시는 `stream: true`
를 거부하고, 기본 앵커는 파일 모사다. "구현했다" 가 아니라 "모듈은 있고 경로 연결은 남았다" 다 (`docs/limits.md` 9).

모듈 책임과 의존 방향, 변경 전후 경로, 검증 방법은 [docs/architecture.md](docs/architecture.md)에 있다.
기존 `python run.py`, `python runtime.py`, `itx.sim.parties`, `itx.runtime.desktop` 진입점은 유지한다.

## 주장 상태 표기

설계 문서 v2 §0.2 를 따른다. 이 저장소가 내는 수치는 모두 `mock_result` 다.
표준 인용은 문서에 `verified_external` 로 표시된 것만 근거로 삼았고, 코드는 그 구조를 옮겼을 뿐
적합성 벡터로 검증하지 않았다 (`planned`).
