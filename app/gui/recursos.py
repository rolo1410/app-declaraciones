"""Utilidades compartidas por la interfaz gráfica."""
from __future__ import annotations


def fmt(valor: float) -> str:
    """Formatea un monto con separador de miles y 2 decimales."""
    return f"{valor:,.2f}"
