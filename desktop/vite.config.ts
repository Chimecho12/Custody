import { defineConfig, type Plugin } from 'vite';
import { createReadStream, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import manifest from './preview-data.json';

// Dev server only: exposes the last simulation bundle and optional runtime fixtures so the UI can be
// inspected in a plain browser. The production build never includes this and never reads artifacts/.
function previewData(): Plugin {
  const here = fileURLToPath(new URL('.', import.meta.url));
  const sources = Object.fromEntries(
    Object.entries(manifest as Record<string, string>)
      .filter(([url]) => url.startsWith('/'))
      .map(([url, file]) => [url, here + file]));
  return {
    name: 'itx-preview-data',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const file = sources[(req.url || '').split('?')[0]];
        if (!file) { next(); return; }
        if (!existsSync(file)) { res.statusCode = 404; res.end(); return; }
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        createReadStream(file).pipe(res);
      });
    },
  };
}

export default defineConfig({
  plugins: [previewData()],
  clearScreen: false,
  // style.css 가 ../../ui/ 의 공통 스타일시트를 @import 한다 (보고서와 같은 원본).
  server: { fs: { allow: ['..'] } },
});
