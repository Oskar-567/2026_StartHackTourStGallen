#!/usr/bin/env bash
# Starts the local backend on macOS: Postgres in Docker, migrations, then the
# Django dev server on 0.0.0.0:8000 so phones on the same network can reach it.
#
#   ./scripts/start-server.sh
#
# The worker is a separate process -- start it in a second terminal, see the
# hint printed below. Stop the server with Ctrl+C; Postgres keeps running
# (`docker compose down` in server/ stops it).
set -euo pipefail

SERVER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../server" && pwd)"
cd "$SERVER_DIR"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$1"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

# Reads one KEY=value from server/.env without sourcing the whole file.
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- || true; }

step "Checking prerequisites"
command -v docker >/dev/null || fail "Docker is not installed (Docker Desktop or OrbStack)."
command -v uv >/dev/null || fail "uv is not installed: brew install uv"
docker info >/dev/null 2>&1 || fail "Docker is not running. Start Docker Desktop (or OrbStack) and try again."
if [[ ! -f .env ]]; then
  cp .env.example .env
  warn "Created server/.env from .env.example -- fill in VISECA_API_KEY and VISECA_DATA_DIR."
fi

step "Starting Postgres (Docker, port 5433)"
docker compose up -d
for _ in $(seq 1 30); do
  if docker compose exec -T db pg_isready -U app >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker compose exec -T db pg_isready -U app >/dev/null 2>&1 || fail "Postgres did not become ready."
echo "Postgres is ready."

step "Installing Python dependencies"
uv sync

step "Applying migrations"
uv run python manage.py migrate

# Fact extraction via Ollama is optional; warn early instead of failing silently
# later with step-ups for every purchase.
if [[ "$(env_value FACTS_BACKEND)" == "local" ]]; then
  step "Checking Ollama"
  OLLAMA_HOST_VALUE="$(env_value OLLAMA_HOST)"
  OLLAMA_HOST_VALUE="${OLLAMA_HOST_VALUE:-http://127.0.0.1:11434}"
  OLLAMA_MODEL_VALUE="$(env_value OLLAMA_MODEL)"
  if ! TAGS="$(curl -fsS --max-time 3 "$OLLAMA_HOST_VALUE/api/tags")"; then
    warn "Ollama is not reachable at $OLLAMA_HOST_VALUE -- open the Ollama app. Purchases will be decided without facts."
  elif [[ -n "$OLLAMA_MODEL_VALUE" && "$TAGS" != *"\"$OLLAMA_MODEL_VALUE\""* ]]; then
    warn "Model $OLLAMA_MODEL_VALUE is not pulled. Run: ollama pull $OLLAMA_MODEL_VALUE"
  else
    echo "Ollama is up with $OLLAMA_MODEL_VALUE."
  fi
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "<your-mac-ip>")"

step "Starting Django on 0.0.0.0:8000"
cat <<EOF
  This Mac:       http://localhost:8000/health/
  Phone (Wi-Fi):  http://$LAN_IP:8000/health/
  API docs:       http://localhost:8000/api/docs/

  In a second terminal, to take part in a live run:
    cd "$SERVER_DIR"
    uv run python manage.py create_mandate --scenario SCEN0000
    uv run python manage.py run_worker --scenario SCEN0000 --mandate-id <id printed above>

  Or fill the approval queue without the live API:
    uv run python manage.py replay --scenario SCEN0002 --seed-queue

EOF
exec uv run python manage.py runserver 0.0.0.0:8000
