const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s)=>document.querySelector(s);
const esc = (s)=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cls = (r)=>r==='pass'?'pass':r==='fail'?'fail':'na';
const st = (s)=>s==='passed'?'pass':s==='failed'?'fail':'warn';
// 해시·커밋은 앞 12자만 보이고, 누르면 전체 값을 클립보드로 복사한다.
const short = (h)=>h?`<span class="hashchip" data-copy="${esc(h)}" role="button" tabindex="0" title="클릭하면 전체 값을 복사합니다">${esc(String(h).slice(0,12))}…</span>`:'<span class="absent">없음</span>';
const absent = (v)=>(v===null||v===undefined)?'<span class="absent">null</span>':esc(v);
// 색은 CSS 토큰과 같은 값을 SVG stroke 등 속성 컨텍스트에도 그대로 써야 하므로 여기서도 고정한다
// (var(--x) 는 attribute 컨텍스트에서 계산된 값으로 안전하게 쓰인다).
const CV = (name)=>`var(--${name})`;

// ---------- 배지
(function(){
  const g = D.generated_with;
  $('#badges').innerHTML = [`itx ${g.itx_version}`,`검사기 ${g.checker_version}`,`seed ${g.seed}`,`서명 ${g.crypto_backend}`,`claim ${g.claim_status}`,`deployment evaluation`,`assurance ≤ air-local`].map(x=>`<span>${esc(x)}</span>`).join('');
})();

// ---------- 요약
(function(){
  const S = D.summary; const modes = Object.keys(S);
  const row = (label, f)=>`<tr><th>${label}</th>${modes.map(m=>`<td>${f(S[m])}</td>`).join('')}</tr>`;
  const frac = (o)=>o.den?`${o.num}/${o.den}${o.rate!=null?` <span class="muted">(${(o.rate*100).toFixed(0)}%)</span>`:''}`:'<span class="absent">분모 0</span>';
  $('#summary').innerHTML = `<table><thead><tr><th>지표</th>${modes.map(m=>`<th>${m}</th>`).join('')}</tr></thead><tbody>
  ${row('시도 수 / 공격 시도', s=>`${s.attempts} / ${s.attack_attempts}`)}
  ${row('탐지 (T 최종 판정 failed, 관측 가능한 공격 중)', s=>frac(s.detection)+` <span class="muted small">제외 ${s.detection.excluded_undetectable}</span>`)}
  ${row('사용 전 방어 (공격 응답이 업무에 소비되지 않음)', s=>frac(s.defense_before_use))}
  ${row('피해 노출 (공격 응답이 업무에 사용됨)', s=>`${s.harm_exposed.num}/${s.harm_exposed.den}`)}
  ${row('오차단 (정상인데 격리·거부)', s=>frac(s.false_block)+` <span class="muted small">무응답 제외 ${s.false_block.excluded_no_response}</span>`)}
  ${row('안전 완료 (정상 요청이 검증 후 수용)', s=>frac(s.safe_completion_legit))}
  ${row('가용성 (정상 요청이 서비스됨 · 압박 조건: R 진술 보류·T 정지·지연·큐 포화)', s=>s.availability_legit ? frac(s.availability_legit)+` <span class="muted small">압박 조건 ${frac(s.availability_under_pressure)}</span>` : '<span class="absent">이 결과 파일에는 없음</span>')}
  ${row('증거 완전 (합의 증거 모두 등록)', s=>`${s.evidence_complete.num}/${s.evidence_complete.den}`)}
  ${row('결정 대기 ms (평균 / 최대)', s=>`${s.decision_wait_ms.mean ?? '-'} / ${s.decision_wait_ms.max ?? '-'}`)}
  ${row('왕복 지연 ms (평균 / 최대)', s=>`${s.rtt_ms.mean ?? '-'} / ${s.rtt_ms.max ?? '-'}`)}
  </tbody></table>`;
})();

// ---------- 매트릭스
const byKey = {}; D.results.forEach(r=>{ byKey[r.run.scenario_id+'|'+r.run.mode]=r; });
let cur = {sid:'S01', mode:'protect', attempt:0};
(function(){
  const modes = ['observe','protect','strict'];
  const rows = D.scenarios.map(sc=>{
    const rp = byKey[sc.id+'|protect']; const last = rp.attempts[rp.attempts.length-1]; const fv = last.final_verdict;
    const codes = fv.discrepancies.map(d=>d.code);
    const gates = modes.map(m=>{const r=byKey[sc.id+'|'+m]; const a=r.attempts[r.attempts.length-1]; const atk=a.metrics.attack_present; const act=a.gate.action;
      const k = act==='no_response' ? 'na' : (act==='accept'||act==='accept_unverified') ? (atk?'fail':'pass') : (atk?'pass':'fail');
      return `<td class="${k}">${esc(act)}</td>`;}).join('');
    const audit = rp.audit; const anch = audit.anchors.every(a=>a.ok);
    return `<tr class="clickable" tabindex="0" data-sid="${sc.id}"><td><b>${sc.id}</b></td><td>${esc(sc.title)}<div class="small muted">${esc(sc.category)} · 공격 ${sc.ground_truth.attack_present?'있음':'없음'}${sc.ground_truth.detectable_by_evidence?'':' · <b>증거로 탐지 불가</b>'}</div></td>
      <td class="${st(fv.verification_status)}">${fv.verification_status}</td><td>${fv.completeness}</td><td class="small">${codes.length?codes.map(esc).join('<br>'):'<span class="absent">없음</span>'}</td>${gates}
      <td class="${audit.ok?'pass':'fail'}">${audit.ok?'일치':'불일치'}${audit.verdict_mismatches.length?` <span class="small">(판정 ${audit.verdict_mismatches.length})</span>`:''}</td><td class="${anch?'pass':'fail'}">${anch?'일치':'재작성 감지'}</td></tr>`;
  }).join('');
  $('#matrix').innerHTML = `<table><thead><tr><th>ID</th><th>시나리오</th><th>최종 판정 (protect 실행)</th><th>완전성</th><th>불일치 코드</th><th>게이트 observe</th><th>게이트 protect</th><th>게이트 strict</th><th>독립 감사</th><th>앵커</th></tr></thead><tbody>${rows}</tbody></table>
  <p class="small muted">게이트 칸의 색은 '공격이 있으면 막았는가, 없으면 통과시켰는가' 기준이다. observe 모드는 설계상 모두 통과시키므로 공격 시나리오에서 빨갛다 — 그것이 관찰 모드의 비용이다. 무응답은 회색이다.</p>`;
  const pick = (sid)=>{cur.sid=sid;cur.attempt=0;onSelectionChanged();};
  document.querySelectorAll('#matrix tr.clickable').forEach(tr=>{
    tr.addEventListener('click',()=>pick(tr.dataset.sid));
    tr.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(tr.dataset.sid);}});
  });
})();

// ---------- 사건 상세: 탭 컨트롤 ----------------------------------------------------
function buildTabs(container, items, isOn, onPick){
  container.innerHTML = items.map(it=>`<button type="button" class="pill${isOn(it)?' on':''}" data-v="${esc(it.v)}">${esc(it.label)}</button>`).join('');
  container.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>onPick(b.dataset.v)));
}
function onSelectionChanged(){
  document.querySelectorAll('#matrix tr').forEach(tr=>tr.classList.toggle('sel',tr.dataset.sid===cur.sid));
  buildTabs($('#scenarioTabs'), D.scenarios.map(sc=>({v:sc.id,label:sc.id})), it=>it.v===cur.sid, v=>{cur.sid=v;cur.attempt=0;onSelectionChanged();});
  buildTabs($('#modeTabs'), ['observe','protect','strict'].map(m=>({v:m,label:m})), it=>it.v===cur.mode, v=>{cur.mode=v;onSelectionChanged();});
  const r = byKey[cur.sid+'|'+cur.mode];
  const attemptRow = $('#attemptRow');
  if (r.attempts.length>1){
    attemptRow.style.display='';
    buildTabs($('#attemptTabs'), r.attempts.map((a,i)=>({v:String(i),label:a.attempt_id})), it=>+it.v===cur.attempt, v=>{cur.attempt=+v;onSelectionChanged();});
  } else { attemptRow.style.display='none'; }
  stopPlayback();
  renderDetail();
}

// ---------- 재생: 실제 타임라인에서 구간을 역산한다 --------------------------------
// 홉 20ms · 중개 처리 5ms · 서명 2ms 는 itx/sim/context.py 의 시뮬레이션 지연 상수와 같다.
const HOP_MS = 20, PROC_MS = 5, SIGN_MS = 2;
// itx/sim/model.py DEFAULT_MODELS 의 latency_ms. 프런트는 백엔드를 다시 호출하지 않으므로
// 표시용으로만 복제했다 — 실제 실행 성능이 아니라 재생 애니메이션의 구간 비율을 정하는 데만 쓴다.
const MODEL_LATENCY_MS = {'model-A':200,'model-A-small':80,'model-B':150};

// 구간은 꺾은선(pts)으로 둔다. 꼴(좌표)은 그래프 캔버스의 노드·핸들 기하(fcShape)에서 뽑으므로 화면의 엣지 위를 그대로 탄다.
// 노드로 들어가는 이동은 홉(20ms) 구간에 붙인다. 처리(5ms)·서명(2ms) 구간에 이동을 넣으면 한 프레임에 순간이동한다.
// arrive 는 이동 구간이 닿는 노드, at 은 머무는 구간이 속한 노드다.
function computeLegs(a, c, rl, m){
  const modelId = (m && m.model_id) || (rl && rl.upstream_model) || c.requested_model;
  const lat = MODEL_LATENCY_MS[modelId] ?? 200;
  const S = fcShape();
  const raw = []; let t = 0;
  const push=(dt,pts,label,work,arrive,at)=>{ raw.push({t0:t,t1:t+dt,pts,label,work,arrive,at}); t+=dt; };
  push(HOP_MS,  S[0], '요청 전송 U→R', false, 'R');
  push(PROC_MS, S[1], 'R 중개자 처리',  true, undefined, 'R');
  push(HOP_MS,  S[2], '요청 전달 R→M',  false, 'M');
  push(lat,     S[3], 'M 추론',         true, undefined, 'M');
  push(SIGN_MS, S[4], 'M 영수증 서명',  true, undefined, 'M');
  push(HOP_MS,  S[5], '응답 전달 M→R',  false, 'R');
  push(SIGN_MS, S[6], 'R 중계 진술 서명', true, undefined, 'R');
  push(HOP_MS,  S[7], '응답 전송 R→U',  false, 'U');
  const rawEnd = t;
  const real0 = a.sent_at, real1 = a.received_at;
  const scale = (rawEnd>0 && real1>real0) ? (real1-real0)/rawEnd : 1;
  return raw.map(L=>({...L, t0:real0+L.t0*scale, t1:real0+L.t1*scale}));
}
const segLen = (a,b)=>Math.hypot(b[0]-a[0], b[1]-a[1]);
function cumulative(pts){ const c=[0]; for(let i=1;i<pts.length;i++) c.push(c[i-1]+segLen(pts[i-1],pts[i])); return c; }
function atDist(pts, c, d){
  const total = c[c.length-1];
  if (total<=0) return [pts[0][0], pts[0][1]];
  const x = Math.max(0, Math.min(total, d));
  for (let i=1;i<pts.length;i++){
    if (x<=c[i] || i===pts.length-1){
      const len=c[i]-c[i-1], f=len>0?(x-c[i-1])/len:0;
      return [pts[i-1][0]+(pts[i][0]-pts[i-1][0])*f, pts[i-1][1]+(pts[i][1]-pts[i-1][1])*f];
    }
  }
  return [pts[pts.length-1][0], pts[pts.length-1][1]];
}
// 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 준다. 노드 안 구간은 앞부분에서 자리를 잡고 머문다.
const easeInOut = (f)=> f<.5 ? 2*f*f : 1-Math.pow(-2*f+2,2)/2;
const settle = (f)=> 1-Math.pow(1-Math.min(1,f/0.28),3);
function packetPos(t, legs){
  if (t<=legs[0].t0){ const p=legs[0].pts[0]; return {x:p[0], y:p[1], leg:legs[0], index:0, f:0}; }
  let index = 0;
  for (let i=0;i<legs.length;i++) if (t>=legs[i].t0) index=i;
  const L = legs[index];
  const raw = Math.max(0, Math.min(1, (t-L.t0)/Math.max(1,L.t1-L.t0)));
  const f = L.work ? settle(raw) : easeInOut(raw);
  const c = cumulative(L.pts), p = atDist(L.pts, c, f*c[c.length-1]);
  return {x:p[0], y:p[1], leg:L, index, f};
}
// 노드에 머무는 구간에서는 잔상이 구간 앞 30% 안에 0 으로 줄어든다 — 도착해서 멈췄다는 사실을 남긴다.
function trailLength(t, legs, base){
  const L = packetPos(t, legs).leg;
  if (!L.work) return base;
  const decay = Math.max(1, (L.t1-L.t0)*0.3);
  return base*Math.max(0, 1-(t-L.t0)/decay);
}
// 진행 방향 뒤쪽으로 maxLen 만큼의 잔상 좌표를 되짚는다. 꺾이는 지점과 구간 경계를 그대로 따라간다.
function trailPoints(t, legs, maxLen){
  const cur = packetPos(t, legs);
  const out = [[cur.x, cur.y]];
  if (maxLen<=0.5) return out;
  let remain = maxLen, i = cur.index, f = cur.f;
  while (remain>0.5 && i>=0){
    const pts = legs[i].pts, c = cumulative(pts);
    let pos = f*c[c.length-1];
    for (let k=pts.length-1; k>=0 && remain>0.5; k--){
      if (c[k]>=pos) continue;
      const step = pos-c[k];
      if (step>=remain){ out.push(atDist(pts, c, pos-remain)); remain=0; break; }
      out.push([pts[k][0], pts[k][1]]); remain-=step; pos=c[k];
    }
    i--; f=1;
  }
  return out;
}

// ---------- 재생 엔진 ------------------------------------------------------------
let PB = null; // 현재 선택의 재생 컨텍스트 (renderDetail 이 채운다)
let playing = false, rafId = null, lastTs = null;
let reducedMotion = false;
try {
  const motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  reducedMotion = motionPreference.matches;
  motionPreference.addEventListener('change', e=>{ reducedMotion = e.matches; });
} catch(e) {}

