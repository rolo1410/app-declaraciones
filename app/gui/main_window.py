"""Ventana principal: menú, barra superior y páginas.

    Clientes (inicio)  →  ficha del cliente y su mes  →  1 Descarga · 2 Declaración
                                                          Configuración (aparte)

El contador elige cliente y mes en la cuadrícula de «Clientes»; las etapas del
mes se abren desde la ficha y trabajan sobre ese cliente y ese mes.
"""
from __future__ import annotations

import os
import platform

import tkinter as tk
from tkinter import messagebox, ttk

from .acciones_clientes import AccionesClientes
from .contexto import ContextoCliente
from .menu_principal import MenuPrincipal
from .navegacion import BarraSuperior, Pagina, Paginas
from .pestana_clientes import Navegar, PestanaClientes, periodo_por_defecto
from .pestana_configuracion import abrir_configuracion
from .pestana_declaracion import PestanaDeclaracion
from .pestana_descarga import PestanaDescarga
from .recursos import poner_icono

TITULO = "Comprobantes SRI — Declaraciones de IVA"


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(TITULO)
        # Grande si la pantalla lo permite: la cuadrícula de clientes y la ficha
        # del mes caben lado a lado desde ~1100 px.
        ancho = min(1360, self.winfo_screenwidth() - 80)
        alto = min(860, self.winfo_screenheight() - 120)
        self.geometry(f"{max(ancho, 1100)}x{max(alto, 700)}")
        self.minsize(1100, 640)
        poner_icono(self)

        # Cliente y mes de trabajo, compartidos por todas las páginas.
        self.contexto = ContextoCliente(self)
        ctx = self.contexto
        self.acciones = AccionesClientes(self, ctx)

        barra = ttk.Frame(self)
        barra.pack(fill="x")
        ttk.Separator(self).pack(fill="x")
        paginas = Paginas(self)
        paginas.pack(fill="both", expand=True)
        self.notebook = paginas
        self.barra = BarraSuperior(barra, self, paginas, ctx, al_volver=self.ir_a_clientes)
        self.barra.pack(fill="x")

        self.pestana_clientes = PestanaClientes(paginas, ctx, self.acciones, Navegar(
            descarga=self.ir_a_descarga, declaracion=self.ir_a_declaracion,
            enviar=self.enviar_al_cliente))
        self.pestana_descarga = PestanaDescarga(
            paginas, on_descarga_completa=self._descarga_completa, contexto=ctx)
        self.pestana_declaracion = PestanaDeclaracion(
            paginas, contexto=ctx, on_configurar=lambda: self.after(1, self._ir_a_configuracion))

        b = self.barra
        b.agregar(Pagina(self.pestana_clientes, "Clientes",
                         "Elija un mes de un cliente para ver y avanzar sus etapas."))
        b.agregar(Pagina(self.pestana_descarga, "Descarga", tipo="etapa", numero="1"))
        b.agregar(Pagina(self.pestana_declaracion, "Declaración", tipo="etapa", numero="2"))

        # Barra de menús: «Clientes», «Ir» y «Ventana».
        self.menu = MenuPrincipal(self, ctx, self.acciones, [
            ("Clientes", self.ir_a_clientes),
            ("1 · Descarga", self.ir_a_descarga),
            ("2 · Declaración", self.ir_a_declaracion),
        ], al_configurar=self._ir_a_configuracion)

        # Cerrar (botón de la ventana, ⌘W y ⌘Q) pasa por cerrar(): avisa si hay
        # una descarga en curso.
        self.protocol("WM_DELETE_WINDOW", self.cerrar)
        if platform.system() == "Darwin":
            self.createcommand("tk::mac::Quit", self.cerrar)
            # «Comprobantes SRI → Ajustes…» (⌘,) del menú de la app en macOS.
            self.createcommand("tk::mac::ShowPreferences",
                               lambda: self.after(1, self._ir_a_configuracion))

        # En macOS, una app lanzada fuera de un bundle .app no se activa sola:
        # el primer clic solo enfoca la ventana en vez de accionar el control.
        # Traerla al frente y darle foco evita esa sensación de "no hace clic".
        self.after(200, self._traer_al_frente)

        # Retomar el último cliente usado, en el mes que se declara ahora.
        ultimo = ctx.ultimo_cliente()
        if ultimo is not None:
            anio, mes = periodo_por_defecto()
            ctx.fijar(ultimo)
            ctx.fijar_periodo(f"{anio:04d}-{mes:02d}")
        paginas.select(self.pestana_clientes)

    def cerrar(self) -> None:
        if getattr(self, "pila_dialogos", None):
            self.pila_dialogos[-1].cancelar()
            return
        if self.pestana_descarga.descargando() and not messagebox.askyesno(
            "Cerrar",
            "Hay una descarga en curso. Si cierra la app se interrumpe.\n\n¿Cerrar de todos modos?",
        ):
            return
        self.destroy()

    # -- navegación ------------------------------------------------------------
    def _ir(self, pagina) -> bool:
        if getattr(self, "pila_dialogos", None):
            return False
        self.notebook.select(pagina)
        return True

    def _ir_a_configuracion(self) -> None:
        """Configuración es un formulario modal sobre la ventana atenuada."""
        if getattr(self, "pila_dialogos", None):
            return
        abrir_configuracion(self, self.contexto, self.acciones)

    def ir_a_clientes(self) -> None:
        self._ir(self.pestana_clientes)

    def ir_a_descarga(self) -> None:
        self._ir(self.pestana_descarga)

    def _declaracion_es_del_mes(self) -> bool:
        """La declaración cargada es del cliente y mes de trabajo."""
        d, ctx = self.pestana_declaracion, self.contexto
        if ctx.cliente is None or not ctx.periodo:
            return True
        return (bool(d.comprobantes) and (not d.ruc or d.ruc in ctx.cliente.identificaciones)
                and ctx.periodo in (d.combo_periodo.cget("values") or ()))

    def ir_a_declaracion(self) -> None:
        """Declaración del mes de trabajo: carga sus XML si aún no están cargados."""
        if not self._ir(self.pestana_declaracion):
            return
        d = self.pestana_declaracion
        if self._declaracion_es_del_mes():
            d.elegir_periodo(self.contexto.periodo)
        elif d._carpetas_del_mes():
            d.cargar_xml()

    def enviar_al_cliente(self) -> None:
        d, ctx = self.pestana_declaracion, self.contexto
        calculada = (d.declaracion is not None and d.declaracion.periodo == ctx.periodo
                     and self._declaracion_es_del_mes())
        self.ir_a_declaracion()
        if calculada:
            self.after(50, d.enviar_por_correo)
        else:
            messagebox.showinfo(
                "Enviar al cliente",
                "Primero calcule la declaración de este mes: el informe se arma con ese "
                "cálculo. Después use «Enviar al cliente por correo…».")

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

    # -- enlaces entre páginas --
    def _descarga_completa(self, carpeta: str) -> None:
        """Tras descargar, carga esos XML en la declaración y la muestra."""
        self.pestana_declaracion.cargar_carpetas_xml([carpeta], self.contexto.periodo or "")
        self._ir(self.pestana_declaracion)
        self.contexto.seguimiento_cambio()


