// Execute local TypeScript modules with their real relative imports and per-load cache.
const {existsSync, readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../desktop/node_modules/typescript');

// context 를 넘기면 그 컨텍스트에서, 넘기지 않으면 현재 realm 에서 실행한다. 반환한 객체를
// deepEqual 로 비교하는 테스트는 넘기지 않아야 한다 — 별도 컨텍스트는 프로토타입이 달라 비교가 어긋난다.
function loadTypeScript(entry, context) {
  const cache = new Map();
  function load(filename) {
    const absolute = path.resolve(filename);
    const resolved = [absolute + '.ts', path.join(absolute, 'index.ts'), absolute]
      .find(candidate => candidate.endsWith('.ts') && existsSync(candidate));
    if (!resolved) throw new Error(`TypeScript module not found: ${absolute}`);
    if (cache.has(resolved)) return cache.get(resolved).exports;
    const module_ = {exports: {}};
    cache.set(resolved, module_);
    const source = ts.transpileModule(readFileSync(resolved, 'utf8'), {
      compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS},
    }).outputText;
    const wrapped = `(function (module, exports, require) {${source}\n})`;
    const run = context ? vm.runInContext(wrapped, context, {filename: resolved})
      : vm.runInThisContext(wrapped, {filename: resolved});
    run(module_, module_.exports, request => {
      if (!request.startsWith('.')) throw new Error(`Unexpected external import: ${request}`);
      return load(path.resolve(path.dirname(resolved), request));
    });
    return module_.exports;
  }
  return load(entry);
}

module.exports = {loadTypeScript};
