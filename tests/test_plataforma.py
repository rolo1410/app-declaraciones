from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from app.core import plataforma


def test_datos_dir_respeta_variable(tmp_path):
    assert plataforma.datos_dir() == tmp_path / "datos"
    assert (tmp_path / "datos").is_dir()


def test_base_path_por_defecto_y_configurable(tmp_path):
    assert plataforma.base_path() == (Path.home() / "ComprobantesSRI").resolve()
    nueva = plataforma.fijar_base_path(str(tmp_path / "mis clientes"))
    assert nueva == (tmp_path / "mis clientes").resolve()
    assert plataforma.base_path() == nueva
    assert plataforma.carpeta_clientes() == nueva / "clientes"


def test_config_con_barras_invertidas_y_comillas(tmp_path):
    plataforma.guardar_config({"base_path": 'C:\\Datos\\"raro"'})
    assert plataforma.leer_config()["base_path"] == 'C:\\Datos\\"raro"'
    texto = plataforma.ruta_config().read_text(encoding="utf-8")
    assert plataforma._parsear_toml_simple(texto)["base_path"] == 'C:\\Datos\\"raro"'


def test_config_danada_usa_defecto(tmp_path):
    plataforma.ruta_config().write_text("base_path = [sin cerrar", encoding="utf-8")
    assert isinstance(plataforma.leer_config(), dict)


@pytest.mark.parametrize("texto", ["~/X", "$HOME/X", "${HOME}/X", "%USERPROFILE%/X"])
def test_expandir_ruta(texto, monkeypatch):
    if sys.platform == "win32":
        monkeypatch.setenv("HOME", str(Path.home()))
    assert Path(plataforma.expandir_ruta(texto)) == Path.home() / "X"


def test_dentro_de(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    assert plataforma.dentro_de(base / "clientes" / "1", base)
    assert not plataforma.dentro_de(base / ".." / "fuera", base)
    assert not plataforma.dentro_de(tmp_path / "base2", base)


@pytest.mark.parametrize("ruta,servicio", [
    ("/Users/x/Library/Mobile Documents/com~apple~CloudDocs/SRI", "iCloud Drive"),
    ("/home/x/Dropbox/SRI", "Dropbox"),
    ("/Users/x/Library/CloudStorage/GoogleDrive-a@b.com/My Drive/SRI", "Google Drive"),
    ("/Users/x/OneDrive - Empresa/SRI", "OneDrive"),
    ("/home/x/ComprobantesSRI", None),
])
def test_carpeta_en_nube(ruta, servicio):
    assert plataforma.carpeta_en_nube(Path(ruta)) == servicio


def test_escribir_atomico(tmp_path):
    destino = tmp_path / "sub" / "a.json"
    plataforma.escribir_atomico(destino, b"uno")
    plataforma.escribir_atomico(destino, b"dos")
    assert destino.read_bytes() == b"dos"
    assert [p.name for p in destino.parent.iterdir()] == ["a.json"]


def test_escribir_atomico_reintenta_si_esta_bloqueado(tmp_path, monkeypatch):
    llamadas = {"n": 0}
    real = os.replace

    def bloqueado(a, b):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise PermissionError("bloqueado")
        real(a, b)

    monkeypatch.setattr(plataforma.os, "replace", bloqueado)
    monkeypatch.setattr(plataforma.time, "sleep", lambda s: None)
    plataforma.escribir_atomico(tmp_path / "a.txt", b"x")
    assert (tmp_path / "a.txt").read_bytes() == b"x"
    assert llamadas["n"] == 2


@pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")
def test_restringir_permisos_posix(tmp_path):
    carpeta = tmp_path / "c"
    (carpeta / "sub").mkdir(parents=True)
    (carpeta / "sub" / "a.xml").write_text("x")
    plataforma.restringir_permisos(carpeta)
    assert os.stat(carpeta).st_mode & 0o777 == 0o700
    assert os.stat(carpeta / "sub").st_mode & 0o777 == 0o700
    assert os.stat(carpeta / "sub" / "a.xml").st_mode & 0o777 == 0o600


@pytest.mark.skipif(sys.platform != "win32", reason="solo Windows")
def test_restringir_permisos_windows_dentro_del_perfil_no_falla(tmp_path):
    plataforma.restringir_permisos(tmp_path)


def test_candado_excluye_entre_procesos(tmp_path):
    import subprocess

    ruta = tmp_path / "x.lock"
    codigo = (
        "import sys; from app.core.plataforma import Candado, CandadoOcupado\n"
        f"c = Candado(r'{ruta}')\n"
        "try:\n    c.adquirir()\nexcept CandadoOcupado:\n    sys.exit(3)\nsys.exit(0)\n"
    )
    raiz = Path(__file__).resolve().parents[1]
    with plataforma.Candado(ruta):
        r = subprocess.run([sys.executable, "-c", codigo], cwd=raiz)
        assert r.returncode == 3
    r = subprocess.run([sys.executable, "-c", codigo], cwd=raiz)
    assert r.returncode == 0


def test_candado_se_puede_reusar(tmp_path):
    c = plataforma.Candado(tmp_path / "x.lock")
    with c:
        pass
    with c:
        pass


def test_una_sola_ventana_de_la_app(monkeypatch):
    """Con la app ya abierta (candado tomado) no se crea otra ventana."""
    from app.core import plataforma
    from app.gui import main_window

    avisos = []
    monkeypatch.setattr(main_window, "_avisar_ya_abierta", lambda: avisos.append(True))
    monkeypatch.setattr(main_window, "App", lambda: (_ for _ in ()).throw(
        AssertionError("no debía abrir otra ventana")))
    abierta = plataforma.candado_app()
    abierta.adquirir()
    try:
        assert main_window.ejecutar_gui() is False
        assert avisos == [True]
    finally:
        abierta.liberar()
