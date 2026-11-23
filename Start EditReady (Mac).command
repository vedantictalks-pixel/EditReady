#!/bin/bash
# EditReady launcher for macOS. Double-click this file to start EditReady.
# First start: installs the free engine (about 100 MB) into ~/.editready.
cd "$(dirname "$0")" || exit 1
VENV="$HOME/.editready/venv"
clear
echo ""
echo "  EditReady"
echo ""

find_python() {
  for c in python3.14 python3.13 python3.12 python3.11 python3 \
           /Library/Frameworks/Python.framework/Versions/Current/bin/python3 \
           /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    p="$(command -v "$c" 2>/dev/null)" || continue
    # Skip Apple's /usr/bin/python3: it's too old and may pop up an installer.
    [ "$p" = "/usr/bin/python3" ] && continue
    if "$p" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      echo "$p"; return 0
    fi
  done
  return 1
}

PY="$(find_python)" || {
  echo "  EditReady needs Python 3.11 or newer. It's free."
  echo "  1. Download it from https://www.python.org/downloads/"
  echo "  2. Install it, then double-click this file again."
  open "https://www.python.org/downloads/" 2>/dev/null
  echo ""
  read -r -p "  Press Return to close this window. "
  exit 1
}

FIRST=0
if [ ! -x "$VENV/bin/python" ]; then
  FIRST=1
  echo "  First start: setting up. This downloads about 100 MB, one time only."
  mkdir -p "$HOME/.editready"
  "$PY" -m venv "$VENV" || { echo "  Couldn't create the app environment."; read -r -p "  Press Return to close. "; exit 1; }
fi

echo "  Checking for engine updates..."
if [ "$FIRST" = "1" ]; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check -U -r requirements.txt
else
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q -U -r requirements.txt
fi
if [ $? -ne 0 ]; then
  if [ "$FIRST" = "1" ]; then
    rm -rf "$VENV"
    echo "  Setup failed. Check your internet connection and double-click this file again."
    read -r -p "  Press Return to close. "
    exit 1
  fi
  echo "  Couldn't check for updates (offline?). Starting with the current engine."
fi

"$VENV/bin/python" app.py
echo ""
read -r -p "  Press Return to close this window. "
