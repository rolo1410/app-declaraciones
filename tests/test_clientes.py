from __future__ import annotations

import os
import sqlite3
import sys

import pytest

from app.core import cifrado, clientes, db, plataforma
from app.core.ruc import RucInvalido

NATURAL = "1710034065001"
SOCIEDAD = "1790011674001"
PUBLICA = "1760001550001"
CLAVE = "clave-ficticia-de-prueba-123"


@pytest.fixture
def registro(tmp_path):
    return clientes.Registro(ruta_db=tmp_path / "datos" / "c.db", base=tmp_path / "base")


def test_alta_natural_crea_carpeta_con_cedula(registro, tmp_path):
    c = registro.crear_cliente(NATURAL, "Juan Pérez", CLAVE)
    assert c.tipo == "natural" and c.carpeta == "1710034065"
    carpeta = tmp_path / "base" / "clientes" / "1710034065"
    assert (carpeta / "descargas").is_dir() and (carpeta / "resultados").is_dir()
    assert registro.carpeta_cliente(c) == carpeta.resolve()
    assert c.identificaciones == {NATURAL, "1710034065"}


@pytest.mark.parametrize("ruc", [SOCIEDAD, PUBLICA])
def test_alta_sociedad_y_publica_usan_el_ruc(registro, tmp_path, ruc):
    c = registro.crear_cliente(ruc, "Empresa S.A.", CLAVE)
    assert c.carpeta == ruc and c.cedula is None
    assert (tmp_path / "base" / "clientes" / ruc / "descargas").is_dir()


def test_alta_devuelve_advertencias(registro):
    c = registro.crear_cliente("1790011675001", "Empresa", CLAVE)
    assert c.advertencias


def test_ruc_duplicado(registro):
    registro.crear_cliente(SOCIEDAD, "A", CLAVE)
    with pytest.raises(clientes.ClienteDuplicado):
        registro.crear_cliente(SOCIEDAD, "B", CLAVE)
    # La carpeta del primero sigue intacta.
    assert registro.carpeta_cliente(registro.listar()[0]).is_dir()


def test_ruc_invalido_no_crea_nada(registro, tmp_path):
    with pytest.raises(RucInvalido):
        registro.crear_cliente("1710034066001", "X", CLAVE)
    assert registro.listar() == []
    assert not (tmp_path / "base" / "clientes").exists()


@pytest.mark.parametrize("nombre,clave", [("", CLAVE), ("  ", CLAVE), ("X", "")])
def test_campos_obligatorios(registro, nombre, clave):
    with pytest.raises(clientes.ErrorClientes):
        registro.crear_cliente(SOCIEDAD, nombre, clave)


def test_fallo_al_crear_carpeta_deshace_el_registro(registro, tmp_path, monkeypatch):
    def falla(_ruta):
        raise OSError("sin permisos")

    registro.listar()  # la base ya existe: el fallo es de la carpeta
    monkeypatch.setattr(plataforma, "restringir_permisos", falla)
    with pytest.raises(OSError):
        registro.crear_cliente(SOCIEDAD, "Empresa", CLAVE)
    assert registro.listar(incluir_inactivos=True) == []
    assert not (tmp_path / "base" / "clientes" / SOCIEDAD).exists()
    with db.abrir(tmp_path / "datos" / "c.db") as cx:
        assert cx.execute("SELECT count(*) FROM credenciales").fetchone()[0] == 0
        assert cx.execute("SELECT count(*) FROM bitacora").fetchone()[0] == 0


def test_fallo_no_borra_carpeta_que_ya_existia(registro, tmp_path, monkeypatch):
    previa = tmp_path / "base" / "clientes" / SOCIEDAD
    previa.mkdir(parents=True)
    (previa / "mio.txt").write_text("x")
    registro.listar()
    monkeypatch.setattr(plataforma, "restringir_permisos", lambda r: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        registro.crear_cliente(SOCIEDAD, "Empresa", CLAVE)
    assert (previa / "mio.txt").exists()


def test_clave_ida_y_vuelta_y_cambio(registro):
    c = registro.crear_cliente(SOCIEDAD, "Empresa", CLAVE)
    assert registro.tiene_clave(c.id)
    assert registro.clave_de(c.id) == CLAVE
    registro.cambiar_clave(c.id, "nueva-clave-ficticia")
    assert registro.clave_de(c.id) == "nueva-clave-ficticia"


def test_la_clave_no_queda_en_claro(registro, tmp_path):
    c = registro.crear_cliente(SOCIEDAD, "Empresa", CLAVE)
    registro.cambiar_clave(c.id, CLAVE + "x")
    registro.registrar_evento("descarga", c.id, "recibidos 2026-10")
    datos = tmp_path / "datos"
    for archivo in datos.iterdir():  # .db, -wal, -shm
        assert CLAVE.encode() not in archivo.read_bytes(), archivo.name
    with db.abrir(datos / "c.db") as cx:
        for (detalle,) in cx.execute("SELECT coalesce(detalle, '') FROM bitacora"):
            assert CLAVE not in detalle
    assert CLAVE not in repr(c)


def test_clave_cifrada_no_se_puede_mover_a_otro_cliente(registro, tmp_path):
    a = registro.crear_cliente(SOCIEDAD, "A", CLAVE)
    b = registro.crear_cliente(NATURAL, "B", "otra-clave-ficticia")
    with db.abrir(tmp_path / "datos" / "c.db") as cx:
        cx.execute(
            "UPDATE credenciales SET (clave_cifrada, nonce) = "
            "(SELECT clave_cifrada, nonce FROM credenciales WHERE id_cliente = ?) "
            "WHERE id_cliente = ?", (a.id, b.id),
        )
    with pytest.raises(cifrado.ClaveIlegible):
        registro.clave_de(b.id)


def test_listar_buscar_desactivar(registro):
    a = registro.crear_cliente(SOCIEDAD, "Ferretería Andes", CLAVE)
    registro.crear_cliente(NATURAL, "Juan Pérez", CLAVE)
    assert [c.nombre for c in registro.listar()] == ["Ferretería Andes", "Juan Pérez"]
    assert [c.ruc for c in registro.listar(buscar="andes")] == [SOCIEDAD]
    assert [c.ruc for c in registro.listar(buscar="1710034065")] == [NATURAL]
    registro.fijar_activo(a.id, False)
    assert [c.ruc for c in registro.listar()] == [NATURAL]
    assert len(registro.listar(incluir_inactivos=True)) == 2
    assert registro.obtener(a.id).activo is False
    registro.fijar_activo(a.id, True)
    assert registro.obtener(a.id).activo is True


def test_por_identificacion_y_renombrar(registro):
    c = registro.crear_cliente(NATURAL, "Juan", CLAVE)
    assert registro.por_identificacion("1710034065").id == c.id
    assert registro.por_identificacion(NATURAL).id == c.id
    assert registro.por_identificacion("9999999999") is None
    registro.renombrar(c.id, "  Juan   Pérez ")
    assert registro.obtener(c.id).nombre == "Juan Pérez"


def test_cliente_no_encontrado(registro):
    with pytest.raises(clientes.ClienteNoEncontrado):
        registro.obtener(99)


def test_mkdir_fallido_deshace_el_registro(registro, tmp_path):
    registro.listar()
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "clientes").write_text("un archivo donde debería ir la carpeta")
    with pytest.raises(OSError):
        registro.crear_cliente(SOCIEDAD, "Empresa", CLAVE)
    assert registro.listar(incluir_inactivos=True) == []


