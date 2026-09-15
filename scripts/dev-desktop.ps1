param([string]$Python = 'python', [string]$Pnpm, [switch]$RebuildAgent, [switch]$UiOnly)
# 개발용 실행. -UiOnly: vite 만 (브라우저 미리보기, 표본 데이터). 기본: tauri dev (앱 창 + 프런트 HMR + Rust 자동 재컴파일).
# Python Agent 는 사이드카 exe 로 실행되므로 itx/ 를 고친 뒤에는 -RebuildAgent 로 다시 패키징해야 반영된다.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = (Join-Path $projectRoot '.build\python-packages') + [IO.Path]::PathSeparator + $projectRoot
$localCargo = Join-Path $projectRoot '.toolchain\cargo'
if (Test-Path (Join-Path $localCargo 'bin\cargo.exe')) {
    $env:CARGO_HOME = $localCargo
    $env:RUSTUP_HOME = Join-Path $projectRoot '.toolchain\rustup'
    $env:Path = (Join-Path $localCargo 'bin') + ';' + $env:Path
}
if (-not $Pnpm) { $found = Get-Command pnpm -ErrorAction SilentlyContinue; if ($found) { $Pnpm = $found.Source } }
Push-Location $projectRoot
try {
    if ($RebuildAgent) {
        $transformSource = (Join-Path $projectRoot 'itx/reconcile/transforms.py') + ':itx/reconcile'
        & $Python -m PyInstaller --noconfirm --clean --onefile --name itx-agent --add-data $transformSource --distpath desktop/src-tauri/binaries --workpath .build/pyinstaller --specpath .build runtime.py
        if ($LASTEXITCODE -ne 0) { throw 'Agent packaging failed' }
        Copy-Item -LiteralPath 'desktop/src-tauri/binaries/itx-agent.exe' -Destination 'desktop/src-tauri/binaries/itx-agent-x86_64-pc-windows-msvc.exe' -Force
    }
    if (-not $UiOnly -and -not (Test-Path 'desktop/src-tauri/binaries/itx-agent-x86_64-pc-windows-msvc.exe')) {
        throw 'Agent sidecar is missing. Run again with -RebuildAgent (needs PyInstaller in .build\python-packages).'
    }
    Push-Location desktop
    try {
        if (-not (Test-Path 'node_modules')) {
            if (-not $Pnpm) { throw 'node_modules is missing and pnpm is not available. Install pnpm 11 (corepack enable pnpm) or pass -Pnpm, then rerun.' }
            & $Pnpm install --frozen-lockfile
            if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
        }
        if ($UiOnly) {
            Write-Host 'UI preview: http://127.0.0.1:1420 (browser only; runtime data comes from desktop/preview/fixtures.json if present)'
            if ($Pnpm) { & $Pnpm dev } else { & npm run dev }
        } elseif ($Pnpm) {
            # tauri.conf.json 의 beforeDevCommand('pnpm dev')가 같은 pnpm 을 찾도록 한다.
            $env:Path = (Split-Path -Parent $Pnpm) + ';' + $env:Path
            & $Pnpm exec tauri dev
        } else {
            # pnpm 없이도 이미 설치된 node_modules 로 실행한다. dev 명령만 npm 으로 바꾼다.
            & .\node_modules\.bin\tauri.cmd dev --config tauri.dev.conf.json
        }
    } finally { Pop-Location }
} finally { Pop-Location }
