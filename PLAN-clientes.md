# Plan de implementación — Registro de clientes, claves cifradas y carpetas por cliente

> Documento de instrucciones para implementar esta funcionalidad en **app-declaraciones**
> (Comprobantes SRI). Complementa a `PLAN.md` (cálculo de la declaración), que no cambia.
>
> **Revisión 2 (2026-11-17)**: incorpora el análisis del plan original — ruta base sin
> `clientes/` duplicado, selector de cliente global, control de sesión simplificado,
> verificador de llave, AAD ampliado, candado de descargas y entrega en 4 PRs. Se
> posponen la tabla `archivos` y la rotación de llave (ver §13).

## 1. Objetivo

Hoy la app trabaja con **un solo contribuyente**: el RUC, la clave y la carpeta de descarga
salen de `.env` (`SRI_RUC`, `SRI_CLAVE`, `SRI_DIR`) o se escriben a mano en la pestaña
**Descarga**, y la clave queda **en texto plano** en `.env`.

Se necesita:

1. Una **base de datos local pequeña** con los clientes (RUC) y su **clave de SRI en línea
   guardada de forma segura** (cifrada, nunca en texto plano).
2. Una **ruta base** configurable donde se guardan los archivos descargados y los resultados.
3. Al **crear un cliente**, crear automáticamente **su carpeta**:
   - persona natural → carpeta con su **número de cédula** (10 dígitos);
   - sociedad o entidad pública (no tienen cédula) → carpeta con su **RUC** (13 dígitos).
4. Que las descargas de cada cliente vayan a **su carpeta**, y los resultados (trabajo
   guardado `.iva.json`, exportaciones Excel/PDF/CSV) también.
5. Funcionar igual en **Windows, macOS y Ubuntu (con escritorio)**.

## 2. Decisiones ya tomadas

| Tema | Decisión |
|---|---|
| Lenguaje | Python (Tkinter, Playwright, PyInstaller). Compatible con **Python ≥ 3.10** — usar `from __future__ import annotations` |
| Base de datos | **SQLite** (`sqlite3` de la biblioteca estándar), un archivo local |
| Portal | **SRI en línea**. Usuario = RUC del cliente; solo se cifra la clave |
| Cifrado | **AES-256-GCM** (`cryptography`), nonce aleatorio de 12 bytes por registro, AAD = `"<ruc>\|<portal>\|v<version>"` |
| Llave maestra | En el almacén del sistema vía `keyring`: Administrador de credenciales (Windows), Llavero (macOS), GNOME Keyring / Secret Service (Ubuntu **con escritorio**) |
| Verificación de llave | Tabla `llaves` con un HMAC de control: detecta que la llave del llavero no corresponde a la base antes de descifrar nada |
| Recuperación | Copia de emergencia de la llave maestra protegida con frase de paso (**Argon2id**, `argon2-cffi`) |
| Carpeta del cliente | `cédula` si es persona natural, `RUC` si es sociedad o entidad pública |
| Cliente activo | **Un selector global** en la ventana principal, compartido por las tres pestañas |
| Plataformas | Windows, macOS y Ubuntu con escritorio |

## 3. Estado actual relevante del código

- `app/core/preferencias.py` — lee `SRI_RUC`, `SRI_CLAVE`, `SRI_DIR` de entorno / `.env`.
- `app/gui/pestana_descarga.py` — campos RUC, clave (con «Ver clave») y carpeta; arma `DownloadConfig`.
- `app/core/sri_downloader.py`:
  - `DownloadConfig(ruc, clave, …, download_dir)`, `validar_config()` (ya valida 10/13 dígitos).
  - `sanitizar_nombre()` y `ruta_unica()` — **reutilizarlas**, no duplicarlas.
  - `subdirectorio_periodo()` → `recibidos_AAAA_MM_todos`.
  - `PERFIL_DIR = ~/.sri_descargas/perfil_chrome` — **perfil de Chrome compartido** que
    conserva cookies (necesario para el reCAPTCHA v3).
  - `_login()` / `_sesion_ya_abierta()` — si ya hay sesión abierta, **la reutiliza sin
    comprobar de qué RUC es** (ver §6.4).
