"""Detalles que cambian según el sistema operativo.

Rutas de datos y de clientes, configuración (``config.toml``), permisos de
carpetas, escritura atómica y aviso cuando la ruta base cae en una carpeta
sincronizada con la nube.

Ubicaciones (ver ``PLAN-clientes.md`` §4.2):

* ``datos_dir()`` — base SQLite y ``config.toml``. Siempre en disco local:
  ``%LOCALAPPDATA%\\ComprobantesSRI`` (Windows),
  ``~/Library/Application Support/ComprobantesSRI`` (macOS),
  ``~/.local/share/ComprobantesSRI`` (Linux).
* ``base_path()`` — archivos de los clientes. Por defecto ``~/ComprobantesSRI``
  en los tres sistemas; configurable. Los clientes van en
  ``base_path() / "clientes" / <carpeta>``.

La variable de entorno ``COMPROBANTES_SRI_DATOS`` sustituye a ``datos_dir()``
(pruebas o instalaciones portátiles).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_NOMBRE = "ComprobantesSRI"
VAR_DATOS = "COMPROBANTES_SRI_DATOS"
ARCHIVO_CONFIG = "config.toml"
CARPETA_CLIENTES = "clientes"

ES_WINDOWS = sys.platform == "win32"

# Segmentos de ruta que delatan una carpeta sincronizada con la nube.
_PATRONES_NUBE = (
    (re.compile(r"^onedrive( - .*)?$", re.I), "OneDrive"),
    (re.compile(r"^icloud ?drive$", re.I), "iCloud Drive"),
    (re.compile(r"^mobile documents$", re.I), "iCloud Drive"),
    (re.compile(r"^com~apple~clouddocs$", re.I), "iCloud Drive"),
    (re.compile(r"^dropbox( \(.*\))?$", re.I), "Dropbox"),
    (re.compile(r"^google ?drive$", re.I), "Google Drive"),
    (re.compile(r"^my drive$|^mi unidad$", re.I), "Google Drive"),
    (re.compile(r"^googledrive-.*$", re.I), "Google Drive"),
)


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def datos_dir() -> Path:
    """Carpeta local de la base de datos y la configuración (se crea si falta)."""
    forzada = os.environ.get(VAR_DATOS, "").strip()
    if forzada:
        ruta = Path(expandir_ruta(forzada))
    else:
        from platformdirs import user_data_dir

        ruta = Path(user_data_dir(APP_NOMBRE, appauthor=False, roaming=False))
    nueva = not ruta.exists()
    ruta.mkdir(parents=True, exist_ok=True)
    if nueva:
        restringir_permisos(ruta)
    return ruta


def base_path_por_defecto() -> Path:
    return Path.home() / APP_NOMBRE


def expandir_ruta(texto: str) -> str:
    """Expande ``~``, ``$HOME``/``${VAR}`` y ``%VAR%`` en cualquier sistema.

    ``os.path.expandvars`` solo entiende ``%VAR%`` en Windows; aquí se acepta
    también en macOS/Linux (``%USERPROFILE%`` y ``%HOME%`` apuntan al home), así
    una configuración copiada de un equipo a otro sigue funcionando.
    """
    texto = (texto or "").strip()
    home = str(Path.home())

    def _pct(m: re.Match) -> str:
        nombre = m.group(1)
        if nombre.upper() in ("USERPROFILE", "HOME"):
            return os.environ.get(nombre, home) if ES_WINDOWS else home
        return os.environ.get(nombre, m.group(0))

    texto = re.sub(r"%([A-Za-z_][A-Za-z0-9_]*)%", _pct, texto)
    texto = os.path.expandvars(texto)
    return os.path.expanduser(texto)


def resolver(texto: str) -> Path:
    """Ruta absoluta y normalizada a partir de texto con variables."""
    return Path(expandir_ruta(texto)).resolve()


def dentro_de(ruta: Path, base: Path) -> bool:
    """True si ``ruta`` (ya resuelta, sin ``..`` ni enlaces) queda dentro de ``base``."""
    try:
        Path(ruta).resolve().relative_to(Path(base).resolve())
        return True
    except ValueError:
        return False


def carpeta_en_nube(ruta: Path) -> str | None:
    """Nombre del servicio de nube si ``ruta`` cae en una carpeta sincronizada."""
    ruta = Path(ruta).resolve()
    if ES_WINDOWS:
        for var in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
            valor = os.environ.get(var, "").strip()
            if valor and dentro_de(ruta, Path(valor)):
                return "OneDrive"
    for segmento in ruta.parts:
        for patron, servicio in _PATRONES_NUBE:
            if patron.match(segmento):
                return servicio
    return None


# ---------------------------------------------------------------------------
# Configuración (config.toml)
# ---------------------------------------------------------------------------

def ruta_config() -> Path:
    return datos_dir() / ARCHIVO_CONFIG


def _parsear_toml_simple(texto: str) -> dict:
    """Parser mínimo para Python 3.10 (sin ``tomllib``): ``clave = "valor"``."""
    datos: dict = {}
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or linea.startswith("[") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] == '"':
            valor = valor[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        elif len(valor) >= 2 and valor[0] == valor[-1] == "'":
            valor = valor[1:-1]
        datos[clave.strip()] = valor
    return datos


def leer_config() -> dict:
    ruta = ruta_config()
    try:
        texto = ruta.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        import tomllib  # Python 3.11+

        return tomllib.loads(texto)
    except ImportError:
        return _parsear_toml_simple(texto)
    except Exception:  # noqa: BLE001 - archivo dañado: se usan los valores por defecto
        return {}


def _toml_cadena(valor: str) -> str:
    return '"' + valor.replace("\\", "\\\\").replace('"', '\\"') + '"'


def guardar_config(datos: dict) -> None:
    """Escribe ``config.toml`` (solo claves de primer nivel con texto)."""
    lineas = ["# Configuración de Comprobantes SRI"]
    for clave, valor in datos.items():
        lineas.append(f"{clave} = {_toml_cadena(str(valor))}")
    escribir_atomico(ruta_config(), ("\n".join(lineas) + "\n").encode("utf-8"))


def base_path() -> Path:
    """Ruta base absoluta de los archivos de clientes (configurable)."""
    texto = str(leer_config().get("base_path", "")).strip()
    return resolver(texto) if texto else base_path_por_defecto().resolve()


def fijar_base_path(texto: str) -> Path:
    """Guarda una nueva ruta base y la devuelve resuelta (no mueve archivos)."""
    ruta = resolver(texto)
    config = leer_config()
    config["base_path"] = str(ruta)
    guardar_config(config)
    return ruta


def carpeta_clientes(base: Path | None = None) -> Path:
    return (base or base_path()) / CARPETA_CLIENTES


# ---------------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------------

def _sid_usuario_actual() -> str | None:
    try:
        salida = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(S-1-[0-9-]+)", salida)
    return m.group(1) if m else None


def restringir_permisos(ruta: Path) -> None:
    """Deja ``ruta`` accesible solo para el usuario actual.

    * POSIX: ``0700`` en carpetas y ``0600`` en archivos (recursivo).
    * Windows: dentro del perfil del usuario la ACL ya es privada y no se toca.
      Fuera del perfil se corta la herencia y se concede control total solo al
      usuario actual y a SYSTEM (copias de seguridad, antivirus).
    """
    ruta = Path(ruta)
    if not ES_WINDOWS:
        _chmod_recursivo(ruta)
        return
    if dentro_de(ruta, Path.home()):
        return
    sid = _sid_usuario_actual()
    if not sid:
        raise OSError("No se pudo identificar al usuario actual para proteger la carpeta.")
    subprocess.run(
        ["icacls", str(ruta), "/inheritance:r",
         "/grant:r", f"*{sid}:(OI)(CI)F",
         "/grant:r", "*S-1-5-18:(OI)(CI)F"],
        capture_output=True, check=True, timeout=60,
    )


def _chmod_recursivo(ruta: Path) -> None:
    if ruta.is_symlink():
        return
    if ruta.is_dir():
        os.chmod(ruta, stat.S_IRWXU)
        for hijo in ruta.iterdir():
            _chmod_recursivo(hijo)
    elif ruta.exists():
        os.chmod(ruta, stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# Escritura atómica
# ---------------------------------------------------------------------------

def escribir_atomico(ruta: Path, datos: bytes, intentos: int = 3) -> None:
    """Escribe ``datos`` en ``ruta`` sin dejar archivos a medias.

    Se escribe a un temporal en la misma carpeta y se reemplaza con
    ``os.replace``. En Windows el destino puede estar bloqueado un momento
    (antivirus, Excel abierto): se reintenta antes de rendirse.
    """
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp_", dir=str(ruta.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(datos)
            fh.flush()
            os.fsync(fh.fileno())
        if not ES_WINDOWS:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        for intento in range(intentos):
            try:
                os.replace(tmp, ruta)
                return
            except PermissionError:
                if intento == intentos - 1:
                    raise
                time.sleep(0.5 * (intento + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def abrir_en_explorador(ruta: Path) -> None:
    """Abre una carpeta en el explorador de archivos del sistema."""
    ruta = str(ruta)
    if ES_WINDOWS:
        os.startfile(ruta)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", ruta])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", ruta])  # noqa: S603,S607
