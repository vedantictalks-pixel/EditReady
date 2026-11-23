#!/usr/bin/env python3
"""
EditReady Downloader
====================
Free, open-source video downloader for editors. Paste a link and get the
highest quality the site offers, as a file Premiere Pro and After Effects
open directly.

Runs on macOS, Windows and Linux. Opens in your web browser, but everything
happens on your own computer.

Engine (all free and open source):
  yt-dlp        downloads from YouTube and 1,000+ other sites
  Deno          solves YouTube's JavaScript checks so all qualities show up
  FFmpeg        converts to ProRes / H.264 / WAV for Adobe apps

License: MIT (see LICENSE)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_NAME = "EditReady"
APP_VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
CONFIG_DIR = Path.home() / ".editready"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
TEMP_DIRNAME = ".editready-temp"
FIRST_PORT = 8765

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # hide console windows for child processes on Windows
FROZEN = bool(getattr(sys, "frozen", False))  # True inside the ready-made app
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", HERE))
ENGINE_DIR = CONFIG_DIR / "engine"
LOG_FILE = CONFIG_DIR / "editready.log"
PYPI = "https://pypi.org/pypi"


def setup_stdio() -> None:
    """The ready-made app has no terminal window, so send output to a log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 2_000_000:
            LOG_FILE.unlink()
        stream = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except Exception:
        stream = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def version_tuple(v: str | None) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def bundled_ytdlp_version() -> str | None:
    """Version of the yt-dlp that shipped with this copy of EditReady (read without importing it)."""
    if FROZEN:
        try:
            return json.loads((BUNDLE_DIR / "engine_versions.json").read_text(encoding="utf-8"))["yt-dlp"]
        except Exception:
            return None
    import importlib.util
    spec = importlib.util.find_spec("yt_dlp")
    if spec and spec.origin:
        try:
            text = (Path(spec.origin).parent / "version.py").read_text(encoding="utf-8")
            m = re.search(r"__version__\s*=\s*['\"]([^'\"]+)", text)
            return m.group(1) if m else None
        except OSError:
            return None
    return None


def activate_engine_update() -> str | None:
    """Use a newer yt-dlp downloaded by the in-app updater. Must run before yt_dlp is imported."""
    try:
        state = json.loads((ENGINE_DIR / "active.json").read_text(encoding="utf-8"))
    except Exception:
        return None
    folder = ENGINE_DIR / str(state.get("dir", ""))
    version = state.get("version")
    if not version or not (folder / "yt_dlp" / "__init__.py").exists():
        return None
    bundled = bundled_ytdlp_version()
    if bundled and version_tuple(version) <= version_tuple(bundled):
        return None
    sys.path.insert(0, str(folder))
    return version


def bundled_tool(name: str) -> str | None:
    """FFmpeg and Deno ship inside the ready-made app, in a folder called tools."""
    exe = BUNDLE_DIR / "tools" / (name + (".exe" if IS_WIN else ""))
    return str(exe) if exe.exists() else None


def https_context():
    """Trust the computer's own certificates (needed on office networks) plus certifi's public list."""
    import ssl
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return ctx


def http_get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout, context=https_context()) as r:
        return r.read()


def windows_has_webview2() -> bool:
    """Edge WebView2 draws EditReady's window on Windows. It's built into Windows 11 and most Windows 10 PCs."""
    try:
        import winreg
    except ImportError:
        return False
    key = r"Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    places = [
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\{key}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\{key}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\{key}"),
    ]
    for hive, path in places:
        try:
            with winreg.OpenKey(hive, path) as k:
                pv, _ = winreg.QueryValueEx(k, "pv")
                if version_tuple(str(pv)) and version_tuple(str(pv))[0] >= 86:
                    return True
        except OSError:
            continue
    return False

MODES = {
    "smart": "Best for Premiere & After Effects",
    "prores": "ProRes 422 HQ (.mov)",
    "mp4": "H.264 (.mp4)",
    "audio": "Audio only (.wav)",
}
MAXRES = {"best": None, "2160": 2160, "1440": 1440, "1080": 1080, "720": 720}
BROWSERS = ["none", "chrome", "firefox", "edge", "safari", "brave", "opera", "vivaldi", "chromium"]

# ProRes 422 HQ is about 220 Mbps at 1080p30, i.e. roughly 3.54 bits per pixel per frame.
PRORES_HQ_BITS_PER_PIXEL = 3.54


# --------------------------------------------------------------------------- #
# Folder picker (runs in a child process so Tk gets its own main thread)
# --------------------------------------------------------------------------- #
def _tk_pick_folder(initial: str) -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        sys.exit(3)
    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except Exception:
        pass
    start = initial if os.path.isdir(initial) else str(Path.home())
    path = filedialog.askdirectory(
        initialdir=start, title="Choose where EditReady saves videos", parent=root
    )
    root.destroy()
    print(os.path.normpath(path) if path else "")


def pick_folder_dialog(initial: str) -> str | None:
    """Open the system's folder chooser. Returns None if cancelled."""
    if IS_MAC:
        script = 'POSIX path of (choose folder with prompt "Choose where EditReady saves videos"'
        if os.path.isdir(initial):
            safe = initial.replace("\\", "\\\\").replace('"', '\\"')
            script += f' default location (POSIX file "{safe}")'
        script += ")"
        r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        return r.stdout.strip().rstrip("/") or None
    if not IS_WIN and shutil.which("zenity"):
        r = subprocess.run(
            ["zenity", "--file-selection", "--directory",
             "--title=Choose where EditReady saves videos", f"--filename={initial}/"],
            capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
        return r.stdout.strip() or None
    r = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--pick-folder", initial],
        capture_output=True, text=True, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
    )
    if r.returncode == 3:
        raise RuntimeError("The folder chooser isn't available on this computer. Type the folder path instead.")
    return r.stdout.strip() or None


def open_in_file_manager(path: Path, select: bool = False) -> None:
    path = Path(path)
    if IS_MAC:
        subprocess.Popen(["open", "-R", str(path)] if select else ["open", str(path)], stdin=subprocess.DEVNULL)
    elif IS_WIN:
        if select and path.exists():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            os.startfile(str(path if path.is_dir() else path.parent))  # type: ignore[attr-defined]
    else:
        target = path.parent if select else path
        subprocess.Popen(["xdg-open", str(target)], stdin=subprocess.DEVNULL)


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
DEFAULT_SETTINGS = {
    "folder": str(Path.home() / "Downloads" / "EditReady"),
    "mode": "smart",
    "maxres": "best",
    "cookies": "none",
    "playlist": False,
}