const SPEEDS = [0.5, 1, 2];
let speed = 1;
function stopPlayback(){
  playing=false; if(rafId) cancelAnimationFrame(rafId); rafId=null; lastTs=null; if(PB) PB.prev=null;
  document.querySelectorAll('.flowing, .pulse, .settling').forEach(el=>el.classList.remove('flowing','pulse','settling'));
  scrubTip(null); updatePlayBtn();
}
function updatePlayBtn(){
  const b=$('#playBtn'); if(b){ b.textContent = playing?'❚❚ 일시정지':'▶ 재생'; b.setAttribute('aria-pressed', String(playing)); }
  const sp=$('#speedBtn'); if(sp) sp.textContent = speed+'×';
}
function setT(v){
  if(!PB) return;
  const next = Math.max(0, Math.min(PB.tEnd, v));
  // 뒤로 가면 그 이후의 도달 펄스를 다시 낼 수 있게 되돌린다.
  if (next < PB.t) for (const i of [...PB.fired]) if (PB.legs[i].t1 > next) PB.fired.delete(i);
  PB.t = next; updatePacket();
}
// 홉 경계(구간 시작·끝)로만 이동한다. 어떤 구간에서 무엇이 바뀌는지 한 걸음씩 확인하는 용도다.
function stepHop(dir){
  if(!PB) return;
  const marks = [...new Set([0, ...PB.legs.map(l=>l.t0), ...PB.legs.map(l=>l.t1), PB.tEnd])]
    .filter(v=>v>=0 && v<=PB.tEnd).sort((a,b)=>a-b);
  const next = dir>0 ? marks.find(v=>v>PB.t+0.5) : [...marks].reverse().find(v=>v<PB.t-0.5);
  setT(next ?? (dir>0 ? PB.tEnd : 0));
}
function stepPlayback(ts){
  if (!playing) return;
  if (reducedMotion){ stopPlayback(); setT(PB.tEnd); return; }
  const dt = lastTs!=null ? Math.min(64, ts-lastTs) : 16; lastTs = ts;
  const base = Math.max(0.05, PB.tEnd/3600); // 원안: ×1 재생은 약 3.6초, 구간 비율은 실제 값 그대로
  let nt = PB.t + dt*base*speed;
  if (nt >= PB.tEnd) { nt = PB.tEnd; playing = false; }
  setT(nt);
  if (playing) rafId = requestAnimationFrame(stepPlayback); else updatePlayBtn();
}
function togglePlay(){
  if (!PB) return;
  if (reducedMotion){ stopPlayback(); setT(PB.tEnd); return; } // 축소 모션: 최종 상태로 즉시 점프, 재생하지 않는다
  if (playing) { stopPlayback(); return; }
  if (PB.t >= PB.tEnd) setT(0);
  playing = true; lastTs = null; updatePlayBtn();
  rafId = requestAnimationFrame(stepPlayback);
}
$('#playBtn').addEventListener('click', togglePlay);
$('#resetBtn').addEventListener('click', ()=>{ stopPlayback(); setT(0); });
$('#stepBackBtn').addEventListener('click', ()=>{ stopPlayback(); stepHop(-1); });
$('#stepFwdBtn').addEventListener('click', ()=>{ stopPlayback(); stepHop(1); });
$('#speedBtn').addEventListener('click', ()=>{ speed = SPEEDS[(SPEEDS.indexOf(speed)+1)%SPEEDS.length]; updatePlayBtn(); });

