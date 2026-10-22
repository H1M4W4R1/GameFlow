# -*- mode: python ; coding: utf-8 -*-
"""Single-file Windows distribution. Build with build.ps1."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(SPECPATH)
PACKAGES = ("core", "ui", "devices", "nodes", "plugins")

# Analyze DLL dependencies using the build environment and Windows only.
# An inherited tool PATH can otherwise supply incompatible ICU/OpenSSL DLLs.
qt_package = importlib.util.find_spec("PyQt6")
qt_root = Path(next(iter(qt_package.submodule_search_locations)))
windows_root = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(
    str(path)
    for path in (
        Path(sys.executable).parent,
        Path(sys.base_prefix),
        qt_root / "Qt6" / "bin",
        windows_root / "System32",
        windows_root,
    )
)

icon_path = ROOT / "build" / "pyinstaller" / "app.ico"
subprocess.run(
    [
        sys.executable,
        str(ROOT / "scripts" / "generate_app_icon.py"),
        str(ROOT / "assets" / "icons" / "app.svg"),
        str(icon_path),
    ],
    check=True,
)

# Discovery uses importlib and scans real .py files. Explicitly analyze every
# module, and retain source files for the directories scanned at startup.
hiddenimports = []
for package in PACKAGES:
    for source in sorted((ROOT / package).rglob("*.py")):
        parts = source.relative_to(ROOT).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        hiddenimports.append(".".join(parts))

datas = []
for directory in ("devices", "nodes", "plugins", "assets", "locales"):
    for source in sorted((ROOT / directory).rglob("*")):
        if not source.is_file():
            continue
        if "__pycache__" in source.parts or source.suffix in {".pyc", ".pyo"}:
            continue
        destination = source.parent.relative_to(ROOT).as_posix()
        datas.append((str(source), destination))

for filename in ("README.md", "DEVELOPER.md", "LICENSE.md"):
    datas.append((str(ROOT / filename), "."))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=sorted(set(hiddenimports)),
    hookspath=[],
    runtime_hooks=[],
    # Windows audio uses the required PyAudioWPatch backend. Omit the unused
    # PyAudio fallback, whose external PortAudio DLL may be absent locally.
    excludes=["pyaudio"],
    noarchive=False,
)

# Qt uses the ICU API supplied by Windows. Never ship a third-party DLL with
# the same name, or a build-machine copy of these Windows system libraries.
windows_icu = {"icu.dll", "icuuc.dll", "icuin.dll"}
a.binaries = [
    entry for entry in a.binaries
    if Path(entry[0]).name.lower() not in windows_icu
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GameFlow",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(icon_path),
)
