"""Barra de menús de la ventana principal.

    Clientes   Ir   Ventana

«Clientes» reúne todo lo que se hace con el registro de contribuyentes: alta,
cambio de cliente activo, acciones sobre el cliente activo (clave, nombre,
carpetas, desactivar), llave maestra y ruta base. Las acciones son las mismas
de la pestaña «Clientes»; el menú las aplica al cliente *activo* y la pestaña a
la fila seleccionada en la tabla.

«Ir» cambia de pestaña con atajos de teclado (⌘/Ctrl + 0…3).

En macOS la barra aparece en la parte superior de la pantalla; en Windows y
Linux, debajo del título de la ventana.
"""
from __future__ import annotations

import platform
import tkinter as tk
from tkinter import messagebox
from typing import Callable

from ..core import preferencias
from .contexto import ContextoCliente
from .dialogos import tras_el_clic
from .acciones_clientes import AccionesClientes

ES_MAC = platform.system() == "Darwin"
_MOD_EVT = "Command" if ES_MAC else "Control"


def _atajo(tecla: str, shift: bool = False) -> tuple[str, str]:
    """(texto para el menú, secuencia de evento Tk) para ⌘/Ctrl + tecla.

    En macOS Tk dibuja «Command-Shift-O» como ⌘⇧O; en el resto se muestra tal cual.
    """
    visible = {"comma": ","}.get(tecla, tecla.upper())
    if ES_MAC:
        texto = f"Command-{'Shift-' if shift else ''}{visible}"
    else:
        texto = f"Ctrl+{'Shift+' if shift else ''}{visible}"
    keysym = tecla.upper() if shift and len(tecla) == 1 else tecla.lower()
    return texto, f"<{_MOD_EVT}-{'Shift-' if shift else ''}{keysym}>"


