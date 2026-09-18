# itx Unified Design System: Antigravity × Apple × ChatGPT × Observability

본 문서는 **Google Antigravity의 유려한 물리/글래스모피즘**, **Apple의 절제된 타이포그래피와 이징(Easing)**, **ChatGPT의 고효율 마이크로 인터랙션**, 그리고 **Cilium Hubble / OpenTelemetry의 분산 관제 흐름**을 융합한 itx 데스크톱 콘솔의 종합 디자인 가이드입니다.

---

## 1. 디자인 철학 및 핵심 원칙 (Core Principles)

1. **"색은 판정에만 쓴다 (Color for Verdicts Only)"**:
   - 기본 캔버스, 카드, 텍스트는 중립적인 흑백/슬레이트 톤과 절제된 브랜드 네이비(`--accent`)만 사용.
   - 초록(`pass`), 빨강(`fail`), 주황(`warn`), 회색(`na`)은 시스템의 암호학적 판정에만 엄격히 제한.
2. **Apple-grade Surface & Depth (표면과 깊이감)**:
   - 플랫한 1px 단일 보더를 지양하고, **내부 보더 하이라이트(`inset 0 1px 0 rgba(...)`)**와 **은은한 블러 글래스모피즘(`backdrop-filter: blur(16px)`)**을 결합하여 프리미엄 질감 형성.
3. **Google Antigravity Fluidity (물리 기반 동역학)**:
   - 기계적 선형 이동 대신 Apple 표준 이징(`cubic-bezier(0.16, 1, 0.3, 1)`)과 부드러운 감속을 적용.
   - 홉 지도(Hop Map) 이동 시 혜성 잔상(Comet trail)과 노드 수신 반응(Receptive pulse) 구현.
4. **ChatGPT High-Utility Ergonomics (사용성 및 조작 편의)**:
   - 드래그 가능한 시간선 스크러버(Timeline Scrubber).
   - 해시 및 토큰 1클릭 복사 & 툴팁 피드백.
   - 키보드 단축키(`Space`, `←/→`, `R`) 지원.

---

## 2. 디자인 토큰 사양 (Design Tokens)

### 2.1 컬러 팔레트 & 글래스모피즘
```css
:root {
  /* Canvas & Card (Apple Light Style) */
  --bg: #F5F7FA;
  --card: rgba(255, 255, 255, 0.85);
  --card-solid: #FFFFFF;
  --chip: #EEF2F6;
  --fg: #111827;
  --muted: #64748B;
  --line: rgba(203, 213, 225, 0.6);
  --line-strong: #CBD5E1;
  
  /* Brand & Lighting */
  --accent: #1E3A8A;
  --accent-soft: rgba(30, 58, 138, 0.08);
  --accent-glow: rgba(30, 58, 138, 0.18);
  
  /* Semantic Verdicts (Pass / Fail / Warn / NA) */
  --pass: #059669;
  --pass-soft: rgba(5, 150, 105, 0.10);
  --fail: #DC2626;
  --fail-soft: rgba(220, 38, 38, 0.08);
  --warn: #D97706;
  --warn-soft: rgba(217, 119, 6, 0.10);
  --na: #94A3B8;
  
  /* Shadows & Apple Elevation */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.04), inset 0 1px 0 rgba(255, 255, 255, 0.8);
  --shadow-md: 0 4px 16px -2px rgba(0, 0, 0, 0.06), inset 0 1px 0 rgba(255, 255, 255, 0.9);
  --shadow-lg: 0 12px 32px -4px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 1);
  --ease-apple: cubic-bezier(0.16, 1, 0.3, 1);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]), :root[data-theme="dark"] {
    --bg: #0B0E14;
    --card: rgba(18, 24, 38, 0.75);
    --card-solid: #121826;
    --chip: #1A2234;
    --fg: #F1F5F9;
    --muted: #94A3B8;
    --line: rgba(51, 65, 85, 0.5);
    --line-strong: #334155;
    
    --accent: #60A5FA;
    --accent-soft: rgba(96, 165, 250, 0.12);
    --accent-glow: rgba(96, 165, 250, 0.25);
    
    --pass: #34D399;
    --pass-soft: rgba(52, 211, 153, 0.15);
    --fail: #F87171;
    --fail-soft: rgba(248, 113, 113, 0.15);
    --warn: #FBBF24;
    --warn-soft: rgba(251, 191, 36, 0.15);
    --na: #64748B;
    
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.05);
    --shadow-md: 0 4px 20px -2px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.08);
    --shadow-lg: 0 16px 40px -4px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.1);
  }
}
```

