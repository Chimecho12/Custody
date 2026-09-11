param([string]$Python = 'python', [string]$Pnpm = 'pnpm', [switch]$SkipAgent, [switch]$NoBundle)
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
Push-Location $projectRoot
try {
    if (-not $SkipAgent) {
        # The checker hashes the published transform source via inspect.getsource.
        $transformSource = (Join-Path $projectRoot 'itx/reconcile/transforms.py') + ':itx/reconcile'
        & $Python -m PyInstaller --noconfirm --clean --onefile --name itx-agent --add-data $transformSource --distpath desktop/src-tauri/binaries --workpath .build/pyinstaller --specpath .build runtime.py
        if ($LASTEXITCODE -ne 0) { throw 'Agent packaging failed' }
        Copy-Item -LiteralPath 'desktop/src-tauri/binaries/itx-agent.exe' -Destination 'desktop/src-tauri/binaries/itx-agent-x86_64-pc-windows-msvc.exe' -Force
    }
    Push-Location desktop
    try {
        & $Pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
        # The resolved pnpm launcher must also be visible to Tauri beforeBuildCommand.
        $pnpmCommand = Get-Command $Pnpm
        $env:Path = (Split-Path -Parent $pnpmCommand.Source) + ';' + $env:Path
        if ($NoBundle) { & $Pnpm exec tauri build --no-bundle } else { & $Pnpm exec tauri build }
        if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed' }
    } finally { Pop-Location }
} finally { Pop-Location }
