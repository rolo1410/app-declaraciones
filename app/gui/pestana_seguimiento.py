"""Página «Seguimiento»: todos los clientes y sus 12 meses del año.

Cada cliente es una fila con un cuadro por mes:

* gris: pendiente;
* naranja: declarada (la marca el contador tras presentarla en el SRI);
* verde: enviada al cliente por correo;
* ✓ dentro del cuadro: cobrada.

Al hacer clic en un cuadro se elige ese cliente y, a la derecha, se ve el
resumen del mes (totales del último cálculo), sus fechas y el historial del
cliente; desde ahí se marca declarada o cobrada.
"""
from __future__ import annotations

import sys
import tkinter as tk
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import font, messagebox, ttk

from ..core import clientes, plataforma
from ..core.informe import MESES, nombre_periodo
from .contexto import ContextoCliente
from .dialogos import pedir_fecha, tras_el_clic

TITULO = "Seguimiento"
ES_MAC = sys.platform == "darwin"
MESES_CORTOS = [m[:3].capitalize() for m in MESES]

LADO = 22          # lado del cuadro
PASO = 30          # ancho de cada columna de mes
ALTO_FILA = 44
X_MESES = 190      # inicio de la columna de meses (antes, nombre y RUC)
ALTO_CABECERA = 30


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
        "anillo": "#ffffff" if oscuro else "#1c1c1e",
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
        return "—"
    try:
        if len(texto) > 10:
            return datetime.strptime(texto, "%Y-%m-%d %H:%M").strftime("%d/%m/%Y %H:%M")
        return date.fromisoformat(texto).strftime("%d/%m/%Y")
    except ValueError:
        return texto


def _monto(valor) -> str:
    try:
        return f"$ {Decimal(str(valor)):,.2f}"
    except (InvalidOperation, ValueError):
        return "—"


