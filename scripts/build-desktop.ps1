param([string]$Python = 'python', [string]$Pnpm = 'pnpm', [switch]$SkipAgent, [switch]$NoBundle,
      [string]$SigningConfig, [string]$AgentSignScript)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([bool]$SigningConfig -ne [bool]$AgentSignScript) {
    throw 'Signed builds require both -SigningConfig (Tauri JSON) and -AgentSignScript (PowerShell script taking one binary path).'
}
if ($SigningConfig) {
    $SigningConfig = (Resolve-Path -LiteralPath $SigningConfig).Path
    $AgentSignScript = (Resolve-Path -LiteralPath $AgentSignScript).Path
    if ([IO.Path]::GetExtension($AgentSignScript) -ne '.ps1') { throw 'Agent signer must be an explicitly supplied .ps1 file' }
}
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
    }
    if ($SigningConfig) {
        & $AgentSignScript (Join-Path $projectRoot 'desktop/src-tauri/binaries/itx-agent.exe')
        if (-not $? -or (Get-AuthenticodeSignature -LiteralPath 'desktop/src-tauri/binaries/itx-agent.exe').Status -ne 'Valid') {
            throw 'Agent code signature is not valid; packaging stopped'
        }
    }
    Copy-Item -LiteralPath 'desktop/src-tauri/binaries/itx-agent.exe' -Destination 'desktop/src-tauri/binaries/itx-agent-x86_64-pc-windows-msvc.exe' -Force
    Push-Location desktop
    try {
        & $Pnpm install --frozen-lockfile
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency install failed' }
        # The resolved pnpm launcher must also be visible to Tauri beforeBuildCommand.
        $pnpmCommand = Get-Command $Pnpm
        $env:Path = (Split-Path -Parent $pnpmCommand.Source) + ';' + $env:Path
        $tauriArguments = @('exec', 'tauri', 'build')
        if ($NoBundle) { $tauriArguments += '--no-bundle' }
        if ($SigningConfig) { $tauriArguments += @('--config', $SigningConfig) }
        & $Pnpm @tauriArguments
        if ($LASTEXITCODE -ne 0) { throw 'Tauri build failed' }
        if ($SigningConfig) {
            $version = (Get-Content package.json -Raw | ConvertFrom-Json).version
            $signedTargets = @('src-tauri/target/release/itx-desktop.exe')
            if (-not $NoBundle) { $signedTargets += "src-tauri/target/release/bundle/nsis/itx_${version}_x64-setup.exe" }
            foreach ($signedTarget in $signedTargets) {
                if ((Get-AuthenticodeSignature -LiteralPath $signedTarget).Status -ne 'Valid') { throw "Invalid release signature: $signedTarget" }
            }
        }
    } finally { Pop-Location }
} finally { Pop-Location }
