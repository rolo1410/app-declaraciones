"""Valores por defecto de la pestaña «Descarga».

Las credenciales del SRI nunca se escriben en el código ni se versionan: salen
de las variables de entorno ``SRI_RUC``, ``SRI_CLAVE`` y ``SRI_DIR``, y si no
están definidas se leen del archivo ``.env`` (ignorado por git). Así funciona
igual con ``./run.sh``, con ``python -m app.main`` o con el ejecutable
empaquetado.

El ``.env`` se busca, en este orden:
  1. el directorio actual,
  2. la raíz del proyecto (junto a ``app/``),
  3. la carpeta del ejecutable, cuando corre empaquetado con PyInstaller.

Una variable de entorno definida tiene prioridad sobre el archivo.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List

# campo interno -> variable de entorno
CAMPOS = {
    "ruc": "SRI_RUC",
    "clave": "SRI_CLAVE",
    "download_dir": "SRI_DIR",
}

NOMBRE_ARCHIVO_ENV = ".env"


def rutas_env() -> List[str]:
    """Rutas candidatas del ``.env``, en orden de búsqueda y sin repetidos."""
    raiz_proyecto = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    candidatas = [
        os.path.join(os.getcwd(), NOMBRE_ARCHIVO_ENV),
        os.path.join(raiz_proyecto, NOMBRE_ARCHIVO_ENV),
    ]
    if getattr(sys, "frozen", False):  # ejecutable PyInstaller
        candidatas.append(
            os.path.join(os.path.dirname(sys.executable), NOMBRE_ARCHIVO_ENV)
        )

    vistas: set = set()
    unicas: List[str] = []
    for ruta in candidatas:
        if ruta not in vistas:
            vistas.add(ruta)
            unicas.append(ruta)
    return unicas


def _leer_archivo_env(ruta: str) -> Dict[str, str]:
    """Parseo mínimo de ``CLAVE=valor``: comentarios, ``export`` y comillas."""
    valores: Dict[str, str] = {}
    try:
        with open(ruta, encoding="utf-8") as fh:
            for linea in fh:
                linea = linea.strip()
                if not linea or linea.startswith("#") or "=" not in linea:
                    continue
                clave, _, valor = linea.partition("=")
                clave = clave.strip()
                if clave.startswith("export "):
                    clave = clave[len("export "):].strip()
                valor = valor.strip()
                if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
                    valor = valor[1:-1]
                if clave:
                    valores[clave] = valor
    except OSError:
        pass  # archivo ilegible: se sigue solo con el entorno
    return valores


def cargar() -> Dict[str, str]:
    """Devuelve los valores por defecto disponibles (entorno y/o ``.env``).

    Los valores vacíos o en blanco se descartan, de modo que ``SRI_CLAVE=``
    equivale a no definirla y el campo queda para llenar a mano.
    """
    del_archivo: Dict[str, str] = {}
    for ruta in rutas_env():
        if os.path.isfile(ruta):
            del_archivo = _leer_archivo_env(ruta)
            break

    valores: Dict[str, str] = {}
    for campo, variable in CAMPOS.items():
        valor = (
            os.environ.get(variable, "").strip()
            or del_archivo.get(variable, "").strip()
        )
        if valor:
            valores[campo] = valor
    return valores