// 시점 타임라인 스크러버: 누른 자리로 바로 이동하고 드래그로 따라간다.
let scrubbing = null;
function seekAt(box, clientX){
  if (!PB) return;
  const r = box.getBoundingClientRect();
  if (r.width<=0) return;
  setT(PB.span.inv(((clientX-r.left)/r.width)*100));
}
document.addEventListener('pointerdown', e=>{
  const box = e.target.closest && e.target.closest('[data-scrub]');
  if (!box || !PB || e.button!==0 || !e.isPrimary || scrubbing) return;
  e.preventDefault(); stopPlayback(); scrubbing = {box, pointerId:e.pointerId}; box.setPointerCapture(e.pointerId); box.focus();
  seekAt(box, e.clientX); scrubTip(box, e.clientX);
});
function packetLabel(t, legs){
  return t<legs[0].t0 ? '전송 전' : t>=legs[legs.length-1].t1 ? '응답 수신 후' : packetPos(t, legs).leg.label;
}
// 커서 아래 시점을 툴팁으로 말한다: 어느 구간인지, 전송 전인지, 수신 후인지. 드래그 중에는 재생 헤드가 그 자리다.
function scrubTip(box, clientX){
  const el = $('#itxScrubTip'); if (!el) return;
  if (!box || !PB){ el.hidden = true; return; }
  const r = box.getBoundingClientRect(); if (r.width<=0){ el.hidden = true; return; }
  const pct = Math.max(0, Math.min(100, ((clientX-r.left)/r.width)*100));
  const t = scrubbing ? PB.t : PB.span.inv(pct);
  el.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, PB.legs)}`;
  el.hidden = false;
  const half = el.offsetWidth/2+4, x = (scrubbing ? PB.span(t) : pct)/100*r.width;
  el.style.left = Math.max(half, Math.min(r.width-half, x)).toFixed(1)+'px';
}
document.addEventListener('pointermove', e=>{
  if (scrubbing){
    if (e.pointerId===scrubbing.pointerId){ seekAt(scrubbing.box, e.clientX); scrubTip(scrubbing.box, e.clientX); }
    return;
  }
  if (!e.isPrimary) return;
  const box = e.target && e.target.closest ? e.target.closest('[data-scrub]') : null;
  scrubTip(box, e.clientX);
});
function cancelScrub(){
  const active = scrubbing; scrubbing=null;
  if (active && active.box.hasPointerCapture(active.pointerId)) active.box.releasePointerCapture(active.pointerId);
  scrubTip(null);
}
const endScrub = e=>{ if(scrubbing && scrubbing.pointerId===e.pointerId) cancelScrub(); };
document.addEventListener('pointerup', e=>{
  if(scrubbing && scrubbing.pointerId===e.pointerId){ seekAt(scrubbing.box, e.clientX); cancelScrub(); }
});
document.addEventListener('pointercancel', endScrub);
document.addEventListener('lostpointercapture', endScrub);
document.addEventListener('pointerleave', ()=>{ if(!scrubbing) scrubTip(null); });
// 키보드 (원안): 입력란 밖이면 어디서든 Space 재생·정지, ←/→ 홉 이동, R·Home 처음, F 핏뷰.
document.addEventListener('keydown', e=>{
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || e.altKey || e.ctrlKey || e.metaKey) return;
  if (e.key === ' '){ if (e.target && e.target.closest && e.target.closest('button')) return; e.preventDefault(); if(!e.repeat) togglePlay(); }
  else if (e.key === 'ArrowRight'){ e.preventDefault(); stopPlayback(); stepHop(1); }
  else if (e.key === 'ArrowLeft'){ e.preventDefault(); stopPlayback(); stepHop(-1); }
  else if (e.key === 'r' || e.key === 'R' || e.key === 'Home'){ stopPlayback(); setT(0); }
  else if ((e.key === 'f' || e.key === 'F') && typeof fcFit === 'function'){ fcFit(); }
});

// ---------- 홉 지도 (Claude Design 'Hopmap Console v2' 원안 그대로 · 가상화 뷰만 제외) ----------
// 원안의 상수·배치·로직을 그대로 쓴다. 원안이 합성했던 값(시각·판정·등록 시각)만 실제 사건 데이터로 채운다.
const EQ_TITLE = {E1:'자기 정합', E2:'요청 U→R', E3:'진술 R↔M', E4:'승인 변환 재계산', E5:'nonce 결합', E6:'응답 M→R',
  E7:'응답 R→U', E8:'승인 경로', E9:'아티팩트', E10:'종단 응답 결합', E11:'시도 결합', E12:'유효기간'};
function eqGlyph(r){ return r==='pass'?'✓':r==='fail'?'✗':'–'; }
const NODE_DEF = {
  U:{label:'U', name:'사용자 · 집행 모듈', sub:'로컬 검증 · 격리', rows:['E12','E2','E10','E1']},
  R:{label:'R', name:'중개자 (클라우드 대행)', sub:'중계 진술 서명', rows:['E3','E4','E7']},
  M:{label:'M', name:'모델 운영자', sub:'추론 · 영수증 서명', rows:['E6','E5','E11']},
  T:{label:'T', name:'T — 독립 제3자', sub:'대조 · 정책 · 추가 전용 로그', rows:['E9','E8','E1']}
};
const LAYOUTS = {
  dagre: {label:'계층 · Dagre LR', axis:'h', pos:{U:[70,250], R:[520,250], M:[970,250], T:[520,600]}},
  elk:   {label:'직교 · ELK', axis:'v', pos:{U:[90,70], R:[600,330], M:[1060,70], T:[600,650]}}
};
const WORLD = {map:{w:1340, h:820}, sm:{w:1280, h:620}};
// CSS 가 정한 값과 같아야 한다: 머리 48 + 카드 위아래 테두리 2, 행 24, 행 영역 패딩 11
const NW = 250, HEAD = 50, ROWH = 24;
const APPLE = f => 1 - Math.pow(1 - f, 4);
const lerp = (a, b, f) => a + (b - a) * f;
const EV_NAME = {U:'U 요청 진술', R:'R 중계 진술', M:'M 응답 영수증'};
const EV_DETAIL = {U:'contract · nonce · 허용 모델 집합', R:'전달 해시 · 변환 선언', M:'응답 커밋 · 시도 ID · 서명'};
const SM = {
  base:[['sign','계약 서명','U 서명 · 만료 고정'],['send','전송','U→R→M'],['recv','응답 수신','본문 + 영수증'],['verify','로컬 검증','E2 · E10 · nonce']],
  observe:[['show','표시만','상태만 알린다'],['accept','수용','검증 실패도 업무 반영']],
  protect:[['accept','수용','로컬 검증 통과'],['hold','격리','업무 반영 전 차단']],
  strict:[['wait','T 판정 대기','기한 내 등록 필요'],['accept','수용','로컬 + T 판정'],['deny','거부','기한 내 판정 없음']]
};
// 캔버스 상태 (원안의 this.state / 인스턴스 필드)
const fc = {view:'map', layout:'dagre', open:{U:true, R:true, M:true, T:true}, sel:null, showMinimap:true,
  vp:{x:40, y:20, k:.66}, posA:LAYOUTS.dagre.pos, posB:null, lt:1, axisA:'h', axisB:null, lraf:0};
let fcPan = null, fcMini = null;
function fcPos(){
  if (!fc.posB) return fc.posA;
  const f = APPLE(fc.lt), out = {};
  for (const k in fc.posA) out[k] = [lerp(fc.posA[k][0], fc.posB[k][0], f), lerp(fc.posA[k][1], fc.posB[k][1], f)];
  return out;
}
function fcAxis(){ return fc.posB ? (fc.lt < .5 ? fc.axisA : fc.axisB) : fc.axisA; }
function nodeH(id){ return fc.open[id] ? HEAD + NODE_DEF[id].rows.length*ROWH + 11 : HEAD; }
function anchor(id, side, frac){
  const p = fcPos()[id], h = nodeH(id);
  if (side === 'r') return [p[0]+NW, p[1]+h*frac];
  if (side === 'l') return [p[0], p[1]+h*frac];
  if (side === 't') return [p[0]+NW*frac, p[1]];
  return [p[0]+NW*frac, p[1]+h];
}
function ends(a, b, frac){
  const ax = fcAxis(), pa = fcPos()[a], pb = fcPos()[b];
  if (ax === 'h'){ const fwd = pb[0] >= pa[0]; return [anchor(a, fwd?'r':'l', frac), anchor(b, fwd?'l':'r', frac)]; }
  const down = pb[1] >= pa[1];
  return [anchor(a, down?'b':'t', frac), anchor(b, down?'t':'b', frac)];
}
function smoothstep(x1, y1, x2, y2, axis){
  const r = 14;
  if (axis === 'h'){
    const mx = (x1+x2)/2, sx = x2 > x1 ? 1 : -1, sy = y2 > y1 ? 1 : -1;
    if (Math.abs(y2-y1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`;
    return `M ${x1} ${y1} L ${mx-r*sx} ${y1} Q ${mx} ${y1} ${mx} ${y1+r*sy} L ${mx} ${y2-r*sy} Q ${mx} ${y2} ${mx+r*sx} ${y2} L ${x2} ${y2}`;
  }
  const my = (y1+y2)/2, sy = y2 > y1 ? 1 : -1, sx = x2 > x1 ? 1 : -1;
  if (Math.abs(x2-x1) < 2) return `M ${x1} ${y1} L ${x2} ${y2}`;
  return `M ${x1} ${y1} L ${x1} ${my-r*sy} Q ${x1} ${my} ${x1+r*sx} ${my} L ${x2-r*sx} ${my} Q ${x2} ${my} ${x2} ${my+r*sy} L ${x2} ${y2}`;
}
function stepPts(x1, y1, x2, y2, axis){
  if (axis === 'h'){ const mx = (x1+x2)/2; return [[x1,y1],[mx,y1],[mx,y2],[x2,y2]]; }
  const my = (y1+y2)/2; return [[x1,y1],[x1,my],[x2,my],[x2,y2]];
}
// 원안 flowLegs 의 꼴. computeLegs 가 시간을 입힌다.
function fcShape(){
  const ax = fcAxis();
  const pair = (a, b, frac) => { const [p, q] = ends(a, b, frac); return stepPts(p[0], p[1], q[0], q[1], ax); };
  const at = (id, side, frac) => [anchor(id, side, frac)];
  const ax2 = ax === 'h' ? {in:'l', out:'r'} : {in:'t', out:'b'};
  return [pair('U','R',.3), at('R', ax2.in, .3), pair('R','M',.3), at('M', ax2.in, .3), at('M', ax2.in, .72),
          pair('M','R',.72), at('R', ax === 'h' ? 'r' : 'b', .72), pair('R','U',.72)];
}
function ringFor(legs, node, t){
  const lat = legs[3].t1 - legs[3].t0, win = Math.max(8, lat*0.14);
  let best = 0;
  for (const L of legs) if (L.arrive === node && t >= L.t1){ const f = 1 - (t - L.t1)/win; if (f > best) best = f; }
  return +Math.max(0, Math.min(1, best)).toFixed(3);
}
function clipLine(a, b){
  const P = fcPos(), pa = P[a], pb = P[b], ha = nodeH(a), hb = nodeH(b);
  const c1 = [pa[0]+NW/2, pa[1]+ha/2], c2 = [pb[0]+NW/2, pb[1]+hb/2];
  const cut = (c, o, w, h) => {
    const dx = o[0]-c[0], dy = o[1]-c[1];
    const sx = dx === 0 ? Infinity : (w/2)/Math.abs(dx), sy = dy === 0 ? Infinity : (h/2)/Math.abs(dy);
    const k = Math.min(sx, sy); return [c[0]+dx*k, c[1]+dy*k];
  };
  return [cut(c1, c2, NW, ha), cut(c2, c1, NW, hb)];
}
const fcRes = id => (PB && PB.eq[id] ? PB.eq[id].result : null) || 'not_evaluable';
const colOf = r => CV(cls(r));
// ---- 개선 캔버스: 엣지 ----
function fcEdges(){
  const ax = fcAxis(), t = PB ? PB.t : 0;
  const mkFlow = (id, a, b, frac) => { const [p, q] = ends(a, b, frac), r = fcRes(id);
    return {id, d:smoothstep(p[0], p[1], q[0], q[1], ax), color:colOf(r), dash:'none', marker:'url(#itxar)', cls:'', res:r, mid:[(p[0]+q[0])/2, (p[1]+q[1])/2]}; };
  const edges = [mkFlow('E2','U','R',.3), mkFlow('E3','R','M',.3), mkFlow('E6','M','R',.72), mkFlow('E7','R','U',.72)];
  { const [p, q] = clipLine('U','M'), r = fcRes('E10'), my = Math.max(p[1], q[1]) + 190;
    edges.push({id:'E10', d:`M ${p[0]} ${p[1]} C ${p[0]} ${my} ${q[0]} ${my} ${q[0]} ${q[1]}`, color:colOf(r), dash:'7 4', marker:'none', cls:'', res:r, mid:[(p[0]+q[0])/2, my*0.78]}); }
  for (const k of ['U','R','M']){
    const reg = PB ? PB.regs[k] : null, registered = reg != null && t >= reg;
    const [p, q] = clipLine(k, 'T');
    edges.push({id:'ev'+k, ev:k, d:`M ${p[0]} ${p[1]} L ${q[0]} ${q[1]}`, color: reg == null ? CV('na') : registered ? CV('accent') : CV('line'),
      dash:'4 6', marker:'none', cls: registered && playing ? 'flowing' : '', res:'', mid:[(p[0]+q[0])/2, (p[1]+q[1])/2]});
  }
  return edges;
}
function fcMapWorldHtml(){
  const edges = fcEdges(), P = fcPos(), ax = fcAxis();
  const start = fcShape()[0][0];
  const paths = edges.map(e => `<path ${e.ev ? `id="itxEv${e.ev}" class="evline${e.cls?' '+e.cls:''}"` : `class="edge${fc.sel===e.id?' on':''}" data-edge-path="${e.id}"`} d="${e.d}" fill="none" stroke="${e.color}" stroke-width="2.5" stroke-dasharray="${e.dash}" stroke-linecap="round" marker-end="${e.marker}"/>`).join('')
    + edges.map(e => `<path class="edge-hit" d="${e.d}" ${e.ev ? `data-fc-ev="${e.ev}"` : `data-eq="${e.id}" data-fc-pick="${e.id}"`}/>`).join('');
  const labels = edges.filter(e => e.res).map(e => `<div class="fclabel${fc.sel===e.id?' sel':''}" data-eq="${e.id}" data-fc-pick="${e.id}" style="left:${e.mid[0].toFixed(1)}px;top:${e.mid[1].toFixed(1)}px;color:${e.color}">${eqGlyph(e.res)} ${e.id} ${EQ_TITLE[e.id]}</div>`).join('');
  const nodes = Object.keys(NODE_DEF).map(id => {
    const d = NODE_DEF[id], open = !!fc.open[id], isT = id === 'T';
    const rows = d.rows.map(eid => { const r = fcRes(eid);
      return `<div class="fcrow${fc.sel===eid?' sel':''}" data-eq="${eid}" data-fc-pick="${eid}"><span class="g" style="color:${colOf(r)}">${eqGlyph(r)}</span><span class="i" style="color:${colOf(r)}">${eid}</span><span class="n">${EQ_TITLE[eid]}</span><span class="d" style="background:${colOf(r)}"></span></div>`; }).join('');
    const handles = (ax === 'h' ? ['left:0;top:30%','left:0;top:72%','left:100%;top:30%','left:100%;top:72%'] : ['top:0;left:30%','top:0;left:72%','top:100%;left:30%','top:100%;left:72%'])
      .map(st => `<span class="handle" style="${st}"></span>`).join('');
    return `<div class="fcnode${isT?' t':''}${open?'':' closed'}" data-node="${id}" style="left:${P[id][0].toFixed(1)}px;top:${P[id][1].toFixed(1)}px">
      <div class="ring" data-ring="${id}" style="opacity:0"></div>
      <div class="fccard"><div class="fchead"><span class="fcbadge">${d.label}</span><span style="min-width:0;flex:1"><span class="fcname">${esc(d.name)}</span><span class="fcsub">${esc(d.sub)}</span></span>
        <button type="button" class="fccaret" data-fc-toggle="${id}" title="포트 접기 · 펼치기">${open?'▾':'▸'}</button></div>
        <div class="fcrows">${rows}</div></div>${handles}</div>`;
  }).join('');
  return `<svg width="${WORLD.map.w}" height="${WORLD.map.h}" viewBox="0 0 ${WORLD.map.w} ${WORLD.map.h}" aria-hidden="true">
      <defs><marker id="itxar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('na')}"/></marker>
        <linearGradient id="itxTrailGradient" gradientUnits="userSpaceOnUse" x1="${start[0]-20}" y1="${start[1]}" x2="${start[0]}" y2="${start[1]}" style="color:${CV('accent')}">
          <stop offset="0" stop-color="currentColor" stop-opacity="0"/><stop offset="1" stop-color="currentColor" stop-opacity=".65"/></linearGradient></defs>
      <g id="itxEdges">${paths}</g>
      <polyline id="itxTrail" class="packettrail" points="" fill="none" stroke="url(#itxTrailGradient)" stroke-width="6" stroke-linecap="round" stroke-linejoin="round" opacity="0"/>
      <circle id="itxPacket" class="packet" cx="${start[0]}" cy="${start[1]}" r="6" fill="${CV('accent')}"/>
    </svg><div id="itxEdgeLabels">${labels}</div><div id="itxNodes">${nodes}</div>`;
}
// ---- 상태 머신 뷰 (원안 체인·배치·활성 규칙). 결정 자리에는 이 요청의 실제 게이트 결정을 쓴다 ----
function smChain(){ const mode = PB ? PB.mode : 'protect'; return SM.base.concat(SM[mode] || SM.protect); }
function smActiveKey(t){
  const legs = PB.legs, last = legs[legs.length-1], consumed = PB.consumedAt, verdict = PB.verdictAt, mode = PB.mode;
  const act = PB.gateAction, blocked = act === 'quarantine' || act === 'reject' || act === 'reject_timeout' || act === 'no_response';
  let activeKey = 'sign';
  if (t > 0 && t < last.t1) activeKey = 'send';
  else if (t >= last.t1 && t < last.t1 + 8) activeKey = 'recv';
  else if (t >= last.t1 + 8 && (consumed == null || t < consumed) && t < PB.decidedAt) activeKey = 'verify';
  else if (t >= Math.min(consumed != null ? consumed : Infinity, PB.decidedAt)){
    if (mode === 'observe') activeKey = 'accept';
    else if (mode === 'protect') activeKey = blocked ? 'hold' : 'accept';
    else activeKey = verdict == null ? (t > last.t1 + 700 ? 'deny' : 'wait') : (t >= verdict ? (blocked ? 'deny' : 'accept') : 'wait');
  }
  return activeKey;
}
const smXY = i => [i < 4 ? 70 + i*300 : 70 + (i-4)*300, i < 4 ? 130 : 400];
function fcSmWorldHtml(){
  const chain = smChain();
  const cards = chain.map(([k, name, sub], i) => { const [x, y] = smXY(i);
    return `<div class="fcsm${k==='hold'||k==='deny'?' term':''}" data-sm="${k}" style="left:${x}px;top:${y}px"><span class="n">${esc(name)}</span><span class="s">${esc(sub)}</span></div>`; }).join('');
  let paths = '';
  for (let i = 0; i < chain.length - 1; i++){
    const [ax1, ay1] = smXY(i), [bx1, by1] = smXY(i+1), sameRow = (i < 4) === (i+1 < 4);
    const p = sameRow ? [ax1+244, ay1+34] : [ax1+122, ay1+70], q = sameRow ? [bx1, by1+34] : [bx1+122, by1];
    paths += `<path class="smedge" data-sm-edge="${i}" d="${smoothstep(p[0], p[1], q[0], q[1], sameRow ? 'h' : 'v')}" marker-end="url(#itxar)"/>`;
  }
  return `<svg width="${WORLD.sm.w}" height="${WORLD.sm.h}" viewBox="0 0 ${WORLD.sm.w} ${WORLD.sm.h}" aria-hidden="true"><defs><marker id="itxar" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 z" fill="${CV('na')}"/></marker></defs>${paths}</svg>${cards}`;
}
function fcSmUpdate(t){
  if (fc.view !== 'sm' || !PB) return;
  const chain = smChain(), key = smActiveKey(t), idx = chain.findIndex(c => c[0] === key);
  document.querySelectorAll('.fcsm[data-sm]').forEach(el => el.classList.toggle('on', el.dataset.sm === key));
  document.querySelectorAll('[data-sm-edge]').forEach(el => el.classList.toggle('done', idx > +el.dataset.smEdge));
}
// ---- 도달 링: 원안 ringFor 로 프레임마다 감쇠 ----
function fcRings(t){
  if (!PB || fc.view !== 'map') return;
  const legs = PB.legs, lat = legs[3].t1 - legs[3].t0;
  for (const k of ['U','R','M']){ const el = document.querySelector(`[data-ring="${k}"]`); if (el) el.style.opacity = String(ringFor(legs, k, t)); }
  const tr = document.querySelector('[data-ring="T"]');
  if (tr) tr.style.opacity = String(Math.max(0, ...['U','R','M'].map(k => { const reg = PB.regs[k]; if (reg == null || t < reg) return 0; return Math.max(0, 1 - (t - reg)/Math.max(8, lat*0.14)); })).toFixed(3));
}
// ---- 미니맵 · 월드 · 캔버스 ----
function fcWorld(){ return fc.view === 'sm' ? WORLD.sm : WORLD.map; }
function fcMiniShapesHtml(){
  if (fc.view === 'sm') return smChain().map((c, i) => { const [x, y] = smXY(i); return `<rect class="mmnode" x="${x}" y="${y}" width="244" height="70" rx="6"/>`; }).join('');
  const P = fcPos();
  return Object.keys(NODE_DEF).map(id => `<rect class="mmnode${id==='T'?' t':''}" x="${P[id][0].toFixed(1)}" y="${P[id][1].toFixed(1)}" width="${NW}" height="${nodeH(id)}" rx="6"/>`).join('');
}
function fcWorldHtml(){ return fc.view === 'sm' ? fcSmWorldHtml() : fcMapWorldHtml(); }
function fcCanvasHtml(){
  const W = fcWorld();
  const tabs = [['map','경로 지도','U·R·M·T 홉 그래프'],['sm','게이트 상태 머신','AntV X6 스타일 상태 전이']]
    .map(([k, l, ti]) => `<button type="button" class="itx-btn tab${fc.view===k?' on':''}" data-fc-view="${k}" title="${ti}">${l}</button>`).join('');
  const lays = Object.keys(LAYOUTS).map(k => `<button type="button" class="itx-btn tab lay${fc.layout===k?' on':''}${fc.view==='map'?'':' off'}" data-fc-layout="${k}" title="자동 레이아웃 — 전환은 애니메이션으로 이어진다">${LAYOUTS[k].label}</button>`).join('');
  return `<div class="flowc" id="itxFlow" tabindex="0" role="img" aria-label="홉 정합 지도 — 그래프 캔버스">
    <div class="flowc-bar">${tabs}<span class="sp"></span>${lays}
      <span style="margin-left:auto;display:flex;align-items:center;gap:6px">
        <button type="button" class="itx-btn sq" data-fc-zoom="out" title="축소 (−)">−</button><span class="zoom" id="itxZoom">66%</span><button type="button" class="itx-btn sq" data-fc-zoom="in" title="확대 (+)">+</button>
        <button type="button" class="itx-btn" data-fc-zoom="fit" title="전체 보기 (F)">핏뷰</button>
        <button type="button" class="itx-btn${fc.showMinimap?' on':''}" data-fc-mini title="미니맵 표시">미니맵</button></span>
    </div>
    <div class="flowc-canvas" id="itxCanvas">
      <div class="flowc-world" id="itxWorld">${fcWorldHtml()}</div>
      <div class="flowc-tip" id="itxTip" hidden></div>
      <div class="flowc-legend"><span class="pass">✓ pass</span><span class="fail">✗ fail</span><span class="na">– not_evaluable</span><span>휠 줌 · 드래그 팬 · 엣지 클릭 선택</span></div>
      <div class="flowc-mini" id="itxMini"${fc.showMinimap?'':' hidden'}><svg id="itxMiniSvg" viewBox="0 0 ${W.w} ${W.h}" preserveAspectRatio="xMidYMid meet"><g id="itxMiniShapes">${fcMiniShapesHtml()}</g><rect class="mmview" id="itxMiniView" x="0" y="0" width="${W.w}" height="${W.h}"/></svg><span class="mmtag">MINIMAP</span></div>
      <div class="flowc-sel" id="itxSel" hidden><div class="h"><span class="id" id="itxSelId"></span><span class="ti" id="itxSelTitle"></span><button type="button" class="x" data-fc-clear>닫기</button></div><div class="reason" id="itxSelReason"></div><div class="cmp" id="itxSelCmp"></div></div>
    </div>
    <div class="flowc-foot" id="itxFoot"></div>
  </div>`;
}
// ---------- 뷰포트 · 상호작용 (원안 핸들러) ----------
function fcCanvasRect(){ const el = $('#itxCanvas'); return el ? el.getBoundingClientRect() : null; }
function fcApply(){
  const w = $('#itxWorld'), cv = $('#itxCanvas'); if (!w || !cv) return;
  w.style.transform = `translate(${fc.vp.x.toFixed(1)}px,${fc.vp.y.toFixed(1)}px) scale(${fc.vp.k.toFixed(3)})`;
  cv.style.backgroundSize = `${(22*fc.vp.k).toFixed(1)}px ${(22*fc.vp.k).toFixed(1)}px`;
  cv.style.backgroundPosition = `${fc.vp.x.toFixed(1)}px ${fc.vp.y.toFixed(1)}px`;
  const z = $('#itxZoom'); if (z) z.textContent = Math.round(fc.vp.k*100)+'%';
  const r = fcCanvasRect(), mv = $('#itxMiniView');
  if (r && mv){ mv.setAttribute('x', (-fc.vp.x/fc.vp.k).toFixed(1)); mv.setAttribute('y', (-fc.vp.y/fc.vp.k).toFixed(1)); mv.setAttribute('width', (r.width/fc.vp.k).toFixed(1)); mv.setAttribute('height', (r.height/fc.vp.k).toFixed(1)); }
}
function fcFit(){
  const r = fcCanvasRect(), w = fcWorld(); if (!r || r.width <= 0) return;
  const k = Math.max(.2, Math.min(1.6, Math.min(r.width/w.w, r.height/w.h)*0.94));
  fc.vp = {k, x:(r.width - w.w*k)/2, y:(r.height - w.h*k)/2}; fcApply();
}
function fcZoomBy(f){
  const r = fcCanvasRect(); if (!r) return;
  const k = Math.max(.25, Math.min(2.4, fc.vp.k*f)), cw = r.width, ch = r.height;
  fc.vp = {k, x: cw/2 - (cw/2 - fc.vp.x)*(k/fc.vp.k), y: ch/2 - (ch/2 - fc.vp.y)*(k/fc.vp.k)}; fcApply();
}
function fcMiniTo(cx, cy, r){
  const w = fcWorld(), c = fcCanvasRect(); if (!c) return;
  const k = Math.min(r.width/w.w, r.height/w.h), offx = (r.width - w.w*k)/2, offy = (r.height - w.h*k)/2;
  const wx = (cx - r.left - offx)/k, wy = (cy - r.top - offy)/k;
  fc.vp = {k:fc.vp.k, x:c.width/2 - wx*fc.vp.k, y:c.height/2 - wy*fc.vp.k}; fcApply();
}
function fcRenderWorld(){
  const w = $('#itxWorld'); if (!w || !PB) return;
  w.innerHTML = fcWorldHtml();
  const ms = $('#itxMiniShapes'); if (ms) ms.innerHTML = fcMiniShapesHtml();
  const msvg = $('#itxMiniSvg'), W = fcWorld(); if (msvg) msvg.setAttribute('viewBox', `0 0 ${W.w} ${W.h}`);
  const mv = $('#itxMiniView'); if (mv){ mv.setAttribute('width', String(W.w)); mv.setAttribute('height', String(W.h)); }
  if (PB.legArgs){ const t = PB.t; PB.legs = computeLegs(...PB.legArgs); PB.t = t; }
  PB.fill = ''; PB.prev = null;
  fcApply(); updatePacket();
}
function fcTip(text){ const el = $('#itxTip'); if (!el) return; if (!text){ el.hidden = true; return; } el.textContent = text; el.hidden = false; }
function fcSelect(id){
  fc.sel = id;
  document.querySelectorAll('.fclabel.sel, .fcrow.sel, .edge.on').forEach(n => n.classList.remove('sel','on'));
  const panel = $('#itxSel'); if (!panel) return;
  if (!id || !PB){ panel.hidden = true; return; }
  document.querySelectorAll(`[data-fc-pick="${id}"]`).forEach(n => n.classList.add('sel'));
  document.querySelectorAll(`[data-edge-path="${id}"]`).forEach(n => n.classList.add('on'));
  const e = PB.eq[id] || {}, r = e.result || 'not_evaluable';
  $('#itxSelId').textContent = id; $('#itxSelId').style.color = colOf(r);
  $('#itxSelTitle').textContent = EQ_TITLE[id] || '';
  $('#itxSelReason').textContent = e.reason || `결과 ${r} — 사유는 등식 표에서 확인한다.`;
  $('#itxSelCmp').textContent = `비교 대상 · ${(e.compared||[]).join(' · ') || id} · trust_grade=${e.trust_grade || '—'} · 판정 ${r}`;
  panel.hidden = false;
}
function fcSetLayout(k){
  if (k === fc.layout || fc.view !== 'map') return;
  fc.posA = fcPos(); fc.axisA = fcAxis(); fc.posB = LAYOUTS[k].pos; fc.axisB = LAYOUTS[k].axis; fc.lt = 0; fc.layout = k;
  document.querySelectorAll('[data-fc-layout]').forEach(b => b.classList.toggle('on', b.dataset.fcLayout === k));
  const t0 = performance.now();
  const run = ts => {
    fc.lt = Math.min(1, (ts - t0)/520);
    if (fc.lt >= 1){ fc.posA = fc.posB; fc.axisA = fc.axisB; fc.posB = null; fc.axisB = null; }
    fcRenderWorld();
    if (fc.posB) fc.lraf = requestAnimationFrame(run);
  };
  cancelAnimationFrame(fc.lraf); fc.lraf = requestAnimationFrame(reducedMotion ? ts => { fc.lt = 1; run(ts); } : run);
}
function fcSetView(v){
  fc.view = v; fc.sel = null;
  document.querySelectorAll('[data-fc-view]').forEach(b => b.classList.toggle('on', b.dataset.fcView === v));
  document.querySelectorAll('[data-fc-layout]').forEach(b => b.classList.toggle('off', v !== 'map'));
  fcSelect(null); fcTip(null); fcRenderWorld(); requestAnimationFrame(fcFit);
}
function fcMount(){
  const cv = $('#itxCanvas'); if (!cv) return;
  fcSelect(null); fcTip(null);
  if (typeof ResizeObserver !== 'undefined' && !cv.__ro){ cv.__ro = new ResizeObserver(fcFit); cv.__ro.observe(cv); }
  fcApply(); requestAnimationFrame(fcFit);
}
document.addEventListener('click', e => {
  const t = e.target; if (!t.closest) return;
  const z = t.closest('[data-fc-zoom]');
  if (z){ if (z.dataset.fcZoom === 'fit') fcFit(); else fcZoomBy(z.dataset.fcZoom === 'in' ? 1.18 : 1/1.18); return; }
  const mb = t.closest('[data-fc-mini]');
  if (mb){ fc.showMinimap = !fc.showMinimap; const m = $('#itxMini'); if (m) m.hidden = !fc.showMinimap; mb.classList.toggle('on', fc.showMinimap); return; }
  const tg = t.closest('[data-fc-toggle]');
  if (tg){ const id = tg.dataset.fcToggle; fc.open[id] = !fc.open[id]; fcRenderWorld(); return; }
  const vb = t.closest('[data-fc-view]'); if (vb){ fcSetView(vb.dataset.fcView); return; }
  const lb = t.closest('[data-fc-layout]'); if (lb){ fcSetLayout(lb.dataset.fcLayout); return; }
  if (t.closest('[data-fc-clear]')){ fcSelect(null); return; }
  const pk = t.closest('[data-fc-pick]');
  if (pk && !t.closest('[data-copy]')) fcSelect(fc.sel === pk.dataset.fcPick ? null : pk.dataset.fcPick);
});
document.addEventListener('mouseover', e => {
  const t = e.target; if (!t.closest || !t.closest('#itxCanvas')) return;
  const pk = t.closest('[data-fc-pick]');
  if (pk){ const id = pk.dataset.fcPick; fcTip(`${id} ${EQ_TITLE[id] || ''} — ${fcRes(id)}`); return; }
  const ev = t.closest('[data-fc-ev]');
  if (ev && PB){ const k = ev.dataset.fcEv, reg = PB.regs[k]; fcTip(`${EV_NAME[k]} 제출 — ${reg == null ? '결손 (등록 없음)' : PB.t >= reg ? '등록 ≤ '+reg+' ms' : '대기'}`); return; }
  fcTip(null);
});
document.addEventListener('pointerdown', e => {
  const t = e.target; if (!t.closest || e.button !== 0) return;
  const mini = t.closest('#itxMini');
  if (mini){ e.preventDefault(); e.stopPropagation(); const r = mini.getBoundingClientRect(); fcMini = {r, id:e.pointerId}; mini.setPointerCapture(e.pointerId); fcMiniTo(e.clientX, e.clientY, r); return; }
  const cv = t.closest('#itxCanvas'); if (!cv) return;
  if (t.closest('button, .fcnode, .fclabel, .fcsm, [data-copy], .flowc-sel')) return;
  e.preventDefault(); fcPan = {x:e.clientX, y:e.clientY, vx:fc.vp.x, vy:fc.vp.y, id:e.pointerId}; cv.setPointerCapture(e.pointerId); cv.classList.add('panning');
});
document.addEventListener('pointermove', e => {
  if (fcMini && fcMini.id === e.pointerId){ fcMiniTo(e.clientX, e.clientY, fcMini.r); return; }
  if (fcPan && fcPan.id === e.pointerId){ fc.vp = {k:fc.vp.k, x:fcPan.vx + (e.clientX - fcPan.x), y:fcPan.vy + (e.clientY - fcPan.y)}; fcApply(); }
});
const fcEndPointer = e => {
  if (fcMini && fcMini.id === e.pointerId) fcMini = null;
  if (fcPan && fcPan.id === e.pointerId){ const cv = $('#itxCanvas'); if (cv) cv.classList.remove('panning'); fcPan = null; }
};
document.addEventListener('pointerup', fcEndPointer); document.addEventListener('pointercancel', fcEndPointer);
document.addEventListener('wheel', e => {
  const cv = e.target && e.target.closest ? e.target.closest('#itxCanvas') : null; if (!cv) return;
  e.preventDefault();
  const r = cv.getBoundingClientRect(), vp = fc.vp;
  const k = Math.max(.25, Math.min(2.4, vp.k * (e.deltaY < 0 ? 1.09 : 1/1.09)));
  const px = e.clientX - r.left, py = e.clientY - r.top;
  fc.vp = {k, x: px - (px - vp.x)*(k/vp.k), y: py - (py - vp.y)*(k/vp.k)}; fcApply();
}, {passive:false});