def _traer_ventana_existente() -> None:
    """Pone al frente la ventana de la app que ya está abierta (si se puede)."""
    from ..core import plataforma

    try:
        pid = int(plataforma.ruta_pid_app().read_text().strip())
    except (OSError, ValueError):
        pid = None
    try:
        if platform.system() == "Darwin" and pid:
            import subprocess

            subprocess.run(["osascript", "-e",
                            "tell application \"System Events\" to set frontmost of "
                            f"(first process whose unix id is {pid}) to true"],
                           check=False, capture_output=True, timeout=3)
        elif platform.system() == "Windows":
            import ctypes

            usuario = ctypes.windll.user32
            hwnd = usuario.FindWindowW(None, TITULO)
            if hwnd:
                usuario.ShowWindow(hwnd, 9)  # SW_RESTORE
                usuario.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001 - traerla al frente es solo una ayuda
        pass


def _avisar_ya_abierta() -> None:
    _traer_ventana_existente()
    raiz = tk.Tk()
    raiz.withdraw()
    messagebox.showinfo(TITULO, "Comprobantes SRI ya está abierta en otra ventana.\n\n"
                                "Solo se puede abrir una a la vez: siga trabajando en esa.",
                        parent=raiz)
    raiz.destroy()


def ejecutar_gui() -> bool:
    """Abre la app; si ya hay una ventana abierta, avisa y no abre otra.

    Devuelve False si no se abrió por estar ya abierta.
    """
    from ..core import plataforma

    candado = plataforma.candado_app()
    try:
        candado.adquirir()
    except plataforma.CandadoOcupado:
        _avisar_ya_abierta()
        return False
    pid = plataforma.ruta_pid_app()
    try:
        try:
            pid.write_text(str(os.getpid()))
        except OSError:
            pass
        App().mainloop()
    finally:
        try:
            pid.unlink(missing_ok=True)
        except OSError:
            pass
        candado.liberar()
    return True
