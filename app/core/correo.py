"""Envío de correo por SMTP (biblioteca estándar).

La contraseña se recibe ya descifrada, se usa solo para ``login`` y nunca se
escribe en mensajes de error ni en la bitácora.
"""
from __future__ import annotations

import mimetypes
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from .perfil import ServidorCorreo

TIEMPO_ESPERA = 30  # segundos


class ErrorCorreo(Exception):
    """Fallo de envío con mensaje apto para el usuario."""


def lista_correos(texto: str) -> list[str]:
    return [p.strip() for p in texto.replace(";", ",").split(",") if p.strip()]


def construir(
    servidor: ServidorCorreo,
    para: list[str],
    asunto: str,
    cuerpo: str,
    adjuntos: list[Path] = (),
    responder_a: str = "",
) -> EmailMessage:
    remitente = servidor.usuario.strip()
    msg = EmailMessage()
    msg["From"] = formataddr((servidor.remitente.strip() or remitente, remitente))
    msg["To"] = ", ".join(para)
    if servidor.copia_a_mi:
        msg["Bcc"] = remitente
    if responder_a and responder_a.strip().lower() != remitente.lower():
        msg["Reply-To"] = responder_a.strip()
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=remitente.rpartition("@")[2] or None)
    msg.set_content(cuerpo)
    for ruta in adjuntos:
        tipo, _ = mimetypes.guess_type(ruta.name)
        principal, _, secundario = (tipo or "application/octet-stream").partition("/")
        msg.add_attachment(Path(ruta).read_bytes(), maintype=principal, subtype=secundario,
                           filename=Path(ruta).name)
    return msg


def _conectar(servidor: ServidorCorreo, clave: str) -> smtplib.SMTP:
    contexto = ssl.create_default_context()
    host, puerto = servidor.servidor.strip(), int(servidor.puerto)
    try:
        if servidor.seguridad == "ssl":
            smtp = smtplib.SMTP_SSL(host, puerto, timeout=TIEMPO_ESPERA, context=contexto)
        else:
            smtp = smtplib.SMTP(host, puerto, timeout=TIEMPO_ESPERA)
            if servidor.seguridad == "starttls":
                smtp.starttls(context=contexto)
        if servidor.autenticar:
            smtp.login(servidor.usuario.strip(), clave)
        return smtp
    except smtplib.SMTPAuthenticationError:
        raise ErrorCorreo(
            "El servidor rechazó el usuario o la contraseña.\n\n"
            "Gmail y Outlook exigen una «contraseña de aplicación» (no la contraseña "
            "normal de la cuenta) cuando la cuenta tiene verificación en dos pasos."
        ) from None
    except (OSError, smtplib.SMTPException) as e:
        raise ErrorCorreo(
            f"No se pudo conectar con {host}:{puerto} ({type(e).__name__}).\n"
            "Revise servidor, puerto y seguridad en «Configuración», y la conexión a internet."
        ) from None


def probar(servidor: ServidorCorreo, clave: str) -> None:
    """Conecta e inicia sesión sin enviar nada."""
    smtp = _conectar(servidor, clave)
    try:
        smtp.quit()
    except smtplib.SMTPException:
        pass


def enviar(servidor: ServidorCorreo, clave: str, mensaje: EmailMessage) -> list[str]:
    """Envía el mensaje. Devuelve las direcciones que el servidor rechazó (si
    rechaza solo algunas, a las demás sí se envió)."""
    smtp = _conectar(servidor, clave)
    try:
        rechazados = smtp.send_message(mensaje)
    except smtplib.SMTPRecipientsRefused:
        raise ErrorCorreo("El servidor rechazó todas las direcciones de destino.") from None
    except smtplib.SMTPSenderRefused:
        raise ErrorCorreo("El servidor no acepta enviar desde esta cuenta.") from None
    except smtplib.SMTPDataError as e:
        raise ErrorCorreo(f"El servidor rechazó el mensaje (código {e.smtp_code}). "
                          "Puede que los adjuntos superen su límite de tamaño.") from None
    except (OSError, smtplib.SMTPException) as e:
        raise ErrorCorreo(f"Se cortó la conexión al enviar ({type(e).__name__}).") from None
    finally:
        try:
            smtp.quit()
        except (OSError, smtplib.SMTPException):
            pass
    return sorted(rechazados)
