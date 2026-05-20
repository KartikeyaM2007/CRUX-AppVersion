# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


def hidden(package):
    try:
        return collect_submodules(package)
    except Exception:
        return []


hiddenimports = []
for package in [
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pandas",
    "numpy",
    "sklearn",
    "scipy",
    "ctgan",
    "rdt",
    "torch",
    "requests",
    "jinja2",
    "multipart",
]:
    hiddenimports += hidden(package)


def collect_tree(root):
    root_path = Path(root)
    files = []
    for path in root_path.rglob("*"):
        if path.is_file():
            target_dir = Path(root_path.name) / path.relative_to(root_path).parent
            files.append((str(path), str(target_dir)))
    return files


datas = [("model_catalog.json", ".")] + collect_tree("bundled_web")


a = Analysis(
    ["desktop_launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "matplotlib.tests",
        "numpy.tests",
        "pandas.tests",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Crux",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Crux",
)
