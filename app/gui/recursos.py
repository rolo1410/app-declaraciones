"""Utilidades compartidas por la interfaz gráfica."""
from __future__ import annotations

import sys
from pathlib import Path

# En el ejecutable de PyInstaller los «assets» viajan dentro de _MEIPASS.
_RAIZ = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def ruta_asset(nombre: str) -> Path:
    return _RAIZ / "assets" / nombre


def poner_icono(ventana) -> None:
    """Ícono de la ventana (y del Dock en macOS al ejecutar desde la terminal).

    macOS usa la versión con margen de la losa; Windows y Linux la versión sin
    margen, pensada para 16–32 px en la barra de tareas.
    """
    import tkinter as tk

    nombre = "icon.png" if sys.platform == "darwin" else "icon_ventana.png"
    try:
        imagen = tk.PhotoImage(master=ventana, file=str(ruta_asset(nombre)))
    except (tk.TclError, OSError):
        return  # sin ícono la app funciona igual
    ventana._icono = imagen  # evitar que el recolector libere la imagen
    ventana.iconphoto(True, imagen)


def fmt(valor: float) -> str:
    """Formatea un monto con separador de miles y 2 decimales."""
    return f"{valor:,.2f}"
