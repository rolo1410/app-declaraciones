"""Ventana principal: una sola app con tres pestañas.

    Descarga  →  Análisis  →  Declaración

Flujo: descargar los XML del SRI, analizarlos y enviarlos a la declaración para
calcular los casilleros del formulario de IVA.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .pestana_analisis import PestanaAnalisis
from .pestana_declaracion import PestanaDeclaracion
from .pestana_descarga import PestanaDescarga
from .recursos import cargar_imagen

TITULO = "Comprobantes SRI — Descarga, Análisis y Declaración de IVA"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(TITULO)
        self.geometry("1180x760")
        self.minsize(980, 640)

        # Ícono de la aplicación (ventana / barra de tareas).
        self._icono = cargar_imagen("icon.png")
        if self._icono is not None:
            try:
                self.iconphoto(True, self._icono)
            except Exception:  # noqa: BLE001
                pass

        # Encabezado con el logo (branding).
        banner = tk.Frame(self, bg="white")
        banner.pack(fill="x")
        self._logo = cargar_imagen("icon.png", subsample=8)  # 512 -> ~64 px
        if self._logo is not None:
            tk.Label(banner, image=self._logo, bg="white").pack(side="left", padx=10, pady=6)
        tk.Label(
            banner, text="Comprobantes SRI — IVA Ecuador",
            bg="white", fg="#4a8b5c", font=("Helvetica", 15, "bold"),
        ).pack(side="left", pady=6)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.notebook = notebook

        # Las pestañas se crean en orden de flujo y se enlazan entre sí.
        self.pestana_declaracion = PestanaDeclaracion(notebook)
        self.pestana_analisis = PestanaAnalisis(
            notebook, on_enviar_declaracion=self._enviar_a_declaracion)
        self.pestana_descarga = PestanaDescarga(
            notebook, on_descarga_completa=self._descarga_completa)

        notebook.add(self.pestana_descarga, text="  1 · Descarga  ")
        notebook.add(self.pestana_analisis, text="  2 · Análisis  ")
        notebook.add(self.pestana_declaracion, text="  3 · Declaración  ")

    # -- enlaces entre pestañas --
    def _descarga_completa(self, carpeta: str) -> None:
        """Tras descargar, apunta la pestaña de Análisis a la carpeta y la muestra."""
        self.pestana_analisis.cargar_carpeta(carpeta)
        self.notebook.select(self.pestana_analisis)

    def _enviar_a_declaracion(self, comps_xml) -> None:
        """Pasa los comprobantes analizados a la declaración y muestra esa pestaña."""
        self.pestana_declaracion.cargar_desde_analisis(comps_xml)
        self.notebook.select(self.pestana_declaracion)


def ejecutar_gui() -> None:
    App().mainloop()
