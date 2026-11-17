"""Diálogos modales: alta de cliente, clave y frase de paso.

Ninguno muestra una clave ya guardada: solo permiten escribir una nueva.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ..core import cifrado
from ..core import ruc as ruc_mod


class _Dialogo(tk.Toplevel):
    def __init__(self, padre, titulo: str) -> None:
        super().__init__(padre)
        self.title(titulo)
        self.transient(padre.winfo_toplevel())
        self.resizable(False, False)
        self.resultado = None
        self.cuerpo = ttk.Frame(self, padding=14)
        self.cuerpo.pack(fill="both", expand=True)
        self.protocol("WM_DELETE_WINDOW", self.cancelar)
        self.bind("<Escape>", lambda _e: self.cancelar())
        self.bind("<Return>", lambda _e: self.aceptar())

    def _botones(self, fila: int, texto_ok: str = "Aceptar") -> None:
        barra = ttk.Frame(self.cuerpo)
        barra.grid(row=fila, column=0, columnspan=3, sticky="e", pady=(12, 0))
        ttk.Button(barra, text="Cancelar", command=self.cancelar).pack(side="right")
        ttk.Button(barra, text=texto_ok, command=self.aceptar).pack(side="right", padx=6)
        self.lbl_error = ttk.Label(self.cuerpo, text="", foreground="#c0392b", wraplength=420,
                                   justify="left")
        self.lbl_error.grid(row=fila - 1, column=0, columnspan=3, sticky="w")

    def mostrar(self):
        self.update_idletasks()
        padre = self.master.winfo_toplevel()
        x = padre.winfo_rootx() + (padre.winfo_width() - self.winfo_width()) // 2
        y = padre.winfo_rooty() + (padre.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        self.grab_set()
        self.focus_force()
        self.wait_window()
        return self.resultado

    def error(self, texto: str) -> None:
        self.lbl_error.configure(text=texto)

    def aceptar(self) -> None:  # pragma: no cover - lo redefinen las subclases
        self.destroy()

    def cancelar(self) -> None:
        self.resultado = None
        self.destroy()


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


def pedir_cliente_nuevo(padre, ruc: str = "", clave: str = ""):
    """``(ruc, nombre, clave)`` o ``None`` si se cancela."""
    return DialogoNuevoCliente(padre, ruc, clave).mostrar()


def pedir_clave(padre, titulo: str, texto: str) -> str | None:
    return DialogoClave(padre, titulo, texto).mostrar()


def pedir_frase(padre, titulo: str, texto: str, confirmar: bool) -> str | None:
    return DialogoFrase(padre, titulo, texto, confirmar).mostrar()
