# Comprobantes SRI — Declaraciones de IVA para contadores (Ecuador)

Aplicación de escritorio (Windows, Linux y macOS) para que un contador lleve la
declaración de IVA de **varios clientes**, mes a mes, en SRI en línea (sucesor
del Formulario 104):

- **Clientes** (inicio) — la cartera con los 12 meses de cada cliente
  (pendiente, declarada, enviada, cobrada) y, al elegir un mes, sus etapas.
- **1 · Descarga** — descarga automatizada de los XML de comprobantes
  electrónicos **recibidos** desde [SRI en línea](https://srienlinea.sri.gob.ec)
  (Playwright + Chrome real, supera el reCAPTCHA v3).
- **2 · Declaración** — clasifica las compras (con/sin derecho a crédito),
  calcula los **casilleros** del formulario de IVA, exporta a Excel y PDF y
  **envía el informe al cliente por correo**.

El flujo de cada mes: **elegir cliente y mes → descargar → calcular → presentar
en el SRI → enviar al cliente → cobrar**, sin manipular archivos intermedios.

> **Importante:** los valores de la declaración son un pre-cálculo de apoyo.
> Verifíquelos siempre contra el prellenado de SRI en línea y, en caso de duda,
> con un contador.

## Descargar los ejecutables

Los ejecutables se compilan automáticamente con GitHub Actions:

- **Release «latest» (recomendado):** <https://github.com/rolo1410/app-declaraciones/releases/latest>
  — `ComprobantesSRI-Setup.exe`, `ComprobantesSRI-windows.zip` y
  `ComprobantesSRI-linux.tar.gz`. Se actualiza automáticamente en **cada merge
  a `main`**; no hace falta crear etiquetas.
- **Artifacts de una compilación puntual:** pestaña **Actions** → ejecución más
  reciente del workflow «Compilar ejecutables» → sección **Artifacts**.

### Windows: instalador (recomendado)

Descargue `ComprobantesSRI-Setup.exe`, ábralo y pulse «Siguiente». Se instala
para el usuario actual (no pide administrador), crea el acceso en el menú Inicio
y, si se marca, en el escritorio. Para actualizar, ejecute el instalador nuevo
encima; los datos (`%LOCALAPPDATA%\ComprobantesSRI`) se conservan, también al
desinstalar. Como el ejecutable no está firmado, SmartScreen puede mostrar
«Windows protegió su PC»: «Más información» → «Ejecutar de todas formas».

El instalador se genera con Inno Setup a partir de `instalador/ComprobantesSRI.iss`.

### Versión portable (zip / tar.gz)

Cada paquete es una carpeta *onedir*: extráigala **completa** y ejecute el
binario que está dentro. En Windows **no** abra el `.exe` desde dentro del zip
(doble clic en el Explorador): falla con «Failed to load Python DLL» porque
Windows no copia la carpeta `_internal`. Use antes «Extraer todo».

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

Solo se puede abrir **una ventana** de la app a la vez: si ya está abierta, un
segundo intento la trae al frente y avisa.

### Clientes (inicio)
La app abre en **Clientes**: un cliente por fila con sus 12 meses del año.

- **gris** pendiente · **naranja** declarada · **verde** enviada al cliente;
  un **✓** dentro del cuadro indica que el mes está cobrado.
- Un clic en un cuadro elige ese **cliente y mes de trabajo**. A la derecha, la
  ficha muestra sus datos (editar, clave del SRI, carpeta, desactivar) y las
  etapas del mes en orden, cada una con su estado y su botón:
  1. **Descargar comprobantes** (cuántos XML hay) → abre «Descarga» con ese mes;
  2. **Calcular la declaración** → abre «Declaración» con los XML del mes;
  3. **Presentar en el SRI** → «Marcar hoy» / «Cambiar…» / «Quitar»;
  4. **Enviar al cliente** → informe por correo (o «Abrir envío» si ya se envió);
  5. **Cobrar** → «Marcar hoy» / «Cambiar…» / «Quitar».

  Debajo, el **resumen del mes** guardado al calcular (ventas, compras,
  impuesto generado, crédito tributario e impuesto a pagar o crédito a favor)
  y la **fecha límite** según el noveno dígito del RUC.
- En Descarga y Declaración, la barra superior muestra el cliente y el mes,
  las etapas «1 Descarga · 2 Declaración» y «‹ Clientes» para volver.

Cada cliente se registra con su RUC, nombre, correo y **clave de SRI en línea
cifrada** (AES-256-GCM). La llave maestra que
protege las claves vive en el almacén de credenciales del sistema: Administrador
de credenciales (Windows), Llavero (macOS) o GNOME Keyring (Ubuntu). La clave
nunca se muestra: solo se puede reemplazar.

Al registrar un cliente se crea su carpeta:

```
~/ComprobantesSRI/                ← ruta base (configurable en «Configuración»)
└── clientes/
    ├── 1712345678/               ← persona natural: su cédula
    │   ├── descargas/recibidos_2026_10_todos/
    │   └── resultados/2026-10/   ← .iva.json, Excel, PDF, CSV
    └── 1790012345001/            ← sociedad / entidad pública: su RUC
```

Con un cliente elegido, la descarga usa su RUC, su clave y su carpeta, y al
guardar o exportar se propone su carpeta `resultados/<AAAA-MM>/`.

- **Copia de emergencia** (en «Configuración»): guarda la llave
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
la app encuentra `SRI_CLAVE`, **Configuración** ofrece importarla cifrada y
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
Con un cliente y mes elegidos, el período ya viene puesto: elija los tipos e
**Iniciar descarga**. Sin cliente, ingrese RUC/cédula, clave, período y carpeta.
Se abre una ventana de Chrome (modo visible) que hace todo el proceso; al
terminar, la app pasa a **Declaración** con esos XML ya cargados.

### 2 · Declaración
- **Cargar XML descargados…** trae los XML del cliente y mes de trabajo (o los
  de una carpeta que elija). Al seleccionar un comprobante se ve su detalle.
- Doble clic en una factura alterna su derecho a crédito tributario. Sugerencia
  inicial: facturas al RUC → con crédito; a la cédula → sin crédito (gasto
  personal).
- Ingrese las ventas brutas (campo 401 prellenado por el SRI) y los contadores
  de comprobantes emitidos.
- El formulario **se calcula solo** al cargar los comprobantes y cada vez que
  cambia el crédito de una compra o un valor de ventas. Arriba se ve siempre el
  resultado (impuesto a pagar o crédito a favor); «Ver formulario ▸» muestra
  cada casillero.
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
Formulario modal: menú **Configuración → Configuración…** (⌘, en macOS,
Ctrl+, en Windows y Linux). En ese mismo menú están la llave maestra, la ruta
de los archivos y la importación del `.env`.

- **Quien prepara la declaración:** nombre o estudio, cédula/RUC, cargo,
  n.º de registro, contacto y logo. Van al pie del PDF y a la firma del correo.
- **Correo de envío (SMTP):** proveedor (Gmail, Outlook, Yahoo, Zoho, servidor
  local de pruebas u otro), **correo de la cuenta** y contraseña. Para un
  servidor sin contraseña (p. ej. Mailpit en `localhost`) desmarque «El
  servidor la pide». Gmail y Outlook exigen una *contraseña de aplicación*.
  La contraseña se guarda cifrada con la llave maestra (como las claves del
  SRI) y no se vuelve a mostrar. «Probar conexión» inicia sesión sin enviar nada.
- **Archivos y seguridad:** ruta base de los archivos, estado de la llave
  maestra, copia de emergencia, restaurar, respaldo completo e importación de
  `SRI_CLAVE` del `.env`.

También puede alimentar la declaración con un **archivo TXT de «Recibidos»**
(botón «Cargar TXT de Recibidos…») si prefiere ese flujo.

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
    main_window.py        Ventana: barra superior + páginas; una sola instancia
    navegacion.py         Barra superior y contenedor de páginas
    contexto.py           Cliente y mes de trabajo compartidos por las páginas
    acciones_clientes.py  Acciones sobre clientes, llave maestra y ruta base
    dialogos.py           Formularios modales (cliente, clave, frase, envío)
    pestana_clientes.py   Inicio: cuadrícula de clientes × 12 meses y ficha del mes
    pestana_descarga.py   1 · Descarga
    pestana_declaracion.py 2 · Declaración (incluye el envío por correo)
    pestana_configuracion.py Configuración (formulario modal)
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
