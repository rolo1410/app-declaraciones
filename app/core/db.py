"""Base SQLite local de clientes y credenciales.

La base vive siempre en ``plataforma.datos_dir()`` (disco local), nunca en la
ruta base de los clientes: SQLite se corrompe en carpetas sincronizadas o de red.

El esquema se versiona con ``PRAGMA user_version``; cada elemento de
``MIGRACIONES`` lleva la base de la versión ``i`` a la ``i + 1``.

Las conexiones no se comparten entre hilos: abrir una con ``conectar()`` por
operación (es barato) y cerrarla al terminar.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

NOMBRE_DB = "clientes.db"

MIGRACIONES: list[str] = [
    # v0 -> v1
    """
    CREATE TABLE clientes (
      id                 INTEGER PRIMARY KEY,
      ruc                TEXT NOT NULL UNIQUE
                         CHECK (length(ruc) = 13 AND ruc NOT GLOB '*[^0-9]*'),
      tipo_contribuyente TEXT NOT NULL
                         CHECK (tipo_contribuyente IN ('natural','sociedad','publica')),
      cedula             TEXT UNIQUE
                         CHECK (cedula IS NULL OR (length(cedula) = 10 AND cedula NOT GLOB '*[^0-9]*')),
      carpeta            TEXT NOT NULL UNIQUE,
      nombre             TEXT NOT NULL CHECK (length(trim(nombre)) > 0),
      activo             INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
      creado_en          TEXT NOT NULL,
      actualizado_en     TEXT NOT NULL,
      CHECK ((tipo_contribuyente = 'natural') = (cedula IS NOT NULL)),
      CHECK (carpeta = coalesce(cedula, ruc))
    );

    CREATE TABLE llaves (
      version      INTEGER PRIMARY KEY CHECK (version >= 1),
      verificador  BLOB NOT NULL CHECK (length(verificador) = 32),
      creada_en    TEXT NOT NULL
    );

    CREATE TABLE credenciales (
      id               INTEGER PRIMARY KEY,
      id_cliente       INTEGER NOT NULL REFERENCES clientes(id),
      portal           TEXT NOT NULL DEFAULT 'sri_en_linea' CHECK (portal IN ('sri_en_linea')),
      usuario          TEXT NOT NULL,
      clave_cifrada    BLOB NOT NULL,
      nonce            BLOB NOT NULL CHECK (length(nonce) = 12),
      version_llave    INTEGER NOT NULL REFERENCES llaves(version),
      actualizado_en   TEXT NOT NULL,
      UNIQUE (id_cliente, portal)
    );

    CREATE TABLE bitacora (
      id          INTEGER PRIMARY KEY,
      id_cliente  INTEGER REFERENCES clientes(id),
      accion      TEXT NOT NULL,
      detalle     TEXT,
      ocurrido_en TEXT NOT NULL
    );

    CREATE INDEX bitacora_cliente ON bitacora (id_cliente, ocurrido_en);
    """,
]

VERSION_ESQUEMA = len(MIGRACIONES)


class EsquemaMasNuevo(RuntimeError):
    """La base la creó una versión más nueva de la app."""


def ahora_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ruta_por_defecto() -> Path:
    from . import plataforma

    return plataforma.datos_dir() / NOMBRE_DB


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    """Abre la base (la crea y migra si hace falta)."""
    ruta = Path(ruta) if ruta else ruta_por_defecto()
    nueva = not ruta.exists()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: las transacciones se abren a mano con transaccion().
    cx = sqlite3.connect(str(ruta), isolation_level=None, timeout=10)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    cx.execute("PRAGMA journal_mode = WAL")
    cx.execute("PRAGMA busy_timeout = 10000")
    try:
        migrar(cx)
    except BaseException:
        cx.close()
        raise
    if nueva:
        from . import plataforma

        if not plataforma.ES_WINDOWS:
            plataforma.restringir_permisos(ruta)
    return cx


@contextmanager
def abrir(ruta: Path | None = None) -> Iterator[sqlite3.Connection]:
    cx = conectar(ruta)
    try:
        yield cx
    finally:
        cx.close()


@contextmanager
def transaccion(cx: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """``BEGIN IMMEDIATE`` … ``COMMIT``; ``ROLLBACK`` si algo falla."""
    cx.execute("BEGIN IMMEDIATE")
    try:
        yield cx
    except BaseException:
        cx.execute("ROLLBACK")
        raise
    else:
        cx.execute("COMMIT")


def version_esquema(cx: sqlite3.Connection) -> int:
    return int(cx.execute("PRAGMA user_version").fetchone()[0])


def migrar(cx: sqlite3.Connection) -> None:
    actual = version_esquema(cx)
    if actual > VERSION_ESQUEMA:
        raise EsquemaMasNuevo(
            f"La base de datos es de una versión más nueva de la app (esquema {actual}). "
            "Actualice Comprobantes SRI."
        )
    for version in range(actual, VERSION_ESQUEMA):
        # executescript hace COMMIT implícito, así que se usa una transacción
        # explícita sentencia a sentencia para que la migración sea atómica.
        with transaccion(cx):
            for sentencia in _sentencias(MIGRACIONES[version]):
                cx.execute(sentencia)
            cx.execute(f"PRAGMA user_version = {version + 1}")


def _sentencias(script: str) -> list[str]:
    partes, actual = [], ""
    for linea in script.splitlines(keepends=True):
        actual += linea
        if sqlite3.complete_statement(actual):
            if actual.strip():
                partes.append(actual.strip())
            actual = ""
    if actual.strip():
        partes.append(actual.strip())
    return partes


def registrar(
    cx: sqlite3.Connection, accion: str, id_cliente: int | None = None, detalle: str | None = None
) -> None:
    """Anota un evento en la bitácora. ``detalle`` NUNCA debe contener claves."""
    cx.execute(
        "INSERT INTO bitacora (id_cliente, accion, detalle, ocurrido_en) VALUES (?, ?, ?, ?)",
        (id_cliente, accion, detalle, ahora_iso()),
    )


def respaldar(destino: Path, origen: Path | None = None) -> None:
    """Copia consistente de la base (API ``backup`` de SQLite)."""
    with abrir(origen) as cx:
        dst = sqlite3.connect(str(destino))
        try:
            cx.backup(dst)
        finally:
            dst.close()