- `app/core/analizador.py:~352` — ya extrae `identificacionComprador` /
  `identificacionSujetoRetenido`: **reutilizarlo** para la comprobación de §6.4.
- `app/core/sesion.py` — guarda/carga el trabajo en `*.iva.json`; ya incluye `ruc`.
- `app/gui/main_window.py` — crea el `Notebook` con las tres pestañas.
- `comprobantes_sri.spec` — `hiddenimports` explícitos (añadir los de `keyring`).
- `.github/workflows/build.yml` — las pruebas corren **solo en `ubuntu-latest`**.

> Nota: `preferencias.py`, `sesion.py` y parte de `sri_downloader.py` están en la rama
> `declaracion-ventas0-detalle`, aún no mergeada a `main`. El PR A no depende de ellos;
> los PR B–D sí.

## 4. Diseño

### 4.1 Módulos nuevos

```
app/core/
  plataforma.py   rutas por sistema, config.toml, permisos, escritura atómica, aviso de nube
  ruc.py          validación de RUC/cédula, tipo de contribuyente, nombre de carpeta
  cifrado.py      llave maestra (keyring), cifrar/descifrar, verificador, copia de emergencia
  db.py           conexión SQLite, esquema, migraciones (PRAGMA user_version)
  clientes.py     alta/edición/listado de clientes + creación de carpeta (todo o nada)
app/gui/
  selector_cliente.py   combo «Cliente» global encima del Notebook
  pestana_clientes.py   nueva pestaña «Clientes» (alta, edición, cambio de clave)
```

### 4.2 Ubicaciones por sistema

Usar `platformdirs` (nombre de la app: `ComprobantesSRI`).

| Sistema | Base de datos y configuración (`datos_dir`) | `BASE_PATH` por defecto |
|---|---|---|
| Windows | `%LOCALAPPDATA%\ComprobantesSRI\` | `%USERPROFILE%\ComprobantesSRI\` |
| macOS | `~/Library/Application Support/ComprobantesSRI/` | `~/ComprobantesSRI/` |
| Ubuntu | `~/.local/share/ComprobantesSRI/` | `~/ComprobantesSRI/` |

- Los clientes van en `BASE_PATH/clientes/<carpeta>/` (el segmento `clientes/` lo añade el
  código, **no** forma parte de `BASE_PATH`).
- `BASE_PATH` en la raíz del perfil: visible para el usuario y **no** redirigida por OneDrive
  (que solo redirige Escritorio/Documentos/Imágenes) ni por iCloud (Escritorio/Documentos).
- `BASE_PATH` es **configurable** (`config.toml` en `datos_dir`). Se aceptan `~`,
  `%USERPROFILE%`, `$HOME`; se resuelve a ruta absoluta al arrancar. El TOML se lee con
  `tomllib` (3.11+) o con un parser mínimo en 3.10, y se escribe a mano (solo claves simples).
- **La base SQLite va siempre en `datos_dir`**, nunca en `BASE_PATH`: SQLite se corrompe en
  carpetas sincronizadas o de red.
- **Aviso de nube**: si `BASE_PATH` cae dentro de OneDrive, iCloud Drive, Dropbox o Google
  Drive (segmentos de ruta y `%OneDrive%`), mostrar advertencia (datos de terceros, LOPDP).

### 4.3 Estructura de carpetas

```
BASE_PATH/                              (p. ej. ~/ComprobantesSRI)
└── clientes/
    ├── 1712345678/                      ← persona natural: cédula
    │   ├── descargas/
    │   │   └── recibidos_2026_10_todos/   ← nombre actual de subdirectorio_periodo()
    │   └── resultados/
    │       └── 2026-10/                   ← .iva.json, Excel, PDF, CSV del período
    └── 1790012345001/                   ← sociedad / entidad pública: RUC
        ├── descargas/
        └── resultados/
