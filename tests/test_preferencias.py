"""
Pruebas de ``preferencias``: los valores por defecto de la pestaña Descarga
salen del entorno (SRI_RUC / SRI_CLAVE / SRI_DIR) o del archivo ``.env``, y
nunca del código.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import preferencias


def _aislar(monkeypatch, ruta_env: str = "") -> None:
    """Quita las variables del entorno y apunta la búsqueda de ``.env``.

    Sin ``ruta_env`` la búsqueda queda vacía, para que las pruebas no lean el
    ``.env`` real del proyecto.
    """
    for variable in preferencias.CAMPOS.values():
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(
        preferencias, "rutas_env", lambda: [ruta_env] if ruta_env else []
    )


def test_sin_variables_ni_archivo_devuelve_vacio(monkeypatch):
    _aislar(monkeypatch)
    assert preferencias.cargar() == {}


def test_lee_las_tres_variables(monkeypatch):
    _aislar(monkeypatch)
    monkeypatch.setenv("SRI_RUC", "1700000000001")
    monkeypatch.setenv("SRI_CLAVE", "secreta")
    monkeypatch.setenv("SRI_DIR", "/tmp/descargas")
    assert preferencias.cargar() == {
        "ruc": "1700000000001",
        "clave": "secreta",
        "download_dir": "/tmp/descargas",
    }


def test_ignora_valores_vacios_o_con_espacios(monkeypatch):
    _aislar(monkeypatch)
    monkeypatch.setenv("SRI_RUC", "   ")
    monkeypatch.setenv("SRI_CLAVE", "")
    monkeypatch.setenv("SRI_DIR", "  /tmp/descargas  ")
    assert preferencias.cargar() == {"download_dir": "/tmp/descargas"}


def test_lee_el_archivo_env(tmp_path, monkeypatch):
    archivo = tmp_path / ".env"
    archivo.write_text(
        "# comentario\n"
        "SRI_RUC=1700000000001\n"
        'export SRI_CLAVE="con espacios"\n'
        "SRI_DIR=/tmp/descargas\n"
        "\n",
        encoding="utf-8",
    )
    _aislar(monkeypatch, str(archivo))
    assert preferencias.cargar() == {
        "ruc": "1700000000001",
        "clave": "con espacios",
        "download_dir": "/tmp/descargas",
    }


def test_el_entorno_tiene_prioridad_sobre_el_archivo(tmp_path, monkeypatch):
    archivo = tmp_path / ".env"
    archivo.write_text("SRI_RUC=del-archivo\n", encoding="utf-8")
    _aislar(monkeypatch, str(archivo))
    monkeypatch.setenv("SRI_RUC", "del-entorno")
    assert preferencias.cargar()["ruc"] == "del-entorno"


def test_el_directorio_actual_se_busca_antes_que_la_raiz(tmp_path, monkeypatch):
    """La primera ruta candidata es el directorio de trabajo."""
    monkeypatch.chdir(tmp_path)
    assert preferencias.rutas_env()[0] == str(tmp_path / ".env")


def test_clave_heredada_del_archivo(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("SRI_RUC=1790011674001\nSRI_CLAVE=ficticia\n", encoding="utf-8")
    _aislar(monkeypatch, str(env))
    assert preferencias.clave_heredada() == {
        "ruc": "1790011674001", "clave": "ficticia", "origen": str(env)}


def test_clave_heredada_vacia(monkeypatch, tmp_path):
    _aislar(monkeypatch)
    assert preferencias.clave_heredada() == {}


def test_clave_heredada_del_entorno(monkeypatch):
    _aislar(monkeypatch)
    monkeypatch.setenv("SRI_CLAVE", "ficticia")
    assert preferencias.clave_heredada()["origen"] == "entorno"


def test_quitar_variable_conserva_lo_demas(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# credenciales\nSRI_RUC=1\nexport SRI_CLAVE='x'\nSRI_CLAVE_OTRA=y\n",
                   encoding="utf-8")
    assert preferencias.quitar_variable(str(env), "SRI_CLAVE") is True
    assert env.read_text(encoding="utf-8") == "# credenciales\nSRI_RUC=1\nSRI_CLAVE_OTRA=y\n"
    assert preferencias.quitar_variable(str(env), "SRI_CLAVE") is False
