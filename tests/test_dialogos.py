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


def test_dialogo_dentro_de_la_ventana_bloquea_el_menu_y_se_limpia():
    import pytest

    tk = pytest.importorskip("tkinter")
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sin pantalla para Tk")
    from app.gui.dialogos import DialogoTexto

    barra = tk.Menu(raiz)
    barra.add_cascade(label="Clientes", menu=tk.Menu(barra, tearoff=False))
    raiz.configure(menu=barra)
    vistos = {}

    def durante():
        vistos["menu"] = barra.entrycget(0, "state")
        vistos["abiertos"] = raiz.dialogos_abiertos
        dialogo.var.set("Nuevo nombre")
        dialogo.aceptar()

    dialogo = DialogoTexto(raiz, "Renombrar", "Nombre:", "Viejo")
    raiz.after(50, durante)
    try:
        assert dialogo.mostrar() == "Nuevo nombre"
        assert vistos == {"menu": "disabled", "abiertos": 1}
        assert barra.entrycget(0, "state") == "normal"
        assert raiz.dialogos_abiertos == 0
        assert raiz.bind("<Escape>") == ""
    finally:
        raiz.destroy()
