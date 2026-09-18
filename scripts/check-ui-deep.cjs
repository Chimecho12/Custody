// 빌드된 미리보기에서 화면을 실제로 조작해 보는 점검. check-ui.cjs 의 레이아웃 점검 위에,
// 요청 실행 뒤에만 나타나는 상태(상세 탭·홉 지도 노드 메뉴·감사 결과·어두운 테마)를 확인한다.
// 네이티브 IPC 는 여기서도 흉내 내지 않는다.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {startPreviewServer} = require('./testing/preview-server.cjs');
const {viewHeight, shoot} = require('./testing/ui-shot.cjs');
const output = path.resolve(process.argv[2] || path.join(__dirname, '../artifacts/ui-deep'));
const views = ['request','history','audit','simulation','settings','deployment','evidence','standards','keys'];

// 마지막 줄에 낱말 하나만 남은 곳(고아 낱말)을 찾는다. 낱말마다 재면 느리므로
// 줄 사각형과 마지막 낱말의 폭만 비교한다.
function orphanWords() {
  const out = [];
  const selector = '.ui-title,.ui-subtitle,.ui-body,.ui-body-strong,.ui-caption,.itx-help,h1,h2,h3,h4,p,li';
  const range = document.createRange();
  for (const el of document.querySelectorAll(selector)) {
    if (!el.offsetParent) continue;
    const kids = [...el.childNodes];
    if (kids.length !== 1 || kids[0].nodeType !== 3) continue;   // 글자만 든 요소만 본다
    const node = kids[0];
    const words = [...node.textContent.matchAll(/\S+/g)];
    if (words.length < 2) continue;
    range.selectNodeContents(el);
    const lines = [...range.getClientRects()].filter(r => r.width > 0);
    if (lines.length < 2) continue;
    const lastLine = lines[lines.length - 1];
    const word = words[words.length - 1];
    range.setStart(node, word.index); range.setEnd(node, word.index + word[0].length);
    const lastWord = range.getBoundingClientRect();
    if (Math.round(lastWord.top) !== Math.round(lastLine.top)) continue;
    if (lastLine.width - lastWord.width < 2) out.push({text: node.textContent.trim().slice(0, 70), where: el.className || el.tagName.toLowerCase()});
  }
  return out;
}

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
    const checks = {};

    // ---------- 요청 한 건을 실행한다. 아래 상태는 실행 뒤에만 생긴다 ----------
    await page.locator('nav button[data-view="request"]').click();
    await page.locator('#prompt').fill('deep check run');
    await page.locator('#send').click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled
      && document.querySelector('#request-meta').textContent.trim().length > 0);
    assert.notEqual(await page.locator('#request-state').innerText(), '진행 중');

    // ---------- 상세 탭 셋: 고른 하나만 열리고 나머지는 닫힌다 ----------
    const panes = ['map','timeline','checks'];
    checks.detail_tabs = [];
    for (const tab of panes) {
      await page.locator(`[data-detail-tab="${tab}"]`).click();
      assert.equal(await page.locator(`[data-detail-pane="${tab}"]`).isVisible(), true, `detail pane ${tab} hidden`);
      assert.equal(await page.locator(`[data-detail-tab="${tab}"]`).getAttribute('aria-selected'), 'true', `detail tab ${tab} not selected`);
      for (const other of panes.filter(p => p !== tab)) {
        assert.equal(await page.locator(`[data-detail-pane="${other}"]`).isVisible(), false, `detail pane ${other} still open with ${tab}`);
      }
      const nodes = await page.locator(`[data-detail-pane="${tab}"] *`).count();
      assert.ok(nodes > 10, `detail pane ${tab} looks empty (${nodes})`);
      checks.detail_tabs.push({tab, nodes});
    }

    // ---------- 홉 지도 노드 메뉴: 열고 → 고르면 실험 조건이 바뀌고 → Escape 로 닫힌다 ----------
    await page.locator('[data-detail-tab="map"]').click();
    const head = page.locator('#route-map [data-fc-node]').first();
    await head.click();
    const menu = page.locator('#route-map [data-fc-nodemenu]');
    assert.equal(await menu.isVisible(), true, 'node menu did not open');
    const options = menu.locator('[data-fc-nodeopt]');
    const optionCount = await options.count();
    assert.ok(optionCount >= 2, `node menu has ${optionCount} options`);
    const before = await page.locator('#scenario').inputValue();
    const pick = await options.evaluateAll((els, current) =>
      els.map(e => e.dataset.fcNodeopt).find(v => v && v !== current) || null, before);
    assert.ok(pick, 'node menu offers no other scenario');
    await menu.locator(`[data-fc-nodeopt="${pick}"]`).click();
    await page.waitForFunction(v => document.querySelector('#scenario').value === v, pick, {timeout:5000});
    checks.node_menu = {options: optionCount, scenario_before: before, scenario_after: pick};
    // 고른 뒤에도 메뉴는 열린 채 남는다. Escape 는 지도 안에 초점이 있을 때만 닿으므로
    // (flow.ts 가 keydown 을 지도 뿌리에 건다) 노드 머리에 초점을 준 뒤 누른다.
    if (!await menu.isVisible()) await head.click();
    assert.equal(await menu.isVisible(), true, 'node menu is not open before Escape');
    await head.focus();
    await page.keyboard.press('Escape');
    assert.equal(await menu.isVisible(), false, 'Escape did not close the node menu');

    // ---------- 감사 실행: 빈 상태 문구가 실제 결과로 바뀐다 ----------
    await page.locator('nav button[data-view="audit"]').click();
    assert.match(await page.locator('#audit-content').innerText(), /아직 감사를 실행하지 않았습니다/);
    await page.locator('#run-audit').click();
    await page.waitForFunction(() => !/아직 감사를 실행하지 않았습니다/.test(document.querySelector('#audit-content').textContent), null, {timeout:30000});
    const cards = await page.locator('#audit-cards *').count();
    assert.ok(cards > 0, 'audit produced no cards');
    checks.audit = {cards, head: (await page.locator('#audit-content').innerText()).split('\n')[0]};

    // ---------- 어두운 테마: 배경이 실제로 바뀌는지 본다 ----------
    const light = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    for (let i = 0; i < 3 && await page.evaluate(() => document.documentElement.dataset.theme) !== 'dark'; i += 1) {
      await page.locator('#theme').click();
    }
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark', 'theme did not reach dark');
    const dark = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    assert.notEqual(dark, light, 'dark theme did not change the background');
    checks.theme = {light, dark};

    // ---------- 화면마다: 어두운 테마 그림 · 가로 넘침 · 고아 낱말 ----------
    const rows = [];
    for (const view of views) {
      await page.locator(`nav button[data-view="${view}"]`).click();
      assert.equal(await page.locator(`#view-${view}`).isVisible(), true);
      const dimensions = await page.evaluate(() => ({viewport:innerWidth, content:document.documentElement.scrollWidth}));
      assert.ok(dimensions.content <= dimensions.viewport, `horizontal overflow ${view} in dark theme`);
      const shot = await shoot(page, 1320, path.join(output, `dark-${view}.png`));
      const orphans = await page.evaluate(orphanWords);
      rows.push({view, horizontal_overflow:false, shot_height:shot.height, shot_clipped:shot.clipped, orphan_words:orphans});
    }

    assert.deepEqual(errors, []);
    // 고아 낱말은 통과·실패를 가르지 않고 세어서 남긴다. 몇 개까지 둘지는 글 쓰는 쪽의 판단이라
    // 스크립트가 정할 일이 아니고, 늘어나는 것은 이 숫자로 드러난다.
    const report = {scope:'built_browser_preview_interactions_and_dark_theme', native_ipc_tested:false,
      interactions:['request_run','detail_tabs','node_menu','audit_run','theme_cycle'],
      checks, rows, orphan_word_total: rows.reduce((n, r) => n + r.orphan_words.length, 0), errors};
    await fs.writeFile(path.join(output,'result.json'), JSON.stringify(report,null,2));
    process.stdout.write(JSON.stringify(report,null,2));
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
})().catch(error => {process.stderr.write(error.stack+'\n');process.exitCode=1;});