```

### 4.4 Modelo de datos (SQLite)

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE clientes (
  id                 INTEGER PRIMARY KEY,
  ruc                TEXT NOT NULL UNIQUE CHECK (length(ruc) = 13 AND ruc NOT GLOB '*[^0-9]*'),
  tipo_contribuyente TEXT NOT NULL CHECK (tipo_contribuyente IN ('natural','sociedad','publica')),
  cedula             TEXT UNIQUE CHECK (cedula IS NULL OR (length(cedula) = 10 AND cedula NOT GLOB '*[^0-9]*')),
  carpeta            TEXT NOT NULL UNIQUE,          -- cédula o RUC
  nombre             TEXT NOT NULL,
  activo             INTEGER NOT NULL DEFAULT 1,
  creado_en          TEXT NOT NULL,                 -- ISO 8601 UTC
  actualizado_en     TEXT NOT NULL,
  CHECK ((tipo_contribuyente = 'natural') = (cedula IS NOT NULL)),
  CHECK (carpeta = coalesce(cedula, ruc))
);

CREATE TABLE llaves (
  version      INTEGER PRIMARY KEY CHECK (version >= 1),
  verificador  BLOB NOT NULL,          -- HMAC-SHA256(llave, "ComprobantesSRI/verificador")
  creada_en    TEXT NOT NULL
);

CREATE TABLE credenciales (
  id               INTEGER PRIMARY KEY,
  id_cliente       INTEGER NOT NULL REFERENCES clientes(id),
  portal           TEXT NOT NULL DEFAULT 'sri_en_linea' CHECK (portal IN ('sri_en_linea')),
  usuario          TEXT NOT NULL,                   -- por defecto, el RUC
  clave_cifrada    BLOB NOT NULL,
  nonce            BLOB NOT NULL CHECK (length(nonce) = 12),
  version_llave    INTEGER NOT NULL REFERENCES llaves(version),
  actualizado_en   TEXT NOT NULL,
  UNIQUE (id_cliente, portal)
);

CREATE TABLE bitacora (
  id          INTEGER PRIMARY KEY,
  id_cliente  INTEGER REFERENCES clientes(id),
  accion      TEXT NOT NULL,          -- 'cliente_creado', 'clave_actualizada', 'descarga', 'exportacion', ...
  detalle     TEXT,                   -- NUNCA claves ni datos descifrados; rutas relativas a BASE_PATH con '/'
  ocurrido_en TEXT NOT NULL
);
```

- Versionar el esquema con `PRAGMA user_version` y migraciones en `db.py`.
- Una conexión **por hilo/operación** (la descarga corre en otro hilo; `sqlite3` no comparte
  conexiones entre hilos).
- Los clientes no se borran: se marcan `activo = 0`.
- **Tabla `archivos` pospuesta** (§13): la carpeta es la fuente de verdad; descargas y
  exportaciones se anotan en `bitacora`.

## 5. Reglas de validación del RUC (`app/core/ruc.py`)

| Tercer dígito | Tipo | Estructura | Verificador | Carpeta |
|---|---|---|---|---|
| 0–5 | `natural` | cédula (10) + `001` | módulo 10 sobre la cédula — **obligatorio** | cédula |
| 6 | `publica` | 8 dígitos + verificador (9.º) + `0001` | módulo 11 — solo advertencia | RUC |
| 9 | `sociedad` | 9 dígitos + verificador (10.º) + `001` | módulo 11 — solo advertencia | RUC |
| 7, 8 | — | se rechaza | | |

- **Siempre**: 13 dígitos; provincia (2 primeros) en `01`–`24` o `30`; establecimiento final ≠ `000`.
- `carpeta_de(ruc) -> str` es la **única** función que decide el nombre de la carpeta.

## 6. Seguridad

### 6.1 Cifrado de la clave (`app/core/cifrado.py`)

- Llave maestra: 32 bytes de `os.urandom`, guardada con
  `keyring.set_password("ComprobantesSRI", "llave_maestra_v<N>", base64)`.
- `cifrar(clave, ruc, portal) -> (nonce, cifrado, version)` con `AESGCM`,
  `aad = f"{ruc}|{portal}|v{version}"`.
