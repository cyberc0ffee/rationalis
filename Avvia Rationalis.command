#!/bin/bash
# Avvia Rationalis dal sorgente su macOS (o Linux). Al primo avvio crea un ambiente Python in .venv e installa
# le librerie (serve Python 3.11 o successivo, ad esempio da python.org). Per renderlo cliccabile nel Finder:
#   chmod +x "Avvia Rationalis.command"
cd "$(dirname "$0")" || exit 1
PY=python3
if [ ! -x .venv/bin/python ]; then
  "$PY" -m venv .venv || { echo "Serve Python 3.11 o successivo (python.org)"; exit 1; }
  .venv/bin/python -m pip install --upgrade pip >/dev/null
  .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python -m rationalis "$@"
