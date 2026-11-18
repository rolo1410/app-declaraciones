"""Fixtures comunes: llavero en memoria y carpetas aisladas en ``tmp_path``.

Ninguna prueba toca el almacén de credenciales real ni la carpeta de datos del
usuario.
"""
from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend


class LlaveroMemoria(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.datos: dict[tuple[str, str], str] = {}

    def get_password(self, service, username):
        return self.datos.get((service, username))

    def set_password(self, service, username, password):
        self.datos[(service, username)] = password

    def delete_password(self, service, username):
        self.datos.pop((service, username), None)


@pytest.fixture(autouse=True)
def _aislar(tmp_path, monkeypatch):
    """Datos de la app y llavero aislados en cada prueba."""
    monkeypatch.setenv("COMPROBANTES_SRI_DATOS", str(tmp_path / "datos"))
    anterior = keyring.get_keyring()
    memoria = LlaveroMemoria()
    keyring.set_keyring(memoria)
    yield memoria
    keyring.set_keyring(anterior)


@pytest.fixture
def llavero_memoria(_aislar):
    return _aislar
