// 브라우저 미리보기(Tauri 없음)에서만 쓰는 데이터 공급. 개발 서버의 /preview-data/* 를 읽는다.
// 표본임을 화면에 항상 표시하며, 실행·서명·파일 저장이 필요한 작업은 거부한다.
type Data = Record<string, any>;

let bundle: Promise<Data | null> | null = null;
let fixtures: Promise<Data | null> | null = null;

async function json(url: string): Promise<Data | null> {
  try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch { return null; }
}
function compactRow(r: Data): Data {
  const last = r.attempts[r.attempts.length - 1], fv = last.final_verdict;
  return {scenario_id: r.run.scenario_id, mode: r.run.mode, verification_status: fv.verification_status, completeness: fv.completeness,
          codes: fv.discrepancies.map((d: Data) => d.code), gate_action: last.gate.action, attack_present: last.metrics.attack_present,
          attempts: r.attempts.length, audit_ok: r.audit.ok, verdict_mismatches: r.audit.verdict_mismatches.length,
          anchors_ok: r.audit.anchors.every((a: Data) => a.ok)};
}
const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export async function previewCall(operation: string, args: Data): Promise<any> {
  if (operation === 'simulation_matrix' || operation === 'simulation') {
    bundle ??= json('/preview-data/results.json');
    const b = await bundle;
    if (!b) throw new Error('미리보기 데이터가 없습니다. 먼저 python run.py run 으로 artifacts/results.json 을 만드세요.');
    if (operation === 'simulation') {
      const r = b.results.find((x: Data) => x.run.scenario_id === args.scenario && x.run.mode === args.mode);
      if (!r) throw new Error('unknown scenario');
      return r;
    }
    return {generated_with: b.generated_with, scenarios: b.scenarios, q1_matrix: b.q1_matrix, summary: b.summary, rows: b.results.map(compactRow)};
  }
  fixtures ??= json('/preview-data/fixtures.json');
  const f = await fixtures;
  if (!f) throw new Error(`브라우저 미리보기에는 런타임 표본이 없습니다 (scripts/make-preview-fixtures.py). '${operation}' 은 설치형 앱에서 실행하세요.`);
  if (operation === 'request') {
    await wait(700);
    const found = f.history.find((r: Data) => r.mode === args.mode && (r.lab_scenario || 'normal') === args.scenario) || f.history[0];
    if (!found) throw new Error('표본에 요청 기록이 없습니다.');
    return found;
  }
  if (operation === 'refresh') {
    const found = f.history.find((r: Data) => r.sub === args.sub);
    if (!found) throw new Error('unknown request');
    return found;
  }
  if (operation in f) return f[operation];
  throw new Error(`브라우저 미리보기에서는 '${operation}' 을 실행할 수 없습니다. 설치형 앱에서 사용하세요.`);
}
