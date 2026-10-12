"""Modelos de datos de la declaración de IVA (SRI Ecuador, impuesto 2011)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

DOS_DECIMALES = Decimal("0.01")
TARIFA_IVA = Decimal("0.15")


def redondear(valor: Decimal) -> Decimal:
    """Redondeo monetario a 2 decimales (ROUND_HALF_UP)."""
    return valor.quantize(DOS_DECIMALES, rounding=ROUND_HALF_UP)


@dataclass
class LineaDetalle:
    """Una línea (producto/servicio) de la factura; solo disponible desde XML."""

    descripcion: str
    cantidad: Decimal
    precio_unitario: Decimal
    precio_total: Decimal  # sin impuestos
    tarifa_iva: Decimal  # porcentaje: 0, 15...


@dataclass
class Comprobante:
    """Una fila del archivo de comprobantes recibidos del SRI."""

    ruc_emisor: str
    razon_social_emisor: str
    tipo_comprobante: str
    serie_comprobante: str
    clave_acceso: str
    fecha_autorizacion: str
    fecha_emision: date
    identificacion_receptor: str
    valor_sin_impuestos: Decimal
    iva: Decimal
    importe_total: Decimal
    numero_documento_modificado: str = ""
    con_credito: bool = True
    # Base con tarifa 0 % del propio comprobante. En el archivo TXT no viene
    # desglosada (queda en 0), pero los XML sí separan la parte gravada de la
    # parte 0 % dentro de un mismo comprobante (tarifas mixtas).
    base_tarifa_cero: Decimal = Decimal("0")
    advertencias: list[str] = field(default_factory=list)
    # Solo los XML traen el nombre del receptor y las líneas de la factura.
    razon_social_receptor: str = ""
    detalles: list[LineaDetalle] = field(default_factory=list)

    @property
    def periodo(self) -> str:
        """Período fiscal en formato AAAA-MM, según la fecha de emisión."""
        return f"{self.fecha_emision.year:04d}-{self.fecha_emision.month:02d}"

    @property
    def es_nota_credito(self) -> bool:
        tipo = self.tipo_comprobante.lower()
        return "nota" in tipo and ("créd" in tipo or "cred" in tipo)

    @property
    def es_nota_venta(self) -> bool:
        return "nota de venta" in self.tipo_comprobante.lower()

    @property
    def receptor_es_ruc(self) -> bool:
        """True si la factura fue emitida al RUC (13 dígitos) y no a la cédula."""
        return len(self.identificacion_receptor.strip()) == 13


@dataclass
class CasillerosCompras:
    """Sección COMPRAS del formulario de IVA."""

    c500: Decimal = Decimal("0")  # Gravadas ≠0% con crédito — bruto
    c510: Decimal = Decimal("0")  # Gravadas ≠0% con crédito — neto
    c520: Decimal = Decimal("0")  # Gravadas ≠0% con crédito — impuesto
    c502: Decimal = Decimal("0")  # Gravadas ≠0% sin crédito — bruto
    c512: Decimal = Decimal("0")  # Gravadas ≠0% sin crédito — neto
    c522: Decimal = Decimal("0")  # Gravadas ≠0% sin crédito — impuesto
    c507: Decimal = Decimal("0")  # Tarifa 0% — bruto
    c517: Decimal = Decimal("0")  # Tarifa 0% — neto
    c508: Decimal = Decimal("0")  # Negocios populares (notas de venta) — bruto
    c518: Decimal = Decimal("0")  # Negocios populares — neto
    c509: Decimal = Decimal("0")  # Total adquisiciones — bruto
    c519: Decimal = Decimal("0")  # Total adquisiciones — neto
    c529: Decimal = Decimal("0")  # Total impuesto en adquisiciones
    c563: Decimal = Decimal("1.0000")  # Factor de proporcionalidad
    c564: Decimal = Decimal("0")  # Crédito tributario aplicable
    c565: Decimal = Decimal("0")  # IVA no considerado como crédito
    c115: int = 0  # Comprobantes recibidos (excepto notas de venta)
    c117: int = 0  # Notas de venta recibidas


@dataclass
class CasillerosVentas:
    """Sección VENTAS del formulario de IVA (valores base ingresados manualmente)."""

    c401: Decimal = Decimal("0")  # Ventas gravadas ≠0% — bruto
    c411: Decimal = Decimal("0")  # Ventas gravadas ≠0% — neto (bruto - N/C)
    c421: Decimal = Decimal("0")  # Impuesto generado
    c403: Decimal = Decimal("0")  # Ventas 0% sin derecho a crédito — bruto
    c413: Decimal = Decimal("0")  # Ventas 0% sin derecho a crédito — neto
    c405: Decimal = Decimal("0")  # Ventas 0% con derecho a crédito — bruto
    c415: Decimal = Decimal("0")  # Ventas 0% con derecho a crédito — neto
    c409: Decimal = Decimal("0")  # Total ventas — bruto
    c419: Decimal = Decimal("0")  # Total ventas — neto
    c429: Decimal = Decimal("0")  # Total impuesto generado
    c482: Decimal = Decimal("0")  # Total impuesto generado (traslado del 429)
    c483: Decimal = Decimal("0")  # Impuesto a liquidar de meses anteriores
    c484: Decimal = Decimal("0")  # Impuesto a liquidar en este mes
    c499: Decimal = Decimal("0")  # Total impuesto a liquidar (483 + 484)
    c111: int = 0  # Comprobantes de venta emitidos
    c113: int = 0  # Comprobantes de venta anulados


@dataclass
class Resumen:
    """Resumen impositivo del período."""

    impuesto_generado: Decimal  # campo 499
    credito_tributario: Decimal  # campo 564
    impuesto_a_pagar: Decimal  # si 499 > 564
    credito_a_favor: Decimal  # si 564 > 499 (se arrastra al siguiente mes)


@dataclass
class Declaracion:
    periodo: str
    ventas: CasillerosVentas
    compras: CasillerosCompras
    resumen: Resumen
    comprobantes: list[Comprobante] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
