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
    DownloadConfig,
    extraer_clave_acceso,
    ruta_unica,
    sanitizar_nombre,
    subdirectorio_periodo,
    validar_config,
)


def _cfg(tmp_path, **overrides) -> DownloadConfig:
    base = dict(
        ruc="1791287541001",
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
