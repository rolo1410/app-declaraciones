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
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Constantes del portal
# ---------------------------------------------------------------------------

LANDING_URL = "https://srienlinea.sri.gob.ec/sri-en-linea/inicio/NAT"

# Carpeta de perfil persistente de Chrome. Es CLAVE para el reCAPTCHA: acumula
# reputación entre ejecuciones. No borrar entre corridas.
PERFIL_DIR = os.path.join(os.path.expanduser("~"), ".sri_descargas", "perfil_chrome")

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
    clave: str
    anio: int
    mes: int
    dia: int  # 0 == todos los días del mes
    download_dir: str
    tipo: str = TIPO_RECIBIDOS  # actualmente sólo "recibidos"
    # Códigos de tipo de comprobante a descargar. None == todos.
    tipos_comprobante: Optional[List[str]] = None
    headless: bool = False
    nav_timeout_ms: int = 60_000


# ---------------------------------------------------------------------------
# Funciones puras (validación / utilidades) -- testeables sin navegador
# ---------------------------------------------------------------------------

def validar_config(cfg: DownloadConfig) -> List[str]:
    """Devuelve una lista de mensajes de error. Vacía == configuración válida."""
    errores: List[str] = []

    ruc = (cfg.ruc or "").strip()
    if not ruc:
        errores.append("El RUC / C.I. / Pasaporte es obligatorio.")
    elif not re.fullmatch(r"[0-9]{10,13}", ruc):
        errores.append("El RUC / cédula debe contener solo dígitos (10 a 13).")

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


def sanitizar_nombre(nombre: str) -> str:
    """Limpia un nombre de archivo para que sea válido en el sistema de archivos."""
    nombre = (nombre or "").strip()
    if not nombre:
        return "comprobante.xml"
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre)
    nombre = nombre.strip(". ")
    return nombre or "comprobante.xml"


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


def subdirectorio_periodo(cfg: DownloadConfig) -> str:
    """Nombre de subcarpeta sugerido para organizar la descarga por periodo."""
    dia = "todos" if cfg.dia == 0 else f"{cfg.dia:02d}"
    return f"{cfg.tipo}_{cfg.anio}_{cfg.mes:02d}_{dia}"


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
    TXT_INICIAR_SESION = "Iniciar sesión"

    # Menú de navegación
    MENU_FACTURACION = "FACTURACIÓN ELECTRÓNICA"
    MENU_RECIBIDOS = "Comprobantes electrónicos recibidos"

    # Formulario de consulta (ids JSF confirmados)
    SELECT_ANIO = "#frmPrincipal\\:ano"
    SELECT_MES = "#frmPrincipal\\:mes"
    SELECT_DIA = "#frmPrincipal\\:dia"
    SELECT_TIPO = "#frmPrincipal\\:cmbTipoComprobante"
    BTN_CONSULTAR = "#frmPrincipal\\:btnBuscar"

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


class PaginacionError(Exception):
    """No se pudo avanzar de página tras los reintentos permitidos."""


# Número máximo de reintentos para operaciones frágiles (captcha, paginación).
MAX_REINTENTOS = 5