// ---------- 사건 상세: 전체 재구성 ------------------------------------------------
function renderDetail(){
  cancelScrub();
  const r = byKey[cur.sid+'|'+cur.mode];
  const a = r.attempts[Math.min(cur.attempt, r.attempts.length-1)];
  const sc = r.scenario, fv = a.final_verdict, eq = fv.equations, g = a.gate;
  const c = a.contract.payload, o = a.observation?a.observation.payload:null,
        rl = a.inline_relay?a.inline_relay.payload:null, m = a.inline_receipt?a.inline_receipt.payload:null;
  const gt = a.ground_truth_view||{};

  const findReg = (ct)=> (a.registered||[]).find(x=>x.content_type===ct);
  const regContract = findReg('application/vnd.itx.contract+json');
  const regRelay = findReg('application/vnd.itx.relay+json');
  const regReceipt = findReg('application/vnd.itx.receipt+json');
  const regObs = findReg('application/vnd.itx.observation+json');
  const verdictEv = r.timeline.find(e=>e.kind==='verdict_issued' && e.sub===a.sub);
  const verdictAt = verdictEv ? verdictEv.t : null;
  const consumedAt = g.consumed_at;
  const detectable = a.ground_truth.detectable_by_evidence;
  const attack = a.ground_truth.attack_present;
  const harmExposed = a.metrics.harm_exposed;

  // ---- 재생 컨텍스트 계산 -------------------------------------------------------
  const legs = computeLegs(a, c, rl, m);
  const breakpoint = Math.max(60, Math.round(a.received_at*1.4/10)*10);
  const candidates = [a.sent_at, a.received_at, g.decided_at, consumedAt||0, verdictAt||0];
  const tEnd = Math.max(breakpoint+40, ...candidates) * 1.08;
  const span = (ms)=>{ const v=Math.min(Math.max(ms,0),tEnd); return v<=breakpoint ? 4+(v/breakpoint)*60 : 72+((v-breakpoint)/Math.max(1,tEnd-breakpoint))*24; };
  // 스크러버가 쓰는 역함수. 축 생략 구간(64~72%)은 breakpoint 로, 오른쪽 여백은 끝 시점으로 모은다.
  span.inv = (pct)=>{
    const q = Math.min(Math.max(pct,0),100);
    const ms = q<=4 ? 0 : q<=64 ? ((q-4)/60)*breakpoint : q<72 ? breakpoint
      : breakpoint + ((q-72)/24)*Math.max(1, tEnd-breakpoint);
    return Math.min(Math.max(ms,0), tEnd);
  };
  PB = { legs, tEnd, breakpoint, span, eq, consumedAt, verdictAt, harmExposed, detectable, attack,
         receivedAt:a.received_at, hasError: !!a.error, t: tEnd,
         fired: new Set(legs.map((_,i)=>i)), evFired: new Set(), primed: false, prev: null, fill: '',
         legArgs:[a, c, rl, m], mode: g.mode, gateAction: g.action, decidedAt: g.decided_at,
         regs:{U: regContract ? regContract.registered_at : null, R: regRelay ? regRelay.registered_at : null, M: regReceipt ? regReceipt.registered_at : null} };
  $('#tLabel').textContent = `t = ${Math.round(tEnd)} ms`;

  // ---- 홉 지도 (그래프 캔버스, 원안 마크업) ----------------------------------------
  // 이전 렌더에서 캔버스 안으로 옮겨 둔 재생 컨트롤을 먼저 꺼내 둔다 (innerHTML 교체로 사라지지 않게).
  { const pc = document.querySelector('.playctl'); if (pc && pc.parentElement && pc.parentElement.id === 'itxPlayDock') document.body.appendChild(pc); }
  const canvas = fcCanvasHtml();
  const actionCol = g.action === 'accept' ? 'pass' : g.action === 'accept_unverified' ? 'warn' : 'fail';
  const infoBar = `<div class="fcinfo"><span class="id">${esc(sc.id)}</span><span class="ti">${esc(sc.title)}</span><span class="sp"></span>
    <span class="kv">판정 <b class="${st(fv.verification_status)}">${esc(fv.verification_status)}</b></span><span class="kv">집행 <b class="${actionCol}">${esc(g.action)}</b></span>
    <span class="note">${esc(fv.completeness)} · ${esc(fv.established_assurance)}</span></div>`;
  const evidenceRegs = { U: regContract, R: regRelay, M: regReceipt };

  // ---- 시점 타임라인 (정적 마크. 재생 바는 updatePacket 이 채운다) ------------------
  // 원안의 마크: 전송 · M 서명 · 수신 · 사용 · T 판정(또는 판정 없음). 전송·수신·사용·판정은 시뮬레이션 시계의 값이고
  // M 서명은 그 사이를 상수 비율로 나눈 추정이다 — 표기를 다르게 한다.
  let marks = [
    {label:'전송', at:`${Math.round(a.sent_at)} ms`, pos:span(a.sent_at), color:'muted'},
    {label:'M 서명', at:`${Math.round(legs[4].t1)} ms · 추정`, pos:span(legs[4].t1), color:'muted'},
    {label:'수신', at:`${Math.round(a.received_at)} ms`, pos:span(a.received_at), color:'accent'},
  ];
  if (consumedAt != null) marks.push({label:'사용', at:`${Math.round(consumedAt)} ms`, pos:span(consumedAt), color:'fail'});
  marks.push(verdictAt != null
    ? {label:'T 판정', at:`${Math.round(verdictAt)} ms`, pos:span(verdictAt), color:'pass'}
    : {label:'판정 없음', at:'기한 초과', pos:span(tEnd), color:'na'});
  marks.sort((x,y)=>x.pos-y.pos);
  let lastPos=-999, row=0;
  for (const mk of marks){ row = (mk.pos-lastPos<7) ? (row===0?1:0) : 0; mk.row=row; lastPos=mk.pos; }
  const marksHtml = marks.map(mk=>`<div style="position:absolute;top:${mk.row?41:2}px;left:${mk.pos}%;transform:translateX(-50%);pointer-events:none">
    <div class="markline"></div><div class="marklabel" style="color:${CV(mk.color)}">${esc(mk.label)}</div><div class="markat">${esc(mk.at)}</div></div>`).join('');
  const harmNote = (attack && !detectable)
    ? '탐지 불가로 분류된 사건이다. 탐지율 분모에서 제외하고 그 수를 따로 적는다 — 통과 배지로 표시하지 않는다.'
    : consumedAt===null
      ? "업무 사용 없음. 이 사건에서 방어는 '경로를 차단했다' 가 아니라 '변조된 응답이 도구 실행에 쓰이기 전에 U 가 거부했다' 로 기록된다."
      : harmExposed && verdictAt!=null
        ? `소비 ${consumedAt} ms · T 판정 등록 ${verdictAt} ms. 그 사이 ${Math.max(0,verdictAt-consumedAt)} ms 동안 피해가 노출되었다. 탐지는 성공, 이 피해의 방어는 실패다.`
        : `정상 요청이 기한 내 완료되었다. 대기 비용 ${g.decided_at - g.received_at} ms.`;

  // ---- 증거 패널 -----------------------------------------------------------------
  const evRow = (key, reg)=>{
    const name = EV_NAME[key], detail = EV_DETAIL[key];
    if (!reg) return `<div class="evrow absent-row" data-ev-key="${key}">
      <span class="evdot"></span>
      <span class="evname">${name}</span><span class="evdetail">${detail}</span>
      <span class="evstate">결손 — 등록 없음</span></div>`;
    return `<div class="evrow" data-ev-reg="${reg.registered_at}" data-ev-key="${key}">
      <span class="evdot"></span>
      <span class="evname">${name}</span><span class="evdetail">${detail}</span>
      <span class="evstate">대기</span></div>`;
  };
  const evidence = evRow('U',regContract) + evRow('R',regRelay) + evRow('M',regReceipt);

  // ---- 결론 -----------------------------------------------------------------------
  const sevColor = (sv)=> sv==='violation'?'fail':sv==='contradiction'?'warn':'na';
  const codes = fv.discrepancies.length
    ? fv.discrepancies.map(d=>`<div class="codebox" style="border-color:${CV(sevColor(d.severity))}">
        <div class="mono" style="font-weight:600;color:${CV(sevColor(d.severity))}">${esc(d.code)} <span style="font-weight:400;color:${CV('muted')}">· ${esc(d.severity)}</span></div>
        <div class="small">귀속 ${esc(d.attribution)} <span class="muted">— ${esc(d.attribution_basis)}</span></div></div>`).join('')
    : `<div class="small absent">불일치 코드 없음</div>`;

  // ---- 집행 -------------------------------------------------------------------------
  const gateColor = g.action==='accept'?'pass':g.action==='accept_unverified'?'warn':g.action==='no_response'?'na':'fail';
  const lc = Object.entries(g.local_checks||{}).map(([k,v])=>{
    const c2 = v.result==='fail'?`background:${CV('card')};border:1px solid ${CV('fail')};color:${CV('fail')}`
      : v.result==='not_evaluable'?`background:${CV('card')};border:1px dashed ${CV('na')};color:${CV('na')}`
      : `background:${CV('chip')};border:1px solid ${CV('line')};color:${CV('muted')}`;
    return `<span class="mono eqchip" data-eq="${esc(k)}" style="padding:2px 6px;border-radius:4px;${c2}" title="${esc(v.reason)}">${esc(k)}</span>`;
  }).join(' ');

  // ---- 비교: bad-cell 표시는 실제 등식 결과에서 도출한다 (수기 지정 색인 없음) ------
  const eqr = (id)=> (eq[id]||{}).result;
  const isFail = (id)=> eqr(id)==='fail';
  const bad = {
    req:  { R: isFail('E2')||isFail('E4'), M: isFail('E3')||isFail('E4') },
    model:{ R: isFail('E8'), M: isFail('E8')||isFail('E9') },
    tr:   { R: isFail('E4') },
    nonce:{ R: isFail('E5'), M: isFail('E5') },
    resp: { R: isFail('E6')||isFail('E7')||isFail('E10'), M: isFail('E6'), U: isFail('E7')||isFail('E10') },
    att:  { R: isFail('E11'), M: isFail('E11'), U: isFail('E11') },
  };
  const cell = (html, isBad, isGap)=> isGap ? `<span style="color:${CV('na')};font-style:italic">결손</span>`
    : (html==null ? '<span class="absent">없음</span>'
      : isBad ? `<span style="color:${CV('fail')};font-weight:600;background:${CV('fail-soft')};padding:1px 4px;border-radius:3px">${html}</span>` : html);
  const cmp = `<div class="tablewrap"><table><thead><tr><th></th><th>U 승인 계약</th><th>R 선언 (동봉)</th><th>M 관측 (동봉 영수증)</th><th>U 실제 수신</th></tr></thead><tbody>
    <tr><th>요청 커밋</th><td class="mono">${short(c.req_commit)}</td>
      <td class="mono">${cell(rl?`in ${short(rl.in_commit)}<br>out ${short(rl.out_commit)}`:null, bad.req.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.request_commit):null, bad.req.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>모델</th><td>${esc(c.requested_model)} <span class="small muted">허용 ${esc(c.allowed_models.join(', '))} · 폴백 ${esc(c.fallback_policy)}</span></td>
      <td>${cell(rl?esc(rl.upstream_model)+' <span class="small muted">('+esc(rl.policy_decision)+')</span>':null, bad.model.R, !rl)}</td>
      <td>${cell(m?esc(m.model_id)+' <span class="small muted">'+esc(m.decision)+'</span>':null, bad.model.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>변환</th><td>${esc(c.allowed_request_transforms.join(', '))}</td>
      <td>${cell(rl?esc(rl.request_transform_id):null, bad.tr.R, !rl)}</td>
      <td class="muted small">—</td><td class="muted small">—</td></tr>
    <tr><th>nonce</th><td class="mono">${short(c.nonce)}</td>
      <td class="mono">${cell(rl?short(rl.nonce_forwarded):null, bad.nonce.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.eat_nonce):null, bad.nonce.M, !m)}</td>
      <td class="muted small">—</td></tr>
    <tr><th>응답 커밋</th><td class="muted small">—</td>
      <td class="mono">${cell(rl?`in ${short(rl.resp_in_commit)}<br>out ${short(rl.resp_out_commit)}`:null, bad.resp.R, !rl)}</td>
      <td class="mono">${cell(m?short(m.response_commit):null, bad.resp.M, !m)}</td>
      <td class="mono">${cell(o?short(o.resp_commit):null, bad.resp.U, !o)}</td></tr>
    <tr><th>시도</th><td>${esc(c.attempt_id)}</td>
      <td>${cell(rl?esc(rl.attempt_id):null, bad.att.R, !rl)}</td>
      <td>${cell(m?esc(m.attempt_id):null, bad.att.M, !m)}</td>
      <td>${cell(o?esc(o.attempt_id):null, bad.att.U, !o)}</td></tr>
    </tbody></table></div>
    <div class="small muted" style="margin-top:7px">커밋은 <span class="mono">commit(x) = H(salt ‖ H(canonical(x)))</span> 의 앞 12자다. 솔트는 로그에 올리지 않으므로 공개 원장만으로는 사전 대입이 불가능하다. 빨간 셀은 실패한 등식이 가리키는 값이며 두 칸이 다르다는 사실 자체가 가해자 확정은 아니다.</div>`;

  // ---- 등식 표 / 등록 진술 표 (기존 세부 자료, 유지) --------------------------------
  const eqRows = Object.entries(eq).map(([k,e])=>`<tr data-eq="${k}"><td><b>${k}</b> ${esc(e.title)}<div class="small muted">${esc(e.hop)}</div></td><td class="${cls(e.result)}">${e.result}</td><td>${esc(e.reason)}</td><td class="small">${(e.compared||[]).map(esc).join('<br>')}</td><td class="small muted">${esc(e.trust_grade)}</td></tr>`).join('');
  const regs = (a.registered||[]).map(x=>`<tr><td>${x.index}</td><td class="small">${esc(x.content_type.replace('application/vnd.itx.','').replace('+json',''))}</td><td class="small">${esc(x.iss.replace('urn:itx:party:',''))}</td><td>≤ ${x.registered_at} ms</td><td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';

  // ---- 시뮬레이터 사실 (증거 아님) --------------------------------------------------
  const factsHtml = `<div class="tablewrap"><table class="small"><tbody>
    <tr><th>U 가 보낸 요청</th><td>${absent(gt.request_sent&&gt.request_sent.input)}</td></tr>
    <tr><th>M 이 받은 요청</th><td>${gt.request_at_model?esc(JSON.stringify(gt.request_at_model)):'<span class="absent">null (전달되지 않음)</span>'}</td></tr>
    <tr><th>M 이 낸 응답</th><td>${absent(gt.response_from_model&&gt.response_from_model.output)}</td></tr>
    <tr><th>U 가 받은 응답</th><td>${absent(gt.response_at_user&&gt.response_at_user.output)}${gt.replayed_from?` <span class="warn">(${esc(gt.replayed_from)} 의 응답 재사용)</span>`:''}${a.response_body&&a.response_body.tool_call?` <span class="fail">도구 호출 지시 포함: ${esc(JSON.stringify(a.response_body.tool_call))}</span>`:''}</td></tr>
    </tbody></table></div>`;

  const tl = r.timeline.filter(e=>!e.sub||e.sub===a.sub||e.kind.startsWith('service')||e.actor==='T'||e.actor==='auditor'||e.actor==='sim').map(e=>{
    const mark = e.kind==='response_consumed'?'mark':e.kind==='gate_decision'?'decide':'';
    return `<tr><td class="muted">${e.seq}</td><td>${e.t}</td><td><b>${esc(e.actor)}</b></td><td class="${mark}">${esc(e.kind)}</td><td class="small mono">${esc(JSON.stringify(e.detail)).slice(0,220)}</td></tr>`;}).join('');
  const au = r.audit; const ts = r.ts;
  const anchors = au.anchors.map(x=>`<tr><td>${x.tree_size}</td><td class="mono">${short(x.anchored_root)}</td><td class="mono">${short(x.recomputed_root)}</td><td class="${x.ok?'pass':'fail'}">${esc(x.reason)}</td></tr>`).join('') || '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
  const mism = au.verdict_mismatches.map(x=>`<li><span class="mono">${short(x.sub)}</span> T: <b>${esc(x.t_verdict?x.t_verdict.verification_status:'없음')}</b> [${esc((x.t_verdict?x.t_verdict.codes:[]).join(', '))}] → 재계산: <b>${esc(x.recomputed.verification_status)}</b> [${esc(x.recomputed.codes.join(', '))}]</li>`).join('');
  const unauth = (au.unauthenticated_verdicts||[]).map(x=>`<li><span class="mono">${short(x.sub)}</span> #${x.log_index} <b>${esc(x.iss)}</b>: ${esc(x.problem)}</li>`).join('');
  const drops = Object.entries(ts.queue_drops).map(([k,v])=>`${k}: ${v.length}`).join(' · ');
  const swimlane = swimlaneCard(r, a, consumedAt, verdictAt, harmExposed, detectable, attack, g);
  const ledger = ledgerCard(r, a);

  $('#detail').innerHTML = `
  <div class="card">
    <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:24px;flex-wrap:wrap">
      <div><div style="font-size:16px;font-weight:700;letter-spacing:-.01em">요청 <span class="mono" style="color:${CV('muted')};font-size:14px">${esc(a.sub)}</span> · ${esc(sc.title)}</div>
      <div class="small muted" style="margin-top:3px">${esc(sc.description)}</div></div>
      <div class="badges"><span>mock_result</span><span>evaluation</span></div>
    </div>
    <p class="small" style="margin:10px 0 0"><b>시뮬레이터 사실:</b> 공격 ${attack?`있음 (${esc(a.ground_truth.attack_kind)})`:'없음'} · 증거로 탐지 ${detectable?'가능':'<b class="warn">불가 (설계상 한계)</b>'} ${a.ground_truth.note?'· '+esc(a.ground_truth.note):''}</p>
  </div>

  <div class="card"><h3>경로 — 업무 데이터 경로(실선)와 T 의 증거·통제 경로(점선)</h3>
    ${infoBar}
    ${canvas}
    <template id="itxFootTpl"><div class="playdock" id="itxPlayDock"></div>
    <div class="timebox" id="itxTimebox" data-scrub tabindex="0" role="slider" aria-label="재생 시점 탐색 — 드래그·방향키"
         aria-valuemin="0" aria-valuemax="0" aria-valuenow="0" title="클릭·드래그로 시점 이동 · ←/→ 홉 이동 · Space 재생">
      <div class="timeaxis"></div>
      <div class="timegap" style="left:66%"></div><div class="timegaplabel" style="left:68%">축 생략</div>
      <div id="itxHarmBar" class="harmbar empty" style="left:0;width:0"><span class="harmlabel">피해 노출 — 사용 이후 T 판정 전</span></div>
      ${marksHtml}
      <div id="itxPlayhead" class="playhead" style="left:0"><span class="playknob"></span></div>
      <div id="itxScrubTip" class="scrubtip" hidden></div>
    </div>
    <div class="fcev">${evidence}</div></template>
    <p class="small muted" style="margin-top:10px">${harmNote}</p>

    <div class="stripgrid" style="margin-top:14px">
      <div class="stripcell"><div class="k">정책 해시</div><div class="v">${short(fv.policy_hash)}</div></div>
      <div class="stripcell"><div class="k">검사기</div><div class="v">${esc(fv.checker_version)}</div></div>
      <div class="stripcell"><div class="k">신뢰 키 집합</div><div class="v">${esc(fv.trust_keys_version)}</div></div>
      <div class="stripcell"><div class="k">독립 재실행</div><div class="v" style="color:${au.ok?CV('pass'):CV('fail')}">${au.ok?'일치':'불일치'}</div></div>
    </div>
    <div class="small muted" style="margin-top:7px">판정은 이 네 값에 고정된다. 감사자는 로그 내보내기와 앵커만으로 같은 판정을 재계산할 수 있어야 하며, 재계산이 T 와 다르면 그 사실이 위 칸에 남는다.</div>
  </div>

  <div class="grid">
    <div class="card"><h3>결론 — 사실·모순·부족을 섞지 않는다</h3>
      <p style="margin:0 0 6px"><span class="mono" style="font-weight:700;font-size:14px;color:${CV(st(fv.verification_status))}">${fv.verification_status}</span>
        <span class="small muted" style="margin-left:10px">완전성 <b style="color:${fv.completeness==='complete'?CV('muted'):CV('na')}">${fv.completeness}</b></span>
        <span class="small muted" style="margin-left:10px">협조 ${esc(fv.cooperation_set)}</span>
        <span class="small muted" style="margin-left:10px">보증 <b>${esc(fv.established_assurance)}</b></span></p>
      ${codes}
      <ul class="tight small muted">${(fv.notes||[]).map(n=>`<li>${esc(n)}</li>`).join('')}</ul></div>
    <div class="card"><h3>집행 — 사용자 게이트 (${esc(g.mode)})</h3>
      <div class="mono" style="font-weight:700;font-size:13px;color:${CV(gateColor)}">${esc(g.action)}</div>
      <div class="small" style="margin-top:3px">${g.reasons.map(esc).join(' · ')}</div>
      <div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">${lc}</div>
      <div class="small muted" style="margin-top:8px">수신 ${g.received_at} ms → 결정 ${g.decided_at} ms (대기 ${g.waited_ms} ms) · 업무 사용 ${g.consumed_at===null?'<span class="absent">없음</span>':g.consumed_at+' ms'} ${g.consumed_before_decision?'<b class="fail">— 결정 전에 소비됨</b>':''}</div>
      ${a.live_verdict?`<div class="small muted" style="margin-top:4px">strict 모드에서 참조한 T 판정: ${esc(a.live_verdict.verification_status)} (${esc(a.live_verdict.completeness)})</div>`:''}
      ${a.error?`<div class="fail small" style="margin-top:4px">오류: ${esc(a.error)}</div>`:''}</div>
  </div>

  <div class="card"><h3>비교 — U 승인 계약 · R 선언 · M 관측 · U 실제 수신</h3>${cmp}</div>

  <div class="card"><h3>시뮬레이터가 아는 사실 (증거가 아님)</h3>${factsHtml}</div>

  <div class="grid">
    <div class="card"><h3>등식 (pass / fail / not_evaluable)</h3><div class="tablewrap"><table><thead><tr><th>등식</th><th>결과</th><th>사유</th><th>비교 대상</th><th>신뢰 등급</th></tr></thead><tbody>${eqRows}</tbody></table></div></div>
    <div class="card"><h3>등록된 진술 원장</h3><div class="tablewrap"><table><thead><tr><th>#</th><th>유형</th><th>발행</th><th>등록 시각 (상한)</th><th>진술 해시</th></tr></thead><tbody>${regs}</tbody></table></div>
      <p class="small muted">판정이 참조한 진술 ${fv.evidence_refs.length}건 · 서명 무효 ${fv.invalid_signature_refs.length}건 · 발행 권한 없음 ${(fv.unauthorized_issuer_refs||[]).length}건</p></div>
  </div>

  <div class="card"><h3>T 자기 검증과 독립 감사</h3>
    <p class="small">트리 크기 ${ts.tree_size} · 루트 <span class="mono">${short(ts.root_hash)}</span> · 등록 ${ts.submissions} / 거부 ${ts.refusals} · 큐 드롭 ${drops} · T 정지 ${ts.down_during_run?'있음':'없음'} · 추가 지연 ${ts.extra_delay_ms} ms ${ts.tampered_index!==null?`· <b class="fail">운영자가 항목 #${ts.tampered_index} 를 교체 (모사)</b>`:''}</p>
    <p>독립 재실행: <b class="${au.ok?'pass':'fail'}">${au.ok?'T 판정·트리·앵커 모두 일치':'불일치 발견'}</b> · 트리 재계산 ${au.tree_recomputed_matches_head?'<span class="pass">일치</span>':'<span class="fail">불일치</span>'} · 헤드 서명 ${au.head_signature_valid?'<span class="pass">유효</span>':'<span class="fail">무효</span>'} · 검사한 요청 ${au.subs_checked}</p>
    ${mism?`<ul class="tight small">${mism}</ul>`:''}
    ${unauth?`<p class="small fail">인증되지 않는 판정 진술 (서명·발행자 확인 실패)</p><ul class="tight small">${unauth}</ul>`:''}
    <div class="tablewrap"><table><thead><tr><th>앵커 크기</th><th>앵커 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchors}</tbody></table></div>
    <p class="small muted">${esc(au.note)}</p></div>

  ${swimlane}
  ${ledger}

  <div class="card"><h3>시간선 (시뮬레이션 ms). 붉은 행 = 업무 사용, 녹색 행 = 게이트 결정</h3><div class="scroll"><table class="tl"><thead><tr><th>#</th><th>t</th><th>주체</th><th>사건</th><th>세부</th></tr></thead><tbody>${tl}</tbody></table></div></div>`;

  // 하단 패널: 원안대로 재생 컨트롤·스크러버·증거 행을 캔버스 아래에 둔다. 컨트롤은 정적 DOM 을 옮겨 붙인다 (리스너 유지).
  { const foot = $('#itxFoot'), tpl = $('#itxFootTpl'); if (foot && tpl){ foot.appendChild(tpl.content.cloneNode(true)); tpl.remove(); }
    const pc = document.querySelector('.playctl'), dock = $('#itxPlayDock'); if (pc && dock) dock.appendChild(pc); }
  fcMount();
  updatePacket();
}