---

## 3. 핵심 컴포넌트별 리파인먼트 사양

### 3.1 홉 지도 (Cilium Hubble × Antigravity)
* **Comet Tail (SVG Gradient Trail)**:
  - 단일 `<circle>` 대신 패킷 이동 경로 뒤로 20px 길이의 투명도 그라데이션 선을 오버레이.
  - 패킷 앞단: 중심 반경 6px, 외곽 부드러운 Glow(`filter: drop-shadow(0 0 6px var(--accent))`).
* **노드 수신 반응 (Node Receptive Halo)**:
  - 패킷이 노드(U, R, M, T)에 들어서는 순간 노드 외곽선에 300ms 동안 `box-shadow: 0 0 0 4px var(--accent-soft)` 펄스 효과 발생.
* **증거선(T 제출 경로)**:
  - `stroke-dasharray: 4 6`와 `@keyframes dashflow { to { stroke-dashoffset: -20px; } }`를 결합하여 살아 움직이는 비동기 파이프라인 느낌 제공.

### 3.2 타임라인 스크러버 (OpenTelemetry × ChatGPT)
* **대화형 드래그 스크러빙**:
  - `.timebox` 위에서 마우스 드래그 시 즉시 `playback.seek(t)` 동기화.
  - 커서: `ew-resize`. 드래그 중인 현재 `t` 값과 홉 상태를 툴팁으로 표시.
* **스텝 컨트롤러 UI**:
  - `[|◀ 처음] [◀ 이전 홉] [▶ 재생 / ❚❚ 일시정지] [다음 홉 ▶] [0.5x / 1x / 2x]`

### 3.3 검증 및 증거 패널 (Apple × Sigstore)
* **체크리스트 안착 애니메이션**:
  - 증거 등록 시 `transform: translateY(2px) -> translateY(0)`, `opacity: 0.7 -> 1.0`의 부드러운 스프링 트랜지션.
* **양방향 호버 하이라이트**:
  - 지도 상의 등식(E10 등)에 호버하면 하단 표의 해당 행이 은은한 `--accent-soft`로 점등되고, 표 행에 호버하면 지도 선이 강조됨.
* **1클릭 복사**:
  - 축약 해시(`short(h)`) 클릭 시 클립보드 복사 + "복사됨" 미니 뱃지 표시.

---

## 4. 파일별 적용 지침
1. **`itx/ui/tokens.css`**: 글래스모피즘 토큰, 섀도우, 이징 커브를 한 곳에 둔다. 데스크톱 앱(`desktop/src/styles/app.css` 의 @import)과
   HTML 보고서(`itx/report/html.py` 의 인라인)가 **같은 파일**을 읽으므로, 한쪽만 고쳐 두 콘솔이 갈라지는 일이 없다.
   노드 펄스 키프레임을 비롯한 콘솔 컴포넌트는 `itx/ui/console.css` 에 있다.
2. **`desktop/src/shared/console.ts`**: `Playback` 클래스에 스크러버 마우스 이벤트, 스텝 이동, 패킷 꼬리(Trail) 로직 추가.
3. **`desktop/src/features/simulation/view.ts`**: 스텝 버튼 및 호버 인터랙션 연동.

## 근거 종류 표기 규칙 (2026-09-16)

화면에 나오는 모든 판정·수치는 네 가지 근거 중 하나이고, 그 종류를 값 옆에 적는다. 색은 여전히 판정에만 쓴다.

