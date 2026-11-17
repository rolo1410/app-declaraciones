"""Registro de clientes: alta, edición, claves cifradas y carpeta por cliente.

Cada cliente tiene su carpeta en ``<ruta base>/clientes/<carpeta>/`` con
``descargas/`` y ``resultados/``; ``<carpeta>`` es la cédula (persona natural)
o el RUC (sociedad / entidad pública), según ``ruc.carpeta_de``.

El alta es todo o nada: si no se puede crear la carpeta, el registro se deshace
(y si la carpeta la creó este alta, se elimina).

La clave del SRI se descifra solo cuando se pide con ``clave_de()``, justo antes
del login, y nunca se escribe en la bitácora ni en mensajes de error.
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import cifrado, db, plataforma
from . import ruc as ruc_mod

PORTAL_SRI = "sri_en_linea"
SUBCARPETAS = ("descargas", "resultados")


class ErrorClientes(Exception):
    """Error de negocio con mensaje apto para el usuario."""


class ClienteDuplicado(ErrorClientes):
    pass


class ClienteNoEncontrado(ErrorClientes):
    pass


@dataclass(frozen=True)
class Cliente:
    id: int
    ruc: str
    tipo: str
    cedula: str | None
    carpeta: str
    nombre: str
    activo: bool
    creado_en: str
    actualizado_en: str
    advertencias: list[str] = field(default_factory=list, compare=False)

    @property
    def nombre_tipo(self) -> str:
        return ruc_mod.NOMBRES_TIPO[self.tipo]

    @property
    def identificaciones(self) -> set[str]:
        """RUC y, si es persona natural, la cédula."""
        return {self.ruc} | ({self.cedula} if self.cedula else set())

    @classmethod
    def _desde_fila(cls, fila: sqlite3.Row) -> "Cliente":
        return cls(
            id=fila["id"], ruc=fila["ruc"], tipo=fila["tipo_contribuyente"],
            cedula=fila["cedula"], carpeta=fila["carpeta"], nombre=fila["nombre"],
            activo=bool(fila["activo"]), creado_en=fila["creado_en"],
            actualizado_en=fila["actualizado_en"],
        )


class Registro:
    """Acceso a los clientes. Seguro entre hilos: cada operación abre su conexión."""

    def __init__(
        self,
        ruta_db: Path | None = None,
        base: Path | None = None,
        llavero: cifrado.Llavero | None = None,
    ) -> None:
        self._ruta_db = Path(ruta_db) if ruta_db else None
        self._base = Path(base).resolve() if base else None
        self.llavero: cifrado.Llavero = llavero or cifrado.LlaveroSistema()

    # -- rutas ----------------------------------------------------------------

    @property
    def base(self) -> Path:
        return self._base or plataforma.base_path()

    def carpeta_cliente(self, cliente: Cliente) -> Path:
        carpeta = plataforma.carpeta_clientes(self.base) / cliente.carpeta
        if not plataforma.dentro_de(carpeta, self.base):
            raise ErrorClientes("La carpeta del cliente queda fuera de la ruta base.")
        return carpeta

    def carpeta_descargas(self, cliente: Cliente) -> Path:
        return self.carpeta_cliente(cliente) / "descargas"

    def carpeta_resultados(self, cliente: Cliente, periodo: str | None = None) -> Path:
        """``…/resultados`` o ``…/resultados/<AAAA-MM>``."""
        carpeta = self.carpeta_cliente(cliente) / "resultados"
        return carpeta / periodo if periodo else carpeta

    def _abrir(self):
        return db.abrir(self._ruta_db)

    # -- llave maestra ----------------------------------------------------------

    def _llave_actual(self, cx: sqlite3.Connection, crear: bool) -> tuple[int, bytes]:
        """``(version, llave)`` vigente; la crea la primera vez si ``crear``."""
        fila = cx.execute(
            "SELECT version, verificador FROM llaves ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if fila is None:
            if not crear:
                raise cifrado.LlaveNoDisponible("Aún no se ha configurado la llave maestra.")
            llave = self.llavero.leer(1)
            if llave is None:
                llave = cifrado.generar_llave()
                self.llavero.guardar(1, llave)
            cx.execute(
                "INSERT INTO llaves (version, verificador, creada_en) VALUES (1, ?, ?)",
                (cifrado.verificador(llave), db.ahora_iso()),
            )
            db.registrar(cx, "llave_creada", detalle="version=1")
            return 1, llave
        return fila["version"], self._llave_de_version(fila["version"], fila["verificador"])

    def _llave_de_version(self, version: int, verificador: bytes) -> bytes:
        llave = self.llavero.leer(version)
        if llave is None:
            raise cifrado.LlaveNoDisponible(
                "No se encontró la llave maestra en el almacén de credenciales del sistema. "
                "Restaure la copia de emergencia (.llave)."
            )
        cifrado.comprobar_verificador(llave, verificador)
        return llave

    def estado_llave(self) -> str:
        """``'sin_configurar'``, ``'ok'``, ``'falta'`` o ``'no_corresponde'``."""
        with self._abrir() as cx:
            try:
                self._llave_actual(cx, crear=False)
            except cifrado.LlaveNoCorresponde:
                return "no_corresponde"
            except cifrado.LlaveNoDisponible:
                hay = cx.execute("SELECT 1 FROM llaves LIMIT 1").fetchone()
                return "falta" if hay else "sin_configurar"
        return "ok"

    def exportar_copia(self, frase: str) -> bytes:
        """Contenido del archivo ``.llave`` de la llave vigente."""
        with self._abrir() as cx:
            with db.transaccion(cx):
                version, llave = self._llave_actual(cx, crear=True)
                db.registrar(cx, "copia_exportada", detalle=f"version={version}")
        return cifrado.exportar_copia(llave, version, frase)

    def restaurar_copia(self, datos: bytes, frase: str) -> int:
        """Vuelve a guardar en el sistema la llave de una copia de emergencia."""
        version, llave = cifrado.importar_copia(datos, frase)
        with self._abrir() as cx:
            with db.transaccion(cx):
                fila = cx.execute(
                    "SELECT verificador FROM llaves WHERE version = ?", (version,)
                ).fetchone()
                if fila is not None:
                    cifrado.comprobar_verificador(llave, fila["verificador"])
                elif cx.execute("SELECT 1 FROM llaves LIMIT 1").fetchone():
                    raise cifrado.LlaveNoCorresponde(
                        "La copia de emergencia no corresponde a esta base de datos."
                    )
                else:
                    cx.execute(
                        "INSERT INTO llaves (version, verificador, creada_en) VALUES (?, ?, ?)",
                        (version, cifrado.verificador(llave), db.ahora_iso()),
                    )
                self.llavero.guardar(version, llave)
                db.registrar(cx, "llave_restaurada", detalle=f"version={version}")
        return version

    # -- consultas --------------------------------------------------------------

    def listar(self, incluir_inactivos: bool = False, buscar: str = "") -> list[Cliente]:
        sql = "SELECT * FROM clientes WHERE 1 = 1"
        args: list = []
        if not incluir_inactivos:
            sql += " AND activo = 1"
        buscar = (buscar or "").strip()
        if buscar:
            sql += " AND (ruc LIKE ? OR cedula LIKE ? OR nombre LIKE ?)"
            patron = f"%{buscar}%"
            args += [patron, patron, patron]
        sql += " ORDER BY nombre COLLATE NOCASE, ruc"
        with self._abrir() as cx:
            return [Cliente._desde_fila(f) for f in cx.execute(sql, args)]

    def obtener(self, id_cliente: int) -> Cliente:
        with self._abrir() as cx:
            return self._obtener(cx, id_cliente)

    def _obtener(self, cx: sqlite3.Connection, id_cliente: int) -> Cliente:
        fila = cx.execute("SELECT * FROM clientes WHERE id = ?", (id_cliente,)).fetchone()
        if fila is None:
            raise ClienteNoEncontrado("El cliente no existe.")
        return Cliente._desde_fila(fila)

    def por_identificacion(self, identificacion: str) -> Cliente | None:
        """Busca por RUC o por cédula."""
        ident = "".join((identificacion or "").split())
        with self._abrir() as cx:
            fila = cx.execute(
                "SELECT * FROM clientes WHERE ruc = ? OR cedula = ?", (ident, ident)
            ).fetchone()
        return Cliente._desde_fila(fila) if fila else None

    def tiene_clave(self, id_cliente: int) -> bool:
        with self._abrir() as cx:
            return cx.execute(
                "SELECT 1 FROM credenciales WHERE id_cliente = ? AND portal = ?",
                (id_cliente, PORTAL_SRI),
            ).fetchone() is not None

    # -- alta y edición -------------------------------------------------------------

    def crear_cliente(self, ruc: str, nombre: str, clave: str) -> Cliente:
        """Registra el cliente, cifra su clave y crea su carpeta (todo o nada)."""
        info = ruc_mod.analizar(ruc)  # lanza RucInvalido
        nombre = " ".join((nombre or "").split())
        if not nombre:
            raise ErrorClientes("El nombre o razón social es obligatorio.")
        if not clave:
            raise ErrorClientes("La clave de SRI en línea es obligatoria.")

        carpeta = plataforma.carpeta_clientes(self.base) / info.carpeta
        if not plataforma.dentro_de(carpeta, self.base):
            raise ErrorClientes("La carpeta del cliente queda fuera de la ruta base.")

        nueva = not carpeta.exists()
        ahora = db.ahora_iso()
        try:
            with self._abrir() as cx, db.transaccion(cx):
                if cx.execute(
                    "SELECT 1 FROM clientes WHERE ruc = ?", (info.ruc,)
                ).fetchone():
                    raise ClienteDuplicado(f"El RUC {info.ruc} ya está registrado.")
                cur = cx.execute(
                    "INSERT INTO clientes (ruc, tipo_contribuyente, cedula, carpeta, nombre,"
                    " activo, creado_en, actualizado_en) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                    (info.ruc, info.tipo, info.cedula, info.carpeta, nombre, ahora, ahora),
                )
                id_cliente = int(cur.lastrowid)
                self._guardar_clave(cx, id_cliente, info.ruc, clave)
                db.registrar(cx, "cliente_creado", id_cliente, f"carpeta=clientes/{info.carpeta}")
                for sub in SUBCARPETAS:
                    (carpeta / sub).mkdir(parents=True, exist_ok=True)
                plataforma.restringir_permisos(carpeta)
                cliente = self._obtener(cx, id_cliente)
        except BaseException:
            if nueva:
                shutil.rmtree(carpeta, ignore_errors=True)
            raise
        return replace(cliente, advertencias=list(info.advertencias))

    def _guardar_clave(self, cx: sqlite3.Connection, id_cliente: int, ruc: str, clave: str) -> None:
        version, llave = self._llave_actual(cx, crear=True)
        nonce, cifrada = cifrado.cifrar(llave, version, clave, ruc, PORTAL_SRI)
        cx.execute(
            "INSERT INTO credenciales (id_cliente, portal, usuario, clave_cifrada, nonce,"
            " version_llave, actualizado_en) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id_cliente, portal) DO UPDATE SET usuario = excluded.usuario,"
            " clave_cifrada = excluded.clave_cifrada, nonce = excluded.nonce,"
            " version_llave = excluded.version_llave, actualizado_en = excluded.actualizado_en",
            (id_cliente, PORTAL_SRI, ruc, cifrada, nonce, version, db.ahora_iso()),
        )

    def cambiar_clave(self, id_cliente: int, clave: str) -> None:
        if not clave:
            raise ErrorClientes("La clave de SRI en línea es obligatoria.")
        with self._abrir() as cx, db.transaccion(cx):
            cliente = self._obtener(cx, id_cliente)
            self._guardar_clave(cx, cliente.id, cliente.ruc, clave)
            self._tocar(cx, cliente.id)
            db.registrar(cx, "clave_actualizada", cliente.id)

    def clave_de(self, id_cliente: int) -> str:
        """Descifra la clave del SRI del cliente (solo en memoria, justo antes del login)."""
        with self._abrir() as cx:
            cliente = self._obtener(cx, id_cliente)
            fila = cx.execute(
                "SELECT c.clave_cifrada, c.nonce, c.version_llave, l.verificador"
                " FROM credenciales c JOIN llaves l ON l.version = c.version_llave"
                " WHERE c.id_cliente = ? AND c.portal = ?",
                (id_cliente, PORTAL_SRI),
            ).fetchone()
            if fila is None:
                raise ErrorClientes(f"El cliente {cliente.ruc} no tiene clave registrada.")
            llave = self._llave_de_version(fila["version_llave"], fila["verificador"])
            return cifrado.descifrar(
                llave, fila["version_llave"], fila["nonce"], fila["clave_cifrada"],
                cliente.ruc, PORTAL_SRI,
            )

    def renombrar(self, id_cliente: int, nombre: str) -> None:
        nombre = " ".join((nombre or "").split())
        if not nombre:
            raise ErrorClientes("El nombre o razón social es obligatorio.")
        with self._abrir() as cx, db.transaccion(cx):
            self._obtener(cx, id_cliente)
            cx.execute("UPDATE clientes SET nombre = ? WHERE id = ?", (nombre, id_cliente))
            self._tocar(cx, id_cliente)
            db.registrar(cx, "nombre_actualizado", id_cliente)

    def fijar_activo(self, id_cliente: int, activo: bool) -> None:
        """Desactiva o reactiva un cliente (nunca se borra: quedan archivos y bitácora)."""
        with self._abrir() as cx, db.transaccion(cx):
            self._obtener(cx, id_cliente)
            cx.execute("UPDATE clientes SET activo = ? WHERE id = ?", (int(activo), id_cliente))
            self._tocar(cx, id_cliente)
            db.registrar(cx, "cliente_reactivado" if activo else "cliente_desactivado", id_cliente)

    def asegurar_carpeta(self, cliente: Cliente) -> Path:
        """Vuelve a crear la carpeta del cliente si se borró o cambió la ruta base."""
        carpeta = self.carpeta_cliente(cliente)
        for sub in SUBCARPETAS:
            (carpeta / sub).mkdir(parents=True, exist_ok=True)
        plataforma.restringir_permisos(carpeta)
        return carpeta

    def registrar_evento(self, accion: str, id_cliente: int | None = None, detalle: str | None = None) -> None:
        """Anota en la bitácora (descargas, exportaciones…). Nunca pasar claves."""
        with self._abrir() as cx, db.transaccion(cx):
            db.registrar(cx, accion, id_cliente, detalle)

    @staticmethod
    def _tocar(cx: sqlite3.Connection, id_cliente: int) -> None:
        cx.execute(
            "UPDATE clientes SET actualizado_en = ? WHERE id = ?", (db.ahora_iso(), id_cliente)
        )
