# Meier – startpanel (Canvas-app)

En sida i Agent Canvas som startar, stoppar och övervakar Meier-webbappen.

## Varför

Miljön stängs av efter 20 minuters vila. När du kommer tillbaka är
webbappen nere och behöver startas igen. Panelen ger dig en knapp i
Canvas i stället för en egen terminal.

Panelen anropar agent-serverns bash-endpoint via `host.agentServer.request`.
Agent Canvas sköter autentiseringen, så **ingen hemlighet finns i appkoden**
och ingen egen server behövs.

## Filer

| Fil | Roll |
|---|---|
| `canvas-extension.json` | Manifest (schema 1, host API 1) |
| `extension.js` | Panelens kod, en självständig ESM-fil |
| `extension.test.mjs` | Tester med DOM och en host-attrapp |
| `install.sh` | Installerar/ominstallerar panelen |
| `verify-panel.sh` | Kör panelens kommandon mot agent-servern |

## Installera

```sh
./canvas-app/install.sh
```

Installationen lämnar panelen **avstängd**. `install.sh` aktiverar den
också, eftersom det är ett medvetet val att köra appens kod. Vill du bara
installera, hoppa över sista steget i skriptet.

Panelen installeras i agent-serverns hemkatalog, som ligger på en
tillfällig volym. Kör `install.sh` igen om panelen saknas efter en omstart.

## Testa

```sh
node --test canvas-app/extension.test.mjs   # kräver jsdom
bash canvas-app/verify-panel.sh             # kräver att appen finns
```

## Vad panelen gör

| Knapp | Kommando |
|---|---|
| Starta | `cd /workspace/project && ./run.sh --background` |
| Stoppa | `pkill -f '[u]vicorn meier.web.app'` |
| Uppdatera status | `curl -sf http://127.0.0.1:12000/api/health` |

Status-kommandot skriver också ut `RUNTIME_URL`, som panelen visar som
klickbar webblänk.