| 종류 | 뜻 | 예 | 표기 |
|---|---|---|---|
| U 실측·계산 (`measured_locally`) | U 가 직접 잰 시각, 직접 계산·비교한 해시·서명·nonce | 전송·수신·공개 시각, `response_binding`, `receipt_signature` | 그대로 |
| 서명된 자기보고 (`signed_self_report`) | 서명은 U 가 검증했지만 내용은 서명자의 주장 | `route_allowed`(M 의 model_id·R 의 폴백 선언), `model_hash_reference` | 근거 종류를 반드시 적는다. "해시 일치" 는 실행 증명이 아니다 |
| 추정 (`estimate`) | 실측 사이를 시뮬레이션 상수 비율로 나눈 값 | 홉 지도 재생 구간, 'M 서명' 시점 | `· 추정` 을 붙인다. "실제 지연 비율" 같은 표현 금지 |
| 평가 불가 (`not_evaluable`) | 증거가 없어 평가하지 않음 | R 진술 결손, 기준 해시 미등록 | 회색·점선. 위반이 아니다 |

T 의 대조 등식(E1~E12)은 다섯 번째 축 `reconciled` 로, 로컬 검사와 **같은 자리에 놓이더라도 같은 주장이 아니다**.
홉 지도의 검사 모드는 등식 번호 대신 `L-` 코드를 보인다 (`receipt_signature` 는 E4 자리에 있지만 승인 변환을 재계산한
것이 아니라 서명을 확인한 것이다). 근거 종류의 진실은 `itx/enforce/user_gate.py` 의 `CHECK_BASIS` 이고, 화면은 검사가
가진 `basis` 필드를 읽는다. `tests/test_report_assets.py` 가 검사·코드·이름표가 갈라지는 순간 실패한다.

## Console v3 반영 (2026-09-16)

편의성·가시성 기준으로 재구성한 `Console v3.dc.html` 을 데스크톱 앱에 적용했다. 기능은 하나도 빼지 않았다 — 목업의
단순 SVG 홉 지도 대신 기존 그래프 캔버스(줌·팬·미니맵·상태 머신)를 「경로 상세」 접이식 섹션 안에 그대로 둔다.

- **팔레트 — 대비 보강판.** `itx/ui/tokens.css` 밝은 테마의 판정 색을 한 단계 어둡게 잡았다 (`--pass #047857` ·
  `--fail #B91C1C` · `--warn #B45309`), 본문 `--body #334155`, 회색 `--muted #475569` · `--na #64748B`.
  흰 배경 기준 4.5:1 이상. 보고서(`itx/report`)도 같은 토큰을 읽으므로 함께 바뀐다.
- **셸.** 밝은 사이드바, 목적별 4그룹(사용 · 검증·감사 · 운영 · 실험), 항목 옆 힌트(건수). 선택은 채움이 아니라
  accent-soft 배경과 왼쪽 선. 앱바는 흰 면.
- **요청 화면 4단.** 요청 입력(집행 정책은 라디오 카드) → 결과 요약 → 응답 본문 → 경로 상세(접이식).
  결과 요약은 **검증 결과**(색을 쓰는 유일한 축)와 **응답 공개 여부**(중립)를 두 줄로 나눈다. 관찰 전용에서
  검증 실패 응답이 공개된 사건은 그래서 「검증 실패」 + 「공개됨 — 검증 실패 상태로」 두 줄로 읽힌다.
- **사건 기록.** 요청 ID 검색, 기간·집행 정책·검증 결과 필터. 검증 결과 열과 응답 공개 열은 실제 기록에서 계산한다.
- **제3자 검증.** 요약 카드 4장(트리 헤드 서명 · 앵커 일치 · 전수 검사 · 목격자 독립성) + 기존 다이어그램·JSON.
  JSON 에 「불일치 항목만 보기」 — 불일치·결손 경로의 조상·자손만 남긴다.
- **배포 설정.** 5단계 위저드. 단, 목업의 선형 게이트("실행해야 다음으로")는 넣지 않았다 — 운영자마다 다른 PC 에서
  다른 단계를 수행하므로 탭은 자유롭게 오가고, 완료 표시는 이 PC 에서 실행한 단계만 기록한다.
- **참조 시나리오.** 분류 필터 + 17장 카드 내비게이터. 「이 사건 재생」은 기존 사건 상세로 이동한다. 카드의 기대
  결과는 상수가 아니라 protect 실행의 T 최종 판정이다.
- **표준 적합성 · 키 신뢰 기준점.** 같은 팔레트와 머리 패턴을 적용했다.
- 모든 화면에 ⓘ 설명 토글. 기본은 접힘.

검증: `scripts/check-ui.cjs` 가 9개 화면 × 2해상도를 찍고 가로 넘침·콘솔 오류를 검사한다.
