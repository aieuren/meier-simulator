#!/usr/bin/env bash
# Kör panelens exakta kommandon mot agent-serverns bash-endpoint.
# Används för att verifiera startpanelens flöde utan webbläsare.
set -u

KEY=$(tr '\0' '\n' < /proc/1/environ | sed -n 's/^SESSION_API_KEY=//p')
API=http://127.0.0.1:60000/api/bash/execute_bash_command

run() {
  python3 - "$1" <<'PY' | curl -s -m 60 -X POST -H "X-Session-API-Key: $KEY" \
      -H "Content-Type: application/json" --data-binary @- "$API"
import json, sys
print(json.dumps({"command": sys.argv[1]}))
PY
}

show() {
  python3 -c "
import json, sys
d = json.load(sys.stdin)
print('  exit:', d.get('exit_code'))
out = (d.get('stdout') or '').strip()
if out: print('  stdout:', out.replace(chr(10), ' | '))
err = (d.get('stderr') or '').strip()
if err: print('  stderr:', err.replace(chr(10), ' | '))
"
}

CMD_STOP="pkill -f '[u]vicorn meier.web.app' || true"
CMD_STATUS='echo "URL=$RUNTIME_URL"; curl -sf -m 3 http://127.0.0.1:12000/api/health || echo MEIER_DOWN'
CMD_START='cd /workspace/project && ./run.sh --background'

echo "1. STOPP (panelens kommando)"; run "$CMD_STOP" | show
sleep 1
echo "2. STATUS efter stopp (ska visa MEIER_DOWN)"; run "$CMD_STATUS" | show
echo "3. START (panelens kommando)"; run "$CMD_START" | show
sleep 2
echo "4. STATUS efter start (ska visa health-JSON)"; run "$CMD_STATUS" | show
