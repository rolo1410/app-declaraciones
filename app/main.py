"""Punto de entrada: sin argumentos abre la interfaz gráfica; con argumentos funciona como CLI.

Ejemplos:
    python -m app.main                                        # interfaz gráfica
    python -m app.main archivo_Recibidos.txt --periodo 2026-06 --ventas 5586.96
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal

from .core import calculadora, clasificador, parser


def _formatear(valor: object) -> str:
    if isinstance(valor, Decimal):
        return f"{valor:,.2f}"
    return str(valor)


def ejecutar_cli(argumentos: list[str]) -> int:
    analizador = argparse.ArgumentParser(
        description="Pre-cálculo de la declaración de IVA (SRI Ecuador) desde el archivo de Recibidos."
    )
    analizador.add_argument("archivo", help="Archivo TXT de comprobantes recibidos del SRI")
    analizador.add_argument("--periodo", help="Período AAAA-MM (por defecto, el más reciente del archivo)")
    analizador.add_argument("--ventas", type=Decimal, default=Decimal("0"),
                            help="Ventas brutas del período (campo 401, prellenado del SRI)")
    analizador.add_argument("--notas-credito", type=Decimal, default=Decimal("0"),
                            help="Notas de crédito emitidas en el período")
    analizador.add_argument("--emitidos", type=int, default=0, help="Comprobantes emitidos (campo 111)")
    analizador.add_argument("--anulados", type=int, default=0, help="Comprobantes anulados (campo 113)")
    analizador.add_argument("--todas-con-credito", action="store_true",
                            help="Marcar todas las compras con derecho a crédito "
                                 "(por defecto solo las facturadas al RUC)")
    args = analizador.parse_args(argumentos)

    resultado = parser.leer_archivo(args.archivo)
    if not resultado.comprobantes:
        print("El archivo no contiene comprobantes.", file=sys.stderr)
        return 1

    ruc = parser.ruc_desde_nombre_archivo(args.archivo)
    if args.todas_con_credito:
        clasificador.marcar_todas_con_credito(resultado.comprobantes)
    else:
        clasificador.sugerir_clasificacion(resultado.comprobantes, ruc)

    periodo = args.periodo or resultado.periodos[-1]
    declaracion = calculadora.calcular_declaracion(
        resultado.comprobantes,
        periodo,
        ventas_brutas=args.ventas,
        notas_credito_emitidas=args.notas_credito,
        comprobantes_emitidos=args.emitidos,
        comprobantes_anulados=args.anulados,
        advertencias=resultado.advertencias,
    )

    print(f"\nDECLARACIÓN DE IVA — período {periodo}"
          f" — {len(declaracion.comprobantes)} comprobantes recibidos\n")
    print(f"{'Casillero':>9}  {'Descripción':<62} {'Valor':>14}")
    print("-" * 89)
    for campo, descripcion, valor in calculadora.filas_formulario(declaracion):
        texto = f"{valor:.4f}" if campo == "563" else _formatear(valor)
        print(f"{campo:>9}  {descripcion:<62} {texto:>14}")

    resumen = declaracion.resumen
    print("\nRESUMEN IMPOSITIVO")
    print(f"  Impuesto generado en ventas (499): {resumen.impuesto_generado:>12,.2f}")
    print(f"  Crédito tributario compras (564):  {resumen.credito_tributario:>12,.2f}")
    if resumen.impuesto_a_pagar > 0:
        print(f"  IMPUESTO A PAGAR:                  {resumen.impuesto_a_pagar:>12,.2f}")
    else:
        print(f"  CRÉDITO A FAVOR (próximo mes):     {resumen.credito_a_favor:>12,.2f}")

    if declaracion.advertencias:
        print("\nADVERTENCIAS:")
        for advertencia in declaracion.advertencias:
            print(f"  - {advertencia}")

    print("\nNota: valores de apoyo; verifíquelos contra el prellenado de SRI en línea.")
    return 0


def _selftest() -> int:
    """Verifica que Playwright + Chrome funcionan (útil en el ejecutable empaquetado)."""
    import os
    import tempfile

    log_path = os.path.join(tempfile.gettempdir(), "sri_selftest.log")
    with open(log_path, "w", encoding="utf-8") as f:
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    channel="chrome",
                    headless=True,
                    ignore_default_args=["--enable-automation"],
                )
                page = browser.new_page()
                page.goto("about:blank")
                browser.close()
            f.write("OK: Playwright pudo lanzar Chrome.\n")
            return 0
        except Exception as e:  # noqa: BLE001
            f.write(f"FAIL: {e!r}\n")
            return 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    if len(sys.argv) > 1:
        return ejecutar_cli(sys.argv[1:])
    from .gui.main_window import ejecutar_gui
    ejecutar_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