def load_settings() -> dict:
    data = dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        data.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return sanitize_settings(data)


def sanitize_settings(data: dict) -> dict:
    out = dict(DEFAULT_SETTINGS)
    folder = str(data.get("folder") or "").strip()
    out["folder"] = os.path.expanduser(folder) if folder else DEFAULT_SETTINGS["folder"]
    out["mode"] = data.get("mode") if data.get("mode") in MODES else "smart"
    out["maxres"] = str(data.get("maxres")) if str(data.get("maxres")) in MAXRES else "best"
    out["cookies"] = data.get("cookies") if data.get("cookies") in BROWSERS else "none"
    out["playlist"] = bool(data.get("playlist"))
    return out


def save_settings(data: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Engine: find FFmpeg, Deno and what they can do
# --------------------------------------------------------------------------- #
class Engine:
    def __init__(self) -> None:
        if IS_MAC and FROZEN:
            for tool in ("ffmpeg", "deno"):
                path = bundled_tool(tool)
                if path:  # the app itself was approved, so its helpers shouldn't trigger extra warnings
                    subprocess.run(["xattr", "-d", "com.apple.quarantine", path], capture_output=True,
                                   stdin=subprocess.DEVNULL)
        self.ytdlp_version = self._ytdlp_version()
        self.ejs = self._has_module("yt_dlp_ejs")
        self.ffmpeg = self._find_ffmpeg()
        self.js_name, self.js_path = self._find_js_runtime()
        self.js_version = self._first_line([self.js_path, "--version"]) if self.js_path else None
        self.ffmpeg_version = self._first_line([self.ffmpeg, "-hide_banner", "-version"]) if self.ffmpeg else None
        self.decoders = self._codec_names("decoders") if self.ffmpeg else set()
        self.encoders = self._codec_names("encoders") if self.ffmpeg else set()
        self.av1 = bool({"libdav1d", "libaom-av1"} & self.decoders)
        self.fps_mode_flag = self._fps_mode_flag()
        self.update_status = ""
        self.update_ready: str | None = None

    @staticmethod
    def _has_module(name: str) -> bool:
        import importlib.util
        return importlib.util.find_spec(name) is not None

    @staticmethod
    def _ytdlp_version() -> str | None:
        try:
            from yt_dlp.version import __version__
            return __version__
        except Exception:
            return None

    @staticmethod
    def _find_ffmpeg() -> str | None:
        if bundled_tool("ffmpeg"):
            return bundled_tool("ffmpeg")
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe:
                return shutil.which(exe) or exe
        except Exception:
            pass
        return shutil.which("ffmpeg")

    @staticmethod
    def _find_js_runtime() -> tuple[str | None, str | None]:
        if bundled_tool("deno"):
            return "deno", bundled_tool("deno")
        try:
            import deno
            path = deno.find_deno_bin()
            if path and os.path.exists(path):
                return "deno", str(path)
        except Exception:
            pass
        if shutil.which("deno"):
            return "deno", shutil.which("deno")
        if shutil.which("node"):
            return "node", shutil.which("node")
        return None, None

    @staticmethod
    def _first_line(cmd: list) -> str | None:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW,
                               stdin=subprocess.DEVNULL)
            line = (r.stdout or r.stderr).strip().splitlines()[0]
            return line.strip()
        except Exception:
            return None

    def _codec_names(self, kind: str) -> set:
        try:
            r = subprocess.run([self.ffmpeg, "-hide_banner", f"-{kind}"], capture_output=True,
                               text=True, timeout=20, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        except Exception:
            return set()
        names, started = set(), False
        for line in r.stdout.splitlines():
            if line.strip().startswith("------"):
                started = True
                continue
            if started:
                parts = line.split()
                if len(parts) >= 2:
                    names.add(parts[1])
        return names

    def _fps_mode_flag(self) -> str:
        m = re.search(r"version n?(\d+)\.(\d+)", self.ffmpeg_version or "")
        if m and (int(m.group(1)), int(m.group(2))) < (5, 1):
            return "-vsync"
        return "-fps_mode"

    def public(self) -> dict:
        ff = None
        if self.ffmpeg_version:
            m = re.search(r"version n?(\d+(?:\.\d+)*)", self.ffmpeg_version) or re.search(r"version (\S+)", self.ffmpeg_version)
            ff = m.group(1) if m else self.ffmpeg_version
        js = None
        if self.js_version:
            m = re.search(r"(\d+\.\d+(?:\.\d+)?)", self.js_version)
            js = f"{self.js_name} {m.group(1) if m else ''}".strip()
        notices = []
        if not self.ffmpeg:
            notices.append("FFmpeg is missing, so videos can't be converted. " + REINSTALL_HINT)
        if not self.js_path or not self.ejs:
            notices.append("The YouTube helper (Deno) is missing, so YouTube may offer only low qualities. " + REINSTALL_HINT)
        missing = [e for e in ("prores_ks", "libx264", "aac") if e not in self.encoders] if self.ffmpeg else []
        if missing:
            notices.append("This FFmpeg can't encode: " + ", ".join(missing) + ". Some formats will fail.")
        if self.update_ready:
            notices.append(f"An update for the download engine (yt-dlp {self.update_ready}) is ready. "
                           "Close EditReady and open it again to use it.")
        return {
            "app": APP_VERSION, "ytdlp": self.ytdlp_version, "js": js, "ffmpeg": ff,
            "av1": self.av1, "notices": notices, "update_status": self.update_status,
        }


REINSTALL_HINT = ("Download and install EditReady again." if FROZEN
                  else "Start EditReady with the start file for your system to install it.")


# --------------------------------------------------------------------------- #
# Engine updates: sites like YouTube change often, and yt-dlp ships fixes fast.
# The app downloads the newest yt-dlp from PyPI (checked against PyPI's SHA-256)
# into ~/.editready/engine and uses it from the next start.
# --------------------------------------------------------------------------- #
class EngineUpdater:
    CHECK_EVERY = 20 * 3600

    def __init__(self, engine: Engine):
        self.engine = engine
        self.lock = threading.Lock()

    def check_in_background(self) -> None:
        def run():
            time.sleep(5)
            try:
                last = float((ENGINE_DIR / "last_check").read_text())
            except Exception:
                last = 0
            if time.time() - last > self.CHECK_EVERY:
                try:
                    self.run()
                except Exception as e:  # noqa: BLE001
                    print(f"Engine update check failed: {e}")
        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _wheel(files: list) -> dict:
        wheels = [f for f in files if f.get("packagetype") == "bdist_wheel" and f["filename"].endswith("-py3-none-any.whl")]
        if not wheels:
            raise RuntimeError("no wheel found")
        return wheels[0]

    @staticmethod
    def _extract(file_info: dict, dest: Path) -> None:
        import hashlib
        import io
        import zipfile
        data = http_get(file_info["url"], timeout=120)
        if hashlib.sha256(data).hexdigest() != file_info["digests"]["sha256"]:
            raise RuntimeError(f"checksum mismatch for {file_info['filename']}")
        root = dest.resolve()
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.namelist():
                target = (dest / member).resolve()
                if root not in target.parents and target != root:
                    raise RuntimeError("unsafe path in update")
            z.extractall(dest)

    def run(self) -> str:
        with self.lock:
            ENGINE_DIR.mkdir(parents=True, exist_ok=True)
            data = json.loads(http_get(f"{PYPI}/yt-dlp/json", timeout=30))
            (ENGINE_DIR / "last_check").write_text(str(time.time()))
            latest = data["info"]["version"]
            current = self.engine.update_ready or self.engine.ytdlp_version
            if current and version_tuple(latest) <= version_tuple(current):
                if self.engine.update_ready:
                    msg = f"yt-dlp {self.engine.update_ready} is ready. Close EditReady and open it again to use it."
                else:
                    msg = f"The download engine is up to date (yt-dlp {current})."
                self.engine.update_status = msg
                return msg

            ejs_pin = None
            for req in data["info"].get("requires_dist") or []:
                m = re.match(r"yt-dlp-ejs\s*==\s*([\w.]+)\s*;.*extra\s*==\s*['\"]default['\"]", req)
                if m:
                    ejs_pin = m.group(1)
            staging = ENGINE_DIR / f".download-{latest}"
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True)
            try:
                self._extract(self._wheel(data["urls"]), staging)
                if ejs_pin:
                    ejs = json.loads(http_get(f"{PYPI}/yt-dlp-ejs/{ejs_pin}/json", timeout=30))
                    self._extract(self._wheel(ejs["urls"]), staging)
                final = ENGINE_DIR / f"yt-dlp-{latest}"
                shutil.rmtree(final, ignore_errors=True)
                staging.rename(final)
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
            active_before = None
            try:
                active_before = json.loads((ENGINE_DIR / "active.json").read_text()).get("dir")
            except Exception:
                pass
            tmp = ENGINE_DIR / "active.json.tmp"
            tmp.write_text(json.dumps({"version": latest, "dir": final.name}), encoding="utf-8")
            os.replace(tmp, ENGINE_DIR / "active.json")
            for old in ENGINE_DIR.glob("yt-dlp-*"):
                if old.name not in (final.name, active_before):
                    shutil.rmtree(old, ignore_errors=True)
            self.engine.update_ready = latest
            msg = f"Downloaded yt-dlp {latest}. Close EditReady and open it again to use it."
            self.engine.update_status = msg
            return msg


