#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  /usr/bin/python3 -m venv .venv
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  echo "虚拟环境创建失败，请检查 Python3 是否可用。"
  exit 1
fi

if ! "$VENV_PY" -m pip show uvicorn >/dev/null 2>&1; then
  "$VENV_PY" -m pip install -r requirements.txt
fi

exec "$VENV_PY" launcher.py
