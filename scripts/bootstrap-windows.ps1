$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolsRoot = Join-Path $projectRoot '.toolchain'
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
$env:RUSTUP_HOME = Join-Path $toolsRoot 'rustup'
$env:CARGO_HOME = Join-Path $toolsRoot 'cargo'
$rustInstaller = Join-Path $toolsRoot 'rustup-init.exe'
if (-not (Test-Path (Join-Path $env:CARGO_HOME 'bin\cargo.exe'))) {
    Invoke-WebRequest -Uri 'https://static.rust-lang.org/rustup/dist/x86_64-pc-windows-msvc/rustup-init.exe' -OutFile $rustInstaller
    & $rustInstaller -y --default-host x86_64-pc-windows-msvc --profile minimal --no-modify-path
    if ($LASTEXITCODE -ne 0) { throw 'Rust installation failed' }
}
$vsRoot = Join-Path $toolsRoot 'msvc'
if (-not (Test-Path (Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'))) {
    $vsInstaller = Join-Path $toolsRoot 'vs_BuildTools.exe'
    Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile $vsInstaller
    $signature = Get-AuthenticodeSignature -LiteralPath $vsInstaller
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Microsoft Corporation') {
        throw 'Microsoft installer signature verification failed'
    }
    $installArgs = @('--quiet', '--wait', '--norestart', '--nocache', '--installPath', ('"' + $vsRoot + '"'), '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended')
    $process = Start-Process -FilePath $vsInstaller -ArgumentList $installArgs -WindowStyle Hidden -PassThru -Wait
    if ($process.ExitCode -notin @(0,3010)) { throw "C++ Build Tools failed: $($process.ExitCode)" }
}
Write-Output 'Rust and Windows C++ build tools are ready.'