# --------------------------------------------------------------------------- #
# Format choice
# --------------------------------------------------------------------------- #
@dataclass
class Plan:
    selector: str
    audio_only: bool = False
    res: int | None = None
    fps: float | None = None
    vcodec: str | None = None


def _res(f: dict) -> int:
    w, h = f.get("width"), f.get("height")
    if w and h:
        return int(min(w, h))  # short side, so vertical 1080x1920 counts as 1080p
    return int(h or 0)


def _codec_rank(vc: str | None) -> int:
    vc = (vc or "").lower()
    if vc.startswith("avc") or "h264" in vc:
        return 3  # H.264 at the same size needs no conversion in smart mode
    if vc.startswith(("vp09", "vp9", "hev", "hvc", "h265")):
        return 2
    if vc.startswith("av01"):
        return 1
    return 0


def _has_video(f: dict) -> bool:
    if f.get("vcodec") == "none" or f.get("protocol") == "mhtml":
        return False
    return bool(f.get("vcodec") or f.get("height") or f.get("width"))


def _is_audio_only(f: dict) -> bool:
    return f.get("vcodec") == "none" and f.get("acodec") != "none" and f.get("protocol") != "mhtml"


def _audio_key(f: dict):
    lang = f.get("language_preference")
    lang = lang if isinstance(lang, (int, float)) else 0
    not_drc = 0 if "drc" in str(f.get("format_id", "")).lower() else 1
    return (lang, not_drc, f.get("abr") or f.get("tbr") or 0)


def choose_formats(info: dict, mode: str, maxres: str, engine: Engine) -> Plan:
    fmts = info.get("formats") or []
    if mode == "audio":
        auds = [f for f in fmts if _is_audio_only(f)]
        if auds:
            return Plan(max(auds, key=_audio_key)["format_id"], audio_only=True)
        return Plan("bestaudio/best", audio_only=True)

    vids = [f for f in fmts if _has_video(f)]
    if not vids:
        return Plan("bestvideo*+bestaudio/best")

    if not engine.av1:
        non_av1 = [f for f in vids if not str(f.get("vcodec") or "").lower().startswith("av01")]
        vids = non_av1 or vids
    sdr = [f for f in vids if (f.get("dynamic_range") or "SDR") == "SDR"]
    vids = sdr or vids  # HDR looks washed out in a normal SDR edit, so prefer SDR

    cap = MAXRES.get(maxres)
    if cap:
        under = [f for f in vids if _res(f) <= cap]
        vids = under or [min(vids, key=_res)]

    best = max(vids, key=lambda f: (_res(f), round(f.get("fps") or 0), _codec_rank(f.get("vcodec")), f.get("tbr") or 0))
    plan = Plan(best["format_id"], res=_res(best) or None, fps=best.get("fps"), vcodec=best.get("vcodec"))
    if best.get("acodec") not in (None, "none"):
        return plan
    auds = [f for f in fmts if _is_audio_only(f)]
    if auds:
        plan.selector = f"{best['format_id']}+{max(auds, key=_audio_key)['format_id']}"
    return plan


