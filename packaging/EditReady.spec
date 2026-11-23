# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the ready-made EditReady app.
# Run from the project folder:  python -m PyInstaller --noconfirm --clean packaging/EditReady.spec
import json
import re
import shutil
import sys
from pathlib import Path

import deno
import imageio_ffmpeg
import yt_dlp.version

ROOT = Path(SPECPATH).parent
PKG = Path(SPECPATH)
IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"
SUFFIX = ".exe" if IS_WIN else ""
APP_VERSION = re.search(r'APP_VERSION = "([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8")).group(1)

# Copy FFmpeg and Deno under plain names (yt-dlp recognises "ffmpeg" by name).
tools = ROOT / "build" / "tools"
shutil.rmtree(tools, ignore_errors=True)
tools.mkdir(parents=True)
ff_bin_dir = Path(imageio_ffmpeg.__file__).parent / "binaries"
ff_src = next(p for p in ff_bin_dir.iterdir() if p.name.startswith("ffmpeg"))
shutil.copy2(ff_src, tools / f"ffmpeg{SUFFIX}")
shutil.copy2(deno.find_deno_bin(), tools / f"deno{SUFFIX}")
for t in tools.iterdir():
    t.chmod(0o755)

versions_file = ROOT / "build" / "engine_versions.json"
versions_file.write_text(json.dumps({"yt-dlp": yt_dlp.version.__version__, "app": APP_VERSION}))
print(f"EditReady {APP_VERSION}: bundling yt-dlp {yt_dlp.version.__version__}, {ff_src.name}, deno")

excludes = ["imageio_ffmpeg", "deno", "numpy", "PIL", "matplotlib", "test", "unittest"]
if IS_MAC:
    excludes.append("tkinter")  # the Mac app uses the native folder picker

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    binaries=[(str(tools / f"ffmpeg{SUFFIX}"), "tools"), (str(tools / f"deno{SUFFIX}"), "tools")],
    datas=[(str(ROOT / "ui.html"), "."), (str(versions_file), ".")],
    hiddenimports=["yt_dlp_ejs", "yt_dlp_ejs.yt", "yt_dlp_ejs.yt.solver", "certifi"],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

icon = str(PKG / ("icon.ico" if IS_WIN else "icon.icns" if IS_MAC else "icon.png"))
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EditReady",
    console=False,
    icon=icon,
    upx=False,
    strip=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="EditReady", upx=False, strip=False)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="EditReady.app",
        icon=icon,
        bundle_identifier="io.github.editready",
        version=APP_VERSION,
        info_plist={
            "CFBundleName": "EditReady",
            "CFBundleDisplayName": "EditReady",
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.video",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # the app window talks to EditReady's own engine on this computer (127.0.0.1)
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSExceptionDomains": {
                    "127.0.0.1": {"NSExceptionAllowsInsecureHTTPLoads": True},
                    "localhost": {"NSExceptionAllowsInsecureHTTPLoads": True},
                },
            },
        },
    )