# ---------------------------------------------------------------------------
# Orquestador de la automatización
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    total_descargados: int = 0
    paginas_procesadas: int = 0
    errores: List[str] = field(default_factory=list)
    carpeta_destino: str = ""


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
    ) -> None:
        self.cfg = config
        self.log_fn = log_fn or (lambda msg: None)
        self.stop_event = stop_event or threading.Event()

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

        # Si el formulario no está visible, entrar por "Iniciar sesión".
        if page.locator(Selectors.PASSWORD).count() == 0:
            enlace = page.get_by_text(Selectors.TXT_INICIAR_SESION, exact=False)
            if enlace.count():
                self.log("Entrando al formulario de login...")
                enlace.first.click()

        page.wait_for_selector(Selectors.PASSWORD, timeout=self.cfg.nav_timeout_ms)
        page.wait_for_timeout(1000)

        self.log("Ingresando credenciales...")
        u = page.locator(Selectors.USUARIO)
        u.click(); u.fill(""); u.press_sequentially(self.cfg.ruc.strip(), delay=35)
        c = page.locator(Selectors.PASSWORD)
        c.click(); c.fill(""); c.press_sequentially(self.cfg.clave, delay=35)
        page.click(Selectors.BTN_INGRESAR)

        try:
            page.wait_for_url(lambda x: "auth/realms" not in x, timeout=30000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        if page.locator(Selectors.PASSWORD).count() > 0:
            raise LoginError(
                "No se pudo iniciar sesión. Verifique el RUC/cédula y la clave "
                "(el portal respondió con un error de credenciales)."
            )
        self._check_stop()
        self.log("Sesión iniciada correctamente.")

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
        self.log("Módulo de comprobantes abierto.")
        return activa

    def _comportamiento_humano(self, page) -> None:
        """Movimiento de mouse para mejorar el puntaje de reCAPTCHA v3."""
        try:
            for (x, y) in [(400, 300), (700, 450), (500, 400), (620, 560)]:
                page.mouse.move(x, y)
                page.wait_for_timeout(200)
            page.mouse.wheel(0, 200)
            page.wait_for_timeout(400)
        except Exception:
            pass

    def _consultar(self, page, tipo_codigo: str) -> bool:
        """Aplica filtros y pulsa Consultar, reintentando ante el reCAPTCHA.

        Devuelve True si la consulta se ejecutó (aunque no haya resultados),
        False si el reCAPTCHA siguió fallando tras los reintentos.
        """
        page.select_option(Selectors.SELECT_ANIO, value=str(self.cfg.anio))
        page.select_option(Selectors.SELECT_MES, value=str(self.cfg.mes))
        page.select_option(Selectors.SELECT_DIA, value=str(self.cfg.dia))
        page.select_option(Selectors.SELECT_TIPO, value=tipo_codigo)

        for intento in range(1, MAX_REINTENTOS + 1):
            self._check_stop()
            self._comportamiento_humano(page)
            page.locator(Selectors.BTN_CONSULTAR).hover()
            page.wait_for_timeout(400)
            page.click(Selectors.BTN_CONSULTAR)
            page.wait_for_timeout(6000)

            if page.locator(Selectors.CAPTCHA_ERROR).count() == 0:
                return True
            self.log(
                f"  reCAPTCHA rechazó la consulta (intento {intento}/{MAX_REINTENTOS}), "
                "reintentando..."
            )
            page.wait_for_timeout(3000)
        return False

    def _descargar_pagina_actual(self, page, destino: str) -> int:
        enlaces = page.locator(Selectors.XML_LINKS)
        total = enlaces.count()
        if total == 0:
            return 0

        descargados = 0
        for i in range(total):
            self._check_stop()
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
                try:
                    with open(tmp, "r", encoding="utf-8", errors="ignore") as fh:
                        clave = extraer_clave_acceso(fh.read())
                    if clave:
                        nombre_final = f"{clave}.xml"
                except Exception:
                    pass
                destino_final = ruta_unica(destino, nombre_final)
                os.replace(tmp, destino_final)

                descargados += 1
                self.log(f"    ✓ {os.path.basename(destino_final)}")
            except Exception as e:  # noqa: BLE001
                self.log(f"    ⚠ Error al descargar fila {i + 1}: {e}")
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

        with sync_playwright() as p:
            ctx = self._lanzar_contexto(p)
            ctx.set_default_timeout(self.cfg.nav_timeout_ms)
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            try:
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
        """Lanza Chrome real con perfil persistente (necesario para reCAPTCHA)."""
        comun = dict(
            user_data_dir=PERFIL_DIR,
            headless=self.cfg.headless,
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
            accept_downloads=True,
            no_viewport=True,
        )
        try:
            return p.chromium.launch_persistent_context(channel="chrome", **comun)
        except Exception:
            self.log("  (Chrome no disponible; usando Chromium. El reCAPTCHA puede fallar.)")
            return p.chromium.launch_persistent_context(**comun)
