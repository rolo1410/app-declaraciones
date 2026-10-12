"""Pruebas del adaptador XML -> modelo de la declaración y su cálculo."""
import os
import sys
from datetime import date
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core import analizador as az  # noqa: E402
from app.core import adaptador, calculadora  # noqa: E402


def _comp_xml(**kw) -> az.Comprobante:
    """Construye un analizador.Comprobante con impuestos de cabecera."""
    impuestos = kw.pop("impuestos", [])
    c = az.Comprobante(archivo=kw.pop("archivo", "x.xml"))
    for campo, valor in kw.items():
        setattr(c, campo, valor)
    c.impuestos = impuestos
    return c


def _iva(base: float, valor: float, tarifa: float = 15.0) -> az.ImpuestoResumen:
    return az.ImpuestoResumen(codigo="2", codigo_porcentaje="4",
                              tarifa=tarifa, base_imponible=base, valor=valor)


def _cero(base: float) -> az.ImpuestoResumen:
    return az.ImpuestoResumen(codigo="2", codigo_porcentaje="0",
                              tarifa=0.0, base_imponible=base, valor=0.0)


def test_factura_gravada_mapea_base_e_iva():
    xml = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="A1",
                    fecha_emision=date(2026, 6, 10), ruc_emisor="0999999999001",
                    identificacion_receptor="9999999999001", importe_total=115.0,
                    impuestos=[_iva(100.0, 15.0)])
    m = adaptador.adaptar_comprobante(xml)
    assert m is not None
    assert m.valor_sin_impuestos == Decimal("100.00")
    assert m.iva == Decimal("15.00")
    assert m.base_tarifa_cero == Decimal("0.00")
    assert m.periodo == "2026-06"


def test_lineas_de_detalle_y_receptor_se_conservan():
    linea = az.LineaDetalle(descripcion="Arroz 1kg", cantidad=2.5, precio_unitario=1.123456,
                            descuento=0.0, precio_total_sin_impuesto=2.81, tarifa_iva=0.0)
    xml = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="A9",
                    fecha_emision=date(2026, 6, 10), importe_total=2.81,
                    razon_social_receptor="CLIENTE PRUEBA", detalles=[linea],
                    impuestos=[_cero(2.81)])
    m = adaptador.adaptar_comprobante(xml)
    assert m.razon_social_receptor == "CLIENTE PRUEBA"
    assert len(m.detalles) == 1
    assert m.detalles[0].descripcion == "Arroz 1kg"
    assert m.detalles[0].cantidad == Decimal("2.5")
    assert m.detalles[0].precio_unitario == Decimal("1.123456")
    assert m.detalles[0].precio_total == Decimal("2.81")


def test_tarifas_mixtas_separan_gravada_y_cero():
    xml = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="A2",
                    fecha_emision=date(2026, 6, 10), importe_total=145.0,
                    impuestos=[_iva(100.0, 15.0), _cero(30.0)])
    m = adaptador.adaptar_comprobante(xml)
    assert m.valor_sin_impuestos == Decimal("100.00")
    assert m.iva == Decimal("15.00")
    assert m.base_tarifa_cero == Decimal("30.00")


def test_nota_credito_entrega_magnitudes_positivas():
    # signo -1: las propiedades del analizador dan negativos; el adaptador los
    # devuelve positivos y es la calculadora quien resta.
    xml = _comp_xml(cod_doc="04", tipo_nombre="Nota de Crédito", clave_acceso="A3",
                    fecha_emision=date(2026, 6, 12), importe_total=115.0, signo=-1,
                    impuestos=[_iva(100.0, 15.0)])
    m = adaptador.adaptar_comprobante(xml)
    assert m.valor_sin_impuestos == Decimal("100.00")
    assert m.iva == Decimal("15.00")
    assert m.es_nota_credito


def test_retencion_se_ignora():
    xml = _comp_xml(cod_doc="07", tipo_nombre="Comprobante de Retención",
                    fecha_emision=date(2026, 6, 12), clave_acceso="A4")
    assert adaptador.adaptar_comprobante(xml) is None


def test_calculo_completo_gravada_menos_nota_credito():
    factura = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="F1",
                        fecha_emision=date(2026, 6, 5),
                        identificacion_receptor="9999999999001",
                        importe_total=115.0, impuestos=[_iva(100.0, 15.0)])
    nc = _comp_xml(cod_doc="04", tipo_nombre="Nota de Crédito", clave_acceso="N1",
                   fecha_emision=date(2026, 6, 20), signo=-1,
                   identificacion_receptor="9999999999001",
                   importe_total=23.0, impuestos=[_iva(20.0, 3.0)])
    res = adaptador.adaptar_comprobantes([factura, nc])
    assert len(res.comprobantes) == 2
    for c in res.comprobantes:
        c.con_credito = True
    compras = calculadora.calcular_compras(res.comprobantes, "2026-06")
    # 500 (bruto) solo suma la factura; 510/520 (neto) restan la nota de crédito.
    assert compras.c500 == Decimal("100.00")
    assert compras.c510 == Decimal("80.00")
    assert compras.c520 == Decimal("12.00")
    assert compras.c564 == Decimal("12.00")
    assert compras.c115 == 1  # la nota de crédito no cuenta en 115


def test_dedup_por_clave_de_acceso():
    a = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="DUP",
                  fecha_emision=date(2026, 6, 1), importe_total=115.0,
                  impuestos=[_iva(100.0, 15.0)])
    b = _comp_xml(cod_doc="01", tipo_nombre="Factura", clave_acceso="DUP",
                  fecha_emision=date(2026, 6, 1), importe_total=115.0,
                  impuestos=[_iva(100.0, 15.0)])
    res = adaptador.adaptar_comprobantes([a, b])
    assert len(res.comprobantes) == 1
    assert any("duplicado" in w.lower() for w in res.advertencias)
