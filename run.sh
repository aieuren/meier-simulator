#!/usr/bin/env bash
#
# Startar Mejer-webbappen. Installerar beroenden om de saknas.
#
# Användning:
#   ./run.sh              # startar i förgrunden (Ctrl-C stoppar)
#   ./run.sh --background # startar i bakgrunden, loggar till MEJER_LOG
#   ./run.sh --check      # kontrollerar bara att allt är på plats
#
# Miljövariabler:
#   PORT        port att lyssna på (standard 12000)
#   HOST        adress att binda (standard 0.0.0.0)
#   PYTHON      python-binär (standard python3)
#   MEJER_LOG   loggfil i bakgrundsläget (standard /tmp/mejer_web.log)

cd "$(dirname "$0")" || exit 1

PORT="${PORT:-12000}"
HOST="${HOST:-0.0.0.0}"
PYTHON="${PYTHON:-python3}"
MEJER_LOG="${MEJER_LOG:-/tmp/mejer_web.log}"

# Efter en omstart av containern hamnar pip-installerade skript i ~/.local/bin,
# som inte alltid ligger på PATH.
export PATH="$HOME/.local/bin:$PATH"

MODE="foreground"
case "${1:-}" in
  --background|-b) MODE="background" ;;
  --check|-c)      MODE="check" ;;
  --help|-h)
    sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
    ;;
  "") ;;
  *)
    echo "Okänt argument: $1 (använd --background, --check eller --help)" >&2
    exit 2
    ;;
esac

# -- Beroenden ---------------------------------------------------------------
# Efter en containeromstart försvinner globalt installerade paket. Kontrollera
# att de går att importera och installera om något saknas.
missing="$("$PYTHON" - <<'PY'
import importlib.util
need = ("fastapi", "uvicorn", "httpx", "pydantic")
print(" ".join(m for m in need if importlib.util.find_spec(m) is None))
PY
)" || {
  echo "Fel: kunde inte köra $PYTHON. Är Python installerat?" >&2
  exit 1
}

if [ -n "$missing" ]; then
  echo "Saknade paket: $missing"
  echo "Installerar från requirements.txt ..."
  if ! "$PYTHON" -m pip install --disable-pip-version-check -r requirements.txt; then
    echo "Fel: installationen misslyckades. Kör manuellt:" >&2
    echo "  $PYTHON -m pip install -r requirements.txt" >&2
    exit 1
  fi
else
  echo "Beroenden är på plats."
fi

# -- Redan igång? ------------------------------------------------------------
if command -v curl >/dev/null 2>&1 && curl -sf -m 3 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
  echo "Servern svarar redan på port ${PORT}."
  [ "$MODE" = "check" ] && exit 0
  echo "Stoppa den först (t.ex. pkill -f 'uvicorn mejer.web.app') om du vill starta om."
  exit 0
fi

if [ "$MODE" = "check" ]; then
  echo "Redo att starta på port ${PORT}."
  exit 0
fi

# -- Starta ------------------------------------------------------------------
START_CMD=("$PYTHON" -m uvicorn mejer.web.app:app --host "$HOST" --port "$PORT")

if [ "$MODE" = "background" ]; then
  nohup "${START_CMD[@]}" >"$MEJER_LOG" 2>&1 &
  pid=$!
  echo "Startar i bakgrunden (pid $pid), logg: $MEJER_LOG"
  # Vänta tills servern svarar, upp till ~15 sekunder.
  for _ in $(seq 1 30); do
    if curl -sf -m 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      echo "Servern körs: http://127.0.0.1:${PORT}/"
      curl -s -m 3 "http://127.0.0.1:${PORT}/api/health"
      echo
      exit 0
    fi
    sleep 0.5
  done
  echo "Servern svarade inte inom tidsgränsen. Se loggen: $MEJER_LOG" >&2
  exit 1
else
  echo "Startar på http://${HOST}:${PORT}/ (Ctrl-C stoppar)"
  exec "${START_CMD[@]}"
fi
