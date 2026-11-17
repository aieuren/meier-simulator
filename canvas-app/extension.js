/**
 * Meier – startpanel (Canvas-app, host API 1)
 *
 * En sida i Agent Canvas som startar, stoppar och övervakar Meier-webbappen.
 * Den anropar agent-serverns bash-endpoint via host.agentServer.request, så
 * ingen hemlighet finns i appkoden och ingen egen server behövs.
 */

const PROJECT_DIR = "/workspace/project";
const PORT = 12000;

// Klammertricket hindrar pkill från att matcha sin egen kommandorad.
const CMD_STOP = `pkill -f '[u]vicorn meier.web.app' || true`;
// Starta = stoppa, vänta tills porten är ledig, starta sedan. Utan väntan kan
// en döende process svara på run.sh:s health-koll, som då tror att servern kör
// och hoppar över starten – resultatet blir att inget körs.
const CMD_START =
  `cd ${PROJECT_DIR} && ` +
  `{ pkill -f '[u]vicorn meier.web.app' || true; ` +
  `for i in $(seq 1 40); do ` +
  `curl -sf -m 1 http://127.0.0.1:${PORT}/api/health >/dev/null 2>&1 || break; ` +
  `sleep 0.25; ` +
  `done; } ; ` +
  `./run.sh --background`;
// Skriver ut RUNTIME_URL först, sedan antingen health-JSON eller MEIER_DOWN.
const CMD_STATUS = `echo "URL=$RUNTIME_URL"; curl -sf -m 3 http://127.0.0.1:${PORT}/api/health || echo MEIER_DOWN`;

