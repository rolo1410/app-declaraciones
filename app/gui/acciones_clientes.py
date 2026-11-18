"""Acciones sobre clientes y datos de la app, sin interfaz propia.

Las usan la ficha del cliente (página Clientes), el menú «Clientes» y la página
Configuración: alta, edición, clave del SRI, activar/desactivar, carpetas,
ruta base, llave maestra (copia de emergencia y respaldo) e importación de la
clave heredada del ``.env``.

Los diálogos se abren sobre ``padre`` (cualquier widget de la ventana).
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from tkinter import filedialog, messagebox

from ..core import cifrado, clientes, db, plataforma, preferencias
from ..core import ruc as ruc_mod
from . import dialogos
from .contexto import ContextoCliente

TITULO = "Clientes"


class AccionesClientes:
    def __init__(self, padre, contexto: ContextoCliente) -> None:
        self.padre = padre
        self.contexto = contexto
        self.registro = contexto.registro
        # Avisos para refrescar vistas que no escuchan al contexto (p. ej. la llave).
        self.al_cambiar_datos = []

    def _avisar(self) -> None:
        for fn in list(self.al_cambiar_datos):
            fn()

    def _error(self, e: Exception) -> None:
        messagebox.showerror(TITULO, str(e))

    def nuevo(self, ruc: str = "", clave: str = "") -> clientes.Cliente | None:
        datos = dialogos.pedir_cliente_nuevo(self.padre, ruc, clave)
        if not datos:
            return None
        primera_vez = self._estado_llave_seguro() == "sin_configurar"
        try:
            c = self.registro.crear_cliente(*datos[:3], correo=datos[3])
        except (ruc_mod.RucInvalido, clientes.ErrorClientes, cifrado.ErrorCifrado) as e:
            self._error(e)
            return None
        except OSError as e:
            messagebox.showerror(TITULO, f"No se pudo crear la carpeta del cliente:\n{e}")
            return None
        self.contexto.lista_cambio()
        if c.advertencias:
            messagebox.showwarning(TITULO, "\n".join(c.advertencias))
        self.contexto.fijar(c)
        if primera_vez:
            if messagebox.askyesno(
                TITULO,
                "Se creó la llave maestra que protege las claves de los clientes.\n\n"
                "Sin ella (o sin una copia) las claves se pierden si el equipo falla o se "
                "reinstala. ¿Exportar ahora la copia de emergencia?",
            ):
                self.exportar_copia()
        return c

    def _estado_llave_seguro(self) -> str:
        try:
            return self.registro.estado_llave()
        except Exception:  # noqa: BLE001
            return "desconocido"

    def cambiar_clave(self, c: clientes.Cliente) -> None:
        if c:
            cambiar_clave_de(self.padre, self.contexto, c)

    def editar(self, c: clientes.Cliente, enfocar_correo: bool = False) -> bool:
        """Nombre y correo del cliente. True si se guardó algún cambio."""
        if not c:
            return False
        datos = dialogos.pedir_datos_cliente(self.padre, c, enfocar_correo)
        if not datos:
            return False
        nombre, correo = datos
        try:
            if nombre != c.nombre:
                self.registro.renombrar(c.id, nombre)
            if correo != c.correo:
                self.registro.fijar_correo(c.id, correo)
        except clientes.ErrorClientes as e:
            self._error(e)
            return False
        self.contexto.lista_cambio()
        return True

    def alternar_activo(self, c: clientes.Cliente) -> None:
        if not c:
            return
        if c.activo and not messagebox.askyesno(
            TITULO, f"¿Desactivar a {c.nombre}?\n\nSus archivos y su historial se conservan; "
                    "puede reactivarlo cuando quiera."):
            return
        self.registro.fijar_activo(c.id, not c.activo)
        self.contexto.lista_cambio()

    def abrir_carpeta(self, c: clientes.Cliente) -> None:
        if c:
            try:
                self._abrir(self.registro.asegurar_carpeta(c))
            except OSError as e:
                self._error(e)

    def abrir_base(self) -> None:
        self._abrir(self.registro.base)

    def _abrir(self, ruta: Path) -> None:
        try:
            Path(ruta).mkdir(parents=True, exist_ok=True)
            plataforma.abrir_en_explorador(ruta)
        except OSError as e:
            self._error(e)

    def cambiar_base(self) -> None:  # noqa: C901
        carpeta = filedialog.askdirectory(title="Ruta base de los archivos de clientes",
                                          initialdir=str(self.registro.base.parent))
        if not carpeta:
            return
        nueva = Path(carpeta).resolve()
        nube = plataforma.carpeta_en_nube(nueva)
        if nube and not messagebox.askyesno(
            TITULO, f"La carpeta elegida está dentro de {nube}: los comprobantes de sus "
                    "clientes se subirán a la nube.\n\n¿Usarla de todas formas?"):
            return
        anterior = self.registro.base
        if (plataforma.carpeta_clientes(anterior)).exists() and nueva != anterior:
            messagebox.showinfo(
                TITULO, "Los archivos que ya están en la ruta anterior no se mueven:\n"
                        f"{plataforma.carpeta_clientes(anterior)}\n\n"
                        "Si quiere conservarlos en la nueva ruta, mueva esa carpeta «clientes» "
                        "a la nueva ubicación con la app cerrada.")
        try:
            plataforma.fijar_base_path(str(nueva))
            for c in self.registro.listar(incluir_inactivos=False):
                self.registro.asegurar_carpeta(c)
        except OSError as e:
            self._error(e)
        self.contexto.lista_cambio()
        self._avisar()

    def exportar_copia(self) -> None:
        frase = dialogos.pedir_frase(
            self, "Copia de emergencia",
            "La copia de la llave maestra se cifra con una frase de paso. Guarde el archivo "
            "FUERA de este equipo (memoria USB, gestor de contraseñas…) y anote la frase "
            "por separado.", confirmar=True)
        if not frase:
            return
        try:
            datos = self.registro.exportar_copia(frase)
        except (cifrado.ErrorCifrado, ValueError) as e:
            self._error(e)
            return
        ruta = filedialog.asksaveasfilename(
            title="Guardar copia de emergencia", defaultextension=cifrado.EXTENSION_COPIA,
            initialfile=f"ComprobantesSRI-{datetime.now():%Y%m%d}{cifrado.EXTENSION_COPIA}",
            filetypes=[("Copia de emergencia", f"*{cifrado.EXTENSION_COPIA}")])
        if not ruta:
            return
        try:
            plataforma.escribir_atomico(Path(ruta), datos)
        except OSError as e:
            self._error(e)
            return
        messagebox.showinfo(TITULO, f"Copia de emergencia guardada en:\n{ruta}\n\n"
                                    "Muévala fuera de este equipo.")

    def restaurar_copia(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Restaurar llave desde la copia de emergencia",
            filetypes=[("Copia de emergencia", f"*{cifrado.EXTENSION_COPIA}"), ("Todos", "*.*")])
        if not ruta:
            return
        frase = dialogos.pedir_frase(self.padre, "Restaurar llave",
                                     "Escriba la frase de paso de la copia.", confirmar=False)
        if not frase:
            return
        try:
            version = self.registro.restaurar_copia(Path(ruta).read_bytes(), frase)
        except (cifrado.ErrorCifrado, OSError) as e:
            self._error(e)
            return
        self._avisar()
        self.contexto.lista_cambio()
        messagebox.showinfo(TITULO, f"Llave maestra restaurada (versión {version}).")

    def respaldo_completo(self) -> None:
        carpeta = filedialog.askdirectory(
            title="Carpeta donde guardar el respaldo (base de clientes + copia de la llave)")
        if not carpeta:
            return
        frase = dialogos.pedir_frase(
            self, "Respaldo completo",
            "El respaldo incluye la base de clientes y la copia de la llave cifrada con esta "
            "frase. Ninguno de los dos sirve sin el otro.", confirmar=True)
        if not frase:
            return
        destino = Path(carpeta) / f"ComprobantesSRI-respaldo-{datetime.now():%Y%m%d-%H%M}"
        try:
            destino.mkdir(parents=True, exist_ok=False)
            copia = self.registro.exportar_copia(frase)
            db.respaldar(destino / db.NOMBRE_DB)
            plataforma.escribir_atomico(destino / f"llave{cifrado.EXTENSION_COPIA}", copia)
            plataforma.restringir_permisos(destino)
        except (OSError, cifrado.ErrorCifrado, ValueError) as e:
            self._error(e)
            return
        messagebox.showinfo(TITULO, f"Respaldo guardado en:\n{destino}")

    def importar_env(self) -> None:
        heredada = preferencias.clave_heredada()
        if not heredada:
            return
        ruc, clave = heredada["ruc"], heredada["clave"]
        existente = None
        try:
            existente = self.registro.por_identificacion(ruc) if ruc else None
        except Exception:  # noqa: BLE001
            pass
        if existente is not None:
            if not messagebox.askyesno(
                TITULO, f"{existente.nombre} ({existente.ruc}) ya está registrado.\n"
                        "¿Reemplazar su clave por la del .env?"):
                return
            try:
                self.registro.cambiar_clave(existente.id, clave)
            except (clientes.ErrorClientes, cifrado.ErrorCifrado) as e:
                self._error(e)
                return
            self.contexto.lista_cambio()
        elif self.nuevo(ruc=ruc, clave=clave) is None:
            return
        self._quitar_clave_del_env(heredada["origen"])
        self._avisar()

    def _quitar_clave_del_env(self, origen: str) -> None:
        if origen == "entorno" or not origen or not os.path.isfile(origen):
            messagebox.showinfo(
                TITULO, "Clave importada y cifrada.\n\nQuite la variable de entorno SRI_CLAVE "
                        "de la configuración de su sistema: ya no es necesaria.")
            return
        if messagebox.askyesno(
            TITULO, f"Clave importada y cifrada.\n\n¿Quitar ahora la línea SRI_CLAVE de\n{origen}?\n"
                    "(El resto del archivo no se modifica.)"):
            try:
                preferencias.quitar_variable(origen, "SRI_CLAVE")
            except OSError as e:
                self._error(e)
        else:
            messagebox.showwarning(
                TITULO, f"Recuerde borrar SRI_CLAVE de {origen}: sigue en texto plano.")


def cambiar_clave_de(padre, contexto: ContextoCliente, c: clientes.Cliente) -> bool:
    """Pide y guarda una clave nueva para ``c``. True si se cambió."""
    clave = dialogos.pedir_clave(
        padre, "Cambiar clave",
        f"Nueva clave de SRI en línea para {c.nombre} ({c.ruc}).\n"
        "La clave anterior se reemplaza y no se puede recuperar.")
    if not clave:
        return False
    try:
        contexto.registro.cambiar_clave(c.id, clave)
    except (clientes.ErrorClientes, cifrado.ErrorCifrado) as e:
        messagebox.showerror(TITULO, str(e))
        return False
    contexto.lista_cambio()
    messagebox.showinfo(TITULO, "Clave actualizada.")
    return True
