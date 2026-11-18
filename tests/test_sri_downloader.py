"""
Pruebas unitarias para las funciones puras de ``sri_downloader``.

No requieren navegador ni conexión: validan la lógica de validación de
parámetros, saneamiento de nombres de archivo, generación de rutas únicas y
armado de subcarpetas por periodo.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime

from app.core.sri_downloader import (
    TIPO_EMITIDOS,
    TIPO_RECIBIDOS,
    es_error_navegador_cerrado,
    periodo_anterior,
    DownloadConfig,
    extraer_clave_acceso,
    ruta_unica,
    sanitizar_nombre,
    subdirectorio_periodo,
    validar_config,
)


def _cfg(tmp_path, **overrides) -> DownloadConfig:
    base = dict(
        ruc="9999999999001",
        clave="secreto",
        anio=datetime.now().year,
        mes=6,
        dia=0,
        download_dir=str(tmp_path),
        tipo=TIPO_RECIBIDOS,
    )
    base.update(overrides)
    return DownloadConfig(**base)


# --- validar_config -------------------------------------------------------

def test_config_valida_sin_errores(tmp_path):
    assert validar_config(_cfg(tmp_path)) == []


def test_ruc_vacio(tmp_path):
    errores = validar_config(_cfg(tmp_path, ruc=""))
    assert any("RUC" in e for e in errores)


def test_ruc_no_numerico(tmp_path):
    errores = validar_config(_cfg(tmp_path, ruc="ABC123"))
    assert any("dígitos" in e for e in errores)


def test_clave_vacia(tmp_path):
    errores = validar_config(_cfg(tmp_path, clave="   "))
    assert any("clave" in e.lower() for e in errores)


def test_anio_fuera_de_rango(tmp_path):
    errores = validar_config(_cfg(tmp_path, anio=1990))
    assert any("año" in e.lower() for e in errores)


def test_anio_futuro(tmp_path):
    errores = validar_config(_cfg(tmp_path, anio=datetime.now().year + 5))
    assert any("año" in e.lower() for e in errores)


@pytest.mark.parametrize("mes", [0, 13, -1, 99])
def test_mes_invalido(tmp_path, mes):
    errores = validar_config(_cfg(tmp_path, mes=mes))
    assert any("mes" in e.lower() for e in errores)


@pytest.mark.parametrize("dia", [-1, 32, 40])
def test_dia_invalido(tmp_path, dia):
    errores = validar_config(_cfg(tmp_path, dia=dia))
    assert any("día" in e.lower() for e in errores)


def test_dia_todos_es_valido(tmp_path):
    assert validar_config(_cfg(tmp_path, dia=0)) == []


def test_directorio_inexistente(tmp_path):
    errores = validar_config(_cfg(tmp_path, download_dir=str(tmp_path / "no_existe")))
    assert any("directorio" in e.lower() for e in errores)


def test_directorio_vacio(tmp_path):
    errores = validar_config(_cfg(tmp_path, download_dir=""))
    assert any("directorio" in e.lower() for e in errores)


def test_tipo_invalido(tmp_path):
    errores = validar_config(_cfg(tmp_path, tipo="otro"))
    assert any("tipo" in e.lower() for e in errores)


# --- sanitizar_nombre -----------------------------------------------------

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("factura.xml", "factura.xml"),
        ("a/b\\c:d.xml", "a_b_c_d.xml"),
        ('archivo<>:"|?*.xml', "archivo_______.xml"),
        ("", "comprobante.xml"),
        ("   ", "comprobante.xml"),
        ("...", "comprobante.xml"),
    ],
)
def test_sanitizar_nombre(entrada, esperado):
    assert sanitizar_nombre(entrada) == esperado


def test_sanitizar_elimina_control_chars():
    assert "\n" not in sanitizar_nombre("linea\ncon\tsalto.xml")


# --- ruta_unica -----------------------------------------------------------

def test_ruta_unica_sin_colision(tmp_path):
    ruta = ruta_unica(str(tmp_path), "comprobante.xml")
    assert ruta == os.path.join(str(tmp_path), "comprobante.xml")


def test_ruta_unica_con_colision(tmp_path):
    (tmp_path / "comprobante.xml").write_text("x")
    ruta = ruta_unica(str(tmp_path), "comprobante.xml")
    assert ruta == os.path.join(str(tmp_path), "comprobante_1.xml")


def test_ruta_unica_multiples_colisiones(tmp_path):
    (tmp_path / "doc.xml").write_text("x")
    (tmp_path / "doc_1.xml").write_text("x")
    (tmp_path / "doc_2.xml").write_text("x")
    ruta = ruta_unica(str(tmp_path), "doc.xml")
    assert ruta == os.path.join(str(tmp_path), "doc_3.xml")


# --- subdirectorio_periodo ------------------------------------------------

def test_subdirectorio_dia_todos(tmp_path):
    cfg = _cfg(tmp_path, anio=2024, mes=6, dia=0, tipo=TIPO_RECIBIDOS)
    assert subdirectorio_periodo(cfg) == "recibidos_2024_06_todos"


def test_subdirectorio_dia_especifico(tmp_path):
    cfg = _cfg(tmp_path, anio=2024, mes=6, dia=5, tipo=TIPO_EMITIDOS)
    assert subdirectorio_periodo(cfg) == "emitidos_2024_06_05"


# --- extraer_clave_acceso -------------------------------------------------

def test_clave_desde_claveacceso():
    clave = "1" * 49
    xml = f"<x><claveAcceso>{clave}</claveAcceso></x>"
    assert extraer_clave_acceso(xml) == clave


def test_clave_desde_numeroautorizacion():
    clave = "2" * 49
    xml = f"<autorizacion><numeroAutorizacion>{clave}</numeroAutorizacion></autorizacion>"
    assert extraer_clave_acceso(xml) == clave


def test_clave_ausente_devuelve_none():
    assert extraer_clave_acceso("<x><estado>AUTORIZADO</estado></x>") is None


def test_clave_ignora_numeros_de_otra_longitud():
    assert extraer_clave_acceso("<x><claveAcceso>12345</claveAcceso></x>") is None


@pytest.mark.parametrize(
    "mensaje",
    [
        "Download.save_as: Target page, context or browser has been closed",
        "Locator.click: Target page, context or browser has been closed",
        "Page.goto: Target crashed",
        "Connection closed while reading from the driver",
    ],
)
def test_reconoce_navegador_cerrado(mensaje):
    assert es_error_navegador_cerrado(mensaje)


@pytest.mark.parametrize(
    "mensaje",
    [
        "Timeout 30000ms exceeded",
        "strict mode violation: locator resolved to 2 elements",
        "",
    ],
)
def test_otros_errores_no_son_navegador_cerrado(mensaje):
    assert not es_error_navegador_cerrado(mensaje)


@pytest.mark.parametrize(
    "hoy, esperado",
    [
        (datetime(2026, 9, 17), (2026, 8)),
        (datetime(2026, 3, 1), (2026, 2)),
        (datetime(2026, 12, 31), (2026, 11)),
        (datetime(2026, 1, 5), (2025, 12)),   # enero retrocede de año
    ],
)
def test_periodo_anterior(hoy, esperado):
    assert periodo_anterior(hoy) == esperado


# --- clientes registrados (PLAN-clientes.md §6.4 y §7) -----------------------

import contextlib  # noqa: E402
import unicodedata  # noqa: E402

from app.core import analizador  # noqa: E402
from app.core.sri_downloader import (  # noqa: E402
    DOMINIOS_SRI,
    SRIDownloader,
    comprador_ajeno,
)


def _xml(comprador: str | None, clave: str = "1" * 49, tag="identificacionComprador") -> str:
    ident = f"<{tag}>{comprador}</{tag}>" if comprador else ""
    interno = (f"<factura><infoTributaria><claveAcceso>{clave}</claveAcceso></infoTributaria>"
               f"<infoFactura>{ident}</infoFactura></factura>")
    return (f"<autorizacion><numeroAutorizacion>{clave}</numeroAutorizacion>"
            f"<comprobante><![CDATA[{interno}]]></comprobante></autorizacion>")


def test_la_clave_no_aparece_en_repr(tmp_path):
    assert "secreto" not in repr(_cfg(tmp_path))


@pytest.mark.parametrize("entrada,esperado", [
    ("CON.xml", "_CON.xml"), ("con", "_con"), ("COM1.tar.gz", "_COM1.tar.gz"),
    ("LPT9.xml", "_LPT9.xml"), ("CONSOLA.xml", "CONSOLA.xml"), ("COM10.xml", "COM10.xml"),
])
def test_sanitizar_nombres_reservados_windows(entrada, esperado):
    assert sanitizar_nombre(entrada) == esperado


def test_sanitizar_normaliza_nfc():
    nfd = unicodedata.normalize("NFD", "año_señal.xml")
    assert sanitizar_nombre(nfd) == unicodedata.normalize("NFC", "año_señal.xml")


def test_sanitizar_limita_longitud_y_conserva_extension():
    nombre = sanitizar_nombre("x" * 300 + ".xml")
    assert len(nombre) == 100 and nombre.endswith(".xml")


def test_identificacion_comprador():
    assert analizador.identificacion_comprador(_xml("1710034065001")) == "1710034065001"
    assert analizador.identificacion_comprador(
        _xml("1790011674001", tag="identificacionSujetoRetenido")) == "1790011674001"
    assert analizador.identificacion_comprador(_xml(None)) is None
    assert analizador.identificacion_comprador("no es xml") is None


@pytest.mark.parametrize("comprador,esperado", [
    ("1710034065001", None),      # RUC del cliente
    ("1710034065", None),         # cédula del cliente
    (None, None),                 # sin comprador (guía de remisión)
    ("1790011674001", "1790011674001"),  # otro contribuyente
])
def test_comprador_ajeno(comprador, esperado):
    idents = {"1710034065001", "1710034065"}
    assert comprador_ajeno(_xml(comprador), idents) == esperado


def test_sin_cliente_registrado_no_se_comprueba():
    assert comprador_ajeno(_xml("1790011674001"), None) is None


@pytest.mark.parametrize("dominio,coincide", [
    ("srienlinea.sri.gob.ec", True), (".sri.gob.ec", True), ("sri.gob.ec", True),
    (".google.com", False), ("www.recaptcha.net", False), ("sri.gob.ec.evil.com", False),
    ("nosri.gob.ec", False),
])
def test_dominios_sri(dominio, coincide):
    assert bool(DOMINIOS_SRI.search(dominio)) is coincide


# Página falsa de Playwright con una fila de XML por cada contenido.
class _Descarga:
    def __init__(self, contenido):
        self.contenido = contenido
        self.suggested_filename = "comprobante.xml"

    def save_as(self, ruta):
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write(self.contenido)


class _Pagina:
    def __init__(self, contenidos):
        self.contenidos = contenidos
        self._actual = None

    def locator(self, _sel):
        pagina = self

        class _Loc:
            def count(self):
                return len(pagina.contenidos)

            def nth(self, i):
                class _Enlace:
                    def click(self_inner):
                        pagina._actual = _Descarga(pagina.contenidos[i])
                return _Enlace()
        return _Loc()

    def is_closed(self):
        return False

    def wait_for_timeout(self, _ms):
        pass

    @contextlib.contextmanager
    def expect_download(self, timeout=None):
        class _Info:
            pass
        info = _Info()
        yield info
        info.value = self._actual


def test_dos_clientes_seguidos_cada_xml_en_su_carpeta(tmp_path):
    natural = {"1710034065001", "1710034065"}
    sociedad = {"1790011674001"}
    xml_a = _xml("1710034065", clave="1" * 49)
    xml_b = _xml("1790011674001", clave="2" * 49)
    carpeta_a, carpeta_b = tmp_path / "a", tmp_path / "b"
    carpeta_a.mkdir(); carpeta_b.mkdir()

    for idents, carpeta in ((natural, carpeta_a), (sociedad, carpeta_b)):
        d = SRIDownloader(_cfg(tmp_path, identificaciones_cliente=idents))
        # La "sesión" devuelve ambos XML: solo el del cliente debe quedarse.
        assert d._descargar_pagina_actual(_Pagina([xml_a, xml_b]), str(carpeta)) == 1
        assert d.rechazados == 1

    assert sorted(p.name for p in carpeta_a.iterdir()) == ["1" * 49 + ".xml"]
    assert sorted(p.name for p in carpeta_b.iterdir()) == ["2" * 49 + ".xml"]


def test_cerrar_sesion_sri_borra_solo_cookies_del_sri(tmp_path):
    llamadas = []

    class _Ctx:
        def clear_cookies(self, **kw):
            llamadas.append(kw)

    SRIDownloader(_cfg(tmp_path))._cerrar_sesion_sri(_Ctx())
    assert llamadas == [{"domain": DOMINIOS_SRI}]
