"""Punto d'ingresso per la versione portabile (PyInstaller): equivale a `python -m rationalis`."""
import sys

from rationalis.ui.app import main

if __name__ == "__main__":
    sys.exit(main())
