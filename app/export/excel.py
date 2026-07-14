"""Exportación de la declaración a Excel (openpyxl)."""
from __future__ import annotations

from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..core import calculadora
from ..core.clasificador import categoria_de
from ..core.models import Declaracion

ENCABEZADO = Font(bold=True, color="FFFFFF")
FONDO_ENCABEZADO = PatternFill("solid", fgColor="1F4E79")
FONDO_TOTAL = PatternFill("solid", fgColor="FFE699")


def _numero(valor: object) -> object:
    return float(valor) if isinstance(valor, Decimal) else valor


def exportar_excel(declaracion: Declaracion, ruta: str) -> None:
    libro = Workbook()

    hoja = libro.active
    hoja.title = "Formulario"
    hoja.append([f"Declaración de IVA — período {declaracion.periodo}"])
    hoja["A1"].font = Font(bold=True, size=14)
    hoja.append([])
    hoja.append(["Casillero", "Descripción", "Valor"])
    for celda in hoja[3]:
        celda.font = ENCABEZADO
        celda.fill = FONDO_ENCABEZADO
    for campo, descripcion, valor in calculadora.filas_formulario(declaracion):
        hoja.append([campo, descripcion, _numero(valor)])
        if campo in ("409", "419", "429", "499", "509", "519", "529", "564"):
            for celda in hoja[hoja.max_row]:
                celda.fill = FONDO_TOTAL
                celda.font = Font(bold=True)

    hoja.append([])
    resumen = declaracion.resumen
    hoja.append(["", "Impuesto generado en ventas (499)", _numero(resumen.impuesto_generado)])
    hoja.append(["", "Crédito tributario en compras (564)", _numero(resumen.credito_tributario)])
    if resumen.impuesto_a_pagar > 0:
        hoja.append(["", "IMPUESTO A PAGAR", _numero(resumen.impuesto_a_pagar)])
    else:
        hoja.append(["", "CRÉDITO A FAVOR (próximo período)", _numero(resumen.credito_a_favor)])
    hoja[hoja.max_row][1].font = Font(bold=True)
    hoja.append([])
    hoja.append(["", "Valores de apoyo; verifíquelos contra el prellenado de SRI en línea."])

    hoja.column_dimensions["A"].width = 10
    hoja.column_dimensions["B"].width = 68
    hoja.column_dimensions["C"].width = 14
    for fila in hoja.iter_rows(min_row=4, min_col=3, max_col=3):
        for celda in fila:
            celda.number_format = "#,##0.00"
            celda.alignment = Alignment(horizontal="right")

    detalle = libro.create_sheet("Comprobantes")
    detalle.append(["Fecha", "Tipo", "Serie", "Emisor (RUC)", "Razón social",
                    "Receptor", "Base", "IVA", "Total", "Clasificación"])
    for celda in detalle[1]:
        celda.font = ENCABEZADO
        celda.fill = FONDO_ENCABEZADO
    for c in declaracion.comprobantes:
        detalle.append([
            c.fecha_emision.strftime("%d/%m/%Y"), c.tipo_comprobante, c.serie_comprobante,
            c.ruc_emisor, c.razon_social_emisor, c.identificacion_receptor,
            _numero(c.valor_sin_impuestos), _numero(c.iva), _numero(c.importe_total),
            categoria_de(c).value,
        ])
    anchos = {"A": 11, "B": 12, "C": 20, "D": 15, "E": 42, "F": 15, "G": 10, "H": 10, "I": 10, "J": 46}
    for columna, ancho in anchos.items():
        detalle.column_dimensions[columna].width = ancho
    for fila in detalle.iter_rows(min_row=2, min_col=7, max_col=9):
        for celda in fila:
            celda.number_format = "#,##0.00"

    if declaracion.advertencias:
        hoja_avisos = libro.create_sheet("Advertencias")
        hoja_avisos.append(["Advertencias detectadas al procesar el archivo"])
        hoja_avisos["A1"].font = Font(bold=True)
        for advertencia in declaracion.advertencias:
            hoja_avisos.append([advertencia])
        hoja_avisos.column_dimensions["A"].width = 120

    libro.save(ruta)