- `descifrar(...)` falla si cambian el RUC, el portal, la versión, el nonce, el cifrado o la
  llave: una clave cifrada no se puede «mover» a otro cliente.
- **Verificador**: al crear la llave se guarda en `llaves` un HMAC de una constante. Al
  arrancar se comprueba; si no coincide → «La llave del sistema no corresponde a esta base:
  restaure la copia de emergencia».
- **Copia de emergencia**: archivo `.llave` (JSON: versión, sal, parámetros Argon2id, nonce,
  llave cifrada con AES-GCM). Se ofrece al configurar por primera vez y desde la pestaña
  Clientes; «Restaurar llave» la vuelve a poner en el llavero tras validar el verificador.
  **Sin llave y sin copia, las claves se pierden.**
- **Sin llavero real** (Linux sin Secret Service): no fallar; ofrecer el modo «frase de paso
  al abrir la app» (la misma derivación Argon2id de la copia de emergencia).

### 6.2 Manejo de la clave en la app

- Se descifra **solo en memoria, justo antes del login**, y se pasa a `DownloadConfig.clave`.
- Nunca en logs, `bitacora`, mensajes de error, `__repr__` ni archivos.
  `DownloadConfig.clave` con `field(repr=False)`.
- La pestaña Clientes permite **reemplazar** la clave, no mostrarla.
- Ante un `LoginError` de un cliente registrado, ofrecer «Actualizar clave de este cliente»
  (el SRI obliga a cambiarla periódicamente).
- `SRI_CLAVE` en `.env` queda **obsoleta**: si existe, ofrecer importarla al cliente
  correspondiente y avisar que debe borrarse del `.env`.

### 6.3 Permisos (`app/core/plataforma.py`)

