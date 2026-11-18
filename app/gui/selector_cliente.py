"""Barra «Cliente: [combo]» encima de las pestañas (cliente activo global)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .contexto import ContextoCliente

SIN_CLIENTE = "— Sin cliente registrado —"


def etiqueta_cliente(c) -> str:
    return f"{c.nombre} ({c.ruc})"


class SelectorCliente(ttk.Frame):
    """Combo del cliente activo.

    Horizontal (``Cliente: [combo] info [Gestionar…]``) o, con ``vertical``,
    apilado para la barra lateral (etiqueta, combo y una línea de detalle).
    """

    def __init__(self, master, contexto: ContextoCliente, on_gestionar=None,
                 vertical: bool = False) -> None:
        super().__init__(master, padding=0 if vertical else (8, 6, 8, 2))
        self.contexto = contexto
        self._por_etiqueta: dict = {}
        self.vertical = vertical

        lado = {} if vertical else {"side": "left"}
        ttk.Label(self, text="Cliente", foreground="gray" if vertical else "").pack(
            anchor="w", **lado)
        self.var = tk.StringVar(value=SIN_CLIENTE)
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly",
                                  width=24 if vertical else 48)
        self.combo.pack(fill="x" if vertical else "none", pady=(4, 0) if vertical else 0,
                        padx=0 if vertical else 6, **lado)
        self.combo.bind("<<ComboboxSelected>>", self._elegido)
        self.lbl_info = ttk.Label(self, text="", foreground="gray",
                                  wraplength=200 if vertical else 0, justify="left")
        self.lbl_info.pack(anchor="w", pady=(4, 0) if vertical else 0,
                           padx=0 if vertical else 6, **lado)
        if on_gestionar is not None and not vertical:
            ttk.Button(self, text="Gestionar clientes…", command=on_gestionar).pack(side="right")

        contexto.al_cambiar_lista(self.refrescar)
        contexto.al_cambiar_cliente(self._mostrar_activo)
        self.refrescar()

    def refrescar(self) -> None:
        try:
            lista = self.contexto.registro.listar()
        except Exception as e:  # noqa: BLE001
            lista = []
            messagebox.showerror("Clientes", f"No se pudo leer la base de clientes:\n{e}")
        self._por_etiqueta = {etiqueta_cliente(c): c for c in lista}
        self.combo.configure(values=[SIN_CLIENTE, *self._por_etiqueta])
        self._mostrar_activo()

    def _mostrar_activo(self) -> None:
        c = self.contexto.cliente
        if c is None:
            self.var.set(SIN_CLIENTE)
            self.lbl_info.configure(text="RUC, clave y carpeta se ingresan a mano en «Descarga».")
        else:
            self.var.set(etiqueta_cliente(c))
            if self.vertical:
                self.lbl_info.configure(text=f"RUC {c.ruc}\n{c.nombre_tipo}")
            else:
                self.lbl_info.configure(text=f"{c.nombre_tipo} · carpeta clientes/{c.carpeta}")

    def _elegido(self, _evento=None) -> None:
        self.contexto.fijar(self._por_etiqueta.get(self.var.get()))
