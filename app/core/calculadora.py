"""Cálculo de los casilleros de la declaración de IVA."""
from __future__ import annotations

from decimal import Decimal

from .clasificador import Categoria, categoria_de
from .models import (
    TARIFA_IVA,
    CasillerosCompras,
    CasillerosVentas,
    Comprobante,
    Declaracion,
    Resumen,
    redondear,
)


def filtrar_periodo(comprobantes: list[Comprobante], periodo: str) -> list[Comprobante]:
    return [c for c in comprobantes if c.periodo == periodo]


def calcular_compras(
    comprobantes: list[Comprobante],
    periodo: str,
    factor_proporcionalidad: Decimal = Decimal("1.0000"),
) -> CasillerosCompras:
    casilleros = CasillerosCompras(c563=factor_proporcionalidad)
    del_periodo = filtrar_periodo(comprobantes, periodo)

    for comprobante in del_periodo:
        categoria = categoria_de(comprobante)
        base = comprobante.valor_sin_impuestos
        iva = comprobante.iva

        if comprobante.es_nota_credito:
            # Las notas de crédito no suman al bruto: restan del valor neto.
            if categoria is Categoria.GRAVADA_CON_CREDITO:
                casilleros.c510 -= base
                casilleros.c520 -= iva
            elif categoria is Categoria.GRAVADA_SIN_CREDITO:
                casilleros.c512 -= base
                casilleros.c522 -= iva
            elif categoria is Categoria.NEGOCIO_POPULAR:
                casilleros.c518 -= base
            else:
                casilleros.c517 -= base
            continue

        if categoria is Categoria.GRAVADA_CON_CREDITO:
            casilleros.c500 += base
            casilleros.c510 += base
            casilleros.c520 += iva
        elif categoria is Categoria.GRAVADA_SIN_CREDITO:
            casilleros.c502 += base
            casilleros.c512 += base
            casilleros.c522 += iva
        elif categoria is Categoria.NEGOCIO_POPULAR:
            casilleros.c508 += base
            casilleros.c518 += base
        else:
            casilleros.c507 += base
            casilleros.c517 += base

        if comprobante.es_nota_venta:
            casilleros.c117 += 1
        else:
            casilleros.c115 += 1

    casilleros.c509 = casilleros.c500 + casilleros.c502 + casilleros.c507 + casilleros.c508
    casilleros.c519 = casilleros.c510 + casilleros.c512 + casilleros.c517 + casilleros.c518
    casilleros.c529 = casilleros.c520 + casilleros.c522
    casilleros.c564 = redondear(casilleros.c520 * casilleros.c563)
    casilleros.c565 = casilleros.c520 - casilleros.c564
    return casilleros


def calcular_ventas(
    ventas_brutas: Decimal,
    notas_credito_emitidas: Decimal = Decimal("0"),
    impuesto_meses_anteriores: Decimal = Decimal("0"),
    comprobantes_emitidos: int = 0,
    comprobantes_anulados: int = 0,
    tarifa: Decimal = TARIFA_IVA,
) -> CasillerosVentas:
    casilleros = CasillerosVentas()
    casilleros.c401 = ventas_brutas
    casilleros.c411 = ventas_brutas - notas_credito_emitidas
    casilleros.c421 = redondear(casilleros.c411 * tarifa)
    casilleros.c409 = casilleros.c401
    casilleros.c419 = casilleros.c411
    casilleros.c429 = casilleros.c421
    casilleros.c482 = casilleros.c429
    casilleros.c483 = impuesto_meses_anteriores
    casilleros.c484 = casilleros.c482
    casilleros.c499 = casilleros.c483 + casilleros.c484
    casilleros.c111 = comprobantes_emitidos
    casilleros.c113 = comprobantes_anulados
    return casilleros


def calcular_resumen(ventas: CasillerosVentas, compras: CasillerosCompras) -> Resumen:
    diferencia = ventas.c499 - compras.c564
    return Resumen(
        impuesto_generado=ventas.c499,
        credito_tributario=compras.c564,
        impuesto_a_pagar=max(diferencia, Decimal("0")),
        credito_a_favor=max(-diferencia, Decimal("0")),
    )


