"""Diálogos modales: alta de cliente, clave y frase de paso.

Ninguno muestra una clave ya guardada: solo permiten escribir una nueva.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from ..core import cifrado
from ..core import ruc as ruc_mod


class _Dialogo(ttk.Frame):
    """Base de los diálogos: una tarjeta dentro de la ventana principal.

    No se usa una ventana aparte (``Toplevel``): en macOS, con Tk 8.6, arrastrar
    un diálogo modal lo devolvía a su sitio o dejaba el cursor ocupado y el
    formulario sin responder. Aquí el diálogo cubre toda la ventana principal
    (nada debajo recibe clics), se centra como una tarjeta y es modal a su
    modo: el menú queda deshabilitado y Tab recorre solo sus campos.
    """

    def __init__(self, padre, titulo: str) -> None:
        raiz = padre.winfo_toplevel()
        super().__init__(raiz)
        self._raiz = raiz
        self.resultado = None
        self._menu_previo: list[tuple[tk.Menu, int, str]] = []
        self._abierto = False

        tarjeta = ttk.Labelframe(self, text=f"  {titulo}  ", padding=(18, 12, 18, 16),
                                 style="Dialogo.TLabelframe")
        tarjeta.place(relx=0.5, rely=0.42, anchor="center")
        self.cuerpo = ttk.Frame(tarjeta)
        self.cuerpo.pack(fill="both", expand=True)
        estilo = ttk.Style(raiz)
        negrita = ("TkDefaultFont", 14, "bold") if sys.platform == "darwin" \
            else ("TkDefaultFont", 11, "bold")
        estilo.configure("Dialogo.TLabelframe.Label", font=negrita)


    def _botones(self, fila: int, texto_ok: str = "Aceptar") -> None:
        barra = ttk.Frame(self.cuerpo)
        barra.grid(row=fila, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(barra, text="Cancelar", command=self.cancelar).pack(side="right")
        ttk.Button(barra, text=texto_ok, command=self.aceptar,
                   default="active").pack(side="right", padx=6)
        self.lbl_error = ttk.Label(self.cuerpo, text="", foreground="#c0392b", wraplength=420,
                                   justify="left")
        self.lbl_error.grid(row=fila - 1, column=0, columnspan=3, sticky="w")

    # -- teclado -------------------------------------------------------------------
    def _descendientes(self, w=None):
        for hijo in (w or self).winfo_children():
            yield hijo
            yield from self._descendientes(hijo)

    def _enfocables(self) -> list:
        tipos = ("TEntry", "TButton", "TCheckbutton", "TCombobox", "TRadiobutton", "Entry")
        return [w for w in self._descendientes()
                if w.winfo_class() in tipos and str(w.cget("state")) != "disabled"]

    def _ciclar(self, evento, paso: int) -> str:
        lista = self._enfocables()
        if lista:
            i = lista.index(evento.widget) if evento.widget in lista else -paso
            lista[(i + paso) % len(lista)].focus_set()
        return "break"

    def _enter(self, evento) -> str:
        if evento.widget.winfo_class() == "TButton" and self._contiene(evento.widget):
            evento.widget.invoke()  # Enter sobre «Cancelar» cancela
        else:
            self.aceptar()
        return "break"

    def _contiene(self, w) -> bool:
        return str(w).startswith(str(self) + ".")

    # Las teclas se enlazan a la ventana principal (no a cada campo) para que
    # funcionen aunque el foco haya quedado debajo de la cubierta. Con diálogos
    # anidados manda el de arriba de la pila.
    _TECLAS = ("<Escape>", "<Return>", "<KP_Enter>", "<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>")

    def _instalar_teclas(self) -> None:
        r = self._raiz
        r.bind("<Escape>", lambda _e: (self.cancelar(), "break")[1])
        r.bind("<Return>", self._enter)
        r.bind("<KP_Enter>", self._enter)
        r.bind("<Tab>", lambda e: self._ciclar(e, 1))
        for seq in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            r.bind(seq, lambda e: self._ciclar(e, -1))

    def _quitar_teclas(self) -> None:
        for seq in self._TECLAS:
            self._raiz.unbind(seq)

    # -- mostrar / cerrar ----------------------------------------------------------
    def _bloquear_menu(self) -> None:
        nombre = self._raiz.cget("menu")
        if not nombre:
            return
        barra = self._raiz.nametowidget(nombre)
        fin = barra.index("end")
        for i in range(0 if fin is None else fin + 1):
            if barra.type(i) == "cascade":
                self._menu_previo.append((barra, i, barra.entrycget(i, "state")))
                barra.entryconfigure(i, state="disabled")

    def _restaurar_menu(self) -> None:
        for barra, i, estado in self._menu_previo:
            try:
                barra.entryconfigure(i, state=estado)
            except tk.TclError:
                pass
        self._menu_previo.clear()

    def mostrar(self):
        self.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.lift()
        self._abierto = True
        pila = self._pila()
        pila.append(self)
        self._raiz.dialogos_abiertos = len(pila)
        self._bloquear_menu()
        self._instalar_teclas()
        self.update_idletasks()
        actual = self.focus_get()
        foco = actual if actual is not None and self._contiene(actual) else None
        (foco or (self._enfocables() or [self])[0]).focus_force()
        self.wait_window(self)
        return self.resultado

    def _pila(self) -> list:
        if not hasattr(self._raiz, "pila_dialogos"):
            self._raiz.pila_dialogos = []
        return self._raiz.pila_dialogos

    def destroy(self) -> None:
        if self._abierto:
            self._abierto = False
            self._restaurar_menu()
            pila = self._pila()
            if self in pila:
                pila.remove(self)
            self._raiz.dialogos_abiertos = len(pila)
            if pila:
                pila[-1]._instalar_teclas()
            else:
                self._quitar_teclas()
        super().destroy()

    def error(self, texto: str) -> None:
        self.lbl_error.configure(text=texto)

    def aceptar(self) -> None:  # pragma: no cover - lo redefinen las subclases
        self.destroy()

    def cancelar(self) -> None:
        self.resultado = None
        self.destroy()


def tras_el_clic(widget, accion):
    """``command=`` para un botón o menú que abre un diálogo.

    En macOS, Tk mantiene el mouse «capturado» por el botón pulsado hasta que
    termina de atender el clic. Si el diálogo espera respuesta *dentro* de ese
    clic, la captura no se suelta y los clics no llegan al formulario. Se abre
    un instante después, ya fuera del clic.
    """
    return lambda: widget.after(1, accion)


def _entrada_clave(padre, fila: int, etiqueta: str) -> tk.StringVar:
    ttk.Label(padre, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=4)
    var = tk.StringVar()
    ttk.Entry(padre, textvariable=var, show="•", width=34).grid(
        row=fila, column=1, sticky="w", padx=8)
    return var


class DialogoNuevoCliente(_Dialogo):
    def __init__(self, padre, ruc_inicial: str = "", clave_inicial: str = "") -> None:
        super().__init__(padre, "Nuevo cliente")
        c = self.cuerpo
        ttk.Label(c, text="RUC:").grid(row=0, column=0, sticky="w", pady=4)
        self.var_ruc = tk.StringVar(value=ruc_inicial)
        self.ent_ruc = ttk.Entry(c, textvariable=self.var_ruc, width=34)
        self.ent_ruc.grid(row=0, column=1, sticky="w", padx=8)
        self.lbl_info = ttk.Label(c, text="", foreground="gray", wraplength=420, justify="left")
        self.lbl_info.grid(row=1, column=1, sticky="w", padx=8)
        ttk.Label(c, text="Nombre / razón social:").grid(row=2, column=0, sticky="w", pady=4)
        self.var_nombre = tk.StringVar()
        ttk.Entry(c, textvariable=self.var_nombre, width=34).grid(
            row=2, column=1, sticky="w", padx=8)
        self.var_clave = _entrada_clave(c, 3, "Clave SRI en línea:")
        self.var_clave2 = _entrada_clave(c, 4, "Repita la clave:")
        if clave_inicial:
            self.var_clave.set(clave_inicial)
            self.var_clave2.set(clave_inicial)
        ttk.Label(c, text="La clave se guarda cifrada y no se podrá volver a ver.",
                  foreground="gray").grid(row=5, column=1, sticky="w", padx=8)
        self._botones(7, "Registrar")
        self.var_ruc.trace_add("write", lambda *_: self._analizar())
        self._analizar()
        self.ent_ruc.focus_set()

    def _analizar(self) -> None:
        texto = "".join(self.var_ruc.get().split())
        if len(texto) < 13:
            self.lbl_info.configure(text="13 dígitos (persona natural: cédula + 001).",
                                    foreground="gray")
            return
        try:
            info = ruc_mod.analizar(texto)
        except ruc_mod.RucInvalido as e:
            self.lbl_info.configure(text=str(e), foreground="#c0392b")
            return
        msg = f"{ruc_mod.NOMBRES_TIPO[info.tipo]} · carpeta «{info.carpeta}»"
        if info.advertencias:
            msg += "\n⚠ " + " ".join(info.advertencias)
        self.lbl_info.configure(text=msg, foreground="#b9770e" if info.advertencias else "gray")

    def aceptar(self) -> None:
        try:
            ruc_mod.analizar(self.var_ruc.get())
        except ruc_mod.RucInvalido as e:
            self.error(str(e))
            return
        if not self.var_nombre.get().strip():
            self.error("Escriba el nombre o la razón social.")
            return
        if not self.var_clave.get():
            self.error("Escriba la clave de SRI en línea.")
            return
        if self.var_clave.get() != self.var_clave2.get():
            self.error("Las claves no coinciden.")
            return
        self.resultado = ("".join(self.var_ruc.get().split()),
                          self.var_nombre.get().strip(), self.var_clave.get())
        self.destroy()


class DialogoClave(_Dialogo):
    def __init__(self, padre, titulo: str, texto: str) -> None:
        super().__init__(padre, titulo)
        ttk.Label(self.cuerpo, text=texto, wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.var_clave = _entrada_clave(self.cuerpo, 1, "Clave nueva:")
        self.var_clave2 = _entrada_clave(self.cuerpo, 2, "Repita la clave:")
        self._botones(4, "Guardar")

    def aceptar(self) -> None:
        if not self.var_clave.get():
            self.error("Escriba la clave.")
            return
        if self.var_clave.get() != self.var_clave2.get():
            self.error("Las claves no coinciden.")
            return
        self.resultado = self.var_clave.get()
        self.destroy()


class DialogoFrase(_Dialogo):
    def __init__(self, padre, titulo: str, texto: str, confirmar: bool) -> None:
        super().__init__(padre, titulo)
        self.confirmar = confirmar
        ttk.Label(self.cuerpo, text=texto, wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.var_frase = _entrada_clave(self.cuerpo, 1, "Frase de paso:")
        self.var_frase2 = _entrada_clave(self.cuerpo, 2, "Repita la frase:") if confirmar else None
        if confirmar:
            ttk.Label(
                self.cuerpo, foreground="gray", justify="left", wraplength=440,
                text=f"Mínimo {cifrado.LARGO_MINIMO_FRASE} caracteres. Use varias palabras. "
                     "Si la olvida no se puede recuperar.",
            ).grid(row=3, column=0, columnspan=3, sticky="w")
        self._botones(5)

    def aceptar(self) -> None:
        frase = self.var_frase.get()
        if self.confirmar:
            if len(frase) < cifrado.LARGO_MINIMO_FRASE:
                self.error(f"La frase debe tener al menos {cifrado.LARGO_MINIMO_FRASE} caracteres.")
                return
            if frase != self.var_frase2.get():
                self.error("Las frases no coinciden.")
                return
        elif not frase:
            self.error("Escriba la frase de paso.")
            return
        self.resultado = frase
        self.destroy()


class DialogoTexto(_Dialogo):
    def __init__(self, padre, titulo: str, texto: str, inicial: str = "") -> None:
        super().__init__(padre, titulo)
        ttk.Label(self.cuerpo, text=texto, wraplength=440, justify="left").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        self.var = tk.StringVar(value=inicial)
        entrada = ttk.Entry(self.cuerpo, textvariable=self.var, width=44)
        entrada.grid(row=1, column=0, columnspan=3, sticky="we")
        entrada.select_range(0, "end")
        entrada.focus_set()
        self._botones(3)

    def aceptar(self) -> None:
        if not self.var.get().strip():
            self.error("Escriba un valor.")
            return
        self.resultado = self.var.get().strip()
        self.destroy()


def pedir_texto(padre, titulo: str, texto: str, inicial: str = "") -> str | None:
    return DialogoTexto(padre, titulo, texto, inicial).mostrar()


def pedir_cliente_nuevo(padre, ruc: str = "", clave: str = ""):
    """``(ruc, nombre, clave)`` o ``None`` si se cancela."""
    return DialogoNuevoCliente(padre, ruc, clave).mostrar()


def pedir_clave(padre, titulo: str, texto: str) -> str | None:
    return DialogoClave(padre, titulo, texto).mostrar()


def pedir_frase(padre, titulo: str, texto: str, confirmar: bool) -> str | None:
    return DialogoFrase(padre, titulo, texto, confirmar).mostrar()


def tipos_archivo(*tipos: tuple[str, str]) -> list[tuple[str, str]]:
    """``filetypes`` seguros para los diálogos de archivo de Tk.

    En macOS, Tk 8.6 traduce cada extensión a un tipo del sistema y, con una
    extensión doble como ``*.iva.json``, obtiene ``nil`` y la app se cierra
    (NSInvalidArgumentException). Allí se filtra solo por la última extensión
    (``*.json``) y se quitan los patrones repetidos que eso produce.
    """
    if sys.platform != "darwin":
        return list(tipos)
    vistos: set[str] = set()
    seguros = []
    for nombre, patron in tipos:
        if patron.startswith("*.") and patron.count(".") > 1:
            patron = "*." + patron.rsplit(".", 1)[1]
        if patron not in vistos:
            vistos.add(patron)
            seguros.append((nombre, patron))
    return seguros