// ---------- 재생 프레임: 패킷 위치·잔상·색, 도달 펄스, 증거 도달선, 재생 헤드/피해 막대만 갱신 -----------
function pulseNode(node){
  // 캔버스의 도달 링은 fcRings 가 프레임마다 감쇠시킨다. 옛 SVG halo 가 있을 때만 1회성 펄스를 낸다.
  const el = $('#itxHalo'+node);
  if (!el) return;
  el.classList.remove('pulse'); void el.getBoundingClientRect(); el.classList.add('pulse');
}
function updatePacket(){
  if (!PB) return;
  const t = PB.t, lastLeg = PB.legs[PB.legs.length-1];
  const tl = $('#tLabel'); if (tl) tl.textContent = `t = ${Math.round(t)} ms · ${packetLabel(t, PB.legs)}`;
  const pos = packetPos(t, PB.legs);
  const respTampered = (PB.eq.E10||{}).result==='fail';
  const reqTampered = (PB.eq.E4||{}).result==='fail';
  let fill = 'accent';
  if (t >= lastLeg.t1) fill = 'muted';
  if (reqTampered && t>=PB.legs[1].t0 && t<PB.legs[4].t0) fill = 'fail';
  if (respTampered && t>=PB.legs[5].t0) fill = 'fail';
  const changed = fill !== PB.fill; PB.fill = fill;
  const dot = $('#itxPacket');
  if (dot){
    dot.setAttribute('cx', pos.x.toFixed(1)); dot.setAttribute('cy', pos.y.toFixed(1));
    if (changed){
      dot.setAttribute('fill', CV(fill));
      // 글로우는 패킷 색을 따른다. 도착해 멈춘 뒤(muted)에는 빛나지 않는다.
      dot.style.filter = fill==='muted' ? 'none' : `drop-shadow(0 0 6px ${CV(fill+'-glow')})`;
    }
  }

  const moving = t > PB.legs[0].t0 && t < lastLeg.t1;
  // 홉 구간은 추론 구간보다 10배 짧아 한 프레임에 크게 건너뛴다. 재생 중에는 그 간격만큼 꼬리를 늘려
  // 이동이 끊겨 보이지 않게 한다 — 속도를 그대로 드러내는 것이고 판정과는 무관하다.
  const jump = PB.prev ? Math.hypot(pos.x-PB.prev.x, pos.y-PB.prev.y) : 0;
  PB.prev = {x:pos.x, y:pos.y};
  const base = playing ? Math.max(22, Math.min(46, jump*1.6)) : 22; // 원안 값
  const full = (moving && !reducedMotion) ? trailLength(t, PB.legs, base) : 0;
  // 실제 SVG 그라데이션을 꼬리→패킷 방향으로 정렬하고 경로의 꺾임은 유지한다.
  const layer = $('#itxTrail'), gradient = $('#itxTrailGradient');
  if (layer && gradient){
    const pts = full>0.5 ? trailPoints(t, PB.legs, full) : [];
    layer.setAttribute('points', pts.map(q=>`${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' '));
    if (changed) gradient.style.color = CV(fill);
    if (pts.length>1){
      const tail = pts[pts.length-1];
      gradient.setAttribute('x1', String(tail[0])); gradient.setAttribute('y1', String(tail[1]));
      gradient.setAttribute('x2', String(pos.x)); gradient.setAttribute('y2', String(pos.y));
    }
    layer.style.opacity = pts.length>1 ? '1' : '0';
  }
  // 도달 링은 원안 ringFor 로 프레임마다 감쇠하고, 상태 머신 뷰는 활성 상태를 갱신한다 (하네스 vm 에는 없으므로 typeof 로 막는다).
  if (typeof fcRings === 'function') fcRings(t);
  if (typeof fcSmUpdate === 'function') fcSmUpdate(t);
  if (!reducedMotion) for (let i=0;i<PB.legs.length;i++){
    const L = PB.legs[i];
    if (L.arrive && !PB.fired.has(i) && t>=L.t1){ PB.fired.add(i); if(playing) pulseNode(L.arrive); }
  }

  // 결손 증거의 점선은 회색으로 고정한다 — 등록을 기다리는 상태(line)와 구분한다.
  for (const k of ['U','R','M']){
    const el = $('#itxEv'+k); if (!el) continue;
    const row = document.querySelector(`.evrow[data-ev-key="${k}"]`);
    const reg = row ? row.dataset.evReg : undefined;
    const missing = !row || row.classList.contains('absent-row');
    const registered = !missing && reg !== undefined && t >= +reg;
    const want = missing ? CV('na') : registered ? CV('accent') : CV('line');
    if (el.getAttribute('stroke') !== want) el.setAttribute('stroke', want);
    // 증거 제출 경로임을 업무 데이터 경로와 구분해 보인다: 재생 중이고 이미 등록된 선만 흐른다.
    el.classList.toggle('flowing', registered && playing && !reducedMotion);
    if (registered && !PB.evFired.has(k)){ PB.evFired.add(k); if (playing && PB.primed && !reducedMotion) pulseNode('T'); }
    if (!registered) PB.evFired.delete(k);
  }
  // 등록 여부는 클래스만 바꾸고 색 전이는 CSS 가 맡는다 (프레임마다 인라인 색을 쓰면 전이가 끊긴다).
  document.querySelectorAll('.evrow[data-ev-reg]').forEach(row=>{
    const reg = +row.dataset.evReg, arrived = t>=reg;
    if (row.classList.contains('arrived') === arrived) return;
    row.classList.toggle('arrived', arrived);
    // 이미 끝난 사건을 불러올 때(primed 이전)는 안착 애니메이션을 내지 않는다 — 방금 등록된 것이 아니다.
    row.classList.toggle('settling', arrived && playing && PB.primed && !reducedMotion);
    row.querySelector('.evstate').textContent = arrived ? `등록 ≤ ${reg} ms` : '대기';
  });
  PB.primed = true;
  const box = $('#itxTimebox');
  if (box){
    box.setAttribute('aria-valuemax', String(Math.round(PB.tEnd)));
    box.setAttribute('aria-valuenow', String(Math.round(t)));
    box.setAttribute('aria-valuetext', `t = ${Math.round(t)} ms · ${packetLabel(t, PB.legs)}`);
  }

  const ph = $('#itxPlayhead'); if (ph) ph.style.left = PB.span(t) + '%';
  const hb = $('#itxHarmBar');
  if (hb){
    let w = 0;
    if (PB.harmExposed && PB.detectable && PB.consumedAt!=null && PB.verdictAt!=null){
      const left = PB.span(PB.consumedAt), right = PB.span(Math.min(t, PB.verdictAt));
      w = Math.max(0, right-left);
      hb.style.left = left+'%'; hb.style.width = w+'%';
    } else { hb.style.width = '0'; }
    hb.classList.toggle('empty', w <= 1); // 라벨을 띄울 자리가 없으면 막대만 남긴다
  }
}

// ---------- 1b 스윔레인: 실제 타임라인을 U/R/M/T 레인으로 피벗한다 --------------------
const KIND_LABEL = {
  contract_signed:'계약 서명', request_sent:'요청 전송', received:'요청 수신', pre_exec_check:'실행 전 검사',
  refused:'거부', inferred:'추론 완료', receipt_issued:'영수증 발행', relay_statement_issued:'중계 진술 발행',
  modified_request:'요청 변조', transformed_request:'요청 변환', rerouted:'재라우팅', stripped_binding:'결합 정보 제거',
  modified_response:'응답 변조', collusion_forged_receipt:'공모 영수증 위조', dropped_request:'요청 드롭',
  replayed_previous_response:'이전 응답 재사용', statement_omitted:'진술 미발행', stripped_inline_receipt:'영수증 제거',
  response_received:'응답 수신', error_received:'오류 수신', gate_local_checks:'로컬 검사',
  response_consumed:'업무 사용', manifest_issued:'매니페스트 발행', verdict_requested:'T 판정 조회',
  verdict_unavailable:'T 응답 없음', verdict_deadline:'기한 도달', service_down:'T 정지', service_up:'T 복구',
  checkpoint_anchored:'앵커 고정', log_tampered:'기록 재작성', gate_decision:'게이트 결정', verdict_issued:'T 판정',
};
// 증거 등록·비공개 증거 전달 같은 배관용 이벤트는 뺀다 — 이미 '증거' 패널·원장·아래 시간선에 있다.
// 스윔레인의 목적은 서사(무엇이 언제 어느 당사자에서 일어났는가)이지 전체 로그 재현이 아니다.
function swimlaneCard(r, a, consumedAt, verdictAt, harmExposed, detectable, attack, g){
  const rows = r.timeline.filter(e=>(e.actor==='U'||e.actor==='R'||e.actor==='M'||e.actor==='T')
    && (e.sub===a.sub || (e.sub===null && e.actor==='T')) && KIND_LABEL[e.kind]!==undefined);
  const lanes = rows.map(e=>{
    let label = KIND_LABEL[e.kind] || e.kind;
    let cls = '';
    if (e.kind==='gate_decision'){ label = `게이트 ${e.detail.action}`; cls = (e.detail.action==='accept'||e.detail.action==='accept_unverified') ? '' : ''; }
    if (e.kind==='verdict_issued'){ label = attack && !detectable ? '판정 (탐지 불가)' : `T 판정 ${e.detail.status}`; }
    if (e.kind==='modified_response') cls='fail';
    if (e.kind==='modified_request') cls='fail';
    if (e.kind==='response_consumed' && harmExposed) cls='fail';
    if (e.kind==='gate_decision' && (g.action==='accept'||g.action==='accept_unverified') && attack) cls='fail';
    if (e.kind==='gate_decision' && (g.action==='quarantine'||g.action==='reject'||g.action==='reject_timeout')) cls='pass';
    return {seq:e.seq, t:e.t, actor:e.actor, label, cls};
  });
  const cell = (row, actor)=> row.actor===actor ? `<span class="${row.cls}">${esc(row.label)}</span>` : '<span class="muted">·</span>';
  const body = lanes.map(row=>`<tr><td class="muted">${row.seq}</td><td class="mono">${row.t}</td>
    <td>${cell(row,'U')}</td><td>${cell(row,'R')}</td><td>${cell(row,'M')}</td><td>${cell(row,'T')}</td></tr>`).join('');
  const gapVisible = consumedAt!==null && attack && harmExposed && verdictAt!=null;
  const tEndLocal = Math.max(consumedAt||0, verdictAt||0, 1) * 1.1;
  const gapPct = gapVisible ? Math.min(88, ((verdictAt-consumedAt)/tEndLocal)*100+6) : 0;
  const gapNote = !detectable && attack
    ? `이 사건은 증거 구조로 탐지할 수 없다 (${esc(a.ground_truth.attack_kind)}). 간격 자체가 정의되지 않는다.`
    : consumedAt===null
      ? '결정 전 소비 없음 — 간격이 0 이다. 이것이 protect·strict 가 사는 이유다.'
      : gapVisible ? `observe 모드라면 응답은 ${consumedAt} ms 에 소비되고 T 판정은 ${verdictAt} ms 에 등록된다. 이 화면의 목적은 그 간격을 숨기지 않는 것이다.`
        : '정상 사건. 소비와 판정 사이의 위험 간격 없음.';
  return `<div class="card"><h3>스윔레인 — 수집기 시퀀스 정렬</h3>
    <p class="small muted" style="margin:0 0 8px">정렬 기준은 각 당사자의 시계가 아니라 수집기가 등록한 순서(seq)다. t 는 시뮬레이션 시계이며 등록 시각은 상한으로 별도 표시된다.</p>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>seq</th><th>t ms</th><th>U</th><th>R</th><th>M</th><th style="color:${CV('accent')}">T</th></tr></thead><tbody>${body}</tbody></table></div>
    <h3>탐지 ≠ 방어</h3>
    <div class="gapbox"><div class="gapaxis"></div>
      ${gapVisible?`<div class="gapfill" style="left:4%;width:${gapPct}%"></div>`:''}
      <div class="gaplabel-l">${consumedAt===null?'소비 없음':'소비 '+consumedAt+' ms'}</div>
      <div class="gaplabel-r">${(!detectable&&attack)?'탐지 불가':verdictAt!=null?'탐지 '+verdictAt+' ms':'—'}</div>
    </div>
    <p class="small" style="margin-top:4px">${gapNote}</p></div>`;
}

// ---------- 1c 원장형: 이 사건에 등록된 진술 + 외부 앵커 ------------------------------
// 1c 재작성 재생: 셀 값은 이 실행(S14)의 실제 재작성 전·후 잎 해시와 접두 루트다. 항목 하나가 바뀌면 그 잎과
// 그 뒤의 모든 접두 루트가 차례로 바뀌고 마지막에 앵커 비교가 불일치로 넘어간다 — 연출이 아니라 값의 차이를 순서대로 보이는 것이다.
function rewriteTableHtml(rw){
  const cell = (b, a)=>`<td class="mono rw-cell" data-before="${esc(b)}" data-after="${esc(a)}">${short(b)}</td>`;
  const rows = rw.before.map((b, i)=>{ const x = rw.after[i];
    return `<tr class="rw-row${i===rw.tampered_index?' tampered':''}"><td class="muted">${i}</td><td>${esc(b.content_type.replace('application/vnd.itx.','').replace('+json',''))}</td>${cell(b.leaf_hash, x.leaf_hash)}${cell(b.prefix_root, x.prefix_root)}</tr>`; }).join('');
  const lastB = rw.before[rw.before.length-1], lastA = rw.after[rw.after.length-1];
  return `<div data-rw>
    <div class="tabrow" style="margin:10px 0 6px;gap:8px;flex-wrap:wrap"><button type="button" class="itx-btn itx-btn-accent" data-rw-play>▶ 재작성 재생</button><button type="button" class="itx-btn" data-rw-reset>앵커 시점으로 되돌리기</button>
      <span class="small muted">항목 #${rw.tampered_index} 교체 → 그 뒤 접두 루트가 차례로 바뀜 → 앵커 비교 불일치. 모든 값은 이 실행의 실제 전·후 값이다.</span></div>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>#</th><th>유형</th><th>잎 해시</th><th>접두 루트 root(0..#)</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="tablewrap" style="margin-top:8px"><table><thead><tr><th>앵커 크기</th><th>앵커에 고정된 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>
      <tr><td class="mono">${rw.anchor.tree_size}</td><td class="mono">${short(rw.anchor.root_hash)}</td>${cell(lastB.prefix_root, lastA.prefix_root)}<td class="rw-verdict" data-rw-verdict data-before="일치" data-after="앵커된 체크포인트와 다른 과거를 제시함 (기록 재작성)">일치</td></tr></tbody></table></div></div>`;
}
function ledgerRewritePlay(root, toAfter){
  const cells = [...root.querySelectorAll('.rw-cell')], verdict = root.querySelector('[data-rw-verdict]');
  const set = (c, after)=>{ const changed = after && c.dataset.after !== c.dataset.before;
    c.classList.toggle('changed', changed); c.innerHTML = short(after ? c.dataset.after : c.dataset.before) + (changed ? `<span class="old">${short(c.dataset.before)}</span>` : ''); };
  (root._rwTimers||[]).forEach(clearTimeout); root._rwTimers = [];
  if (!toAfter){ cells.forEach(c=>set(c,false)); verdict.textContent = verdict.dataset.before; verdict.classList.remove('bad'); return; }
  const changing = cells.filter(c=>c.dataset.after !== c.dataset.before);
  cells.filter(c=>c.dataset.after === c.dataset.before).forEach(c=>set(c,false));
  const step = reducedMotion ? 0 : 260;
  changing.forEach((c, i)=>root._rwTimers.push(setTimeout(()=>set(c,true), i*step)));
  root._rwTimers.push(setTimeout(()=>{ verdict.textContent = verdict.dataset.after; verdict.classList.add('bad'); }, changing.length*step));
}
function ledgerCard(r, a){
  const rows = (a.registered||[]).map(x=>`<tr><td class="muted">${x.index}</td>
    <td>${esc(x.content_type.replace('application/vnd.itx.','').replace('+json',''))}</td>
    <td class="mono">${esc(x.iss.replace('urn:itx:party:',''))}</td>
    <td class="mono">≤ ${x.registered_at}</td>
    <td class="mono">${short(x.statement_hash)}</td></tr>`).join('') || '<tr><td colspan="5" class="absent">등록된 진술 없음</td></tr>';
  const ts = r.ts;
  const anch = ts.anchor_record;
  const av = ts.anchors && ts.anchors[0];
  const anchorRow = av
    ? `<tr><td class="mono">${av.tree_size}</td><td class="mono">${short(av.anchored_root)}</td><td class="mono">${short(av.recomputed_root)}</td>
        <td class="${av.ok?'pass':'fail'}">${esc(av.reason)}</td></tr>`
    : '<tr><td colspan="4" class="absent">앵커 없음</td></tr>';
  const showTamperDemo = r.run.scenario_id !== 'S14';
  return `<div class="card"><h3>원장형 — 추가 전용 로그와 외부 앵커</h3>
    <p class="small muted" style="margin:0 0 8px">블록체인의 자리는 여기 하나다 — T 가 나중에 다른 과거를 제시하지 못하게 하는 외부 체크포인트. 이 표는 실제 등록 원장이며 임의로 값을 바꾸는 시연 버튼은 두지 않는다.</p>
    <div class="tablewrap"><table style="font-size:12px"><thead><tr><th>#</th><th>진술 유형</th><th>발행</th><th>≤ 등록</th><th>해시</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="tablewrap" style="margin-top:10px"><table><thead><tr><th>앵커 크기</th><th>앵커에 고정된 루트</th><th>현재 재계산 루트</th><th>판정</th></tr></thead><tbody>${anchorRow}</tbody></table></div>
    ${showTamperDemo
      ? `<p class="small" style="margin-top:8px">운영자가 과거 항목을 실제로 교체하면 어떻게 되는지는 <button type="button" class="ledgerlink" data-jump="S14">S14 — T 의 기록 재작성</button> 시나리오에서 그대로 볼 수 있다. 트리는 다시 계산돼 스스로는 깨지지 않지만, 앵커된 루트와 달라지고 일관성 증명이 실패한다.</p>`
      : `<p class="small fail" style="margin-top:8px">이 시나리오는 앵커 이후 항목 #${ts.tampered_index} 을 교체한 사건이다. 위 판정 칸이 '재작성 감지' 로 바뀐 것을 확인한다 — 트리 자체는 재계산돼 깨지지 않았지만 외부에 고정한 루트와 달라졌다.</p>${ts.ledger_rewrite ? rewriteTableHtml(ts.ledger_rewrite) : ''}`}
  </div>`;
}
document.addEventListener('click', e=>{
  const rw = e.target.closest('[data-rw-play],[data-rw-reset]');
  if (rw){ ledgerRewritePlay(rw.closest('[data-rw]'), rw.hasAttribute('data-rw-play')); return; }
  const btn = e.target.closest('button[data-jump]');
  if (btn){ cur.sid = btn.dataset.jump; cur.attempt = 0; onSelectionChanged(); window.scrollTo({top:0,behavior:reducedMotion?'auto':'smooth'}); $('#scenarioTabs').scrollIntoView({block:'center'}); }
});

// ---------- 1d 판정 불확실성 표현 3종 --------------------------------------------------
let curU = { sid:'S03', coop:'U' };
function renderUncertainty(){
  const rows = D.q1_matrix;
  const sids = [...new Set(rows.map(r=>r.scenario_id))];
  buildTabs($('#uncScTabs'), sids.map(s=>({v:s,label:s})), it=>it.v===curU.sid, v=>{curU.sid=v;renderUncertainty();});
  buildTabs($('#uncCoopTabs'), ['U','U+M','U+R','U+R+M'].map(c=>({v:c,label:c})), it=>it.v===curU.coop, v=>{curU.coop=v;renderUncertainty();});
  const full = rows.find(r=>r.scenario_id===curU.sid && r.cooperation==='U+R+M');
  const row = rows.find(r=>r.scenario_id===curU.sid && r.cooperation===curU.coop);
  const title = row.title;
  const establishedCodes = row.codes;
  const missingCodes = full.codes.filter(c=>!row.codes.includes(c));
  const coopSet = new Set(curU.coop.split('+'));
  const statusStyle = row.verification_status==='insufficient_evidence'
    ? `background:${CV('card')};border:1px dashed ${CV('na')};color:${CV('na')}`
    : `background:${CV('card')};border:1px solid ${CV(st(row.verification_status))};color:${CV(st(row.verification_status))}`;
  const gateStyle = (row.gate_action==='accept'||row.gate_action==='accept_unverified')
    ? `background:${CV('chip')};color:${CV('muted')}` : `background:${CV('card')};border:1px solid ${CV('fail')};color:${CV('fail')}`;

  const meter = ['U','R','M'].map(p=>`<span class="meter-sq" style="background:${coopSet.has(p)?CV('accent'):CV('card')};${coopSet.has(p)?'':'border:1px dashed '+CV('na')}"></span>`).join('');
  const missingParties = ['U','R','M'].filter(p=>!coopSet.has(p));

  const ladder = [];
  ladder.push(`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>U 가 서명한 요청 계약과 수신 진술의 자기 결합 (${esc(curU.coop)} 협조 수준에서 항상 확인 가능).</span></div>`);
  if (establishedCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag pass">확립</span><span>이 협조 수준에서 이미 드러난 위반: ${establishedCodes.map(esc).join(', ')}.</span></div>`);
  if (missingCodes.length) ladder.push(`<div class="ladder-row"><span class="ladder-tag na">미확립</span><span>이 협조 수준에서는 감춰짐: ${missingCodes.map(esc).join(', ')}. 필요한 증거: ${missingParties.map(p=>p==='R'?'R 중계 진술':'M 추론 영수증').join(', ')||'없음'}.</span></div>`);
  ladder.push(`<div class="ladder-row"><span class="ladder-tag ${(row.gate_action==='accept'||row.gate_action==='accept_unverified')?'na':'fail'}">조치</span><span>protect 정책상 게이트 결정: <span class="mono">${esc(row.gate_action)}</span>.</span></div>`);

  $('#uncertainty').innerHTML = `<div class="card"><p class="small muted" style="margin:0 0 10px">${esc(title)} — 협조 <b>${esc(curU.coop)}</b> (전체 U+R+M 결과와 비교)</p>
  <div class="grid">
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(i) 세 상태 배지 — 가장 보수적</div>
      <div class="badge3">
        <span style="${statusStyle}">${esc(row.verification_status)}</span>
        <span style="background:${CV('chip')};color:${CV('muted')}">completeness: ${esc(row.completeness)}</span>
        <span style="${gateStyle}">gate: ${esc(row.gate_action)}</span>
      </div>
      <p class="small" style="margin-top:7px">판정과 집행이 서로 다른 축임이 드러난다. 대신 "왜 부족한가" 가 안 보인다.</p></div>
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(ii) 증거 커버리지 눈금 계량기 — 실측과의 거리</div>
      <div style="display:flex;align-items:center;gap:10px">${meter}<span class="mono small">${curU.coop} 협조${missingParties.length?' · '+missingParties.map(p=>p+' 결손').join(', '):''}</span></div>
      <p class="small" style="margin-top:7px">종단 등식(E10)을 세우려면 M 영수증이 필요하다는 사실이 칸 수로 보인다. 다만 "칸이 많을수록 좋다" 로 오독될 위험이 있어 사용자 시험이 필요하다.</p></div>
    <div class="card"><div class="mono" style="font-size:10.5px;color:${CV('na')};margin:0 0 7px">(iii) 확립/미확립 서술 사다리</div>
      ${ladder.join('')}
      <p class="small" style="margin-top:7px">논문·발표에 가장 잘 읽힌다. 운영 콘솔에는 길다.</p></div>
  </div></div>`;
}

// ---------- 1e 애니메이션 메모 (정적 — 섹션 3 재생 기능의 실제 구현 여부를 함께 표기) --------
(function(){
  const IMPL = 'background:var(--chip);color:var(--pass)', PLANNED = 'background:var(--chip);color:var(--na)';
  const items = [
    {title:'그래프 캔버스 (Hopmap Console v2)', spec:'섹션 3 · Claude Design 원안', impl:true,
     body:'줌·팬 캔버스(휠·드래그·핏뷰) · 미니맵 뷰포트 드래그 · 커스텀 노드(포트 접기·펼치기, 핸들) · 인터랙티브 엣지(호버 툴팁·클릭 선택·라벨 칩) · 자동 레이아웃 전환 애니메이션(Dagre LR ↔ ELK 직교, 520ms) · 게이트 상태 머신 뷰. 원안의 대규모 노드 가상화 뷰는 넣지 않았다. 색은 판정에만 쓰고, 결손·미실행은 움직이지 않는다.'},
    {title:'요청의 이동과 진술 발행', spec:'섹션 3 재생 · sent/received 사이를 상수 비율로 나눈 추정', impl:true,
     body:'U→R→M→R→U 를 점 하나가 지난다. 구간 경계는 임의 데모 수치가 아니라 이 시도의 sent_at/received_at 과 시뮬레이션 지연 상수(홉 20ms·중개 처리 5ms·서명 2ms)에서 역산한 것이다 — 양 끝만 기록된 시각이고 그 사이 배분은 추정이며 패킷 캡처가 아니다. 이동 구간은 정지에서 출발해 정지로 끝나므로 가감속을 주고, 노드를 드나드는 수직 구간을 넣어 꺾은선 위를 실제로 타고 돈다.'},
    {title:'진행 방향 잔상', spec:'섹션 3 재생 · 20px 꼬리 + 글로우', impl:true,
     body:'점 뒤로 지나온 경로를 20px 만큼 되짚고, 꼬리 끝에서 패킷 앞단으로 불투명도가 증가하는 SVG 그라데이션을 적용한다. 패킷은 반경 6px 에 같은 색의 6px 글로우를 두르고, 꼬리는 경로의 꺾임과 구간 경계를 그대로 따라가며 노드에 머무는 동안 길이가 0 으로 줄어든다. 빠른 홉 구간에서는 프레임 간 이동량에 따라 최대 40px까지 늘린다.'},
    {title:'노드 도달 펄스', spec:'섹션 3 재생 · 1회성 fade', impl:true,
     body:'패킷이 U/R/M 상자에 닿는 순간 그 상자 바깥에만 4px 링이 300ms 동안 잦아든다 (흐름 색 accent-glow). 반복·점멸하지 않고 잔상도 남기지 않는다. 뒤로 이동하면 다시 낼 수 있게 초기화되고, 선택을 바꿔 최종 상태로 들어올 때는 내지 않는다 — 방금 일어난 일이 아니기 때문이다.'},
    {title:'변조의 순간', spec:'섹션 3 재생 · 색 전이만', impl:true,
     body:'요청 변조(E4 실패)는 R→M 구간에서, 응답 변조(E10 실패)는 M→R 구간부터 점과 꼬리의 색이 파랑에서 빨강으로 바뀐다. 폭발·흔들림 없이 색과 라벨만 바꾼다. 실제로 실패한 등식에서 색을 가져오므로 시나리오마다 자동으로 맞다.'},
    {title:'증거 제출 경로의 흐름', spec:'섹션 3 T 점선 · 대시 오프셋', impl:true,
     body:'T 로 가는 점선은 업무 데이터 경로(실선)와 다른 성격이므로, 재생 중이면서 이미 등록된 선만 대시 오프셋이 천천히 흐른다. 등록 전이거나 결손인 선은 정지해 있고, 정지·완료 상태에서는 전부 멈춘다. 증거가 T 에 닿는 순간 T 상자에 1회성 펄스를 낸다.'},
    {title:'증거 등록의 도달', spec:'섹션 3 증거 패널 · 320ms 페이드 + 안착', impl:true,
     body:'재생 시점이 각 진술의 등록 시각(상한)을 지나면 그 행과 T 로 가는 점선이 대기색에서 흐름 색(accent)으로 넘어가고 2px 만큼 제자리로 안착한다. 등록 완료는 무결성 검증 통과를 뜻하지 않는다. 상태 클래스로 전이를 제어하며 결손 행은 전이 대상에서 제외한다.'},
    {title:'임의 시점 탐색', spec:'섹션 3 시점 타임라인 · 스크러버', impl:true,
     body:'타임라인을 누르거나 끌면 그 시점으로 바로 간다. |◀ ▶| 는 홉 경계 단위로 한 걸음씩 옮기고, 속도는 ×0.5/×1/×2 로 바꾼다. 초점이 타임라인이나 재생 컨트롤에 있을 때 Space 는 재생·정지, ←/→ 는 홉 이동, Home/End 는 처음·끝이다.'},
    {title:'탐지와 소비의 간격', spec:'섹션 3 시점 타임라인 + 스윔레인(1b) 하단', impl:true,
     body:'소비 지점에서 T 판정 등록 지점까지 붉은 막대가 실제 시간 비율대로 자란다. 막대가 길수록 나쁜 것이 아니라 "무엇이 그 사이에 실행되었는가" 를 묻게 만드는 장치다.'},
    {title:'증거가 늘며 바뀌는 판정', spec:'섹션 5 (1d) · 탭 전환', impl:true,
     body:'협조 집합 탭을 U → U+M/U+R → U+R+M 으로 늘리면 같은 사건의 배지·사다리가 실제 Q1 매트릭스 값으로 바뀐다. 탭을 누를 때만 바뀌고 나머지는 정지한다 — 별도 애니메이션은 넣지 않았다.'},
    {title:'해시 체인과 외부 앵커', spec:'섹션 3 원장형(1c) · S14 재작성 재생', impl:true,
     body:'S14 에서 「재작성 재생」을 누르면 교체된 항목의 잎 해시가 먼저 바뀌고, 그 뒤의 접두 루트 root(0..#) 가 260ms 간격으로 차례로 바뀌며, 마지막에 앵커 비교 행이 불일치로 넘어간다. 셀의 값은 시뮬레이션이 재작성 직전·직후에 실제로 계산한 잎 해시와 접두 루트이고 바뀐 셀에는 이전 값이 취소선으로 남는다 — 연출용 수치는 없다. 교체 이전 항목은 움직이지 않으며, 다른 시나리오에서는 S14 로 이동하는 링크만 둔다.'},
    {title:'모드 전환', spec:'섹션 3 · 탭 전환', impl:true,
     body:'observe/protect/strict 를 바꾸면 경로와 증거는 그대로 있고 시간선의 결정·소비 표시와 게이트 패널만 바뀐다. 크로스페이드는 넣지 않았고 즉시 갱신된다 — 같은 사건에서 정책만 달라졌음을 보이는 데는 애니메이션이 굳이 필요하지 않았다.'},
  ];
  $('#animNotes').innerHTML = items.map(a=>`<div class="animnote"><div style="font:600 12.5px 'IBM Plex Sans KR',system-ui">${esc(a.title)}
    <span class="mono muted" style="font-size:11px">${esc(a.spec)}</span>
    <span class="animstatus" style="${a.impl?IMPL:PLANNED}">${a.impl?'구현됨':'미구현'}</span></div>
    <div class="small" style="color:var(--fg);line-height:1.5">${esc(a.body)}</div></div>`).join('')
    + `<p class="small muted" style="margin-top:10px;padding-top:10px;border-top:1px solid var(--line)">공통 규칙: 모션은 인과를 보이는 데만 쓰고 강조에는 쓰지 않는다. 결손·미실행은 절대 움직이지 않는다. <span class="mono">prefers-reduced-motion</span> 에서는 이 페이지의 모든 재생이 최종 상태로 즉시 점프한다.</p>`;
})();

// ---------- Q1
(function(){
  const rows = D.q1_matrix; const coops = ['U','U+M','U+R','U+R+M']; const sids = [...new Set(rows.map(r=>r.scenario_id))];
  const cell = (r)=>r?`<div class="${st(r.verification_status)}">${r.verification_status}</div><div class="small">${r.codes.length?r.codes.map(esc).join('<br>'):'<span class="absent">코드 없음</span>'}</div><div class="small muted">완전성 ${r.completeness} · 게이트 ${esc(r.gate_action)}</div>`:'-';
  $('#q1').innerHTML = `<table><thead><tr><th>위반 시나리오</th>${coops.map(c=>`<th>${c}</th>`).join('')}</tr></thead><tbody>${sids.map(s=>{const t=rows.find(r=>r.scenario_id===s).title;return `<tr><td><b>${s}</b><div class="small">${esc(t)}</div></td>${coops.map(c=>`<td>${cell(rows.find(r=>r.scenario_id===s&&r.cooperation===c))}</td>`).join('')}</tr>`;}).join('')}</tbody></table>`;
})();

// ---------- 4b T 기여: U 로컬 검증만 vs U+T ----------
(function(){
  const el = $('#tcontrib'); if (!el) return;
  const rows = D.t_contribution || [], sum = D.t_contribution_summary;
  if (!rows.length){ el.innerHTML = '<p class="small absent">이 결과 파일에는 T 기여 실험이 없다 (python run.py run 을 다시 실행).</p>'; return; }
  const ADD = {pre_execution_refusal:'실행 전 거부 (M 이 T 에서 계약 조회)', signed_detection_record:'서명·등록된 탐지 기록', audit_finding:'감사 발견 (T 오판·재작성·누락)', complete_evidence:'증거 완전성 complete', strict_block:'strict 추가 차단'};
  const gate = (c)=>`<span class="mono ${['quarantine','reject','reject_timeout'].includes(c.gate_action)?'fail':c.gate_action==='no_response'?'na':c.gate_action==='accept'?'pass':'warn'}">${esc(c.gate_action)}</span>`;
  const yn = (v)=>v===null||v===undefined?'<span class="absent">없음</span>':v?'<span class="pass">✓</span>':'<span class="na">–</span>';
  const cell = (c, t)=>`${gate(c)}<div class="small">사용 전 차단 ${yn(c.blocked_before_use)} · 실행 전 거부 ${yn(c.model_refused_before_execution)}</div>${t?`<div class="small muted">탐지 기록 ${yn(c.detected_by_verdict)} · 완전성 ${esc(c.completeness)} · 감사 발견 ${yn(c.audit_finding)}</div>`:'<div class="small muted">판정·감사 없음 (T 부재)</div>'}`;
  el.innerHTML = `<p class="small">공격 ${sum.attack_attempts}건 중 사용 전 차단: 로컬만 <b>${sum.attacks_blocked_local_only}</b> · U+T protect <b>${sum.attacks_blocked_with_t_protect}</b> (방어 동일 ${sum.defense_same_without_t}/${sum.scenarios}). T 가 더한 것 — 실행 전 거부 ${sum.pre_execution_refusal.join(', ')||'없음'} · 서명된 탐지 기록 ${sum.signed_detection_record.length}건 · 감사 발견 ${sum.audit_finding.join(', ')||'없음'} · strict 추가 차단 ${sum.strict_block.join(', ')||'없음'}.</p>
  <table><thead><tr><th>사건</th><th>(a) U 로컬만 · T 없음</th><th>(b) U+T protect</th><th>(c) U+T strict</th><th>T 가 더한 것</th></tr></thead><tbody>${rows.map(r=>`<tr><td><b>${esc(r.scenario_id)}</b>${r.attack_present?' <span class="fail small">공격</span>':''}<div class="small">${esc(r.title)}</div></td><td>${cell(r.local_only,false)}</td><td>${cell(r.with_t_protect,true)}</td><td>${cell(r.with_t_strict,true)}</td><td class="small">${r.t_adds.length?r.t_adds.map(a=>esc(ADD[a]||a)).join('<br>'):'<span class="absent">없음</span>'}</td></tr>`).join('')}</tbody></table>`;
})();

// ---------- 4c 인센티브 원장 ----------
(function(){
  const el = $('#incentives'); if (!el) return;
  const inc = D.incentives; if (!inc || !inc.summary){ el.innerHTML = '<p class="small absent">이 결과 파일에는 인센티브 원장이 없다 (python run.py run 을 다시 실행).</p>'; return; }
  const s = inc.summary, st_ = s.structural, pp = s.per_party, par = s.parametric;
  const P = ['U','R','M','T'];
  const sign = (v)=>v>0?`<span class="pass">+${v}</span>`:v<0?`<span class="fail">${v}</span>`:'<span class="na">0</span>';
  el.innerHTML = `<p class="small">구조: 부당한 책임 <b class="${st_.unjust_liability_total?'fail':'pass'}">${st_.unjust_liability_total}건</b> · 가해자 있는 공격 ${st_.attacks}건 중 분쟁 해결 ${st_.attacks_resolved}건 · 미해결 ${st_.attacks_unresolved.join(', ')||'없음'} (공모는 증거 구조가 보지 못한다) · 지목할 당사자 없음 ${st_.attacks_without_party.join(', ')||'없음'} · <span class="mono">${st_.claim_status}</span></p>
  <table><thead><tr><th>당사자</th><th>정직 행 수</th><th>정당한 책임</th><th>부당한 책임</th><th>면책</th><th>정직 참여 비용(단위)</th><th>정직 참여 편익(단위)</th><th>순편익(단위)</th></tr></thead><tbody>
  ${P.map(p=>`<tr><td><b>${p}</b></td><td>${pp[p].honest_rows}</td><td>${pp[p].just_liability}</td><td class="${pp[p].unjust_liability?'fail':'pass'}">${pp[p].unjust_liability}</td><td>${pp[p].exonerated}</td><td>${pp[p].honest_cost_units}</td><td>${pp[p].honest_benefit_units}</td><td>${sign(pp[p].honest_net_units)}</td></tr>`).join('')}
  </tbody></table>
  <p class="small muted">단위 파라미터 (<span class="mono">${par.claim_status}</span>): ${Object.entries(par.params).map(([k,v])=>`${k}=${v}`).join(' · ')}. ${esc(par.note)}</p>`;
})();

// ---------- 등식 라벨 <-> 등식표·집행 칩 양방향 연동, 해시 복사 ----------
(function(){
  let current = null;
  const mark = (id, on)=>{ if(!id) return; document.querySelectorAll(`[data-eq="${CSS.escape(id)}"]`).forEach(n=>n.classList.toggle('eq-hi', on)); };
  const point = (e)=>{
    const n = e.target && e.target.closest ? e.target.closest('[data-eq]') : null;
    const id = n ? n.dataset.eq : null;
    if (id === current) return;
    mark(current, false); current = id; mark(current, true);
  };
  document.addEventListener('mouseover', point);
  document.addEventListener('focusin', point);

  async function copyText(text){
    if (!text) return false;
    try { await navigator.clipboard.writeText(text); return true; } catch(e) {}
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.setAttribute('readonly',''); ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.select();
      const ok = document.execCommand('copy'); ta.remove(); return ok;
    } catch(e) { return false; }
  }
  const flash = (n, message)=>{
    n.dataset.flash = message; n.classList.add('copied');
    setTimeout(()=>{ n.classList.remove('copied'); delete n.dataset.flash; }, 1200);
  };
  document.addEventListener('click', e=>{
    const n = e.target && e.target.closest ? e.target.closest('[data-copy]') : null;
    if (!n) return;
    e.preventDefault();
    copyText(n.dataset.copy||'').then(ok=>flash(n, ok?'복사됨':'복사 실패'));
  });
  document.addEventListener('keydown', e=>{
    if (e.key!=='Enter' && e.key!==' ') return;
    const n = e.target && e.target.closest ? e.target.closest('[data-copy][tabindex]') : null;
    if (!n) return;
    e.preventDefault(); n.click();
  });
})();

onSelectionChanged();
renderUncertainty();
