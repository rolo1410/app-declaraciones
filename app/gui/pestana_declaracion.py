"""Pestaña 3 — Declaración de IVA: clasificación de compras y casilleros calculados.

Se alimenta de los comprobantes analizados en la pestaña «Análisis» (XML del SRI)
o, alternativamente, de un archivo TXT de «Recibidos» descargado del portal.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from ..core import adaptador, calculadora, clasificador, parser, sesion
from ..core import analizador as az
from ..core.models import Comprobante, Declaracion
from .dialogos import pedir_envio, tras_el_clic, tipos_archivo

TITULO = "Declaración de IVA — SRI Ecuador"


class PestanaDeclaracion(ttk.Frame):
    def __init__(self, master, contexto=None, on_configurar=None) -> None:
        super().__init__(master, padding=8)
        self.contexto = contexto
        # Lleva a la pestaña «Configuración» si falta configurar el correo.
        self.on_configurar = on_configurar
        self._enviando = False

        self.comprobantes: list[Comprobante] = []
        self.advertencias: list[str] = []
        self.ruc: str | None = None
        self.declaracion: Declaracion | None = None
        self.origen = ""
        # Orden de la tabla de comprobantes: (columna, descendente) o None.
        self._orden: tuple[str, bool] | None = None
        # Comprobantes mostrados en la tabla; el iid de cada fila es su índice aquí.
        self._visibles: list[Comprobante] = []

        self._construir()

    # ------------------------------------------------------------- interfaz
    def _construir(self) -> None:
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(0, 6))
        ttk.Button(barra, text="Cargar archivo Recibidos (TXT)…",
                   command=self.cargar_txt).pack(side="left")
        ttk.Button(barra, text="Abrir trabajo…",
                   command=self.abrir_trabajo).pack(side="left", padx=(6, 0))
        ttk.Button(barra, text="Guardar trabajo…",
                   command=self.guardar_trabajo).pack(side="left", padx=(6, 0))
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

        cabecera = ttk.Frame(marco)
        cabecera.pack(fill="x", pady=(0, 6))
        ayuda = ("Doble clic en una factura para alternar su derecho a crédito tributario. "
                 "Sugerencia inicial: facturas al RUC → con crédito; a la cédula → sin crédito.")
        ttk.Label(cabecera, text=ayuda, foreground="gray", wraplength=640,
                  justify="left").pack(side="left", anchor="w")
        self.var_agrupar = tk.BooleanVar(value=True)
        ttk.Checkbutton(cabecera, text="Agrupar por emisor", variable=self.var_agrupar,
                        command=self.refrescar_tabla).pack(side="right")

        # Izquierda: tabla arriba y detalle de la factura seleccionada abajo.
        division = ttk.PanedWindow(marco, orient="vertical")
        division.pack(side="left", fill="both", expand=True)
        marco_tabla = ttk.Frame(division)
        division.add(marco_tabla, weight=3)

        columnas = ("credito", "fecha", "emisor", "receptor", "base", "iva", "total", "tipo")
        # La columna de árbol (#0) solo muestra el triángulo de expandir del grupo.
        self.tabla = ttk.Treeview(marco_tabla, columns=columnas, show="tree headings",
                                  selectmode="browse")
        self.tabla.column("#0", width=22, stretch=False)
        fuente_grupo = font.nametofont("TkDefaultFont").copy()
        fuente_grupo.configure(weight="bold")
        self.tabla.tag_configure("grupo", font=fuente_grupo)
        anchos = {"credito": 90, "fecha": 90, "emisor": 320, "receptor": 130,
                  "base": 90, "iva": 80, "total": 90, "tipo": 120}
        titulos = {"credito": "Crédito", "fecha": "Fecha", "emisor": "Emisor",
                   "receptor": "Receptor", "base": "Base", "iva": "IVA",
                   "total": "Total", "tipo": "Tipo"}
        self._titulos = titulos
        for columna in columnas:
            self.tabla.heading(columna, text=titulos[columna],
                               command=lambda col=columna: self.ordenar_por(col))
            alineacion = "e" if columna in ("base", "iva", "total") else "w"
            self.tabla.column(columna, width=anchos[columna], anchor=alineacion)
        barra_scroll = ttk.Scrollbar(marco_tabla, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra_scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        barra_scroll.pack(side="left", fill="y")
        self.tabla.bind("<Double-1>", self.alternar_credito)
        self.tabla.bind("<<TreeviewSelect>>", self._mostrar_detalle)
        self.tabla.bind("<<TreeviewOpen>>", self._recordar_grupos)
        self.tabla.bind("<<TreeviewClose>>", self._recordar_grupos)
        self._grupos_cerrados: set[str] = set()

        marco_detalle = ttk.LabelFrame(division, text="Detalle de la factura", padding=8)
        division.add(marco_detalle, weight=2)
        self.etiqueta_detalle = ttk.Label(
            marco_detalle, text="Seleccione una factura para ver su detalle.",
            justify="left", anchor="nw")
        self.etiqueta_detalle.pack(fill="x", anchor="nw", pady=(0, 6))
        columnas_detalle = (("desc", "Descripción", 360, "w"), ("cant", "Cant.", 70, "e"),
                            ("punit", "P. unit.", 90, "e"), ("total", "Total", 90, "e"),
                            ("iva", "IVA %", 60, "e"))
        self.tabla_detalle = ttk.Treeview(
            marco_detalle, columns=[c[0] for c in columnas_detalle], show="headings", height=6)
        for clave, titulo, ancho, alineacion in columnas_detalle:
            self.tabla_detalle.heading(clave, text=titulo)
            self.tabla_detalle.column(clave, width=ancho, anchor=alineacion,
                                      stretch=(clave == "desc"))
        scroll_detalle = ttk.Scrollbar(marco_detalle, orient="vertical",
                                       command=self.tabla_detalle.yview)
        self.tabla_detalle.configure(yscrollcommand=scroll_detalle.set)
        self.tabla_detalle.pack(side="left", fill="both", expand=True)
        scroll_detalle.pack(side="left", fill="y")

        panel = ttk.Frame(marco, padding=(12, 0, 0, 0))
        panel.pack(side="left", fill="y")

        acciones = ttk.LabelFrame(panel, text="Clasificación", padding=8)
        acciones.pack(fill="x", pady=(0, 10))
        ttk.Button(acciones, text="Sugerencia RUC/cédula",
                   command=self.aplicar_sugerencia).pack(fill="x", pady=2)
        ttk.Button(acciones, text="Todas con crédito",
                   command=self.aplicar_todas_con_credito).pack(fill="x", pady=2)
        ttk.Separator(acciones, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(acciones, text="Emisor seleccionado:").pack(anchor="w")
        ttk.Button(acciones, text="✔ Todo con crédito",
                   command=lambda: self.marcar_emisor(True)).pack(fill="x", pady=2)
        ttk.Button(acciones, text="✘ Todo sin crédito",
                   command=lambda: self.marcar_emisor(False)).pack(fill="x", pady=2)

        ventas = ttk.LabelFrame(panel, text="Ventas del período (prellenado SRI)", padding=8)
        ventas.pack(fill="x")
        self.entradas: dict[str, tk.Entry] = {}
        campos = [
            ("ventas", "Ventas brutas IVA ≠0% (401)", "0"),
            ("ventas_cero", "Ventas brutas IVA 0% sin crédito (403)", "0"),
            ("ventas_cero_credito", "Ventas brutas IVA 0% con crédito (405)", "0"),
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
        ttk.Separator(panel).pack(fill="x", pady=8)
        self.btn_enviar = ttk.Button(panel, text="Enviar al cliente por correo…",
                                     command=tras_el_clic(self, self.enviar_por_correo))
        self.btn_enviar.pack(fill="x", pady=2)
        self.lbl_envio = ttk.Label(panel, text="", wraplength=220, justify="left")
        self.lbl_envio.pack(anchor="w", pady=(4, 0))
        ttk.Label(panel, foreground="gray", wraplength=220, justify="left",
                  text="\nValores de apoyo: verifíquelos contra el prellenado "
                       "de SRI en línea antes de enviar la declaración.").pack(anchor="w")

    # ----------------------------------------------------- carga de datos
    def _establecer_comprobantes(self, comprobantes, advertencias, ruc, descripcion_origen,
                                 sugerir: bool = True, periodo: str = "") -> None:
        self.comprobantes = comprobantes
        self.advertencias = list(advertencias or [])
        self.ruc = ruc
        self.declaracion = None
        self.origen = descripcion_origen
        if sugerir:
            clasificador.sugerir_clasificacion(self.comprobantes, self.ruc)

        periodos = sorted({c.periodo for c in self.comprobantes})
        if periodos:
            self.combo_periodo.configure(state="readonly", values=periodos)
            self.combo_periodo.set(periodo if periodo in periodos else periodos[-1])
        else:
            self.combo_periodo.configure(state="disabled", values=[])
            self.combo_periodo.set("")
        self.etiqueta_origen.configure(
            text=f"{descripcion_origen} — {len(self.comprobantes)} comprobante(s)")

        if self.advertencias and sugerir:
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

    def guardar_trabajo(self) -> None:
        if not self.comprobantes:
            messagebox.showinfo(TITULO, "No hay compras cargadas para guardar.")
            return
        periodo = self.combo_periodo.get()
        carpeta = self._carpeta_resultados(periodo)
        ruta = filedialog.asksaveasfilename(
            title="Guardar trabajo de la declaración",
            defaultextension=sesion.EXTENSION,
            initialfile=f"declaracion_{periodo}{sesion.EXTENSION}",
            initialdir=str(carpeta) if carpeta else None,
            filetypes=tipos_archivo(("Trabajo de declaración", f"*{sesion.EXTENSION}"),
                                    ("Todos", "*.*")),
        )
        if not ruta:
            return
        datos = sesion.Sesion(
            comprobantes=self.comprobantes,
            periodo=periodo,
            ruc=self.ruc,
            origen=self.origen,
            advertencias=self.advertencias,
            ventas={clave: entrada.get() for clave, entrada in self.entradas.items()},
        )
        try:
            sesion.guardar(datos, ruta)
        except OSError as error:
            messagebox.showerror(TITULO, f"No se pudo guardar: {error}")
            return
        self._registrar("trabajo_guardado", ruta)
        messagebox.showinfo(TITULO, f"Trabajo guardado en:\n{ruta}")

    def abrir_trabajo(self) -> None:
        carpeta = self._carpeta_resultados(None)
        ruta = filedialog.askopenfilename(
            title="Abrir trabajo de la declaración",
            initialdir=str(carpeta) if carpeta else None,
            filetypes=tipos_archivo(("Trabajo de declaración", f"*{sesion.EXTENSION}"),
                                    ("JSON", "*.json"), ("Todos", "*.*")),
        )
        if not ruta:
            return
        try:
            datos = sesion.cargar(ruta)
        except ValueError as error:
            messagebox.showerror(TITULO, str(error))
            return
        if not self._confirmar_cliente_del_trabajo(datos.ruc):
            return
        for clave, entrada in self.entradas.items():
            entrada.delete(0, "end")
            entrada.insert(0, datos.ventas.get(clave, "0"))
        # La clasificación guardada se respeta: no se vuelve a sugerir.
        self._establecer_comprobantes(
            datos.comprobantes, datos.advertencias, datos.ruc,
            datos.origen or Path(ruta).name, sugerir=False, periodo=datos.periodo)

    # ------------------------------------------------- cliente activo
    def _carpeta_resultados(self, periodo):
        if self.contexto is None:
            return None
        return self.contexto.carpeta_resultados(periodo)

    def _registrar(self, accion: str, ruta: str) -> None:
        if self.contexto is not None:
            self.contexto.registrar(accion, ruta)

    def _confirmar_cliente_del_trabajo(self, ruc: str | None) -> bool:
        """Avisa si el trabajo es de otro contribuyente y ofrece cambiar de cliente."""
        if self.contexto is None or not ruc:
            return True
        activo = self.contexto.cliente
        if activo is not None and ruc in activo.identificaciones:
            return True
        try:
            duenio = self.contexto.registro.por_identificacion(ruc)
        except Exception:  # noqa: BLE001
            duenio = None
        if duenio is not None and duenio.activo:
            respuesta = messagebox.askyesnocancel(
                TITULO, f"Este trabajo es de {duenio.nombre} ({duenio.ruc}).\n\n"
                        "¿Cambiar el cliente activo a ese contribuyente?\n"
                        "(No: abrirlo sin cambiar de cliente)")
            if respuesta is None:
                return False
            if respuesta:
                self.contexto.fijar(duenio)
            return True
        if activo is not None:
            return messagebox.askyesno(
                TITULO, f"Este trabajo es del RUC {ruc}, que no es el cliente activo "
                        f"({activo.nombre}, {activo.ruc}).\n\n¿Abrirlo de todas formas?")
        return True

    # -------------------------------------------------------------- acciones
    def _comprobantes_periodo(self):
        if not self.comprobantes:
            return []
        return calculadora.filtrar_periodo(self.comprobantes, self.combo_periodo.get())

    _CLAVES_ORDEN = {
        "credito": lambda c: (c.iva > 0, c.con_credito),
        "fecha": lambda c: c.fecha_emision,
        "emisor": lambda c: c.razon_social_emisor.lower(),
        "receptor": lambda c: c.identificacion_receptor,
        "base": lambda c: c.valor_sin_impuestos,
        "iva": lambda c: c.iva,
        "total": lambda c: c.importe_total,
        "tipo": lambda c: c.tipo_comprobante.lower(),
    }

    def ordenar_por(self, columna: str) -> None:
        """Clic en un encabezado: ordena ascendente; otro clic invierte el orden."""
        if self._orden and self._orden[0] == columna:
            self._orden = (columna, not self._orden[1])
        else:
            self._orden = (columna, False)
        for col, titulo in self._titulos.items():
            if col == columna:
                titulo += " ▼" if self._orden[1] else " ▲"
            self.tabla.heading(col, text=titulo)
        self.refrescar_tabla()

    @staticmethod
    def _signo(c: Comprobante) -> int:
        return -1 if c.es_nota_credito else 1

    @staticmethod
    def _texto_credito(c: Comprobante) -> str:
        if c.iva <= 0:
            return "— 0%"
        return "✔ Sí" if c.con_credito else "✘ No"

    def _seleccionado(self) -> Comprobante | None:
        seleccion = self.tabla.selection()
        if not seleccion or seleccion[0].startswith("g:"):
            return None
        return self._visibles[int(seleccion[0])]

    def refrescar_tabla(self) -> None:
        anterior = self._seleccionado()
        self.tabla.delete(*self.tabla.get_children())
        self._visibles = self._comprobantes_periodo()
        filas = list(enumerate(self._visibles))
        columna, descendente = self._orden or ("fecha", False)
        clave = self._CLAVES_ORDEN[columna]
        filas.sort(key=lambda fila: clave(fila[1]), reverse=descendente)

        if self.var_agrupar.get():
            self._insertar_agrupado(filas, columna, descendente)
        else:
            for indice, c in filas:
                self._insertar_factura("", indice, c)

        # Mantener seleccionada la misma factura (por identidad, no por índice).
        iid = next((str(i) for i, c in filas if c is anterior), None)
        if iid:
            self.tabla.selection_set(iid)
            self.tabla.focus(iid)
            self.tabla.see(iid)
        self._mostrar_detalle()
        self._actualizar_totales()

    def _insertar_factura(self, padre: str, indice: int, c: Comprobante) -> None:
        self.tabla.insert(padre, "end", iid=str(indice), values=(
            self._texto_credito(c),
            c.fecha_emision.strftime("%d/%m/%Y"),
            c.razon_social_emisor,
            c.identificacion_receptor,
            f"{c.valor_sin_impuestos:,.2f}",
            f"{c.iva:,.2f}",
            f"{c.importe_total:,.2f}",
            c.tipo_comprobante,
        ))

    def _insertar_agrupado(self, filas, columna: str, descendente: bool) -> None:
        grupos: dict[str, list] = {}
        for indice, c in filas:  # conserva el orden de las facturas dentro del grupo
            grupos.setdefault(c.ruc_emisor or c.razon_social_emisor, []).append((indice, c))

        def totales(miembros):
            # Las notas de crédito restan del subtotal del emisor.
            return {campo: sum((self._signo(c) * getattr(c, campo) for _, c in miembros),
                               Decimal("0"))
                    for campo in ("valor_sin_impuestos", "iva", "importe_total")}

        sumas = {ruc: totales(miembros) for ruc, miembros in grupos.items()}
        campo_suma = {"base": "valor_sin_impuestos", "iva": "iva", "total": "importe_total"}
        if columna in campo_suma:
            orden_grupos = sorted(grupos, key=lambda r: sumas[r][campo_suma[columna]],
                                  reverse=descendente)
        elif columna == "emisor":
            orden_grupos = sorted(grupos, key=lambda r: grupos[r][0][1].razon_social_emisor.lower(),
                                  reverse=descendente)
        else:
            orden_grupos = list(grupos)  # según su primera factura ya ordenada

        for ruc in orden_grupos:
            miembros = grupos[ruc]
            if len(miembros) == 1:
                # Una sola factura: no hace falta expandir, va directa.
                self._insertar_factura("", *miembros[0])
                continue
            primero = miembros[0][1]
            gravadas = [c for _, c in miembros if c.iva > 0]
            con_credito = sum(1 for c in gravadas if c.con_credito)
            credito = f"{con_credito}/{len(gravadas)}" if gravadas else "— 0%"
            iid = f"g:{ruc}"
            self.tabla.insert("", "end", iid=iid, open=iid not in self._grupos_cerrados,
                              tags=("grupo",), values=(
                credito,
                f"{len(miembros)} doc.",
                primero.razon_social_emisor,
                ruc,
                f"{sumas[ruc]['valor_sin_impuestos']:,.2f}",
                f"{sumas[ruc]['iva']:,.2f}",
                f"{sumas[ruc]['importe_total']:,.2f}",
                "",
            ))
            for indice, c in miembros:
                self._insertar_factura(iid, indice, c)

    def _recordar_grupos(self, _evento=None) -> None:
        # El evento llega antes de cambiar el estado: se lee después.
        def leer():
            self._grupos_cerrados = {
                iid for iid in self.tabla.get_children()
                if iid.startswith("g:") and not self.tabla.item(iid, "open")}
        self.after_idle(leer)

    def _mostrar_detalle(self, _evento=None) -> None:
        self.tabla_detalle.delete(*self.tabla_detalle.get_children())
        seleccion = self.tabla.selection()
        if not seleccion or seleccion[0].startswith("g:"):
            if seleccion:
                hijos = self.tabla.get_children(seleccion[0])
                self.etiqueta_detalle.configure(
                    text=f"Emisor: {self.tabla.set(seleccion[0], 'emisor')} "
                         f"({seleccion[0][2:]})\n{len(hijos)} comprobante(s). "
                         "Seleccione una factura para ver su detalle.")
            else:
                self.etiqueta_detalle.configure(
                    text="Seleccione una factura para ver su detalle.")
            return
        c = self._visibles[int(seleccion[0])]
        receptor = c.identificacion_receptor
        if c.razon_social_receptor:
            receptor = f"{c.razon_social_receptor} ({receptor})"
        texto = (
            f"{c.tipo_comprobante}   Nº {c.serie_comprobante}   "
            f"Fecha: {c.fecha_emision.strftime('%d/%m/%Y')}\n"
            f"Emisor: {c.razon_social_emisor} ({c.ruc_emisor})\n"
            f"Receptor: {receptor}\n"
            f"Base gravada: {c.valor_sin_impuestos:,.2f}   IVA: {c.iva:,.2f}   "
            f"Base 0%: {c.base_tarifa_cero:,.2f}   Total: {c.importe_total:,.2f}   "
            f"Crédito tributario: {self._texto_credito(c)}\n"
            f"Clave de acceso: {c.clave_acceso}"
        )
        if c.advertencias:
            texto += "\n⚠ " + "\n⚠ ".join(c.advertencias)
        if not c.detalles:
            texto += "\n(Sin líneas de detalle: solo los XML las incluyen, no el TXT.)"
        self.etiqueta_detalle.configure(text=texto)
        for ln in c.detalles:
            self.tabla_detalle.insert("", "end", values=(
                ln.descripcion, f"{ln.cantidad:g}", f"{ln.precio_unitario:,.2f}",
                f"{ln.precio_total:,.2f}", f"{ln.tarifa_iva:g}"))

    def alternar_credito(self, evento) -> None:
        # Un doble clic en el encabezado (ordenar) no debe tocar la fila enfocada.
        if self.tabla.identify_region(evento.x, evento.y) not in ("cell", "tree"):
            return
        seleccion = self.tabla.focus()
        if not seleccion or seleccion.startswith("g:"):
            return  # en un grupo, el doble clic solo expande/contrae
        comprobante = self._visibles[int(seleccion)]
        if comprobante.iva <= 0:
            return  # tarifa 0%: el derecho a crédito no aplica
        comprobante.con_credito = not comprobante.con_credito
        self.refrescar_tabla()

    def marcar_emisor(self, con_credito: bool) -> None:
        """Marca todas las facturas del emisor seleccionado (fila de emisor o factura)."""
        seleccion = self.tabla.selection()
        if not seleccion:
            messagebox.showinfo(TITULO, "Seleccione un emisor o una de sus facturas.")
            return
        if seleccion[0].startswith("g:"):
            ruc = seleccion[0][2:]
        else:
            c = self._visibles[int(seleccion[0])]
            ruc = c.ruc_emisor or c.razon_social_emisor
        for c in self._visibles:
            if (c.ruc_emisor or c.razon_social_emisor) == ruc and c.iva > 0:
                c.con_credito = con_credito
        self.refrescar_tabla()
        if seleccion[0].startswith("g:") and self.tabla.exists(seleccion[0]):
            self.tabla.selection_set(seleccion[0])

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
            ventas = self._leer_decimal("ventas", "Ventas brutas IVA ≠0%")
            ventas_cero = self._leer_decimal("ventas_cero", "Ventas brutas IVA 0% sin crédito")
            ventas_cero_credito = self._leer_decimal(
                "ventas_cero_credito", "Ventas brutas IVA 0% con crédito")
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
            ventas_tarifa_cero=ventas_cero,
            ventas_tarifa_cero_con_credito=ventas_cero_credito,
        )
        self._mostrar_formulario()
        self.cuaderno.select(self.pestania_formulario)
        self._guardar_resumen_del_mes()

    def _cliente_del_trabajo(self):
        """Cliente activo si el trabajo es suyo (o no se sabe de quién es)."""
        if self.contexto is None or self.contexto.cliente is None:
            return None
        cliente = self.contexto.cliente
        if self.ruc and self.ruc not in cliente.identificaciones:
            return None
        return cliente

    def _guardar_resumen_del_mes(self) -> None:
        """Deja el resumen del cálculo en el seguimiento mensual del cliente."""
        from datetime import datetime

        cliente = self._cliente_del_trabajo()
        if cliente is None or self.declaracion is None:
            return
        d = self.declaracion
        r = d.resumen
        resumen = {
            "impuesto_generado": str(r.impuesto_generado),
            "credito_tributario": str(r.credito_tributario),
            "impuesto_a_pagar": str(r.impuesto_a_pagar),
            "credito_a_favor": str(r.credito_a_favor),
            "ventas": str(d.ventas.c409),
            "compras": str(d.compras.c509),
            "comprobantes": len(calculadora.filtrar_periodo(self.comprobantes, d.periodo)),
        }
        try:
            self.contexto.registro.guardar_resumen(
                cliente.id, d.periodo, resumen, f"{datetime.now():%Y-%m-%d %H:%M}")
            self.contexto.seguimiento_cambio()
        except Exception:  # noqa: BLE001 - el seguimiento nunca debe impedir el trabajo
            pass

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
        carpeta = self._carpeta_resultados(self.declaracion.periodo)
        ruta = filedialog.asksaveasfilename(
            initialdir=str(carpeta) if carpeta else None,
            defaultextension=extension,
            initialfile=f"declaracion_iva_{self.declaracion.periodo}{extension}",
            filetypes=tipos_archivo((extension.upper().strip("."), f"*{extension}")),
        )
        if not ruta:
            return
        try:
            funcion(self.declaracion, ruta)
        except ImportError as error:
            messagebox.showerror(TITULO, f"Falta una dependencia para exportar: {error}")
            return
        self._registrar("exportacion", ruta)
        messagebox.showinfo(TITULO, f"Reporte guardado en:\n{ruta}")

    def exportar_excel(self) -> None:
        from ..export.excel import exportar_excel
        self._exportar(".xlsx", exportar_excel)

    def exportar_pdf(self) -> None:
        from ..export.pdf import exportar_pdf
        self._exportar(".pdf", exportar_pdf)

    # ---------------------------------------------------------- envío por correo
    def _faltan_ajustes(self, mensaje: str) -> None:
        if messagebox.askyesno(TITULO, mensaje + "\n\n¿Ir a «Configuración»?") and self.on_configurar:
            self.on_configurar()

    def enviar_por_correo(self) -> None:
        """Arma el informe (PDF, Excel, XML) y lo envía al correo del cliente."""
        from ..core import informe, perfil

        if self._enviando:
            return
        if not self.declaracion:
            messagebox.showinfo(TITULO, "Primero calcule la declaración.")
            return
        if self.contexto is None or self.contexto.cliente is None:
            messagebox.showinfo(TITULO, "Elija el cliente en el selector «Cliente» de arriba: "
                                        "el informe se envía a su correo.")
            return
        if not self._confirmar_cliente_del_trabajo(self.ruc):
            return
        cliente = self.contexto.cliente
        registro = self.contexto.registro
        ajustes = perfil.leer()
        if not ajustes.declarante.completo:
            self._faltan_ajustes("Faltan sus datos (nombre y correo de contacto) para el "
                                 "informe y la firma del correo.")
            return
        try:
            hay_clave = registro.tiene_clave_smtp()
        except Exception:  # noqa: BLE001
            hay_clave = False
        if not ajustes.correo.configurado or not hay_clave:
            self._faltan_ajustes("Falta configurar la cuenta de correo de envío "
                                 "(servidor, usuario y contraseña).")
            return

        declaracion = self.declaracion
        claves = informe.claves_del_periodo(declaracion)
        try:
            carpeta_xml = registro.carpeta_descargas(cliente)
        except Exception:  # noqa: BLE001
            carpeta_xml = None
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            xml = informe.xml_de_comprobantes(carpeta_xml, claves) if carpeta_xml else []
        finally:
            self.configure(cursor="")
        datos = pedir_envio(
            self,
            para=cliente.correo or "",
            asunto=informe.asunto(declaracion, cliente.nombre),
            cuerpo=informe.cuerpo(declaracion, cliente.nombre, cliente.ruc, ajustes.declarante),
            xml_encontrados=len(xml), xml_esperados=len(claves),
            correo_guardado=cliente.correo,
            mes=informe.nombre_periodo(declaracion.periodo),
            ya_declarada=bool(registro.estado_mes(cliente.id, declaracion.periodo).declarada_en),
        )
        if not datos:
            return
        if datos["guardar_correo"]:
            try:
                registro.fijar_correo(cliente.id, datos["para"])
                self.contexto.lista_cambio()
            except Exception as e:  # noqa: BLE001
                messagebox.showwarning(TITULO, f"No se guardó el correo del cliente:\n{e}")

        carpeta_resultados = self._carpeta_resultados(declaracion.periodo)
        if carpeta_resultados is None:
            messagebox.showerror(TITULO, "No se pudo crear la carpeta de resultados del cliente.")
            return
        destino = informe.carpeta_envio(carpeta_resultados)
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            paquete = informe.armar_paquete(
                declaracion, destino, contribuyente=(cliente.nombre, cliente.ruc),
                declarante=ajustes.declarante, logo=ajustes.ruta_logo(),
                carpeta_xml=carpeta_xml, incluir_pdf=datos["pdf"],
                incluir_excel=datos["excel"], incluir_xml=datos["xml"])
        except (OSError, ImportError, ValueError) as e:
            messagebox.showerror(TITULO, f"No se pudo preparar el informe:\n{e}")
            return
        finally:
            self.configure(cursor="")
        if paquete.tamano > informe.LIMITE_ADJUNTOS and not messagebox.askyesno(
            TITULO, f"Los adjuntos pesan {paquete.tamano / 1048576:.1f} MB y muchos servidores "
                    "rechazan correos de más de 20 MB.\n\n¿Enviar de todas formas?"):
            return
        try:
            clave = registro.clave_smtp()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(TITULO, str(e))
            return
        self._enviar_en_segundo_plano(ajustes, clave, datos, paquete,
                                      cliente.id, declaracion.periodo)

    def _enviar_en_segundo_plano(self, ajustes, clave: str, datos: dict, paquete,
                                 id_cliente: int, periodo: str) -> None:
        import threading

        from ..core import correo

        self._enviando = True
        self.btn_enviar.configure(state="disabled")
        self.lbl_envio.configure(text="Enviando…", foreground="gray")
        resultado: dict = {}

        def trabajo() -> None:
            try:
                mensaje = correo.construir(
                    ajustes.correo, correo.lista_correos(datos["para"]), datos["asunto"],
                    datos["cuerpo"], paquete.adjuntos, responder_a=ajustes.declarante.correo)
                resultado["rechazados"] = correo.enviar(ajustes.correo, clave, mensaje)
            except correo.ErrorCorreo as e:
                resultado["error"] = str(e)
            except OSError as e:
                resultado["error"] = f"No se pudo leer un adjunto: {e}"

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()

        def esperar() -> None:
            if hilo.is_alive():
                self.after(200, esperar)
                return
            self._enviando = False
            self.btn_enviar.configure(state="normal")
            if "error" in resultado:
                self.lbl_envio.configure(text="No se envió.", foreground="#c0392b")
                messagebox.showerror(TITULO, resultado["error"])
                return
            destinatarios = correo.lista_correos(datos["para"])
            rechazados = resultado.get("rechazados") or []
            self._registrar_envio(paquete, len(destinatarios) - len(rechazados))
            self._seguimiento_envio(id_cliente, periodo, paquete, datos.get("marcar_declarada"))
            self.lbl_envio.configure(text="✓ Enviado.", foreground="#1e8449")
            texto = (f"Declaración enviada a {datos['para']}.\n\n"
                     f"Copia del informe en:\n{paquete.carpeta}")
            if rechazados:
                messagebox.showwarning(TITULO, texto + "\n\nEl servidor rechazó: "
                                       + ", ".join(rechazados))
            else:
                messagebox.showinfo(TITULO, texto)

        esperar()

    def _seguimiento_envio(self, id_cliente: int, periodo: str, paquete,
                           marcar_declarada: bool) -> None:
        from datetime import datetime

        registro = self.contexto.registro
        ahora = datetime.now()
        try:
            relativa = paquete.carpeta.resolve().relative_to(registro.base).as_posix()
        except ValueError:
            relativa = str(paquete.carpeta)
        try:
            registro.registrar_envio(id_cliente, periodo, f"{ahora:%Y-%m-%d %H:%M}", relativa)
            if marcar_declarada:
                registro.marcar(id_cliente, periodo, "declarada", f"{ahora:%Y-%m-%d}")
            self.contexto.seguimiento_cambio()
        except Exception:  # noqa: BLE001 - el correo ya salió; el seguimiento no debe fallar
            pass

    def _registrar_envio(self, paquete, n_destinatarios: int) -> None:
        if self.contexto is not None:
            self.contexto.registrar(
                "correo_enviado", paquete.carpeta,
                f"destinatarios={n_destinatarios} · adjuntos={len(paquete.adjuntos)}")
