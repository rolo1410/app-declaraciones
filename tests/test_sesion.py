"""Pruebas de guardar/retomar el trabajo de la declaración."""
from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from app.core import sesion
from app.core.models import LineaDetalle
from tests.test_core import _comprobante


class TestSesion(unittest.TestCase):
    def test_ida_y_vuelta(self):
        sin_credito = _comprobante(clave_acceso="W" * 49, con_credito=False,
                                   base_tarifa_cero=Decimal("1.05"),
                                   razon_social_receptor="CLIENTE",
                                   detalles=[LineaDetalle("Servicio", Decimal("1.5"),
                                                          Decimal("3.333333"), Decimal("5.00"),
                                                          Decimal("15"))])
        original = sesion.Sesion(
            comprobantes=[_comprobante(), sin_credito],
            periodo="2026-06",
            ruc="9999999999001",
            origen="prueba.txt",
            advertencias=["aviso"],
            ventas={"ventas": "2086.96", "ventas_cero": "197.71"},
        )
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / f"trabajo{sesion.EXTENSION}"
            sesion.guardar(original, ruta)
            cargada = sesion.cargar(ruta)

        self.assertEqual(cargada.comprobantes, original.comprobantes)
        self.assertFalse(cargada.comprobantes[1].con_credito)
        self.assertEqual(cargada.comprobantes[1].base_tarifa_cero, Decimal("1.05"))
        self.assertEqual(cargada.comprobantes[1].detalles[0].precio_unitario,
                         Decimal("3.333333"))
        self.assertEqual(cargada.periodo, "2026-06")
        self.assertEqual(cargada.ruc, "9999999999001")
        self.assertEqual(cargada.ventas, original.ventas)
        self.assertEqual(cargada.advertencias, ["aviso"])

    def test_archivo_invalido(self):
        with tempfile.TemporaryDirectory() as carpeta:
            ruta = Path(carpeta) / "malo.json"
            ruta.write_text("{no es json", encoding="utf-8")
            with self.assertRaises(ValueError):
                sesion.cargar(ruta)


if __name__ == "__main__":
    unittest.main()
