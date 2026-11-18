"""Navegación: barra superior y contenedor de páginas (sin barra lateral).

El inicio es «Clientes»: ahí se elige cliente y mes. Las etapas del mes
(Descarga y Declaración) se abren desde la ficha del cliente, y la barra
superior muestra en cada momento dónde se está:

    Inicio:   Clientes  (descripción)
    Trabajo:  [‹ Clientes]  NOMBRE · octubre 2026        [1 Descarga][2 Declaración]

Configuración no está aquí: se abre desde el menú (⌘, en macOS).
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import font, ttk
from typing import Callable

ES_MAC = sys.platform == "darwin"


def colores(raiz) -> dict[str, str]:
    """Colores del sistema en macOS (siguen el modo claro/oscuro)."""
    if ES_MAC:
        return {"fondo": "systemWindowBackgroundColor", "texto": "systemTextColor",
                "secundario": "#8e8e93", "hover": "systemWindowBackgroundColor1",
                "sel_fondo": "systemUnemphasizedSelectedContentBackgroundColor",
                "linea": "systemWindowBackgroundColor3"}
    fondo = ttk.Style(raiz).lookup("TFrame", "background") or "#ececec"
    return {"fondo": fondo, "texto": "#1f2328", "secundario": "#6b7280", "hover": "#e4e6e9",
            "sel_fondo": "#d5d8dc", "linea": "#c8ccd1"}


class Paginas(ttk.Frame):
    """Páginas apiladas en la misma celda; solo se ve la seleccionada.

    Misma interfaz que usaba el ``ttk.Notebook`` (``add``, ``select`` y el
    evento ``<<NotebookTabChanged>>``), pero sin pestañas ni bordes.
    """

    def __init__(self, master, **opciones) -> None:
        super().__init__(master, **opciones)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._paginas: list = []
        self._actual = ""

    def add(self, widget, text: str = "") -> None:
        self._paginas.append(widget)
        widget.grid(row=0, column=0, sticky="nsew")
        if not self._actual:
            self._actual = str(widget)
        else:
            widget.grid_remove()

    def select(self, widget=None) -> str:
        if widget is None:
            return self._actual
        destino = str(widget)
        if destino != self._actual:
            for w in self._paginas:
                if str(w) == destino:
                    w.grid()
                else:
                    w.grid_remove()
            self._actual = destino
            self.event_generate("<<NotebookTabChanged>>")
        return destino


class _Paso(tk.Frame):
    """Botón de etapa («1 Descarga») con la seleccionada en gris suave, como Finder."""

    def __init__(self, master, numero: str, texto: str, c: dict, al_elegir) -> None:
        super().__init__(master, background=c["fondo"])
        self.c, self._sel, self._hover = c, False, False
        base = font.nametofont("TkDefaultFont").actual()
        self.lbl_num = tk.Label(self, text=numero, background=c["fondo"],
                                foreground=c["secundario"], font=(base["family"], base["size"],
                                                                  "bold"))
        self.lbl_num.pack(side="left", padx=(12, 6), pady=6)
        self.lbl = tk.Label(self, text=texto, background=c["fondo"], foreground=c["texto"],
                            font=(base["family"], base["size"]))
        self.lbl.pack(side="left", padx=(0, 14), pady=6)
        for w in (self, self.lbl_num, self.lbl):
            w.bind("<Button-1>", lambda _e: al_elegir())
            w.bind("<Enter>", lambda _e: self._fijar(hover=True))
            w.bind("<Leave>", lambda _e: self._fijar(hover=False))

    def _fijar(self, sel: bool | None = None, hover: bool | None = None) -> None:
        if sel is not None:
            self._sel = sel
        if hover is not None:
            self._hover = hover
        fondo = self.c["sel_fondo"] if self._sel else (
            self.c["hover"] if self._hover else self.c["fondo"])
        for w in (self, self.lbl_num, self.lbl):
            w.configure(background=fondo)
        base = font.nametofont("TkDefaultFont").actual()
        self.lbl.configure(font=(base["family"], base["size"], "bold" if self._sel else "normal"))

    def seleccionar(self, valor: bool) -> None:
        self._fijar(sel=valor)


@dataclass
class Pagina:
    widget: tk.Widget
    titulo: str
    descripcion: str = ""
    tipo: str = "inicio"        # inicio | etapa
    numero: str = ""            # para las etapas: «1», «2»
    extra: dict = field(default_factory=dict)


class BarraSuperior(ttk.Frame):
    """Título o miga de pan («‹ Clientes  NOMBRE · mes») y etapas del mes."""

    def __init__(self, master, raiz, paginas: Paginas, contexto,
                 al_volver: Callable[[], None]) -> None:
        super().__init__(master, padding=(18, 12, 18, 10))
        self.raiz, self.paginas, self.contexto = raiz, paginas, contexto
        self.c = colores(raiz)
        self._registro: dict[str, Pagina] = {}
        self._pasos: dict[str, _Paso] = {}
        familia = font.nametofont("TkDefaultFont").actual("family")

        self.btn_volver = ttk.Button(self, text="‹ Clientes", command=al_volver)
        self.izq = ttk.Frame(self)
        self.izq.pack(side="left", fill="x", expand=True)
        self.lbl_titulo = ttk.Label(self.izq, font=(familia, 20 if ES_MAC else 16, "bold"))
        self.lbl_titulo.pack(anchor="w")
        self.lbl_desc = ttk.Label(self.izq, foreground="gray")
        self.lbl_desc.pack(anchor="w", pady=(2, 0))

        self.pasos = tk.Frame(self, background=self.c["fondo"])
        self.pasos.pack(side="right")

        paginas.bind("<<NotebookTabChanged>>", lambda _e: self.actualizar(), add="+")
        contexto.al_cambiar_cliente(self.actualizar)
        contexto.al_cambiar_periodo(self.actualizar)

    def agregar(self, pagina: Pagina) -> None:
        self.paginas.add(pagina.widget, text=pagina.titulo)
        self._registro[str(pagina.widget)] = pagina
        if pagina.tipo == "etapa":
            paso = _Paso(self.pasos, pagina.numero, pagina.titulo, self.c,
                         lambda w=pagina.widget: self.ir(w))
            paso.pack(side="left", padx=2)
            self._pasos[str(pagina.widget)] = paso
        self.actualizar()

    def ir(self, widget) -> None:
        # Con un formulario modal abierto no se cambia de página.
        if getattr(self.raiz, "pila_dialogos", None):
            return
        self.paginas.select(widget)

    def actualizar(self) -> None:
        pagina = self._registro.get(self.paginas.select())
        if pagina is None:
            return
        for clave, paso in self._pasos.items():
            paso.seleccionar(clave == str(pagina.widget))
        if pagina.tipo == "inicio":
            self.btn_volver.pack_forget()
            self.pasos.pack_forget()
            self.lbl_titulo.configure(text=pagina.titulo)
            self.lbl_desc.configure(text=pagina.descripcion)
            return
        self.btn_volver.pack(side="left", padx=(0, 14), before=self.izq)
        self.pasos.pack(side="right")
        cliente = self.contexto.cliente
        if cliente is None:
            self.lbl_titulo.configure(text="Sin cliente")
            self.lbl_desc.configure(text="RUC, clave y carpeta se ingresan a mano. "
                                         "Elija un cliente y mes en «Clientes».")
            return
        from ..core.informe import nombre_periodo

        self.lbl_titulo.configure(text=cliente.nombre)
        mes = nombre_periodo(self.contexto.periodo) if self.contexto.periodo else "sin mes elegido"
        self.lbl_desc.configure(text=f"RUC {cliente.ruc} · {mes}")
