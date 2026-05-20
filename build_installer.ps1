param(
    [switch]$SkipInstall,
    [switch]$SkipPyInstaller,
    [switch]$SkipInno
)

$ErrorActionPreference = "Stop"
$AppRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $AppRoot

New-Item -ItemType Directory -Force -Path "release" | Out-Null

if (-not $SkipInstall) {
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    python -m pip install pyinstaller
}

if (-not $SkipPyInstaller) {
    pyinstaller --noconfirm --clean Crux.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}

$PortableZip = Join-Path $AppRoot "release\Crux-portable-windows.zip"
if (Test-Path $PortableZip) {
    Remove-Item -LiteralPath $PortableZip -Force
}
if (-not (Test-Path "dist\Crux")) {
    throw "dist\Crux was not created. Run PyInstaller before packaging."
}
Compress-Archive -Path "dist\Crux\*" -DestinationPath $PortableZip -Force
Write-Host "Portable package: $PortableZip"

if (-not $SkipInno) {
    $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if (-not $iscc) {
        $iscc = Get-Command iscc.exe -ErrorAction SilentlyContinue
    }

    if ($iscc) {
        & $iscc.Source "installer\crux.iss"
        Write-Host "Inno installer output: $(Join-Path $AppRoot 'release')"
    } else {
        Write-Host "Inno Setup compiler was not found. Install Inno Setup and rerun this script to create CruxSetup-0.1.0.exe."
    }
}
