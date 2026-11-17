from __future__ import annotations

import json

import pytest

from app.core import cifrado

CLAVE = "clave-de-prueba-ficticia"
RUC_A = "1790011674001"
RUC_B = "1710034065001"
PORTAL = "sri_en_linea"


def test_ida_y_vuelta():
    llave = cifrado.generar_llave()
    nonce, c = cifrado.cifrar(llave, 1, CLAVE, RUC_A, PORTAL)
    assert len(nonce) == 12
    assert CLAVE.encode() not in c
    assert cifrado.descifrar(llave, 1, nonce, c, RUC_A, PORTAL) == CLAVE


def test_nonce_distinto_en_cada_cifrado():
    llave = cifrado.generar_llave()
    a = cifrado.cifrar(llave, 1, CLAVE, RUC_A, PORTAL)
    b = cifrado.cifrar(llave, 1, CLAVE, RUC_A, PORTAL)
    assert a[0] != b[0] and a[1] != b[1]


@pytest.mark.parametrize("ruc,portal,version", [
    (RUC_B, PORTAL, 1),       # otro cliente
    (RUC_A, "otro", 1),       # otro portal
    (RUC_A, PORTAL, 2),       # otra versión de llave
])
def test_datos_asociados_distintos_fallan(ruc, portal, version):
    llave = cifrado.generar_llave()
    nonce, c = cifrado.cifrar(llave, 1, CLAVE, RUC_A, PORTAL)
    with pytest.raises(cifrado.ClaveIlegible):
        cifrado.descifrar(llave, version, nonce, c, ruc, portal)


def test_llave_distinta_falla_y_no_filtra_la_clave():
    nonce, c = cifrado.cifrar(cifrado.generar_llave(), 1, CLAVE, RUC_A, PORTAL)
    with pytest.raises(cifrado.ClaveIlegible) as e:
        cifrado.descifrar(cifrado.generar_llave(), 1, nonce, c, RUC_A, PORTAL)
    assert CLAVE not in str(e.value)


def test_cifrado_alterado_falla():
    llave = cifrado.generar_llave()
    nonce, c = cifrado.cifrar(llave, 1, CLAVE, RUC_A, PORTAL)
    alterado = bytes([c[0] ^ 1]) + c[1:]
    with pytest.raises(cifrado.ClaveIlegible):
        cifrado.descifrar(llave, 1, nonce, alterado, RUC_A, PORTAL)


def test_verificador():
    llave = cifrado.generar_llave()
    cifrado.comprobar_verificador(llave, cifrado.verificador(llave))
    with pytest.raises(cifrado.LlaveNoCorresponde):
        cifrado.comprobar_verificador(cifrado.generar_llave(), cifrado.verificador(llave))


def test_copia_de_emergencia_ida_y_vuelta():
    llave = cifrado.generar_llave()
    datos = cifrado.exportar_copia(llave, 1, "frase de paso larga")
    doc = json.loads(datos)
    assert doc["kdf"]["algoritmo"] == "argon2id"
    assert cifrado.importar_copia(datos, "frase de paso larga") == (1, llave)


def test_copia_frase_incorrecta():
    datos = cifrado.exportar_copia(cifrado.generar_llave(), 1, "frase de paso larga")
    with pytest.raises(cifrado.CopiaInvalida, match="frase"):
        cifrado.importar_copia(datos, "otra frase cualquiera")


def test_copia_frase_corta_rechazada():
    with pytest.raises(ValueError):
        cifrado.exportar_copia(cifrado.generar_llave(), 1, "corta")


@pytest.mark.parametrize("datos", [b"", b"no es json", b'{"formato": "otro"}'])
def test_copia_danada(datos):
    with pytest.raises(cifrado.CopiaInvalida):
        cifrado.importar_copia(datos, "frase de paso larga")


def test_copia_con_version_manipulada_falla():
    datos = cifrado.exportar_copia(cifrado.generar_llave(), 1, "frase de paso larga")
    doc = json.loads(datos)
    doc["version_llave"] = 2
    with pytest.raises(cifrado.CopiaInvalida):
        cifrado.importar_copia(json.dumps(doc).encode(), "frase de paso larga")


def test_llavero_sistema_con_backend_en_memoria(llavero_memoria):
    llavero = cifrado.LlaveroSistema()
    assert llavero.leer(1) is None
    llave = cifrado.generar_llave()
    llavero.guardar(1, llave)
    assert llavero.leer(1) == llave
    assert ("ComprobantesSRI", "llave_maestra_v1") in llavero_memoria.datos


def test_backend_real_detecta_fail():
    import keyring
    from keyring.backends import fail

    assert cifrado.backend_real()[0] is True  # el de memoria cuenta como real
    keyring.set_keyring(fail.Keyring())
    assert cifrado.backend_real()[0] is False


def test_llavero_archivo_sin_almacen_del_sistema(tmp_path):
    pedidas = []

    def frase(nueva):
        pedidas.append(nueva)
        return "frase de paso larga"

    llavero = cifrado.LlaveroArchivo(tmp_path, frase)
    assert llavero.leer(1) is None
    llave = cifrado.generar_llave()
    llavero.guardar(1, llave)
    assert pedidas == [True]
    # Otra sesión de la app: pide la frase para leer.
    otro = cifrado.LlaveroArchivo(tmp_path, frase)
    assert otro.leer(1) == llave
    assert pedidas == [True, False]


def test_llavero_archivo_frase_incorrecta_y_cancelada(tmp_path):
    cifrado.LlaveroArchivo(tmp_path, lambda n: "frase de paso larga").guardar(
        1, cifrado.generar_llave())
    with pytest.raises(cifrado.CopiaInvalida):
        cifrado.LlaveroArchivo(tmp_path, lambda n: "otra frase larga!").leer(1)
    with pytest.raises(cifrado.LlaveNoDisponible):
        cifrado.LlaveroArchivo(tmp_path, lambda n: None).leer(1)