| Sistema | `restringir_permisos(ruta)` |
|---|---|
| macOS / Ubuntu | `chmod 0o700` en carpetas, `0o600` en archivos. La carpeta `datos_dir` en `0o700` protege también `-wal`/`-shm` de SQLite |
| Windows | Dentro del perfil la ACL ya está restringida → no se hace nada. Fuera del perfil (p. ej. `D:\`): `icacls <ruta> /inheritance:r /grant:r *<SID>:(OI)(CI)F /grant:r *S-1-5-18:(OI)(CI)F` (usuario actual + SYSTEM; SID con `whoami /user`; `subprocess` sin `shell=True`) |

### 6.4 Sesión del SRI con varios clientes

Riesgo: el perfil persistente conserva la sesión y `_login()` la reutiliza; descargar para B
podría usar la sesión de A.

1. Antes de descargar para un cliente registrado, **borrar solo las cookies del SRI**:
   `ctx.clear_cookies(domain=re.compile(r"(^|\.)sri\.gob\.ec$"))` (Playwright ≥ 1.43 acepta
   regex; una cadena exacta no cubre `srienlinea.sri.gob.ec` y `.sri.gob.ec` a la vez).
   **No** borrar el perfil (la reputación del reCAPTCHA vive en las cookies de Google).
   Con esto siempre se inicia sesión de nuevo; la reutilización queda solo para el modo
   «sin cliente registrado».
2. ~~Verificar el RUC de la sesión abierta~~ — **descartado**: exigiría leer el perfil del SRI
   con selectores frágiles y el punto 1 ya lo hace innecesario.
3. Defensa adicional al guardar cada XML (reutilizando la extracción de `analizador.py`):
   identificación = `identificacionComprador` o `identificacionSujetoRetenido`.
   - coincide con el RUC **o** la cédula del cliente → se guarda;
   - existe y **no** coincide → **no se guarda** y se avisa;
   - no existe (p. ej. guía de remisión) → se guarda con advertencia en el log.
4. **Candado de descargas**: el perfil de Chrome no se puede abrir dos veces. Archivo
   `descarga.lock` en `datos_dir` (con PID); una segunda descarga se rechaza o se pone en cola.

## 7. Multiplataforma: nombres y escritura de archivos

La carpeta del cliente es segura (solo dígitos validados). Para los **nombres de archivo**,
ampliar `sanitizar_nombre()` (no crear otra función):

| Problema | Dónde | Medida |
|---|---|---|
| `< > : " / \ \| ? *` y controles | Windows | Ya cubierto: reemplazar por `_` |
| `CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9` (también con extensión) | Windows | Prefijo `_` |
| Punto o espacio final | Windows | Ya cubierto (`strip(". ")`) |
| Unicode NFD vs NFC (`ñ`, tildes) | macOS | `unicodedata.normalize("NFC", nombre)` |
| Ruta > 260 caracteres | Windows | Nombres ≤ 100 caracteres; comprobar longitud total antes de escribir |

- Mayúsculas/minúsculas en `ruta_unica()`: no hace falta (los XML se nombran con la clave de
  acceso, solo dígitos).
- Construir rutas **siempre** con `pathlib.Path`.
- Toda ruta final debe quedar dentro de `BASE_PATH`: `plataforma.dentro_de(ruta, base)`.
- Escritura atómica: temporal en la misma carpeta + `os.replace()`; en Windows reintentar
  hasta 3 veces si el archivo está bloqueado (antivirus, Excel).

### Alta de cliente (todo o nada)

```python
def crear_cliente(ruc: str, nombre: str, clave: str) -> Cliente:
    info = ruc_mod.analizar(ruc)                  # tipo, cédula, advertencias
    carpeta = base_path() / "clientes" / info.carpeta
    if not plataforma.dentro_de(carpeta, base_path()):
        raise ...
    with db.transaccion() as cx:                  # rollback si algo falla
        cliente = db.insertar_cliente(cx, info, nombre)
        db.guardar_credencial(cx, cliente.id, usuario=ruc, clave=clave)
        nueva = not carpeta.exists()
        try:
            for sub in ("descargas", "resultados"):
                (carpeta / sub).mkdir(parents=True, exist_ok=True)
            plataforma.restringir_permisos(carpeta)
        except OSError:
            if nueva:
                shutil.rmtree(carpeta, ignore_errors=True)
            raise
    return cliente
```

## 8. Cambios en la interfaz

- **Selector de cliente global** (`selector_cliente.py`) encima del `Notebook`:
  «Cliente: [combo] · Gestionar…». Guarda `App.cliente_activo` y notifica a las pestañas.
  Incluye la opción «— Sin cliente registrado —» (flujo actual).
- **Nueva pestaña «Clientes»** (antes de Descarga): lista, buscar por RUC/nombre, alta
  (RUC, nombre, clave), cambiar clave, desactivar, «Abrir carpeta» (`os.startfile` /
  `open` / `xdg-open`), configurar `BASE_PATH`, exportar/restaurar copia de emergencia,
  «Respaldo completo» (copia de la base con la API `backup` de `sqlite3` + `.llave`).
- **Pestaña Descarga**: con cliente activo, RUC/clave/carpeta se ocultan y el destino es
  `BASE_PATH/clientes/<carpeta>/descargas/`. Sin cliente, se mantienen los campos manuales.
- **Análisis / Declaración**: al guardar (`.iva.json`) o exportar, proponer
  `…/<carpeta>/resultados/<AAAA-MM>/` y anotar en `bitacora`. Al abrir un `.iva.json` cuyo
  `ruc` no es el del cliente activo, avisar y ofrecer cambiar de cliente.

## 9. Dependencias y empaquetado

- `requirements.txt`: `cryptography`, `keyring`, `platformdirs`, `argon2-cffi`.
- `comprobantes_sri.spec`: `collect_submodules("keyring.backends")`, `"secretstorage"`,
  `"jeepney"`, `"win32ctypes.core"` (Windows); verificar `cryptography` y `argon2`.
- `--selftest`: comprobar backend real de `keyring` (no `fail.Keyring`) y escritura en `BASE_PATH`.
- README: Ubuntu con inicio de sesión automático (el llavero pide contraseña la primera vez);
  macOS sin firma (el Llavero vuelve a pedir permiso en cada versión → firmar con `codesign`).

## 10. Pruebas

- `tests/conftest.py`: backend de `keyring` en memoria (subclase de `KeyringBackend`) y
  `BASE_PATH`/`datos_dir` en `tmp_path`.
- `test_ruc.py`: natural válida/inválida, sociedad con y sin verificador (advertencia),
  pública, tercer dígito 7/8, provincia inválida, establecimiento `000`, longitud.
- `test_cifrado.py`: ida y vuelta; RUC/portal distinto falla; llave distinta falla;
  verificador; exportar/restaurar copia de emergencia; frase incorrecta.
- `test_db.py`: esquema nuevo, `user_version`, CHECK rechazan datos incoherentes.
- `test_clientes.py`: alta crea carpeta y subcarpetas; RUC duplicado; fallo al crear la
  carpeta deshace el registro; carpeta = cédula o RUC; la clave no aparece en claro en el `.db`.
- `test_plataforma.py`: `CON.xml`, `ñ` en NFD, ruta fuera de `BASE_PATH`, permisos `0700`
  (POSIX), config.toml, aviso de nube, escritura atómica.
- `test_sri_downloader.py` (PR C): destino derivado del cliente; XML de otro RUC rechazado.

**CI**: job de pruebas en matriz `ubuntu-latest`, `windows-latest`, `macos-latest`.

## 11. Entrega en 4 PRs

| PR | Contenido | Criterio de aceptación |
|---|---|---|
| **A · Núcleo** | `plataforma`, `ruc`, `db`, `cifrado`, `clientes` + pruebas + matriz de CI. Sin cambios de UI | Pruebas pasan en los 3 sistemas |
| **B · Clientes** | Pestaña Clientes, selector global, copia de emergencia, importación de `SRI_CLAVE` | Alta/edición manual en los 3 sistemas; la clave deja de estar en `.env` |
| **C · Descarga** | Destino por cliente, borrado de cookies del SRI, comprobación de comprador, candado | Dos clientes seguidos dejan cada XML en su carpeta |
| **D · Cierre** | Carpeta de resultados por defecto, `.spec`, `--selftest`, README | Ejecutables arrancan y guardan una clave; README actualizado |

### Estado (2026-11-17, rama `clientes-claves-cifradas`)

| PR | Estado |
|---|---|
| A · Núcleo | ✅ Hecho y probado (Python 3.10 y 3.12, macOS) |
| B · Clientes | ✅ Hecho: pestaña, selector global, copia de emergencia, respaldo completo, importación de `SRI_CLAVE`, frase de paso sin almacén del sistema |
| C · Descarga | ✅ Hecho: destino por cliente, cookies del SRI, comprobación de comprador, candado, aviso de clave rechazada |
| D · Cierre | ✅ Resultados por cliente + bitácora, `.spec`, `--selftest` (Chrome, keyring, cifrado, ruta base), README. Ejecutable de macOS verificado; Windows/Linux pendientes de CI |

Pendiente de verificar a mano: alta/edición en Windows y Ubuntu, descarga real de
dos clientes seguidos contra el portal del SRI.

> La rama incluye `declaracion-ventas0-detalle` (fusionada): conviene mergear esa
> rama a `main` antes que esta, o abrir un solo MR con ambas.

## 12. Reglas de trabajo

- Partir de `main` actualizado, rama nueva (`clientes-claves-cifradas`), push de la rama; nunca a `main`.
- Commits pequeños, con sus pruebas.
- No tocar `calculadora.py` ni `clasificador.py`.
- No guardar ni registrar claves en texto plano (código, pruebas, logs, CI).
- No borrar `~/.sri_descargas/perfil_chrome`.

## 13. Pospuesto

| Qué | Por qué |
|---|---|
| Tabla `archivos` (registro con `sha256`) | La carpeta es la fuente de verdad; el registro se desincroniza si el usuario borra o reexporta. Basta `bitacora` |
| Rotación de llave | Se mantiene `version_llave` desde el día 1; se implementa cuando haga falta |
| Mover `datos/recibidos_*` a la carpeta del cliente | Opcional y arriesgado; se documenta cómo hacerlo a mano |
