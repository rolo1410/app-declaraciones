"""
Automatización de descarga de comprobantes electrónicos (XML) del portal
SRI en línea (Ecuador) usando Playwright.

Este módulo contiene:
  - Funciones puras de validación / utilidades (fácilmente testeables).
  - La clase ``SRIDownloader`` que ejecuta el flujo completo de automatización.

FLUJO REAL (verificado contra el portal):
  1. Ir a la landing de "SRI en línea" y hacer clic en "Iniciar sesión".
  2. En el login de Keycloak, escribir usuario y clave (tecla por tecla, porque
     el formulario Angular no reconoce un ``fill`` directo) y enviar.
  3. Desde la landing autenticada, expandir el panel "FACTURACIÓN ELECTRÓNICA"
     y abrir "Comprobantes electrónicos recibidos" (se abre en pestaña nueva).
  4. Filtrar por año/mes/día y tipo de comprobante y pulsar "Consultar".
  5. Descargar el XML de cada fila, recorriendo todas las páginas.

reCAPTCHA:
  La consulta está protegida por reCAPTCHA v3 (invisible, por puntaje). Para
  obtener un puntaje aceptable se usa:
    - Chrome real (channel="chrome") en lugar de Chromium.
    - Un PERFIL PERSISTENTE (user-data-dir) que acumula reputación entre
      ejecuciones.
    - Desactivación de las banderas de automatización + ``navigator.webdriver``.
    - Movimiento de mouse "humano" antes de pulsar Consultar y reintentos.
"""

from __future__ import annotations

import os
import random
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Collection, List, Optional


# ---------------------------------------------------------------------------
# Constantes del portal
# ---------------------------------------------------------------------------

LANDING_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT"
# Destino del enlace "Iniciar sesión" del header. Navegar aquí equivale a
# pulsarlo: si no hay sesión, el portal redirige a Keycloak generando state y
# nonce nuevos; si la hay, carga el perfil del contribuyente.
PERFIL_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/contribuyente/perfil"

# Carpeta de perfil persistente de Chrome. Es CLAVE para el reCAPTCHA: acumula
# reputación entre ejecuciones. No borrar entre corridas.
PERFIL_DIR = os.path.join(os.path.expanduser("~"), ".sri_descargas", "perfil_chrome")

# Cookies del SRI (portal y Keycloak). Borrarlas cierra la sesión sin tocar las
# de Google, que son las que guardan la reputación del reCAPTCHA.
DOMINIOS_SRI = re.compile(r"(^|\.)sri\.gob\.ec$")

TIPO_RECIBIDOS = "recibidos"
TIPO_EMITIDOS = "emitidos"

# Meses para poblar los combos de la interfaz (valor = value del <select>).
MESES = [
    ("01 - Enero", "1"), ("02 - Febrero", "2"), ("03 - Marzo", "3"),
    ("04 - Abril", "4"), ("05 - Mayo", "5"), ("06 - Junio", "6"),
    ("07 - Julio", "7"), ("08 - Agosto", "8"), ("09 - Septiembre", "9"),
    ("10 - Octubre", "10"), ("11 - Noviembre", "11"), ("12 - Diciembre", "12"),
]

# Tipos de comprobante disponibles en el portal (value = value del <option>).
TIPOS_COMPROBANTE = [
    ("1", "Factura"),
    ("2", "Liquidación de compra de bienes y prestación de servicios"),
    ("3", "Notas de Crédito"),
    ("4", "Notas de Débito"),
    ("6", "Comprobante de Retención"),
]

DIA_TODOS = "0"


# ---------------------------------------------------------------------------
# Configuración de la descarga
# ---------------------------------------------------------------------------

@dataclass
class DownloadConfig:
    """Parámetros que el usuario proporciona en tiempo de ejecución."""

    ruc: str
    clave: str = field(repr=False)
    anio: int
    mes: int
    dia: int  # 0 == todos los días del mes
    download_dir: str
    tipo: str = TIPO_RECIBIDOS  # actualmente sólo "recibidos"
    # Códigos de tipo de comprobante a descargar. None == todos.
    tipos_comprobante: Optional[List[str]] = None
    headless: bool = False
    nav_timeout_ms: int = 60_000
    # Modo semi-manual: el usuario inicia sesión y hace la consulta a mano
    # (resolviendo el reCAPTCHA), y la app sólo descarga los XML resultantes.
    semi_manual: bool = False
    # Usar el Chromium de Playwright en vez del Chrome del sistema. Es la salida
    # cuando Chrome se cierra solo: es otro binario y no comparte el fallo.
    usar_chromium: bool = False
    # Cliente registrado: identificaciones (RUC y cédula) con las que puede
    # figurar como comprador. Un XML a nombre de otro no se guarda. None ==
    # descarga sin cliente registrado (no se comprueba).
    identificaciones_cliente: Optional[Collection[str]] = None
    # Cerrar cualquier sesión previa del SRI antes de empezar, para no
    # descargar con la sesión de otro contribuyente.
    limpiar_sesion_sri: bool = False


# ---------------------------------------------------------------------------
# Funciones puras (validación / utilidades) -- testeables sin navegador
# ---------------------------------------------------------------------------

