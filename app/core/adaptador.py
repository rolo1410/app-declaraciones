"""Puente entre el análisis de XML (``analizador``) y el modelo de la declaración.

La pestaña de Análisis parsea los comprobantes electrónicos (XML) y produce
``analizador.Comprobante`` (basado en ``float``, con base gravada y base 0 %
separadas y el signo ya aplicado en sus propiedades). La calculadora de la
declaración trabaja con ``models.Comprobante`` (basado en ``Decimal``, una base
gravada + un IVA + la base 0 % por comprobante, y el signo lo aplica ella misma
al detectar notas de crédito).

Este módulo convierte de lo primero a lo segundo, cuidando dos detalles:

* **Signo**: las propiedades del analizador (``iva``, ``base_gravada``,
  ``base_cero``) ya multiplican por ``signo`` (−1 en notas de crédito). Aquí se
  deshace ese signo para entregar magnitudes positivas, porque la calculadora
  resta las notas de crédito por su cuenta.
* **Tarifas mixtas**: un mismo XML puede tener líneas al 15 % y al 0 %. La base
  gravada va a ``valor_sin_impuestos`` y la 0 % a ``base_tarifa_cero``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from . import analizador as az
from .models import Comprobante, redondear

# Tipos de comprobante que sustentan adquisiciones en la declaración de IVA.
# Se excluyen los comprobantes de retención (06/07): no son compras, son
# constancias de retención practicada.
COD_DOC_COMPRAS = {"01", "03", "04", "05"}


def _a_decimal(valor: float) -> Decimal:
    """float -> Decimal a 2 decimales, sin arrastrar artefactos binarios."""
    return redondear(Decimal(str(valor)))


@dataclass
class ResultadoAdaptacion:
    comprobantes: list[Comprobante] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    ignorados: int = 0  # retenciones u otros no considerados compras

    @property
    def periodos(self) -> list[str]:
        return sorted({c.periodo for c in self.comprobantes})


def adaptar_comprobante(comp: az.Comprobante) -> Comprobante | None:
    """Convierte un ``analizador.Comprobante`` en un ``models.Comprobante``.

    Devuelve ``None`` si el comprobante no aplica a la declaración de compras
    (retención, con error, o sin fecha de emisión para asignar período).
    """
    if comp.error or comp.fecha_emision is None:
        return None
    if comp.cod_doc and comp.cod_doc not in COD_DOC_COMPRAS:
        return None

    signo = comp.signo or 1
    # Deshacer el signo que aplican las propiedades del analizador.
    base_gravada = comp.base_gravada * signo
    iva = comp.iva * signo
    base_cero = comp.base_cero * signo

    return Comprobante(
        ruc_emisor=comp.ruc_emisor,
        razon_social_emisor=comp.razon_social_emisor or comp.ruc_emisor,
        tipo_comprobante=comp.tipo_nombre,
        serie_comprobante=comp.numero,
        clave_acceso=comp.clave_acceso,
        fecha_autorizacion="",
        fecha_emision=comp.fecha_emision,
        identificacion_receptor=comp.identificacion_receptor,
        valor_sin_impuestos=_a_decimal(base_gravada),
        iva=_a_decimal(iva),
        importe_total=_a_decimal(comp.importe_total),
        base_tarifa_cero=_a_decimal(base_cero),
    )


def adaptar_comprobantes(comprobantes: list[az.Comprobante]) -> ResultadoAdaptacion:
    """Adapta una lista de comprobantes XML, deduplicando por clave de acceso."""
    resultado = ResultadoAdaptacion()
    claves_vistas: set[str] = set()

    for comp in comprobantes:
        if comp.error:
            resultado.advertencias.append(
                f"{comp.archivo}: XML con error, se ignora ({comp.error})."
            )
            continue

        adaptado = adaptar_comprobante(comp)
        if adaptado is None:
            resultado.ignorados += 1
            continue

        clave = adaptado.clave_acceso
        if clave and clave in claves_vistas:
            resultado.advertencias.append(
                f"Comprobante duplicado (clave {clave}); se ignora."
            )
            continue
        if clave:
            claves_vistas.add(clave)

        resultado.comprobantes.append(adaptado)

    return resultado
