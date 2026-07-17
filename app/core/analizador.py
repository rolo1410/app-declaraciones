"""
Análisis de comprobantes electrónicos XML del SRI (Ecuador).

Lógica pura y sin dependencias de interfaz gráfica: parsea los XML descargados,
extrae cabecera, impuestos y líneas de detalle, y calcula los totales del lote.
Diseñado para probarse con pytest sobre archivos reales.

El XML del SRI es un `<autorizacion>` que envuelve el comprobante real dentro de
`<comprobante><![CDATA[ ... ]]></comprobante>`. Hay que desanidar ese CDATA y
luego parsear según el tipo de documento (codDoc):

    01 factura · 03 liquidación de compra · 04 nota de crédito
    05 nota de débito · 06/07 comprobante de retención
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime

# --- Catálogos del SRI --------------------------------------------------------

# codDoc -> nombre legible del tipo de comprobante.
TIPOS_DOC = {
    "01": "Factura",
    "03": "Liquidación de compra",
    "04": "Nota de Crédito",
    "05": "Nota de Débito",
    "06": "Comprobante de Retención",  # variante antigua
    "07": "Comprobante de Retención",
}

# Documentos que restan en los totales del lote (devoluciones).
COD_DOC_NEGATIVOS = {"04"}

# codigoPorcentaje del IVA -> tarifa (%). Los códigos 6/7 (no objeto/exento) y 0
# se agrupan como 0 %.
TARIFA_POR_CODIGO = {
    "0": 0.0,
    "1": 0.0,
    "2": 12.0,
    "3": 14.0,
    "4": 15.0,
    "5": 5.0,
    "6": 0.0,
    "7": 0.0,
    "8": 8.0,
    "10": 13.0,
}

# codigo de impuesto: 2 = IVA (el único que aporta a los totales de IVA).
COD_IMPUESTO_IVA = "2"


# --- Modelo de datos ----------------------------------------------------------


@dataclass
class ImpuestoResumen:
    codigo: str  # "2" = IVA
    codigo_porcentaje: str  # "0","2","4"...
    tarifa: float  # 0, 12, 15...
    base_imponible: float
    valor: float  # monto del impuesto (IVA)


@dataclass
class LineaDetalle:
    descripcion: str
    cantidad: float
    precio_unitario: float
    descuento: float
    precio_total_sin_impuesto: float
    tarifa_iva: float


@dataclass
class Comprobante:
    archivo: str
    cod_doc: str = ""
    tipo_nombre: str = "Desconocido"
    clave_acceso: str = ""
    fecha_emision: date | None = None
    numero: str = ""  # "estab-ptoEmi-secuencial"
    ruc_emisor: str = ""
    razon_social_emisor: str = ""
    identificacion_receptor: str = ""
    razon_social_receptor: str = ""
    total_sin_impuestos: float = 0.0
    total_descuento: float = 0.0
    importe_total: float = 0.0  # con IVA
    signo: int = 1  # +1 normal, -1 nota de crédito
    impuestos: list[ImpuestoResumen] = field(default_factory=list)
    valor_retenido: float = 0.0  # solo retenciones
    detalles: list[LineaDetalle] = field(default_factory=list)
    error: str | None = None

    # --- métricas derivadas (con signo aplicado) ---

    @property
    def iva(self) -> float:
        """IVA total del comprobante (solo impuesto codigo 2, tarifa > 0)."""
        return round(
            sum(i.valor for i in self.impuestos if i.codigo == COD_IMPUESTO_IVA and i.tarifa > 0)
            * self.signo,
            2,
        )

    @property
    def base_gravada(self) -> float:
        """Base imponible con tarifa de IVA > 0."""
        return round(
            sum(i.base_imponible for i in self.impuestos if i.codigo == COD_IMPUESTO_IVA and i.tarifa > 0)
            * self.signo,
            2,
        )

    @property
    def base_cero(self) -> float:
        """Base imponible con tarifa de IVA 0 % (incluye no objeto/exento)."""
        return round(
            sum(i.base_imponible for i in self.impuestos if i.codigo == COD_IMPUESTO_IVA and i.tarifa == 0)
            * self.signo,
            2,
        )

    @property
    def total_con_signo(self) -> float:
        return round(self.importe_total * self.signo, 2)


@dataclass
class TarifaResumen:
    tarifa: float
    base: float
    iva: float
    conteo: int


@dataclass
class TotalesLote:
    conteo: int = 0
    con_error: int = 0
    total_con_iva: float = 0.0
    total_sin_iva: float = 0.0  # suma de bases gravadas (tarifa > 0)
    iva_total: float = 0.0
    base_iva_0: float = 0.0
    total_retenido: float = 0.0
    por_tarifa: dict[float, TarifaResumen] = field(default_factory=dict)


# --- Utilidades de parseo -----------------------------------------------------


def _a_float(texto: str | None) -> float:
    """Convierte un texto monetario a float, tolerando coma o punto decimal."""
    if not texto:
        return 0.0
    t = texto.strip().replace(" ", "")
    if not t:
        return 0.0
    # Si tiene coma y punto, la coma suele ser separador de miles.
    if "," in t and "." in t:
        t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return 0.0


def _texto(nodo: ET.Element | None, ruta: str, defecto: str = "") -> str:
    """findtext relativo tolerante (devuelve defecto si no existe)."""
    if nodo is None:
        return defecto
    hallado = nodo.findtext(ruta)
    return hallado.strip() if hallado else defecto


def _parsear_fecha(texto: str) -> date | None:
    """Fecha de emisión del SRI: 'dd/mm/yyyy' (a veces con hora)."""
    if not texto:
        return None
    txt = texto.strip().split(" ")[0].split("T")[0]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            continue
    return None


def _tarifa_impuesto(imp: ET.Element) -> float:
    """Determina la tarifa (%) de un nodo de impuesto."""
    tarifa_txt = imp.findtext("tarifa")
    if tarifa_txt and tarifa_txt.strip():
        return _a_float(tarifa_txt)
    cod = (imp.findtext("codigoPorcentaje") or "").strip()
    return TARIFA_POR_CODIGO.get(cod, 0.0)


def desanidar_comprobante(xml_texto: str) -> str:
    """
    Devuelve el XML interno del comprobante. Si viene envuelto en
    `<autorizacion><comprobante><![CDATA[...]]>`, extrae el CDATA; si no, asume
    que ya es el comprobante y lo devuelve tal cual.
    """
    try:
        raiz = ET.fromstring(xml_texto)
    except ET.ParseError:
        return xml_texto
    # Buscar el nodo <comprobante> (directo o anidado).
    comp = raiz.find(".//comprobante")
    if comp is not None and comp.text and comp.text.strip().startswith("<"):
        return comp.text
    if raiz.tag == "comprobante" and raiz.text:
        return raiz.text
    # Ya es el comprobante en sí (factura, notaCredito, etc.).
    return xml_texto


# Nodos de información de cabecera según el tipo de comprobante.
_NODOS_INFO = (
    "infoFactura",
    "infoNotaCredito",
    "infoNotaDebito",
    "infoLiquidacionCompra",
    "infoCompRetencion",
)


def _extraer_impuestos(info: ET.Element | None, raiz: ET.Element) -> list[ImpuestoResumen]:
    """
    Extrae los impuestos de cabecera (totalImpuesto en factura/NC/liquidación,
    o impuesto en nota de débito). Solo el nivel de cabecera para no duplicar con
    los impuestos por línea de detalle.
    """
    if info is None:
        return []
    nodos: list[ET.Element] = list(info.findall("totalConImpuestos/totalImpuesto"))
    if not nodos:
        nodos = list(info.findall("impuestos/impuesto"))
    impuestos: list[ImpuestoResumen] = []
    for imp in nodos:
        impuestos.append(
            ImpuestoResumen(
                codigo=(imp.findtext("codigo") or "").strip(),
                codigo_porcentaje=(imp.findtext("codigoPorcentaje") or "").strip(),
                tarifa=_tarifa_impuesto(imp),
                base_imponible=_a_float(imp.findtext("baseImponible")),
                valor=_a_float(imp.findtext("valor")),
            )
        )
    return impuestos


def _extraer_detalles(raiz: ET.Element) -> list[LineaDetalle]:
    """Líneas de detalle (detalle) o, para nota de débito, motivos (motivo)."""
    lineas: list[LineaDetalle] = []
    for det in raiz.findall(".//detalles/detalle"):
        tarifa = 0.0
        imp = det.find(".//impuesto")
        if imp is not None:
            tarifa = _tarifa_impuesto(imp)
        lineas.append(
            LineaDetalle(
                descripcion=_texto(det, "descripcion") or _texto(det, "codigoPrincipal"),
                cantidad=_a_float(det.findtext("cantidad")),
                precio_unitario=_a_float(det.findtext("precioUnitario")),
                descuento=_a_float(det.findtext("descuento")),
                precio_total_sin_impuesto=_a_float(det.findtext("precioTotalSinImpuesto")),
                tarifa_iva=tarifa,
            )
        )
    if lineas:
        return lineas
    # Nota de débito: usa <motivos><motivo>.
    for mot in raiz.findall(".//motivos/motivo"):
        lineas.append(
            LineaDetalle(
                descripcion=_texto(mot, "razon"),
                cantidad=1.0,
                precio_unitario=_a_float(mot.findtext("valor")),
                descuento=0.0,
                precio_total_sin_impuesto=_a_float(mot.findtext("valor")),
                tarifa_iva=0.0,
            )
        )
    return lineas


def _extraer_valor_retenido(raiz: ET.Element) -> float:
    """Suma todos los valorRetenido de un comprobante de retención."""
    total = 0.0
    for v in raiz.iter("valorRetenido"):
        total += _a_float(v.text)
    return round(total, 2)


def parsear_comprobante(ruta: str) -> Comprobante:
    """
    Parsea un XML de comprobante. Tolera errores: si algo falla, devuelve un
    Comprobante con el campo `error` poblado (nunca lanza excepción).
    """
    comp = Comprobante(archivo=ruta)
    try:
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            contenido = f.read()
    except OSError as e:
        comp.error = f"No se pudo leer el archivo: {e}"
        return comp

    try:
        interno = desanidar_comprobante(contenido)
        raiz = ET.fromstring(interno)
    except ET.ParseError as e:
        comp.error = f"XML inválido: {e}"
        return comp

    try:
        info_trib = raiz.find(".//infoTributaria")
        comp.cod_doc = _texto(info_trib, "codDoc")
        comp.tipo_nombre = TIPOS_DOC.get(comp.cod_doc, raiz.tag or "Desconocido")
        comp.clave_acceso = _texto(info_trib, "claveAcceso")
        comp.ruc_emisor = _texto(info_trib, "ruc")
        comp.razon_social_emisor = _texto(info_trib, "razonSocial")
        estab = _texto(info_trib, "estab")
        pto = _texto(info_trib, "ptoEmi")
        sec = _texto(info_trib, "secuencial")
        comp.numero = "-".join(p for p in (estab, pto, sec) if p)

        # Nodo de información de cabecera (varía por tipo).
        info = None
        for nombre in _NODOS_INFO:
            info = raiz.find(f".//{nombre}")
            if info is not None:
                break

        comp.fecha_emision = _parsear_fecha(_texto(info, "fechaEmision") or _texto(raiz, ".//fechaEmision"))

        # Receptor: la factura usa razonSocialComprador; la retención,
        # razonSocialSujetoRetenido.
        comp.razon_social_receptor = (
            _texto(info, "razonSocialComprador")
            or _texto(info, "razonSocialSujetoRetenido")
            or _texto(raiz, ".//razonSocialComprador")
            or _texto(raiz, ".//razonSocialSujetoRetenido")
        )
        comp.identificacion_receptor = (
            _texto(info, "identificacionComprador")
            or _texto(info, "identificacionSujetoRetenido")
            or _texto(raiz, ".//identificacionComprador")
            or _texto(raiz, ".//identificacionSujetoRetenido")
        )

        comp.total_sin_impuestos = _a_float(_texto(info, "totalSinImpuestos"))
        comp.total_descuento = _a_float(_texto(info, "totalDescuento"))
        # Total con IVA según el tipo de documento.
        comp.importe_total = _a_float(
            _texto(info, "importeTotal")
            or _texto(info, "valorModificacion")  # nota de crédito
            or _texto(info, "valorTotal")  # nota de débito
        )

        comp.signo = -1 if comp.cod_doc in COD_DOC_NEGATIVOS else 1
        comp.impuestos = _extraer_impuestos(info, raiz)
        comp.detalles = _extraer_detalles(raiz)

        if comp.cod_doc in ("06", "07"):
            comp.valor_retenido = _extraer_valor_retenido(raiz)
    except Exception as e:  # noqa: BLE001 - cualquier fallo se reporta como error
        comp.error = f"Error al interpretar el comprobante: {e}"

    return comp


def listar_xmls(carpeta: str) -> list[str]:
    """Rutas de los archivos .xml directamente en `carpeta` (no recursivo)."""
    if not carpeta or not os.path.isdir(carpeta):
        return []
    rutas = [
        os.path.join(carpeta, n)
        for n in os.listdir(carpeta)
        if n.lower().endswith(".xml") and os.path.isfile(os.path.join(carpeta, n))
    ]
    return sorted(rutas)


def parsear_carpeta(carpeta: str) -> list[Comprobante]:
    """Parsea todos los XML de una carpeta (no recursivo)."""
    return [parsear_comprobante(r) for r in listar_xmls(carpeta)]


def calcular_totales(comprobantes: list[Comprobante]) -> TotalesLote:
    """Agrega los totales del lote, con desglose de IVA por tarifa."""
    tot = TotalesLote()
    for c in comprobantes:
        if c.error:
            tot.con_error += 1
            continue
        tot.conteo += 1
        tot.total_con_iva += c.total_con_signo
        tot.total_retenido += c.valor_retenido
        for imp in c.impuestos:
            if imp.codigo != COD_IMPUESTO_IVA:
                continue
            base = imp.base_imponible * c.signo
            valor = imp.valor * c.signo
            if imp.tarifa > 0:
                tot.total_sin_iva += base
                tot.iva_total += valor
            else:
                tot.base_iva_0 += base
            res = tot.por_tarifa.get(imp.tarifa)
            if res is None:
                res = TarifaResumen(tarifa=imp.tarifa, base=0.0, iva=0.0, conteo=0)
                tot.por_tarifa[imp.tarifa] = res
            res.base += base
            res.iva += valor
            res.conteo += 1

    # Redondeo final a 2 decimales.
    tot.total_con_iva = round(tot.total_con_iva, 2)
    tot.total_sin_iva = round(tot.total_sin_iva, 2)
    tot.iva_total = round(tot.iva_total, 2)
    tot.base_iva_0 = round(tot.base_iva_0, 2)
    tot.total_retenido = round(tot.total_retenido, 2)
    for res in tot.por_tarifa.values():
        res.base = round(res.base, 2)
        res.iva = round(res.iva, 2)
    return tot


# --- Exportación --------------------------------------------------------------

# Encabezados de la tabla exportada (orden fijo).
COLUMNAS_EXPORT = [
    ("fecha", "Fecha"),
    ("tipo_nombre", "Tipo"),
    ("numero", "Nº Comprobante"),
    ("ruc_emisor", "RUC Emisor"),
    ("razon_social_emisor", "Razón Social Emisor"),
    ("identificacion_receptor", "Identificación Receptor"),
    ("razon_social_receptor", "Razón Social Receptor"),
    ("base_gravada", "Base Gravada"),
    ("iva", "IVA"),
    ("base_cero", "Base 0%"),
    ("total", "Total"),
    ("valor_retenido", "Valor Retenido"),
    ("clave_acceso", "Clave de Acceso"),
    ("archivo", "Archivo"),
    ("error", "Error"),
]


def _fila_export(c: Comprobante) -> list:
    return [
        c.fecha_emision.strftime("%d/%m/%Y") if c.fecha_emision else "",
        c.tipo_nombre,
        c.numero,
        c.ruc_emisor,
        c.razon_social_emisor,
        c.identificacion_receptor,
        c.razon_social_receptor,
        c.base_gravada,
        c.iva,
        c.base_cero,
        c.total_con_signo,
        c.valor_retenido,
        c.clave_acceso,
        os.path.basename(c.archivo),
        c.error or "",
    ]


def _lineas_totales(totales: TotalesLote) -> list[list]:
    """Filas de resumen que se agregan al final de la exportación."""
    filas: list[list] = [
        [],
        ["RESUMEN DEL LOTE"],
        ["Comprobantes", totales.conteo],
        ["Con error", totales.con_error],
        ["Total con IVA", totales.total_con_iva],
        ["Base gravada (sin IVA)", totales.total_sin_iva],
        ["IVA total", totales.iva_total],
        ["Base 0%", totales.base_iva_0],
        ["Total retenido", totales.total_retenido],
        [],
        ["Desglose por tarifa", "Base", "IVA", "Comprobantes"],
    ]
    for tarifa in sorted(totales.por_tarifa):
        r = totales.por_tarifa[tarifa]
        filas.append([f"{tarifa:g}%", r.base, r.iva, r.conteo])
    return filas


def exportar_csv(comprobantes: list[Comprobante], totales: TotalesLote, ruta: str) -> None:
    """Exporta el lote a CSV (UTF-8 con BOM para que Excel lea bien los acentos)."""
    import csv

    with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([etiqueta for _, etiqueta in COLUMNAS_EXPORT])
        for c in comprobantes:
            w.writerow(_fila_export(c))
        for fila in _lineas_totales(totales):
            w.writerow(fila)


def exportar_xlsx(comprobantes: list[Comprobante], totales: TotalesLote, ruta: str) -> None:
    """
    Exporta a Excel .xlsx (hojas "Detalle" y "Totales"). Requiere openpyxl;
    si no está instalado lanza ImportError para que la GUI ofrezca solo CSV.
    """
    from openpyxl import Workbook  # import diferido (dependencia opcional)
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Detalle"
    ws.append([etiqueta for _, etiqueta in COLUMNAS_EXPORT])
    for celda in ws[1]:
        celda.font = Font(bold=True)
    for c in comprobantes:
        ws.append(_fila_export(c))

    ws2 = wb.create_sheet("Totales")
    for fila in _lineas_totales(totales)[1:]:  # omite la primera fila vacía
        ws2.append(fila)

    wb.save(ruta)


def openpyxl_disponible() -> bool:
    """True si se puede exportar a Excel."""
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False
