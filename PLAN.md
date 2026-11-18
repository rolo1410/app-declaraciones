# Plan de implementación — Asistente de Declaración de IVA (SRI Ecuador, código de impuesto 2011)

## 1. Objetivo

Aplicación de escritorio (macOS y Windows) en Python que:

1. Recibe como entrada el archivo TXT de **comprobantes recibidos** descargado del SRI
   (formato TSV, ej. `9999999999001_Recibidos.txt`).
2. Clasifica y totaliza las compras del período seleccionado.
3. Genera el detalle de **casilleros y valores** que el contribuyente debe verificar/completar
   en la declaración de IVA de SRI en línea (formulario unificado, sucesor del 104).
4. Exporta un reporte (pantalla, Excel y PDF) con los valores por casillero y el detalle de
   facturas que respaldan cada uno.

> **Alcance acordado:** declaración **mensual** (régimen general), solo archivo de *Recibidos*
> (la sección VENTAS se ingresa manualmente en la app porque el SRI la prellena desde
> Facturación Electrónica), se incluyen **todas** las compras (a cédula y a RUC) con
> posibilidad de marcar cada factura con/sin derecho a crédito, y las ventas gravan IVA 15%
> (derecho a crédito tributario total, factor de proporcionalidad = 1.0000).

## 2. Contexto tributario (base de las reglas de cálculo)

- **IVA vigente en Ecuador:** 15 % tarifa general; existen bienes con 5 % y 0 % / exentos.
- **Crédito tributario:** el IVA pagado en compras relacionadas con la actividad económica
  y con ventas gravadas tarifa ≠ 0 % se descuenta del IVA generado en ventas.
- **Facturas a la cédula vs. al RUC:** solo las compras vinculadas a la actividad económica
  sustentan crédito tributario. La app incluirá todas y permitirá reclasificar cada factura:
  - *Con derecho a crédito* → casilleros 500/510/520.
  - *Sin derecho a crédito* (p. ej., gastos personales facturados a la cédula) → 502/512/522.
  - Valor por defecto sugerido: facturas al RUC (`...001`) → con crédito; a la cédula → sin
    crédito (el usuario puede cambiarlo por factura).
- **Notas de crédito:** restan del valor bruto para obtener el valor neto (columnas 510/512/517).
  El archivo las identifica por `TIPO_COMPROBANTE` y `NUMERO_DOCUMENTO_MODIFICADO`.

## 3. Mapeo archivo → casilleros del formulario

### 3.1 Estructura del archivo de entrada

TSV con cabecera, codificación **Windows-1252** (contiene `Ñ`), decimales con punto y sin
cero inicial (`.47`). Columnas:

`RUC_EMISOR, RAZON_SOCIAL_EMISOR, TIPO_COMPROBANTE, SERIE_COMPROBANTE, CLAVE_ACCESO,
FECHA_AUTORIZACION, FECHA_EMISION, IDENTIFICACION_RECEPTOR, VALOR_SIN_IMPUESTOS, IVA,
IMPORTE_TOTAL, NUMERO_DOCUMENTO_MODIFICADO`

### 3.2 Reglas de clasificación por comprobante

Para cada fila del período (filtrado por `FECHA_EMISION`, mes/año elegido):

| Condición | Clasificación | Casilleros |
|---|---|---|
| `IVA > 0` y marcada *con derecho a crédito* | Gravada ≠ 0 % con crédito | 500 (bruto), 510 (neto), 520 (IVA) |
| `IVA > 0` y marcada *sin derecho a crédito* | Gravada ≠ 0 % sin crédito | 502 (bruto), 512 (neto), 522 (IVA) |
| `IVA = 0` | Tarifa 0 % | 507 (bruto), 517 (neto) |
| `TIPO_COMPROBANTE = Nota de crédito` | Resta al neto de su categoría | afecta 510/512/517 |
| Emisor RIMPE Negocio Popular (nota de venta) | Adquisición a negocio popular | 508/518 |

### 3.3 Casilleros calculados (sección COMPRAS)

- **509** = 500 + 502 + 507 + 508 (total bruto adquisiciones)
- **519** = 510 + 512 + 517 + 518 (total neto)
- **529** = 520 + 522 (total impuesto)
- **531/541** adquisiciones no objeto de IVA, **532/542** exentas — normalmente 0 con este
  archivo; editables manualmente.
- **563** factor de proporcionalidad = 1.0000 (ventas 100 % gravadas)
- **564** crédito tributario aplicable = 520 × 563 (con factor 1 → 564 = 520)
- **565** IVA no considerado como crédito = 520 − 564 = 0
- **115** = número de comprobantes recibidos del período; **117/119** = 0 salvo notas de venta.

### 3.4 Sección VENTAS (entrada manual)

El usuario digita el valor bruto de ventas (401) — o lo copia del prellenado del SRI — y la app calcula:

