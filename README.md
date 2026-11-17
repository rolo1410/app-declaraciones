# Comprobantes SRI — Descarga, Análisis y Declaración de IVA (Ecuador)

Aplicación de escritorio (Windows, Linux y macOS) que integra en **una sola app con tres
pestañas** todo el flujo de la declaración de IVA en SRI en línea (sucesor del
Formulario 104):

1. **Descarga** — descarga automatizada de los XML de comprobantes electrónicos
   **recibidos** desde el portal [SRI en línea](https://srienlinea.sri.gob.ec)
   (Playwright + Chrome real, supera el reCAPTCHA v3).
2. **Análisis** — lee los XML descargados, los lista con navegación por teclado,
   muestra los **totales del lote** (base gravada / 0 %, IVA por tarifa,
   retenido) y **exporta a CSV/Excel**.
3. **Declaración** — clasifica las compras (con/sin derecho a crédito) y calcula
   los **casilleros** del formulario de IVA, con exportación a Excel y PDF.

El flujo natural es continuo: **Descargar → Análisis → «Enviar a Declaración»**,
sin salir de la aplicación ni manipular archivos intermedios.

> **Importante:** los valores de la declaración son un pre-cálculo de apoyo.
> Verifíquelos siempre contra el prellenado de SRI en línea y, en caso de duda,
> con un contador.

## Descargar los ejecutables

Los ejecutables se compilan automáticamente con GitHub Actions:

- **Release «latest» (recomendado):** <https://github.com/rolo1410/app-declaraciones/releases/latest>
  — `ComprobantesSRI-windows.zip` y `ComprobantesSRI-linux.tar.gz`. Se actualiza
  automáticamente en **cada merge a `main`**; no hace falta crear etiquetas.
- **Artifacts de una compilación puntual:** pestaña **Actions** → ejecución más
  reciente del workflow «Compilar ejecutables» → sección **Artifacts**.

Cada paquete es una carpeta *onedir*: extráigala **completa** y ejecute el
binario que está dentro.

```bash
# Windows (PowerShell)
Expand-Archive ComprobantesSRI-windows.zip -DestinationPath .
.\ComprobantesSRI\ComprobantesSRI.exe

# Linux
tar -xzf ComprobantesSRI-linux.tar.gz
./ComprobantesSRI/ComprobantesSRI
```

> **Requisito en la máquina destino:** tener **Google Chrome** instalado (la
> pestaña Descarga usa el Chrome del sistema para superar el reCAPTCHA).
> En Linux hace falta además Tcl/Tk (`sudo apt install python3-tk` en Debian/Ubuntu
> si la ventana no abre).

> **macOS:** no se publica ejecutable. El proyecto corre igual en macOS, pero el
> `.app` requiere firma y notarización de Apple para distribuirse sin que
> Gatekeeper lo bloquee. Compílelo localmente con `./build.sh`.

## Requisitos (desarrollo)

- Python 3.10 o superior (con Tkinter, incluido en el instalador de python.org).
- Google Chrome instalado (pestaña Descarga).
- Dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium   # respaldo; se prefiere Chrome real
```

## Uso — interfaz gráfica

```bash
./run.sh            # entorno virtual del proyecto + variables de .env
python -m app.main  # equivalente, si ya activó el venv
```

> `run.sh` usa `.venv/bin/python`: Playwright está instalado ahí, no en el
> Python del sistema. Con otro intérprete la descarga falla con
> `No module named 'playwright'`.

### Valores por defecto (opcional)
Copie `.env.example` a `.env` y complete las variables para que la pestaña
**Descarga** se autocomplete al abrir. La app lee el `.env` por su cuenta, así
que funciona igual con `./run.sh`, con `python -m app.main` o con el ejecutable
empaquetado. `.env` está en `.gitignore`: las credenciales no se versionan.

Se busca en el directorio actual, luego en la raíz del proyecto y, en el
ejecutable, junto al binario. Una variable exportada en la terminal tiene
prioridad sobre el archivo.

| Variable | Campo que rellena |
|---|---|
| `SRI_RUC` | RUC / C.I. / Pasaporte |
| `SRI_CLAVE` | Clave |
| `SRI_DIR` | Directorio de descarga |

### 1 · Descarga
Ingrese RUC/cédula y clave, seleccione año/mes/día y los tipos de comprobante,
elija la carpeta de descarga e **Iniciar descarga**. Se abre una ventana de
Chrome (modo visible) que hace todo el proceso; al terminar, la app pasa
automáticamente a **Análisis** apuntando a la carpeta descargada.

### 2 · Análisis
Revise los comprobantes y los totales del lote. Exporte a CSV/Excel si lo desea.
Pulse **«Enviar a Declaración ▸»** para pasar las facturas al cálculo del IVA.

### 3 · Declaración
- Doble clic en una factura alterna su derecho a crédito tributario. Sugerencia
  inicial: facturas al RUC → con crédito; a la cédula → sin crédito (gasto
  personal).
- Ingrese las ventas brutas (campo 401 prellenado por el SRI) y los contadores
  de comprobantes emitidos.
- **Calcular declaración** muestra cada casillero con su valor y el resumen
  (impuesto a pagar o crédito a favor).
- **Exportar** a Excel o PDF.

También puede alimentar la declaración con un **archivo TXT de «Recibidos»**
(botón «Cargar archivo Recibidos (TXT)…») si prefiere ese flujo.

## Uso — línea de comandos (declaración desde TXT)

```bash
python -m app.main 9999999999001_Recibidos.txt --periodo 2026-06 --ventas 5586.96
python -m app.main archivo.txt --todas-con-credito     # todas las compras con crédito
```

## Sobre el reCAPTCHA (pestaña Descarga)

La consulta del SRI está protegida por **reCAPTCHA v3** (invisible, por puntaje).
La app lo supera automáticamente usando **Chrome real** (`channel="chrome"`), un
**perfil persistente** en `~/.sri_descargas/perfil_chrome` que acumula reputación
entre ejecuciones (*no borre esa carpeta*), y movimientos de mouse "humanos" con
reintentos. Por eso el **modo headless no se recomienda**.

## Pruebas

```bash
python -m pytest tests/ -q
```

## Empaquetado (ejecutables)

Se empaqueta con **PyInstaller** usando el spec `comprobantes_sri.spec` (incluye
el driver de Playwright y los `assets/`, pero no los navegadores):

```bash
./build.sh
```

Diagnóstico incluido: `ComprobantesSRI --selftest` verifica que Playwright puede
lanzar Chrome y escribe el resultado en `<temp>/sri_selftest.log` (código 0 = OK).

En la nube, `.github/workflows/build.yml` corre las pruebas, compila **Windows**
(`windows-latest`) y **Linux** (`ubuntu-22.04`) y publica los paquetes en el
Release **`latest`** en cada merge a `main`. macOS no se compila en CI: el `.app`
necesita firma/notarización de Apple para poder distribuirse.

En local, `./build.sh` compila para el sistema donde se ejecuta (en macOS genera
`dist/ComprobantesSRI.app`).

## Estructura del proyecto

```
launcher.py               Punto de entrada del ejecutable (imports absolutos)
comprobantes_sri.spec     Configuración de PyInstaller
assets/                   Íconos y marca de agua
app/
  main.py                 CLI (declaración desde TXT) + GUI + --selftest
  core/
    sri_downloader.py     Descarga automatizada (Playwright)
    analizador.py         Parseo de XML + totales del lote + exportación
    adaptador.py          Puente XML → modelo de la declaración
    parser.py             Lectura del TXT de «Recibidos» (flujo alterno)
    models.py             Modelos de la declaración (Decimal)
    clasificador.py       Clasificación con/sin crédito
    calculadora.py        Cálculo de los casilleros
  gui/
    main_window.py        Ventana con las 3 pestañas
    pestana_descarga.py   Pestaña 1 · Descarga
    pestana_analisis.py   Pestaña 2 · Análisis
    pestana_declaracion.py Pestaña 3 · Declaración
    recursos.py           Utilidades de recursos e imágenes
  export/                 Reportes Excel (openpyxl) y PDF (reportlab)
tests/                    Pruebas unitarias (pytest)
```

## Reglas de cálculo aplicadas (declaración)

- IVA tarifa general 15 % (campo 421 = campo 411 × 15 %).
- Compras gravadas ≠0 % **con** derecho a crédito → 500/510/520; **sin** derecho → 502/512/522.
- Compras tarifa 0 % → 507/517; notas de venta (negocios populares) → 508/518.
- Comprobantes con **tarifas mixtas** (15 % y 0 % en el mismo XML): la base gravada
  va a 500/510 y la porción 0 % a 507/517.
- Las notas de crédito restan del valor **neto** (no del bruto).
- Los comprobantes de **retención** no se consideran compras (se omiten).
- Factor de proporcionalidad (563) = 1.0000 (ventas 100 % gravadas) → 564 = 520.
- Duplicados por clave de acceso se ignoran con aviso.
