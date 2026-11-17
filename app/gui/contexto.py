"""Cliente activo compartido por todas las pestañas.

La ventana principal crea un único ``ContextoCliente``; las pestañas se
suscriben para enterarse de cuándo cambia el cliente seleccionado o la lista de
clientes. Con ``cliente is None`` la app trabaja como antes («sin cliente
registrado»): RUC, clave y carpeta se escriben a mano.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Callable

from ..core import cifrado, clientes, plataforma
from ..core.clientes import Cliente

Oyente = Callable[[], None]


class ContextoCliente:
    def __init__(self, raiz) -> None:
        self.raiz = raiz
        real, self.nombre_backend = cifrado.backend_real()
        # Sin almacén del sistema (Linux sin Secret Service) la llave se guarda
        # cifrada con una frase de paso que se pide al primer uso.
        self.sin_almacen = not real
        llavero = (
            cifrado.LlaveroSistema() if real
            else cifrado.LlaveroArchivo(plataforma.datos_dir(), self._pedir_frase)
        )
        self.registro = clientes.Registro(llavero=llavero)
        self.cliente: Cliente | None = None
        self._oyentes_cliente: list[Oyente] = []
        self._oyentes_lista: list[Oyente] = []

    # -- suscripciones ------------------------------------------------------------

    def al_cambiar_cliente(self, fn: Oyente) -> None:
        self._oyentes_cliente.append(fn)

    def al_cambiar_lista(self, fn: Oyente) -> None:
        self._oyentes_lista.append(fn)

    def fijar(self, cliente: Cliente | None) -> None:
        self.cliente = cliente
        try:
            config = plataforma.leer_config()
            config["ultimo_cliente"] = cliente.ruc if cliente else ""
            plataforma.guardar_config(config)
        except OSError:
            pass  # recordar el último cliente es solo una comodidad
        for fn in list(self._oyentes_cliente):
            fn()

    def lista_cambio(self) -> None:
        """Avisar tras un alta, edición o desactivación."""
        if self.cliente is not None:
            try:
                self.cliente = self.registro.obtener(self.cliente.id)
            except clientes.ErrorClientes:
                self.cliente = None
            if self.cliente is not None and not self.cliente.activo:
                self.fijar(None)
        for fn in list(self._oyentes_lista):
            fn()

    def ultimo_cliente(self) -> Cliente | None:
        ruc = str(plataforma.leer_config().get("ultimo_cliente", "")).strip()
        if not ruc:
            return None
        try:
            c = self.registro.por_identificacion(ruc)
        except Exception:  # noqa: BLE001 - base ilegible: se empieza sin cliente
            return None
        return c if c and c.activo else None

    # -- rutas del cliente activo -------------------------------------------------

    def carpeta_resultados(self, periodo: str | None = None) -> Path | None:
        """``…/resultados/<AAAA-MM>`` del cliente activo (creada), o None."""
        if self.cliente is None:
            return None
        try:
            self.registro.asegurar_carpeta(self.cliente)
            carpeta = self.registro.carpeta_resultados(self.cliente, periodo or None)
            carpeta.mkdir(parents=True, exist_ok=True)
            return carpeta
        except OSError:
            return None

    def carpeta_descargas(self) -> Path | None:
        if self.cliente is None:
            return None
        try:
            return self.registro.asegurar_carpeta(self.cliente) / "descargas"
        except OSError:
            return None

    def registrar(self, accion: str, ruta: str | Path | None = None, detalle: str = "") -> None:
        """Anota en la bitácora del cliente activo (rutas relativas a la base)."""
        if self.cliente is None:
            return
        partes = []
        if ruta:
            ruta = Path(ruta)
            try:
                partes.append(ruta.resolve().relative_to(self.registro.base).as_posix())
            except ValueError:
                partes.append(ruta.name)
        if detalle:
            partes.append(detalle)
        try:
            self.registro.registrar_evento(accion, self.cliente.id, " · ".join(partes) or None)
        except Exception:  # noqa: BLE001 - la bitácora nunca debe impedir el trabajo
            pass

    # -- frase de paso (sin almacén del sistema) ----------------------------------

    def _pedir_frase(self, nueva: bool) -> str | None:
        from .dialogos import pedir_frase

        if nueva:
            titulo = "Crear frase de paso"
            texto = ("Este equipo no tiene un almacén de credenciales disponible "
                     "(p. ej. GNOME Keyring).\nLas claves de los clientes se protegerán "
                     "con una frase de paso que se pedirá cada vez que abra la app.")
        else:
            titulo = "Frase de paso"
            texto = "Escriba la frase de paso que protege las claves de los clientes."
        return pedir_frase(self.raiz, titulo, texto, confirmar=nueva)


def periodo_mayoritario(fechas) -> str | None:
    """``AAAA-MM`` más frecuente entre las fechas dadas (ignora ``None``)."""
    conteo = Counter(f"{f.year:04d}-{f.month:02d}" for f in fechas if f)
    return conteo.most_common(1)[0][0] if conteo else None

