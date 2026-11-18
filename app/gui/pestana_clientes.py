"""Página de inicio «Clientes»: la cartera del contador y la ficha de cada mes.

Izquierda: un cliente por fila con sus 12 meses del año (gris pendiente,
naranja declarada, verde enviada, ✓ cobrada). Un clic en un cuadro elige ese
cliente y ese mes como **mes de trabajo**.

Derecha: la ficha del cliente (datos y acciones) y las etapas del mes en el
orden del trabajo, cada una con su estado y su botón:

    1 Descargar comprobantes → 2 Calcular la declaración → 3 Presentar en el SRI
    → 4 Enviar al cliente → 5 Cobrar
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import font, messagebox, ttk
from typing import Callable

from ..core import clientes, informe, plataforma
from ..core.informe import MESES, nombre_periodo
from .acciones_clientes import AccionesClientes
from .contexto import ContextoCliente
from .dialogos import pedir_fecha, tras_el_clic

TITULO = "Clientes"
ES_MAC = sys.platform == "darwin"
MESES_CORTOS = [m[:3].capitalize() for m in MESES]

LADO = 22          # lado del cuadro
PASO = 30          # ancho de cada columna de mes
ALTO_FILA = 46
X_MESES = 200      # inicio de la columna de meses (antes: nombre y RUC)
ALTO_CABECERA = 28
ANCHO_FICHA = 400


def _es_oscuro(widget) -> bool:
    try:
        r, g, b = (v >> 8 for v in widget.winfo_rgb(
            "systemWindowBackgroundColor" if ES_MAC else "SystemButtonFace"))
    except tk.TclError:
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


def paleta(widget) -> dict[str, str]:
    oscuro = _es_oscuro(widget)
    base = {
        "pendiente": "#48484a" if oscuro else "#d1d1d6",
        "declarada": "#ff9f0a" if oscuro else "#ef8a00",
        "enviada": "#30b465" if oscuro else "#2e9d5b",
        "secundario": "#8e8e93",
        "fila_sel": "#3a3a3c" if oscuro else "#e8e8ed",
        "fila_hover": "#353537" if oscuro else "#f2f2f5",
        "anillo": "#ffffff" if oscuro else "#1c1c1e",
        "aviso": "#ff9f0a" if oscuro else "#b35c00",
    }
    if ES_MAC:
        base.update(fondo="systemWindowBackgroundColor", texto="systemTextColor")
    else:
        base.update(fondo=ttk.Style(widget).lookup("TFrame", "background") or "#f0f0f0",
                    texto="#1f2328")
    return base


ETIQUETA_ESTADO = {"pendiente": "Pendiente", "declarada": "Declarada",
                   "enviada": "Enviada al cliente"}


def _fecha(texto: str | None) -> str:
    """``2026-08-12`` / ``2026-08-12 10:30`` → ``12/08/2026`` / ``12/08/2026 10:30``."""
    if not texto:
        return ""
    try:
        if len(texto) > 10:
            return datetime.strptime(texto, "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
        return date.fromisoformat(texto).strftime("%d/%m/%Y")
    except ValueError:
        return texto


def _decimal(valor) -> Decimal:
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _monto(valor) -> str:
    return f"$ {_decimal(valor):,.2f}"


def periodo_por_defecto() -> tuple[int, int]:
    """El mes anterior: es el que se declara este mes."""
    hoy = date.today()
    return (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)


@dataclass
class Navegar:
    """Lo que la ficha necesita de la ventana para llevar a cada etapa."""
    descarga: Callable[[], None]
    declaracion: Callable[[], None]
    enviar: Callable[[], None]


class PestanaClientes(ttk.Frame):
    def __init__(self, master, contexto: ContextoCliente, acciones: AccionesClientes,
                 navegar: Navegar) -> None:
        super().__init__(master, padding=(18, 6, 18, 12))
        self.contexto = contexto
        self.registro = contexto.registro
        self.acciones = acciones
        self.navegar = navegar
        self.anio = periodo_por_defecto()[0]
        self._clientes: list[clientes.Cliente] = []
        self._estados: dict = {}
        self._hover: int | None = None
        self._con_marcador = False
        self.colores = paleta(self)
        self._construir()
        contexto.al_cambiar_lista(self.refrescar)
        contexto.al_cambiar_seguimiento(self.refrescar)
        contexto.al_cambiar_cliente(self._contexto_cambiado)
        contexto.al_cambiar_periodo(self._contexto_cambiado)
        self.refrescar()

    # ----------------------------------------------------------------- interfaz
    def _construir(self) -> None:
        familia = font.nametofont("TkDefaultFont").actual("family")
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 10))
        ttk.Button(barra, text="Nuevo cliente…",
                   command=tras_el_clic(self, self._nuevo)).pack(side="left")
        self.var_buscar = tk.StringVar()
        self.ent_buscar = ttk.Entry(barra, textvariable=self.var_buscar, width=26)
        self.ent_buscar.pack(side="left", padx=(12, 0))
        self._marcador(self.ent_buscar, "Buscar por nombre o RUC")
        self.var_buscar.trace_add("write", lambda *_: self.refrescar())
        self.var_inactivos = tk.BooleanVar(value=False)
        ttk.Checkbutton(barra, text="Desactivados", variable=self.var_inactivos,
                        command=self.refrescar).pack(side="left", padx=(12, 0))
        ttk.Button(barra, text="›", width=2,
                   command=lambda: self._cambiar_anio(1)).pack(side="right")
        self.lbl_anio = ttk.Label(barra, text="", width=5, anchor="center",
                                  font=(familia, 15 if ES_MAC else 12, "bold"))
        self.lbl_anio.pack(side="right", padx=4)
        ttk.Button(barra, text="‹", width=2,
                   command=lambda: self._cambiar_anio(-1)).pack(side="right")

        cuerpo = ttk.Frame(self)
        cuerpo.pack(fill="both", expand=True)

        # Cartera (izquierda)
        izquierda = ttk.Frame(cuerpo)
        izquierda.pack(side="left", fill="both", expand=True)
        self._leyenda(izquierda)
        self.lbl_estado = ttk.Label(izquierda, text=" ", foreground="gray")
        self.lbl_estado.pack(side="bottom", anchor="w", pady=(6, 0))
        marco = ttk.Frame(izquierda)
        marco.pack(fill="both", expand=True)
        self.lienzo = tk.Canvas(marco, highlightthickness=0, background=self.colores["fondo"])
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.lienzo.yview)
        self.lienzo.configure(yscrollcommand=scroll.set)
        self.lienzo.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.lienzo.bind("<Button-1>", self._clic)
        self.lienzo.bind("<Motion>", self._mover)
        self.lienzo.bind("<Leave>", self._salir)
        self.lienzo.bind("<Configure>", lambda _e: self._dibujar())
        self.lienzo.bind("<MouseWheel>", self._rueda)

        ttk.Separator(cuerpo, orient="vertical").pack(side="left", fill="y", padx=(14, 0))

        # Ficha (derecha)
        self.ficha = ttk.Frame(cuerpo, padding=(18, 0, 0, 0), width=ANCHO_FICHA)
        self.ficha.pack(side="left", fill="y")
        self.ficha.pack_propagate(False)

    def _marcador(self, entrada: ttk.Entry, texto: str) -> None:
        """Texto de ayuda dentro de la caja de búsqueda mientras está vacía."""
        def mostrar(_e=None):
            if not self.var_buscar.get() and self.focus_get() is not entrada:
                self._con_marcador = True
                entrada.configure(foreground="gray")
                entrada.insert(0, texto)

        def quitar(_e=None):
            if self._con_marcador:
                entrada.delete(0, "end")
                entrada.configure(foreground="")
                self._con_marcador = False

        entrada.bind("<FocusIn>", quitar)
        entrada.bind("<FocusOut>", mostrar)
        self.after_idle(mostrar)

    def _texto_buscar(self) -> str:
        return "" if self._con_marcador else self.var_buscar.get().strip()

    def _leyenda(self, padre) -> None:
        c = self.colores
        lienzo = tk.Canvas(padre, height=20, highlightthickness=0, background=c["fondo"])
        lienzo.pack(fill="x", pady=(0, 4))
        x = X_MESES
        fuente = font.nametofont("TkDefaultFont")
        chica = font.Font(family=fuente.actual("family"), size=fuente.actual("size") - 1)
        for clave, texto in (("pendiente", "Pendiente"), ("declarada", "Declarada"),
                             ("enviada", "Enviada"), ("cobrada", "Cobrada")):
            color = c["enviada"] if clave == "cobrada" else c[clave]
            lienzo.create_rectangle(x, 4, x + 12, 16, fill=color, outline="")
            if clave == "cobrada":
                self._check(lienzo, x, 4, 12, "#ffffff")
            lienzo.create_text(x + 17, 10, text=texto, anchor="w", fill=c["secundario"],
                               font=chica)
            x += 17 + chica.measure(texto) + 16

    # ------------------------------------------------------------------ datos
    def refrescar(self) -> None:
        try:
            todos = self.registro.listar(incluir_inactivos=self.var_inactivos.get())
            self._estados = self.registro.estados_del_anio(self.anio)
        except Exception as e:  # noqa: BLE001
            todos, self._estados = [], {}
            self.lbl_estado.configure(text=f"No se pudo leer la base de clientes: {e}")
        buscar = self._texto_buscar().lower()
        self._clientes = [c for c in todos if not buscar or buscar in c.nombre.lower()
                          or buscar in c.ruc or (c.cedula and buscar in c.cedula)]
        self.lbl_anio.configure(text=str(self.anio))
        self._dibujar()
        self._mostrar_ficha()

    def _cambiar_anio(self, paso: int) -> None:
        self.anio += paso
        self.refrescar()

    def _contexto_cambiado(self) -> None:
        if self.contexto.periodo and int(self.contexto.periodo[:4]) != self.anio:
            self.anio = int(self.contexto.periodo[:4])
            self.refrescar()
            return
        self._dibujar()
        self._mostrar_ficha()

    def _estado(self, cliente, mes: int) -> clientes.EstadoMes:
        return self._estados.get(cliente.id, {}).get(mes) or \
            clientes.EstadoMes(f"{self.anio:04d}-{mes:02d}")

    # ---------------------------------------------------------------- cuadrícula
    @staticmethod
    def _check(lienzo, x, y, lado, color) -> None:
        lienzo.create_line(x + lado * 0.24, y + lado * 0.52, x + lado * 0.43, y + lado * 0.70,
                           x + lado * 0.76, y + lado * 0.32, fill=color,
                           width=max(2, lado // 9), capstyle="round", joinstyle="round")

    def _mes_sel(self) -> int | None:
        p = self.contexto.periodo
        if p and int(p[:4]) == self.anio:
            return int(p[5:7])
        return None

    def _dibujar(self) -> None:
        cv, c = self.lienzo, self.colores
        cv.delete("all")
        fuente = font.nametofont("TkDefaultFont")
        familia, tamano = fuente.actual("family"), fuente.actual("size")
        chica = font.Font(family=familia, size=tamano - 2)
        hoy = date.today()
        ancho = max(cv.winfo_width(), X_MESES + 12 * PASO + 8)

        if not self._clientes:
            texto = ("Ningún cliente coincide con la búsqueda." if self._texto_buscar()
                     else "Aún no hay clientes. Use «Nuevo cliente…» para registrar el primero.")
            cv.create_text(8, 30, text=texto, anchor="w", fill=c["secundario"], font=fuente)
            cv.configure(scrollregion=(0, 0, ancho, 80))
            return

        for mes in range(1, 13):
            x = X_MESES + (mes - 1) * PASO + LADO / 2
            actual = (self.anio, mes) == (hoy.year, hoy.month)
            cv.create_text(x, ALTO_CABECERA / 2, text=MESES_CORTOS[mes - 1],
                           fill=c["texto"] if actual else c["secundario"],
                           font=(familia, tamano - 1, "bold" if actual else "normal"))

        activo, mes_sel = self.contexto.cliente, self._mes_sel()
        for fila, cliente in enumerate(self._clientes):
            y0 = ALTO_CABECERA + fila * ALTO_FILA
            sel = activo is not None and cliente.id == activo.id
            if sel or self._hover == fila:
                cv.create_rectangle(0, y0 + 1, ancho, y0 + ALTO_FILA - 1, outline="",
                                    fill=c["fila_sel"] if sel else c["fila_hover"])
            color_nombre = c["texto"] if cliente.activo else c["secundario"]
            cv.create_text(8, y0 + ALTO_FILA / 2 - 8, text=self._recortar(cliente.nombre, fuente),
                           anchor="w", fill=color_nombre, font=fuente)
            por_cobrar = 0
            for mes in range(1, 13):
                estado = self._estado(cliente, mes)
                x = X_MESES + (mes - 1) * PASO
                y = y0 + (ALTO_FILA - LADO) / 2
                cv.create_rectangle(x, y, x + LADO, y + LADO, fill=c[estado.estado], outline="")
                if estado.cobrada:
                    self._check(cv, x, y, LADO,
                                "#ffffff" if estado.estado != "pendiente" else c["texto"])
                elif estado.estado != "pendiente":
                    por_cobrar += 1
                if sel and mes == mes_sel:
                    cv.create_rectangle(x - 3, y - 3, x + LADO + 3, y + LADO + 3,
                                        outline=c["anillo"], width=2)
            detalle = cliente.ruc if cliente.activo else f"{cliente.ruc} · desactivado"
            id_ruc = cv.create_text(8, y0 + ALTO_FILA / 2 + 9, text=detalle, anchor="w",
                                    fill=c["secundario"], font=chica)
            if por_cobrar:
                x_fin = cv.bbox(id_ruc)[2]
                texto = f"· {por_cobrar} por cobrar"
                if x_fin + 8 + chica.measure(texto) > X_MESES - 10:
                    texto = f"· {por_cobrar}"
                cv.create_text(x_fin + 8, y0 + ALTO_FILA / 2 + 9, text=texto, anchor="w",
                               fill=c["aviso"], font=chica)
        alto = ALTO_CABECERA + len(self._clientes) * ALTO_FILA + 8
        cv.configure(scrollregion=(0, 0, ancho, alto))

    @staticmethod
    def _recortar(texto: str, fuente, maximo: int = X_MESES - 20) -> str:
        if fuente.measure(texto) <= maximo:
            return texto
        while texto and fuente.measure(texto + "…") > maximo:
            texto = texto[:-1]
        return texto.rstrip() + "…"

    def _celda(self, evento) -> tuple[int | None, int | None]:
        x, y = self.lienzo.canvasx(evento.x), self.lienzo.canvasy(evento.y)
        fila = int((y - ALTO_CABECERA) // ALTO_FILA)
        if y < ALTO_CABECERA or not (0 <= fila < len(self._clientes)):
            return None, None
        rel = x - X_MESES
        mes = int(rel // PASO) + 1 if rel >= 0 else None
        if mes is not None and (mes > 12 or rel - (mes - 1) * PASO > LADO + 4):
            mes = None
        return fila, mes

    def _clic(self, evento) -> None:
        if getattr(self.winfo_toplevel(), "pila_dialogos", None):
            return
        fila, mes = self._celda(evento)
        if fila is None:
            return
        self.elegir(self._clientes[fila], mes)

    def elegir(self, cliente: clientes.Cliente, mes: int | None = None) -> None:
        """Fija cliente y mes de trabajo (sin mes: el que ya estaba, o el anterior)."""
        if mes is None:
            anio_def, mes_def = periodo_por_defecto()
            mes = self._mes_sel() or (mes_def if self.anio == anio_def else 12)
        activo = self.contexto.cliente
        if activo is None or activo.id != cliente.id:
            self.contexto.fijar(cliente)
        self.contexto.fijar_periodo(f"{self.anio:04d}-{mes:02d}")
        self._dibujar()
        self._mostrar_ficha()

    def _mover(self, evento) -> None:
        fila, mes = self._celda(evento)
        if fila != self._hover:
            self._hover = fila
            self._dibujar()
        if fila is None or mes is None:
            self.lbl_estado.configure(text=" ")
            return
        cliente = self._clientes[fila]
        e = self._estado(cliente, mes)
        partes = [f"{cliente.nombre} · {MESES[mes - 1]} {self.anio}: {ETIQUETA_ESTADO[e.estado]}"]
        if e.cobrada:
            partes.append("cobrada")
        self.lbl_estado.configure(text=", ".join(partes))

    def _salir(self, _evento=None) -> None:
        self.lbl_estado.configure(text=" ")
        if self._hover is not None:
            self._hover = None
            self._dibujar()

    def _rueda(self, evento) -> None:
        paso = -evento.delta if ES_MAC else -evento.delta // 120
        self.lienzo.yview_scroll(int(paso), "units")

    # -------------------------------------------------------------------- ficha
    def _mostrar_ficha(self) -> None:
        for hijo in self.ficha.winfo_children():
            hijo.destroy()
        f = self.ficha
        familia = font.nametofont("TkDefaultFont").actual("family")
        cliente, periodo = self.contexto.cliente, self.contexto.periodo
        if cliente is None:
            ttk.Label(f, text="Elija un cliente",
                      font=(familia, 16 if ES_MAC else 13, "bold")).pack(anchor="w")
            ttk.Label(f, foreground="gray", wraplength=ANCHO_FICHA - 30, justify="left",
                      text="Haga clic en un mes de la cuadrícula para ver las etapas de ese mes: "
                           "descarga, declaración, presentación, envío y cobro.").pack(
                anchor="w", pady=(4, 0))
            return

        # --- Datos del cliente ---------------------------------------------------
        ttk.Label(f, text=cliente.nombre, font=(familia, 16 if ES_MAC else 13, "bold"),
                  wraplength=ANCHO_FICHA - 30, justify="left").pack(anchor="w")
        ttk.Label(f, foreground="gray",
                  text=f"RUC {cliente.ruc} · {cliente.nombre_tipo}"
                       + ("" if cliente.activo else " · desactivado")).pack(anchor="w", pady=(2, 0))
        ttk.Label(f, foreground="gray" if cliente.correo else self.colores["aviso"],
                  text=cliente.correo or "Sin correo para enviarle la declaración",
                  wraplength=ANCHO_FICHA - 30, justify="left").pack(anchor="w")
        botones = ttk.Frame(f)
        botones.pack(anchor="w", pady=(8, 0))
        a = self.acciones
        ttk.Button(botones, text="Editar datos…",
                   command=tras_el_clic(self, lambda: a.editar(cliente))).pack(side="left")
        ttk.Button(botones, text="Clave SRI…",
                   command=tras_el_clic(self, lambda: a.cambiar_clave(cliente))).pack(
            side="left", padx=(6, 0))
        ttk.Button(botones, text="Carpeta", command=lambda: a.abrir_carpeta(cliente)).pack(
            side="left", padx=(6, 0))
        if not cliente.activo:  # desactivar está en el menú «Clientes»
            ttk.Button(botones, text="Reactivar",
                       command=tras_el_clic(self, lambda: a.alternar_activo(cliente))).pack(
                side="left", padx=(6, 0))

        if not periodo:
            return
        ttk.Separator(f).pack(fill="x", pady=14)

        # --- Mes de trabajo --------------------------------------------------------
        estado = self.registro.estado_mes(cliente.id, periodo)
        cabecera = ttk.Frame(f)
        cabecera.pack(fill="x")
        ttk.Label(cabecera, text=nombre_periodo(periodo).capitalize(),
                  font=(familia, 15 if ES_MAC else 12, "bold")).pack(side="left")
        limite = informe.fecha_limite(cliente.ruc, periodo)
        if limite:
            vencido = limite < date.today() and not estado.declarada_en
            ttk.Label(cabecera, text=f"vence {limite:%d/%m/%Y}",
                      foreground=self.colores["aviso"] if vencido else "gray").pack(side="right")

        try:
            carpetas = informe.carpetas_de_descarga(self.registro.carpeta_descargas(cliente),
                                                    periodo)
        except Exception:  # noqa: BLE001
            carpetas = []
        n_xml = informe.contar_xml(carpetas)
        r = estado.resumen or {}
        a_pagar = _decimal(r.get("impuesto_a_pagar", 0))
        resultado = ""
        if r:
            resultado = (f"{_monto(a_pagar)} a pagar" if a_pagar > 0
                         else f"{_monto(r.get('credito_a_favor', 0))} de crédito a favor")
        etapas = [
            ("Descargar comprobantes", n_xml > 0,
             f"{n_xml} XML descargados" if n_xml else "Aún no se descargan del SRI",
             [("Descargar", self.navegar.descarga)]),
            ("Calcular la declaración", bool(r),
             f"{resultado} · {_fecha(estado.calculada_en)}" if r else "Sin calcular",
             [("Declaración", self.navegar.declaracion)]),
            ("Presentar en el SRI", bool(estado.declarada_en),
             f"Declarada el {_fecha(estado.declarada_en)}" if estado.declarada_en
             else "Márquela al presentarla en SRI en línea",
             self._botones_fecha(cliente, periodo, "declarada", estado.declarada_en)),
            ("Enviar al cliente", bool(estado.enviada_en),
             (f"Enviada el {_fecha(estado.enviada_en)}"
              + (f" ({estado.envios} envíos)" if estado.envios > 1 else ""))
             if estado.enviada_en else "Informe PDF, Excel y XML por correo",
             [("Abrir envío", lambda: self._abrir_envio(estado))] if estado.carpeta_envio
             else [("Enviar…", self.navegar.enviar)]),
            ("Cobrar", estado.cobrada,
             f"Cobrada el {_fecha(estado.cobrada_en)}" if estado.cobrada else "Pendiente de cobro",
             self._botones_fecha(cliente, periodo, "cobrada", estado.cobrada_en)),
        ]
        siguiente = next((i for i, e in enumerate(etapas) if not e[1]), None)
        lista = ttk.Frame(f)
        lista.pack(fill="x", pady=(10, 0))
        lista.columnconfigure(1, weight=1)
        for i, (titulo, hecha, detalle, acciones) in enumerate(etapas):
            self._etapa(lista, i, titulo, hecha, i == siguiente, detalle, acciones)

        if r:
            ttk.Separator(f).pack(fill="x", pady=12)
            ttk.Label(f, text="Resumen del mes",
                      font=(familia, 13 if ES_MAC else 11, "bold")).pack(anchor="w")
            tabla = ttk.Frame(f)
            tabla.pack(fill="x", pady=(6, 0))
            tabla.columnconfigure(1, weight=1)
            filas = [("Ventas (409)", _monto(r.get("ventas")), False),
                     ("Compras (509)", _monto(r.get("compras")), False),
                     ("Impuesto generado (499)", _monto(r.get("impuesto_generado")), False),
                     ("Crédito tributario (564)", _monto(r.get("credito_tributario")), False),
                     ("Impuesto a pagar" if a_pagar > 0 else "Crédito a favor",
                      _monto(a_pagar if a_pagar > 0 else r.get("credito_a_favor")), True)]
            tamano = font.nametofont("TkDefaultFont").actual("size")
            for i, (etiqueta, valor, fuerte) in enumerate(filas):
                estilo = (familia, tamano, "bold" if fuerte else "normal")
                ttk.Label(tabla, text=etiqueta, font=estilo).grid(row=i, column=0, sticky="w")
                ttk.Label(tabla, text=valor, font=estilo).grid(row=i, column=1, sticky="e")
            ttk.Label(tabla, foreground="gray",
                      text=f"{r.get('comprobantes', '—')} comprobantes de compra").grid(
                row=len(filas), column=0, columnspan=2, sticky="w", pady=(4, 0))

    def _etapa(self, lista, i: int, titulo: str, hecha: bool, siguiente: bool, detalle: str,
               acciones) -> None:
        c = self.colores
        familia = font.nametofont("TkDefaultFont").actual("family")
        tamano = font.nametofont("TkDefaultFont").actual("size")
        marca = tk.Canvas(lista, width=20, height=20, highlightthickness=0, background=c["fondo"])
        marca.grid(row=i, column=0, sticky="n", pady=(3, 10), padx=(0, 10))
        if hecha:
            marca.create_oval(1, 1, 19, 19, fill=c["enviada"], outline="")
            self._check(marca, 1, 1, 18, "#ffffff")
        else:
            color = c["texto"] if siguiente else c["secundario"]
            marca.create_oval(2, 2, 18, 18, outline=color, width=2)
            marca.create_text(10, 10, text=str(i + 1), fill=color,
                              font=(familia, max(tamano - 3, 8), "bold"))
        textos = ttk.Frame(lista)
        textos.grid(row=i, column=1, sticky="we", pady=(1, 10))
        ttk.Label(textos, text=titulo,
                  font=(familia, tamano, "bold" if siguiente else "normal")).pack(anchor="w")
        ttk.Label(textos, text=detalle, foreground="gray", wraplength=ANCHO_FICHA - 200,
                  justify="left").pack(anchor="w")
        zona = ttk.Frame(lista)
        zona.grid(row=i, column=2, sticky="ne", pady=(1, 10))
        for texto, accion in reversed(acciones):
            ttk.Button(zona, text=texto, command=accion).pack(side="right", padx=(4, 0))

    def _botones_fecha(self, cliente, periodo: str, que: str, valor: str | None):
        if valor:
            return [("Cambiar…", tras_el_clic(
                        self, lambda: self._cambiar_fecha(cliente, periodo, que, valor))),
                    ("Quitar", lambda: self._marcar(cliente, periodo, que, None))]
        return [("Marcar hoy", lambda: self._marcar(cliente, periodo, que,
                                                    date.today().isoformat()))]

    # ----------------------------------------------------------------- acciones
    def _nuevo(self) -> None:
        c = self.acciones.nuevo()
        if c is not None:
            self.elegir(c)

    def _marcar(self, cliente, periodo: str, que: str, fecha: str | None) -> None:
        if fecha is None and not messagebox.askyesno(
                TITULO, f"¿Quitar la marca de {que} de {nombre_periodo(periodo)}?"):
            return
        try:
            self.registro.marcar(cliente.id, periodo, que, fecha)
        except clientes.ErrorClientes as e:
            messagebox.showerror(TITULO, str(e))
            return
        self.contexto.seguimiento_cambio()

    def _cambiar_fecha(self, cliente, periodo: str, que: str, actual: str | None) -> None:
        fecha = pedir_fecha(self, f"Fecha de {que}",
                            f"¿Qué día quedó {que} {nombre_periodo(periodo)} de {cliente.nombre}?",
                            actual)
        if fecha:
            self._marcar(cliente, periodo, que, fecha)

    def _abrir_envio(self, estado: clientes.EstadoMes) -> None:
        ruta = Path(estado.carpeta_envio)
        if not ruta.is_absolute():
            ruta = self.registro.base / ruta
        if not ruta.exists():
            messagebox.showinfo(TITULO, f"La carpeta del envío ya no existe:\n{ruta}")
            return
        try:
            plataforma.abrir_en_explorador(ruta)
        except OSError as e:
            messagebox.showerror(TITULO, str(e))
