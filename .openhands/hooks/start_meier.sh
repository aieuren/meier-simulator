#!/usr/bin/env bash
#
# SessionStart-krok: ser till att Meier-webbappen kör.
#
# Sandlådan stängs av efter 20 minuters inaktivitet (OH_RUNTIME_IDLE_TIMEOUT_SECONDS).
# Vid nästa besök startar containern om, men webbappen gör det inte. Den här
# kroken körs när en ny session börjar och startar då appen igen.
#
# Körs av agent-servern vid SessionStart. Får JSON på stdin och ska alltid
# avsluta med 0 – ett fel här ska aldrig blockera sessionen.

set -u

PROJECT_DIR="${OPENHANDS_PROJECT_DIR:-/workspace/project}"
LOG_DIR="/workspace/meier-logs"
LOG="$LOG_DIR/start-hook.log"

mkdir -p "$LOG_DIR" 2>/dev/null || true

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG" 2>/dev/null || true; }

# Panelregistret ligger i agent-serverns hemkatalog (~/.openhands), som nollställs
# vid omstart. Installera om panelen så Canvas-menyn får tillbaka sitt val.
if [ -x "$PROJECT_DIR/canvas-app/install.sh" ]; then
  if "$PROJECT_DIR/canvas-app/install.sh" >>"$LOG" 2>&1; then
    log "Panelen återinstallerad"
  else
    log "Panelinstallation misslyckades"
  fi
fi

log "SessionStart: kontrollerar Meier"

# Redan igång? Gör inget.
if curl -sf -m 3 http://127.0.0.1:12000/api/health >/dev/null 2>&1; then
  log "Redan igång – inget att göra"
  exit 0
fi

# Katalogen kan saknas om kroken körs innan repot klonats.
if [ ! -x "$PROJECT_DIR/run.sh" ]; then
  log "Hittar inte $PROJECT_DIR/run.sh – hoppar över"
  exit 0
fi

# --background löser både nyckeln och beroenden, precis som för en människa.
cd "$PROJECT_DIR" || exit 0
if MEIER_LOG="$LOG_DIR/meier_web.log" ./run.sh --background >>"$LOG" 2>&1; then
  log "Startad"
else
  log "Start misslyckades – se $LOG_DIR/meier_web.log"
fi

exit 0
