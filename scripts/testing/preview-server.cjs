// 빌드된 브라우저 미리보기(desktop/dist)를 내는 정적 서버. UI 점검 스크립트들이 같은 표를 읽게 한다.
const fs = require('node:fs/promises');
const path = require('node:path');
const http = require('node:http');
const root = path.resolve(__dirname, '../../desktop/dist');
const desktopDir = path.resolve(__dirname, '../../desktop');
// vite 개발 서버와 같은 미리보기 데이터를 낸다. 표는 desktop/preview-data.json 하나만 둔다.
const preview = Object.fromEntries(Object.entries(require('../../desktop/preview-data.json'))
  .filter(([url]) => url.startsWith('/'))
  .map(([url, file]) => [url, path.resolve(desktopDir, file)]));

async function startPreviewServer() {
  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, 'http://localhost');
      if (url.pathname === '/favicon.ico') {response.writeHead(204).end(); return;}
      const served = preview[url.pathname];
      const file = served || path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname)));
      if (!served && !file.startsWith(root + path.sep)) {response.writeHead(403).end(); return;}
      const type = {'.html':'text/html; charset=utf-8','.js':'text/javascript','.css':'text/css','.json':'application/json; charset=utf-8'}[path.extname(file)] || 'application/octet-stream';
      // 먼저 읽고 나서 헤더를 쓴다. 순서가 반대면 없는 파일 요청 하나에 catch 가 두 번째 writeHead 를 불러 서버가 죽는다.
      const body = await fs.readFile(file);
      response.writeHead(200, {'Content-Type':type}).end(body);
    } catch {if (!response.headersSent) response.writeHead(404); response.end();}
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  return {url: `http://127.0.0.1:${server.address().port}`,
    close: () => new Promise(resolve => server.close(resolve))};
}

module.exports = {startPreviewServer};
