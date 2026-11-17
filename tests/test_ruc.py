from __future__ import annotations

import pytest

from app.core import ruc

NATURAL = "1710034065001"
SOCIEDAD = "1790011674001"
PUBLICA = "1760001550001"


def test_persona_natural_valida():
    info = ruc.analizar(NATURAL)
    assert info.tipo == ruc.NATURAL
    assert info.cedula == "1710034065"
    assert info.carpeta == "1710034065"
    assert info.advertencias == []


def test_persona_natural_cedula_invalida_se_rechaza():
    with pytest.raises(ruc.RucInvalido, match="cédula"):
        ruc.analizar("1710034066001")


def test_persona_natural_debe_terminar_en_001():
    with pytest.raises(ruc.RucInvalido, match="001"):
        ruc.analizar("1710034065002")


def test_sociedad_valida():
    info = ruc.analizar(SOCIEDAD)
    assert info.tipo == ruc.SOCIEDAD
    assert info.cedula is None
    assert info.carpeta == SOCIEDAD
    assert info.advertencias == []


def test_sociedad_con_verificador_incorrecto_solo_advierte():
    info = ruc.analizar("1790011675001")
    assert info.tipo == ruc.SOCIEDAD
    assert info.advertencias


def test_entidad_publica():
    info = ruc.analizar(PUBLICA)
    assert info.tipo == ruc.PUBLICA
    assert info.carpeta == PUBLICA
    assert info.advertencias == []


def test_entidad_publica_verificador_incorrecto_advierte():
    assert ruc.analizar("1760001560001").advertencias


@pytest.mark.parametrize("valor", ["1770001550001", "1780001550001"])
def test_tercer_digito_7_u_8_se_rechaza(valor):
    with pytest.raises(ruc.RucInvalido, match="Tercer dígito"):
        ruc.analizar(valor)


@pytest.mark.parametrize("valor", ["0010034065001", "2510034065001", "9990011674001"])
def test_provincia_invalida(valor):
    with pytest.raises(ruc.RucInvalido, match="provincia"):
        ruc.analizar(valor)


def test_provincia_30_aceptada():
    cedula = "300000000"
    # Calcula el verificador para una cédula de la provincia 30.
    for d in range(10):
        if ruc.cedula_valida(cedula + str(d)):
            assert ruc.analizar(cedula + str(d) + "001").tipo == ruc.NATURAL
            return
    pytest.fail("no se encontró verificador")


def test_establecimiento_000():
    with pytest.raises(ruc.RucInvalido, match="000"):
        ruc.analizar("1790011674000")
    with pytest.raises(ruc.RucInvalido, match="0000"):
        ruc.analizar("1760001550000")


@pytest.mark.parametrize("valor", ["", "17900116740", "17900116740011", "17900116A4001"])
def test_longitud_y_formato(valor):
    with pytest.raises(ruc.RucInvalido):
        ruc.analizar(valor)


def test_cedula_sola_explica_que_falta_001():
    with pytest.raises(ruc.RucInvalido, match="001"):
        ruc.analizar("1710034065")


def test_espacios_se_ignoran():
    assert ruc.analizar(" 1710034065 001 ").ruc == NATURAL


def test_carpeta_de_e_identificaciones():
    assert ruc.carpeta_de(NATURAL) == "1710034065"
    assert ruc.carpeta_de(SOCIEDAD) == SOCIEDAD
    assert ruc.identificaciones_de(NATURAL) == {NATURAL, "1710034065"}
    assert ruc.identificaciones_de(SOCIEDAD) == {SOCIEDAD}
