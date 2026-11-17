from __future__ import annotations

import sqlite3

import pytest

from app.core import db

AHORA = "2026-11-17T00:00:00+00:00"


def _insertar(cx, **campos):
    fila = dict(ruc="1790011674001", tipo_contribuyente="sociedad", cedula=None,
                carpeta="1790011674001", nombre="X", creado_en=AHORA, actualizado_en=AHORA)
    fila.update(campos)
    cols = ", ".join(fila)
    cx.execute(f"INSERT INTO clientes ({cols}) VALUES ({', '.join('?' * len(fila))})",
               list(fila.values()))


def test_base_nueva_con_esquema(tmp_path):
    with db.abrir(tmp_path / "x.db") as cx:
        assert db.version_esquema(cx) == db.VERSION_ESQUEMA
        tablas = {r[0] for r in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"clientes", "credenciales", "llaves", "bitacora"} <= tablas
        assert cx.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert cx.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_reabrir_no_vuelve_a_migrar(tmp_path):
    ruta = tmp_path / "x.db"
    with db.abrir(ruta) as cx:
        _insertar(cx)
    with db.abrir(ruta) as cx:
        assert cx.execute("SELECT count(*) FROM clientes").fetchone()[0] == 1


def test_esquema_mas_nuevo(tmp_path):
    ruta = tmp_path / "x.db"
    with db.abrir(ruta) as cx:
        cx.execute(f"PRAGMA user_version = {db.VERSION_ESQUEMA + 1}")
    with pytest.raises(db.EsquemaMasNuevo):
        db.conectar(ruta)


@pytest.mark.parametrize("campos", [
    dict(ruc="179001167400"),                                       # 12 dígitos
    dict(ruc="17900116740A1", carpeta="17900116740A1"),             # letra
    dict(tipo_contribuyente="otro"),
    dict(tipo_contribuyente="natural"),                             # natural sin cédula
    dict(cedula="1710034065", carpeta="1710034065"),                # sociedad con cédula
    dict(carpeta="otra"),                                           # carpeta incoherente
    dict(nombre="   "),
])
def test_check_rechazan_datos_incoherentes(tmp_path, campos):
    with db.abrir(tmp_path / "x.db") as cx:
        with pytest.raises(sqlite3.IntegrityError):
            _insertar(cx, **campos)


def test_transaccion_hace_rollback(tmp_path):
    with db.abrir(tmp_path / "x.db") as cx:
        with pytest.raises(RuntimeError):
            with db.transaccion(cx):
                _insertar(cx)
                raise RuntimeError
        assert cx.execute("SELECT count(*) FROM clientes").fetchone()[0] == 0


def test_credencial_exige_llave_existente(tmp_path):
    with db.abrir(tmp_path / "x.db") as cx:
        _insertar(cx)
        with pytest.raises(sqlite3.IntegrityError):
            cx.execute(
                "INSERT INTO credenciales (id_cliente, usuario, clave_cifrada, nonce,"
                " version_llave, actualizado_en) VALUES (1, 'u', x'00', ?, 9, ?)",
                (b"0" * 12, AHORA),
            )


def test_respaldo(tmp_path):
    ruta = tmp_path / "x.db"
    with db.abrir(ruta) as cx:
        _insertar(cx)
    db.respaldar(tmp_path / "copia.db", ruta)
    with sqlite3.connect(tmp_path / "copia.db") as cx:
        assert cx.execute("SELECT count(*) FROM clientes").fetchone()[0] == 1
