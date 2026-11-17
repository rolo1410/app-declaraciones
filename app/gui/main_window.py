"""Ventana principal: selector de cliente y cuatro pestañas.

    Clientes  ·  Descarga  →  Análisis  →  Declaración

Flujo: descargar los XML del SRI, analizarlos y enviarlos a la declaración para
calcular los casilleros del formulario de IVA.
"""
from __future__ import annotations

import os
import platform

import tkinter as tk
from tkinter import ttk

from .contexto import ContextoCliente
from .pestana_analisis import PestanaAnalisis
from .pestana_clientes import PestanaClientes
from .pestana_declaracion import PestanaDeclaracion
from .pestana_descarga import PestanaDescarga
from .selector_cliente import SelectorCliente

TITULO = "Comprobantes SRI — Descarga, Análisis y Declaración de IVA"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(TITULO)
        self.geometry("1180x760")
        self.minsize(980, 640)

        # Cliente activo compartido por todas las pestañas.
        self.contexto = ContextoCliente(self)
        SelectorCliente(self, self.contexto, on_gestionar=self._ir_a_clientes).pack(fill="x")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.notebook = notebook

        # Las pestañas se crean en orden de flujo y se enlazan entre sí.
        ctx = self.contexto
        self.pestana_clientes = PestanaClientes(notebook, ctx)
        self.pestana_declaracion = PestanaDeclaracion(notebook, contexto=ctx)
        self.pestana_analisis = PestanaAnalisis(
            notebook, on_enviar_declaracion=self._enviar_a_declaracion, contexto=ctx)
        self.pestana_descarga = PestanaDescarga(
            notebook, on_descarga_completa=self._descarga_completa, contexto=ctx)

        notebook.add(self.pestana_clientes, text="  Clientes  ")
        notebook.add(self.pestana_descarga, text="  1 · Descarga  ")
        notebook.add(self.pestana_analisis, text="  2 · Análisis  ")
        notebook.add(self.pestana_declaracion, text="  3 · Declaración  ")

        # En macOS, una app lanzada fuera de un bundle .app no se activa sola:
        # el primer clic solo enfoca la ventana en vez de accionar el control.
        # Traerla al frente y darle foco evita esa sensación de "no hace clic".
        self.after(200, self._traer_al_frente)

        # Retomar el último cliente usado. Se abre en «Descarga», como antes.
        ultimo = ctx.ultimo_cliente()
        if ultimo is not None:
            ctx.fijar(ultimo)
        notebook.select(self.pestana_descarga)

    def _ir_a_clientes(self) -> None:
        self.notebook.select(self.pestana_clientes)

    def _traer_al_frente(self) -> None:
        """Activa la ventana en macOS cuando se lanza desde la terminal.

        Sin esto la app no queda como aplicación frontal y el primer clic sobre
        un control (p. ej. el texto de un botón) solo sirve para activar la
        ventana en vez de accionarlo. En el ejecutable empaquetado (.app) macOS
        ya la activa y esto no hace falta.
        """
        try:
            self.lift()
            self.focus_force()
        except Exception:  # noqa: BLE001
            pass
        if platform.system() != "Darwin":
            return
        try:
            import subprocess

            subprocess.run(
                ["osascript", "-e",
                 "tell application \"System Events\" to set frontmost of "
                 f"(first process whose unix id is {os.getpid()}) to true"],
                check=False, capture_output=True, timeout=3,
            )
        except Exception:  # noqa: BLE001
            pass

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
