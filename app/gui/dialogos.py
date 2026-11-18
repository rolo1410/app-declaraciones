"""Diálogos modales: alta de cliente, clave y frase de paso.

Ninguno muestra una clave ya guardada: solo permiten escribir una nueva.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from ..core import cifrado
from ..core import ruc as ruc_mod


# Opacidad del velo que atenúa la ventana principal detrás del diálogo.
OPACIDAD_VELO = 0.38
# macOS y Windows componen ventanas translúcidas siempre; en Linux depende del
# escritorio (sin compositor el velo sería negro opaco), así que allí el
# diálogo se dibuja dentro de la ventana principal.
FLOTANTE = sys.platform in ("darwin", "win32")


class _Dialogo(ttk.Frame):
    """Base de los diálogos modales, «dentro» de la ventana principal.

    Con ``FLOTANTE``: un velo translúcido (ventana sin borde) cubre el
    contenido de la ventana principal y la atenúa; encima, otra ventana sin
    borde con el formulario, centrada. Ninguna se puede arrastrar, y ambas
    siguen a la ventana principal si se mueve o cambia de tamaño. Sin
    ``FLOTANTE``: una cubierta opaca dentro de la propia ventana.

    En ambos casos es modal: el velo no deja hacer clic debajo, el menú y sus
    atajos se deshabilitan, Tab recorre solo los campos del diálogo, Enter
    acepta y Escape cancela. No se usa ``grab`` ni ``transient``: en macOS
    con Tk 8.6 dejaban el diálogo sin responder o lo devolvían a su sitio.
    """

    def __init__(self, padre, titulo: str) -> None:
        raiz = padre.winfo_toplevel()
        self._raiz = raiz
        self._velo: tk.Toplevel | None = None
        if FLOTANTE:
            self._velo = tk.Toplevel(raiz, background="#000000")
            self._velo.withdraw()
            self._velo.overrideredirect(True)
            try:
                self._velo.attributes("-alpha", OPACIDAD_VELO)
            except tk.TclError:
                pass
            self._caja = tk.Toplevel(raiz, background=_color_borde(raiz))
            self._caja.withdraw()
            self._caja.overrideredirect(True)
            super().__init__(self._caja, padding=(20, 14, 20, 18))
            self.pack(padx=1, pady=1)  # 1 px de borde con el fondo de la caja
        else:
            self._caja = ttk.Frame(raiz)  # cubierta opaca de toda la ventana
            borde = tk.Frame(self._caja, background=_color_borde(raiz))
            borde.place(relx=0.5, rely=0.42, anchor="center")
            super().__init__(borde, padding=(20, 14, 20, 18))
            self.pack(padx=1, pady=1)
        self.resultado = None
        self._menu_previo: list[tuple[tk.Menu, int, str]] = []
        self._abierto = False
        self._cerrando = False
        self._enlaces_raiz: list[tuple[str, str]] = []

        tamano = 15 if sys.platform == "darwin" else 12
        ttk.Label(self, text=titulo, font=("TkDefaultFont", tamano, "bold")).pack(
            anchor="w")
        ttk.Separator(self).pack(fill="x", pady=(8, 12))
        self.cuerpo = ttk.Frame(self)
        self.cuerpo.pack(fill="both", expand=True)

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

    # Las teclas se enlazan a la ventana del diálogo y a la principal, para que
    # funcionen aunque el foco haya quedado debajo. Con diálogos anidados manda
    # el de arriba de la pila.
    _TECLAS = ("<Escape>", "<Return>", "<KP_Enter>", "<Tab>", "<Shift-Tab>", "<ISO_Left_Tab>")

    def _instalar_teclas(self) -> None:
        destinos = [self._raiz] + ([self._caja] if FLOTANTE else [])
        for r in destinos:
            r.bind("<Escape>", lambda _e: (self.cancelar(), "break")[1])
            r.bind("<Return>", self._enter)
            r.bind("<KP_Enter>", self._enter)
            r.bind("<Tab>", lambda e: self._ciclar(e, 1))
            for seq in ("<Shift-Tab>", "<ISO_Left_Tab>"):
                r.bind(seq, lambda e: self._ciclar(e, -1))

    def _quitar_teclas(self) -> None:
        for seq in self._TECLAS:
            self._raiz.unbind(seq)

    # -- velo flotante -------------------------------------------------------------
    def _ubicar(self, _evento=None) -> None:
        """Ajusta velo y formulario a la posición actual de la ventana principal."""
        if self._cerrando or not self.winfo_exists():
            return
        r = self._raiz
        x, y, ancho, alto = r.winfo_rootx(), r.winfo_rooty(), r.winfo_width(), r.winfo_height()
        if self._velo is not None:
            self._velo.geometry(f"{ancho}x{alto}+{x}+{y}")
        self._caja.update_idletasks()
        cx = x + (ancho - self._caja.winfo_reqwidth()) // 2
        cy = y + int((alto - self._caja.winfo_reqheight()) * 0.4)
        self._caja.geometry(f"+{max(cx, 0)}+{max(cy, 0)}")

    def _al_frente(self, _evento=None) -> None:
        """Si se activa la ventana principal, el velo y el diálogo vuelven encima."""
        if self._cerrando or self._pila()[-1:] != [self]:
            return
        if self._velo is not None:
            self._velo.lift()
        self._caja.lift()
        actual = self.focus_get()
        if actual is None or not self._contiene(actual):
            (self._enfocables() or [self])[0].focus_force()

    def _enlazar_raiz(self, secuencia: str, funcion) -> None:
        self._enlaces_raiz.append((secuencia, self._raiz.bind(secuencia, funcion, add="+")))

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
        self._abierto = True
        pila = self._pila()
        pila.append(self)
        self._raiz.dialogos_abiertos = len(pila)
        self._bloquear_menu()
        self._instalar_teclas()
        if FLOTANTE:
            self._ubicar()
            self._velo.deiconify()
            self._caja.deiconify()
            self._velo.lift()
            self._caja.lift()
            # Un clic en el velo devuelve el foco al formulario.
            self._velo.bind("<ButtonPress>", self._al_frente)
            # En macOS la posición de la ventana principal se actualiza después
            # del evento: se recalcula un instante más tarde.
            self._enlazar_raiz("<Configure>", lambda e: self.after(15, self._ubicar)
                               if e.widget is self._raiz else None)
            self._enlazar_raiz("<FocusIn>", lambda _e: self.after_idle(self._al_frente))
        else:
            self._caja.place(relx=0, rely=0, relwidth=1, relheight=1)
            self._caja.lift()
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
        if self._cerrando:  # llamado de nuevo al destruir la caja que lo contiene
            super().destroy()
            return
        self._cerrando = True
        if self._abierto:
            self._abierto = False
            self._restaurar_menu()
            for secuencia, funcid in self._enlaces_raiz:
                _desenlazar(self._raiz, secuencia, funcid)
            self._enlaces_raiz.clear()
            pila = self._pila()
            if self in pila:
                pila.remove(self)
            self._raiz.dialogos_abiertos = len(pila)
            if pila:
                pila[-1]._instalar_teclas()
            else:
                self._quitar_teclas()
        for contenedor in (self._caja, self._velo):
            if contenedor is not None:
                try:
                    contenedor.destroy()
                except tk.TclError:
                    pass
        try:
            super().destroy()
        except tk.TclError:
            pass
        if self._pila():
            self._pila()[-1].after_idle(self._pila()[-1]._al_frente)

    def error(self, texto: str) -> None:
        self.lbl_error.configure(text=texto)

    def aceptar(self) -> None:  # pragma: no cover - lo redefinen las subclases
        self.destroy()

    def cancelar(self) -> None:
        self.resultado = None
        self.destroy()


def _color_borde(raiz) -> str:
    """Color del borde de 1 px del formulario, según el tema del sistema."""
    for color in ("systemSeparatorColor", "#8a8a8a"):
        try:
            raiz.winfo_rgb(color)
            return color
        except tk.TclError:
            continue
    return "#8a8a8a"


def _desenlazar(widget, secuencia: str, funcid: str) -> None:
    """Quita solo el enlace ``funcid`` (``unbind`` de Python < 3.13 quita todos)."""
    try:
        actual = widget.bind(secuencia)
        restantes = [linea for linea in actual.split("\n") if funcid not in linea]
        widget.bind(secuencia, "\n".join(restantes))
        widget.deletecommand(funcid)
    except tk.TclError:
        pass


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
