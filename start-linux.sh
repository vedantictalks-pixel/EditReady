#!/bin/bash
# EditReady launcher for Linux. Run:  bash start-linux.sh
# Needs Python 3.11+ with venv (Debian/Ubuntu: sudo apt install python3 python3-venv).
# Optional, for the "Choose..." folder button: sudo apt install zenity   (or python3-tk)
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.editready/venv"
echo ""
echo "  EditReady"
echo ""

PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  p="$(command -v "$c" 2>/dev/null)" || continue
  if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then PY="$p"; break; fi
done
if [ -z "$PY" ]; then
  echo "  EditReady needs Python 3.11 or newer. Install it with your package manager, then run this again."
  exit 1
fi

FIRST=0
if [ ! -x "$VENV/bin/python" ]; then
  FIRST=1
  echo "  First start: setting up. This downloads about 100 MB, one time only."
  mkdir -p "$HOME/.editready"
  "$PY" -m venv "$VENV" || { echo "  Couldn't create the app environment. On Debian/Ubuntu run: sudo apt install python3-venv"; exit 1; }
fi

echo "  Checking for engine updates..."
QUIET="-q"; [ "$FIRST" = "1" ] && QUIET=""
if ! "$VENV/bin/python" -m pip install --disable-pip-version-check $QUIET -U -r requirements.txt; then
  if [ "$FIRST" = "1" ]; then rm -rf "$VENV"; echo "  Setup failed. Check your internet connection and try again."; exit 1; fi
  echo "  Couldn't check for updates (offline?). Starting with the current engine."
fi

exec "$VENV/bin/python" app.py
