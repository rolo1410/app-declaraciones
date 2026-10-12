"""Guardar y retomar el trabajo de la pestaña «Declaración».

Se guarda en un archivo JSON: los comprobantes (con su clasificación de
crédito tributario), los valores de ventas ingresados a mano, el período
seleccionado, el RUC y las advertencias. Los importes se escriben como texto
para no perder precisión decimal.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Comprobante, LineaDetalle

VERSION = 1
EXTENSION = ".iva.json"

_CAMPOS_DECIMALES = {"valor_sin_impuestos", "iva", "importe_total", "base_tarifa_cero"}
_CAMPOS_DECIMALES_LINEA = {"cantidad", "precio_unitario", "precio_total", "tarifa_iva"}


@dataclass
class Sesion:
    comprobantes: list[Comprobante]
    periodo: str = ""
    ruc: str | None = None
    origen: str = ""
    advertencias: list[str] = field(default_factory=list)
    ventas: dict[str, str] = field(default_factory=dict)  # clave de entrada -> texto


def _comprobante_a_dict(c: Comprobante) -> dict:
    datos = {}
    for f in fields(c):
        valor = getattr(c, f.name)
        if isinstance(valor, Decimal):
            valor = str(valor)
        elif isinstance(valor, date):
            valor = valor.isoformat()
        elif f.name == "detalles":
            valor = [{k: str(v) if isinstance(v, Decimal) else v
                      for k, v in vars(ln).items()} for ln in valor]
        elif isinstance(valor, list):
            valor = list(valor)
        datos[f.name] = valor
    return datos


def _comprobante_desde_dict(datos: dict) -> Comprobante:
    conocidos = {f.name for f in fields(Comprobante)}
    valores = {k: v for k, v in datos.items() if k in conocidos}
    for nombre in _CAMPOS_DECIMALES & valores.keys():
        valores[nombre] = Decimal(valores[nombre])
    valores["fecha_emision"] = date.fromisoformat(valores["fecha_emision"])
    valores["detalles"] = [
        LineaDetalle(**{k: Decimal(v) if k in _CAMPOS_DECIMALES_LINEA else v
                        for k, v in ln.items()})
        for ln in valores.get("detalles", [])
    ]
    return Comprobante(**valores)


def guardar(sesion: Sesion, ruta: str | Path) -> None:
    contenido = {
        "version": VERSION,
        "periodo": sesion.periodo,
        "ruc": sesion.ruc,
        "origen": sesion.origen,
        "advertencias": sesion.advertencias,
        "ventas": sesion.ventas,
        "comprobantes": [_comprobante_a_dict(c) for c in sesion.comprobantes],
    }
    Path(ruta).write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")


def cargar(ruta: str | Path) -> Sesion:
    try:
        contenido = json.loads(Path(ruta).read_text(encoding="utf-8"))
        if contenido.get("version") != VERSION:
            raise ValueError(f"versión de archivo no soportada: {contenido.get('version')}")
        return Sesion(
            comprobantes=[_comprobante_desde_dict(d) for d in contenido["comprobantes"]],
            periodo=contenido.get("periodo", ""),
            ruc=contenido.get("ruc"),
            origen=contenido.get("origen", ""),
            advertencias=list(contenido.get("advertencias", [])),
            ventas={k: str(v) for k, v in contenido.get("ventas", {}).items()},
        )
    except (OSError, KeyError, TypeError, ArithmeticError, json.JSONDecodeError) as error:
        raise ValueError(f"No se pudo leer el trabajo guardado: {error}") from error
