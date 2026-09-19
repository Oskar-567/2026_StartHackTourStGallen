#!/usr/bin/env bash
# Starts the Expo dev server on macOS, pointed at the Django server on this Mac.
#
#   ./scripts/start-app.sh            # server on this Mac (LAN IP detected)
#   ./scripts/start-app.sh 10.0.0.5   # server on another machine
#
# Writes EXPO_PUBLIC_API_URL into app/.env: the phone cannot use "localhost",
# and the IP changes with every network (venue Wi-Fi, phone hotspot), so it is
# re-detected on every start. Then press "w" for web or scan the QR code with
# Expo Go.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../app" && pwd)"
cd "$APP_DIR"

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
warn() { printf '\033[33mWARNING: %s\033[0m\n' "$1"; }
fail() { printf '\033[31mERROR: %s\033[0m\n' "$1" >&2; exit 1; }

command -v npm >/dev/null || fail "Node.js is not installed: brew install node"

SERVER_IP="${1:-$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)}"
[[ -n "$SERVER_IP" ]] || fail "Could not detect this Mac's IP. Pass it explicitly: $0 <server-ip>"
API_URL="http://$SERVER_IP:8000"

step "Pointing the app at $API_URL"
if [[ -f .env ]] && grep -q '^EXPO_PUBLIC_API_URL=' .env; then
  # BSD sed on macOS needs the empty suffix after -i.
  sed -i '' "s#^EXPO_PUBLIC_API_URL=.*#EXPO_PUBLIC_API_URL=$API_URL#" .env
else
  echo "EXPO_PUBLIC_API_URL=$API_URL" >> .env
fi

step "Checking the server"
if curl -fsS --max-time 3 "$API_URL/health/" >/dev/null; then
  echo "Server is reachable."
else
  warn "No answer from $API_URL/health/ -- start it with ./scripts/start-server.sh. The app will show connection errors until then."
fi

if [[ ! -d node_modules ]]; then
  step "Installing app dependencies"
  npm install
fi

step "Starting Expo (press w for web, or scan the QR code with Expo Go)"
# --clear: EXPO_PUBLIC_* values are inlined at bundle time, so a changed IP
# needs a fresh bundle.
exec npx expo start --clear
