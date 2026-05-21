# Crux Installer

This folder contains the Inno Setup installer script.

Build the portable app and installer from `app/`:

```powershell
.\build_installer.ps1
```

Outputs:

```text
dist/Crux/                         PyInstaller portable app
release/Crux-portable-windows.zip  Portable package
release/CruxSetup-0.1.0.exe        Inno installer, if ISCC.exe is installed
```

If Inno Setup is not installed, the build script still creates the portable ZIP and tells you how to finish the `.exe` installer.

## GitHub Bootstrap Installer

GitHub release assets have a 2 GB limit. The full Crux desktop package is larger than that, so the release uses a small bootstrap installer:

```powershell
.\installer\bootstrap\build_bootstrap_installer.ps1
```

That produces `release\CruxSetup.exe`. The setup executable downloads the split portable package from the GitHub Release, verifies SHA256 checksums, installs Crux to `%LOCALAPPDATA%\Programs\Crux`, creates Desktop and Start Menu shortcuts, and launches the app.