class PestanaSeguimiento(ttk.Frame):
    def __init__(self, master, contexto: ContextoCliente, on_ir_declaracion=None) -> None:
        super().__init__(master, padding=(12, 4, 12, 8))
        self.contexto = contexto
        self.registro = contexto.registro
        self.on_ir_declaracion = on_ir_declaracion
        self.anio = date.today().year
        self.mes_sel: int | None = None
        self._clientes: list[clientes.Cliente] = []
        self._estados: dict = {}
        self.colores = paleta(self)
        self._construir()
        contexto.al_cambiar_lista(self.refrescar)
        contexto.al_cambiar_seguimiento(self.refrescar)
        contexto.al_cambiar_cliente(self._cliente_cambiado)
        self.refrescar()

    # ----------------------------------------------------------------- interfaz
    def _construir(self) -> None:
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 8))
        ttk.Button(barra, text="‹", width=2, command=lambda: self._cambiar_anio(-1)).pack(side="left")
        self.lbl_anio = ttk.Label(barra, text="", width=6, anchor="center",
                                  font=(font.nametofont("TkDefaultFont").actual("family"),
                                        15 if ES_MAC else 12, "bold"))
        self.lbl_anio.pack(side="left", padx=4)
        ttk.Button(barra, text="›", width=2, command=lambda: self._cambiar_anio(1)).pack(side="left")
        ttk.Label(barra, text="Buscar").pack(side="left", padx=(18, 6))
        self.var_buscar = tk.StringVar()
        ttk.Entry(barra, textvariable=self.var_buscar, width=24).pack(side="left")
        self.var_buscar.trace_add("write", lambda *_: self.refrescar())
        self._leyenda(barra)

        cuerpo = ttk.Frame(self)
        cuerpo.pack(fill="both", expand=True)

        # Cuadrícula (izquierda)
        izquierda = ttk.Frame(cuerpo)
        izquierda.pack(side="left", fill="both", expand=True)
        self.lienzo = tk.Canvas(izquierda, highlightthickness=0, background=self.colores["fondo"])
        scroll = ttk.Scrollbar(izquierda, orient="vertical", command=self.lienzo.yview)
        self.lienzo.configure(yscrollcommand=scroll.set)
        self.lienzo.pack(side="left", fill="both", expand=True)
        scroll.pack(side="left", fill="y")
        self.lienzo.bind("<Button-1>", self._clic)
        self.lienzo.bind("<Motion>", self._mover)
        self.lienzo.bind("<Leave>", lambda _e: self.lbl_estado.configure(text=""))
        self.lienzo.bind("<Configure>", lambda _e: self._dibujar())
        self.lienzo.bind("<MouseWheel>", self._rueda)
        self.lbl_estado = ttk.Label(izquierda, text="", foreground="gray")

        # Detalle del mes (derecha)
        self.panel = ttk.Frame(cuerpo, padding=(16, 0, 0, 0), width=330)
        self.panel.pack(side="left", fill="y")
        self.panel.pack_propagate(False)
        self._construir_panel()

    def _leyenda(self, barra) -> None:
        c = self.colores
        lienzo = tk.Canvas(barra, height=20, width=430, highlightthickness=0,
                           background=c["fondo"])
        lienzo.pack(side="right")
        x = 4
        fuente = font.nametofont("TkDefaultFont")
        for clave, texto in (("pendiente", "Pendiente"), ("declarada", "Declarada"),
                             ("enviada", "Enviada"), ("cobrada", "Cobrada")):
            color = c["enviada"] if clave == "cobrada" else c[clave]
            lienzo.create_rectangle(x, 3, x + 14, 17, fill=color, outline="")
            if clave == "cobrada":
                self._check(lienzo, x, 3, 14, "#ffffff")
            lienzo.create_text(x + 20, 10, text=texto, anchor="w", fill=c["texto"], font=fuente)
            x += 22 + fuente.measure(texto) + 18

    def _construir_panel(self) -> None:
        p = self.panel
        familia = font.nametofont("TkDefaultFont").actual("family")
        self.lbl_mes = ttk.Label(p, text="", font=(familia, 16 if ES_MAC else 13, "bold"))
        self.lbl_mes.pack(anchor="w")
        self.lbl_cliente = ttk.Label(p, text="Elija un cuadro de la cuadrícula.", foreground="gray",
                                     wraplength=300, justify="left")
        self.lbl_cliente.pack(anchor="w", pady=(2, 8))

        estado = ttk.Frame(p)
        estado.pack(anchor="w")
        self.chip = tk.Canvas(estado, width=14, height=14, highlightthickness=0,
                              background=self.colores["fondo"])
        self.chip.pack(side="left")
        self.lbl_chip = ttk.Label(estado, text="")
        self.lbl_chip.pack(side="left", padx=6)

        ttk.Separator(p).pack(fill="x", pady=10)
        ttk.Label(p, text="Resumen del mes", font=(familia, 13 if ES_MAC else 11, "bold")).pack(
            anchor="w")
        self.frm_resumen = ttk.Frame(p)
        self.frm_resumen.pack(fill="x", pady=(6, 0))
        self.frm_resumen.columnconfigure(1, weight=1)

        ttk.Separator(p).pack(fill="x", pady=10)
        self.frm_marcas = ttk.Frame(p)
        self.frm_marcas.pack(fill="x")
        self.frm_marcas.columnconfigure(1, weight=1)

        ttk.Separator(p).pack(fill="x", pady=10)
        self.lbl_hist = ttk.Label(p, text="Historial", font=(familia, 13 if ES_MAC else 11, "bold"))
        self.lbl_hist.pack(anchor="w")
        columnas = (("periodo", "Mes", 70), ("declarada", "Declarada", 76),
                    ("enviada", "Enviada", 76), ("cobrada", "Cobrada", 76))
        marco = ttk.Frame(p)
        marco.pack(fill="both", expand=True, pady=(6, 0))
        self.hist = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings",
                                 height=6, selectmode="browse")
        for clave, titulo, ancho in columnas:
            self.hist.heading(clave, text=titulo)
            self.hist.column(clave, width=ancho, anchor="w" if clave == "periodo" else "center")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.hist.yview)
        self.hist.configure(yscrollcommand=barra.set)
        self.hist.pack(side="left", fill="both", expand=True)
        barra.pack(side="left", fill="y")
        self.hist.bind("<<TreeviewSelect>>", self._elegir_historial)

    # ------------------------------------------------------------------ datos
    def refrescar(self) -> None:
        try:
            todos = self.registro.listar()
            self._estados = self.registro.estados_del_anio(self.anio)
        except Exception as e:  # noqa: BLE001
            todos, self._estados = [], {}
            self.lbl_estado.configure(text=f"No se pudo leer la base: {e}")
        buscar = self.var_buscar.get().strip().lower()
        self._clientes = [c for c in todos if not buscar or buscar in c.nombre.lower()
                          or buscar in c.ruc or (c.cedula and buscar in c.cedula)]
        self.lbl_anio.configure(text=str(self.anio))
        self._dibujar()
        self._mostrar_detalle()

    def _cambiar_anio(self, paso: int) -> None:
        self.anio += paso
        self.refrescar()

    def _cliente_cambiado(self) -> None:
        self._dibujar()
        self._mostrar_detalle()

    def _estado(self, cliente, mes: int) -> clientes.EstadoMes:
        return self._estados.get(cliente.id, {}).get(mes) or \
            clientes.EstadoMes(f"{self.anio:04d}-{mes:02d}")

    # ---------------------------------------------------------------- dibujo
    @staticmethod
    def _check(lienzo, x, y, lado, color) -> None:
        lienzo.create_line(x + lado * 0.24, y + lado * 0.52, x + lado * 0.43, y + lado * 0.70,
                           x + lado * 0.76, y + lado * 0.32, fill=color,
                           width=max(2, lado // 9), capstyle="round", joinstyle="round")

    def _dibujar(self) -> None:
        cv, c = self.lienzo, self.colores
        cv.delete("all")
        fuente = font.nametofont("TkDefaultFont")
        familia, tamano = fuente.actual("family"), fuente.actual("size")
        hoy = date.today()
        ancho = max(cv.winfo_width(), X_MESES + 12 * PASO + 8)

        if not self._clientes:
            texto = ("Ningún cliente coincide con la búsqueda." if self.var_buscar.get().strip()
                     else "Aún no hay clientes. Regístrelos en «Clientes».")
            cv.create_text(20, 40, text=texto, anchor="w", fill=c["secundario"], font=fuente)
            cv.configure(scrollregion=(0, 0, ancho, 100))
            return

        for mes in range(1, 13):
            x = X_MESES + (mes - 1) * PASO + LADO / 2
            actual = (self.anio, mes) == (hoy.year, hoy.month)
            cv.create_text(x, ALTO_CABECERA / 2, text=MESES_CORTOS[mes - 1],
                           fill=c["texto"] if actual else c["secundario"],
                           font=(familia, tamano - 1, "bold" if actual else "normal"))

        activo = self.contexto.cliente
        for fila, cliente in enumerate(self._clientes):
            y0 = ALTO_CABECERA + fila * ALTO_FILA
            sel = activo is not None and cliente.id == activo.id
            if sel:
                cv.create_rectangle(0, y0, ancho, y0 + ALTO_FILA, fill=c["fila_sel"], outline="")
            cv.create_text(8, y0 + ALTO_FILA / 2 - 8, text=self._recortar(cliente.nombre, fuente),
                           anchor="w", fill=c["texto"], font=fuente)
            por_cobrar = 0
            for mes in range(1, 13):
                estado = self._estado(cliente, mes)
                x = X_MESES + (mes - 1) * PASO
                y = y0 + (ALTO_FILA - LADO) / 2
                cv.create_rectangle(x, y, x + LADO, y + LADO, fill=c[estado.estado], outline="",
                                    tags=("cuadro",))
                if estado.cobrada:
                    color = "#ffffff" if estado.estado != "pendiente" else c["texto"]
                    self._check(cv, x, y, LADO, color)
                elif estado.estado != "pendiente":
                    por_cobrar += 1
                if sel and mes == self.mes_sel:
                    cv.create_rectangle(x - 3, y - 3, x + LADO + 3, y + LADO + 3,
                                        outline=c["anillo"], width=2)
            # Segunda línea: RUC y, si hay, meses hechos sin cobrar.
            id_ruc = cv.create_text(8, y0 + ALTO_FILA / 2 + 9, text=cliente.ruc, anchor="w",
                                    fill=c["secundario"], font=(familia, tamano - 2))
            if por_cobrar:
                x_fin = cv.bbox(id_ruc)[2]
                chica = font.Font(family=familia, size=tamano - 2)
                texto = f"· {por_cobrar} por cobrar"
                if x_fin + 8 + chica.measure(texto) > X_MESES - 10:
                    texto = f"· {por_cobrar}"  # sin espacio: solo el número (detalle al pasar)
                cv.create_text(x_fin + 8, y0 + ALTO_FILA / 2 + 9, text=texto, anchor="w",
                               fill=c["declarada"], font=chica)
        alto = ALTO_CABECERA + len(self._clientes) * ALTO_FILA + 8
        cv.configure(scrollregion=(0, 0, ancho, alto))

    @staticmethod
    def _recortar(texto: str, fuente, maximo: int = X_MESES - 24) -> str:
        if fuente.measure(texto) <= maximo:
            return texto
        while texto and fuente.measure(texto + "…") > maximo:
            texto = texto[:-1]
        return texto.rstrip() + "…"

    # ------------------------------------------------------------- interacción
    def _celda(self, evento) -> tuple[clientes.Cliente | None, int | None]:
        x, y = self.lienzo.canvasx(evento.x), self.lienzo.canvasy(evento.y)
        fila = int((y - ALTO_CABECERA) // ALTO_FILA)
        if y < ALTO_CABECERA or not (0 <= fila < len(self._clientes)):
            return None, None
        cliente = self._clientes[fila]
        rel = x - X_MESES
        mes = int(rel // PASO) + 1 if rel >= 0 else None
        if mes is not None and (mes > 12 or rel - (mes - 1) * PASO > LADO + 4):
            mes = None
        return cliente, mes

    def _clic(self, evento) -> None:
        if getattr(self.winfo_toplevel(), "pila_dialogos", None):
            return
        cliente, mes = self._celda(evento)
        if cliente is None:
            return
        if mes is not None:
            self.mes_sel = mes
        elif self.mes_sel is None:
            self.mes_sel = date.today().month if self.anio == date.today().year else 12
        activo = self.contexto.cliente
        if activo is None or activo.id != cliente.id:
            self.contexto.fijar(cliente)  # redibuja vía _cliente_cambiado
        else:
            self._dibujar()
            self._mostrar_detalle()

    def _mover(self, evento) -> None:
        cliente, mes = self._celda(evento)
        if cliente is None or mes is None:
            self.lbl_estado.configure(text="")
            return
        e = self._estado(cliente, mes)
        partes = [f"{cliente.nombre} · {MESES[mes - 1]} {self.anio}: {ETIQUETA_ESTADO[e.estado]}"]
        if e.cobrada:
            partes.append("cobrada")
        self.lbl_estado.configure(text=", ".join(partes))
        if not self.lbl_estado.winfo_ismapped():
            self.lbl_estado.pack(side="bottom", anchor="w", before=self.lienzo)

    def _rueda(self, evento) -> None:
        paso = -evento.delta if ES_MAC else -evento.delta // 120
        self.lienzo.yview_scroll(int(paso), "units")

    # ------------------------------------------------------------------ detalle
    def _periodo(self) -> str | None:
        return f"{self.anio:04d}-{self.mes_sel:02d}" if self.mes_sel else None

    def _mostrar_detalle(self) -> None:
        for hijo in (*self.frm_resumen.winfo_children(), *self.frm_marcas.winfo_children()):
            hijo.destroy()
        self.chip.delete("all")
        cliente, periodo = self.contexto.cliente, self._periodo()
        visible = cliente is not None and any(c.id == cliente.id for c in self._clientes)
        if not visible or periodo is None:
            self.lbl_mes.configure(text="")
            self.lbl_cliente.configure(text="Haga clic en un cuadro para ver el resumen de ese mes.")
            self.lbl_chip.configure(text="")
            self.hist.delete(*self.hist.get_children())
            self.lbl_hist.configure(text="Historial")
            return
        estado = self._estados.get(cliente.id, {}).get(self.mes_sel) or \
            self.registro.estado_mes(cliente.id, periodo)
        self.lbl_mes.configure(text=nombre_periodo(periodo).capitalize())
        self.lbl_cliente.configure(text=f"{cliente.nombre} · RUC {cliente.ruc}")
        self.chip.create_rectangle(0, 0, 14, 14, fill=self.colores[estado.estado], outline="")
        if estado.cobrada:
            self._check(self.chip, 0, 0, 14, "#ffffff")
        texto = ETIQUETA_ESTADO[estado.estado] + (" · cobrada" if estado.cobrada else "")
        self.lbl_chip.configure(text=texto)
        self._llenar_resumen(estado, cliente)
        self._llenar_marcas(estado, cliente, periodo)
        self._llenar_historial(cliente, periodo)

    def _fila(self, marco, fila: int, etiqueta: str, valor: str, negrita: bool = False) -> None:
        familia = font.nametofont("TkDefaultFont").actual("family")
        estilo = (familia, font.nametofont("TkDefaultFont").actual("size"),
                  "bold" if negrita else "normal")
        ttk.Label(marco, text=etiqueta, font=estilo).grid(row=fila, column=0, sticky="w", pady=1)
        ttk.Label(marco, text=valor, font=estilo).grid(row=fila, column=1, sticky="e", pady=1)

    def _llenar_resumen(self, estado: clientes.EstadoMes, cliente) -> None:
        m = self.frm_resumen
        r = estado.resumen
        if not r:
            ttk.Label(m, foreground="gray", wraplength=300, justify="left",
                      text="Aún no se ha calculado la declaración de este mes para este "
                           "cliente.").grid(row=0, column=0, columnspan=2, sticky="w")
            if self.on_ir_declaracion:
                ttk.Button(m, text="Ir a Declaración", command=self.on_ir_declaracion).grid(
                    row=1, column=0, sticky="w", pady=(8, 0))
            return
        filas = [("Ventas (409)", _monto(r.get("ventas"))),
                 ("Compras (509)", _monto(r.get("compras"))),
                 ("Impuesto generado (499)", _monto(r.get("impuesto_generado"))),
                 ("Crédito tributario (564)", _monto(r.get("credito_tributario")))]
        for i, (etiqueta, valor) in enumerate(filas):
            self._fila(m, i, etiqueta, valor)
        try:
            a_pagar = Decimal(str(r.get("impuesto_a_pagar", "0")))
        except InvalidOperation:
            a_pagar = Decimal("0")
        if a_pagar > 0:
            self._fila(m, 4, "Impuesto a pagar", _monto(a_pagar), negrita=True)
        else:
            self._fila(m, 4, "Crédito a favor", _monto(r.get("credito_a_favor")), negrita=True)
        ttk.Label(m, foreground="gray", text=(
            f"{r.get('comprobantes', '—')} comprobantes · calculada el "
            f"{_fecha(estado.calculada_en)}")).grid(row=5, column=0, columnspan=2, sticky="w",
                                                    pady=(6, 0))

    def _llenar_marcas(self, estado: clientes.EstadoMes, cliente, periodo: str) -> None:
        m = self.frm_marcas
        for fila, (que, etiqueta, valor) in enumerate((
            ("declarada", "Declarada", estado.declarada_en),
            ("enviada", "Enviada", estado.enviada_en),
            ("cobrada", "Cobrada", estado.cobrada_en),
        )):
            ttk.Label(m, text=etiqueta, width=10).grid(row=fila, column=0, sticky="w", pady=3)
            texto = _fecha(valor)
            if que == "enviada" and estado.envios > 1:
                texto += f"  ({estado.envios} envíos)"
            ttk.Label(m, text=texto).grid(row=fila, column=1, sticky="w", pady=3)
            botones = ttk.Frame(m)
            botones.grid(row=fila, column=2, sticky="e", pady=3)
            if que == "enviada":
                if estado.carpeta_envio:
                    ttk.Button(botones, text="Abrir envío",
                               command=lambda: self._abrir_envio(estado)).pack(side="right")
                continue
            if valor:
                ttk.Button(botones, text="Quitar", command=tras_el_clic(
                    self, lambda q=que: self._marcar(cliente, periodo, q, None))).pack(side="right")
                ttk.Button(botones, text="Cambiar…", command=tras_el_clic(
                    self, lambda q=que, v=valor: self._cambiar_fecha(cliente, periodo, q, v))).pack(
                    side="right", padx=(0, 4))
            else:
                ttk.Button(botones, text="Marcar hoy", command=lambda q=que: self._marcar(
                    cliente, periodo, q, date.today().isoformat())).pack(side="right")
                ttk.Button(botones, text="Otra fecha…", command=tras_el_clic(
                    self, lambda q=que: self._cambiar_fecha(cliente, periodo, q, None))).pack(
                    side="right", padx=(0, 4))

    def _llenar_historial(self, cliente, periodo: str) -> None:
        self.lbl_hist.configure(text="Historial del cliente")
        self.hist.delete(*self.hist.get_children())
        try:
            historial = self.registro.historial(cliente.id)
        except Exception:  # noqa: BLE001
            historial = []
        for e in historial:
            if e.estado == "pendiente" and not e.cobrada:
                continue  # solo calculado: aún sin fechas que mostrar
            anio, mes = e.periodo.split("-")
            self.hist.insert("", "end", iid=e.periodo, values=(
                f"{MESES_CORTOS[int(mes) - 1]} {anio}", _fecha(e.declarada_en)[:10],
                _fecha(e.enviada_en)[:10], _fecha(e.cobrada_en)))
        if self.hist.exists(periodo):
            self.hist.selection_set(periodo)
            self.hist.see(periodo)

    def _elegir_historial(self, _evento=None) -> None:
        sel = self.hist.selection()
        if not sel:
            return
        anio, mes = (int(x) for x in sel[0].split("-"))
        if (anio, mes) != (self.anio, self.mes_sel):
            self.anio, self.mes_sel = anio, mes
            self.refrescar()

    # ----------------------------------------------------------------- acciones
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
