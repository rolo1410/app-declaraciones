"""Exportación de la declaración a PDF (reportlab)."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..core import calculadora
from ..core.models import Declaracion

FILAS_TOTALES = {"409", "419", "429", "499", "509", "519", "529", "564"}


def _texto(campo: str, valor: object) -> str:
    if campo == "563":
        return f"{valor:.4f}"
    if isinstance(valor, Decimal):
        return f"{valor:,.2f}"
    return str(valor)


def _logo(ruta, alto_max: float = 18 * mm, ancho_max: float = 60 * mm):
    """Imagen del logo escalada sin deformar, o None si no se puede leer."""
    try:
        ancho, alto = ImageReader(str(ruta)).getSize()
    except Exception:  # noqa: BLE001 - un logo dañado no impide el informe
        return None
    escala = min(alto_max / alto, ancho_max / ancho)
    imagen = Image(str(ruta), width=ancho * escala, height=alto * escala)
    imagen.hAlign = "LEFT"
    return imagen


def exportar_pdf(declaracion: Declaracion, ruta: str, *, contribuyente: tuple[str, str] | None = None,
                 declarante=None, logo=None) -> None:
    """PDF de la declaración.

    Opcionales para el informe que se envía al cliente: ``contribuyente``
    (nombre, RUC), ``declarante`` (``perfil.Declarante``, va al pie como
    «Preparado por») y ``logo`` (ruta de la imagen del encabezado).
    """
    estilos = getSampleStyleSheet()
    elementos = []
    if logo:
        imagen = _logo(logo)
        if imagen is not None:
            elementos += [imagen, Spacer(1, 4 * mm)]
    elementos += [
        Paragraph(f"Declaración de IVA — período {declaracion.periodo}", estilos["Title"]),
    ]
    if contribuyente:
        nombre, ruc = contribuyente
        elementos.append(Paragraph(
            f"<b>Contribuyente:</b> {escape(nombre)} — RUC {escape(ruc)}", estilos["Normal"]))
    elementos += [
        Paragraph("Pre-cálculo de casilleros a partir del archivo de comprobantes recibidos del SRI.",
                  estilos["Normal"]),
        Spacer(1, 6 * mm),
    ]

    filas = [["Casillero", "Descripción", "Valor"]]
    indices_totales = []
    for indice, (campo, descripcion, valor) in enumerate(
        calculadora.filas_formulario(declaracion), start=1
    ):
        filas.append([campo, descripcion, _texto(campo, valor)])
        if campo in FILAS_TOTALES:
            indices_totales.append(indice)

    tabla = Table(filas, colWidths=[22 * mm, 118 * mm, 30 * mm], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
    ]
    for indice in indices_totales:
        estilo.append(("BACKGROUND", (0, indice), (-1, indice), colors.HexColor("#FFE699")))
        estilo.append(("FONTNAME", (0, indice), (-1, indice), "Helvetica-Bold"))
    tabla.setStyle(TableStyle(estilo))
    elementos.append(tabla)

    resumen = declaracion.resumen
    if resumen.impuesto_a_pagar > 0:
        resultado = f"IMPUESTO A PAGAR: {resumen.impuesto_a_pagar:,.2f}"
    else:
        resultado = f"CRÉDITO A FAVOR (próximo período): {resumen.credito_a_favor:,.2f}"
    elementos += [
        Spacer(1, 6 * mm),
        Paragraph("Resumen impositivo", estilos["Heading2"]),
        Paragraph(f"Impuesto generado en ventas (499): {resumen.impuesto_generado:,.2f}", estilos["Normal"]),
        Paragraph(f"Crédito tributario en compras (564): {resumen.credito_tributario:,.2f}", estilos["Normal"]),
        Paragraph(f"<b>{resultado}</b>", estilos["Normal"]),
        Spacer(1, 4 * mm),
        Paragraph("<i>Valores de apoyo; verifíquelos contra el prellenado de SRI en línea "
                  "antes de enviar la declaración.</i>", estilos["Normal"]),
    ]

    if declaracion.advertencias:
        elementos.append(Spacer(1, 4 * mm))
        elementos.append(Paragraph("Advertencias", estilos["Heading2"]))
        for advertencia in declaracion.advertencias:
            elementos.append(Paragraph(f"• {advertencia}", estilos["Normal"]))

    if declarante is not None and declarante.lineas_firma():
        lineas = declarante.lineas_firma()
        elementos += [
            Spacer(1, 10 * mm),
            Paragraph("Preparado por", estilos["Heading2"]),
            Paragraph(f"<b>{escape(lineas[0])}</b>", estilos["Normal"]),
            *(Paragraph(escape(linea), estilos["Normal"]) for linea in lineas[1:]),
            Paragraph(f"Fecha del informe: {date.today():%d/%m/%Y}", estilos["Normal"]),
        ]

    autor = declarante.nombre if declarante is not None else ""
    SimpleDocTemplate(ruta, pagesize=A4, title=f"Declaración IVA {declaracion.periodo}",
                      author=autor).build(elementos)
