"""Menú «Clientes»: estado según el cliente activo y cambio de cliente."""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


@pytest.fixture
def app(tmp_path, monkeypatch):
    from app.core import cifrado, plataforma, preferencias

    try:
        prueba = tk.Tk()
        prueba.destroy()
    except tk.TclError:
        pytest.skip("sin pantalla para Tk")
    monkeypatch.setattr(cifrado, "backend_real", lambda: (True, "memoria"))
    monkeypatch.setattr(preferencias, "clave_heredada", lambda: None)
    plataforma.fijar_base_path(str(tmp_path / "base"))
    from app.gui.main_window import App

    ventana = App()
    ventana.withdraw()
    ventana.update()
    yield ventana
    ventana.destroy()


def _estado(menu, i):
    return menu.entrycget(i, "state")


def test_acciones_del_cliente_activo_dependen_de_que_haya_uno(app):
    m = app.menu
    assert all(_estado(m.m_clientes, i) == "disabled" for i in m.i_activo)
    assert m.m_clientes.entrycget(m.i_encabezado, "label") == "Sin cliente activo"

    c = app.contexto.registro.crear_cliente("1710034065001", "Juan Pérez", "x")
    app.contexto.lista_cambio()
    app.contexto.fijar(c)
    assert all(_estado(m.m_clientes, i) == "normal" for i in m.i_activo)
    assert "1710034065001" in m.m_clientes.entrycget(m.i_encabezado, "label")


def test_submenu_cambia_el_cliente_activo(app):
    m = app.menu
    reg = app.contexto.registro
    reg.crear_cliente("1710034065001", "Juan Pérez", "x")
    reg.crear_cliente("1790011674001", "Empresa SA", "y")
    app.contexto.lista_cambio()

    etiquetas = {m.m_cambiar.entrycget(i, "label"): i
                 for i in range(m.m_cambiar.index("end") + 1)
                 if m.m_cambiar.type(i) == "radiobutton"}
    m.m_cambiar.invoke(etiquetas["Empresa SA (1790011674001)"])
    assert app.contexto.cliente.ruc == "1790011674001"

    m.m_cambiar.invoke(0)
    assert app.contexto.cliente is None


def test_atajo_deshabilitado_no_hace_nada(app):
    m = app.menu
    llamado = []
    pestana = app.pestana_clientes
    pestana.abrir_carpeta = lambda c=None: llamado.append(c)
    indice = m.i_activo[2]  # Abrir carpeta del cliente
    m._invocar(m.m_clientes, indice)
    assert llamado == []


def test_iconos_presentes():
    from app.gui.recursos import ruta_asset

    for nombre in ("icon.png", "icon_ventana.png", "icon.icns", "icon.ico"):
        assert ruta_asset(nombre).is_file(), nombre


def test_cmd_w_cancela_el_dialogo_y_luego_cierra(app, monkeypatch):
    from app.gui.dialogos import DialogoTexto

    cerrada = []
    monkeypatch.setattr(app, "destroy", lambda: cerrada.append(True))
    resultado = {}
    dialogo = DialogoTexto(app, "Prueba", "x", "y")
    app.after(50, app.menu.cerrar_ventana)
    resultado["dialogo"] = dialogo.mostrar()
    assert resultado["dialogo"] is None and cerrada == []

    app.menu.cerrar_ventana()
    assert cerrada == [True]


def test_configuracion_guarda_perfil_y_contrasena_cifrada(app):
    from app.core import perfil

    cfg = app.pestana_configuracion
    for clave, valor in {"nombre": "Ana", "correo_declarante": "ana@estudio.ec",
                         "usuario": "ana@estudio.ec", "clave": "app-pass"}.items():
        cfg._vars[clave].set(valor)
    cfg.var_proveedor.set("Outlook / Microsoft 365")
    cfg._aplicar_proveedor()
    assert cfg.guardar()
    guardado = perfil.leer()
    assert guardado.declarante.nombre == "Ana"
    assert (guardado.correo.servidor, guardado.correo.puerto, guardado.correo.seguridad) == (
        "smtp.office365.com", 587, "starttls")
    assert cfg._vars["clave"].get() == ""  # la contraseña no queda en pantalla
    assert app.contexto.registro.clave_smtp() == "app-pass"