def validar_config(cfg: DownloadConfig) -> List[str]:
    """Devuelve una lista de mensajes de error. Vacía == configuración válida."""
    errores: List[str] = []

    ruc = (cfg.ruc or "").strip()
    if not ruc:
        errores.append("El RUC / C.I. / Pasaporte es obligatorio.")
    elif not ruc.isdigit():
        errores.append("El RUC / cédula debe contener solo dígitos.")
    elif len(ruc) not in (10, 13):
        # El portal solo acepta cédula (10) o RUC (13 = cédula + 001); una
        # longitud intermedia se rechaza como "usuario o clave incorrectos",
        # lo que hace parecer que el error está en la clave.
        errores.append(
            f"Se ingresaron {len(ruc)} dígitos: la cédula debe tener 10 y el "
            "RUC 13 (la cédula seguida de 001)."
        )

    if not (cfg.clave or "").strip():
        errores.append("La clave es obligatoria.")

    anio_actual = datetime.now().year
    if not (2000 <= cfg.anio <= anio_actual):
        errores.append(f"El año debe estar entre 2000 y {anio_actual}.")

    if not (1 <= cfg.mes <= 12):
        errores.append("El mes debe estar entre 1 y 12.")

    if not (0 <= cfg.dia <= 31):
        errores.append("El día debe estar entre 0 (todos) y 31.")

    d = (cfg.download_dir or "").strip()
    if not d:
        errores.append("Debe seleccionar un directorio de descarga.")
    elif not os.path.isdir(d):
        errores.append(f"El directorio de descarga no existe: {d}")
    elif not os.access(d, os.W_OK):
        errores.append(f"No hay permisos de escritura en: {d}")

    if cfg.tipo not in (TIPO_RECIBIDOS, TIPO_EMITIDOS):
        errores.append("El tipo de comprobante debe ser 'recibidos' o 'emitidos'.")

    return errores


_RESERVADOS_WINDOWS = {"CON", "PRN", "AUX", "NUL"} | {
    f"{base}{n}" for base in ("COM", "LPT") for n in range(1, 10)
}
LARGO_MAXIMO_NOMBRE = 100


def sanitizar_nombre(nombre: str) -> str:
    """Limpia un nombre de archivo para que sea válido en Windows, macOS y Linux.

    * caracteres prohibidos en Windows y de control → ``_``;
    * Unicode en NFC (macOS puede entregar ``ñ``/tildes descompuestos);
    * nombres reservados de Windows (``CON``, ``COM1``…, también con extensión)
      → prefijo ``_``;
    * sin punto ni espacio final y como máximo 100 caracteres (conservando la
      extensión) para no acercarse al límite de 260 de las rutas de Windows.
    """
    nombre = unicodedata.normalize("NFC", (nombre or "").strip())
    if not nombre:
        return "comprobante.xml"
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre)
    nombre = nombre.strip(". ")
    if not nombre:
        return "comprobante.xml"
    if nombre.split(".")[0].upper() in _RESERVADOS_WINDOWS:
        nombre = "_" + nombre
    if len(nombre) > LARGO_MAXIMO_NOMBRE:
        base, ext = os.path.splitext(nombre)
        ext = ext[:10]
        nombre = base[: LARGO_MAXIMO_NOMBRE - len(ext)].rstrip(". ") + ext
    return nombre


def ruta_unica(directorio: str, nombre: str) -> str:
    """Devuelve una ruta que no colisione: agrega ``_1``, ``_2`` ... si existe."""
    nombre = sanitizar_nombre(nombre)
    base, ext = os.path.splitext(nombre)
    candidato = os.path.join(directorio, nombre)
    contador = 1
    while os.path.exists(candidato):
        candidato = os.path.join(directorio, f"{base}_{contador}{ext}")
        contador += 1
    return candidato


def periodo_anterior(hoy: Optional[datetime] = None) -> tuple:
    """(año, mes) del mes anterior al de ``hoy``.

    Es el periodo que normalmente se declara, y en enero retrocede a diciembre
    del año previo.
    """
    hoy = hoy or datetime.now()
    if hoy.month == 1:
        return hoy.year - 1, 12
    return hoy.year, hoy.month - 1


def subdirectorio_periodo(cfg: DownloadConfig) -> str:
    """Nombre de subcarpeta sugerido para organizar la descarga por periodo."""
    dia = "todos" if cfg.dia == 0 else f"{cfg.dia:02d}"
    return f"{cfg.tipo}_{cfg.anio}_{cfg.mes:02d}_{dia}"


# Fragmentos con los que Playwright avisa de que ya no hay navegador al otro
# lado; cualquiera de ellos hace inútil seguir intentando con las demás filas.
_SENALES_NAVEGADOR_CERRADO = (
    "has been closed",
    "target crashed",
    "browser has disconnected",
    "connection closed",
)


def es_error_navegador_cerrado(mensaje: str) -> bool:
    """True si el mensaje de Playwright indica que el navegador ya no existe."""
    texto = (mensaje or "").lower()
    return any(senal in texto for senal in _SENALES_NAVEGADOR_CERRADO)


def comprador_ajeno(contenido: str, identificaciones: Optional[Collection[str]]) -> Optional[str]:
    """Identificación del comprador si NO es del cliente; ``None`` si se acepta.

    Se acepta cuando no hay cliente registrado (``identificaciones`` es None),
    cuando el comprador es el RUC o la cédula del cliente, o cuando el
    comprobante no trae comprador (p. ej. guía de remisión).
    """
    if identificaciones is None:
        return None
    from .analizador import identificacion_comprador

    ident = identificacion_comprador(contenido)
    if ident is None or ident in identificaciones:
        return None
    return ident


def extraer_clave_acceso(contenido: str) -> Optional[str]:
    """Extrae la clave de acceso (49 dígitos) del XML de un comprobante."""
    for patron in (r"claveAcceso>\s*(\d{49})", r"numeroAutorizacion>\s*(\d{49})"):
        m = re.search(patron, contenido)
        if m:
            return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Selectores (centralizados para mantenimiento fácil)
