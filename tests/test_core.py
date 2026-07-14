"""Pruebas del núcleo de cálculo.

Las pruebas que dependen del archivo real de junio 2026 se omiten si el archivo
no está presente (p. ej. en CI: el archivo contiene datos personales y no se
versiona). Las pruebas con datos sintéticos corren siempre.
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core import calculadora, clasificador, parser
from app.core.models import Comprobante

ARCHIVO_EJEMPLO = Path(__file__).resolve().parent.parent / "0603545351001_Recibidos.txt"
RUC = "0603545351001"
PERIODO = "2026-06"

requiere_archivo = unittest.skipUnless(
    ARCHIVO_EJEMPLO.exists(),
    "archivo real de recibidos no disponible (no se versiona por contener datos personales)",
)


def _comprobante(**cambios) -> Comprobante:
    base = dict(
        ruc_emisor="9999999999001",
        razon_social_emisor="PRUEBA S.A.",
        tipo_comprobante="Factura",
        serie_comprobante="001-001-000000001",
        clave_acceso="X" * 49,
        fecha_autorizacion="01/06/2026 00:00:00",
        fecha_emision=date(2026, 6, 1),
        identificacion_receptor=RUC,
        valor_sin_impuestos=Decimal("100"),
        iva=Decimal("15"),
        importe_total=Decimal("115"),
    )
    base.update(cambios)
    return Comprobante(**base)


class TestParser(unittest.TestCase):
    def test_decimales_sin_cero_inicial(self):
        self.assertEqual(parser.parsear_decimal(".47"), Decimal("0.47"))
        self.assertEqual(parser.parsear_decimal(""), Decimal("0"))
        self.assertEqual(parser.parsear_decimal("3,75"), Decimal("3.75"))

    def test_ruc_desde_nombre(self):
        self.assertEqual(parser.ruc_desde_nombre_archivo("0603545351001_Recibidos.txt"), RUC)
        self.assertIsNone(parser.ruc_desde_nombre_archivo("otro_archivo.txt"))

    @requiere_archivo
    def test_lee_archivo_real(self):
        resultado = parser.leer_archivo(ARCHIVO_EJEMPLO)
        self.assertEqual(len(resultado.comprobantes), 45)
        self.assertEqual(resultado.periodos, [PERIODO])
        # La Ñ de "COMPAÑIA" confirma que la codificación cp1252 se decodificó bien.
        seguros = [c for c in resultado.comprobantes if c.ruc_emisor == "1791289927001"]
        self.assertIn("COMPAÑIA", seguros[0].razon_social_emisor)


@requiere_archivo
class TestComprasArchivoReal(unittest.TestCase):
    def setUp(self):
        self.resultado = parser.leer_archivo(ARCHIVO_EJEMPLO)

    def test_todas_con_credito(self):
        clasificador.marcar_todas_con_credito(self.resultado.comprobantes)
        compras = calculadora.calcular_compras(self.resultado.comprobantes, PERIODO)
        self.assertEqual(compras.c500, Decimal("1642.99"))
        self.assertEqual(compras.c520, Decimal("245.51"))
        self.assertEqual(compras.c507, Decimal("149.73"))
        self.assertEqual(compras.c502, Decimal("0"))
        self.assertEqual(compras.c509, Decimal("1792.72"))
        self.assertEqual(compras.c529, Decimal("245.51"))
        self.assertEqual(compras.c564, Decimal("245.51"))
        self.assertEqual(compras.c565, Decimal("0.00"))
        self.assertEqual(compras.c115, 45)

    def test_clasificacion_sugerida_solo_ruc(self):
        clasificador.sugerir_clasificacion(self.resultado.comprobantes, RUC)
        compras = calculadora.calcular_compras(self.resultado.comprobantes, PERIODO)
        self.assertEqual(compras.c500, Decimal("1063"))
        self.assertEqual(compras.c520, Decimal("159.45"))
        self.assertEqual(compras.c502, Decimal("579.99"))
        self.assertEqual(compras.c522, Decimal("86.06"))
        self.assertEqual(compras.c529, Decimal("245.51"))
        self.assertEqual(compras.c564, Decimal("159.45"))

    def test_resumen_impuesto_a_pagar(self):
        clasificador.marcar_todas_con_credito(self.resultado.comprobantes)
        declaracion = calculadora.calcular_declaracion(
            self.resultado.comprobantes, PERIODO, ventas_brutas=Decimal("5586.96")
        )
        self.assertEqual(declaracion.resumen.impuesto_a_pagar, Decimal("592.53"))
        self.assertEqual(declaracion.resumen.credito_a_favor, Decimal("0"))

    def test_resumen_credito_a_favor(self):
        clasificador.marcar_todas_con_credito(self.resultado.comprobantes)
        declaracion = calculadora.calcular_declaracion(
            self.resultado.comprobantes, PERIODO, ventas_brutas=Decimal("100")
        )
        self.assertEqual(declaracion.resumen.impuesto_a_pagar, Decimal("0"))
        self.assertEqual(declaracion.resumen.credito_a_favor, Decimal("230.51"))


class TestComprasSinteticas(unittest.TestCase):
    def test_nota_credito_resta_del_neto(self):
        comprobantes = [
            _comprobante(),
            _comprobante(
                tipo_comprobante="Nota de Crédito",
                clave_acceso="Y" * 49,
                valor_sin_impuestos=Decimal("20"),
                iva=Decimal("3"),
                importe_total=Decimal("23"),
            ),
        ]
        compras = calculadora.calcular_compras(comprobantes, PERIODO)
        self.assertEqual(compras.c500, Decimal("100"))  # el bruto no cambia
        self.assertEqual(compras.c510, Decimal("80"))   # el neto resta la N/C
        self.assertEqual(compras.c520, Decimal("12"))
        self.assertEqual(compras.c115, 1)  # la N/C no cuenta como comprobante recibido

    def test_nota_venta_negocio_popular(self):
        comprobantes = [
            _comprobante(
                tipo_comprobante="Nota de Venta - RISE",
                iva=Decimal("0"),
                importe_total=Decimal("100"),
            )
        ]
        compras = calculadora.calcular_compras(comprobantes, PERIODO)
        self.assertEqual(compras.c508, Decimal("100"))
        self.assertEqual(compras.c518, Decimal("100"))
        self.assertEqual(compras.c507, Decimal("0"))
        self.assertEqual(compras.c117, 1)
        self.assertEqual(compras.c115, 0)

    def test_filtra_por_periodo(self):
        comprobantes = [
            _comprobante(),
            _comprobante(clave_acceso="Z" * 49, fecha_emision=date(2026, 7, 1)),
        ]
        compras = calculadora.calcular_compras(comprobantes, PERIODO)
        self.assertEqual(compras.c115, 1)

    def test_clasificacion_sugerida_por_receptor(self):
        al_ruc = _comprobante()
        a_cedula = _comprobante(clave_acceso="W" * 49, identificacion_receptor="0603545351")
        clasificador.sugerir_clasificacion([al_ruc, a_cedula], RUC)
        self.assertTrue(al_ruc.con_credito)
        self.assertFalse(a_cedula.con_credito)


class TestVentas(unittest.TestCase):
    def test_ventas_ejemplo_formulario(self):
        ventas = calculadora.calcular_ventas(Decimal("5586.96"))
        self.assertEqual(ventas.c401, Decimal("5586.96"))
        self.assertEqual(ventas.c411, Decimal("5586.96"))
        self.assertEqual(ventas.c421, Decimal("838.04"))  # 5586.96 × 15 %
        self.assertEqual(ventas.c499, Decimal("838.04"))

    def test_ventas_con_notas_de_credito(self):
        ventas = calculadora.calcular_ventas(Decimal("1000"), notas_credito_emitidas=Decimal("100"))
        self.assertEqual(ventas.c401, Decimal("1000"))
        self.assertEqual(ventas.c411, Decimal("900"))
        self.assertEqual(ventas.c421, Decimal("135.00"))


if __name__ == "__main__":
    unittest.main()
