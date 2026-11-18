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

### Clientes
La pestaña **Clientes** guarda los contribuyentes con los que trabaja: RUC,
nombre y **clave de SRI en línea cifrada** (AES-256-GCM). La llave maestra que
protege las claves vive en el almacén de credenciales del sistema: Administrador
de credenciales (Windows), Llavero (macOS) o GNOME Keyring (Ubuntu). La clave
nunca se muestra: solo se puede reemplazar.

Al registrar un cliente se crea su carpeta:

```
~/ComprobantesSRI/                ← ruta base (configurable en «Clientes»)
└── clientes/
    ├── 1712345678/               ← persona natural: su cédula
    │   ├── descargas/recibidos_2026_10_todos/
    │   └── resultados/2026-10/   ← .iva.json, Excel, PDF, CSV
    └── 1790012345001/            ← sociedad / entidad pública: su RUC
```

El combo **Cliente** de la parte superior elige el cliente activo para todas las
pestañas: la descarga usa su RUC, su clave y su carpeta, y al guardar o exportar
se propone su carpeta `resultados/<AAAA-MM>/`. Con «— Sin cliente registrado —»
la app funciona como antes (RUC, clave y carpeta a mano).

- **Copia de emergencia**: «Exportar copia de emergencia…» guarda la llave
  maestra cifrada con una frase de paso (archivo `.llave`). Guárdela **fuera del
  equipo**. Sin la llave y sin la copia, las claves guardadas se pierden y hay
  que volver a pedirlas a cada cliente. «Respaldo completo…» guarda la base de
  clientes junto con la copia.
- La base de clientes (SQLite) está en `%LOCALAPPDATA%\ComprobantesSRI`
  (Windows), `~/Library/Application Support/ComprobantesSRI` (macOS) o
  `~/.local/share/ComprobantesSRI` (Linux). No la mueva a una carpeta
  sincronizada (OneDrive, iCloud, Dropbox): SQLite puede corromperse.
- Si la ruta base cae dentro de una carpeta en la nube, la app avisa: son datos
  personales y tributarios de terceros (LOPDP).
- Antes de descargar para un cliente se cierra cualquier sesión previa del SRI
  (solo se borran las cookies `*.sri.gob.ec`, no el perfil de Chrome), y un XML
  cuyo comprador no es el cliente no se guarda en su carpeta.

**Ubuntu**: hace falta un llavero desbloqueado (GNOME Keyring / Secret Service).
Con inicio de sesión automático el llavero no se desbloquea solo y el sistema
pedirá su contraseña la primera vez. Si no hay llavero, la app protege las claves
con una frase de paso que pide cada vez que se abre.

**macOS**: si el `.app` no está firmado, el Llavero vuelve a pedir permiso tras
cada actualización de la app (el acceso va ligado a la firma).

### Valores por defecto (opcional, obsoleto para la clave)
`SRI_CLAVE` deja la clave en texto plano: es preferible registrar el cliente. Si
la app encuentra `SRI_CLAVE`, la pestaña **Clientes** ofrece importarla cifrada y
luego quitarla del `.env`.

Copie `.env.example` a `.env` y complete las variables para que la pestaña
**Descarga** se autocomplete al abrir (descarga sin cliente registrado). La app lee el `.env` por su cuenta, así
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
Con un cliente activo basta elegir el periodo y los tipos. Sin cliente,
ingrese RUC/cédula y clave, seleccione año/mes/día y los tipos de comprobante,
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
- **Enviar al cliente por correo…** arma el informe y lo envía desde su cuenta
  (ver «Configuración»). Puede editar destinatarios, asunto y mensaje, y elegir
  los adjuntos:
  - PDF con los casilleros, su logo y «Preparado por»;
  - el detalle en Excel;
  - los XML del período en un `.zip` (se buscan por clave de acceso en la
    carpeta `descargas/` del cliente).

  El mensaje trae el resumen (impuesto a pagar o crédito a favor) y la fecha
  límite según el noveno dígito del RUC. Una copia del paquete queda en
  `resultados/<AAAA-MM>/envio_<fecha>/` y el envío se anota en la bitácora.

### Configuración
- **Quien prepara la declaración:** nombre o estudio, cédula/RUC, cargo,
  n.º de registro, contacto y logo. Van al pie del PDF y a la firma del correo.
- **Correo de envío (SMTP):** proveedor (Gmail, Outlook, Yahoo, Zoho u otro),
  usuario y contraseña. Gmail y Outlook exigen una *contraseña de aplicación*.
  La contraseña se guarda cifrada con la llave maestra (como las claves del
  SRI) y no se vuelve a mostrar. «Probar conexión» inicia sesión sin enviar nada.
- Se abre también con ⌘, (macOS) o desde el menú «Ir».

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
lanzar Chrome, que hay un almacén de credenciales real y que se puede escribir
en la ruta base; escribe el resultado en `<temp>/sri_selftest.log` (código 0 = OK).

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
assets/                   Íconos (.icns, .ico, .png); fuentes/ tiene los SVG originales
app/
  main.py                 CLI (declaración desde TXT) + GUI + --selftest
  core/
    sri_downloader.py     Descarga automatizada (Playwright)
    clientes.py           Registro de clientes, claves y carpetas
    cifrado.py            Llave maestra (keyring), AES-GCM, copia de emergencia
    db.py                 Base SQLite (esquema y migraciones)
    ruc.py                Validación de RUC / cédula
    plataforma.py         Rutas, permisos y detalles por sistema operativo
    analizador.py         Parseo de XML + totales del lote + exportación
    adaptador.py          Puente XML → modelo de la declaración
    parser.py             Lectura del TXT de «Recibidos» (flujo alterno)
    models.py             Modelos de la declaración (Decimal)
    clasificador.py       Clasificación con/sin crédito
    calculadora.py        Cálculo de los casilleros
    perfil.py             Datos de quien declara y servidor de correo (perfil.json)
    informe.py            Paquete para el cliente (PDF, Excel, XML) y texto del correo
    correo.py             Envío por SMTP
  gui/
    main_window.py        Ventana: selector de cliente + pestañas
    contexto.py           Cliente activo compartido por las pestañas
    selector_cliente.py   Combo «Cliente» global
    dialogos.py           Formularios modales (cliente, clave, frase, envío)
    pestana_clientes.py   Pestaña Clientes
    pestana_descarga.py   Pestaña 1 · Descarga
    pestana_analisis.py   Pestaña 2 · Análisis
    pestana_declaracion.py Pestaña 3 · Declaración (incluye el envío por correo)
    pestana_configuracion.py Pestaña Configuración
    menu_principal.py     Barra de menús (Clientes, Ir, Ventana)
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