# --------------------------------------------------------------------------- #
# Media helpers
# --------------------------------------------------------------------------- #
@dataclass
class Probe:
    duration: float | None = None
    vcodec: str | None = None
    pix_fmt: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    hdr: bool = False
    acodec: str | None = None


def probe_media(ffmpeg: str, path: Path) -> Probe:
    r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                       errors="replace", creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
    txt = r.stderr
    p = Probe()
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", txt)
    if m:
        p.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in txt.splitlines():
        vm = re.search(r"Stream #\d+:\d+.*?: Video: (.*)", line)
        if vm and "attached pic" not in line and p.vcodec is None:
            details = vm.group(1)
            p.vcodec = re.match(r"(\w+)", details).group(1)
            pm = re.search(r", ((?:yuv|yuvj|rgb|bgr|gbr|nv|p0)\w*)", details)
            p.pix_fmt = pm.group(1) if pm else None
            sm = re.search(r"\b(\d{2,5})x(\d{2,5})\b", details)
            if sm:
                p.width, p.height = int(sm.group(1)), int(sm.group(2))
            fm = re.search(r"([\d.]+) fps", details)
            p.fps = float(fm.group(1)) if fm else None
            p.hdr = "smpte2084" in details or "arib-std-b67" in details
        am = re.search(r"Stream #\d+:\d+.*?: Audio: (\w+)", line)
        if am and p.acodec is None:
            p.acodec = am.group(1)
    return p


STANDARD_RATES = [
    (24000 / 1001, "24000/1001"), (24, "24"), (25, "25"), (30000 / 1001, "30000/1001"), (30, "30"),
    (48, "48"), (50, "50"), (60000 / 1001, "60000/1001"), (60, "60"), (100, "100"),
    (120000 / 1001, "120000/1001"), (120, "120"),
]


def standard_rate(fps: float | None) -> str | None:
    """Snap a measured frame rate to the nearest broadcast rate Premiere expects."""
    if not fps or fps <= 0 or fps > 125:
        return None
    value, label = min(STANDARD_RATES, key=lambda r: abs(r[0] - fps))
    return label if abs(value - fps) / value < 0.02 else None


def clean_title(title: str) -> str:
    title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", title)
    title = re.sub(r"\s+", " ", title).strip().strip(".")
    return (title[:120].rstrip(" .") or "video")


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    candidate = folder / f"{stem}.{ext}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}).{ext}"
        n += 1
    return candidate


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit in ("GB", "TB") else f"{num:.0f} {unit}"
        num /= 1024
    return f"{num:.1f} TB"


def friendly_error(err) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(err))
    msg = re.sub(r"^(ERROR:\s*)+", "", msg.strip())
    msg = re.sub(r"^\[[^\]]+\]\s*[\w-]+:\s*", "", msg)
    low = msg.lower()
    if "not a bot" in low or "sign in to confirm" in low:
        return "YouTube asked to confirm you're not a bot. Open Options, pick your browser under \u201cUse logins from\u201d (and be signed in to YouTube there), then try again."
    if "private video" in low:
        return "This video is private. If your account can watch it, open Options, pick your browser under \u201cUse logins from\u201d, then try again."
    if "age" in low and ("restrict" in low or "confirm your age" in low):
        return "This video is age-restricted. Open Options, pick a browser where you're signed in under \u201cUse logins from\u201d, then try again."
    if any(k in low for k in ("failed to establish a new connection", "connection refused", "name or service not known",
                              "nodename nor servname", "getaddrinfo failed", "temporary failure in name resolution",
                              "timed out", "network is unreachable")):
        return "Couldn't reach the site. Check your internet connection and the link, then try again."
    if "http error 404" in low or "not found" in low and "http" in low:
        return "Nothing was found at this link (error 404). Check that the link is complete and the video still exists."
    if "unsupported url" in low:
        return "EditReady can't read this link. Copy the link from the video's own page and try again."
    if "http error 403" in low or "forbidden" in low:
        return "The site refused the download (error 403). Click \u201cCheck for updates\u201d at the bottom, then close and reopen EditReady and try again."
    if "http error 429" in low or "too many requests" in low:
        return "The site is limiting downloads right now (too many requests). Wait a while, then try again."
    if "login" in low or "log in" in low or "cookies" in low:
        return "This site needs you to be logged in. Open Options, pick your browser under \u201cUse logins from\u201d, then try again."
    if "video unavailable" in low or "not available" in low:
        return "This video isn't available. It may be removed, region-locked or members-only."
    if "could not copy" in low and "cookie" in low:
        return "Couldn't read the browser's logins. Close that browser completely and try again, or pick Firefox."
    return msg[:400] or "Something went wrong."


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
_counter = 0
_counter_lock = threading.Lock()


def _next_id() -> str:
    global _counter
    with _counter_lock:
        _counter += 1
        return f"j{_counter}"


@dataclass
class Job:
    url: str
    mode: str
    maxres: str
    folder: str
    cookies: str
    playlist: bool
    id: str = field(default_factory=_next_id)
    status: str = "queued"  # queued reading downloading converting done failed cancelled playlist
    stage: str = "Waiting"
    progress: float | None = None
    detail: str = ""
    title: str = ""
    site: str = ""
    thumbnail: str = ""
    duration: float | None = None
    quality: str = ""
    output_kind: str = ""
    output_path: str = ""
    error: str = ""
    warnings: list = field(default_factory=list)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    proc: subprocess.Popen | None = None
    tmp: Path | None = None

    def public(self) -> dict:
        return {
            "id": self.id, "url": self.url, "status": self.status, "stage": self.stage,
            "progress": self.progress, "detail": self.detail, "title": self.title or self.url,
            "site": self.site, "thumbnail": self.thumbnail, "duration": self.duration,
            "quality": self.quality, "output_kind": self.output_kind,
            "output_name": Path(self.output_path).name if self.output_path else "",
            "error": self.error, "mode": self.mode,
        }


class JobLogger:
    def __init__(self, job: Job):
        self.job = job

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if len(self.job.warnings) < 20:
            self.job.warnings.append(str(msg))

    def error(self, msg):
        self.job.error = str(msg)


