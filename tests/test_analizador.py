"""Pruebas del módulo de análisis de comprobantes XML."""

import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.core.analizador as az  # noqa: E402
from app.core.analizador import (  # noqa: E402
    Comprobante,
    calcular_totales,
    desanidar_comprobante,
    exportar_csv,
    listar_xmls,
    parsear_comprobante,
)

# --- XML de muestra -----------------------------------------------------------

FACTURA = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<autorizacion>
<estado>AUTORIZADO</estado>
<numeroAutorizacion>1306202601</numeroAutorizacion>
<comprobante><![CDATA[<?xml version="1.0"?><factura id="comprobante" version="2.1.0">
<infoTributaria><ambiente>2</ambiente><razonSocial>TIENDA X</razonSocial>
<ruc>0999999999001</ruc><claveAcceso>1234567890123456789012345678901234567890123456789</claveAcceso>
<codDoc>01</codDoc><estab>763</estab><ptoEmi>003</ptoEmi><secuencial>000138516</secuencial></infoTributaria>
<infoFactura><fechaEmision>13/06/2026</fechaEmision>
<razonSocialComprador>CLIENTE UNO</razonSocialComprador><identificacionComprador>9999999999</identificacionComprador>
<totalSinImpuestos>100.00</totalSinImpuestos><totalDescuento>0.00</totalDescuento>
<totalConImpuestos>
<totalImpuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><baseImponible>80.00</baseImponible><tarifa>15</tarifa><valor>12.00</valor></totalImpuesto>
<totalImpuesto><codigo>2</codigo><codigoPorcentaje>0</codigoPorcentaje><baseImponible>20.00</baseImponible><tarifa>0</tarifa><valor>0.00</valor></totalImpuesto>
</totalConImpuestos>
<importeTotal>112.00</importeTotal></infoFactura>
<detalles>
<detalle><descripcion>PRODUCTO A</descripcion><cantidad>2.000000</cantidad><precioUnitario>40.000000</precioUnitario><descuento>0.00</descuento><precioTotalSinImpuesto>80.00</precioTotalSinImpuesto>
<impuestos><impuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><tarifa>15</tarifa><baseImponible>80.00</baseImponible><valor>12.00</valor></impuesto></impuestos></detalle>
</detalles></factura>]]></comprobante>
</autorizacion>"""

NOTA_CREDITO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<autorizacion><estado>AUTORIZADO</estado>
<comprobante><![CDATA[<notaCredito id="comprobante" version="1.1.0">
<infoTributaria><razonSocial>TIENDA X</razonSocial><ruc>0999999999001</ruc>
<claveAcceso>9999999990123456789012345678901234567890123456789</claveAcceso>
<codDoc>04</codDoc><estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000000010</secuencial></infoTributaria>
<infoNotaCredito><fechaEmision>15/06/2026</fechaEmision>
<razonSocialComprador>CLIENTE UNO</razonSocialComprador><identificacionComprador>9999999999</identificacionComprador>
<totalSinImpuestos>50.00</totalSinImpuestos>
<totalConImpuestos><totalImpuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><baseImponible>50.00</baseImponible><tarifa>15</tarifa><valor>7.50</valor></totalImpuesto></totalConImpuestos>
<valorModificacion>57.50</valorModificacion></infoNotaCredito>
<detalles><detalle><descripcion>DEVOLUCION</descripcion><cantidad>1.000000</cantidad><precioUnitario>50.000000</precioUnitario><descuento>0.00</descuento><precioTotalSinImpuesto>50.00</precioTotalSinImpuesto>
<impuestos><impuesto><codigo>2</codigo><codigoPorcentaje>4</codigoPorcentaje><tarifa>15</tarifa><baseImponible>50.00</baseImponible><valor>7.50</valor></impuesto></impuestos></detalle></detalles>
</notaCredito>]]></comprobante></autorizacion>"""

