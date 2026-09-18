# 프로젝트 구조와 의존 관계

## Python

`itx/`는 설치 가능한 Python 패키지다. `run.py`와 `runtime.py`는 `itx/cli/`를 호출하는 기존 진입점이다.
암호·진술·투명성 로그·대조·집행 모듈은 기존 도메인 단위를 유지한다.
시뮬레이션(`sim/`)과 실제 TLS 실행(`runtime/`)은 같은 검증 도메인을 사용하되 서로 다른 실행 환경을 가진다.

`itx/sim/parties/`의 책임은 다음과 같다.

| 파일 | 책임 |
|---|---|
| `messages.py` | 전송 메시지와 솔트 커밋 계산 |
| `evidence.py` | 용량 제한 증거 큐와 재제출 |
| `third_party.py` | T 등록 정책·대조·판정·체크포인트 |
| `model_operator.py` | M 실행 전 검사·모형 실행·영수증 |
| `relay.py` | R 중계·변환·공격 조건 |
| `user.py` | U 계약·관찰 진술·게이트·요청 결과 |

`__init__.py`는 공개 클래스를 다시 내보낸다. 따라서 기존 `from itx.sim.parties import User`는 유효하다.
역할 사이의 호출과 모의 시계는 유지하며, 공통 메시지가 특정 역할 구현에 의존하지 않도록 한다.

`itx/runtime/desktop/`는 전송 경계와 업무 작업을 구분한다.

실제 서비스 경계도 세 층으로 나눈다. `itx/runtime/models.py`는 운영자가 고정한 모델
엔드포인트와 Ollama 응답 형식만 다루고, `itx/runtime/service.py`는 계약·영수증·대조와
역할별 업무만 다룬다. `itx/runtime/rpc_server.py`는 TLS 소켓·JSON 프레이밍·동시성
상한만 담당한다. 이 분리 덕분에 로컬 Ollama를 쓰는 M과 다른 컴퓨터의 M/R/T를 같은
검증 경로로 연결하면서, 클라우드 제공자 어댑터를 추가해도 서명·정책 코드가 바뀌지 않는다.

| 파일 | 책임 |
|---|---|
| `ipc.py` | JSON 행 프레이밍·작업 큐·응답·종료 |
| `controller.py` | 연결 수명·요청 취소·작업 직렬화·Agent 호출 |
| `operations.py` | Python 허용 명령 목록 |
| `provisioning.py` | Agent 연결 없이 가능한 등록·배포·오프라인 감사 |
| `standards.py` | 표준 화면 데이터·COSE 파일·검증 안내 내보내기 |

공개 `Desktop`, `stdio`, 허용 명령 상수의 import 경로는 `itx.runtime.desktop`로 유지한다.
IPC는 표준 출력에 프로토콜 메시지만 기록한다. 실행 중인 요청의 상태 조회와 취소는 허용하고,
연결 변경과 다른 작업은 기존 잠금으로 직렬화한다.

## 데스크톱

`desktop/src/main.ts`는 CSS를 로드하고 `app/bootstrap.ts`를 실행한다.

| 디렉토리 | 책임 | 의존 규칙 |
|---|---|---|
| `app/` | 화면 조립·탐색·앱 셸 | 기능을 생성하고 기능 사이의 콜백 연결 |
| `features/<기능>/` | 해당 화면의 상태·이벤트·렌더링 | 공통 UI와 서비스 사용, `app/` 역참조 금지 |
| `services/` | Tauri 호출·진행 이벤트·기능 목록·미리보기 데이터 | DOM과 화면 컨트롤러에 의존하지 않음 |
| `shared/` | 데이터 타입·DOM 도우미·작업 바인더·시각 컴포넌트 | 특정 기능이나 앱 전역 상태에 의존하지 않음 |
| `styles/` | 앱 전용 스타일 | `itx/ui/`의 토큰과 공통 컴포넌트 가져오기 |

