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
1. **`desktop/src/style.css`**: 글래스모피즘 토큰, 섀도우, 이징 커브, 노드 펄스 키프레임 적용.
2. **`desktop/src/console.ts`**: `Playback` 클래스에 스크러버 마우스 이벤트, 스텝 이동, 패킷 꼬리(Trail) 로직 추가.
3. **`desktop/src/report.ts`**: 스텝 버튼 및 호버 인터랙션 연동.