def calcular_declaracion(
    comprobantes: list[Comprobante],
    periodo: str,
    ventas_brutas: Decimal = Decimal("0"),
    notas_credito_emitidas: Decimal = Decimal("0"),
    impuesto_meses_anteriores: Decimal = Decimal("0"),
    comprobantes_emitidos: int = 0,
    comprobantes_anulados: int = 0,
    advertencias: list[str] | None = None,
) -> Declaracion:
    ventas = calcular_ventas(
        ventas_brutas,
        notas_credito_emitidas,
        impuesto_meses_anteriores,
        comprobantes_emitidos,
        comprobantes_anulados,
    )
    compras = calcular_compras(comprobantes, periodo)
    return Declaracion(
        periodo=periodo,
        ventas=ventas,
        compras=compras,
        resumen=calcular_resumen(ventas, compras),
        comprobantes=filtrar_periodo(comprobantes, periodo),
        advertencias=list(advertencias or []),
    )


DESCRIPCIONES = {
    "401": "Ventas locales gravadas tarifa ≠0% — valor bruto",
    "411": "Ventas locales gravadas tarifa ≠0% — valor neto",
    "421": "Impuesto generado en ventas",
    "409": "Total ventas — valor bruto",
    "419": "Total ventas — valor neto",
    "429": "Total impuesto generado",
    "482": "Total impuesto generado (traslado campo 429)",
    "483": "Impuesto a liquidar de meses anteriores",
    "484": "Impuesto a liquidar en este mes",
    "499": "Total impuesto a liquidar este mes (483+484)",
    "111": "Total comprobantes de venta emitidos",
    "113": "Total comprobantes de venta anulados",
    "500": "Adquisiciones gravadas ≠0% con derecho a crédito — bruto",
    "510": "Adquisiciones gravadas ≠0% con derecho a crédito — neto",
    "520": "Adquisiciones gravadas ≠0% con derecho a crédito — impuesto",
    "502": "Otras adquisiciones gravadas ≠0% sin derecho a crédito — bruto",
    "512": "Otras adquisiciones gravadas ≠0% sin derecho a crédito — neto",
    "522": "Otras adquisiciones gravadas ≠0% sin derecho a crédito — impuesto",
    "507": "Adquisiciones gravadas tarifa 0% — bruto",
    "517": "Adquisiciones gravadas tarifa 0% — neto",
    "508": "Adquisiciones a negocios populares — bruto",
    "518": "Adquisiciones a negocios populares — neto",
    "509": "TOTAL adquisiciones y pagos — bruto",
    "519": "TOTAL adquisiciones y pagos — neto",
    "529": "TOTAL impuesto en adquisiciones",
    "563": "Factor de proporcionalidad para crédito tributario",
    "564": "Crédito tributario aplicable en este período",
    "565": "IVA no considerado como crédito tributario",
    "115": "Total comprobantes recibidos (excepto notas de venta)",
    "117": "Total notas de venta recibidas",
}


def filas_formulario(declaracion: Declaracion) -> list[tuple[str, str, object]]:
    """Lista (casillero, descripción, valor) en el orden del formulario, para reportes."""
    ventas, compras = declaracion.ventas, declaracion.compras
    valores = {
        "401": ventas.c401, "411": ventas.c411, "421": ventas.c421,
        "409": ventas.c409, "419": ventas.c419, "429": ventas.c429,
        "482": ventas.c482, "483": ventas.c483, "484": ventas.c484,
        "499": ventas.c499, "111": ventas.c111, "113": ventas.c113,
        "500": compras.c500, "510": compras.c510, "520": compras.c520,
        "502": compras.c502, "512": compras.c512, "522": compras.c522,
        "507": compras.c507, "517": compras.c517,
        "508": compras.c508, "518": compras.c518,
        "509": compras.c509, "519": compras.c519, "529": compras.c529,
        "563": compras.c563, "564": compras.c564, "565": compras.c565,
        "115": compras.c115, "117": compras.c117,
    }
    return [(campo, DESCRIPCIONES[campo], valores[campo]) for campo in valores]
