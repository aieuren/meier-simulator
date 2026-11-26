#!/usr/bin/env bash
#
# Startar Meier-webbappen. Installerar beroenden om de saknas.
#
# Användning:
#   ./run.sh              # startar i förgrunden (Ctrl-C stoppar)
#   ./run.sh --background # startar i bakgrunden, loggar till MEIER_LOG
#   ./run.sh --check      # kontrollerar bara att allt är på plats
#
# Miljövariabler:
#   PORT        port att lyssna på (standard 12000)
#   HOST        adress att binda (standard 0.0.0.0)
#   PYTHON      python-binär (standard python3)
#   MEIER_LOG   loggfil i bakgrundsläget (standard /tmp/meier_web.log)
#   MEIER_TIMEOUT/MEIER_RETRIES  timeout (s) och antal försök per LLM-anrop
#   MEIER_MAX_RPM  tak för LLM-anrop per minut (0 = av)

cd "$(dirname "$0")" || exit 1

PORT="${PORT:-12000}"
HOST="${HOST:-0.0.0.0}"
PYTHON="${PYTHON:-python3}"
MEIER_LOG="${MEIER_LOG:-/tmp/meier_web.log}"

# Efter en omstart av containern hamnar pip-installerade skript i ~/.local/bin,
# som inte alltid ligger på PATH.
export PATH="$HOME/.local/bin:$PATH"

# Plocka upp LLM-nyckeln från en beständig fil om den inte redan är satt.
# /home nollställs vid omstart; /workspace ligger kvar. Se MEIER_SECRETS_DIR.
# Claude har företräde: finns anthropic.key används den, annars gemini.key.
MEIER_SECRETS_DIR="${MEIER_SECRETS_DIR:-/workspace/meier-secrets}"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -r "$MEIER_SECRETS_DIR/anthropic.key" ]; then
  ANTHROPIC_API_KEY="$(cat "$MEIER_SECRETS_DIR/anthropic.key")"
  export ANTHROPIC_API_KEY
fi
if [ -z "${GEMINI_API_KEY:-}" ] && [ -r "$MEIER_SECRETS_DIR/gemini.key" ]; then
  GEMINI_API_KEY="$(cat "$MEIER_SECRETS_DIR/gemini.key")"
  export GEMINI_API_KEY
fi

# Gemini-endpointen hänger ibland i minuter och har ett kvottak på fri nivå
# (15 anrop/minut). En match gör ~100-200 anrop, så ett anrop måste kunna göras
# om utan att blockera hela matchen. Kort timeout + fler försök med kvotvila.
export MEIER_TIMEOUT="${MEIER_TIMEOUT:-30}"
export MEIER_RETRIES="${MEIER_RETRIES:-6}"
# En modell kan svara "överbelastad" med jämna mellanrum. Reservlistan gör att
# ett beslut byter modell i stället för att tyst falla tillbaka på baspolicyn,
# som saknar språkmodell. Namnen måste höra till samma leverantör som nyckeln.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  export MEIER_FALLBACK_MODELS="${MEIER_FALLBACK_MODELS:-claude-haiku-4-5-20251001}"
else
  export MEIER_FALLBACK_MODELS="${MEIER_FALLBACK_MODELS:-gemini-flash-lite-latest,gemini-3.5-flash-lite}"
fi
# Håll anropen under kvottaket (anrop/minut). Standard 15 för Gemini; sätt 0
# för att stänga av. Marginalen (1.15) gör att vi ligger strax under taket.
# Claude har ett högre tak, så standarden höjs när anthropic.key används.
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  export MEIER_MAX_RPM="${MEIER_MAX_RPM:-50}"
else
  export MEIER_MAX_RPM="${MEIER_MAX_RPM:-15}"
fi

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
  echo "Stoppa den först (t.ex. pkill -f 'uvicorn meier.web.app') om du vill starta om."
  exit 0
fi

if [ "$MODE" = "check" ]; then
  echo "Redo att starta på port ${PORT}."
  exit 0
fi

# -- Starta ------------------------------------------------------------------
START_CMD=("$PYTHON" -m uvicorn meier.web.app:app --host "$HOST" --port "$PORT")

if [ "$MODE" = "background" ]; then
  nohup "${START_CMD[@]}" >"$MEIER_LOG" 2>&1 &
  pid=$!
  echo "Startar i bakgrunden (pid $pid), logg: $MEIER_LOG"
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
  echo "Servern svarade inte inom tidsgränsen. Se loggen: $MEIER_LOG" >&2
  exit 1
else
  echo "Startar på http://${HOST}:${PORT}/ (Ctrl-C stoppar)"
  exec "${START_CMD[@]}"
fi
