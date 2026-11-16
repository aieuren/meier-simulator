#!/usr/bin/env bash
#
# Installerar (eller ominstallerar) Meier-startpanelen i Agent Canvas.
#
# Panelen installeras i agent-serverns hemkatalog, som ligger på en tillfällig
# volym och nollställs när miljön startas om. Kör därför det här skriptet efter
# en omstart om panelen saknas i Canvas-menyn.
#
# Användning:
#   ./canvas-app/install.sh            # installera och aktivera
#   ./canvas-app/install.sh --disable  # stäng av panelen
#
set -eu

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
NAME="meier-startpanel"
BASE="${AGENT_SERVER_URL:-http://127.0.0.1:60000}"

key=""
for path in /proc/1/environ /proc/self/environ; do
  [ -r "$path" ] || continue
  key=$(tr '\0' '\n' < "$path" | sed -n 's/^SESSION_API_KEY=//p' | head -1)
  [ -n "$key" ] && break
done
if [ -z "$key" ]; then
  echo "Fel: hittade ingen SESSION_API_KEY." >&2
  exit 1
fi

mode="enable"
[ "${1:-}" = "--disable" ] && mode="disable"

echo "Installerar $NAME från $APP_DIR ..."
curl -sf -m 30 -X POST "$BASE/api/canvas-extensions/install" \
  -H "X-Session-API-Key: $key" -H "Content-Type: application/json" \
  -d "$(python3 -c "import json,sys;print(json.dumps({'source':sys.argv[1],'force':True}))" "$APP_DIR")" \
  >/dev/null

enabled=true
[ "$mode" = "disable" ] && enabled=false

echo "Sätter enabled=$enabled ..."
curl -sf -m 30 -X PATCH "$BASE/api/canvas-extensions/installed/$NAME" \
  -H "X-Session-API-Key: $key" -H "Content-Type: application/json" \
  -d "{\"enabled\": $enabled}" >/dev/null

echo "Klart. Öppna \"Meier\" i Canvas-menyn."