const STYLE_ID = "meier-startpanel-style";
const CSS = `
.meier-root {
  --meier-bg: var(--oh-color-surface, #1b1b1f);
  --meier-fg: var(--oh-color-text, #e8e8ea);
  --meier-muted: var(--oh-color-text-secondary, #9a9aa2);
  --meier-border: var(--oh-color-border, #34343a);
  --meier-accent: var(--oh-color-primary, #6d5efc);
  --meier-ok: #2fbf71;
  --meier-off: #e5484d;
  --meier-warn: #f5a524;
  box-sizing: border-box;
  color: var(--meier-fg);
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 720px;
  padding: 4px 2px 32px;
}
.meier-root *, .meier-root *::before, .meier-root *::after { box-sizing: border-box; }
.meier-root h2 { font-size: 1.25rem; margin: 0; }
.meier-root p { margin: 0; line-height: 1.5; }
.meier-muted { color: var(--meier-muted); font-size: 0.9rem; }

.meier-status {
  align-items: center;
  background: color-mix(in srgb, var(--meier-fg) 5%, transparent);
  border: 1px solid var(--meier-border);
  border-radius: 12px;
  display: flex;
  gap: 14px;
  padding: 16px 18px;
}
.meier-dot {
  border-radius: 50%;
  flex: 0 0 auto;
  height: 12px;
  width: 12px;
  background: var(--meier-muted);
}
.meier-dot[data-state="up"] { background: var(--meier-ok); box-shadow: 0 0 0 4px color-mix(in srgb, var(--meier-ok) 22%, transparent); }
.meier-dot[data-state="down"] { background: var(--meier-off); box-shadow: 0 0 0 4px color-mix(in srgb, var(--meier-off) 22%, transparent); }
.meier-dot[data-state="busy"] { background: var(--meier-warn); animation: meier-pulse 1s ease-in-out infinite; }
@keyframes meier-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .meier-dot[data-state="busy"] { animation: none; } }

.meier-status-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.meier-status-title { font-weight: 600; }

.meier-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.meier-btn {
  background: var(--meier-accent);
  border: 1px solid transparent;
  border-radius: 10px;
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  padding: 10px 18px;
  transition: filter 0.15s ease;
}
.meier-btn:hover:not(:disabled) { filter: brightness(1.1); }
.meier-btn:focus-visible { outline: 2px solid var(--meier-accent); outline-offset: 2px; }
.meier-btn:disabled { cursor: not-allowed; opacity: 0.5; }
.meier-btn[data-variant="secondary"] {
  background: transparent;
  border-color: var(--meier-border);
  color: var(--meier-fg);
}
.meier-btn[data-variant="danger"] { background: var(--meier-off); }

.meier-url {
  background: color-mix(in srgb, var(--meier-fg) 5%, transparent);
  border: 1px solid var(--meier-border);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px 16px;
}
.meier-url a { color: var(--meier-accent); font-weight: 600; word-break: break-all; }

.meier-log {
  background: #101014;
  border: 1px solid var(--meier-border);
  border-radius: 10px;
  color: #cfd0d6;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  line-height: 1.45;
  margin: 0;
  max-height: 220px;
  overflow: auto;
  padding: 12px 14px;
  white-space: pre-wrap;
  word-break: break-word;
}
.meier-note {
  border-left: 3px solid var(--meier-warn);
  color: var(--meier-muted);
  font-size: 0.85rem;
  padding: 4px 0 4px 12px;
}
.meier-error {
  background: color-mix(in srgb, var(--meier-off) 14%, transparent);
  border: 1px solid var(--meier-off);
  border-radius: 10px;
  padding: 12px 14px;
}
`;

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.append(style);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function activate(host) {
  if (!host || host.apiVersion !== "1") {
    throw new Error("Den här appen kräver Canvas host API 1.");
  }

  ensureStyle();

  const registered = host.registerPage("meier-start", ({ container }) => {
    const root = el("div", "meier-root");
    container.append(root);

    const heading = el("h2", null, "Meier – startpanel");
    const intro = el(
      "p",
      "meier-muted",
      "Startar och stoppar Meier-webbappen i den här sessionen. Panelen kör kommandon via agent-servern, så du slipper en egen terminal.",
    );

    const status = el("div", "meier-status");
    const dot = el("span", "meier-dot");
    dot.dataset.state = "busy";
    const statusText = el("div", "meier-status-text");
    const statusTitle = el("span", "meier-status-title", "Kontrollerar …");
    const statusDetail = el("span", "meier-muted", "");
    statusText.append(statusTitle, statusDetail);
    status.append(dot, statusText);

    const actions = el("div", "meier-actions");
    const startBtn = el("button", "meier-btn", "Starta");
    startBtn.type = "button";
    const stopBtn = el("button", "meier-btn", "Stoppa");
    stopBtn.type = "button";
    stopBtn.dataset.variant = "danger";
    const refreshBtn = el("button", "meier-btn", "Uppdatera status");
    refreshBtn.type = "button";
    refreshBtn.dataset.variant = "secondary";
    actions.append(startBtn, stopBtn, refreshBtn);

    const urlBox = el("div", "meier-url");
    const urlLabel = el("span", "meier-muted", "Webbadress");
    const urlLink = el("a");
    urlLink.target = "_blank";
    urlLink.rel = "noopener noreferrer";
    urlBox.append(urlLabel, urlLink);

    const errorBox = el("div", "meier-error");
    errorBox.hidden = true;

    const logHeading = el("span", "meier-muted", "Senaste utdata");
    const logView = el("pre", "meier-log", "Ingen utdata än.");
    const note = el(
      "p",
      "meier-note",
      "Miljön som vilar i 20 minuter stängs av. Öppna den här panelen och tryck Starta igen när du kommer tillbaka.",
    );

    root.append(heading, intro, status, actions, urlBox, errorBox, logHeading, logView, note);

    let disposed = false;
    let busy = false;

    function setUrl(url) {
      if (!url) {
        urlLink.remove();
        return;
      }
      urlLink.href = url;
      urlLink.textContent = url;
    }

    function showError(message) {
      errorBox.hidden = false;
      errorBox.textContent = message;
    }

    function clearError() {
      errorBox.hidden = true;
      errorBox.textContent = "";
    }

    function appendLog(text) {
      if (!text) return;
      logView.textContent = text.trim() || "(tom utdata)";
      logView.scrollTop = 0;
    }

    async function runBash(command) {
      return host.agentServer.request({
        method: "POST",
        path: "/api/bash/execute_bash_command",
        body: { command },
      });
    }

    function renderStatus(up, detail) {
      dot.dataset.state = up ? "up" : "down";
      statusTitle.textContent = up ? "Webbappen körs" : "Webbappen är stoppad";
      statusDetail.textContent = detail || "";
    }

    // Plockar ut "URL=..." ur statuskommandots utdata och returnerar resten.
    function splitStatusOutput(output) {
      const lines = String(output || "").split("\n");
      let url = "";
      const rest = [];
      for (const line of lines) {
        if (line.startsWith("URL=")) {
          url = line.slice(4).trim();
        } else {
          rest.push(line);
        }
      }
      return { url, body: rest.join("\n").trim() };
    }

    async function checkStatus() {
      if (disposed) return;
      dot.dataset.state = "busy";
      statusTitle.textContent = "Kontrollerar …";
      statusDetail.textContent = "";
      try {
        const res = await runBash(CMD_STATUS);
        if (disposed) return;
        const { url, body } = splitStatusOutput(res && res.stdout);
        if (url) setUrl(url);
        const up = !body.includes("MEIER_DOWN");
        renderStatus(up, up ? body : "Inget svar på port " + PORT + ".");
      } catch (err) {
        if (disposed) return;
        dot.dataset.state = "down";
        statusTitle.textContent = "Kunde inte nå agent-servern";
        statusDetail.textContent = String((err && err.message) || err);
      }
    }

    function setBusy(next) {
      busy = next;
      startBtn.disabled = next;
      stopBtn.disabled = next;
      refreshBtn.disabled = next;
    }

    async function perform(action) {
      if (busy || disposed) return;
      clearError();
      setBusy(true);
      dot.dataset.state = "busy";
      statusTitle.textContent = action === "start" ? "Startar …" : "Stoppar …";
      statusDetail.textContent = "";
      try {
        const res = await runBash(action === "start" ? CMD_START : CMD_STOP);
        if (disposed) return;
        const output = [res && res.stdout, res && res.stderr].filter(Boolean).join("\n");
        appendLog(output);
        if (res && res.exit_code !== 0) {
          showError(
            "Kommandot avslutades med felkod " +
              res.exit_code +
              ". Se utdata ovan.",
          );
        }
      } catch (err) {
        if (disposed) return;
        showError("Anropet misslyckades: " + String((err && err.message) || err));
      } finally {
        if (!disposed) {
          setBusy(false);
          await checkStatus();
        }
      }
    }

    startBtn.addEventListener("click", () => perform("start"));
    stopBtn.addEventListener("click", () => perform("stop"));
    refreshBtn.addEventListener("click", () => checkStatus());

    checkStatus();

    return () => {
      disposed = true;
      root.remove();
    };
  });

  return () => {
    registered();
    const style = document.getElementById(STYLE_ID);
    if (style) style.remove();
  };
}
