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