# ---------------------------------------------------------------------------

class Selectors:
    # Login (Keycloak) -- ids confirmados en el portal
    USUARIO = "#usuario"
    PASSWORD = "#password"
    BTN_INGRESAR = "#kc-login"
    # Campo opcional "C.I. adicional" (solo para usuario adicional autorizado).
    CI_ADICIONAL = "#ciAdicional"
    TXT_INICIAR_SESION = "Iniciar sesión"
    # Enlace "Iniciar sesión" del header de la landing. Su textContent incluye la
    # ligadura del icono ("account_box Iniciar sesiónIniciar sesión"), por eso se
    # busca por clase / aria-label / href antes que por texto.
    LINK_INICIAR_SESION = (
        "a.sri-tamano-link-iniciar-sesion",
        'a[aria-label="Ir a iniciar sesión"]',
        'a[href*="/contribuyente/perfil"]',
    )
    # Fragmento presente en la URL de Keycloak; la URL completa lleva state y
    # nonce distintos en cada intento, así que nunca se navega a ella directamente.
    URL_LOGIN = "auth/realms"
    # Destino del redirect_uri: solo se alcanza con la sesión ya iniciada.
    URL_AUTENTICADO = "/contribuyente/perfil"
    # Posibles contenedores del mensaje de error de credenciales (Keycloak/SRI).
    LOGIN_ERROR = (
        ".kc-feedback-text",
        ".alert-error",
        ".pf-c-alert__title",
        "#input-error",
        ".ui-messages-error",
        "span.error",
    )

    # Menú de navegación
    MENU_FACTURACION = "FACTURACIÓN ELECTRÓNICA"
    MENU_RECIBIDOS = "Comprobantes electrónicos recibidos"

    # Formulario de consulta (ids JSF confirmados)
    SELECT_ANIO = "#frmPrincipal\\:ano"
    SELECT_MES = "#frmPrincipal\\:mes"
    SELECT_DIA = "#frmPrincipal\\:dia"
    SELECT_TIPO = "#frmPrincipal\\:cmbTipoComprobante"
    BTN_CONSULTAR = "#frmPrincipal\\:btnBuscar"
    # Alternativas por si cambia el id: el botón es un <button> de PrimeFaces
    # cuyo rótulo vive en un <span> interno con el texto "Consultar".
    BTN_CONSULTAR_ALT = (
        "#frmPrincipal\\:btnConsultar",
        "button:has(span:text-is('Consultar'))",
        "span:text-is('Consultar')",
    )

    # Tabla de resultados
    XML_LINKS = "a[id*='lnkXml']"
    PAGINATOR_NEXT = ".ui-paginator-next"
    PAGINATOR_CURRENT = ".ui-paginator-current"      # "(1 of 3)"
    PAGINATOR_RPP = ".ui-paginator-rpp-options"      # filas por página (25/50/75)
    CAPTCHA_ERROR = "text=Captcha incorrecta"


class DownloadStopped(Exception):
    """Se lanza cuando el usuario solicita detener el proceso."""


class LoginError(Exception):
    """Credenciales inválidas o login no completado."""


class NavegadorCerrado(Exception):
    """El navegador dejó de responder o se cerró en mitad del proceso."""


class ElementoNoEncontrado(Exception):
    """No se localizó un control esperado del portal (probable cambio de la web)."""


class PaginacionError(Exception):
    """No se pudo avanzar de página tras los reintentos permitidos."""


# Número máximo de reintentos para operaciones frágiles (captcha, paginación).
MAX_REINTENTOS = 5

# Script inyectado antes de cargar cualquier página para ocultar señales de
# automatización. reCAPTCHA v3 asigna un puntaje según el "aspecto" del
# navegador; cuantas menos huellas de bot detecte, más alto el puntaje.
# Argumentos de arranque del navegador.
#
# Además de ocultar la automatización, se desactivan las tareas de fondo que
# Chrome dispara al minuto de arrancar (component updater y descarga de modelos
# del "optimization guide"). Se observó un segfault reproducible del proceso
# principal a los ~58 s de cada arranque, siempre con la misma firma y con el
# patrón de memoria liberada 0xcdcdcdcd, sin relación con el número de descargas.
ARGS_NAVEGADOR = [
    "--disable-blink-features=AutomationControlled",
    "--disable-component-update",
    "--disable-features=OptimizationGuideModelDownloading,OptimizationHints,"
    "OptimizationTargetPrediction",
]

STEALTH_JS = """
// navigator.webdriver -> undefined (la señal más obvia de automatización)
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
// idioma coherente con un usuario ecuatoriano
Object.defineProperty(navigator, 'languages', {get: () => ['es-EC', 'es', 'en']});
// objeto chrome presente (Chromium headless a veces no lo expone completo)
window.chrome = window.chrome || {};
window.chrome.runtime = window.chrome.runtime || {};
// permissions.query no debe delatar el estado de automatización
try {
  const _q = window.navigator.permissions.query;
  window.navigator.permissions.query = (p) => (
    p && p.name === 'notifications'
      ? Promise.resolve({state: Notification.permission})
      : _q(p)
  );
} catch (e) {}
// plugins/mimeTypes no vacíos (un navegador real siempre tiene alguno)
try {
  Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
} catch (e) {}
"""


# ---------------------------------------------------------------------------
# Orquestador de la automatización
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    total_descargados: int = 0
    paginas_procesadas: int = 0
    errores: List[str] = field(default_factory=list)
    carpeta_destino: str = ""
    # True si el portal rechazó las credenciales (para ofrecer actualizar la clave).
    error_login: bool = False
    # XML descartados porque el comprador no es el cliente.
    rechazados: int = 0


