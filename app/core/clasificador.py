"""Clasificación de comprobantes para la sección COMPRAS del formulario."""
from __future__ import annotations

from enum import Enum

from .models import Comprobante


class Categoria(Enum):
    GRAVADA_CON_CREDITO = "Gravada ≠0% con derecho a crédito (500/510/520)"
    GRAVADA_SIN_CREDITO = "Gravada ≠0% sin derecho a crédito (502/512/522)"
    TARIFA_CERO = "Tarifa 0% (507/517)"
    NEGOCIO_POPULAR = "Negocio popular / nota de venta (508/518)"


def sugerir_clasificacion(comprobantes: list[Comprobante], ruc_contribuyente: str | None) -> None:
    """Sugerencia inicial: las facturas emitidas al RUC sustentan crédito tributario;
    las emitidas a la cédula se presumen gasto personal (sin crédito). El usuario
    puede reclasificar cada comprobante después."""
    for comprobante in comprobantes:
        if ruc_contribuyente:
            comprobante.con_credito = comprobante.identificacion_receptor == ruc_contribuyente
        else:
            comprobante.con_credito = comprobante.receptor_es_ruc


def marcar_todas_con_credito(comprobantes: list[Comprobante]) -> None:
    for comprobante in comprobantes:
        comprobante.con_credito = True


def categoria_de(comprobante: Comprobante) -> Categoria:
    if comprobante.es_nota_venta:
        return Categoria.NEGOCIO_POPULAR
    if comprobante.iva > 0:
        if comprobante.con_credito:
            return Categoria.GRAVADA_CON_CREDITO
        return Categoria.GRAVADA_SIN_CREDITO
    return Categoria.TARIFA_CERO
