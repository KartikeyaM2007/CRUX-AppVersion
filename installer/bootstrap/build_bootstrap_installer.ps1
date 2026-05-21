param(
    [string]$Output = "$PSScriptRoot\..\..\release\CruxSetup.exe"
)

$ErrorActionPreference = "Stop"

$bootstrapDir = $PSScriptRoot
$releaseDir = Split-Path -Parent $Output
New-Item -ItemType Directory -Force -Path $releaseDir | Out-Null

$sedPath = Join-Path $bootstrapDir "CruxSetup.sed"
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
$resolvedSource = [System.IO.Path]::GetFullPath($bootstrapDir)

$sed = @"
[Version]
Class=IEXPRESS
SEDVersion=3
[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=1
HideExtractAnimation=0
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=This will install Crux Desktop for the current Windows user.
DisplayLicense=
FinishMessage=Crux Setup finished.
TargetName=$resolvedOutput
FriendlyName=Crux Setup
AppLaunched=LaunchInstaller.cmd
PostInstallCmd=<None>
AdminQuietInstCmd=LaunchInstaller.cmd
UserQuietInstCmd=LaunchInstaller.cmd
SourceFiles=SourceFiles
[Strings]
FILE0="LaunchInstaller.cmd"
FILE1="Install-Crux.ps1"
[SourceFiles]
SourceFiles0=$resolvedSource
[SourceFiles0]
%FILE0%=
%FILE1%=
"@

$sed | Set-Content -LiteralPath $sedPath -Encoding ASCII

$iexpress = Join-Path $env:WINDIR "System32\iexpress.exe"
if (-not (Test-Path $iexpress)) {
    throw "iexpress.exe was not found."
}

& $iexpress /N /Q $sedPath
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) {
    throw "IExpress failed with exit code $LASTEXITCODE."
}

if (-not (Test-Path -LiteralPath $resolvedOutput)) {
    throw "IExpress did not create $resolvedOutput."
}

Get-Item -LiteralPath $resolvedOutput
