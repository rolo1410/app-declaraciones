"""Barra «Cliente: [combo]» encima de las pestañas (cliente activo global)."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .contexto import ContextoCliente

SIN_CLIENTE = "— Sin cliente registrado —"


def etiqueta_cliente(c) -> str:
    return f"{c.nombre} ({c.ruc})"


class SelectorCliente(ttk.Frame):
    def __init__(self, master, contexto: ContextoCliente, on_gestionar=None) -> None:
        super().__init__(master, padding=(8, 6, 8, 2))
        self.contexto = contexto
        self._por_etiqueta: dict = {}

        ttk.Label(self, text="Cliente:").pack(side="left")
        self.var = tk.StringVar(value=SIN_CLIENTE)
        self.combo = ttk.Combobox(self, textvariable=self.var, state="readonly", width=48)
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", self._elegido)
        self.lbl_info = ttk.Label(self, text="", foreground="gray")
        self.lbl_info.pack(side="left", padx=6)
        if on_gestionar is not None:
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
            self.lbl_info.configure(text=f"{c.nombre_tipo} · carpeta clientes/{c.carpeta}")

    def _elegido(self, _evento=None) -> None:
        self.contexto.fijar(self._por_etiqueta.get(self.var.get()))