RETENCION = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<autorizacion><estado>AUTORIZADO</estado>
<comprobante><![CDATA[<comprobanteRetencion id="comprobante" version="1.0.0">
<infoTributaria><razonSocial>EMPRESA RETENEDORA</razonSocial><ruc>0999999999001</ruc>
<claveAcceso>7777777770123456789012345678901234567890123456789</claveAcceso>
<codDoc>07</codDoc><estab>001</estab><ptoEmi>001</ptoEmi><secuencial>000000005</secuencial></infoTributaria>
<infoCompRetencion><fechaEmision>20/06/2026</fechaEmision><periodoFiscal>06/2026</periodoFiscal>
<razonSocialSujetoRetenido>PROVEEDOR X</razonSocialSujetoRetenido><identificacionSujetoRetenido>1799999999001</identificacionSujetoRetenido></infoCompRetencion>
<impuestos>
<impuesto><codigo>1</codigo><codigoRetencion>312</codigoRetencion><baseImponible>100.00</baseImponible><porcentajeRetener>1.75</porcentajeRetener><valorRetenido>1.75</valorRetenido></impuesto>
<impuesto><codigo>2</codigo><codigoRetencion>3</codigoRetencion><baseImponible>15.00</baseImponible><porcentajeRetener>70.00</porcentajeRetener><valorRetenido>10.50</valorRetenido></impuesto>
</impuestos></comprobanteRetencion>]]></comprobante></autorizacion>"""

XML_CORRUPTO = "<autorizacion><comprobante><![CDATA[<factura> esto no cierra"


@pytest.fixture
def carpeta_muestra(tmp_path):
    (tmp_path / "factura.xml").write_text(FACTURA, encoding="utf-8")
    (tmp_path / "nota.xml").write_text(NOTA_CREDITO, encoding="utf-8")
    (tmp_path / "retencion.xml").write_text(RETENCION, encoding="utf-8")
    (tmp_path / "malo.xml").write_text(XML_CORRUPTO, encoding="utf-8")
    (tmp_path / "ignorar.txt").write_text("no es xml", encoding="utf-8")
    sub = tmp_path / "subcarpeta"
    sub.mkdir()
    (sub / "otra.xml").write_text(FACTURA, encoding="utf-8")
    return tmp_path


# --- desanidar_comprobante ----------------------------------------------------


def test_desanidar_extrae_cdata():
    interno = desanidar_comprobante(FACTURA)
    assert "<factura" in interno
    assert "autorizacion" not in interno


def test_desanidar_comprobante_directo():
    directo = "<factura><infoTributaria><codDoc>01</codDoc></infoTributaria></factura>"
    assert desanidar_comprobante(directo) == directo


# --- parsear_comprobante: factura --------------------------------------------


def test_parsear_factura(tmp_path):
    ruta = tmp_path / "f.xml"
    ruta.write_text(FACTURA, encoding="utf-8")
    c = parsear_comprobante(str(ruta))
    assert c.error is None
    assert c.cod_doc == "01"
    assert c.tipo_nombre == "Factura"
    assert c.numero == "763-003-000138516"
    assert c.ruc_emisor == "0999999999001"
    assert c.razon_social_emisor == "TIENDA X"
    assert c.razon_social_receptor == "CLIENTE UNO"
    assert c.fecha_emision == date(2026, 6, 13)
    assert c.importe_total == 112.00
    assert c.signo == 1
    assert c.base_gravada == 80.00
    assert c.iva == 12.00
    assert c.base_cero == 20.00
    assert len(c.detalles) == 1
    assert c.detalles[0].descripcion == "PRODUCTO A"
    assert c.detalles[0].cantidad == 2.0


# --- nota de crédito: signo negativo -----------------------------------------


def test_parsear_nota_credito_negativa(tmp_path):
    ruta = tmp_path / "nc.xml"
    ruta.write_text(NOTA_CREDITO, encoding="utf-8")
    c = parsear_comprobante(str(ruta))
    assert c.error is None
    assert c.cod_doc == "04"
    assert c.signo == -1
    assert c.importe_total == 57.50  # valor bruto
    assert c.total_con_signo == -57.50  # con signo
    assert c.iva == -7.50
    assert c.base_gravada == -50.00


# --- retención: valor retenido, sin IVA de venta -----------------------------


def test_parsear_retencion(tmp_path):
    ruta = tmp_path / "ret.xml"
    ruta.write_text(RETENCION, encoding="utf-8")
    c = parsear_comprobante(str(ruta))
    assert c.error is None
    assert c.cod_doc == "07"
    assert c.tipo_nombre == "Comprobante de Retención"
    assert c.razon_social_receptor == "PROVEEDOR X"
    assert c.valor_retenido == pytest.approx(12.25)
    assert c.iva == 0.0  # una retención no aporta IVA de venta


# --- archivo corrupto ---------------------------------------------------------


def test_parsear_corrupto_no_lanza(tmp_path):
    ruta = tmp_path / "malo.xml"
    ruta.write_text(XML_CORRUPTO, encoding="utf-8")
    c = parsear_comprobante(str(ruta))
    assert c.error is not None
    assert isinstance(c, Comprobante)


def test_parsear_inexistente_no_lanza(tmp_path):
    c = parsear_comprobante(str(tmp_path / "no_existe.xml"))
    assert c.error is not None


# --- listar_xmls: no recursivo -----------------------------------------------


def test_listar_xmls_no_recursivo(carpeta_muestra):
    rutas = listar_xmls(str(carpeta_muestra))
    nombres = {os.path.basename(r) for r in rutas}
    assert nombres == {"factura.xml", "nota.xml", "retencion.xml", "malo.xml"}
    assert "otra.xml" not in nombres  # no entra a subcarpeta
    assert "ignorar.txt" not in nombres


def test_listar_xmls_carpeta_inexistente():
    assert listar_xmls("/ruta/que/no/existe") == []


# --- calcular_totales ---------------------------------------------------------


def test_calcular_totales_lote(carpeta_muestra):
    comps = az.parsear_carpeta(str(carpeta_muestra))
    tot = calcular_totales(comps)
    assert tot.conteo == 3  # factura + nota + retención (el corrupto no cuenta)
    assert tot.con_error == 1
    # Total con IVA: 112.00 (factura) - 57.50 (NC) + 0 (retención sin importe)
    assert tot.total_con_iva == pytest.approx(54.50)
    # Base gravada: 80 (factura) - 50 (NC)
    assert tot.total_sin_iva == pytest.approx(30.00)
    # IVA: 12 (factura) - 7.50 (NC)
    assert tot.iva_total == pytest.approx(4.50)
    # Base 0%: 20 (factura)
    assert tot.base_iva_0 == pytest.approx(20.00)
    assert tot.total_retenido == pytest.approx(12.25)
    # Desglose por tarifa: 15% y 0%
    assert 15.0 in tot.por_tarifa
    assert 0.0 in tot.por_tarifa
    assert tot.por_tarifa[15.0].iva == pytest.approx(4.50)


def test_totales_lote_vacio():
    tot = calcular_totales([])
    assert tot.conteo == 0
    assert tot.total_con_iva == 0.0


# --- exportación --------------------------------------------------------------


def test_exportar_csv(carpeta_muestra, tmp_path):
    comps = az.parsear_carpeta(str(carpeta_muestra))
    tot = calcular_totales(comps)
    salida = tmp_path / "salida.csv"
    exportar_csv(comps, tot, str(salida))
    assert salida.exists()
    contenido = salida.read_text(encoding="utf-8-sig")
    assert "Nº Comprobante" in contenido
    assert "RESUMEN DEL LOTE" in contenido
    assert "TIENDA X" in contenido


# --- validación contra XMLs reales (si existen) ------------------------------

_REALES = os.path.join(
    "/private/tmp/claude-501/-Users-rolo1410-Documents-KUYA-PROYECTOS-DESCARGA-COMPROBANTES",
    "75c59aa1-2d1e-4f08-8d80-228c194e1bdc/scratchpad/descargas_pag/recibidos_2026_06_todos",
)


@pytest.mark.skipif(not os.path.isdir(_REALES), reason="XMLs reales no disponibles")
def test_xmls_reales_se_parsean_sin_error():
    comps = az.parsear_carpeta(_REALES)
    assert len(comps) == 45
    sin_error = [c for c in comps if c.error is None]
    assert len(sin_error) == 45
    # Todas son facturas con clave de acceso y total positivo.
    for c in sin_error:
        assert c.cod_doc == "01"
        assert len(c.clave_acceso) == 49
        assert c.importe_total > 0
    tot = calcular_totales(comps)
    assert tot.conteo == 45
    assert tot.total_con_iva > 0
