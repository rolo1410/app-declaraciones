"""``tipos_archivo``: filtros que no cierran la app en macOS (Tk 8.6)."""
from __future__ import annotations

import sys

from app.gui.dialogos import tipos_archivo

TIPOS = (("Trabajo", "*.iva.json"), ("JSON", "*.json"), ("Todos", "*.*"))


def test_en_macos_reduce_la_extension_doble_y_quita_repetidos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert tipos_archivo(*TIPOS) == [("Trabajo", "*.json"), ("Todos", "*.*")]


def test_en_otros_sistemas_no_cambia(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert tipos_archivo(*TIPOS) == list(TIPOS)
