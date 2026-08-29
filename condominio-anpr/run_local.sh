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
#    ./run_local.sh                              # puerto 8000
#    PORT=9000 ./run_local.sh                    # otro puerto
#    ADMIN_PASSWORD='TuClave!!!' ./run_local.sh  # fija la clave de admin
#
#  La primera vez crea .env con una SECRET_KEY aleatoria y la contraseña de
#  admin (de la variable ADMIN_PASSWORD, o preguntándola). El .env NUNCA se
#  sube al repo: la clave queda solo en esta máquina.
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

# 3) Configuración inicial (.env solo local; nunca se sube al repo).
if [ ! -f .env ]; then
  cp .env.example .env

  # SECRET_KEY aleatoria y única para esta instalación.
  NEW_SECRET="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(48))')"

  # Contraseña de admin: variable de entorno, o preguntar si es interactivo.
  NEW_PASS="${ADMIN_PASSWORD:-}"
  if [ -z "$NEW_PASS" ] && [ -t 0 ]; then
    printf "▸ Define la contraseña del usuario admin: " >&2
    read -rs NEW_PASS; echo >&2
  fi

  # Escribir valores en .env con Python (evita problemas de escape con !, $, etc.).
  NEW_SECRET="$NEW_SECRET" NEW_PASS="$NEW_PASS" "$PY" - <<'PYEOF'
import os, re, pathlib
p = pathlib.Path(".env"); t = p.read_text()
t = re.sub(r"^SECRET_KEY=.*$", "SECRET_KEY=" + os.environ["NEW_SECRET"], t, flags=re.M)
if os.environ.get("NEW_PASS"):
    t = re.sub(r"^ADMIN_PASSWORD=.*$", "ADMIN_PASSWORD=" + os.environ["NEW_PASS"], t, flags=re.M)
p.write_text(t)
PYEOF
  echo "▸ Se creó .env (SECRET_KEY aleatoria; contraseña de admin fijada). No se sube al repo."
fi

# 4) Arrancar.
echo "▸ Servidor en http://localhost:${PORT}  (Ctrl+C para detener)"
echo "  Usuario/clave: los de tu archivo .env (ADMIN_USER / ADMIN_PASSWORD)"
exec uvicorn app.main:app --host "$HOST" --port "$PORT"
