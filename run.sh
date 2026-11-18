#!/usr/bin/env bash
# Arranca la app con el entorno virtual del proyecto (el único que tiene
# Playwright) y con las variables de .env cargadas.
set -euo pipefail
cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

exec .venv/bin/python -m app.main "$@"
