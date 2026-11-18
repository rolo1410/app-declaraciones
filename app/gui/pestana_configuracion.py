"""Pestaña «Configuración»: datos de quien declara y correo de envío.

Los datos de quien declara van al pie del PDF («Preparado por») y a la firma
del correo. La contraseña del correo se guarda cifrada con la llave maestra
(como las claves del SRI) y nunca se vuelve a mostrar.
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import cifrado, clientes, correo, perfil
from .contexto import ContextoCliente
from .dialogos import tipos_archivo

TITULO = "Configuración"
ROJO, VERDE, GRIS = "#c0392b", "#1e8449", "gray"
OTRO_PROVEEDOR = "Otro (manual)"
SEGURIDAD_TEXTO = {"ssl": "SSL/TLS", "starttls": "STARTTLS", "ninguna": "Ninguna"}


def _ajustar_ancho(etiqueta: ttk.Label) -> ttk.Label:
    """El texto se reparte en líneas según el ancho real de la etiqueta."""
    etiqueta.bind("<Configure>", lambda e: e.widget.configure(wraplength=max(e.width - 4, 120)))
    return etiqueta


class PestanaConfiguracion(ttk.Frame):
    def __init__(self, master, contexto: ContextoCliente) -> None:
        super().__init__(master, padding=12)
        self.contexto = contexto
        self.registro = contexto.registro
        self.perfil = perfil.leer()
        self._vars: dict[str, tk.Variable] = {}
        self._logo_img = None
        self._probando = False
        self._construir()
        self._cargar()

    # ----------------------------------------------------------------- interfaz
    def _campo(self, marco, fila: int, clave: str, etiqueta: str, ancho: int = 36,
               ayuda: str = "", **opciones) -> ttk.Entry:
        ttk.Label(marco, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=3)
        var = self._vars.setdefault(clave, tk.StringVar())
        entrada = ttk.Entry(marco, textvariable=var, width=ancho, **opciones)
        entrada.grid(row=fila, column=1, sticky="we", padx=(8, 0), pady=3)
        if ayuda:
            ttk.Label(marco, text=ayuda, foreground=GRIS).grid(
                row=fila + 1, column=1, sticky="w", padx=(8, 0))
        return entrada

    def _construir(self) -> None:
        columnas = ttk.Frame(self)
        columnas.pack(fill="both", expand=True)
        columnas.columnconfigure(0, weight=1, uniform="c")
        columnas.columnconfigure(1, weight=1, uniform="c")

        # --- Quien declara -------------------------------------------------------
        d = ttk.LabelFrame(columnas, text="Quien prepara la declaración", padding=12)
        d.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        d.columnconfigure(1, weight=1)
        _ajustar_ancho(ttk.Label(d, foreground=GRIS, wraplength=440, justify="left",
                  text="Aparece al pie del informe PDF («Preparado por») y en la firma "
                       "del correo que recibe el cliente.")).grid(
            row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))
        self._campo(d, 1, "nombre", "Nombre o estudio *")
        self._campo(d, 2, "identificacion", "Cédula / RUC")
        self._campo(d, 3, "cargo", "Cargo", ayuda="P. ej. «Contador Público Autorizado»")
        self._campo(d, 5, "registro", "N.º de registro")
        self._campo(d, 6, "correo_declarante", "Correo de contacto *")
        self._campo(d, 7, "telefono", "Teléfono")
        self._campo(d, 8, "direccion", "Dirección")

        ttk.Label(d, text="Logo").grid(row=9, column=0, sticky="nw", pady=(10, 0))
        logo = ttk.Frame(d)
        logo.grid(row=9, column=1, sticky="w", padx=(8, 0), pady=(10, 0))
        self.lbl_logo = ttk.Label(logo, text="Sin logo", foreground=GRIS)
        self.lbl_logo.pack(side="left")
        ttk.Button(logo, text="Quitar", command=self._quitar_logo).pack(side="right")
        ttk.Button(logo, text="Elegir…", command=self._elegir_logo).pack(side="right", padx=6)
        ttk.Label(d, text="PNG, JPG o GIF de hasta 2 MB. Encabeza el informe PDF.",
                  foreground=GRIS).grid(row=10, column=1, sticky="w", padx=(8, 0))

        # --- Correo de envío -----------------------------------------------------
        c = ttk.LabelFrame(columnas, text="Correo de envío (SMTP)", padding=12)
        c.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        c.columnconfigure(1, weight=1)
        _ajustar_ancho(ttk.Label(c, foreground=GRIS, wraplength=440, justify="left",
                  text="Cuenta con la que la app envía la declaración a sus clientes.")).grid(
            row=0, column=0, columnspan=2, sticky="we", pady=(0, 8))

        ttk.Label(c, text="Proveedor").grid(row=1, column=0, sticky="w", pady=3)
        self.var_proveedor = tk.StringVar(value=OTRO_PROVEEDOR)
        combo = ttk.Combobox(c, textvariable=self.var_proveedor, state="readonly",
                             values=[*perfil.PROVEEDORES, OTRO_PROVEEDOR])
        combo.grid(row=1, column=1, sticky="we", padx=(8, 0), pady=3)
        combo.bind("<<ComboboxSelected>>", self._aplicar_proveedor)

        self._campo(c, 2, "servidor", "Servidor")
        fila = ttk.Frame(c)
        fila.grid(row=3, column=1, sticky="we", padx=(8, 0), pady=3)
        ttk.Label(c, text="Puerto").grid(row=3, column=0, sticky="w", pady=3)
        self._vars["puerto"] = tk.StringVar()
        ttk.Entry(fila, textvariable=self._vars["puerto"], width=7).pack(side="left")
        ttk.Label(fila, text="Seguridad").pack(side="left", padx=(14, 6))
        self.var_seguridad = tk.StringVar()
        ttk.Combobox(fila, textvariable=self.var_seguridad, state="readonly", width=11,
                     values=list(SEGURIDAD_TEXTO.values())).pack(side="left")

        self._campo(c, 4, "usuario", "Usuario (correo)")
        self.ent_clave = self._campo(c, 5, "clave", "Contraseña", show="•")
        estado = ttk.Frame(c)
        estado.grid(row=6, column=1, sticky="we", padx=(8, 0))
        self.lbl_clave = ttk.Label(estado, text="", foreground=GRIS)
        self.lbl_clave.pack(side="left")
        self.btn_borrar_clave = ttk.Button(estado, text="Borrar contraseña",
                                           command=self._borrar_clave)
        self.btn_borrar_clave.pack(side="right")
        _ajustar_ancho(ttk.Label(c, foreground=GRIS, wraplength=420, justify="left",
                  text="Gmail y Outlook piden una «contraseña de aplicación» (se crea en la "
                       "seguridad de la cuenta, con la verificación en dos pasos activa). "
                       "Se guarda cifrada y no se vuelve a mostrar.")).grid(
            row=7, column=1, sticky="we", padx=(8, 0), pady=(2, 6))

        self._campo(c, 8, "remitente", "Nombre del remitente",
                    ayuda="Lo que ve el cliente como remitente. Vacío: su correo.")
        self.var_copia = tk.BooleanVar(value=True)
        ttk.Checkbutton(c, text="Enviarme una copia oculta de cada envío",
                        variable=self.var_copia).grid(row=10, column=1, sticky="w",
                                                      padx=(8, 0), pady=(6, 0))
        prueba = ttk.Frame(c)
        prueba.grid(row=11, column=1, sticky="we", padx=(8, 0), pady=(12, 0))
        self.btn_probar = ttk.Button(prueba, text="Probar conexión", command=self._probar)
        self.btn_probar.pack(side="left")
        self.lbl_prueba = ttk.Label(prueba, text="", wraplength=300, justify="left")
        self.lbl_prueba.pack(side="left", padx=8)

        # --- Guardar -------------------------------------------------------------
        barra = ttk.Frame(self)
        barra.pack(fill="x", pady=(12, 0))
        ttk.Button(barra, text="Guardar cambios", command=self.guardar,
                   default="active").pack(side="right")
        self.lbl_estado = ttk.Label(barra, text="", foreground=GRIS)
        self.lbl_estado.pack(side="right", padx=10)

    # ------------------------------------------------------------------ datos
    def _cargar(self) -> None:
        d, c = self.perfil.declarante, self.perfil.correo
        valores = {
            "nombre": d.nombre, "identificacion": d.identificacion, "cargo": d.cargo,
            "registro": d.registro, "correo_declarante": d.correo, "telefono": d.telefono,
            "direccion": d.direccion, "servidor": c.servidor, "puerto": str(c.puerto or ""),
            "usuario": c.usuario, "remitente": c.remitente, "clave": "",
        }
        for clave, valor in valores.items():
            self._vars[clave].set(valor)
        self.var_seguridad.set(SEGURIDAD_TEXTO.get(c.seguridad, "SSL/TLS"))
        self.var_copia.set(c.copia_a_mi)
        proveedor = next((n for n, (s, p, seg) in perfil.PROVEEDORES.items()
                          if (s, p, seg) == (c.servidor, c.puerto, c.seguridad)), OTRO_PROVEEDOR)
        self.var_proveedor.set(proveedor)
        self._mostrar_logo()
        self._mostrar_estado_clave()

    def _leer(self) -> perfil.Perfil:
        v = {k: str(var.get()).strip() for k, var in self._vars.items()}
        seguridad = next((k for k, t in SEGURIDAD_TEXTO.items()
                          if t == self.var_seguridad.get()), "ssl")
        try:
            puerto = int(v["puerto"] or 0)
        except ValueError:
            puerto = 0
        return perfil.Perfil(
            perfil.Declarante(v["nombre"], v["identificacion"], v["cargo"], v["registro"],
                              v["correo_declarante"], v["telefono"], v["direccion"],
                              self.perfil.declarante.logo),
            perfil.ServidorCorreo(v["servidor"], puerto, seguridad, v["usuario"],
                                  v["remitente"], self.var_copia.get()),
        )

    def guardar(self) -> bool:
        nuevo = self._leer()
        try:
            perfil.guardar(nuevo)
        except ValueError as e:
            messagebox.showerror(TITULO, str(e))
            return False
        except OSError as e:
            messagebox.showerror(TITULO, f"No se pudo guardar la configuración:\n{e}")
            return False
        clave = self._vars["clave"].get()
        if clave:
            try:
                self.registro.guardar_clave_smtp(clave)
            except (clientes.ErrorClientes, cifrado.ErrorCifrado) as e:
                messagebox.showerror(TITULO, f"No se pudo guardar la contraseña:\n{e}")
                return False
            self._vars["clave"].set("")
        self.perfil = nuevo
        self._mostrar_estado_clave()
        self.lbl_estado.configure(text="Cambios guardados.", foreground=VERDE)
        self.after(4000, lambda: self.lbl_estado.configure(text=""))
        return True

    def _mostrar_estado_clave(self) -> None:
        try:
            hay = self.registro.tiene_clave_smtp()
        except Exception:  # noqa: BLE001 - base ilegible: se informa como faltante
            hay = False
        if hay:
            self.lbl_clave.configure(text="✓ Contraseña guardada (cifrada). Escriba otra para "
                                          "reemplazarla.", foreground=VERDE)
        else:
            self.lbl_clave.configure(text="Sin contraseña guardada.", foreground=GRIS)
        self.btn_borrar_clave.configure(state="normal" if hay else "disabled")

    def _borrar_clave(self) -> None:
        if not messagebox.askyesno(TITULO, "¿Borrar la contraseña guardada del correo?"):
            return
        self.registro.borrar_clave_smtp()
        self._mostrar_estado_clave()

    def _aplicar_proveedor(self, _evento=None) -> None:
        datos = perfil.PROVEEDORES.get(self.var_proveedor.get())
        if not datos:
            return
        servidor, puerto, seguridad = datos
        self._vars["servidor"].set(servidor)
        self._vars["puerto"].set(str(puerto))
        self.var_seguridad.set(SEGURIDAD_TEXTO[seguridad])

    # ------------------------------------------------------------------- logo
    def _mostrar_logo(self) -> None:
        ruta = self.perfil.ruta_logo()
        self._logo_img = None
        if ruta is None:
            self.lbl_logo.configure(image="", text="Sin logo")
            return
        try:
            from PIL import Image, ImageTk

            imagen = Image.open(ruta)
            imagen.thumbnail((180, 56))
            self._logo_img = ImageTk.PhotoImage(imagen, master=self)
            self.lbl_logo.configure(image=self._logo_img, text="")
        except Exception:  # noqa: BLE001 - sin vista previa se muestra el nombre
            self.lbl_logo.configure(image="", text=ruta.name)

    def _elegir_logo(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Logo para el informe",
            filetypes=tipos_archivo(("Imágenes", "*.png"), ("JPG", "*.jpg"), ("JPEG", "*.jpeg"),
                                    ("GIF", "*.gif")))
        if not ruta:
            return
        try:
            self.perfil.declarante.logo = perfil.importar_logo(ruta)
            perfil.guardar(self._con_logo())
        except (ValueError, OSError) as e:
            messagebox.showerror(TITULO, str(e))
            return
        self._mostrar_logo()

    def _quitar_logo(self) -> None:
        perfil.quitar_logo(self.perfil)
        try:
            perfil.guardar(self._con_logo())
        except (ValueError, OSError):
            pass
        self._mostrar_logo()

    def _con_logo(self) -> perfil.Perfil:
        """Perfil guardado con solo el logo cambiado (no guarda el resto a medias)."""
        guardado = perfil.leer()
        guardado.declarante.logo = self.perfil.declarante.logo
        return guardado

    # ----------------------------------------------------------------- prueba
    def _probar(self) -> None:
        if self._probando:
            return
        servidor = self._leer().correo
        if not servidor.configurado:
            self.lbl_prueba.configure(text="Complete servidor, puerto y usuario.",
                                      foreground=ROJO)
            return
        clave = self._vars["clave"].get()
        if not clave:
            try:
                clave = self.registro.clave_smtp()
            except (clientes.ErrorClientes, cifrado.ErrorCifrado) as e:
                self.lbl_prueba.configure(text=str(e), foreground=ROJO)
                return
        self._probando = True
        self.btn_probar.configure(state="disabled")
        self.lbl_prueba.configure(text="Conectando…", foreground=GRIS)
        resultado: dict = {}

        def trabajo() -> None:
            try:
                correo.probar(servidor, clave)
                resultado["ok"] = True
            except correo.ErrorCorreo as e:
                resultado["error"] = str(e)

        hilo = threading.Thread(target=trabajo, daemon=True)
        hilo.start()

        def esperar() -> None:
            if hilo.is_alive():
                self.after(150, esperar)
                return
            self._probando = False
            self.btn_probar.configure(state="normal")
            if resultado.get("ok"):
                self.lbl_prueba.configure(text="✓ Conexión e inicio de sesión correctos.",
                                          foreground=VERDE)
            else:
                self.lbl_prueba.configure(text=resultado.get("error", "Falló la prueba."),
                                          foreground=ROJO)

        esperar()
