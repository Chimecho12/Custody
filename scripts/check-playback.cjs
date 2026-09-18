// 홉 지도 재생을 실제로 돌려 보고 프레임을 그림으로 남기는 점검. 재생 규칙(t 는 실측 그대로,
// 홉마다 충분한 프레임)은 단위 테스트가 지키지만, 변조 사건에서만 나오는 파문·흔들림은
// 화면을 봐야 확인된다. 그 화면을 사람이 매번 띄우지 않아도 되도록 여기서 찍어 둔다.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {startPreviewServer} = require('./testing/preview-server.cjs');
const {viewHeight} = require('./testing/ui-shot.cjs');
const output = path.resolve(process.argv[2] || path.join(__dirname, '../artifacts/ui-playback'));
// 변조 사건이 기본값이다. 정상 경로는 볼 것이 적다. 미리보기는 (집행 정책, 실험 조건) 짝으로
// 표본을 찾으므로 둘을 함께 준다 — 짝이 없으면 첫 기록으로 조용히 빠지기 때문에 아래에서 확인한다.
const scenario = process.argv[3] || 'request_tamper';
const mode = process.argv[4] || 'strict';
const shots = 8;

(async () => {
  await fs.mkdir(output, {recursive:true});
  const server = await startPreviewServer();
  let browser;
  try {
    const channel = process.env.ITX_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
    browser = await chromium.launch({headless:true, ...(channel ? {channel} : {})});
    const page = await browser.newPage({viewport:{width:1320,height:viewHeight}, deviceScaleFactor:1});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    await page.goto(server.url, {waitUntil:'networkidle'});

    // ---------- 고른 사건으로 요청 한 건 ----------
    await page.locator('nav button[data-view="request"]').click();
    // 표본에 그 짝이 있는지 먼저 본다. 없으면 화면은 다른 기록을 아무 말 없이 보여 준다.
    const want = await page.evaluate(async ([m, s]) => {
      const f = await (await fetch('/preview-data/fixtures.json')).json();
      const found = f.history.find(r => r.mode === m && (r.lab_scenario || 'normal') === s);
      if (!found) return null;
      return {failing: Object.entries(found.checks || {}).filter(([, c]) => c.result === 'fail').map(([id]) => id)};
    }, [mode, scenario]);
    assert.ok(want, `미리보기 표본에 ${mode}/${scenario} 기록이 없습니다 (scripts/make-preview-fixtures.py)`);
    await page.selectOption('#mode', mode);
    await page.selectOption('#scenario', scenario);
    assert.equal(await page.locator('#scenario').inputValue(), scenario, `scenario ${scenario} not selected`);
    await page.locator('#prompt').fill(`playback check · ${scenario}`);
    await page.locator('#send').click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled
      && document.querySelector('#request-meta').textContent.trim().length > 0);
    const verdict = (await page.locator('#request-state').innerText()).trim();
    // 표본에서 실패한 검사가 화면에도 그대로 뜨는지 본다. 짝이 어긋나 다른 기록으로 빠지면
    // 이 줄이 없거나 다른 항목이 적히므로, 조용한 대체를 여기서 잡는다.
    if (want.failing.length) {
      await page.locator('[data-detail-tab="checks"]').click();
      const details = await page.locator('#result-details').innerText();
      assert.match(details, /로컬 검증 실패/, `${mode}/${scenario} 표본이 아닌 기록이 떴습니다 (판정: ${verdict})`);
      for (const id of want.failing) assert.ok(details.includes(id), `화면에 실패 검사 ${id} 가 없습니다`);
    }

    // ---------- 재생: 프레임마다 오는 t 를 모은다 (재생 엔진이 직접 보내는 값이다) ----------
    await page.locator('[data-detail-tab="map"]').click();
    await page.evaluate(() => {
      window.__frames = [];
      document.addEventListener('playbackframe', e => window.__frames.push({t: e.detail.t, playing: e.detail.playing}));
    });
    const scrub = page.locator('[data-scrub]').first();
    const span = Number(await scrub.getAttribute('aria-valuemax'));
    assert.ok(span > 0, `scrubber has no span (aria-valuemax=${span})`);
    await page.locator('[data-play]').first().click();

    // 재생이 끝날 때까지 기다리며 고르게 찍는다. 끝은 엔진이 playing:false 로 알려 준다.
    // 지도 요소가 아니라 보이는 화면을 찍는다 — 사람이 보는 것과 같은 그림이어야 비교가 된다.
    const map = page.locator('#route-map');
    await map.scrollIntoViewIfNeeded();
    for (let i = 0; i < shots; i += 1) {
      await page.screenshot({path: path.join(output, `${scenario}-${String(i).padStart(2,'0')}.png`)});
      const done = await page.evaluate(() => {
        const f = window.__frames;
        return f.length > 0 && f[f.length - 1].playing === false;
      });
      if (done) break;
      await page.waitForTimeout(600);
    }
    await page.waitForFunction(() => {
      const f = window.__frames;
      return f.length > 0 && f[f.length - 1].playing === false;
    }, null, {timeout:60000});
    await page.screenshot({path: path.join(output, `${scenario}-end.png`)});

    const frames = await page.evaluate(() => window.__frames.map(f => f.t));
    assert.ok(frames.length >= 28, `playback produced only ${frames.length} frames`);
    const backwards = frames.findIndex((t, i) => i > 0 && t < frames[i-1]);
    assert.equal(backwards, -1, `playback time went backwards at frame ${backwards}`);
    // 마지막 프레임은 스크러버가 알리는 구간 끝과 같아야 한다. 화면의 t 는 실측 그대로라는 주장이 여기서 확인된다.
    assert.ok(Math.abs(frames[frames.length-1] - span) <= 1, `playback ended at ${frames[frames.length-1]} ms, span is ${span} ms`);
    assert.deepEqual(errors, []);

    const report = {scope:'built_browser_preview_hop_map_playback', native_ipc_tested:false,
      scenario, mode, verdict, failing_checks: want.failing, span_ms: span, frames: frames.length,
      first_t: frames[0], last_t: frames[frames.length-1], shots_written: Math.min(shots, frames.length) + 1, errors};
    await fs.writeFile(path.join(output,'result.json'), JSON.stringify(report,null,2));
    process.stdout.write(JSON.stringify(report,null,2));
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
})().catch(error => {process.stderr.write(error.stack+'\n');process.exitCode=1;});
