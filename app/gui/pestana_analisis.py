"""Pestaña 2 — Análisis de los XML descargados: totales del lote y exportación."""
from __future__ import annotations

import os
import threading

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import analizador as az
from .contexto import periodo_mayoritario
from .dialogos import tipos_archivo
from .recursos import fmt


class PestanaAnalisis(ttk.Frame):
    # (clave interna, encabezado, ancho, alineación)
    COLUMNAS = [
        ("fecha", "Fecha", 80, "center"),
        ("tipo", "Tipo", 130, "w"),
        ("numero", "Nº", 130, "w"),
        ("emisor", "Emisor", 200, "w"),
        ("base", "Base grav.", 90, "e"),
        ("iva", "IVA", 80, "e"),
        ("base0", "Base 0%", 90, "e"),
        ("total", "Total", 100, "e"),
        ("ret", "Retenido", 90, "e"),
    ]

    def __init__(self, master, on_enviar_declaracion=None, contexto=None) -> None:
        super().__init__(master, padding=10)
        self.contexto = contexto
        self._comprobantes: list[az.Comprobante] = []
        self._items: dict[str, az.Comprobante] = {}  # iid -> comprobante
        self._orden_col: str | None = None
        self._orden_desc = False
        self._on_enviar_declaracion = on_enviar_declaracion
        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}

        # --- Selector de carpeta ---
        frm_top = ttk.Frame(self)
        frm_top.pack(fill="x", **pad)
        ttk.Button(frm_top, text="Seleccionar carpeta...", command=self._elegir_carpeta).pack(side="left")
        self.var_carpeta = tk.StringVar()
        ttk.Entry(frm_top, textvariable=self.var_carpeta, state="readonly").pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.btn_refrescar = ttk.Button(frm_top, text="Refrescar", command=self._cargar, state="disabled")
        self.btn_refrescar.pack(side="left")

        # --- Barra de totales ---
        self.frm_tot = ttk.LabelFrame(self, text="Totales del lote", padding=8)
        self.frm_tot.pack(fill="x", **pad)
        self.lbl_totales = ttk.Label(self.frm_tot, text="Seleccione una carpeta con XMLs.", justify="left")
        self.lbl_totales.pack(anchor="w")

        # --- Panel dividido: tabla | detalle ---
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, **pad)

        # Izquierda: tabla de comprobantes
        frm_tabla = ttk.Frame(paned)
        cols = [c[0] for c in self.COLUMNAS]
        self.tree = ttk.Treeview(frm_tabla, columns=cols, show="headings", selectmode="browse")
        for clave, titulo, ancho, anchor in self.COLUMNAS:
            self.tree.heading(clave, text=titulo, command=lambda c=clave: self._ordenar_por(c))
            self.tree.column(clave, width=ancho, anchor=anchor, stretch=(clave == "emisor"))
        self.tree.tag_configure("error", foreground="#c0392b")
        self.tree.tag_configure("credito", foreground="#8e44ad")
        vs = ttk.Scrollbar(frm_tabla, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_seleccion)
        paned.add(frm_tabla, weight=3)

        # Derecha: detalle del comprobante seleccionado
        frm_det = ttk.LabelFrame(paned, text="Detalle del comprobante", padding=8)
        self.lbl_detalle = ttk.Label(frm_det, text="—", justify="left", anchor="nw")
        self.lbl_detalle.pack(fill="x", anchor="nw")
        ttk.Separator(frm_det, orient="horizontal").pack(fill="x", pady=6)
        ttk.Label(frm_det, text="Líneas de detalle:").pack(anchor="w")
        det_cols = ("desc", "cant", "punit", "total", "iva")
        self.tree_det = ttk.Treeview(frm_det, columns=det_cols, show="headings", height=10)
        for c, t, w, a in [
            ("desc", "Descripción", 180, "w"),
            ("cant", "Cant.", 55, "e"),
            ("punit", "P. Unit.", 70, "e"),
            ("total", "Total", 80, "e"),
            ("iva", "IVA %", 50, "e"),
        ]:
            self.tree_det.heading(c, text=t)
            self.tree_det.column(c, width=w, anchor=a, stretch=(c == "desc"))
        vsd = ttk.Scrollbar(frm_det, orient="vertical", command=self.tree_det.yview)
        self.tree_det.configure(yscrollcommand=vsd.set)
        self.tree_det.pack(side="left", fill="both", expand=True)
        vsd.pack(side="right", fill="y")
        paned.add(frm_det, weight=2)

        # --- Barra inferior: exportación y envío a declaración ---
        frm_bot = ttk.Frame(self)
        frm_bot.pack(fill="x", **pad)
        self.btn_csv = ttk.Button(frm_bot, text="Exportar CSV", command=self._exportar_csv, state="disabled")
        self.btn_csv.pack(side="left")
        self.btn_xlsx = ttk.Button(frm_bot, text="Exportar Excel", command=self._exportar_xlsx, state="disabled")
        self.btn_xlsx.pack(side="left", padx=8)
        if not az.openpyxl_disponible():
            self.btn_xlsx.configure(text="Exportar Excel (instale openpyxl)")
        self.btn_declarar = ttk.Button(
            frm_bot, text="Enviar a Declaración ▸", command=self._enviar_declaracion, state="disabled"
        )
        self.btn_declarar.pack(side="left", padx=8)
        self.var_estado = tk.StringVar(value="")
        ttk.Label(frm_bot, textvariable=self.var_estado).pack(side="right")

    # -- acciones --
    def _elegir_carpeta(self) -> None:
        inicial = self.contexto.carpeta_descargas() if self.contexto else None
        carpeta = filedialog.askdirectory(
            title="Carpeta con los XML a analizar",
            initialdir=str(inicial) if inicial else None)
        if carpeta:
            self.cargar_carpeta(carpeta)

    def cargar_carpeta(self, carpeta: str) -> None:
        """Carga y analiza una carpeta (uso público: tras la descarga)."""
        self.var_carpeta.set(carpeta)
        self.btn_refrescar.configure(state="normal")
        self._cargar()

    def _cargar(self) -> None:
        carpeta = self.var_carpeta.get()
        if not carpeta or not os.path.isdir(carpeta):
            return
        rutas = az.listar_xmls(carpeta)
        if not rutas:
            messagebox.showinfo("Sin XMLs", "No se encontraron archivos .xml en la carpeta.")
            return
        self.var_estado.set(f"Procesando {len(rutas)} archivo(s)...")
        self.btn_refrescar.configure(state="disabled")
        threading.Thread(target=self._parsear_en_hilo, args=(carpeta,), daemon=True).start()

    def _parsear_en_hilo(self, carpeta: str) -> None:
        comps = az.parsear_carpeta(carpeta)
        self.after(0, lambda: self._mostrar(comps))

    def _mostrar(self, comprobantes: list[az.Comprobante]) -> None:
        self._comprobantes = comprobantes
        self._poblar_tabla()
        self._actualizar_totales()
        habilitar = "normal" if comprobantes else "disabled"
        self.btn_csv.configure(state=habilitar)
        if az.openpyxl_disponible():
            self.btn_xlsx.configure(state=habilitar)
        # Habilitar "Enviar a Declaración" solo si hay comprobantes sin error.
        hay_validos = any(not c.error for c in comprobantes)
        self.btn_declarar.configure(state="normal" if hay_validos else "disabled")
        self.btn_refrescar.configure(state="normal")
        con_error = sum(1 for c in comprobantes if c.error)
        msg = f"{len(comprobantes)} comprobante(s)"
        if con_error:
            msg += f" — {con_error} con error"
        self.var_estado.set(msg)
        # Foco a la tabla y primera fila seleccionada para navegar con ↑/↓.
        hijos = self.tree.get_children()
        if hijos:
            self.tree.selection_set(hijos[0])
            self.tree.focus(hijos[0])
            self.tree.focus_set()

    def _poblar_tabla(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        for i, c in enumerate(self._comprobantes):
            fecha = c.fecha_emision.strftime("%d/%m/%Y") if c.fecha_emision else ""
            emisor = c.razon_social_emisor or c.ruc_emisor
            if c.error:
                valores = (fecha, "⚠ Error", os.path.basename(c.archivo), c.error, "", "", "", "", "")
                tags = ("error",)
            else:
                valores = (
                    fecha, c.tipo_nombre, c.numero, emisor,
                    fmt(c.base_gravada), fmt(c.iva), fmt(c.base_cero),
                    fmt(c.total_con_signo),
                    fmt(c.valor_retenido) if c.valor_retenido else "",
                )
                tags = ("credito",) if c.signo < 0 else ()
            iid = str(i)
            self.tree.insert("", "end", iid=iid, values=valores, tags=tags)
            self._items[iid] = c

    def _actualizar_totales(self) -> None:
        tot = az.calcular_totales(self._comprobantes)
        partes = [
            f"Comprobantes: {tot.conteo}"
            + (f"  (⚠ {tot.con_error} con error)" if tot.con_error else ""),
            f"Total c/IVA: {fmt(tot.total_con_iva)}",
            f"Base gravada: {fmt(tot.total_sin_iva)}",
            f"IVA: {fmt(tot.iva_total)}",
            f"Base 0%: {fmt(tot.base_iva_0)}",
        ]
        if tot.total_retenido:
            partes.append(f"Retenido: {fmt(tot.total_retenido)}")
        linea1 = "   |   ".join(partes)

        tarifas = []
        for tarifa in sorted(tot.por_tarifa):
            if tarifa <= 0:
                continue
            r = tot.por_tarifa[tarifa]
            tarifas.append(f"{tarifa:g}%: base {fmt(r.base)} / IVA {fmt(r.iva)}")
        linea2 = "IVA por tarifa →   " + "   |   ".join(tarifas) if tarifas else ""
        self.lbl_totales.configure(text=linea1 + (("\n" + linea2) if linea2 else ""))

    def _on_seleccion(self, _evento=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        c = self._items.get(sel[0])
        if c is None:
            return
        self.tree_det.delete(*self.tree_det.get_children())
        if c.error:
            self.lbl_detalle.configure(text=f"Archivo: {os.path.basename(c.archivo)}\n⚠ {c.error}")
            return
        fecha = c.fecha_emision.strftime("%d/%m/%Y") if c.fecha_emision else "—"
        texto = (
            f"Tipo: {c.tipo_nombre}      Nº {c.numero}      Fecha: {fecha}\n"
            f"Emisor: {c.razon_social_emisor} ({c.ruc_emisor})\n"
            f"Receptor: {c.razon_social_receptor} ({c.identificacion_receptor})\n"
            f"Base gravada: {fmt(c.base_gravada)}   IVA: {fmt(c.iva)}   "
            f"Base 0%: {fmt(c.base_cero)}   Total: {fmt(c.total_con_signo)}\n"
            f"Clave de acceso: {c.clave_acceso}"
        )
        if c.valor_retenido:
            texto += f"\nValor retenido: {fmt(c.valor_retenido)}"
        self.lbl_detalle.configure(text=texto)
        for ln in c.detalles:
            self.tree_det.insert(
                "", "end",
                values=(
                    ln.descripcion,
                    f"{ln.cantidad:g}",
                    fmt(ln.precio_unitario),
                    fmt(ln.precio_total_sin_impuesto),
                    f"{ln.tarifa_iva:g}",
                ),
            )

    def _ordenar_por(self, columna: str) -> None:
        if not self._comprobantes:
            return
        self._orden_desc = not self._orden_desc if self._orden_col == columna else False
        self._orden_col = columna

        def clave(c: az.Comprobante):
            if c.error:
                return (1, "")  # errores al final
            mapa = {
                "fecha": c.fecha_emision or "",
                "tipo": c.tipo_nombre,
                "numero": c.numero,
                "emisor": c.razon_social_emisor or c.ruc_emisor,
                "base": c.base_gravada,
                "iva": c.iva,
                "base0": c.base_cero,
                "total": c.total_con_signo,
                "ret": c.valor_retenido,
            }
            return (0, mapa.get(columna, ""))

        self._comprobantes.sort(key=clave, reverse=self._orden_desc)
        self._poblar_tabla()
        hijos = self.tree.get_children()
        if hijos:
            self.tree.selection_set(hijos[0])
            self.tree.focus(hijos[0])

    # -- exportación --
    def _nombre_sugerido(self, ext: str) -> str:
        base = os.path.basename(self.var_carpeta.get().rstrip("/\\")) or "analisis"
        return f"analisis_{base}.{ext}"

    def _carpeta_resultados(self):
        """``resultados/<AAAA-MM>`` del cliente activo (período más frecuente del lote)."""
        if self.contexto is None or self.contexto.cliente is None:
            return None
        periodo = periodo_mayoritario(c.fecha_emision for c in self._comprobantes)
        return self.contexto.carpeta_resultados(periodo)

    def _dialogo_guardar(self, titulo: str, ext: str, tipo: str) -> str:
        carpeta = self._carpeta_resultados()
        return filedialog.asksaveasfilename(
            title=titulo, defaultextension=f".{ext}",
            initialfile=self._nombre_sugerido(ext),
            initialdir=str(carpeta) if carpeta else None,
            filetypes=tipos_archivo((tipo, f"*.{ext}")),
        )

    def _registrar(self, ruta: str) -> None:
        if self.contexto is not None:
            self.contexto.registrar("exportacion", ruta, "análisis")

    def _exportar_csv(self) -> None:
        ruta = self._dialogo_guardar("Guardar CSV", "csv", "CSV")
        if not ruta:
            return
        try:
            tot = az.calcular_totales(self._comprobantes)
            az.exportar_csv(self._comprobantes, tot, ruta)
            self._registrar(ruta)
            messagebox.showinfo("Exportado", f"CSV guardado en:\n{ruta}")
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error al exportar", str(e))

    def _exportar_xlsx(self) -> None:
        ruta = self._dialogo_guardar("Guardar Excel", "xlsx", "Excel")
        if not ruta:
            return
        try:
            tot = az.calcular_totales(self._comprobantes)
            az.exportar_xlsx(self._comprobantes, tot, ruta)
            self._registrar(ruta)
            messagebox.showinfo("Exportado", f"Excel guardado en:\n{ruta}")
        except ImportError:
            messagebox.showerror(
                "Falta openpyxl",
                "Para exportar a Excel instale la dependencia:\n\npip install openpyxl",
            )
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Error al exportar", str(e))

    # -- envío a la pestaña de declaración --
    def _enviar_declaracion(self) -> None:
        validos = [c for c in self._comprobantes if not c.error]
        if not validos:
            messagebox.showinfo("Sin datos", "No hay comprobantes válidos para declarar.")
            return
        if self._on_enviar_declaracion is not None:
            self._on_enviar_declaracion(validos)