- **411** = 401 − notas de crédito emitidas (ingreso manual)
- **421** = 411 × 15 %; **409/419/429** totales; **482** = 429; **484** = 482 − 483;
  **499** = 483 + 484; **111/113** número de comprobantes emitidos/anulados (manual).

### 3.5 Resumen impositivo (verificación final)

- Impuesto causado = 499 − 564 (si > 0) → valor base a pagar.
- Crédito a favor del período = 564 − 499 (si > 0) → se arrastra al mes siguiente.
- La app mostrará este resumen con una advertencia: retenciones de IVA que le hayan
  efectuado, saldos de crédito de meses anteriores, intereses y multas se ingresan
  manualmente (no constan en el archivo de Recibidos).

### 3.6 Validación con el archivo de ejemplo (junio 2026)

45 facturas → 500+502 = **$1,642.99**, 520+522 = **$245.51**, 507 = **$149.73**, 115 = **45**.
Si solo se marcan con crédito las facturas al RUC: 500 = $1,063.00 y 520 = $159.45.
Estos valores servirán como caso de prueba automatizado.

## 4. Arquitectura de la aplicación

```
declaraciones/
├── app/
│   ├── core/
│   │   ├── models.py        # dataclasses: Comprobante, PeriodoFiscal, Declaracion (Decimal)
│   │   ├── parser.py        # lectura TSV cp1252, normalización de decimales y fechas
│   │   ├── clasificador.py  # reglas de la sección 3.2 (con/sin crédito, tarifa 0%, NC)
│   │   └── calculadora.py   # fórmulas de casilleros (3.3–3.5)
│   ├── gui/
│   │   ├── main_window.py   # ventana principal (Tkinter/ttk)
│   │   ├── vista_comprobantes.py  # tabla con checkbox con/sin crédito por factura
│   │   └── vista_formulario.py    # réplica de casilleros con valores calculados
│   ├── export/
│   │   ├── excel.py         # openpyxl: hoja casilleros + hoja detalle facturas
│   │   └── pdf.py           # reportlab: reporte imprimible
│   └── main.py
├── tests/                   # pytest con el archivo de ejemplo (totales de 3.6)
├── requirements.txt         # openpyxl, reportlab (GUI = Tkinter, sin dependencias)
└── build/                   # especificaciones PyInstaller por SO
```

Decisiones técnicas:

- **Python 3.12 + Tkinter/ttk**: GUI incluida en la biblioteca estándar → empaquetado
  simple y ejecutables livianos en macOS y Windows.
- **`decimal.Decimal`** en todos los cálculos monetarios (nunca `float`), redondeo
  ROUND_HALF_UP a 2 decimales.
- **PyInstaller** para generar `.app` (macOS) y `.exe` (Windows); cada uno se compila en su
  propio sistema operativo.

## 5. Flujo de uso

1. Abrir la app → botón **"Cargar archivo Recibidos"**.
2. La app detecta los períodos disponibles (mes/año de `FECHA_EMISION`) y el usuario elige uno.
3. Tabla de facturas con clasificación sugerida (RUC → con crédito, cédula → sin crédito);
   el usuario ajusta con checkboxes.
4. Panel VENTAS: usuario ingresa el valor prellenado por el SRI (401, 111, 113).
5. Botón **"Calcular declaración"** → vista del formulario con todos los casilleros y valores.
6. Exportar a Excel/PDF para tenerlo a mano al llenar SRI en línea.

## 6. Validaciones y casos borde

- Codificación cp1252 con *fallback* a UTF-8/latin-1; última línea vacía del archivo.
- Decimales tipo `.47` y campos vacíos → `Decimal("0")`.
- Duplicados por `CLAVE_ACCESO` (se ignoran con aviso).
- Facturas autorizadas en mes distinto al de emisión (se usa `FECHA_EMISION`).
- Notas de crédito y notas de venta cuando aparezcan en archivos futuros.
- Verificar consistencia `VALOR_SIN_IMPUESTOS + IVA ≈ IMPORTE_TOTAL` (tolerancia ±0.01;
  diferencias indican ICE u otros impuestos → se reportan como advertencia).
- Descargo visible en la app: *los valores son un pre-cálculo de apoyo; deben verificarse
  contra el prellenado del SRI y, en caso de duda, con un contador.*

## 7. Fases de implementación

| Fase | Entregable | Contenido |
|---|---|---|
| 1 | Núcleo de cálculo + CLI | parser, clasificador, calculadora, tests con archivo de ejemplo |
| 2 | Interfaz gráfica | ventana principal, tabla de facturas, panel ventas, vista formulario |
| 3 | Exportación | reportes Excel y PDF |
| 4 | Empaquetado | ejecutables macOS/Windows con PyInstaller, prueba de instalación |

Extensiones futuras (fuera del alcance inicial): procesar archivo de *Emitidos* para la
sección VENTAS, soporte RIMPE semestral, arrastre automático de crédito tributario entre
meses (persistencia local), retenciones (archivo de comprobantes de retención).
