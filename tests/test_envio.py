"""Envío de la declaración por correo: datos, perfil, informe y SMTP."""
from __future__ import annotations

import sqlite3
import zipfile
from datetime import date
from decimal import Decimal
from email import message_from_bytes

import pytest

from app.core import calculadora, clientes, correo, db, informe, perfil
from app.core.models import Comprobante

RUC_NATURAL = "1710034065001"
RUC_EMPRESA = "1790011674001"


def _comprobante(clave: str, dia: int = 1, mes: int = 7) -> Comprobante:
    return Comprobante(
        ruc_emisor="1790011674001", razon_social_emisor="PROVEEDOR S.A.",
        tipo_comprobante="Factura", serie_comprobante="001-001-000000001",
        clave_acceso=clave, fecha_autorizacion="", fecha_emision=date(2026, mes, dia),
        identificacion_receptor=RUC_NATURAL, valor_sin_impuestos=Decimal("100"),
        iva=Decimal("15"), importe_total=Decimal("115"),
    )


def _clave(n: int) -> str:
    return f"{n:049d}"


@pytest.fixture
def registro(tmp_path):
    return clientes.Registro(ruta_db=tmp_path / "c.db", base=tmp_path / "base")


@pytest.fixture
def declaracion():
    comps = [_comprobante(_clave(1)), _comprobante(_clave(2), dia=15),
             _comprobante(_clave(3), mes=6)]  # otro período: no entra
    return calculadora.calcular_declaracion(comps, "2026-07", ventas_brutas=Decimal("1000"))


# -- base de datos -----------------------------------------------------------------

def test_migracion_de_v1_a_v2_conserva_los_clientes(tmp_path):
    ruta = tmp_path / "v1.db"
    cx = sqlite3.connect(ruta, isolation_level=None)
    for sentencia in db._sentencias(db.MIGRACIONES[0]):
        cx.execute(sentencia)
    cx.execute("PRAGMA user_version = 1")
    cx.execute("INSERT INTO clientes (ruc, tipo_contribuyente, cedula, carpeta, nombre,"
               " activo, creado_en, actualizado_en) VALUES"
               " ('1790011674001','sociedad',NULL,'1790011674001','X',1,'t','t')")
    cx.close()

    reg = clientes.Registro(ruta_db=ruta, base=tmp_path / "base")
    [c] = reg.listar()
    assert c.nombre == "X" and c.correo is None
    reg.fijar_correo(c.id, "cliente@ejemplo.ec")
    assert reg.obtener(c.id).correo == "cliente@ejemplo.ec"


def test_correo_del_cliente_se_normaliza_y_valida(registro):
    c = registro.crear_cliente(RUC_EMPRESA, "Empresa", "x", correo=" a@x.ec ; b@y.com ")
    assert c.correo == "a@x.ec, b@y.com"
    with pytest.raises(clientes.ErrorClientes):
        registro.fijar_correo(c.id, "no-es-correo")
    registro.fijar_correo(c.id, "")
    assert registro.obtener(c.id).correo is None


def test_clave_smtp_cifrada_y_recuperable(registro):
    assert not registro.tiene_clave_smtp()
    registro.guardar_clave_smtp("app-password-123")
    assert registro.tiene_clave_smtp()
    with db.abrir(registro._ruta_db) as cx:
        guardado = cx.execute("SELECT clave_cifrada FROM secretos").fetchone()[0]
    assert b"app-password-123" not in bytes(guardado)
    assert registro.clave_smtp() == "app-password-123"
    registro.borrar_clave_smtp()
    with pytest.raises(clientes.ErrorClientes):
        registro.clave_smtp()


# -- perfil ------------------------------------------------------------------------

def test_perfil_se_guarda_y_lee(tmp_path):
    p = perfil.Perfil()
    p.declarante.nombre = "Ana Contadora"
    p.declarante.correo = "ana@estudio.ec"
    p.declarante.cargo = "Contadora Pública Autorizada"
    p.declarante.registro = "17-1234"
    p.correo = perfil.ServidorCorreo("smtp.gmail.com", 465, "ssl", "ana@estudio.ec", "Ana", True)
    perfil.guardar(p)
    leido = perfil.leer()
    assert leido == p
    assert "Reg. 17-1234" in leido.declarante.lineas_firma()[1]
    assert leido.correo.configurado


