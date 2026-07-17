"""Pestaña 3 — Declaración de IVA: clasificación de compras y casilleros calculados.

Se alimenta de los comprobantes analizados en la pestaña «Análisis» (XML del SRI)
o, alternativamente, de un archivo TXT de «Recibidos» descargado del portal.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import adaptador, calculadora, clasificador, parser
from ..core import analizador as az
from ..core.models import Comprobante, Declaracion

TITULO = "Declaración de IVA — SRI Ecuador"


class PestanaDeclaracion(ttk.Frame):
    def __init__(self, master) -> None:
        super().__init__(master, padding=8)

        self.comprobantes: list[Comprobante] = []
        self.advertencias: list[str] = []
        self.ruc: str | None = None
        self.declaracion: Declaracion | None = None

        self._construir()

    # ------------------------------------------------------------- interfaz
    def _construir(self) -> None:
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 6))
        ttk.Button(barra, text="Cargar archivo Recibidos (TXT)…",
                   command=self.cargar_txt).pack(side="left")
        ttk.Label(barra, text="  Período:").pack(side="left")
        self.combo_periodo = ttk.Combobox(barra, state="disabled", width=10)
        self.combo_periodo.pack(side="left")
        self.combo_periodo.bind("<<ComboboxSelected>>", lambda _e: self.refrescar_tabla())
        self.etiqueta_origen = ttk.Label(
            barra, text="Sin datos. Envíe comprobantes desde «Análisis» o cargue un TXT.",
            foreground="gray")
        self.etiqueta_origen.pack(side="left", padx=12)

        cuaderno = ttk.Notebook(self)
        cuaderno.pack(fill="both", expand=True)
        self.pestania_comprobantes = ttk.Frame(cuaderno, padding=8)
        self.pestania_formulario = ttk.Frame(cuaderno, padding=8)
        cuaderno.add(self.pestania_comprobantes, text="Compras y ventas")
        cuaderno.add(self.pestania_formulario, text="Formulario calculado")
        self.cuaderno = cuaderno

        self._construir_pestania_comprobantes()
        self._construir_pestania_formulario()

    def _construir_pestania_comprobantes(self) -> None:
        marco = self.pestania_comprobantes

        ayuda = ("Doble clic en una factura para alternar su derecho a crédito tributario. "
                 "Sugerencia inicial: facturas al RUC → con crédito; a la cédula → sin crédito.")
        ttk.Label(marco, text=ayuda, foreground="gray", wraplength=760,
                  justify="left").pack(anchor="w", pady=(0, 6))

        columnas = ("credito", "fecha", "emisor", "receptor", "base", "iva", "total", "tipo")
        self.tabla = ttk.Treeview(marco, columns=columnas, show="headings", selectmode="browse")
        anchos = {"credito": 90, "fecha": 90, "emisor": 320, "receptor": 130,
                  "base": 90, "iva": 80, "total": 90, "tipo": 120}
        titulos = {"credito": "Crédito", "fecha": "Fecha", "emisor": "Emisor",
                   "receptor": "Receptor", "base": "Base", "iva": "IVA",
                   "total": "Total", "tipo": "Tipo"}
        for columna in columnas:
            self.tabla.heading(columna, text=titulos[columna])
            alineacion = "e" if columna in ("base", "iva", "total") else "w"
            self.tabla.column(columna, width=anchos[columna], anchor=alineacion)
        barra_scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra_scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        barra_scroll.pack(side="left", fill="y")
        self.tabla.bind("<Double-1>", self.alternar_credito)

        panel = ttk.Frame(marco, padding=(12, 0, 0, 0))
        panel.pack(side="left", fill="y")

        acciones = ttk.LabelFrame(panel, text="Clasificación", padding=8)
        acciones.pack(fill="x", pady=(0, 10))
        ttk.Button(acciones, text="Sugerencia RUC/cédula",
                   command=self.aplicar_sugerencia).pack(fill="x", pady=2)
        ttk.Button(acciones, text="Todas con crédito",
                   command=self.aplicar_todas_con_credito).pack(fill="x", pady=2)

        ventas = ttk.LabelFrame(panel, text="Ventas del período (prellenado SRI)", padding=8)
        ventas.pack(fill="x")
        self.entradas: dict[str, tk.Entry] = {}
        campos = [
            ("ventas", "Ventas brutas (401)", "0"),
            ("notas_credito", "Notas de crédito emitidas", "0"),
            ("c483", "Impuesto meses anteriores (483)", "0"),
            ("emitidos", "Comprobantes emitidos (111)", "0"),
            ("anulados", "Comprobantes anulados (113)", "0"),
        ]
        for clave, etiqueta, inicial in campos:
            ttk.Label(ventas, text=etiqueta).pack(anchor="w")
            entrada = ttk.Entry(ventas, width=18)
            entrada.insert(0, inicial)
            entrada.pack(anchor="w", pady=(0, 6))
            self.entradas[clave] = entrada

        ttk.Button(panel, text="Calcular declaración ▸",
                   command=self.calcular).pack(fill="x", pady=12)
        self.etiqueta_totales = ttk.Label(panel, text="", justify="left")
        self.etiqueta_totales.pack(anchor="w")

    def _construir_pestania_formulario(self) -> None:
        marco = self.pestania_formulario
        columnas = ("campo", "descripcion", "valor")
        self.tabla_formulario = ttk.Treeview(marco, columns=columnas, show="headings")
        self.tabla_formulario.heading("campo", text="Casillero")
        self.tabla_formulario.heading("descripcion", text="Descripción")
        self.tabla_formulario.heading("valor", text="Valor")
        self.tabla_formulario.column("campo", width=80, anchor="center")
        self.tabla_formulario.column("descripcion", width=640, anchor="w")
        self.tabla_formulario.column("valor", width=130, anchor="e")
        barra_scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tabla_formulario.yview)
        self.tabla_formulario.configure(yscrollcommand=barra_scroll.set)
        self.tabla_formulario.pack(side="left", fill="both", expand=True)
        barra_scroll.pack(side="left", fill="y")

        panel = ttk.Frame(marco, padding=(12, 0, 0, 0))
        panel.pack(side="left", fill="y")
        self.etiqueta_resumen = ttk.Label(panel, text="Aún no se ha calculado.",
                                          justify="left", font=("", 12))
        self.etiqueta_resumen.pack(anchor="w", pady=(0, 12))
        ttk.Button(panel, text="Exportar a Excel…", command=self.exportar_excel).pack(fill="x", pady=2)
        ttk.Button(panel, text="Exportar a PDF…", command=self.exportar_pdf).pack(fill="x", pady=2)
        ttk.Label(panel, foreground="gray", wraplength=220, justify="left",
                  text="\nValores de apoyo: verifíquelos contra el prellenado "
                       "de SRI en línea antes de enviar la declaración.").pack(anchor="w")

    # ----------------------------------------------------- carga de datos
    def _establecer_comprobantes(self, comprobantes, advertencias, ruc, descripcion_origen) -> None:
        self.comprobantes = comprobantes
        self.advertencias = list(advertencias or [])
        self.ruc = ruc
        self.declaracion = None
        clasificador.sugerir_clasificacion(self.comprobantes, self.ruc)

        periodos = sorted({c.periodo for c in self.comprobantes})
        if periodos:
            self.combo_periodo.configure(state="readonly", values=periodos)
            self.combo_periodo.set(periodos[-1])
        else:
            self.combo_periodo.configure(state="disabled", values=[])
            self.combo_periodo.set("")
        self.etiqueta_origen.configure(
            text=f"{descripcion_origen} — {len(self.comprobantes)} comprobante(s)")

        if self.advertencias:
            messagebox.showwarning(
                TITULO, "Advertencias:\n\n" + "\n".join(self.advertencias[:20]))
        self.refrescar_tabla()

    def cargar_desde_analisis(self, comps_xml: "list[az.Comprobante]") -> None:
        """Recibe los comprobantes analizados (XML) desde la pestaña «Análisis»."""
        res = adaptador.adaptar_comprobantes(comps_xml)
        if not res.comprobantes:
            messagebox.showinfo(
                TITULO, "Los comprobantes analizados no incluyen compras declarables "
                        "(pueden ser solo retenciones o XML con error).")
            return
        origen = "Análisis de XML"
        if res.ignorados:
            origen += f" ({res.ignorados} no declarable/s omitido/s)"
        self._establecer_comprobantes(res.comprobantes, res.advertencias, self.ruc, origen)

    def cargar_txt(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Seleccione el archivo de comprobantes recibidos",
            filetypes=[("Archivos del SRI", "*.txt"), ("Todos", "*.*")],
        )
        if not ruta:
            return
        try:
            resultado = parser.leer_archivo(ruta)
        except ValueError as error:
            messagebox.showerror(TITULO, str(error))
            return
        if not resultado.comprobantes:
            messagebox.showwarning(TITULO, "El archivo no contiene comprobantes.")
            return
        ruc = parser.ruc_desde_nombre_archivo(ruta)
        self._establecer_comprobantes(
            resultado.comprobantes, resultado.advertencias, ruc, Path(ruta).name)

    # -------------------------------------------------------------- acciones
    def _comprobantes_periodo(self):
        if not self.comprobantes:
            return []
        return calculadora.filtrar_periodo(self.comprobantes, self.combo_periodo.get())

    def refrescar_tabla(self) -> None:
        self.tabla.delete(*self.tabla.get_children())
        for indice, c in enumerate(self._comprobantes_periodo()):
            if c.iva > 0:
                credito = "✔ Sí" if c.con_credito else "✘ No"
            else:
                credito = "— 0%"
            self.tabla.insert("", "end", iid=str(indice), values=(
                credito,
                c.fecha_emision.strftime("%d/%m/%Y"),
                c.razon_social_emisor,
                c.identificacion_receptor,
                f"{c.valor_sin_impuestos:,.2f}",
                f"{c.iva:,.2f}",
                f"{c.importe_total:,.2f}",
                c.tipo_comprobante,
            ))
        self._actualizar_totales()

    def alternar_credito(self, _evento) -> None:
        seleccion = self.tabla.focus()
        if not seleccion:
            return
        comprobante = self._comprobantes_periodo()[int(seleccion)]
        if comprobante.iva <= 0:
            return  # tarifa 0%: el derecho a crédito no aplica
        comprobante.con_credito = not comprobante.con_credito
        self.refrescar_tabla()

    def aplicar_sugerencia(self) -> None:
        if self.comprobantes:
            clasificador.sugerir_clasificacion(self.comprobantes, self.ruc)
            self.refrescar_tabla()

    def aplicar_todas_con_credito(self) -> None:
        if self.comprobantes:
            clasificador.marcar_todas_con_credito(self.comprobantes)
            self.refrescar_tabla()

    def _actualizar_totales(self) -> None:
        comprobantes = self._comprobantes_periodo()
        con = sum(c.iva for c in comprobantes if c.iva > 0 and c.con_credito)
        sin = sum(c.iva for c in comprobantes if c.iva > 0 and not c.con_credito)
        self.etiqueta_totales.configure(
            text=f"IVA con crédito: {con:,.2f}\nIVA sin crédito: {sin:,.2f}"
        )

    def _leer_decimal(self, clave: str, etiqueta: str) -> Decimal:
        texto = self.entradas[clave].get().strip().replace(",", ".") or "0"
        try:
            return Decimal(texto)
        except InvalidOperation as error:
            raise ValueError(f"Valor inválido en «{etiqueta}»: {texto}") from error

    def calcular(self) -> None:
        if not self.comprobantes:
            messagebox.showinfo(TITULO, "Primero envíe comprobantes desde «Análisis» o cargue un TXT.")
            return
        try:
            ventas = self._leer_decimal("ventas", "Ventas brutas")
            notas = self._leer_decimal("notas_credito", "Notas de crédito")
            c483 = self._leer_decimal("c483", "Impuesto meses anteriores")
            emitidos = int(self.entradas["emitidos"].get() or 0)
            anulados = int(self.entradas["anulados"].get() or 0)
        except ValueError as error:
            messagebox.showerror(TITULO, str(error))
            return

        self.declaracion = calculadora.calcular_declaracion(
            self.comprobantes,
            self.combo_periodo.get(),
            ventas_brutas=ventas,
            notas_credito_emitidas=notas,
            impuesto_meses_anteriores=c483,
            comprobantes_emitidos=emitidos,
            comprobantes_anulados=anulados,
            advertencias=self.advertencias,
        )
        self._mostrar_formulario()
        self.cuaderno.select(self.pestania_formulario)

    def _mostrar_formulario(self) -> None:
        declaracion = self.declaracion
        assert declaracion is not None
        self.tabla_formulario.delete(*self.tabla_formulario.get_children())
        for campo, descripcion, valor in calculadora.filas_formulario(declaracion):
            if campo == "563":
                texto = f"{valor:.4f}"
            elif isinstance(valor, Decimal):
                texto = f"{valor:,.2f}"
            else:
                texto = str(valor)
            self.tabla_formulario.insert("", "end", values=(campo, descripcion, texto))

        resumen = declaracion.resumen
        if resumen.impuesto_a_pagar > 0:
            resultado = f"IMPUESTO A PAGAR: {resumen.impuesto_a_pagar:,.2f}"
        else:
            resultado = f"CRÉDITO A FAVOR: {resumen.credito_a_favor:,.2f}"
        self.etiqueta_resumen.configure(
            text=(f"Período {declaracion.periodo}\n\n"
                  f"Impuesto generado (499): {resumen.impuesto_generado:,.2f}\n"
                  f"Crédito tributario (564): {resumen.credito_tributario:,.2f}\n\n"
                  f"{resultado}")
        )

    # ----------------------------------------------------------- exportación
    def _exportar(self, extension: str, funcion) -> None:
        if not self.declaracion:
            messagebox.showinfo(TITULO, "Primero calcule la declaración.")
            return
        ruta = filedialog.asksaveasfilename(
            defaultextension=extension,
            initialfile=f"declaracion_iva_{self.declaracion.periodo}{extension}",
            filetypes=[(extension.upper().strip("."), f"*{extension}")],
        )
        if not ruta:
            return
        try:
            funcion(self.declaracion, ruta)
        except ImportError as error:
            messagebox.showerror(TITULO, f"Falta una dependencia para exportar: {error}")
            return
        messagebox.showinfo(TITULO, f"Reporte guardado en:\n{ruta}")

    def exportar_excel(self) -> None:
        from ..export.excel import exportar_excel
        self._exportar(".xlsx", exportar_excel)

    def exportar_pdf(self) -> None:
        from ..export.pdf import exportar_pdf
        self._exportar(".pdf", exportar_pdf)