기능별 `controller.ts`는 이벤트와 로컬 상태를 소유하고 `view.ts`는 화면 표현을 담당한다.
요청 화면의 홉 지도는 이 규칙을 더 분명히 하기 위해 `request/route.ts`와
`request/controls.ts`로 분리했다. `route.ts`는 재생·렌더링만, `controls.ts`는 R 실험
조건과 T 중단·복구 메뉴의 유효성만 담당한다. 지도에서 고른 값은 컨트롤러의 동일한
선택 경로를 거치므로 그림과 실제 실행 조건이 어긋나지 않는다.
기존 `ReportView`, `StandardsView`, `KeysView`는 자체 수명과 이벤트를 가진 화면 객체로 유지한다.
기록에서 요청 조사로 이동하는 동작은 `app/`이 콜백으로 연결한다. 요청 중 여부도 공통 작업
바인더에 함수로 전달하므로 다른 기능이 요청 화면의 변수를 직접 수정하지 않는다.
Tauri 호출과 브라우저 미리보기 분기는 `services/agent.ts`에서 처리한다.

## 공유 자산과 배포

공통 CSS는 `itx/ui/` 한 곳에 두고 데스크톱은 CSS import, 보고서는 `importlib.resources`로 읽는다.
보고서 생성은 저장소 루트나 현재 작업 디렉토리에 의존하지 않는다.
`pyproject.toml`은 `itx`와 그 하위 패키지를 자동 검색하고 공통 CSS 및 보고서 자산을 wheel에 포함한다.
기존 수동 패키지 목록에서 빠져 있던 `itx.cose`와 `itx.keys`도 포함된다.
`scripts/build-desktop.ps1`은 PyInstaller에 `--collect-data itx`를 전달한다.

HTML 보고서의 JavaScript는 독립 파일에서 바로 열 수 있는 기존 방식으로 유지한다.
데스크톱과 보고서가 공유하는 지연·등식 표는 `tests/test_report_assets.py`로 대조한다.

## 이전 경로

| 이전 | 현재 |
|---|---|
| `itx/sim/parties.py` | `itx/sim/parties/` |
| `itx/runtime/desktop.py` | `itx/runtime/desktop/` |
| `ui/*.css` | `itx/ui/*.css` |
| `desktop/src/style.css` | `desktop/src/styles/app.css` |
| `desktop/src/console.ts`, `flow.ts`, `trace.ts` | `desktop/src/shared/` |
| `desktop/src/preview.ts` | `desktop/src/services/preview.ts` |
| `desktop/src/runtime-view.ts` | `desktop/src/features/request/view.ts` |
| `desktop/src/report.ts` | `desktop/src/features/simulation/view.ts` |
| `desktop/src/*-view.ts`의 나머지 화면 | `desktop/src/features/<기능>/view.ts` |

## 검증

전체 Python 테스트는 runtime 및 conformance 의존성이 설치된 환경에서 실행한다.
실제 TLS·Windows DPAPI 검사는 해당 운영체제의 프로세스 실행·키 보호 권한이 필요하다.

```powershell
python -m pip install -e '.[runtime,conformance]'
python run.py test
ruff check .
node --test scripts/test-console.cjs
cd desktop
pnpm build
cd ..
node scripts/check-ui.cjs
python -m pip wheel . --no-deps -w .build/wheels
python scripts/check-package.py .build/wheels/itx-0.1.0-py3-none-any.whl
```

UI 검사는 Playwright와 미리보기 표본 데이터가 필요하다. 화면 9개를 두 너비에서 확인하고,
요청·기록 검색·사건 조사·배포 단계 이동을 실행한다. 이 검사는 native IPC 검사를 대신하지 않는다.
wheel 검사는 격리한 Python 프로세스와 저장소 밖의 작업 디렉토리에서 실행하며,
wheel 자체에서 모듈과 CSS·HTML·JavaScript 자산을 읽을 수 있는지 확인한다.
명령을 추가할 때는 Rust `OPS`와 `operations.py`를 함께 갱신한다. IPC 테스트는 하위 기능
디렉토리와 공통 작업 바인더의 명령까지 읽어 세 계층의 목록을 대조한다.