def test_perfil_ilegible_vuelve_a_valores_por_defecto():
    perfil.ruta().parent.mkdir(parents=True, exist_ok=True)
    perfil.ruta().write_text("{no es json")
    assert perfil.leer() == perfil.Perfil()


def test_perfil_invalido_no_se_guarda():
    p = perfil.Perfil()
    p.correo.puerto = 0
    with pytest.raises(ValueError):
        perfil.guardar(p)


def test_logo_se_copia_a_la_carpeta_de_datos(tmp_path):
    origen = tmp_path / "Mi Logo.PNG"
    origen.write_bytes(b"\x89PNG\r\n")
    nombre = perfil.importar_logo(origen)
    p = perfil.Perfil()
    p.declarante.logo = nombre
    assert p.ruta_logo() is not None and p.ruta_logo().read_bytes() == b"\x89PNG\r\n"
    with pytest.raises(ValueError):
        perfil.importar_logo(tmp_path / "logo.bmp")


# -- informe -----------------------------------------------------------------------

@pytest.mark.parametrize("ruc, periodo, esperada", [
    ("1790011674001", "2026-07", date(2026, 8, 24)),   # 9.º dígito 7 → 22/08 (sábado) → lunes 24
    ("1710034065001", "2026-12", date(2027, 1, 20)),   # 9.º dígito 6 → 20 de enero del año siguiente
    ("1760001550001", "2026-07", date(2026, 8, 18)),   # 9.º dígito 5 → 18/08 (martes)
])
def test_fecha_limite_por_noveno_digito(ruc, periodo, esperada):
    assert informe.fecha_limite(ruc, periodo) == esperada


def test_fecha_limite_con_datos_invalidos():
    assert informe.fecha_limite("123", "2026-07") is None
    assert informe.fecha_limite(RUC_NATURAL, "julio") is None


def test_xml_se_buscan_por_clave_de_acceso(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "f1.xml").write_text(f"<x><claveAcceso>{_clave(1)}</claveAcceso></x>")
    (tmp_path / "f2.xml").write_text(f"<numeroAutorizacion>{_clave(2)}</numeroAutorizacion>")
    (tmp_path / "otro.xml").write_text(f"<claveAcceso>{_clave(9)}</claveAcceso>")
    (tmp_path / "copia.xml").write_text(f"<claveAcceso>{_clave(1)}</claveAcceso>")
    encontrados = informe.xml_de_comprobantes(tmp_path, {_clave(1), _clave(2), _clave(3)})
    assert sorted(p.name for p in encontrados) == ["f1.xml", "f2.xml"]


def test_paquete_completo(tmp_path, declaracion):
    descargas = tmp_path / "descargas"
    descargas.mkdir()
    (descargas / "f1.xml").write_text(f"<claveAcceso>{_clave(1)}</claveAcceso>")
    d = perfil.Declarante(nombre="Ana", correo="ana@estudio.ec")
    paquete = informe.armar_paquete(
        declaracion, tmp_path / "envio", contribuyente=("Juan", RUC_NATURAL),
        declarante=d, carpeta_xml=descargas)
    nombres = sorted(p.name for p in paquete.adjuntos)
    assert nombres == ["comprobantes_2026-07.zip", "declaracion_iva_2026-07.pdf",
                       "declaracion_iva_2026-07.xlsx"]
    assert paquete.xml_incluidos == 1 and paquete.xml_faltantes == 1
    with zipfile.ZipFile(tmp_path / "envio" / "comprobantes_2026-07.zip") as zf:
        assert zf.namelist() == ["f1.xml"]
    assert paquete.tamano > 0