class Manager:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.jobs: list[Job] = []
        self.lock = threading.Lock()
        self.wake = threading.Condition(self.lock)
        self.stopping = False
        threading.Thread(target=self._worker, daemon=True).start()

    # ----- queue -----
    def add(self, urls: list[str], s: dict, after: Job | None = None, playlist: bool | None = None) -> list[Job]:
        new = [Job(url=u, mode=s["mode"], maxres=s["maxres"], folder=s["folder"], cookies=s["cookies"],
                   playlist=s["playlist"] if playlist is None else playlist) for u in urls]
        with self.wake:
            if after and after in self.jobs:
                i = self.jobs.index(after) + 1
                self.jobs[i:i] = new
            else:
                self.jobs.extend(new)
            self.wake.notify_all()
        return new

    def cancel(self, job_id: str) -> None:
        with self.lock:
            job = next((j for j in self.jobs if j.id == job_id), None)
        if not job:
            return
        job.cancel_event.set()
        if job.status == "queued":
            job.status, job.stage, job.progress = "cancelled", "Cancelled", None
        proc = job.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

            def _force_stop():
                time.sleep(1.5)
                if proc.poll() is None:
                    try:
                        proc.kill()
                    except Exception:
                        pass
            threading.Thread(target=_force_stop, daemon=True).start()

    def cancel_all(self) -> None:
        for j in list(self.jobs):
            if j.status in ("queued", "reading", "downloading", "converting"):
                self.cancel(j.id)

    def busy(self) -> bool:
        return any(j.status in ("queued", "reading", "downloading", "converting") for j in self.jobs)

    def stop(self, timeout: float = 4.0) -> None:
        self.stopping = True
        self.cancel_all()
        end = time.time() + timeout
        while time.time() < end and any(j.proc and j.proc.poll() is None for j in self.jobs):
            time.sleep(0.1)
        for j in self.jobs:
            if j.proc and j.proc.poll() is None:
                try:
                    j.proc.kill()
                except Exception:
                    pass

    def remove(self, job_id: str) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs if not (j.id == job_id and j.status in ("done", "failed", "cancelled", "playlist"))]

    def clear_finished(self) -> None:
        with self.lock:
            self.jobs = [j for j in self.jobs if j.status not in ("done", "failed", "cancelled", "playlist")]

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return next((j for j in self.jobs if j.id == job_id), None)

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [j.public() for j in self.jobs]

    def _worker(self) -> None:
        while not self.stopping:
            with self.wake:
                job = next((j for j in self.jobs if j.status == "queued"), None)
                if job is None:
                    self.wake.wait(timeout=1.0)
                    continue
                job.status, job.stage = "reading", "Reading link"
            self._run(job)

    # ----- one job -----
    def _ydl_opts(self, job: Job, **extra) -> dict:
        opts = {
            "quiet": True,
            "noprogress": True,
            "logger": JobLogger(job),
            "noplaylist": not job.playlist,
            "extract_flat": "in_playlist",
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": 4,
            "windowsfilenames": True,
            "overwrites": True,
            "remote_components": ["ejs:github"],
        }
        if self.engine.ffmpeg:
            opts["ffmpeg_location"] = self.engine.ffmpeg
        if self.engine.js_path:
            opts["js_runtimes"] = {self.engine.js_name: {"path": self.engine.js_path}}
        if job.cookies != "none":
            opts["cookiesfrombrowser"] = (job.cookies,)
        opts.update(extra)
        return opts

    def _run(self, job: Job) -> None:
        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadCancelled

            with YoutubeDL(self._ydl_opts(job)) as ydl:
                info = ydl.extract_info(job.url, download=False)
            if job.cancel_event.is_set():
                raise Cancelled()
            info = info or {}

            if info.get("_type") in ("playlist", "multi_video"):
                urls = []
                for e in info.get("entries") or []:
                    if not e:
                        continue
                    u = e.get("url") or e.get("webpage_url")
                    if u and not u.startswith("http") and e.get("ie_key") == "Youtube":
                        u = f"https://www.youtube.com/watch?v={u}"
                    if u:
                        urls.append(u)
                job.title = info.get("title") or "Playlist"
                job.site = info.get("extractor_key") or ""
                self.add(urls, {"mode": job.mode, "maxres": job.maxres, "folder": job.folder,
                                "cookies": job.cookies, "playlist": False}, after=job, playlist=False)
                job.status, job.stage, job.progress = "playlist", f"Added {len(urls)} videos to the queue", None
                return

            job.title = info.get("title") or job.url
            job.site = info.get("extractor_key") or info.get("extractor") or ""
            job.thumbnail = info.get("thumbnail") or ""
            job.duration = info.get("duration")

            plan = choose_formats(info, job.mode, job.maxres, self.engine)
            if plan.audio_only:
                job.quality = "Audio"
            elif plan.res:
                job.quality = f"{plan.res}p" + (f", {round(plan.fps)} fps" if plan.fps else "")
            job.output_kind = self._predict_kind(job.mode, plan.vcodec)

            src = self._download(job, info, plan, YoutubeDL, DownloadCancelled)
            final = self._convert(job, src, info)
            job.output_path = str(final)
            size = final.stat().st_size if final.exists() else 0
            job.status, job.stage, job.progress = "done", "Saved", 1.0
            job.detail = human_size(size)
        except Cancelled:
            job.status, job.stage, job.progress = "cancelled", "Cancelled", None
        except Exception as e:  # noqa: BLE001
            if job.cancel_event.is_set() or e.__class__.__name__ == "DownloadCancelled":
                job.status, job.stage, job.progress = "cancelled", "Cancelled", None
            else:
                job.status, job.stage, job.progress = "failed", "Failed", None
                job.error = friendly_error(job.error or e) if not isinstance(e, UserFacingError) else str(e)
        finally:
            job.proc = None
            if job.tmp and job.tmp.exists():
                shutil.rmtree(job.tmp, ignore_errors=True)
                try:
                    job.tmp.parent.rmdir()  # removes .editready-temp only when empty
                except OSError:
                    pass

    @staticmethod
    def _predict_kind(mode: str, vcodec: str | None) -> str:
        if mode == "audio":
            return "WAV"
        if mode == "prores":
            return "ProRes 422 HQ, .mov"
        if mode == "mp4":
            return "H.264, .mp4"
        if _codec_rank(vcodec) == 3:
            return "H.264, .mp4"
        return "ProRes 422 HQ, .mov" if vcodec else ""

    def _download(self, job: Job, info: dict, plan: Plan, YoutubeDL, DownloadCancelled) -> Path:
        folder = Path(job.folder).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise UserFacingError(f"Can't create the folder {folder}. Check that the drive is connected, or choose another folder.")
        job.tmp = folder / TEMP_DIRNAME / job.id
        job.tmp.mkdir(parents=True, exist_ok=True)

        parts = plan.selector.count("+") + 1
        seen: list[str] = []

        def hook(d):
            if job.cancel_event.is_set():
                raise DownloadCancelled()
            if d.get("status") != "downloading":
                return
            fid = str((d.get("info_dict") or {}).get("format_id", ""))
            if fid not in seen:
                seen.append(fid)
            fi = d.get("info_dict") or {}
            what = "audio" if plan.audio_only or fi.get("vcodec") == "none" else "video"
            step = f" ({len(seen)} of {parts})" if parts > 1 else ""
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            job.status = "downloading"
            job.stage = f"Downloading {what}{step}"
            job.progress = min(done / total, 1.0) if total else None
            speed = d.get("speed")
            job.detail = f"{human_size(speed)}/s" if speed else ""

        opts = self._ydl_opts(
            job,
            format=plan.selector,
            outtmpl={"default": str(job.tmp / "source.%(ext)s")},
            merge_output_format="mkv",
            progress_hooks=[hook],
            noplaylist=True,
            extract_flat=False,
        )
        job.status, job.stage, job.progress = "downloading", "Starting download", None
        with YoutubeDL(opts) as ydl:
            result = ydl.process_ie_result(info, download=True)
        if job.cancel_event.is_set():
            raise Cancelled()

        candidates = []
        for rd in (result or {}).get("requested_downloads") or []:
            fp = rd.get("filepath")
            if fp and Path(fp).exists():
                candidates.append(Path(fp))
        if not candidates:
            candidates = [p for p in job.tmp.iterdir() if p.is_file() and not p.name.endswith((".part", ".ytdl"))]
        if not candidates:
            raise UserFacingError("The download finished but no video file was saved. Try again, or click \u201cCheck for updates\u201d at the bottom.")
        return max(candidates, key=lambda p: p.stat().st_size)

    def _convert(self, job: Job, src: Path, info: dict) -> Path:
        ff = self.engine.ffmpeg
        if not ff:
            raise UserFacingError("FFmpeg is missing. Restart EditReady with the start file for your system to install it.")
        pr = probe_media(ff, src)
        duration = pr.duration or info.get("duration")
        folder = Path(job.folder).expanduser()
        title = clean_title(info.get("title") or "video")

        if job.mode == "audio" or (pr.vcodec is None and pr.acodec):
            target = "wav"
        else:
            is_h264_8bit = pr.vcodec == "h264" and (pr.pix_fmt or "").startswith(("yuv420p", "yuvj420p")) \
                and not (pr.pix_fmt or "").startswith("yuv420p10")
            if job.mode == "prores":
                target = "prores"
            elif job.mode == "mp4":
                target = "copy_mp4" if is_h264_8bit else "x264"
            else:
                target = "copy_mp4" if is_h264_8bit else "prores"

        if target == "wav":
            label, ext, kind = "audio", "wav", "WAV"
        else:
            short = min(pr.width, pr.height) if pr.width and pr.height else None
            label = f"{short}p" if short else "video"
            if pr.fps and pr.fps > 31:
                label += str(round(pr.fps))
            ext = "mov" if target == "prores" else "mp4"
            kind = "ProRes 422 HQ, .mov" if target == "prores" else "H.264, .mp4"
            if pr.width and pr.height:
                job.quality = f"{short}p" + (f", {round(pr.fps)} fps" if pr.fps else "")
        job.output_kind = kind

        if target == "prores" and pr.width and pr.height and duration:
            fps = pr.fps or 30
            need = PRORES_HQ_BITS_PER_PIXEL * pr.width * pr.height * fps * duration / 8
            free = shutil.disk_usage(folder).free
            if need * 1.05 > free:
                raise UserFacingError(
                    f"Not enough free space: the ProRes file needs about {human_size(need)} and the drive has "
                    f"{human_size(free)} free. Choose another folder, or pick H.264 (.mp4) for a smaller file.")

        out_tmp = job.tmp / f"output.{ext}"
        cmd = [ff, "-hide_banner", "-y", "-nostdin", "-loglevel", "error", "-nostats", "-progress", "pipe:1",
               "-i", str(src)]
        if target == "wav":
            cmd += ["-map", "0:a:0", "-vn", "-c:a", "pcm_s16le"]
            stage = "Converting audio to WAV"
        else:
            cmd += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn", "-map_chapters", "-1"]
            video_filters = []
            if pr.width and pr.height and (pr.width % 2 or pr.height % 2):
                video_filters.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
            cfr = []
            rate = standard_rate(pr.fps)
            if rate:
                cfr = ["-r", rate, self.engine.fps_mode_flag, "cfr"]
            if target == "copy_mp4":
                cmd += ["-c:v", "copy"]
                stage = "Packing for Premiere (no quality loss)"
            elif target == "prores":
                cmd += ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0", "-pix_fmt", "yuv422p10le"] + cfr
                stage = "Converting to ProRes for Premiere & After Effects"
            else:
                cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
                        "-profile:v", "high"] + cfr
                stage = "Converting to H.264 for Premiere"
            if video_filters and target != "copy_mp4":
                cmd += ["-vf", ",".join(video_filters)]
            if target == "prores":
                cmd += ["-c:a", "pcm_s16le"]
            elif pr.acodec == "aac":
                cmd += ["-c:a", "copy"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "320k"]
            if ext == "mp4":
                cmd += ["-movflags", "+faststart"]
        cmd.append(str(out_tmp))

        job.status, job.stage, job.progress, job.detail = "converting", stage, 0.0, ""
        self._run_ffmpeg(job, cmd, duration)

        final = unique_path(folder, f"{title} [{label}]", ext)
        shutil.move(str(out_tmp), str(final))
        return final

    def _run_ffmpeg(self, job: Job, cmd: list, duration: float | None) -> None:
        with tempfile.TemporaryFile() as errf:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=errf, stdin=subprocess.DEVNULL,
                                    text=True, errors="replace", creationflags=NO_WINDOW)
            job.proc = proc
            started = time.time()
            assert proc.stdout is not None
            for line in proc.stdout:
                if job.cancel_event.is_set():
                    proc.terminate()
                    break
                key, _, val = line.strip().partition("=")
                if key in ("out_time_us", "out_time_ms") and val.isdigit() and duration:
                    secs = int(val) / 1_000_000
                    frac = max(0.0, min(secs / duration, 1.0))
                    job.progress = frac
                    elapsed = time.time() - started
                    if frac > 0.02:
                        left = elapsed / frac - elapsed
                        if left >= 60:
                            job.detail = f"about {int(left // 60)} min {int(left % 60)} s left"
                        elif left >= 2:
                            job.detail = f"about {int(left)} s left"
                        else:
                            job.detail = "almost done"
            proc.wait()
            if job.cancel_event.is_set():
                raise Cancelled()
            if proc.returncode != 0:
                errf.seek(0)
                err = errf.read().decode("utf-8", "replace").strip().splitlines()
                last = err[-1] if err else f"exit code {proc.returncode}"
                raise UserFacingError(f"FFmpeg couldn't convert this video: {last}")


