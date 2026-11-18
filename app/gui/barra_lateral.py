"""Barra lateral de navegación (en lugar de pestañas).

    Cliente  [combo]
    ─────────────────
    Trabajo del mes
      1  Descarga
      2  Análisis
      3  Declaración
    Gestión
         Clientes
    …
         Configuración   (abajo)

Las páginas siguen viviendo en un ``ttk.Notebook`` con las pestañas ocultas:
así todo lo que ya cambia de página con ``notebook.select()`` (tras una
descarga, al enviar a la declaración, el menú «Ir») sigue funcionando, y la
barra solo refleja y cambia la página seleccionada.
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font, ttk

ES_MAC = sys.platform == "darwin"


def _paleta(raiz) -> dict[str, str]:
    """Colores de la barra: del sistema en macOS (siguen el modo claro/oscuro).

    La página activa se marca con un gris suave, como la barra lateral de
    Finder; el paso del mouse, con un gris aún más tenue.
    """
    fondo = ttk.Style(raiz).lookup("TFrame", "background") or "#ececec"
    if ES_MAC:
        return {"fondo": "systemWindowBackgroundColor", "texto": "systemTextColor",
                "secundario": "#8e8e93", "hover": "systemWindowBackgroundColor1",
                "sel_fondo": "systemUnemphasizedSelectedContentBackgroundColor",
                "sel_texto": "systemTextColor",
                "linea": "systemWindowBackgroundColor3"}
    return {"fondo": fondo, "texto": "#1f2328", "secundario": "#6b7280", "hover": "#e4e6e9",
            "sel_fondo": "#d5d8dc", "sel_texto": "#1f2328", "linea": "#c8ccd1"}


@dataclass
class Pagina:
    widget: tk.Widget
    titulo: str
    descripcion: str
    numero: str = ""          # «1», «2», «3» para los pasos del flujo
    grupo: str = ""           # encabezado de sección en la barra
    abajo: bool = False       # anclada al pie de la barra (Configuración)


class _Item(tk.Frame):
    """Fila clicable de la barra: número (opcional) + nombre."""

    def __init__(self, master, pagina: Pagina, colores: dict, al_elegir) -> None:
        super().__init__(master, background=colores["fondo"])
        self.pagina, self.colores, self._sel, self._hover = pagina, colores, False, False
        base = font.nametofont("TkDefaultFont")
        tamano = base.actual("size") + (1 if ES_MAC else 0)
        self.lbl_num = tk.Label(self, text=pagina.numero, width=2, anchor="e",
                                font=(base.actual("family"), tamano, "bold"),
                                background=colores["fondo"], foreground=colores["secundario"])
        self.lbl_num.pack(side="left", padx=(10, 6), pady=7)
        self.lbl = tk.Label(self, text=pagina.titulo, anchor="w",
                            font=(base.actual("family"), tamano),
                            background=colores["fondo"], foreground=colores["texto"])
        self.lbl.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=7)
        for w in (self, self.lbl_num, self.lbl):
            w.bind("<Button-1>", lambda _e: al_elegir(pagina.widget))
            w.bind("<Enter>", lambda _e: self._fijar_hover(True))
            w.bind("<Leave>", lambda _e: self._fijar_hover(False))

    def _fijar_hover(self, valor: bool) -> None:
        self._hover = valor
        self._pintar()

    def seleccionar(self, valor: bool) -> None:
        self._sel = valor
        self._pintar()

    def _pintar(self) -> None:
        c = self.colores
        if self._sel:
            fondo, texto, num = c["sel_fondo"], c["sel_texto"], c["secundario"]
        else:
            fondo = c["hover"] if self._hover else c["fondo"]
            texto, num = c["texto"], c["secundario"]
        self.configure(background=fondo)
        self.lbl.configure(background=fondo, foreground=texto)
        self.lbl_num.configure(background=fondo, foreground=num)


class Navegacion:
    """Barra lateral + encabezado de página sobre un notebook sin pestañas."""

    ANCHO = 240

    def __init__(self, raiz, notebook: ttk.Notebook, lateral: tk.Frame,
                 encabezado: ttk.Frame) -> None:
        self.raiz, self.notebook = raiz, notebook
        self.colores = _paleta(raiz)
        estilo = ttk.Style(raiz)
        estilo.layout("Oculto.TNotebook.Tab", [])
        estilo.layout("Oculto.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        notebook.configure(style="Oculto.TNotebook")

        self.lateral = lateral
        lateral.configure(background=self.colores["fondo"], width=self.ANCHO)
        self.lista = tk.Frame(lateral, background=self.colores["fondo"])
        self.lista.pack(fill="x", padx=8)
        self.pie = tk.Frame(lateral, background=self.colores["fondo"])
        self.pie.pack(side="bottom", fill="x", padx=8, pady=(0, 10))

        base = font.nametofont("TkDefaultFont").actual()
        self.lbl_titulo = ttk.Label(encabezado, font=(base["family"], 20 if ES_MAC else 16, "bold"))
        self.lbl_titulo.pack(anchor="w")
        self.lbl_desc = ttk.Label(encabezado, foreground="gray")
        self.lbl_desc.pack(anchor="w", pady=(2, 0))

        self._items: dict[str, _Item] = {}
        self._paginas: dict[str, Pagina] = {}
        self._grupo_actual = None
        notebook.bind("<<NotebookTabChanged>>", lambda _e: self._reflejar(), add="+")

    def separador(self) -> None:
        tk.Frame(self.lista, height=1, background=self.colores["linea"]).pack(
            fill="x", pady=(12, 4), padx=4)

    def agregar(self, pagina: Pagina) -> None:
        self.notebook.add(pagina.widget, text=pagina.titulo)
        destino = self.pie if pagina.abajo else self.lista
        if pagina.grupo and pagina.grupo != self._grupo_actual and not pagina.abajo:
            self._grupo_actual = pagina.grupo
            tk.Label(destino, text=pagina.grupo, anchor="w", background=self.colores["fondo"],
                     foreground=self.colores["secundario"],
                     font=(font.nametofont("TkDefaultFont").actual("family"), 11 if ES_MAC else 9,
                           "bold")).pack(fill="x", padx=10, pady=(14, 4))
        item = _Item(destino, pagina, self.colores, self.ir)
        item.pack(fill="x", pady=1)
        self._items[str(pagina.widget)] = item
        self._paginas[str(pagina.widget)] = pagina
        self._reflejar()

    def ir(self, widget) -> None:
        # Con un formulario modal abierto no se cambia de página.
        if getattr(self.raiz, "pila_dialogos", None):
            return
        self.notebook.select(widget)

    def _reflejar(self) -> None:
        actual = self.notebook.select()
        for clave, item in self._items.items():
            item.seleccionar(clave == actual)
        pagina = self._paginas.get(actual)
        if pagina:
            titulo = f"{pagina.numero} · {pagina.titulo}" if pagina.numero else pagina.titulo
            self.lbl_titulo.configure(text=titulo)
            self.lbl_desc.configure(text=pagina.descripcion)
