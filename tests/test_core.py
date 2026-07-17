"""Pruebas del núcleo de cálculo.

Usan un archivo de muestra 100 % sintético (`tests/datos/recibidos_sintetico.txt`)
que replica las particularidades del formato real del SRI: codificación cp1252
(con Ñ), decimales sin cero inicial (`.47`), receptores a cédula y a RUC,
un comprobante duplicado y uno cuyo total no cuadra (simula ICE).
"""
from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.core import calculadora, clasificador, parser
from app.core.models import Comprobante

ARCHIVO_MUESTRA = Path(__file__).resolve().parent / "datos" / "recibidos_sintetico.txt"
RUC = "9999999999001"
CEDULA = "9999999999"
PERIODO = "2026-06"


def _comprobante(**cambios) -> Comprobante:
    base = dict(
        ruc_emisor="9990000009001",
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
        self.assertEqual(parser.ruc_desde_nombre_archivo("9999999999001_Recibidos.txt"), RUC)
        self.assertIsNone(parser.ruc_desde_nombre_archivo("otro_archivo.txt"))

    def test_lee_archivo_muestra(self):
        resultado = parser.leer_archivo(ARCHIVO_MUESTRA)
        # 6 filas de datos: 1 duplicada se descarta → 5 comprobantes
        self.assertEqual(len(resultado.comprobantes), 5)
        self.assertEqual(resultado.periodos, [PERIODO])
        # La Ñ confirma que la codificación cp1252 se decodificó bien.
        emisores = [c.razon_social_emisor for c in resultado.comprobantes]
        self.assertIn("COMPAÑIA DE PRUEBAS ÑUFLO S.A.", emisores)

    def test_advertencias_duplicado_y_descuadre(self):
        resultado = parser.leer_archivo(ARCHIVO_MUESTRA)
        self.assertEqual(len(resultado.advertencias), 2)
        self.assertTrue(any("duplicado" in a for a in resultado.advertencias))
        self.assertTrue(any("no cuadra" in a for a in resultado.advertencias))


class TestComprasArchivoMuestra(unittest.TestCase):
    def setUp(self):
        self.resultado = parser.leer_archivo(ARCHIVO_MUESTRA)

    def test_clasificacion_sugerida_solo_ruc(self):
        clasificador.sugerir_clasificacion(self.resultado.comprobantes, RUC)
        compras = calculadora.calcular_compras(self.resultado.comprobantes, PERIODO)
        self.assertEqual(compras.c500, Decimal("103.13"))   # facturas al RUC: 100 + 3.13
        self.assertEqual(compras.c520, Decimal("15.47"))
        self.assertEqual(compras.c502, Decimal("35"))       # facturas a la cédula: 25 + 10
        self.assertEqual(compras.c522, Decimal("5.25"))
        self.assertEqual(compras.c507, Decimal("10"))
        self.assertEqual(compras.c509, Decimal("148.13"))
        self.assertEqual(compras.c529, Decimal("20.72"))
        self.assertEqual(compras.c564, Decimal("15.47"))
        self.assertEqual(compras.c115, 5)

    def test_todas_con_credito(self):
        clasificador.marcar_todas_con_credito(self.resultado.comprobantes)
        compras = calculadora.calcular_compras(self.resultado.comprobantes, PERIODO)
        self.assertEqual(compras.c500, Decimal("138.13"))
        self.assertEqual(compras.c520, Decimal("20.72"))
        self.assertEqual(compras.c502, Decimal("0"))
        self.assertEqual(compras.c564, Decimal("20.72"))
        self.assertEqual(compras.c565, Decimal("0.00"))

    def test_resumen_impuesto_a_pagar(self):
        clasificador.sugerir_clasificacion(self.resultado.comprobantes, RUC)
        declaracion = calculadora.calcular_declaracion(
            self.resultado.comprobantes, PERIODO, ventas_brutas=Decimal("200"),
            advertencias=self.resultado.advertencias,
        )
        self.assertEqual(declaracion.ventas.c421, Decimal("30.00"))  # 200 × 15 %
        self.assertEqual(declaracion.resumen.impuesto_a_pagar, Decimal("14.53"))
        self.assertEqual(declaracion.resumen.credito_a_favor, Decimal("0"))
        self.assertEqual(len(declaracion.advertencias), 2)

    def test_resumen_credito_a_favor(self):
        clasificador.sugerir_clasificacion(self.resultado.comprobantes, RUC)
        declaracion = calculadora.calcular_declaracion(
            self.resultado.comprobantes, PERIODO, ventas_brutas=Decimal("10")
        )
        self.assertEqual(declaracion.resumen.impuesto_a_pagar, Decimal("0"))
        self.assertEqual(declaracion.resumen.credito_a_favor, Decimal("13.97"))


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
        a_cedula = _comprobante(clave_acceso="W" * 49, identificacion_receptor=CEDULA)
        clasificador.sugerir_clasificacion([al_ruc, a_cedula], RUC)
        self.assertTrue(al_ruc.con_credito)
        self.assertFalse(a_cedula.con_credito)


class TestVentas(unittest.TestCase):
    def test_ventas_formulario(self):
        ventas = calculadora.calcular_ventas(Decimal("1000"))
        self.assertEqual(ventas.c401, Decimal("1000"))
        self.assertEqual(ventas.c411, Decimal("1000"))
        self.assertEqual(ventas.c421, Decimal("150.00"))  # 1000 × 15 %
        self.assertEqual(ventas.c499, Decimal("150.00"))

    def test_ventas_con_notas_de_credito(self):
        ventas = calculadora.calcular_ventas(Decimal("1000"), notas_credito_emitidas=Decimal("100"))
        self.assertEqual(ventas.c401, Decimal("1000"))
        self.assertEqual(ventas.c411, Decimal("900"))
        self.assertEqual(ventas.c421, Decimal("135.00"))


if __name__ == "__main__":
    unittest.main()
