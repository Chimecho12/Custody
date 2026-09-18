// Execute local TypeScript modules with their real relative imports and per-load cache.
const {existsSync, readFileSync} = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../../desktop/node_modules/typescript');

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
