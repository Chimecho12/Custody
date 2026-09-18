// Visual/layout check of the built browser preview; this does not emulate native IPC.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const {startPreviewServer} = require('./testing/preview-server.cjs');
const {viewHeight, shoot} = require('./testing/ui-shot.cjs');
const output = path.resolve(process.argv[2] || path.join(__dirname, '../artifacts/ui-v0.3'));
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
    // 표본 데이터로 도는 화면이라는 표시는 #agent-status 에 있다. #source 는 그 표본이 나온 환경을 말한다.
    assert.match(await page.locator('#agent-status').innerText(), /미리보기/);
    assert.match(await page.locator('#source').innerText(), /TLS 실험실|연결 모드/);
    const rows = [];
    for (const width of [1320,900]) {
      await page.setViewportSize({width,height:viewHeight});
      for (const view of ['request','history','audit','simulation','settings','deployment','evidence','standards','keys']) {
        await page.locator(`nav button[data-view="${view}"]`).click();
        assert.equal(await page.locator(`#view-${view}`).isVisible(), true);
        const dimensions = await page.evaluate(() => ({viewport:innerWidth,content:document.documentElement.scrollWidth}));
        assert.ok(dimensions.content <= dimensions.viewport, `horizontal overflow ${view} at ${width}`);
        // 모든 화면을 찍는다. 레이아웃 회귀는 숫자로는 안 보이고 그림으로만 보인다.
        const shot = await shoot(page, width, path.join(output,`${view}-${width}.png`));
        rows.push({view,width,horizontal_overflow:false,shot_height:shot.height,shot_clipped:shot.clipped});
      }
    }
    assert.equal(await page.locator('#retention-apply').isDisabled(), true);
    // Exercise controller boundaries: request -> history -> investigation -> history.
    await page.locator('nav button[data-view="request"]').click();
    await page.locator('#prompt').fill('controller regression check');
    await page.locator('#send').click();
    await page.waitForFunction(() => !document.querySelector('#send').disabled
      && document.querySelector('#request-meta').textContent.trim().length > 0);
    assert.notEqual(await page.locator('#request-state').innerText(), '진행 중');
    await page.locator('nav button[data-view="history"]').click();
    await page.locator('#history-content button').first().click();
    assert.equal(await page.locator('#view-request').isVisible(), true);
    assert.equal(await page.locator('#request-title').innerText(), '사건 조사');
    await page.locator('#back-to-log').click();
    assert.equal(await page.locator('#view-history').isVisible(), true);
    await page.locator('#history-query').fill('missing-request-refactor-check');
    assert.match(await page.locator('#history-count').innerText(), /^0 \/ /);
    await page.locator('#history-clear').click();
    assert.ok(await page.locator('#history-content button').count() > 0);
    await page.locator('nav button[data-view="deployment"]').click();
    await page.locator('#deploy-next').click();
    assert.equal(await page.locator('[data-step-tab="propose"]').getAttribute('class').then(c => c.includes(' on')), true);
    await page.locator('#deploy-prev').click();
    assert.equal(await page.locator('#deploy-prev').isDisabled(), true);
    assert.deepEqual(errors, []);
    const report = {scope:'built_browser_preview_layout_and_controllers',native_ipc_tested:false,
      interactions:['request','history_filter','history_inspection','deployment_steps'],rows,errors};
    await fs.writeFile(path.join(output,'result.json'), JSON.stringify(report,null,2));
    process.stdout.write(JSON.stringify(report,null,2));
  } finally {
    if (browser) await browser.close();
    await server.close();
  }
})().catch(error => {process.stderr.write(error.stack+'\n');process.exitCode=1;});
