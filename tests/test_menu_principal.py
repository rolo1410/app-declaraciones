"""Menú «Clientes»: estado según el cliente activo y cambio de cliente."""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")

pytestmark = pytest.mark.gui


@pytest.fixture
def app(tmp_path, monkeypatch):
    from app.core import cifrado, plataforma, preferencias

    try:
        prueba = tk.Tk()
        prueba.destroy()
    except tk.TclError:
        pytest.skip("sin pantalla para Tk")
    # Un aviso nativo bloquearía la prueba esperando un clic: que falle en su lugar.
    from tkinter import messagebox

    def _aviso(*args, **_kw):
        raise AssertionError(f"messagebox inesperado: {args[:2]}")

    for nombre in ("showinfo", "showwarning", "showerror", "askyesno", "askyesnocancel"):
        monkeypatch.setattr(messagebox, nombre, _aviso)
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


def test_atajo_deshabilitado_no_hace_nada(app):
    m = app.menu
    llamado = []
    app.acciones.abrir_carpeta = lambda c=None: llamado.append(c)
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


def test_configuracion_es_un_formulario_modal_que_guarda(app):
    from app.core import perfil
    from app.gui import dialogos
    from app.gui.pestana_configuracion import DialogoConfiguracion

    vistos = {}

    def durante():
        cfg = dialogo.pagina
        for clave, valor in {"nombre": "Ana", "correo_declarante": "ana@estudio.ec",
                             "usuario": "ana@estudio.ec", "clave": "app-pass"}.items():
            cfg._vars[clave].set(valor)
        cfg.var_proveedor.set("Outlook / Microsoft 365")
        cfg._aplicar_proveedor()
        # Desde Configuración sí se puede abrir otro formulario (anidado)…
        frase = dialogos.DialogoFrase(cfg, "Frase", "x", confirmar=False)
        app.after(30, lambda: (vistos.setdefault("pila", len(app.pila_dialogos)),
                               frase.cancelar()))
        frase.mostrar()
        # …pero no desde fuera de él.
        vistos["externo"] = dialogos.DialogoTexto(app, "Otro", "x").mostrar()
        dialogo.aceptar()

    dialogo = DialogoConfiguracion(app, app.contexto, app.acciones)
    app.after(50, durante)
    dialogo.mostrar()
    assert vistos == {"pila": 2, "externo": None}
    assert app.pila_dialogos == []
    guardado = perfil.leer()
    assert guardado.declarante.nombre == "Ana"
    assert (guardado.correo.servidor, guardado.correo.puerto, guardado.correo.seguridad) == (
        "smtp.office365.com", 587, "starttls")
    assert app.contexto.registro.clave_smtp() == "app-pass"


def test_clic_en_un_mes_elige_cliente_y_mes_y_muestra_sus_etapas(app):
    from tkinter import ttk

    from app.gui import pestana_clientes as pc

    reg = app.contexto.registro
    c = reg.crear_cliente("1790011674001", "Empresa", "x")
    reg.guardar_resumen(c.id, "2026-07", {"impuesto_generado": "150", "credito_tributario": "20",
                                          "impuesto_a_pagar": "130", "credito_a_favor": "0",
                                          "ventas": "1000", "compras": "140", "comprobantes": 3},
                        "2026-08-12 10:00")
    reg.marcar(c.id, "2026-07", "declarada", "2026-08-12")
    inicio = app.pestana_clientes
    inicio.anio = 2026
    app.contexto.lista_cambio()
    app.update()
    x = pc.X_MESES + 6 * pc.PASO + 4
    y = pc.ALTO_CABECERA + pc.ALTO_FILA / 2
    inicio._clic(type("E", (), {"x": x, "y": y})())
    assert app.contexto.cliente.id == c.id and app.contexto.periodo == "2026-07"

    textos = [w.cget("text") for w in _descendientes(inicio.ficha) if isinstance(w, ttk.Label)]
    etapas = ["Descargar comprobantes", "Calcular la declaración", "Presentar en el SRI",
              "Enviar al cliente", "Cobrar"]
    assert [t for t in textos if t in etapas] == etapas
    assert "Declarada el 12/08/2026" in textos
    assert "$ 130.00" in textos  # resumen del mes

    # La barra superior muestra cliente y mes al ir a una etapa. (Sin update():
    # con otra ventana Tk creada antes en el mismo proceso, Tk 8.6 en macOS se
    # cuelga procesando los eventos del sistema; la app real usa una sola.)
    app.ir_a_descarga()
    app.update_idletasks()
    assert app.barra.lbl_titulo.cget("text") == "Empresa"
    assert "julio 2026" in app.barra.lbl_desc.cget("text")
    assert app.pestana_descarga.var_anio.get() == "2026"


def _descendientes(w):
    for hijo in w.winfo_children():
        yield hijo
        yield from _descendientes(hijo)


def test_correo_escrito_en_nombre_visible_se_mueve_a_la_cuenta(app):
    from app.core import perfil
    from app.gui.pestana_configuracion import DialogoConfiguracion

    def durante():
        cfg = dialogo.pagina
        valores = {"nombre": "Rolando estudio", "correo_declarante": "contacto@estudio.ec",
                   "servidor": "localhost", "puerto": "1026", "remitente": "rolo@ejemplo.ec"}
        for clave, valor in valores.items():
            cfg._vars[clave].set(valor)
        cfg.var_seguridad.set("Ninguna")
        cfg.var_autenticar.set(False)
        dialogo.aceptar()

    dialogo = DialogoConfiguracion(app, app.contexto, app.acciones)
    app.after(50, durante)
    dialogo.mostrar()
    c = perfil.leer().correo
    assert (c.usuario, c.remitente) == ("rolo@ejemplo.ec", "Rolando estudio")
