#!/usr/bin/env bash
# Genera el ejecutable de escritorio (app unificada) con PyInstaller.
# Uso: ./build.sh
set -e

cd "$(dirname "$0")"

echo "==> Instalando dependencias..."
python3 -m pip install --quiet -r requirements.txt pyinstaller

echo "==> Limpiando builds previos..."
rm -rf build dist

echo "==> Compilando..."
python3 -m PyInstaller --noconfirm --clean comprobantes_sri.spec

echo ""
echo "==> Listo."
echo "    macOS  : dist/ComprobantesSRI.app"
echo "    binario: dist/ComprobantesSRI/ComprobantesSRI"
echo ""
echo "Requisito en la máquina destino: tener Google Chrome instalado (pestaña Descarga)."