class MenuPrincipal:
    """Construye la barra de menús y mantiene su estado al día."""

    def __init__(
        self,
        raiz: tk.Tk,
        contexto: ContextoCliente,
        acciones: AccionesClientes,
        pestanas: list[tuple[str, Callable[[], None]]],
        al_configurar: Callable[[], None] | None = None,
    ) -> None:
        self.al_configurar = al_configurar
        self.raiz = raiz
        self.contexto = contexto
        self.clientes = acciones
        self.ir_a_clientes = pestanas[0][1]

        self.barra = tk.Menu(raiz)
        self._menu_clientes()
        self._menu_ir(pestanas)
        self._menu_ventana()
        raiz.configure(menu=self.barra)

        contexto.al_cambiar_cliente(self.actualizar)
        contexto.al_cambiar_lista(self.actualizar)
        self.actualizar()

    # ------------------------------------------------------------ construcción
    def _agregar(self, menu: tk.Menu, etiqueta: str, accion: Callable[[], None],
                 tecla: str | None = None, shift: bool = False) -> int:
        """Añade un comando (con atajo opcional) y devuelve su índice."""
        menu.add_command(label=etiqueta, command=tras_el_clic(self.raiz, accion))
        indice = menu.index("end")
        if tecla:
            texto, evento = _atajo(tecla, shift)
            menu.entryconfigure(indice, accelerator=texto)
            self.raiz.bind_all(evento, lambda _e: self._invocar(menu, indice))
        return indice

    def _invocar(self, menu: tk.Menu, indice: int) -> str:
        # El atajo respeta el estado del elemento: deshabilitado no hace nada,
        # y con un diálogo abierto ningún atajo actúa.
        if getattr(self.raiz, "dialogos_abiertos", 0):
            return "break"
        self.actualizar()
        if menu.entrycget(indice, "state") != "disabled":
            menu.invoke(indice)
        return "break"

    def _menu_clientes(self) -> None:
        m = tk.Menu(self.barra, tearoff=False, postcommand=self.actualizar)
        self.m_clientes = m
        p = self.clientes

        self._agregar(m, "Nuevo cliente…", p.nuevo, "n")
        self._agregar(m, "Ver todos los clientes", self.ir_a_clientes)  # ⌘/Ctrl+0 en «Ir»

        m.add_separator()
        # Encabezado (deshabilitado) con el nombre del cliente activo.
        m.add_command(label="", state="disabled")
        self.i_encabezado = m.index("end")
        self.i_activo = [
            self._agregar(m, "Cambiar clave…", lambda: self._con_activo(p.cambiar_clave)),
            self._agregar(m, "Editar datos…", lambda: self._con_activo(p.editar)),
            self._agregar(m, "Abrir carpeta del cliente",
                          lambda: self._con_activo(p.abrir_carpeta), "o", shift=True),
            self._agregar(m, "Abrir resultados del mes", self._abrir_resultados),
            self._agregar(m, "Desactivar…", lambda: self._con_activo(p.alternar_activo)),
        ]

        m.add_separator()
        llave = tk.Menu(m, tearoff=False)
        r = self.raiz
        llave.add_command(label="Exportar copia de emergencia…",
                          command=tras_el_clic(r, p.exportar_copia))
        llave.add_command(label="Restaurar llave…", command=tras_el_clic(r, p.restaurar_copia))
        llave.add_separator()
        llave.add_command(label="Respaldo completo…", command=tras_el_clic(r, p.respaldo_completo))
        m.add_cascade(label="Llave maestra y respaldo", menu=llave)

        base = tk.Menu(m, tearoff=False)
        base.add_command(label="Cambiar ruta base…", command=tras_el_clic(r, p.cambiar_base))
        base.add_command(label="Abrir ruta base", command=p.abrir_base)
        m.add_cascade(label="Ruta base de los archivos", menu=base)

        m.add_separator()
        m.add_command(label="Importar clave del .env…", command=tras_el_clic(r, p.importar_env))
        self.i_env = m.index("end")
        if self.al_configurar is not None:
            m.add_separator()
            # En macOS ⌘, ya lo da «Ajustes…» del menú de la app (tk::mac::ShowPreferences).
            self._agregar(m, "Configuración…", self.al_configurar,
                          None if ES_MAC else "comma")

        self.barra.add_cascade(label="Clientes", menu=m)

    def _menu_ir(self, pestanas: list[tuple[str, Callable[[], None]]]) -> None:
        m = tk.Menu(self.barra, tearoff=False)
        for n, (etiqueta, accion) in enumerate(pestanas):
            self._agregar(m, etiqueta, accion, str(n))
        self.barra.add_cascade(label="Ir", menu=m)

    def _menu_ventana(self) -> None:
        # En macOS el menú llamado «window» recibe además Minimizar/Zoom nativos.
        m = tk.Menu(self.barra, tearoff=False, name="window" if ES_MAC else None)
        texto, evento = _atajo("w")
        m.add_command(label="Cerrar ventana", accelerator=texto,
                      command=tras_el_clic(self.raiz, self.cerrar_ventana))
        # ⌘W funciona también con un diálogo abierto (el menú queda deshabilitado).
        self.raiz.bind_all(evento, lambda _e: (self.cerrar_ventana(), "break")[1])
        self.barra.add_cascade(label="Ventana", menu=m)

    def cerrar_ventana(self) -> None:
        """⌘W: cancela el diálogo abierto o, si no hay ninguno, cierra la app."""
        pila = getattr(self.raiz, "pila_dialogos", [])
        if pila:
            pila[-1].cancelar()
        elif hasattr(self.raiz, "cerrar"):
            self.raiz.cerrar()
        else:
            self.raiz.destroy()

    # ------------------------------------------------------------------ estado
    def actualizar(self) -> None:
        """Refresca la lista de clientes y habilita lo que aplica al cliente activo."""
        c = self.contexto.cliente
        m = self.m_clientes
        m.entryconfigure(self.i_encabezado,
                         label=f"Cliente activo: {c.nombre} ({c.ruc})" if c
                         else "Sin cliente activo")
        estado = "normal" if c else "disabled"
        for i in self.i_activo:
            m.entryconfigure(i, state=estado)

        try:
            heredada = preferencias.clave_heredada()
        except Exception:  # noqa: BLE001 - leer el .env nunca debe romper el menú
            heredada = None
        m.entryconfigure(self.i_env, state="normal" if heredada else "disabled")


    # --------------------------------------------------------------- acciones
    def _con_activo(self, accion: Callable) -> None:
        if self.contexto.cliente is not None:
            accion(self.contexto.cliente)

    def _abrir_resultados(self) -> None:
        carpeta = self.contexto.carpeta_resultados()
        if carpeta is None:
            messagebox.showerror("Clientes", "No se pudo crear la carpeta de resultados.")
            return
        self.clientes._abrir(carpeta)