def test_cuerpo_del_correo_trae_resumen_y_firma(declaracion):
    d = perfil.Declarante(nombre="Ana", cargo="CPA", correo="ana@estudio.ec")
    texto = informe.cuerpo(declaracion, "Juan Pérez", RUC_NATURAL, d)
    assert "julio 2026" in texto and "Fecha límite" in texto
    assert "IMPUESTO A PAGAR" in texto or "Crédito a favor" in texto
    assert texto.rstrip().endswith("ana@estudio.ec")
    assert informe.asunto(declaracion, "Juan") == "Declaración de IVA julio 2026 — Juan"


# -- SMTP --------------------------------------------------------------------------

class _SMTPFalso:
    instancias: list = []

    def __init__(self, host, puerto, timeout=None, context=None):
        self.host, self.puerto = host, puerto
        self.enviados, self.login_con = [], None
        _SMTPFalso.instancias.append(self)

    def starttls(self, context=None):
        self.tls = True

    def login(self, usuario, clave):
        if clave != "buena":
            import smtplib
            raise smtplib.SMTPAuthenticationError(535, b"no")
        self.login_con = usuario

    def send_message(self, msg):
        self.enviados.append(msg)
        return {}

    def quit(self):
        pass


def _servidor(seguridad="ssl"):
    return perfil.ServidorCorreo("smtp.ejemplo.ec", 465, seguridad, "ana@estudio.ec", "Ana CPA",
                                 copia_a_mi=True)


def test_mensaje_con_adjuntos_y_copia_oculta(tmp_path):
    adjunto = tmp_path / "declaracion.pdf"
    adjunto.write_bytes(b"%PDF-1.4")
    msg = correo.construir(_servidor(), ["juan@cliente.ec"], "Asunto", "Hola", [adjunto],
                           responder_a="otra@estudio.ec")
    assert msg["From"] == "Ana CPA <ana@estudio.ec>"
    assert msg["Bcc"] == "ana@estudio.ec" and msg["Reply-To"] == "otra@estudio.ec"
    leido = message_from_bytes(msg.as_bytes())
    nombres = [p.get_filename() for p in leido.walk() if p.get_filename()]
    assert nombres == ["declaracion.pdf"]


def test_enviar_y_probar_con_servidor_falso(monkeypatch):
    _SMTPFalso.instancias.clear()
    monkeypatch.setattr(correo.smtplib, "SMTP_SSL", _SMTPFalso)
    monkeypatch.setattr(correo.smtplib, "SMTP", _SMTPFalso)
    msg = correo.construir(_servidor(), ["juan@cliente.ec"], "A", "B")
    assert correo.enviar(_servidor(), "buena", msg) == []
    assert _SMTPFalso.instancias[-1].login_con == "ana@estudio.ec"
    correo.probar(_servidor("starttls"), "buena")
    assert _SMTPFalso.instancias[-1].tls


def test_contrasena_rechazada_da_mensaje_claro_sin_la_clave(monkeypatch):
    monkeypatch.setattr(correo.smtplib, "SMTP_SSL", _SMTPFalso)
    with pytest.raises(correo.ErrorCorreo) as e:
        correo.probar(_servidor(), "mala-clave-secreta")
    assert "contraseña de aplicación" in str(e.value)
    assert "mala-clave-secreta" not in str(e.value)


def test_servidor_sin_autenticacion_no_inicia_sesion(monkeypatch):
    """Mailpit y otros servidores locales: sin contraseña no se llama a login."""
    _SMTPFalso.instancias.clear()
    monkeypatch.setattr(correo.smtplib, "SMTP", _SMTPFalso)
    servidor = perfil.ServidorCorreo("localhost", 1025, "ninguna", "ana@estudio.ec",
                                     autenticar=False)
    msg = correo.construir(servidor, ["juan@cliente.ec"], "A", "B")
    assert correo.enviar(servidor, "", msg) == []
    assert _SMTPFalso.instancias[-1].login_con is None


def test_faltantes_nombra_los_campos():
    s = perfil.ServidorCorreo("localhost", 1026, "ninguna", "", "rolo@gmail.com")
    assert s.faltantes() == ["Correo de la cuenta"] and not s.configurado
    p = perfil.Perfil(correo=s)
    with pytest.raises(ValueError, match="Correo de la cuenta"):
        perfil.guardar(p)
