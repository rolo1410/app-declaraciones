"""Cifrado de las claves del SRI con una llave maestra.

* Llave maestra: 32 bytes aleatorios guardados en el almacén de credenciales del
  sistema (``keyring``): Administrador de credenciales en Windows, Llavero en
  macOS y Secret Service (GNOME Keyring) en Linux.
* Cada clave se cifra con AES-256-GCM, nonce aleatorio de 12 bytes y como dato
  asociado ``"<ruc>|<portal>|v<version>"``: una clave cifrada no sirve para otro
  cliente, otro portal u otra versión de la llave.
* Verificador: HMAC de una constante con la llave. Se guarda en la base para
  detectar, antes de descifrar nada, que la llave del sistema no es la de esta base.
* Copia de emergencia: la llave cifrada con una frase de paso (Argon2id →
  AES-GCM) en un archivo ``.llave`` que el usuario guarda fuera del equipo.

Este módulo nunca registra ni devuelve claves en mensajes de error.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SERVICIO = "ComprobantesSRI"
LARGO_LLAVE = 32
LARGO_NONCE = 12
_CONTEXTO_VERIFICADOR = b"ComprobantesSRI/verificador/v1"

FORMATO_COPIA = "ComprobantesSRI-llave"
EXTENSION_COPIA = ".llave"
LARGO_MINIMO_FRASE = 12

# Parámetros Argon2id de la copia de emergencia (se guardan en el archivo para
# poder endurecerlos en el futuro sin romper copias antiguas).
ARGON2_TIEMPO = 3
ARGON2_MEMORIA_KIB = 64 * 1024
ARGON2_PARALELISMO = 4


class ErrorCifrado(Exception):
    """Base de los errores de este módulo (mensajes aptos para el usuario)."""


class LlaveNoDisponible(ErrorCifrado):
    """No hay llave maestra en el almacén del sistema."""


class LlaveNoCorresponde(ErrorCifrado):
    """La llave del sistema no es la que cifró esta base."""


class ClaveIlegible(ErrorCifrado):
    """El descifrado falló: datos alterados, de otro cliente o llave errónea."""


class CopiaInvalida(ErrorCifrado):
    """El archivo de copia de emergencia es ilegible o la frase es incorrecta."""


# ---------------------------------------------------------------------------
# Almacén de la llave maestra
# ---------------------------------------------------------------------------

class Llavero(Protocol):
    def leer(self, version: int) -> bytes | None: ...
    def guardar(self, version: int, llave: bytes) -> None: ...


def _nombre_entrada(version: int) -> str:
    return f"llave_maestra_v{version}"


class LlaveroSistema:
    """Guarda la llave maestra en el almacén del sistema vía ``keyring``."""

    def leer(self, version: int) -> bytes | None:
        import keyring
        from keyring.errors import KeyringError

        try:
            valor = keyring.get_password(SERVICIO, _nombre_entrada(version))
        except KeyringError as e:
            raise LlaveNoDisponible(
                f"No se pudo acceder al almacén de credenciales del sistema ({type(e).__name__})."
            ) from None
        if not valor:
            return None
        try:
            llave = base64.b64decode(valor, validate=True)
        except ValueError:
            raise LlaveNoCorresponde("La llave guardada en el sistema está dañada.") from None
        if len(llave) != LARGO_LLAVE:
            raise LlaveNoCorresponde("La llave guardada en el sistema está dañada.")
        return llave

    def guardar(self, version: int, llave: bytes) -> None:
        import keyring
        from keyring.errors import KeyringError

        try:
            keyring.set_password(
                SERVICIO, _nombre_entrada(version), base64.b64encode(llave).decode("ascii")
            )
        except KeyringError as e:
            raise LlaveNoDisponible(
                f"No se pudo guardar la llave en el almacén del sistema ({type(e).__name__})."
            ) from None


def backend_real() -> tuple[bool, str]:
    """(hay_almacén_utilizable, nombre_del_backend).

    ``keyring`` cae en ``fail.Keyring`` o ``null.Keyring`` cuando no encuentra
    un almacén (p. ej. Linux sin Secret Service): ahí no se puede guardar nada.
    """
    import keyring

    kr = keyring.get_keyring()
    nombre = f"{type(kr).__module__}.{type(kr).__name__}"
    malos = ("keyring.backends.fail", "keyring.backends.null")
    if type(kr).__module__ in malos:
        return False, nombre
    hijos = getattr(kr, "backends", None)
    if hijos is not None:  # ChainerBackend: vale si alguno es real
        reales = [b for b in hijos if type(b).__module__ not in malos]
        return bool(reales), nombre
    return True, nombre


# ---------------------------------------------------------------------------
# Llave, verificador y cifrado
# ---------------------------------------------------------------------------

def generar_llave() -> bytes:
    return os.urandom(LARGO_LLAVE)


def verificador(llave: bytes) -> bytes:
    return hmac.new(llave, _CONTEXTO_VERIFICADOR, hashlib.sha256).digest()


def comprobar_verificador(llave: bytes, esperado: bytes) -> None:
    if not hmac.compare_digest(verificador(llave), bytes(esperado)):
        raise LlaveNoCorresponde(
            "La llave del sistema no corresponde a esta base de datos. "
            "Restaure la copia de emergencia (.llave)."
        )


def datos_asociados(ruc: str, portal: str, version: int) -> bytes:
    return f"{ruc}|{portal}|v{version}".encode("utf-8")


def cifrar(llave: bytes, version: int, clave: str, ruc: str, portal: str) -> tuple[bytes, bytes]:
    """Cifra ``clave`` y devuelve ``(nonce, cifrado)``."""
    if not clave:
        raise ValueError("La clave no puede estar vacía.")
    nonce = os.urandom(LARGO_NONCE)
    cifrado = AESGCM(llave).encrypt(
        nonce, clave.encode("utf-8"), datos_asociados(ruc, portal, version)
    )
    return nonce, cifrado


def descifrar(
    llave: bytes, version: int, nonce: bytes, cifrado: bytes, ruc: str, portal: str
) -> str:
    try:
        claro = AESGCM(llave).decrypt(
            bytes(nonce), bytes(cifrado), datos_asociados(ruc, portal, version)
        )
    except (InvalidTag, ValueError):
        raise ClaveIlegible(
            "No se pudo descifrar la clave guardada (datos alterados o llave distinta). "
            "Vuelva a registrar la clave del cliente."
        ) from None
    return claro.decode("utf-8")


# ---------------------------------------------------------------------------
# Copia de emergencia
# ---------------------------------------------------------------------------

def _derivar(frase: str, sal: bytes, tiempo: int, memoria: int, paralelismo: int) -> bytes:
    from argon2.low_level import Type, hash_secret_raw

    return hash_secret_raw(
        secret=frase.encode("utf-8"), salt=sal, time_cost=tiempo,
        memory_cost=memoria, parallelism=paralelismo, hash_len=LARGO_LLAVE, type=Type.ID,
    )


def _aad_copia(version: int) -> bytes:
    return f"{FORMATO_COPIA}|v{version}".encode("utf-8")


def exportar_copia(llave: bytes, version: int, frase: str) -> bytes:
    """Contenido del archivo ``.llave``: la llave cifrada con la frase de paso."""
    if len(frase or "") < LARGO_MINIMO_FRASE:
        raise ValueError(
            f"La frase de paso debe tener al menos {LARGO_MINIMO_FRASE} caracteres."
        )
    sal = os.urandom(16)
    derivada = _derivar(frase, sal, ARGON2_TIEMPO, ARGON2_MEMORIA_KIB, ARGON2_PARALELISMO)
    nonce = os.urandom(LARGO_NONCE)
    cifrado = AESGCM(derivada).encrypt(nonce, llave, _aad_copia(version))
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    documento = {
        "formato": FORMATO_COPIA,
        "version_formato": 1,
        "version_llave": version,
        "kdf": {
            "algoritmo": "argon2id", "sal": b64(sal), "tiempo": ARGON2_TIEMPO,
            "memoria_kib": ARGON2_MEMORIA_KIB, "paralelismo": ARGON2_PARALELISMO,
        },
        "nonce": b64(nonce),
        "llave_cifrada": b64(cifrado),
        "verificador": b64(verificador(llave)),
    }
    return (json.dumps(documento, indent=2) + "\n").encode("utf-8")


def importar_copia(datos: bytes, frase: str) -> tuple[int, bytes]:
    """Lee un archivo ``.llave`` y devuelve ``(version, llave)``."""
    try:
        doc = json.loads(datos.decode("utf-8"))
        if doc.get("formato") != FORMATO_COPIA or doc.get("version_formato") != 1:
            raise CopiaInvalida("El archivo no es una copia de emergencia de Comprobantes SRI.")
        kdf = doc["kdf"]
        if kdf["algoritmo"] != "argon2id":
            raise CopiaInvalida("Algoritmo de la copia no soportado.")
        version = int(doc["version_llave"])
        sal = base64.b64decode(kdf["sal"])
        nonce = base64.b64decode(doc["nonce"])
        cifrado = base64.b64decode(doc["llave_cifrada"])
        verif = base64.b64decode(doc["verificador"])
        tiempo, memoria, paral = int(kdf["tiempo"]), int(kdf["memoria_kib"]), int(kdf["paralelismo"])
    except CopiaInvalida:
        raise
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise CopiaInvalida("El archivo de copia de emergencia está dañado.") from None

    derivada = _derivar(frase or "", sal, tiempo, memoria, paral)
    try:
        llave = AESGCM(derivada).decrypt(nonce, cifrado, _aad_copia(version))
    except InvalidTag:
        raise CopiaInvalida("La frase de paso es incorrecta.") from None
    if len(llave) != LARGO_LLAVE or not hmac.compare_digest(verificador(llave), verif):
        raise CopiaInvalida("El archivo de copia de emergencia está dañado.")
    return version, llave
