// Visual/layout check of the built browser preview; this does not emulate native IPC.
const {chromium} = require('playwright');
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../desktop/dist');
const output = path.resolve(process.argv[2] || path.join(__dirname, '../artifacts/ui-v0.3'));

(async () => {
  await fs.mkdir(output, {recursive:true});
  const server = http.createServer(async (request,response) => {
    try {
      const url = new URL(request.url, 'http://localhost');
      if (url.pathname === '/favicon.ico') {response.writeHead(204).end(); return;}
      const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname)));
      if (!file.startsWith(root + path.sep)) {response.writeHead(403).end(); return;}
      const type = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css'}[path.extname(file)] || 'application/octet-stream';
      response.writeHead(200, {'Content-Type':type}).end(await fs.readFile(file));
    } catch {response.writeHead(404).end();}
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    const channel = process.env.ITX_BROWSER_CHANNEL || (process.platform === 'win32' ? 'msedge' : undefined);
    browser = await chromium.launch({headless:true, ...(channel ? {channel} : {})});
    const page = await browser.newPage({viewport:{width:1320,height:920}, deviceScaleFactor:1});
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    page.on('console', m => {if (m.type() === 'error') errors.push(m.text());});
    await page.goto(`http://127.0.0.1:${server.address().port}`, {waitUntil:'networkidle'});
    assert.match(await page.locator('#source').innerText(), /미리보기/);
    const rows = [];
    for (const width of [1320,900]) {
      await page.setViewportSize({width,height:920});
      for (const view of ['request','history','audit','simulation','settings','deployment','evidence']) {
        await page.locator(`nav button[data-view="${view}"]`).click();
        assert.equal(await page.locator(`#view-${view}`).isVisible(), true);
        const dimensions = await page.evaluate(() => ({viewport:innerWidth,content:document.documentElement.scrollWidth}));
        assert.ok(dimensions.content <= dimensions.viewport, `horizontal overflow ${view} at ${width}`);
        if (['deployment','evidence'].includes(view)) {
          await page.screenshot({path:path.join(output,`${view}-${width}.png`),fullPage:true});
        }
        rows.push({view,width,horizontal_overflow:false});
      }
    }
    assert.equal(await page.locator('#retention-apply').isDisabled(), true);
    assert.deepEqual(errors, []);
    const report = {scope:'built_browser_preview_layout_only',native_ipc_tested:false,rows,errors};
    await fs.writeFile(path.join(output,'result.json'), JSON.stringify(report,null,2));
    process.stdout.write(JSON.stringify(report,null,2));
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => {process.stderr.write(error.stack+'\n');process.exitCode=1;});
