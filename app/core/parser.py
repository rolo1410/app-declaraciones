"""Lectura del archivo TSV de comprobantes recibidos del SRI."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Comprobante

COLUMNAS_REQUERIDAS = {
    "RUC_EMISOR",
    "TIPO_COMPROBANTE",
    "CLAVE_ACCESO",
    "FECHA_EMISION",
    "IDENTIFICACION_RECEPTOR",
    "VALOR_SIN_IMPUESTOS",
    "IVA",
    "IMPORTE_TOTAL",
}

# El SRI exporta estos archivos en Windows-1252; se intenta UTF-8 primero por si
# el archivo fue re-guardado desde otra herramienta.
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

TOLERANCIA = Decimal("0.01")


@dataclass
class ResultadoCarga:
    comprobantes: list[Comprobante] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def periodos(self) -> list[str]:
        return sorted({c.periodo for c in self.comprobantes})


def parsear_decimal(texto: str) -> Decimal:
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return Decimal("0")
    return Decimal(texto)


def parsear_fecha(texto: str):
    return datetime.strptime(texto.strip()[:10], "%d/%m/%Y").date()


def ruc_desde_nombre_archivo(ruta: str | Path) -> str | None:
    """Extrae el RUC del contribuyente del nombre del archivo (ej. 0603545351001_Recibidos.txt)."""
    coincidencia = re.match(r"(\d{13})_", Path(ruta).name)
    return coincidencia.group(1) if coincidencia else None


def _leer_texto(ruta: Path) -> str:
    datos = ruta.read_bytes()
    for encoding in ENCODINGS:
        try:
            return datos.decode(encoding)
        except UnicodeDecodeError:
            continue
    return datos.decode("cp1252", errors="replace")


def leer_archivo(ruta: str | Path) -> ResultadoCarga:
    """Lee y valida el archivo de recibidos. Nunca lanza por filas malas: las reporta."""
    ruta = Path(ruta)
    resultado = ResultadoCarga()
    texto = _leer_texto(ruta)
    lector = csv.DictReader(texto.splitlines(), delimiter="\t")

    columnas = set(lector.fieldnames or [])
    faltantes = COLUMNAS_REQUERIDAS - columnas
    if faltantes:
        raise ValueError(
            f"El archivo no tiene el formato esperado; faltan columnas: {', '.join(sorted(faltantes))}"
        )

    claves_vistas: set[str] = set()
    for numero_fila, fila in enumerate(lector, start=2):
        if not (fila.get("RUC_EMISOR") or "").strip():
            continue  # fila vacía al final del archivo
        try:
            comprobante = Comprobante(
                ruc_emisor=fila["RUC_EMISOR"].strip(),
                razon_social_emisor=(fila.get("RAZON_SOCIAL_EMISOR") or "").strip(),
                tipo_comprobante=fila["TIPO_COMPROBANTE"].strip(),
                serie_comprobante=(fila.get("SERIE_COMPROBANTE") or "").strip(),
                clave_acceso=fila["CLAVE_ACCESO"].strip(),
                fecha_autorizacion=(fila.get("FECHA_AUTORIZACION") or "").strip(),
                fecha_emision=parsear_fecha(fila["FECHA_EMISION"]),
                identificacion_receptor=fila["IDENTIFICACION_RECEPTOR"].strip(),
                valor_sin_impuestos=parsear_decimal(fila["VALOR_SIN_IMPUESTOS"]),
                iva=parsear_decimal(fila["IVA"]),
                importe_total=parsear_decimal(fila["IMPORTE_TOTAL"]),
                numero_documento_modificado=(fila.get("NUMERO_DOCUMENTO_MODIFICADO") or "").strip(),
            )
        except (ValueError, InvalidOperation, KeyError) as error:
            resultado.advertencias.append(f"Fila {numero_fila} ignorada: {error}")
            continue

        if comprobante.clave_acceso in claves_vistas:
            resultado.advertencias.append(
                f"Fila {numero_fila}: comprobante duplicado (clave {comprobante.clave_acceso}); se ignora."
            )
            continue
        claves_vistas.add(comprobante.clave_acceso)

        diferencia = comprobante.valor_sin_impuestos + comprobante.iva - comprobante.importe_total
        if abs(diferencia) > TOLERANCIA:
            mensaje = (
                f"base + IVA no cuadra con el total (diferencia {diferencia}); "
                "puede incluir ICE u otros impuestos."
            )
            comprobante.advertencias.append(mensaje)
            resultado.advertencias.append(
                f"{comprobante.serie_comprobante} ({comprobante.razon_social_emisor}): {mensaje}"
            )

        resultado.comprobantes.append(comprobante)

    return resultado
