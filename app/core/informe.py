"""Informe de la declaración para el cliente: adjuntos y texto del correo.

El paquete se arma en una carpeta (``resultados/<AAAA-MM>/envio_<fecha>``) con:

* ``declaracion_iva_<periodo>.pdf``: casilleros, resumen y «Preparado por».
* ``declaracion_iva_<periodo>.xlsx``: el mismo detalle en Excel.
* ``comprobantes_<periodo>.zip``: los XML del período encontrados en la
  carpeta de descargas del cliente (se buscan por clave de acceso, así no
  importa en qué subcarpeta quedaron).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Declaracion

# Día de vencimiento de la declaración mensual de IVA según el noveno dígito
# del RUC (Reglamento a la LRTI, art. 158).
DIA_POR_NOVENO_DIGITO = {"1": 10, "2": 12, "3": 14, "4": 16, "5": 18,
                         "6": 20, "7": 22, "8": 24, "9": 26, "0": 28}

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")

# Por encima de esto muchos servidores rechazan el correo (Gmail: 25 MB).
LIMITE_ADJUNTOS = 20 * 1024 * 1024

_CLAVE = re.compile(rb"<(?:claveAcceso|numeroAutorizacion)>\s*(\d{49})\s*</")


def nombre_periodo(periodo: str) -> str:
    """``2026-07`` → ``julio 2026``."""
    try:
        anio, mes = periodo.split("-")
        return f"{MESES[int(mes) - 1]} {anio}"
    except (ValueError, IndexError):
        return periodo


def fecha_limite(ruc: str, periodo: str) -> date | None:
    """Vencimiento de la declaración mensual de IVA del ``periodo`` (``AAAA-MM``).

    Es el día que corresponde al noveno dígito del RUC en el mes siguiente;
    si cae en sábado o domingo pasa al lunes. Los feriados no se consideran.
    """
    try:
        anio, mes = (int(x) for x in periodo.split("-"))
        dia = DIA_POR_NOVENO_DIGITO[ruc[8]]
    except (ValueError, IndexError, KeyError):
        return None
    anio, mes = (anio + 1, 1) if mes == 12 else (anio, mes + 1)
    limite = date(anio, mes, dia)
    while limite.weekday() >= 5:
        limite += timedelta(days=1)
    return limite


def xml_de_comprobantes(carpeta: Path, claves: set[str]) -> list[Path]:
    """XML de ``carpeta`` (y subcarpetas) cuya clave de acceso está en ``claves``.

    Si hay dos archivos con la misma clave se toma uno solo.
    """
    encontrados: dict[str, Path] = {}
    if not claves or not carpeta.is_dir():
        return []
    for ruta in sorted(carpeta.rglob("*.xml")):
        try:
            contenido = ruta.read_bytes()
        except OSError:
            continue
        for coincidencia in _CLAVE.finditer(contenido):
            clave = coincidencia.group(1).decode()
            if clave in claves and clave not in encontrados:
                encontrados[clave] = ruta
                break
    return list(encontrados.values())


def comprimir(archivos: list[Path], destino: Path) -> Path:
    """Zip con los archivos (nombres repetidos se numeran)."""
    usados: set[str] = set()
    with zipfile.ZipFile(destino, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ruta in archivos:
            nombre, n = ruta.name, 1
            while nombre.lower() in usados:
                nombre = f"{ruta.stem} ({n}){ruta.suffix}"
                n += 1
            usados.add(nombre.lower())
            zf.write(ruta, nombre)
    return destino


@dataclass
class Paquete:
    carpeta: Path
    adjuntos: list[Path] = field(default_factory=list)
    xml_incluidos: int = 0
    xml_faltantes: int = 0

    @property
    def tamano(self) -> int:
        return sum(p.stat().st_size for p in self.adjuntos if p.exists())


def armar_paquete(
    declaracion: Declaracion,
    destino: Path,
    *,
    contribuyente: tuple[str, str],
    declarante=None,
    logo: Path | None = None,
    carpeta_xml: Path | None = None,
    incluir_pdf: bool = True,
    incluir_excel: bool = True,
    incluir_xml: bool = True,
) -> Paquete:
    """Genera los adjuntos en ``destino`` (que se crea)."""
    from ..export.excel import exportar_excel
    from ..export.pdf import exportar_pdf

    destino.mkdir(parents=True, exist_ok=True)
    paquete = Paquete(destino)
    base = f"declaracion_iva_{declaracion.periodo}"
    if incluir_pdf:
        ruta = destino / f"{base}.pdf"
        exportar_pdf(declaracion, str(ruta), contribuyente=contribuyente,
                     declarante=declarante, logo=logo)
        paquete.adjuntos.append(ruta)
    if incluir_excel:
        ruta = destino / f"{base}.xlsx"
        exportar_excel(declaracion, str(ruta))
        paquete.adjuntos.append(ruta)
    if incluir_xml:
        claves = claves_del_periodo(declaracion)
        xml = xml_de_comprobantes(carpeta_xml, claves) if carpeta_xml else []
        paquete.xml_incluidos = len(xml)
        paquete.xml_faltantes = len(claves) - len(xml)
        if xml:
            paquete.adjuntos.append(
                comprimir(xml, destino / f"comprobantes_{declaracion.periodo}.zip"))
    return paquete


def claves_del_periodo(declaracion: Declaracion) -> set[str]:
    return {c.clave_acceso for c in declaracion.comprobantes
            if c.clave_acceso and c.periodo == declaracion.periodo}


def carpeta_envio(resultados_periodo: Path) -> Path:
    return resultados_periodo / f"envio_{datetime.now():%Y%m%d-%H%M%S}"


def asunto(declaracion: Declaracion, nombre_cliente: str) -> str:
    return f"Declaración de IVA {nombre_periodo(declaracion.periodo)} — {nombre_cliente}"


def cuerpo(declaracion: Declaracion, nombre_cliente: str, ruc: str, declarante=None) -> str:
    """Texto del correo con el resumen y la firma de quien declara."""
    r = declaracion.resumen
    periodo = nombre_periodo(declaracion.periodo)
    lineas = [
        f"Estimado/a {nombre_cliente}:",
        "",
        f"Le envío el informe de la declaración de IVA de {periodo} (RUC {ruc}).",
        "",
        "Resumen:",
        f"  • Impuesto generado en ventas (casillero 499): $ {r.impuesto_generado:,.2f}",
        f"  • Crédito tributario en compras (casillero 564): $ {r.credito_tributario:,.2f}",
    ]
    if r.impuesto_a_pagar > 0:
        lineas.append(f"  • IMPUESTO A PAGAR: $ {r.impuesto_a_pagar:,.2f}")
    else:
        lineas.append(f"  • Crédito a favor para el próximo mes: $ {r.credito_a_favor:,.2f}")
    limite = fecha_limite(ruc, declaracion.periodo)
    if limite:
        lineas += [
            "",
            f"Fecha límite de presentación: {limite:%d/%m/%Y} (según el noveno dígito del RUC; "
            "si es feriado, el siguiente día hábil).",
        ]
    lineas += [
        "",
        "Adjunto el detalle en PDF y Excel, y los comprobantes electrónicos del período.",
        "Quedo atento/a a cualquier consulta.",
        "",
        "Saludos cordiales,",
    ]
    if declarante is not None:
        lineas += declarante.lineas_firma()
    return "\n".join(lineas)
