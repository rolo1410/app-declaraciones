"""Pestaña 1 — Descarga automatizada de comprobantes XML del SRI (Playwright)."""
from __future__ import annotations

import queue
import sys
import threading
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import preferencias
from ..core.sri_downloader import (
    MESES,
    periodo_anterior,
    TIPO_RECIBIDOS,
    TIPOS_COMPROBANTE,
    DownloadConfig,
    SRIDownloader,
    validar_config,
)

# Tipos marcados al abrir la app. Por defecto solo "Factura" (código "1");
# los demás quedan disponibles pero sin marcar.
TIPOS_MARCADOS_POR_DEFECTO = {"1"}


class PestanaDescarga(ttk.Frame):
    def __init__(self, master, on_descarga_completa=None) -> None:
        super().__init__(master, padding=12)
        self._log_queue: "queue.Queue[str]" = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._continue_event = threading.Event()
        self._on_descarga_completa = on_descarga_completa
        self._ultimo_dir: str | None = None
        self._build_ui()
        self.after(100, self._poll_log_queue)

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        # Valores por defecto guardados fuera del repo (ver app/core/preferencias.py).
        prefs = preferencias.cargar()

        # --- Credenciales ---
        frm_cred = ttk.LabelFrame(self, text="Credenciales SRI", padding=10)
        frm_cred.pack(fill="x", **pad)

        ttk.Label(frm_cred, text="RUC / C.I. / Pasaporte:").grid(row=0, column=0, sticky="w", pady=4)
        self.var_ruc = tk.StringVar(value=prefs.get("ruc", ""))
        ttk.Entry(frm_cred, textvariable=self.var_ruc, width=30).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(frm_cred, text="Clave:").grid(row=1, column=0, sticky="w", pady=4)
        self.var_clave = tk.StringVar(value=prefs.get("clave", ""))
        self.entry_clave = ttk.Entry(frm_cred, textvariable=self.var_clave, width=30, show="•")
        self.entry_clave.grid(row=1, column=1, sticky="w", padx=8)
        self.var_ver_clave = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_cred, text="Ver clave", variable=self.var_ver_clave,
            command=self._toggle_clave,
        ).grid(row=1, column=2, sticky="w")

        # --- Periodo ---
        frm_per = ttk.LabelFrame(self, text="Periodo a consultar", padding=10)
        frm_per.pack(fill="x", **pad)

        anio_actual = datetime.now().year
        # Por defecto, el mes anterior: es el periodo que se declara.
        anio_previo, mes_previo = periodo_anterior()
        ttk.Label(frm_per, text="Año:").grid(row=0, column=0, sticky="w", pady=4)
        self.var_anio = tk.StringVar(value=str(anio_previo))
        ttk.Combobox(
            frm_per, textvariable=self.var_anio, width=8, state="readonly",
            values=[str(a) for a in range(anio_actual, 1999, -1)],
        ).grid(row=0, column=1, sticky="w", padx=8)

        ttk.Label(frm_per, text="Mes:").grid(row=0, column=2, sticky="w", pady=4)
        self.var_mes = tk.StringVar(value=MESES[mes_previo - 1][0])
        ttk.Combobox(
            frm_per, textvariable=self.var_mes, width=16, state="readonly",
            values=[etiqueta for etiqueta, _ in MESES],
        ).grid(row=0, column=3, sticky="w", padx=8)

        ttk.Label(frm_per, text="Día:").grid(row=0, column=4, sticky="w", pady=4)
        self.var_dia = tk.StringVar(value="Todos")
        ttk.Combobox(
            frm_per, textvariable=self.var_dia, width=8, state="readonly",
            values=["Todos"] + [f"{d:02d}" for d in range(1, 32)],
        ).grid(row=0, column=5, sticky="w", padx=8)

        # --- Tipos de comprobante ---
        frm_tipo = ttk.LabelFrame(self, text="Tipos de comprobante a descargar", padding=10)
        frm_tipo.pack(fill="x", **pad)
        self.vars_tipos: dict[str, tk.BooleanVar] = {}
        for i, (codigo, nombre) in enumerate(TIPOS_COMPROBANTE):
            var = tk.BooleanVar(value=codigo in TIPOS_MARCADOS_POR_DEFECTO)
            self.vars_tipos[codigo] = var
            ttk.Checkbutton(frm_tipo, text=nombre, variable=var).grid(
                row=i // 2, column=i % 2, sticky="w", padx=6, pady=2
            )

        # --- Directorio ---
        frm_dir = ttk.LabelFrame(self, text="Directorio de descarga", padding=10)
        frm_dir.pack(fill="x", **pad)
        self.var_dir = tk.StringVar(value=prefs.get("download_dir", ""))
        ttk.Entry(frm_dir, textvariable=self.var_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(frm_dir, text="Seleccionar...", command=self._elegir_directorio).pack(side="left", padx=8)

        # --- Opciones ---
        frm_opt = ttk.Frame(self)
        frm_opt.pack(fill="x", **pad)
        self.var_headless = tk.BooleanVar(value=False)
        self.chk_headless = ttk.Checkbutton(
            frm_opt,
            text="Headless (no recomendado: el reCAPTCHA suele rechazar el modo sin ventana)",
            variable=self.var_headless,
        )
        self.chk_headless.pack(side="left")

        frm_opt2 = ttk.Frame(self)
        frm_opt2.pack(fill="x", **pad)
        self.var_semi_manual = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opt2,
            text="Modo semi-manual (recomendado si el captcha falla: inicias sesión "
            "y consultas a mano; la app solo descarga los XML)",
            variable=self.var_semi_manual,
            command=self._toggle_semi_manual,
        ).pack(side="left")

        frm_opt3 = ttk.Frame(self)
        frm_opt3.pack(fill="x", **pad)
        self.var_chromium = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opt3,
            text="Usar Chromium en vez de Chrome (pruébelo si Chrome se cierra "
            "solo a mitad de la descarga)",
            variable=self.var_chromium,
        ).pack(side="left")

        # --- Botones ---
        frm_btn = ttk.Frame(self)
        frm_btn.pack(fill="x", **pad)
        self.btn_iniciar = ttk.Button(frm_btn, text="Iniciar descarga", command=self._iniciar)
        self.btn_iniciar.pack(side="left")
        self.btn_continuar = ttk.Button(
            frm_btn, text="Continuar descarga", command=self._continuar, state="disabled"
        )
        self.btn_continuar.pack(side="left", padx=8)
        self.btn_detener = ttk.Button(frm_btn, text="Detener", command=self._detener, state="disabled")
        self.btn_detener.pack(side="left", padx=8)
        self.progress = ttk.Progressbar(frm_btn, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)

        # --- Log ---
        frm_log = ttk.LabelFrame(self, text="Progreso", padding=6)
        frm_log.pack(fill="both", expand=True, **pad)
        self.txt_log = tk.Text(frm_log, height=10, state="disabled", wrap="word")
        scroll = ttk.Scrollbar(frm_log, command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    # -- helpers --
    def _toggle_clave(self) -> None:
        self.entry_clave.configure(show="" if self.var_ver_clave.get() else "•")

    def _toggle_semi_manual(self) -> None:
        # En modo semi-manual el navegador SIEMPRE debe verse (el usuario lo usa).
        if self.var_semi_manual.get():
            self.var_headless.set(False)
            self.chk_headless.configure(state="disabled")
        else:
            self.chk_headless.configure(state="normal")

    def _elegir_directorio(self) -> None:
        carpeta = filedialog.askdirectory(title="Seleccione la carpeta de descarga")
        if carpeta:
            self.var_dir.set(carpeta)

    def _log(self, msg: str) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                self._log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _leer_config(self) -> DownloadConfig:
        mes_valor = next(v for etiqueta, v in MESES if etiqueta == self.var_mes.get())
        dia_txt = self.var_dia.get()
        dia = 0 if dia_txt == "Todos" else int(dia_txt)
        tipos = [c for c, var in self.vars_tipos.items() if var.get()]
        return DownloadConfig(
            ruc=self.var_ruc.get(),
            clave=self.var_clave.get(),
            anio=int(self.var_anio.get()),
            mes=int(mes_valor),
            dia=dia,
            download_dir=self.var_dir.get(),
            tipo=TIPO_RECIBIDOS,
            tipos_comprobante=tipos or None,
            headless=self.var_headless.get() and not self.var_semi_manual.get(),
            semi_manual=self.var_semi_manual.get(),
            usar_chromium=self.var_chromium.get(),
        )

    def _iniciar(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        cfg = self._leer_config()
        if cfg.semi_manual:
            # En semi-manual el usuario inicia sesión y consulta a mano: sólo
            # hace falta un directorio de descarga válido.
            errores = [
                e for e in validar_config(cfg)
                if "directorio" in e.lower() or "descarga" in e.lower()
            ]
        else:
            errores = validar_config(cfg)
            if not any(var.get() for var in self.vars_tipos.values()):
                errores.append("Seleccione al menos un tipo de comprobante.")
        if errores:
            messagebox.showerror("Datos inválidos", "\n".join(f"• {e}" for e in errores))
            return

        self._stop_event.clear()
        self._continue_event.clear()
        self._ultimo_dir = cfg.download_dir
        self.btn_iniciar.configure(state="disabled")
        self.btn_detener.configure(state="normal")
        if cfg.semi_manual:
            self.btn_continuar.configure(state="normal")
        self.progress.start(12)
        self._log("=" * 60)
        self._log("Iniciando proceso de descarga...")

        self._worker = threading.Thread(target=self._ejecutar, args=(cfg,), daemon=True)
        self._worker.start()

    def _ejecutar(self, cfg: DownloadConfig) -> None:
        def log_fn(msg: str) -> None:
            self._log_queue.put(msg)

        carpeta_final = None
        try:
            downloader = SRIDownloader(
                cfg,
                log_fn=log_fn,
                stop_event=self._stop_event,
                continue_event=self._continue_event,
            )
            resultado = downloader.run()
            log_fn(
                f"Resumen: {resultado.total_descargados} archivo(s), "
                f"{resultado.paginas_procesadas} página(s)."
            )
            # Solo avanzar a Análisis si de verdad se descargó algo (no tras un
            # fallo de login o una descarga sin resultados).
            if resultado.total_descargados > 0:
                carpeta_final = getattr(resultado, "carpeta_destino", "") or cfg.download_dir
        except ModuleNotFoundError as e:
            if e.name == "playwright":
                log_fn(
                    "✖ Playwright no está instalado en el intérprete que ejecuta la app "
                    f"({sys.executable})."
                )
                log_fn(
                    "  Ejecute la app con el entorno del proyecto: .venv/bin/python -m app.main"
                )
                log_fn(
                    "  Si el entorno es nuevo: pip install -r requirements.txt "
                    "&& python -m playwright install chromium"
                )
            else:
                log_fn(f"✖ Error inesperado: {e}")
        except Exception as e:  # noqa: BLE001
            log_fn(f"✖ Error inesperado: {e}")
        finally:
            self.after(0, lambda: self._finalizar(carpeta_final))

    def _finalizar(self, carpeta: str | None = None) -> None:
        self.progress.stop()
        self.btn_iniciar.configure(state="normal")
        self.btn_detener.configure(state="disabled")
        self.btn_continuar.configure(state="disabled")
        if carpeta and self._on_descarga_completa is not None:
            self._on_descarga_completa(carpeta)

    def _continuar(self) -> None:
        """Modo semi-manual: avisa al worker que la consulta ya está lista."""
        if not (self._worker and self._worker.is_alive()):
            return
        self._continue_event.set()
        self._log("→ Continuar: descargando los comprobantes de la consulta actual...")

    def _detener(self) -> None:
        self._stop_event.set()
        self._log("Solicitando detener el proceso...")
        self.btn_detener.configure(state="disabled")
        self.btn_continuar.configure(state="disabled")
