"""Utilidades compartidas por la interfaz gráfica: recursos e imágenes."""
from __future__ import annotations

import os
import sys

import tkinter as tk

# Raíz del proyecto (…/DECLARACIONES), dos niveles por encima de app/gui/.
_RAIZ_PROYECTO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ruta_recurso(nombre: str) -> str:
    """Ruta a un archivo de ``assets/``, compatible con PyInstaller.

    En el ejecutable empaquetado los recursos viven en ``sys._MEIPASS/assets``
    (ver ``--add-data assets``); en desarrollo, en la raíz del proyecto.
    """
    base = getattr(sys, "_MEIPASS", _RAIZ_PROYECTO)
    return os.path.join(base, "assets", nombre)


def cargar_imagen(nombre: str, subsample: int = 1) -> "tk.PhotoImage | None":
    """Carga un PNG de ``assets/`` como PhotoImage (o None si no está)."""
    try:
        img = tk.PhotoImage(file=ruta_recurso(nombre))
        return img.subsample(subsample, subsample) if subsample > 1 else img
    except Exception:  # noqa: BLE001 - sin recurso => la app sigue funcionando
        return None


def fmt(valor: float) -> str:
    """Formatea un monto con separador de miles y 2 decimales."""
    return f"{valor:,.2f}"