LogFn = Callable[[str], None]


class SRIDownloader:
    """Ejecuta el flujo completo de descarga con Playwright.

    Diseñado para correr en un hilo aparte de la GUI:
      - ``log_fn``: callback para mensajes de progreso.
      - ``stop_event``: ``threading.Event`` para cancelación cooperativa.
    """

    def __init__(
        self,
        config: DownloadConfig,
        log_fn: Optional[LogFn] = None,
        stop_event: Optional[threading.Event] = None,
        continue_event: Optional[threading.Event] = None,
    ) -> None:
        self.cfg = config
        self.log_fn = log_fn or (lambda msg: None)
        self.stop_event = stop_event or threading.Event()
        # Señal que la GUI activa (botón "Continuar descarga") en modo semi-manual.
        self.continue_event = continue_event or threading.Event()
        self.rechazados = 0

    # -- utilidades internas -------------------------------------------------

    def log(self, msg: str) -> None:
        self.log_fn(msg)

    def _check_stop(self) -> None:
        if self.stop_event.is_set():
            raise DownloadStopped()

    def _tipos_a_descargar(self) -> List[tuple]:
        if not self.cfg.tipos_comprobante:
            return TIPOS_COMPROBANTE
        seleccion = set(self.cfg.tipos_comprobante)
        return [(v, n) for (v, n) in TIPOS_COMPROBANTE if v in seleccion]

    # -- pasos del flujo -----------------------------------------------------

    def _login(self, page) -> None:
        self.log("Abriendo portal SRI en línea...")
        page.goto(LANDING_URL, wait_until="domcontentloaded", timeout=self.cfg.nav_timeout_ms)
        page.wait_for_timeout(3000)
        self._check_stop()

        # Si el formulario no está visible, entrar por "Iniciar sesión". Se
        # comprueba ANTES de pulsar si la sesión sigue viva: en ese caso el
        # portal sustituye el enlace por el menú del contribuyente y el clic
        # fallaría, abortando la ejecución.
        if page.locator(Selectors.PASSWORD).count() == 0:
            if self._sesion_activa_en_landing(page):
                # Que falte el enlace no basta: la cookie puede estar caducada.
                # Se abre el perfil para confirmarlo; si el portal devuelve el
                # formulario, se sigue con el login normal.
                page.goto(
                    PERFIL_URL,
                    wait_until="domcontentloaded",
                    timeout=self.cfg.nav_timeout_ms,
                )
                if self._sesion_ya_abierta(page):
                    self.log(
                        "Ya hay una sesión abierta; se continúa sin volver a iniciarla."
                    )
                    return
                self.log("La sesión anterior caducó; se inicia de nuevo.")

            self.log("Entrando al formulario de login...")
            self._click_iniciar_sesion(page)

            if self._sesion_ya_abierta(page):
                self.log("Ya había una sesión abierta en el perfil de Chrome.")
                return

        page.wait_for_selector(Selectors.PASSWORD, timeout=self.cfg.nav_timeout_ms)
        page.wait_for_timeout(1000)

        self.log("Ingresando credenciales...")
        u = page.locator(Selectors.USUARIO)
        u.click(); u.fill(""); u.press_sequentially(self.cfg.ruc.strip(), delay=35)
        c = page.locator(Selectors.PASSWORD)
        c.click(); c.fill(""); c.press_sequentially(self.cfg.clave, delay=35)
        page.click(Selectors.BTN_INGRESAR)

        # Esperar el desenlace: o salimos de Keycloak (éxito) o el portal
        # muestra un error de credenciales. Se corta apenas se detecta el error
        # (sin esperar el timeout completo) para no seguir con el resto del flujo.
        exito = False
        for _ in range(24):  # ~12 s como máximo
            self._check_stop()
            if Selectors.URL_LOGIN not in page.url:
                exito = True
                break
            if self._hay_error_login(page):
                raise LoginError(
                    "Clave o RUC/cédula incorrectos: el portal rechazó las "
                    "credenciales. Se cancela el proceso."
                )
            page.wait_for_timeout(500)

        page.wait_for_timeout(2000)
        # Red de seguridad: si seguimos viendo el formulario, el login no pasó.
        if not exito and page.locator(Selectors.PASSWORD).count() > 0:
            raise LoginError(
                "No se pudo iniciar sesión. Verifique el RUC/cédula y la clave "
                "(el portal respondió con un error de credenciales)."
            )
        self._check_stop()
        self.log("Sesión iniciada correctamente.")

    def _click_iniciar_sesion(self, page) -> None:
        """Pulsa el enlace "Iniciar sesión" de la landing y espera a Keycloak.

        El enlace apunta a /contribuyente/perfil; Angular redirige al login de
        Keycloak generando ``state`` y ``nonce`` nuevos en cada intento, por eso
        se entra siempre por aquí y nunca por una URL de login fija.
        """
        for selector in Selectors.LINK_INICIAR_SESION:
            enlace = page.locator(selector)
            if enlace.count() and enlace.first.is_visible():
                enlace.first.click()
                break
        else:
            enlace = page.get_by_text(Selectors.TXT_INICIAR_SESION, exact=False)
            if enlace.count():
                enlace.first.click()
            else:
                # Sin enlace visible se navega a su destino, que es lo mismo que
                # pulsarlo. Así un header inesperado no aborta el proceso.
                self.log("  (Enlace no visible; se abre el perfil directamente.)")
                page.goto(
                    PERFIL_URL,
                    wait_until="domcontentloaded",
                    timeout=self.cfg.nav_timeout_ms,
                )

        try:
            page.wait_for_url(
                lambda url: Selectors.URL_LOGIN in url, timeout=self.cfg.nav_timeout_ms
            )
        except Exception:  # noqa: BLE001 - el wait_for_selector posterior decide
            pass

    def _sesion_activa_en_landing(self, page) -> bool:
        """True si la landing ya se ve con la sesión iniciada.

        El enlace «Iniciar sesión» solo existe cuando NO hay sesión; con sesión
        activa el header muestra el menú del contribuyente. Se sondea unos
        segundos porque Angular pinta la cabecera con retraso.
        """
        for _ in range(6):  # ~3 s
            self._check_stop()
            for selector in Selectors.LINK_INICIAR_SESION:
                enlace = page.locator(selector)
                if enlace.count() and enlace.first.is_visible():
                    return False
            page.wait_for_timeout(500)
        return True

    def _sesion_ya_abierta(self, page) -> bool:
        """True si el portal saltó el formulario porque la sesión sigue viva.

        El perfil persistente de Chrome (necesario para el reCAPTCHA) conserva
        las cookies del SRI entre ejecuciones, así que cerrar el navegador no
        cierra la sesión. Cuando sigue abierta, Keycloak redirige directo al
        perfil del contribuyente y el campo de clave nunca aparece: sin esta
        comprobación la espera agotaría el tiempo y la descarga fallaría.
        """
        for _ in range(10):  # ~5 s
            self._check_stop()
            if page.locator(Selectors.PASSWORD).count():
                return False
            if Selectors.URL_AUTENTICADO in page.url:
                return True
            page.wait_for_timeout(500)
        return False

    def _hay_error_login(self, page) -> bool:
        """True si el portal muestra un mensaje de error de credenciales."""
        for sel in Selectors.LOGIN_ERROR:
            try:
                loc = page.locator(sel)
                if loc.count() and loc.first.is_visible():
                    return True
            except Exception:  # noqa: BLE001 - selector no aplicable en esta página
                continue
        return False

    def _navegar_a_comprobantes(self, page):
        """Navega al módulo de comprobantes recibidos; devuelve la pestaña activa."""
        self.log("Navegando a Facturación Electrónica > Comprobantes recibidos...")
        context = page.context

        page.goto(LANDING_URL, wait_until="domcontentloaded", timeout=self.cfg.nav_timeout_ms)
        page.wait_for_timeout(2500)

        page.get_by_text(Selectors.MENU_FACTURACION, exact=False).first.click()
        page.wait_for_timeout(1200)

        n = len(context.pages)
        page.get_by_role("link", name=Selectors.MENU_RECIBIDOS).first.click()

        # El módulo se abre en una pestaña nueva.
        for _ in range(30):
            if len(context.pages) > n:
                break
            page.wait_for_timeout(300)
        activa = context.pages[-1]
        activa.wait_for_load_state("domcontentloaded")
        activa.wait_for_timeout(3500)
        activa.wait_for_selector(Selectors.SELECT_ANIO, timeout=self.cfg.nav_timeout_ms)
        # Calentamiento: dar un momento de actividad "humana" antes de la primera
        # consulta ayuda al puntaje de reCAPTCHA v3 (no consultar al instante).
        self._comportamiento_humano(activa)
        activa.wait_for_timeout(1500)
        self.log("Módulo de comprobantes abierto.")
        return activa

    # -- flujo semi-manual (respaldo cuando el reCAPTCHA v3 bloquea) ---------

    def _esperar_continuar(self) -> None:
        """Bloquea hasta que la GUI active ``continue_event``.

        Lanza ``DownloadStopped`` si el usuario pulsa "Detener" (que en este
        modo significa "terminar"). El navegador sigue vivo y respondiendo al
        usuario mientras tanto: corre en un proceso aparte.
        """
        while not self.continue_event.is_set():
            self._check_stop()
            time.sleep(0.3)

    def _pagina_con_resultados(self, ctx):
        """Devuelve la pestaña que tenga una tabla de comprobantes con XML.

        Recorre de la más reciente a la más antigua para preferir la pestaña
        donde el usuario acaba de consultar.
        """
        for p in reversed(ctx.pages):
            try:
                if p.is_closed():
                    continue
                if p.locator(Selectors.XML_LINKS).count() > 0:
                    return p
            except Exception:  # noqa: BLE001 - pestaña no inspeccionable
                continue
        return None

    def _flujo_semi_manual(self, ctx, page, destino, resultado):
        """Abre el navegador y deja que el usuario consulte a mano; luego descarga.

        Repite: espera "Continuar descarga" -> descarga la tabla visible ->
        vuelve a esperar. Termina cuando el usuario pulsa "Detener".
        """
        self.log("=" * 60)
        self.log("MODO SEMI-MANUAL activado.")
        self.log("1) Inicia sesión en el SRI en la ventana del navegador.")
        self.log("2) Entra a «Comprobantes electrónicos recibidos», elige año/")
        self.log("   mes/día y tipo, y pulsa «Consultar» (resuelve el captcha).")
        self.log("3) Cuando veas la tabla de resultados, vuelve a esta app y")
        self.log("   pulsa «Continuar descarga».")
        self.log("Puedes repetir la consulta cuantas veces quieras (otro tipo,")
        self.log("otro periodo) y pulsar «Continuar descarga» cada vez.")
        self.log("Cuando termines, pulsa «Detener» para cerrar el navegador.")
        self.log("=" * 60)

        try:
            page.goto(LANDING_URL, wait_until="domcontentloaded", timeout=self.cfg.nav_timeout_ms)
        except Exception:  # noqa: BLE001 - el usuario puede navegar por su cuenta
            pass

        consultas = 0
        try:
            while True:
                self.log("Esperando a que pulses «Continuar descarga»...")
                self._esperar_continuar()
                self._check_stop()

                objetivo = self._pagina_con_resultados(ctx)
                if objetivo is None:
                    self.log(
                        "  No encontré una tabla de comprobantes con XML en ninguna "
                        "pestaña. Realiza la consulta y vuelve a pulsar «Continuar "
                        "descarga» (o «Detener» para salir)."
                    )
                    self.continue_event.clear()
                    continue

                consultas += 1
                self.log(f"Descargando los comprobantes de la consulta #{consultas}...")
                n = self._descargar_todas_paginas(objetivo, destino)
                resultado.total_descargados += n
                resultado.paginas_procesadas += 1
                self.continue_event.clear()
                self.log(
                    f"✔ Consulta #{consultas}: {n} archivo(s). Haz otra consulta y "
                    "pulsa «Continuar descarga», o «Detener» para terminar."
                )
        except DownloadStopped:
            self.log("Descarga semi-manual finalizada.")

        if resultado.total_descargados:
            self.log(
                f"✔ Total: {resultado.total_descargados} archivo(s) en «{destino}»."
            )
        else:
            self.log("No se descargó ningún archivo.")
        return resultado

    def _comportamiento_humano(self, page) -> None:
        """Movimiento de mouse "humano" para mejorar el puntaje de reCAPTCHA v3.

        reCAPTCHA v3 puntúa el comportamiento: trayectorias variadas, pausas
        irregulares y algo de scroll parecen humanas; los saltos idénticos en
        cada corrida, no. Por eso se aleatorizan posiciones y tiempos.
        """
        try:
            x, y = 300, 300
            for _ in range(random.randint(5, 9)):
                x += random.randint(-180, 220)
                y += random.randint(-120, 160)
                # Mantener el cursor dentro de un área razonable de la ventana.
                x = max(60, min(x, 1100))
                y = max(60, min(y, 700))
                page.mouse.move(x, y, steps=random.randint(6, 14))
                page.wait_for_timeout(random.randint(120, 360))
            page.mouse.wheel(0, random.randint(150, 400))
            page.wait_for_timeout(random.randint(300, 700))
        except Exception:
            pass

    def _seleccionar_filtros(self, page, tipo_codigo: str) -> None:
        page.select_option(Selectors.SELECT_ANIO, value=str(self.cfg.anio))
        page.select_option(Selectors.SELECT_MES, value=str(self.cfg.mes))
        page.select_option(Selectors.SELECT_DIA, value=str(self.cfg.dia))
        page.select_option(Selectors.SELECT_TIPO, value=tipo_codigo)

    def _boton_consultar(self, page):
        """Devuelve el botón «Consultar» del formulario de comprobantes.

        Se prueba primero el id de PrimeFaces y, si no está, el texto del <span>
        interno, que es lo único estable cuando el portal renumera los ids.
        """
        for selector in (Selectors.BTN_CONSULTAR, *Selectors.BTN_CONSULTAR_ALT):
            loc = page.locator(selector)
            if loc.count():
                return loc.first
        raise ElementoNoEncontrado(
            "No se encontró el botón «Consultar» en el formulario de "
            "comprobantes. Es posible que el portal haya cambiado."
        )

    def _consultar(self, page, tipo_codigo: str) -> bool:
        """Aplica filtros y pulsa Consultar, renovando el token ante el reCAPTCHA.

        Devuelve True si la consulta se ejecutó (aunque no haya resultados),
        False si el reCAPTCHA siguió fallando tras los reintentos.

        Estrategia frente a reCAPTCHA v3: NO se martilla el botón. Cada reintento
        RECARGA la página para obtener un token nuevo (el v3 caduca a los ~2 min
        y repetir clics con el mismo contexto sólo baja el puntaje), simula
        comportamiento humano y espera de forma escalonada.
        """
        for intento in range(1, MAX_REINTENTOS + 1):
            self._check_stop()
            if intento > 1:
                self.log(
                    f"  Renovando el reCAPTCHA con una recarga "
                    f"(intento {intento}/{MAX_REINTENTOS})..."
                )
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector(Selectors.SELECT_ANIO, timeout=self.cfg.nav_timeout_ms)
                # Espera escalonada: cada reintento deja "reposar" un poco más la
                # sesión antes de volver a pedir un token.
                page.wait_for_timeout(2000 + intento * 1500)

            self._seleccionar_filtros(page, tipo_codigo)
            self._comportamiento_humano(page)
            boton = self._boton_consultar(page)
            boton.hover()
            page.wait_for_timeout(random.randint(500, 900))
            boton.click()
            page.wait_for_timeout(6000)

            if page.locator(Selectors.CAPTCHA_ERROR).count() == 0:
                return True
            self.log(
                f"  reCAPTCHA rechazó la consulta (intento {intento}/{MAX_REINTENTOS})."
            )
        return False

    def _descargar_pagina_actual(self, page, destino: str) -> int:
        enlaces = page.locator(Selectors.XML_LINKS)
        total = enlaces.count()
        if total == 0:
            return 0

        descargados = 0
        omitidos = 0
        for i in range(total):
            self._check_stop()
            if page.is_closed():
                raise NavegadorCerrado(
                    f"El navegador se cerró antes de la fila {i + 1} de {total}."
                )
            enlace = page.locator(Selectors.XML_LINKS).nth(i)
            try:
                with page.expect_download(timeout=self.cfg.nav_timeout_ms) as dl_info:
                    enlace.click()
                download = dl_info.value
                sugerido = download.suggested_filename or "comprobante.xml"
                tmp = ruta_unica(destino, "_tmp_" + sugerido)
                download.save_as(tmp)

                # Renombrar por clave de acceso (única y significativa).
                nombre_final = sugerido
                clave = None
                contenido = ""
                try:
                    with open(tmp, "r", encoding="utf-8", errors="ignore") as fh:
                        contenido = fh.read()
                    clave = extraer_clave_acceso(contenido)
                    if clave:
                        nombre_final = f"{clave}.xml"
                except Exception:
                    pass

                # Defensa ante una sesión de otro contribuyente: un XML a nombre
                # de otra persona no se guarda en la carpeta de este cliente.
                ajeno = comprador_ajeno(contenido, self.cfg.identificaciones_cliente)
                if ajeno is not None:
                    os.remove(tmp)
                    self.rechazados += 1
                    self.log(
                        f"    ✖ Fila {i + 1}: el comprador ({ajeno}) no es este cliente; "
                        "no se guarda."
                    )
                    continue

                # Con la clave de acceso el nombre es único por comprobante, así
                # que si ya está en la carpeta es el mismo XML: se descarta la
                # copia en vez de crear un duplicado. Esto hace que reanudar una
                # descarga interrumpida no infle el análisis posterior.
                ya_existente = os.path.join(destino, nombre_final)
                if clave and os.path.exists(ya_existente):
                    os.remove(tmp)
                    omitidos += 1
                else:
                    destino_final = ruta_unica(destino, nombre_final)
                    os.replace(tmp, destino_final)
                    descargados += 1
                    self.log(f"    ✓ {os.path.basename(destino_final)}")

                # Respiro entre descargas: no evita el segfault de Chrome (que es
                # periódico, no por volumen), pero hace el recorrido menos
                # mecánico de cara al reCAPTCHA.
                page.wait_for_timeout(random.randint(150, 400))
            except Exception as e:  # noqa: BLE001
                # Si el navegador murió, las demás filas fallarían igual: se
                # aborta en vez de repetir el mismo error una vez por fila.
                if es_error_navegador_cerrado(str(e)):
                    raise NavegadorCerrado(
                        f"El navegador se cerró en la fila {i + 1} de {total}."
                    ) from e
                self.log(f"    ⚠ Error al descargar fila {i + 1}: {e}")

        if omitidos:
            self.log(f"    ↷ {omitidos} comprobante(s) ya estaban descargados.")
        return descargados

    def _firma_pagina(self, page) -> str:
        """Firma del estado de la tabla, para detectar el cambio de página.

        Usa el texto "(N of M)" del paginador (señal fiable de PrimeFaces) más
        el id de la primera fila.
        """
        try:
            cur = page.locator(Selectors.PAGINATOR_CURRENT).first
            texto = cur.inner_text(timeout=1500) if cur.count() else ""
        except Exception:
            texto = ""
        try:
            primer = page.locator(Selectors.XML_LINKS).first
            fid = primer.get_attribute("id", timeout=1500) if primer.count() else ""
        except Exception:
            fid = ""
        return f"{texto}|{fid}"

    def _esperar_cambio_pagina(self, page, firma_previa: str, intentos: int = 40) -> bool:
        for _ in range(intentos):
            self._check_stop()
            page.wait_for_timeout(300)
            if self._firma_pagina(page) != firma_previa:
                return True
        return False

    def _next_deshabilitado(self, page) -> bool:
        next_btn = page.locator(Selectors.PAGINATOR_NEXT).first
        if next_btn.count() == 0:
            return True
        clase = next_btn.get_attribute("class") or ""
        return "ui-state-disabled" in clase

    def _maximizar_filas_por_pagina(self, page) -> None:
        """Sube las filas por página al máximo disponible para reducir clics."""
        rpp = page.locator(Selectors.PAGINATOR_RPP).first
        if rpp.count() == 0:
            return
        try:
            valores = page.eval_on_selector_all(
                Selectors.PAGINATOR_RPP + " option",
                "els=>els.map(e=>e.value).filter(v=>/^\\d+$/.test(v))",
            )
            if not valores:
                return
            maximo = max(valores, key=lambda v: int(v))
            actual = rpp.input_value()
            if actual == maximo:
                return
            firma = self._firma_pagina(page)
            rpp.select_option(value=maximo)
            self._esperar_cambio_pagina(page, firma)
        except Exception:
            pass

    def _avanzar_pagina(self, page, firma_previa: str) -> str:
        """Avanza a la siguiente página con reintentos.

        Devuelve: "fin" (no hay más), "ok" (avanzó), "fallo" (no avanzó tras
        MAX_REINTENTOS).
        """
        for intento in range(1, MAX_REINTENTOS + 1):
            self._check_stop()
            if self._next_deshabilitado(page):
                return "fin"
            page.locator(Selectors.PAGINATOR_NEXT).first.click()
            if self._esperar_cambio_pagina(page, firma_previa):
                return "ok"
            self.log(f"    Reintentando avanzar de página ({intento}/{MAX_REINTENTOS})...")
        return "fallo"

    def _descargar_todas_paginas(self, page, destino: str) -> int:
        total = 0
        pagina = 0
        self._maximizar_filas_por_pagina(page)
        while True:
            self._check_stop()
            pagina += 1
            n = self._descargar_pagina_actual(page, destino)
            self.log(f"  Página {pagina}: {n} archivo(s).")
            total += n

            firma = self._firma_pagina(page)
            estado = self._avanzar_pagina(page, firma)
            if estado == "fin":
                break
            if estado == "fallo":
                raise PaginacionError(
                    f"No se pudo avanzar de la página {pagina} tras "
                    f"{MAX_REINTENTOS} reintentos."
                )
        return total

    # -- API pública ---------------------------------------------------------

    def run(self) -> DownloadResult:
        """Ejecuta el flujo completo. Debe llamarse dentro de un hilo."""
        from playwright.sync_api import sync_playwright

        destino = os.path.join(self.cfg.download_dir, subdirectorio_periodo(self.cfg))
        os.makedirs(destino, exist_ok=True)
        os.makedirs(PERFIL_DIR, exist_ok=True)
        self.log(f"Carpeta de destino: {destino}")

        resultado = DownloadResult(carpeta_destino=destino)
        self.rechazados = 0
        try:
            return self._run(sync_playwright, destino, resultado)
        finally:
            resultado.rechazados = self.rechazados
            if self.rechazados:
                msg = (
                    f"{self.rechazados} comprobante(s) estaban a nombre de otro "
                    "contribuyente y no se guardaron. Compruebe que la sesión del "
                    "SRI corresponde a este cliente."
                )
                self.log("⚠ " + msg)
                resultado.errores.append(msg)

    def _cerrar_sesion_sri(self, ctx) -> None:
        """Borra solo las cookies del SRI: obliga a iniciar sesión de nuevo."""
        try:
            ctx.clear_cookies(domain=DOMINIOS_SRI)
            self.log("Sesión previa del SRI cerrada (se inicia de nuevo con este cliente).")
        except Exception as e:  # noqa: BLE001
            # Sin poder cerrar la sesión no es seguro seguir: podría ser de otro RUC.
            raise RuntimeError(f"No se pudo cerrar la sesión previa del SRI: {e}") from e

    def _run(self, sync_playwright, destino: str, resultado: DownloadResult) -> DownloadResult:
        with sync_playwright() as p:
            ctx = self._lanzar_contexto(p)
            ctx.set_default_timeout(self.cfg.nav_timeout_ms)
            ctx.add_init_script(STEALTH_JS)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
                if self.cfg.limpiar_sesion_sri:
                    self._cerrar_sesion_sri(ctx)
                if self.cfg.semi_manual:
                    return self._flujo_semi_manual(ctx, page, destino, resultado)

                self._login(page)
                comprobantes = self._navegar_a_comprobantes(page)

                for codigo, nombre in self._tipos_a_descargar():
                    self._check_stop()
                    self.log(f"Consultando tipo: {nombre}...")
                    if not self._consultar(comprobantes, codigo):
                        msg = (
                            f"reCAPTCHA no superado para '{nombre}' tras "
                            f"{MAX_REINTENTOS} reintentos. Se declara fallido."
                        )
                        self.log("  ✖ " + msg)
                        resultado.errores.append(msg)
                        continue
                    try:
                        resultado.total_descargados += self._descargar_todas_paginas(
                            comprobantes, destino
                        )
                        resultado.paginas_procesadas += 1
                    except PaginacionError as e:
                        msg = f"Paginación fallida en '{nombre}': {e}"
                        self.log("  ✖ " + msg)
                        resultado.errores.append(msg)

                if resultado.errores:
                    self.log(
                        f"⚠ Finalizado con incidencias: {resultado.total_descargados} "
                        f"archivo(s) descargado(s); {len(resultado.errores)} fallo(s)."
                    )
                else:
                    self.log(
                        f"✔ Completado: {resultado.total_descargados} archivo(s) en «{destino}»."
                    )
                return resultado
            except DownloadStopped:
                self.log("⏹ Proceso detenido por el usuario.")
                resultado.errores.append("Detenido por el usuario.")
                return resultado
            except LoginError as e:
                self.log(f"✖ {e}")
                resultado.errores.append(str(e))
                resultado.error_login = True
                return resultado
            except NavegadorCerrado as e:
                msg = (
                    f"{e} Se conservan los {resultado.total_descargados} "
                    "archivo(s) ya descargados; vuelva a ejecutar la descarga "
                    "para obtener el resto."
                )
                self.log(f"✖ {msg}")
                resultado.errores.append(msg)
                return resultado
            except Exception as e:  # noqa: BLE001
                self.log(f"✖ Error inesperado: {e}")
                resultado.errores.append(str(e))
                return resultado
            finally:
                # Cerrar SIEMPRE el navegador al terminar (éxito, fallo o cancelación).
                self.log("Cerrando el navegador...")
                try:
                    ctx.close()
                except Exception:
                    pass

    def _lanzar_contexto(self, p):
        """Lanza el navegador con perfil persistente (necesario para reCAPTCHA)."""
        comun = dict(
            user_data_dir=PERFIL_DIR,
            headless=self.cfg.headless,
            args=ARGS_NAVEGADOR,
            ignore_default_args=["--enable-automation"],
            accept_downloads=True,
            no_viewport=True,
        )

        if self.cfg.usar_chromium:
            self.log("  Usando Chromium (el reCAPTCHA puede exigir más reintentos).")
            return p.chromium.launch_persistent_context(**comun)

        try:
            return p.chromium.launch_persistent_context(channel="chrome", **comun)
        except Exception:
            self.log("  (Chrome no disponible; usando Chromium. El reCAPTCHA puede fallar.)")
            return p.chromium.launch_persistent_context(**comun)
