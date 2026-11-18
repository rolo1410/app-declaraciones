"""Seguimiento mensual por cliente: declarada, enviada, cobrada y resumen."""
from __future__ import annotations

import pytest

from app.core import clientes, db


@pytest.fixture
def registro(tmp_path):
    return clientes.Registro(ruta_db=tmp_path / "c.db", base=tmp_path / "base")


@pytest.fixture
def cliente(registro):
    return registro.crear_cliente("1790011674001", "Empresa", "x")


def test_mes_sin_registro_esta_pendiente(registro, cliente):
    estado = registro.estado_mes(cliente.id, "2026-07")
    assert estado.estado == "pendiente" and not estado.cobrada and estado.resumen is None


def test_colores_declarada_y_enviada(registro, cliente):
    assert registro.marcar(cliente.id, "2026-07", "declarada", "2026-08-12").estado == "declarada"
    estado = registro.registrar_envio(cliente.id, "2026-07", "2026-08-12 10:30",
                                      "clientes/1790011674001/resultados/2026-07/envio_x")
    assert estado.estado == "enviada" and estado.envios == 1
    estado = registro.registrar_envio(cliente.id, "2026-07", "2026-08-13 09:00")
    assert estado.envios == 2 and estado.enviada_en == "2026-08-13 09:00"
    assert estado.carpeta_envio.endswith("envio_x")  # sin carpeta nueva se conserva la anterior


def test_cobro_y_desmarcar(registro, cliente):
    assert registro.marcar(cliente.id, "2026-07", "cobrada", "2026-08-20").cobrada
    assert not registro.marcar(cliente.id, "2026-07", "cobrada", None).cobrada


def test_estados_del_anio_e_historial(registro, cliente):
    otro = registro.crear_cliente("1760001550001", "Municipio", "y")
    registro.marcar(cliente.id, "2026-01", "declarada", "2026-02-10")
    registro.marcar(cliente.id, "2026-07", "declarada", "2026-08-12")
    registro.marcar(otro.id, "2026-07", "cobrada", "2026-08-20")
    registro.marcar(cliente.id, "2025-12", "declarada", "2026-01-10")
    anio = registro.estados_del_anio(2026)
    assert sorted(anio[cliente.id]) == [1, 7] and list(anio[otro.id]) == [7]
    assert [e.periodo for e in registro.historial(cliente.id)] == ["2026-07", "2026-01", "2025-12"]


def test_resumen_del_calculo(registro, cliente):
    resumen = {"impuesto_generado": "150.00", "credito_tributario": "20.72",
               "impuesto_a_pagar": "129.28", "credito_a_favor": "0", "comprobantes": 5}
    registro.guardar_resumen(cliente.id, "2026-07", resumen, "2026-08-12 10:00")
    estado = registro.estado_mes(cliente.id, "2026-07")
    assert estado.resumen == resumen and estado.calculada_en == "2026-08-12 10:00"
    assert estado.estado == "pendiente"  # calcular no es declarar


@pytest.mark.parametrize("periodo, fecha", [("2026-13", "2026-01-01"), ("julio", "2026-01-01"),
                                            ("2026-07", "12/08/2026"), ("2026-07", "2026-02-30")])
def test_datos_invalidos(registro, cliente, periodo, fecha):
    with pytest.raises(clientes.ErrorClientes):
        registro.marcar(cliente.id, periodo, "declarada", fecha)


def test_marcar_deja_rastro_en_bitacora(registro, cliente):
    registro.marcar(cliente.id, "2026-07", "declarada", "2026-08-12")
    with db.abrir(registro._ruta_db) as cx:
        acciones = [r[0] for r in cx.execute("SELECT accion FROM bitacora WHERE id_cliente = ?",
                                             (cliente.id,))]
    assert "declarada_marcada" in acciones
