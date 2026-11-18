"""Validación de RUC y cédula ecuatorianos.

| Tercer dígito | Tipo       | Estructura                        | Verificador            |
|---------------|------------|-----------------------------------|------------------------|
| 0–5           | natural    | cédula (10) + 001                 | módulo 10 (obligatorio)|
| 6             | publica    | 8 dígitos + verificador + 0001    | módulo 11 (advertencia)|
| 9             | sociedad   | 9 dígitos + verificador + 001     | módulo 11 (advertencia)|

En sociedades y entidades públicas el dígito verificador solo genera una
advertencia: el SRI ha emitido RUC que no cumplen el cálculo.

``carpeta_de()`` es la única función que decide el nombre de la carpeta de un
cliente: la cédula para personas naturales y el RUC para el resto.
"""
from __future__ import annotations

from dataclasses import dataclass, field

NATURAL = "natural"
SOCIEDAD = "sociedad"
PUBLICA = "publica"

TIPOS = (NATURAL, SOCIEDAD, PUBLICA)
NOMBRES_TIPO = {
    NATURAL: "Persona natural",
    SOCIEDAD: "Sociedad",
    PUBLICA: "Entidad pública",
}

_PROVINCIAS = {f"{n:02d}" for n in range(1, 25)} | {"30"}


class RucInvalido(ValueError):
    """El RUC o la cédula no cumplen la estructura exigida."""


@dataclass(frozen=True)
class InfoRuc:
    ruc: str
    tipo: str
    cedula: str | None
    advertencias: list[str] = field(default_factory=list)

    @property
    def carpeta(self) -> str:
        return self.cedula or self.ruc


def _limpiar(texto: str) -> str:
    return "".join((texto or "").split())


def cedula_valida(cedula: str) -> bool:
    """Cédula de 10 dígitos con provincia válida y verificador módulo 10."""
    cedula = _limpiar(cedula)
    if len(cedula) != 10 or not cedula.isdigit():
        return False
    if cedula[:2] not in _PROVINCIAS or int(cedula[2]) > 5:
        return False
    suma = 0
    for i, coef in enumerate((2, 1, 2, 1, 2, 1, 2, 1, 2)):
        producto = int(cedula[i]) * coef
        suma += producto - 9 if producto > 9 else producto
    return (10 - suma % 10) % 10 == int(cedula[9])


def _modulo11(digitos: str, coeficientes: tuple[int, ...]) -> int | None:
    """Dígito verificador módulo 11, o ``None`` si el cálculo da 10 (inválido)."""
    suma = sum(int(d) * c for d, c in zip(digitos, coeficientes))
    resto = suma % 11
    verificador = 0 if resto == 0 else 11 - resto
    return None if verificador == 10 else verificador


def analizar(ruc: str) -> InfoRuc:
    """Valida ``ruc`` y devuelve su tipo, cédula y advertencias.

    Lanza ``RucInvalido`` con un mensaje para el usuario si no es aceptable.
    """
    ruc = _limpiar(ruc)
    if not ruc:
        raise RucInvalido("El RUC es obligatorio.")
    if not ruc.isdigit():
        raise RucInvalido("El RUC debe contener solo dígitos.")
    if len(ruc) == 10:
        raise RucInvalido(
            "Se ingresaron 10 dígitos (una cédula): el RUC de una persona natural "
            "es la cédula seguida de 001."
        )
    if len(ruc) != 13:
        raise RucInvalido(f"El RUC debe tener 13 dígitos (se ingresaron {len(ruc)}).")
    if ruc[:2] not in _PROVINCIAS:
        raise RucInvalido(
            f"Código de provincia inválido ({ruc[:2]}): debe estar entre 01 y 24, o ser 30."
        )

    tercero = int(ruc[2])
    advertencias: list[str] = []

    if tercero <= 5:
        if ruc[10:] != "001":
            raise RucInvalido(
                "El RUC de una persona natural debe terminar en 001 (cédula + 001)."
            )
        cedula = ruc[:10]
        if not cedula_valida(cedula):
            raise RucInvalido(
                f"Los 10 primeros dígitos ({cedula}) no son una cédula válida."
            )
        return InfoRuc(ruc=ruc, tipo=NATURAL, cedula=cedula)

    if tercero == 6:
        if ruc[9:] == "0000":
            raise RucInvalido("El número de establecimiento no puede ser 0000.")
        esperado = _modulo11(ruc[:8], (3, 2, 7, 6, 5, 4, 3, 2))
        if esperado != int(ruc[8]):
            advertencias.append(
                "El dígito verificador no cumple el módulo 11. Revise el RUC; "
                "si es correcto según el SRI, puede continuar."
            )
        return InfoRuc(ruc=ruc, tipo=PUBLICA, cedula=None, advertencias=advertencias)

    if tercero == 9:
        if ruc[10:] == "000":
            raise RucInvalido("El número de establecimiento no puede ser 000.")
        esperado = _modulo11(ruc[:9], (4, 3, 2, 7, 6, 5, 4, 3, 2))
        if esperado != int(ruc[9]):
            advertencias.append(
                "El dígito verificador no cumple el módulo 11. Revise el RUC; "
                "si es correcto según el SRI, puede continuar."
            )
        return InfoRuc(ruc=ruc, tipo=SOCIEDAD, cedula=None, advertencias=advertencias)

    raise RucInvalido(
        f"Tercer dígito inválido ({tercero}): debe ser 0–5 (persona natural), "
        "6 (entidad pública) o 9 (sociedad)."
    )


def carpeta_de(ruc: str) -> str:
    """Nombre de la carpeta del cliente: cédula (natural) o RUC (resto)."""
    return analizar(ruc).carpeta


def identificaciones_de(ruc: str) -> set[str]:
    """Identificaciones con las que el cliente puede figurar como comprador."""
    info = analizar(ruc)
    return {info.ruc, info.cedula} - {None}  # type: ignore[return-value]
