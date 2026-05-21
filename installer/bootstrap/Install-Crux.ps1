param(
    [string]$InstallDir = "$env:LOCALAPPDATA\Programs\Crux",
    [string]$UseLocalZip = "",
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"

$ReleaseBase = "https://github.com/KartikeyaM2007/CRUX-AppVersion/releases/download/v1.0.0"
$PartFiles = @(
    @{
        Name = "Crux-portable-windows.zip.part001"
        Url = "$ReleaseBase/Crux-portable-windows.zip.part001"
        Sha256 = "A9A833A7A5312E99BC90CC5FE09776D691F0C8B1E7390B8D6640E98305A9176D"
    },
    @{
        Name = "Crux-portable-windows.zip.part002"
        Url = "$ReleaseBase/Crux-portable-windows.zip.part002"
        Sha256 = "6E333AFF61730F77F998A033A1F1F441CE5A743CFC35C1BA0FECFAF8D03E5469"
    }
)
$ZipSha256 = "E8B720A7B2375803DA3B573570D7E818A5A3B006D977093B81628234ED714067"

function Write-Step($Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Green
}

function Assert-Hash($Path, $Expected) {
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($actual -ne $Expected.ToUpperInvariant()) {
        throw "Checksum failed for $Path. Expected $Expected but got $actual."
    }
}

function Download-File($Url, $OutputPath) {
    Write-Host "Downloading $Url"
    if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
        Start-BitsTransfer -Source $Url -Destination $OutputPath
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $OutputPath -UseBasicParsing
    }
}

function New-Shortcut($ShortcutPath, $TargetPath, $WorkingDirectory) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $shortcut.TargetPath = $TargetPath
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.IconLocation = $TargetPath
    $shortcut.Save()
}

Write-Host "Crux Setup"
Write-Host "This installer downloads the verified Crux desktop package from GitHub Releases."
Write-Host "Install location: $InstallDir"

$tempRoot = Join-Path $env:TEMP ("CruxSetup-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null

try {
    $zipPath = Join-Path $tempRoot "Crux-portable-windows.zip"

    if ($UseLocalZip) {
        Write-Step "Using local verified package"
        Copy-Item -LiteralPath $UseLocalZip -Destination $zipPath -Force
    } else {
        Write-Step "Downloading package parts"
        foreach ($part in $PartFiles) {
            $partPath = Join-Path $tempRoot $part.Name
            Download-File $part.Url $partPath
            Assert-Hash $partPath $part.Sha256
        }

        Write-Step "Rebuilding portable package"
        $output = [System.IO.File]::Create($zipPath)
        try {
            foreach ($part in $PartFiles) {
                $partPath = Join-Path $tempRoot $part.Name
                $input = [System.IO.File]::OpenRead($partPath)
                try {
                    $input.CopyTo($output)
                } finally {
                    $input.Dispose()
                }
            }
        } finally {
            $output.Dispose()
        }
    }

    Write-Step "Verifying package"
    Assert-Hash $zipPath $ZipSha256

    Write-Step "Installing Crux"
    $parent = Split-Path -Parent $InstallDir
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path $InstallDir) {
        Remove-Item -LiteralPath $InstallDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $InstallDir -Force

    $exe = Join-Path $InstallDir "Crux.exe"
    if (-not (Test-Path $exe)) {
        $nestedExe = Get-ChildItem -LiteralPath $InstallDir -Filter "Crux.exe" -Recurse -File | Select-Object -First 1
        if (-not $nestedExe) {
            throw "Crux.exe was not found after extraction."
        }
        $exe = $nestedExe.FullName
    }

    Write-Step "Creating shortcuts"
    $desktopShortcut = Join-Path ([Environment]::GetFolderPath("Desktop")) "Crux.lnk"
    New-Shortcut $desktopShortcut $exe (Split-Path -Parent $exe)

    $startMenuDir = Join-Path ([Environment]::GetFolderPath("Programs")) "Crux"
    New-Item -ItemType Directory -Force -Path $startMenuDir | Out-Null
    New-Shortcut (Join-Path $startMenuDir "Crux.lnk") $exe (Split-Path -Parent $exe)

    Write-Step "Installation complete"
    Write-Host "Installed to: $InstallDir"
    Write-Host "Desktop shortcut: $desktopShortcut"

    if (-not $NoLaunch) {
        Write-Step "Launching Crux"
        Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe)
    }
} finally {
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
