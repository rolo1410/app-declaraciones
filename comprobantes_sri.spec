# -*- mode: python ; coding: utf-8 -*-
"""
Spec de PyInstaller para la app unificada de comprobantes SRI (multiplataforma):
Descarga (Playwright) + Análisis (XML) + Declaración de IVA.

Empaqueta el driver de Playwright (node + package) pero NO los navegadores: la
app usa el Google Chrome instalado en el sistema (channel="chrome"), necesario
además para superar el reCAPTCHA.

Genera:
  • macOS   -> ComprobantesSRI.app  (+ carpeta onedir)
  • Linux   -> carpeta onedir con el binario ComprobantesSRI
  • Windows -> carpeta onedir con ComprobantesSRI.exe
"""
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Recolecta datos/binarios/imports del paquete playwright (incluye el driver).
pw_datas, pw_binaries, pw_hiddenimports = collect_all("playwright")

# Todos los submódulos del paquete de la app (core, gui, export).
app_hiddenimports = collect_submodules("app")

# keyring elige su backend en tiempo de ejecución (entry points): hay que
# incluirlos todos explícitamente o el ejecutable cae en fail.Keyring.
keyring_hiddenimports = collect_submodules("keyring.backends") + ["argon2", "_cffi_backend"]
if sys.platform == "win32":
    keyring_hiddenimports += ["win32ctypes.core"]
elif sys.platform.startswith("linux"):
    keyring_hiddenimports += ["secretstorage", "jeepney"]

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=pw_binaries,
    datas=pw_datas + [("assets", "assets")],  # íconos y marca de agua
    hiddenimports=pw_hiddenimports + app_hiddenimports + keyring_hiddenimports
    + ["openpyxl", "reportlab"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Ícono del ejecutable: .ico en Windows, .icns en macOS (Linux lo ignora).
if sys.platform == "win32":
    _icono_exe = "assets/icon.ico"
elif sys.platform == "darwin":
    _icono_exe = "assets/icon.icns"
else:
    _icono_exe = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ComprobantesSRI",
    icon=_icono_exe,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # app de ventana (sin consola)
    disable_windowed_traceback=False,
    # argv_emulation solo aplica en macOS; en Linux/Windows PyInstaller avisa.
    argv_emulation=(sys.platform == "darwin"),
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ComprobantesSRI",
)

# El bundle .app solo aplica en macOS; en Linux/Windows se usa la carpeta onedir.
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="ComprobantesSRI.app",
        icon="assets/icon.icns",
        bundle_identifier="ec.decisiondata.comprobantessri",
    )
