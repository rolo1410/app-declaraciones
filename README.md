# Asistente de Declaración de IVA — SRI Ecuador (impuesto 2011)

Aplicación de escritorio (macOS y Windows) que procesa el archivo TXT de
**comprobantes recibidos** descargado del SRI y calcula los valores de los
casilleros de la declaración de IVA en SRI en línea (sucesor del Formulario 104).

> **Importante:** los valores son un pre-cálculo de apoyo. Verifíquelos siempre
> contra el prellenado de SRI en línea y, en caso de duda, con un contador.

## Requisitos

- Python 3.10 o superior (con Tkinter, incluido en el instalador oficial de python.org).
- Dependencias para exportar reportes: `pip install -r requirements.txt`.

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Uso — interfaz gráfica

```bash
python -m app.main
```

1. **Cargar archivo Recibidos…** — seleccione el TXT descargado del SRI
   (ej. `0603545351001_Recibidos.txt`) y elija el período (mes).
2. **Pestaña 1 · Comprobantes recibidos** — revise la clasificación de cada
   factura. Doble clic alterna el derecho a crédito tributario. Sugerencia
   inicial: facturas al RUC → con crédito; a la cédula → sin crédito (gasto
   personal). Ingrese además las ventas brutas del período (el valor que el
   SRI prellena en el campo 401) y los contadores de comprobantes emitidos.
3. **Calcular declaración** — la pestaña 2 muestra cada casillero con su valor
   y el resumen (impuesto a pagar o crédito a favor).
4. **Exportar** — genere el reporte en Excel (casilleros + detalle de facturas)
   o PDF para tenerlo a mano al llenar SRI en línea.

## Uso — línea de comandos

```bash
python -m app.main 0603545351001_Recibidos.txt --periodo 2026-06 --ventas 5586.96
python -m app.main archivo.txt --todas-con-credito     # todas las compras con crédito
```

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Empaquetado (ejecutables) — Fase 4

Cada ejecutable se genera **en su propio sistema operativo** con PyInstaller:

```bash
pip install pyinstaller

# macOS (genera dist/DeclaracionIVA.app)
pyinstaller --windowed --name DeclaracionIVA --osx-bundle-identifier ec.kuya.declaraciones app/main.py

# Windows (genera dist\DeclaracionIVA.exe)
pyinstaller --windowed --onefile --name DeclaracionIVA app\main.py
```

Notas:
- En macOS, para distribuir fuera de su equipo necesitará firmar/notarizar la app
  o los usuarios deberán abrirla con clic derecho → Abrir la primera vez.
- En Windows, SmartScreen puede pedir confirmación por ser un ejecutable sin firma.

## Estructura del proyecto

```
app/core/       modelos, parser del TSV, clasificador y calculadora de casilleros
app/gui/        interfaz gráfica Tkinter
app/export/     reportes Excel (openpyxl) y PDF (reportlab)
tests/          pruebas unitarias (usa el archivo real de junio 2026 como caso base)
PLAN.md         planificación y reglas tributarias aplicadas
```

## Reglas de cálculo aplicadas

- IVA tarifa general 15 % (campo 421 = campo 411 × 15 %).
- Compras gravadas ≠0 % **con** derecho a crédito → 500/510/520; **sin** derecho → 502/512/522.
- Compras tarifa 0 % → 507/517; notas de venta (negocios populares) → 508/518.
- Las notas de crédito restan del valor **neto** (no del bruto).
- Factor de proporcionalidad (563) = 1.0000 (ventas 100 % gravadas) → 564 = 520.
- Duplicados por clave de acceso se ignoran con aviso; si base + IVA ≠ total
  (posible ICE), se genera una advertencia.
