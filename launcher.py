"""Punto de entrada para el ejecutable empaquetado (PyInstaller).

Se usa un lanzador de nivel superior con imports absolutos porque ``app/main.py``
emplea imports relativos (``from .core import …``), que fallan si PyInstaller lo
toma como script ``__main__``. En desarrollo se sigue usando ``python -m app.main``.
"""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
