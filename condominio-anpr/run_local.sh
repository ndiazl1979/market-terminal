#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Arranque local (opción B, sin Docker) del Sistema Condominio ANPR.
#
#  Qué hace:
#    1. Crea el entorno virtual .venv si no existe.
#    2. Instala/actualiza las dependencias.
#    3. Crea .env desde .env.example la primera vez.
#    4. Levanta el servidor en http://localhost:8000
#
#  Uso:
#    ./run_local.sh              # puerto 8000
#    PORT=9000 ./run_local.sh    # otro puerto
# ─────────────────────────────────────────────────────────────
set -euo pipefail

# Situarse en la carpeta del script (funciona desde cualquier directorio).
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"

# Elegir python3 disponible.
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "✗ No se encontró Python 3. Instálalo primero." >&2
  exit 1
fi

# 1) Entorno virtual.
if [ ! -d .venv ]; then
  echo "▸ Creando entorno virtual (.venv)…"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 2) Dependencias (rápido si ya están instaladas).
echo "▸ Instalando dependencias…"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# 3) Configuración inicial.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "▸ Se creó .env desde el ejemplo. EDÍTALO para cambiar la contraseña admin."
fi

# 4) Arrancar.
echo "▸ Servidor en http://localhost:${PORT}  (Ctrl+C para detener)"
echo "  Usuario/clave: los de tu archivo .env (ADMIN_USER / ADMIN_PASSWORD)"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