def test_carpetas_de_resultados(registro):
    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    assert registro.carpeta_resultados(c, "2026-10").parts[-3:] == (SOCIEDAD, "resultados", "2026-10")
    assert registro.carpeta_descargas(c).name == "descargas"


def test_asegurar_carpeta_la_recrea(registro):
    import shutil

    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    shutil.rmtree(registro.carpeta_cliente(c))
    assert (registro.asegurar_carpeta(c) / "descargas").is_dir()


# -- llave maestra ------------------------------------------------------------

def test_estado_llave(registro, llavero_memoria):
    assert registro.estado_llave() == "sin_configurar"
    registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    assert registro.estado_llave() == "ok"
    llavero_memoria.datos.clear()
    assert registro.estado_llave() == "falta"
    cifrado.LlaveroSistema().guardar(1, cifrado.generar_llave())
    assert registro.estado_llave() == "no_corresponde"


def test_llave_ajena_detectada_antes_de_descifrar(registro, llavero_memoria):
    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    cifrado.LlaveroSistema().guardar(1, cifrado.generar_llave())
    with pytest.raises(cifrado.LlaveNoCorresponde):
        registro.clave_de(c.id)


def test_copia_de_emergencia_restaura_la_llave(registro, llavero_memoria):
    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    copia = registro.exportar_copia("frase de paso larga")
    llavero_memoria.datos.clear()  # equipo nuevo / llavero borrado
    with pytest.raises(cifrado.LlaveNoDisponible):
        registro.clave_de(c.id)
    assert registro.restaurar_copia(copia, "frase de paso larga") == 1
    assert registro.clave_de(c.id) == CLAVE


def test_copia_de_otra_base_se_rechaza(tmp_path, registro):
    otro = clientes.Registro(ruta_db=tmp_path / "otra.db", base=tmp_path / "b2",
                             llavero=_LlaveroDict())
    otro.crear_cliente(SOCIEDAD, "E", CLAVE)
    copia_ajena = otro.exportar_copia("frase de paso larga")
    registro.crear_cliente(NATURAL, "J", CLAVE)
    with pytest.raises(cifrado.LlaveNoCorresponde):
        registro.restaurar_copia(copia_ajena, "frase de paso larga")


def test_llave_creada_en_alta_fallida_se_reutiliza(registro, llavero_memoria, monkeypatch):
    registro.listar()
    original = plataforma.restringir_permisos
    monkeypatch.setattr(plataforma, "restringir_permisos", lambda r: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    guardada = dict(llavero_memoria.datos)
    assert guardada  # la llave llegó al llavero aunque la base hizo rollback
    monkeypatch.setattr(plataforma, "restringir_permisos", original)
    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    assert llavero_memoria.datos == guardada
    assert registro.clave_de(c.id) == CLAVE


class _LlaveroDict:
    def __init__(self):
        self.d = {}

    def leer(self, version):
        return self.d.get(version)

    def guardar(self, version, llave):
        self.d[version] = llave


@pytest.mark.skipif(sys.platform == "win32", reason="permisos POSIX")
def test_permisos_posix(registro):
    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    carpeta = registro.carpeta_cliente(c)
    assert os.stat(carpeta).st_mode & 0o777 == 0o700
    assert os.stat(carpeta / "descargas").st_mode & 0o777 == 0o700


def test_hilos_distintos_pueden_usar_el_registro(registro):
    import threading

    c = registro.crear_cliente(SOCIEDAD, "E", CLAVE)
    resultado = {}
    t = threading.Thread(target=lambda: resultado.setdefault("clave", registro.clave_de(c.id)))
    t.start(); t.join()
    assert resultado["clave"] == CLAVE
