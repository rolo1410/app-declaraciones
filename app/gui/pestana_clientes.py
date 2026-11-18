"""Pestaña «Clientes»: registro de contribuyentes, claves cifradas y carpetas.

Permite dar de alta clientes (RUC, nombre y clave de SRI en línea), reemplazar
la clave (nunca mostrarla), desactivar, abrir su carpeta, configurar la ruta
base, y exportar/restaurar la copia de emergencia de la llave maestra.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, font, messagebox, ttk

from ..core import cifrado, clientes, db, plataforma, preferencias
from ..core import ruc as ruc_mod
from . import dialogos
from .contexto import ContextoCliente

TITULO = "Clientes"

_ESTADOS_LLAVE = {
    "sin_configurar": ("Aún no hay llave maestra: se crea al registrar el primer cliente.", "gray"),
    "ok": ("Llave maestra disponible.", "#1e8449"),
    "falta": ("No se encuentra la llave maestra en este equipo: restaure la copia de "
              "emergencia (.llave).", "#c0392b"),
    "no_corresponde": ("La llave de este equipo no corresponde a la base de clientes: "
                       "restaure la copia de emergencia (.llave).", "#c0392b"),
}


class PestanaClientes(ttk.Frame):
    def __init__(self, master, contexto: ContextoCliente) -> None:
        super().__init__(master, padding=10)
        self.contexto = contexto
        self.registro = contexto.registro
        self._por_iid: dict[str, clientes.Cliente] = {}
        self._construir()
        contexto.al_cambiar_lista(self.refrescar)
        contexto.al_cambiar_cliente(self._marcar_activo)
        self.refrescar()
        self.after(400, self._ofrecer_importar_env)

    # ----------------------------------------------------------------- interfaz
    def _construir(self) -> None:
        pad = {"padx": 6, "pady": 4}

        barra = ttk.Frame(self)
        barra.pack(fill="x", **pad)
        ttk.Label(barra, text="Buscar:").pack(side="left")
        self.var_buscar = tk.StringVar()
        ent = ttk.Entry(barra, textvariable=self.var_buscar, width=28)
        ent.pack(side="left", padx=6)
        self.var_buscar.trace_add("write", lambda *_: self.refrescar())
        self.var_inactivos = tk.BooleanVar(value=False)
        ttk.Checkbutton(barra, text="Mostrar desactivados", variable=self.var_inactivos,
                        command=self.refrescar).pack(side="left", padx=8)
        ttk.Button(barra, text="Nuevo cliente…", command=self.nuevo).pack(side="right")

        self.banner_env = ttk.Frame(self)  # se muestra si hay SRI_CLAVE en .env

        marco = ttk.Frame(self)
        marco.pack(fill="both", expand=True, **pad)
        columnas = (("ruc", "RUC", 130), ("nombre", "Nombre / razón social", 320),
                    ("tipo", "Tipo", 120), ("carpeta", "Carpeta", 130), ("estado", "Estado", 90))
        self.tabla = ttk.Treeview(marco, columns=[c[0] for c in columnas], show="headings",
                                  selectmode="browse")
        for clave, titulo, ancho in columnas:
            self.tabla.heading(clave, text=titulo)
            self.tabla.column(clave, width=ancho, stretch=(clave == "nombre"))
        self.tabla.tag_configure("inactivo", foreground="gray")
        negrita = font.nametofont("TkDefaultFont").copy()
        negrita.configure(weight="bold")
        self._negrita = negrita  # evitar que el recolector libere la fuente
        self.tabla.tag_configure("activo_global", font=negrita)
        scroll = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=scroll.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tabla.bind("<Double-1>", lambda _e: self.usar())
        self.tabla.bind("<<TreeviewSelect>>", lambda _e: self._actualizar_botones())

        acciones = ttk.Frame(self)
        acciones.pack(fill="x", **pad)
        self.btn_usar = ttk.Button(acciones, text="Usar este cliente", command=self.usar)
        self.btn_clave = ttk.Button(acciones, text="Cambiar clave…", command=self.cambiar_clave)
        self.btn_nombre = ttk.Button(acciones, text="Renombrar…", command=self.renombrar)
        self.btn_activo = ttk.Button(acciones, text="Desactivar", command=self.alternar_activo)
        self.btn_carpeta = ttk.Button(acciones, text="Abrir carpeta", command=self.abrir_carpeta)
        for b in (self.btn_usar, self.btn_clave, self.btn_nombre, self.btn_activo, self.btn_carpeta):
            b.pack(side="left", padx=(0, 6))

        # --- Ruta base ---
        frm_base = ttk.LabelFrame(self, text="Ruta base de los archivos", padding=8)
        frm_base.pack(fill="x", **pad)
        self.var_base = tk.StringVar()
        ttk.Entry(frm_base, textvariable=self.var_base, state="readonly").pack(
            side="left", fill="x", expand=True)
        ttk.Button(frm_base, text="Cambiar…", command=self.cambiar_base).pack(side="left", padx=6)
        ttk.Button(frm_base, text="Abrir", command=self.abrir_base).pack(side="left")
        self.lbl_nube = ttk.Label(self, text="", foreground="#b9770e", wraplength=900,
                                  justify="left")
        self.lbl_nube.pack(fill="x", padx=12)

        # --- Llave maestra ---
        frm_llave = ttk.LabelFrame(self, text="Llave maestra y respaldo", padding=8)
        frm_llave.pack(fill="x", **pad)
        self.lbl_llave = ttk.Label(frm_llave, text="", wraplength=520, justify="left")
        self.lbl_llave.pack(side="left", fill="x", expand=True)
        ttk.Button(frm_llave, text="Respaldo completo…", command=self.respaldo_completo).pack(
            side="right")
        ttk.Button(frm_llave, text="Restaurar llave…", command=self.restaurar_copia).pack(
            side="right", padx=6)
        ttk.Button(frm_llave, text="Exportar copia de emergencia…",
                   command=self.exportar_copia).pack(side="right")

    # ------------------------------------------------------------------ datos
    def refrescar(self) -> None:
        seleccion = self._seleccionado()
        self.tabla.delete(*self.tabla.get_children())
        self._por_iid.clear()
        try:
            lista = self.registro.listar(self.var_inactivos.get(), self.var_buscar.get())
        except Exception as e:  # noqa: BLE001
            lista = []
            messagebox.showerror(TITULO, f"No se pudo leer la base de clientes:\n{e}")
        for c in lista:
            iid = str(c.id)
            self._por_iid[iid] = c
            self.tabla.insert("", "end", iid=iid, values=(
                c.ruc, c.nombre, c.nombre_tipo, c.carpeta, "Activo" if c.activo else "Desactivado"))
        if seleccion and str(seleccion.id) in self._por_iid:
            self.tabla.selection_set(str(seleccion.id))
        self._marcar_activo()
        self._actualizar_base()
        self._actualizar_llave()
        self._actualizar_botones()

    def _marcar_activo(self) -> None:
        activo = self.contexto.cliente
        for iid, c in self._por_iid.items():
            tags = []
            if not c.activo:
                tags.append("inactivo")
            if activo is not None and c.id == activo.id:
                tags.append("activo_global")
            self.tabla.item(iid, tags=tags)

    def _actualizar_base(self) -> None:
        base = self.registro.base
        self.var_base.set(str(base))
        nube = plataforma.carpeta_en_nube(base)
        self.lbl_nube.configure(text=(
            f"⚠ La ruta base está dentro de {nube}. Son datos personales y tributarios de "
            "terceros (LOPDP): se copiarán a la nube. Se recomienda una carpeta local."
        ) if nube else "")

    def _actualizar_llave(self) -> None:
        try:
            estado = self.registro.estado_llave()
        except cifrado.ErrorCifrado as e:
            self.lbl_llave.configure(text=str(e), foreground="#c0392b")
            return
        except Exception as e:  # noqa: BLE001
            self.lbl_llave.configure(text=f"No se pudo comprobar la llave: {e}",
                                     foreground="#c0392b")
            return
        texto, color = _ESTADOS_LLAVE[estado]
        if self.contexto.sin_almacen:
            texto += " (sin almacén del sistema: protegida con frase de paso)"
        self.lbl_llave.configure(text=texto, foreground=color)

    def _seleccionado(self) -> clientes.Cliente | None:
        sel = self.tabla.selection() if hasattr(self, "tabla") else ()
        return self._por_iid.get(sel[0]) if sel else None

    def _actualizar_botones(self) -> None:
        c = self._seleccionado()
        estado = "normal" if c else "disabled"
        for b in (self.btn_clave, self.btn_nombre, self.btn_activo, self.btn_carpeta):
            b.configure(state=estado)
        self.btn_usar.configure(state="normal" if c and c.activo else "disabled")
        self.btn_activo.configure(text="Reactivar" if c and not c.activo else "Desactivar")

    # --------------------------------------------------------------- acciones
    def _error(self, e: Exception) -> None:
        messagebox.showerror(TITULO, str(e))

    def nuevo(self, ruc: str = "", clave: str = "") -> clientes.Cliente | None:
        datos = dialogos.pedir_cliente_nuevo(self, ruc, clave)
        if not datos:
            return None
        primera_vez = self._estado_llave_seguro() == "sin_configurar"
        try:
            c = self.registro.crear_cliente(*datos)
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

    def usar(self) -> None:
        c = self._seleccionado()
        if c and c.activo:
            self.contexto.fijar(c)

    def cambiar_clave(self, c: clientes.Cliente | None = None) -> None:
        c = c or self._seleccionado()
        if c:
            cambiar_clave_de(self, self.contexto, c)

    def renombrar(self, c: clientes.Cliente | None = None) -> None:
        c = c or self._seleccionado()
        if not c:
            return
        nombre = dialogos.pedir_texto(self, "Renombrar cliente",
                                      f"Nuevo nombre o razón social para {c.ruc}:", c.nombre)
        if not nombre:
            return
        try:
            self.registro.renombrar(c.id, nombre)
        except clientes.ErrorClientes as e:
            self._error(e)
            return
        self.contexto.lista_cambio()

    def alternar_activo(self, c: clientes.Cliente | None = None) -> None:
        c = c or self._seleccionado()
        if not c:
            return
        if c.activo and not messagebox.askyesno(
            TITULO, f"¿Desactivar a {c.nombre}?\n\nSus archivos y su historial se conservan; "
                    "puede reactivarlo cuando quiera."):
            return
        self.registro.fijar_activo(c.id, not c.activo)
        self.contexto.lista_cambio()

    def abrir_carpeta(self, c: clientes.Cliente | None = None) -> None:
        c = c or self._seleccionado()
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

    def cambiar_base(self) -> None:
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
        frase = dialogos.pedir_frase(self, "Restaurar llave",
                                     "Escriba la frase de paso de la copia.", confirmar=False)
        if not frase:
            return
        try:
            version = self.registro.restaurar_copia(Path(ruta).read_bytes(), frase)
        except (cifrado.ErrorCifrado, OSError) as e:
            self._error(e)
            return
        self.refrescar()
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

    # ------------------------------------------------- importación desde .env
    def _ofrecer_importar_env(self) -> None:
        heredada = preferencias.clave_heredada()
        for hijo in self.banner_env.winfo_children():
            hijo.destroy()
        if not heredada:
            self.banner_env.pack_forget()
            return
        origen = "una variable de entorno" if heredada["origen"] == "entorno" else "el archivo .env"
        ttk.Label(
            self.banner_env, foreground="#b9770e", wraplength=760, justify="left",
            text=f"⚠ Hay una clave del SRI en texto plano en {origen} (SRI_CLAVE). "
                 "Impórtela a un cliente para guardarla cifrada.",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(self.banner_env, text="Importar…", command=self.importar_env).pack(side="right")
        self.banner_env.pack(fill="x", padx=6, pady=4, after=self.winfo_children()[0])

    def importar_env(self) -> None:
        heredada = preferencias.clave_heredada()
        if not heredada:
            self._ofrecer_importar_env()
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
        self._ofrecer_importar_env()

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