class UserFacingError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Web server
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, port: int):
        self.port = port
        self.settings = load_settings()
        self.engine = Engine()
        self.manager = Manager(self.engine)
        self.updater = EngineUpdater(self.engine)
        self.server: ThreadingHTTPServer | None = None
        self.window = None  # the native window, when EditReady runs as a ready-made app

    def quit(self) -> None:
        if self.window is not None:
            try:
                self.window.destroy()
                return
            except Exception:
                pass
        if self.server:
            self.server.shutdown()

    def allowed_hosts(self) -> set:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}


def make_handler(app: App):
    ui_path = BUNDLE_DIR / "ui.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = APP_NAME
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, code: int, body, ctype: str = "application/json; charset=utf-8") -> None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in app.allowed_hosts()

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "forbidden"})
            path = urlparse(self.path).path
            if path in ("/", "/index.html"):
                try:
                    html = ui_path.read_bytes()
                except OSError:
                    return self._send(500, b"ui.html is missing next to app.py", "text/plain; charset=utf-8")
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/ping":
                return self._send(200, {"app": APP_NAME, "version": APP_VERSION})
            if path == "/api/state":
                return self._send(200, {
                    "jobs": app.manager.snapshot(),
                    "settings": app.settings,
                    "engine": app.engine.public(),
                    "modes": MODES,
                    "window_mode": app.window is not None,
                })
            if path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._host_ok() or self.headers.get("X-EditReady") != "1":
                return self._send(403, {"error": "forbidden"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
            except Exception:
                return self._send(400, {"error": "Bad request"})
            path = urlparse(self.path).path
            try:
                return self._route(path, body)
            except UserFacingError as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001
                return self._send(500, {"error": str(e)})

        def _route(self, path: str, body: dict):
            m = app.manager
            if path == "/api/settings":
                app.settings = sanitize_settings({**app.settings, **body})
                save_settings(app.settings)
                return self._send(200, {"settings": app.settings})
            if path == "/api/add":
                app.settings = sanitize_settings({**app.settings, **(body.get("settings") or {})})
                save_settings(app.settings)
                raw = body.get("urls") or ""
                urls = [u.strip() for u in re.split(r"[\s,]+", raw) if u.strip()]
                urls = [u if re.match(r"^[a-z][a-z0-9+.-]*://", u, re.I) else "https://" + u for u in urls]
                urls = list(dict.fromkeys(urls))
                if not urls:
                    raise UserFacingError("Paste at least one video link.")
                folder = Path(app.settings["folder"]).expanduser()
                try:
                    folder.mkdir(parents=True, exist_ok=True)
                except OSError:
                    raise UserFacingError(f"Can't use the folder {folder}. Check that the drive is connected, or choose another folder.")
                added = m.add(urls, app.settings)
                return self._send(200, {"added": len(added)})
            if path == "/api/cancel":
                m.cancel(str(body.get("id")))
                return self._send(200, {"ok": True})
            if path == "/api/cancel-all":
                m.cancel_all()
                return self._send(200, {"ok": True})
            if path == "/api/remove":
                m.remove(str(body.get("id")))
                return self._send(200, {"ok": True})
            if path == "/api/clear":
                m.clear_finished()
                return self._send(200, {"ok": True})
            if path == "/api/retry":
                job = m.get(str(body.get("id")))
                if job and job.status in ("failed", "cancelled"):
                    m.add([job.url], {"mode": job.mode, "maxres": job.maxres, "folder": job.folder,
                                      "cookies": app.settings["cookies"], "playlist": job.playlist}, after=job)
                    m.remove(job.id)
                return self._send(200, {"ok": True})
            if path == "/api/pick-folder":
                if app.window is not None:
                    import webview
                    start = app.settings["folder"] if os.path.isdir(app.settings["folder"]) else str(Path.home())
                    res = app.window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
                    chosen = (res[0] if isinstance(res, (list, tuple)) else res) if res else None
                else:
                    chosen = pick_folder_dialog(app.settings["folder"])
                if chosen:
                    app.settings = sanitize_settings({**app.settings, "folder": chosen})
                    save_settings(app.settings)
                return self._send(200, {"settings": app.settings, "changed": bool(chosen)})
            if path == "/api/open-folder":
                folder = Path(app.settings["folder"]).expanduser()
                folder.mkdir(parents=True, exist_ok=True)
                open_in_file_manager(folder)
                return self._send(200, {"ok": True})
            if path == "/api/reveal":
                job = m.get(str(body.get("id")))
                if job and job.output_path and Path(job.output_path).exists():
                    open_in_file_manager(Path(job.output_path), select=True)
                    return self._send(200, {"ok": True})
                raise UserFacingError("That file isn't there any more. It may have been moved or deleted.")
            if path == "/api/update":
                try:
                    status = app.updater.run()
                except Exception as e:  # noqa: BLE001
                    status = f"Couldn't check for updates. Check your internet connection. ({e})"
                    app.engine.update_status = status
                return self._send(200, {"status": status})
            if path == "/api/quit":
                self._send(200, {"ok": True})
                m.cancel_all()
                threading.Thread(target=lambda: (time.sleep(0.4), app.quit()), daemon=True).start()
                return None
            return self._send(404, {"error": "not found"})

    return Handler


def already_running(port: int) -> bool:
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ping")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=1) as r:
            return json.loads(r.read()).get("app") == APP_NAME
    except Exception:
        return False


def can_use_window() -> bool:
    if "--browser" in sys.argv or os.environ.get("EDITREADY_BROWSER"):
        return False
    if IS_WIN and not windows_has_webview2():
        return False
    if not (IS_WIN or IS_MAC):
        return False  # on Linux the browser is the most reliable window
    try:
        import webview  # noqa: F401
        return True
    except Exception:
        return False


def open_window(url: str, app: App | None) -> bool:
    """Show EditReady in its own native window. Returns False if that isn't possible here."""
    try:
        import webview
        window = webview.create_window(
            APP_NAME, url, width=1040, height=900, min_size=(440, 560),
            text_select=True, background_color="#E6E9E8",
        )
        if app is not None:
            app.window = window

            def guard_close():
                # ask before closing only while something is downloading
                while True:
                    try:
                        window.confirm_close = app.manager.busy()
                    except Exception:
                        return
                    time.sleep(0.5)
            threading.Thread(target=guard_close, daemon=True).start()
        webview.start(
            gui="edgechromium" if IS_WIN else None,
            localization={"global.quitConfirmation": "Downloads in progress will stop. Quit EditReady?",
                          "global.quit": "Quit", "global.cancel": "Keep downloading"},
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Native window unavailable, using the browser instead: {e}")
        if app is not None:
            app.window = None
        return False


def selftest(check_youtube: bool) -> int:
    """Used by the build service to check each ready-made app before release."""
    result: dict = {"frozen": FROZEN, "platform": sys.platform}
    try:
        result["engine_override"] = activate_engine_update()
        eng = Engine()
        result["engine"] = eng.public()
        result["paths"] = {"ffmpeg": eng.ffmpeg, "js": eng.js_path}
        ok = bool(eng.ytdlp_version and eng.ffmpeg and eng.js_path and eng.ejs)
        result["encoders"] = {e: e in eng.encoders for e in ("prores_ks", "libx264", "aac", "pcm_s16le")}
        ok = ok and all(result["encoders"].values())
        tmp = Path(tempfile.mkdtemp())
        r = subprocess.run([eng.ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc2=size=320x180:rate=30", "-t", "1", "-c:v", "prores_ks", "-profile:v", "3",
                            "-pix_fmt", "yuv422p10le", str(tmp / "t.mov")],
                           capture_output=True, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
        result["prores_test"] = r.returncode == 0 and (tmp / "t.mov").exists()
        r = subprocess.run([eng.js_path, "eval", "console.log(6*7)"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=120)
        result["js_test"] = r.stdout.strip() == "42"
        ok = ok and result["prores_test"] and result["js_test"]
        shutil.rmtree(tmp, ignore_errors=True)
        result["ui_found"] = (BUNDLE_DIR / "ui.html").exists()
        ok = ok and result["ui_found"]
        if check_youtube:
            try:
                from yt_dlp import YoutubeDL
                opts = {"quiet": True, "no_warnings": True, "ffmpeg_location": eng.ffmpeg,
                        "js_runtimes": {eng.js_name: {"path": eng.js_path}}, "remote_components": ["ejs:github"]}
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info("https://www.youtube.com/watch?v=jNQXAC9IVRw", download=False)
                fmts = info.get("formats") or []
                result["youtube"] = {"formats": len(fmts), "best_height": max((f.get("height") or 0) for f in fmts)}
            except Exception as e:  # noqa: BLE001
                result["youtube"] = {"error": str(e)[:300]}
    except Exception as e:  # noqa: BLE001
        result["error"] = repr(e)
        ok = False
    result["ok"] = ok
    text = json.dumps(result, indent=2)
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CONFIG_DIR / "selftest.json").write_text(text, encoding="utf-8")
    except Exception:
        pass
    print(text)
    return 0 if ok else 1


def main() -> None:
    setup_stdio()
    if "--pick-folder" in sys.argv:
        i = sys.argv.index("--pick-folder")
        _tk_pick_folder(sys.argv[i + 1] if len(sys.argv) > i + 1 else str(Path.home()))
        return
    if "--selftest" in sys.argv:
        sys.exit(selftest("--youtube" in sys.argv))

    no_browser = "--no-browser" in sys.argv
    use_window = can_use_window()

    if already_running(FIRST_PORT):
        url = f"http://127.0.0.1:{FIRST_PORT}/"
        print(f"{APP_NAME} is already running. Opening it.")
        if not (use_window and open_window(url, None)) and not no_browser:
            webbrowser.open(url)
        return

    override = activate_engine_update()
    server, app = None, None
    for port in range(FIRST_PORT, FIRST_PORT + 30):
        try:
            app = App(port)
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
            break
        except OSError:
            continue
    if server is None or app is None:
        print("Couldn't start EditReady: no free port between 8765 and 8794.")
        sys.exit(1)
    app.server = server
    server.daemon_threads = True
    app.updater.check_in_background()

    url = f"http://127.0.0.1:{app.port}/"
    e = app.engine.public()
    print()
    print(f"  {APP_NAME} {APP_VERSION} is running at {url}")
    print(f"  yt-dlp {e['ytdlp'] or 'missing'}{' (updated)' if override else ''}, "
          f"{e['js'] or 'no YouTube helper'}, FFmpeg {e['ffmpeg'] or 'missing'}")
    for n in e["notices"]:
        print(f"  Note: {n}")
    print()

    shown_in_window = False
    if use_window:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        shown_in_window = open_window(url, app)  # blocks until the window closes
        if not shown_in_window and app.server:
            server.shutdown()  # restart below in the foreground for browser mode
            server.server_close()
            server = ThreadingHTTPServer(("127.0.0.1", app.port), make_handler(app))
            server.daemon_threads = True
            app.server = server

    try:
        if not shown_in_window:
            print("  Keep this window open while you use EditReady.")
            print("  To stop it, click Quit in the app or close this window.")
            print()
            if not no_browser:
                threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.manager.stop()
        try:
            server.shutdown() if shown_in_window else None
        except Exception:
            pass
        server.server_close()
        print("  EditReady stopped.")


if __name__ == "__main__":
    main()
