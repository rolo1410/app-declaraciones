"""Perfil de quien prepara las declaraciones y servidor de correo de envío.

Se guarda en ``perfil.json`` dentro de la carpeta de datos de la app (junto a
``clientes.db``). La contraseña del correo **no** va aquí: se guarda cifrada
con la llave maestra en la base (``Registro.guardar_clave_smtp``).

El logo se copia a la carpeta de datos (``logo.png`` / ``logo.jpg``) para que
el informe no dependa de que el archivo original siga en su sitio.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from . import plataforma

ARCHIVO = "perfil.json"
EXTENSIONES_LOGO = (".png", ".jpg", ".jpeg", ".gif")
MAX_LOGO = 2 * 1024 * 1024  # 2 MB

SEGURIDADES = ("ssl", "starttls", "ninguna")

# Ajustes conocidos: (servidor, puerto, seguridad)
PROVEEDORES: dict[str, tuple[str, int, str]] = {
    "Gmail / Google Workspace": ("smtp.gmail.com", 465, "ssl"),
    "Outlook / Microsoft 365": ("smtp.office365.com", 587, "starttls"),
    "Yahoo": ("smtp.mail.yahoo.com", 465, "ssl"),
    "Zoho": ("smtp.zoho.com", 465, "ssl"),
}


@dataclass
class Declarante:
    nombre: str = ""
    identificacion: str = ""      # cédula o RUC
    cargo: str = ""               # p. ej. «Contador Público Autorizado»
    registro: str = ""            # n.º de registro profesional
    correo: str = ""
    telefono: str = ""
    direccion: str = ""
    logo: str = ""                # nombre del archivo dentro de la carpeta de datos

    @property
    def completo(self) -> bool:
        return bool(self.nombre.strip() and self.correo.strip())

    def lineas_firma(self) -> list[str]:
        """Líneas de la firma del correo y del pie del PDF (sin las vacías)."""
        cargo = " · ".join(x for x in (self.cargo.strip(), _reg(self.registro)) if x)
        contacto = " · ".join(x for x in (self.correo.strip(), self.telefono.strip()) if x)
        ident = f"C.I./RUC {self.identificacion.strip()}" if self.identificacion.strip() else ""
        return [x for x in (self.nombre.strip(), cargo, ident, contacto, self.direccion.strip())
                if x]


def _reg(registro: str) -> str:
    registro = registro.strip()
    return f"Reg. {registro}" if registro else ""


@dataclass
class ServidorCorreo:
    servidor: str = ""
    puerto: int = 465
    seguridad: str = "ssl"
    usuario: str = ""             # cuenta con la que se inicia sesión (suele ser el correo)
    remitente: str = ""           # nombre visible del remitente
    copia_a_mi: bool = True       # enviarse una copia oculta (CCO)

    @property
    def configurado(self) -> bool:
        return bool(self.servidor.strip() and self.usuario.strip() and self.puerto)


@dataclass
class Perfil:
    declarante: Declarante = field(default_factory=Declarante)
    correo: ServidorCorreo = field(default_factory=ServidorCorreo)

    def ruta_logo(self) -> Path | None:
        if not self.declarante.logo:
            return None
        ruta = plataforma.datos_dir() / Path(self.declarante.logo).name
        return ruta if ruta.is_file() else None


def ruta() -> Path:
    return plataforma.datos_dir() / ARCHIVO


def _cargar(clase, datos: object):
    """Instancia ``clase`` con las claves conocidas de ``datos`` (ignora el resto)."""
    if not isinstance(datos, dict):
        return clase()
    validos = {}
    for f in fields(clase):
        if f.name not in datos:
            continue
        valor = datos[f.name]
        if f.type in ("int", int):
            try:
                valor = int(valor)
            except (TypeError, ValueError):
                continue
        elif f.type in ("bool", bool):
            valor = bool(valor)
        else:
            valor = "" if valor is None else str(valor)
        validos[f.name] = valor
    return clase(**validos)


def leer() -> Perfil:
    try:
        datos = json.loads(ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Perfil()
    if not isinstance(datos, dict):
        return Perfil()
    perfil = Perfil(_cargar(Declarante, datos.get("declarante")),
                    _cargar(ServidorCorreo, datos.get("correo")))
    if perfil.correo.seguridad not in SEGURIDADES:
        perfil.correo.seguridad = "ssl"
    return perfil


def validar(perfil: Perfil) -> list[str]:
    """Problemas que impiden guardar (mensajes para el usuario)."""
    errores = []
    c = perfil.correo
    if c.seguridad not in SEGURIDADES:
        errores.append("Seguridad del correo no válida.")
    if not (0 < int(c.puerto or 0) < 65536):
        errores.append("El puerto debe estar entre 1 y 65535.")
    for etiqueta, valor in (("Su correo", perfil.declarante.correo),):
        valor = valor.strip()
        if valor and ("@" not in valor or " " in valor):
            errores.append(f"{etiqueta}: «{valor}» no parece una dirección de correo.")
    return errores


def guardar(perfil: Perfil) -> None:
    errores = validar(perfil)
    if errores:
        raise ValueError("\n".join(errores))
    datos = {"declarante": asdict(perfil.declarante), "correo": asdict(perfil.correo)}
    destino = ruta()
    destino.parent.mkdir(parents=True, exist_ok=True)
    plataforma.escribir_atomico(
        destino, json.dumps(datos, ensure_ascii=False, indent=2).encode("utf-8"))
    plataforma.restringir_permisos(destino, recursivo=False)


def importar_logo(origen: str | Path) -> str:
    """Copia la imagen a la carpeta de datos y devuelve el nombre a guardar en el perfil."""
    origen = Path(origen)
    extension = origen.suffix.lower()
    if extension not in EXTENSIONES_LOGO:
        raise ValueError("El logo debe ser una imagen PNG, JPG o GIF.")
    if origen.stat().st_size > MAX_LOGO:
        raise ValueError("El logo pesa más de 2 MB: use una imagen más liviana.")
    extension = ".jpg" if extension == ".jpeg" else extension
    nombre = f"logo{extension}"
    carpeta = plataforma.datos_dir()
    carpeta.mkdir(parents=True, exist_ok=True)
    for viejo in carpeta.glob("logo.*"):
        if viejo.name != nombre:
            viejo.unlink(missing_ok=True)
    shutil.copyfile(origen, carpeta / nombre)
    return nombre


def quitar_logo(perfil: Perfil) -> None:
    for viejo in plataforma.datos_dir().glob("logo.*"):
        viejo.unlink(missing_ok=True)
    perfil.declarante.logo = ""
