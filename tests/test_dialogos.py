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
    from app.gui.dialogos import DialogoTexto, tras_el_clic

    barra = tk.Menu(raiz)
    submenu = tk.Menu(barra, tearoff=False)
    abiertos_desde_menu = []
    submenu.add_command(label="Nuevo…", command=tras_el_clic(
        raiz, lambda: abiertos_desde_menu.append(True)))
    barra.add_cascade(label="Clientes", menu=submenu)
    raiz.configure(menu=barra)
    vistos = {}

    def durante():
        vistos["menu"] = barra.entrycget(0, "state")
        vistos["abiertos"] = raiz.dialogos_abiertos
        submenu.invoke(0)  # lo que abre el menú no actúa con un formulario abierto
        raiz.after(20, terminar)

    def terminar():
        dialogo.var.set("Nuevo nombre")
        dialogo.aceptar()

    dialogo = DialogoTexto(raiz, "Renombrar", "Nombre:", "Viejo")
    raiz.after(50, durante)
    try:
        assert dialogo.mostrar() == "Nuevo nombre"
        assert vistos["abiertos"] == 1
        assert abiertos_desde_menu == []
        # El gris de la barra de menús es solo visual; en Windows Tk no lo refleja
        # en la barra (allí el bloqueo lo hace tras_el_clic, comprobado arriba).
        if sys.platform != "win32":
            assert vistos["menu"] == "disabled"
        assert barra.entrycget(0, "state") == "normal"
        assert raiz.dialogos_abiertos == 0
        assert raiz.bind("<Escape>") == ""
    finally:
        raiz.destroy()


def test_solo_un_formulario_modal_a_la_vez():
    import pytest

    tk = pytest.importorskip("tkinter")
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sin pantalla para Tk")
    from app.gui.dialogos import DialogoTexto, tras_el_clic

    vistos = {}
    abiertos = []

    def durante():
        vistos["segundo"] = DialogoTexto(raiz, "Segundo", "x", "b").mostrar()
        vistos["pila"] = len(raiz.pila_dialogos)
        # Doble clic sobre un botón que abre un diálogo: no abre nada mientras
        # haya uno abierto.
        boton = tras_el_clic(raiz, lambda: abiertos.append(1))
        boton()
        boton()
        raiz.after(30, primero.cancelar)

    primero = DialogoTexto(raiz, "Primero", "x", "a")
    raiz.after(50, durante)
    try:
        assert primero.mostrar() is None
        raiz.update()
        assert vistos == {"segundo": None, "pila": 1}
        assert abiertos == []
        assert raiz.pila_dialogos == []
    finally:
        raiz.destroy()
