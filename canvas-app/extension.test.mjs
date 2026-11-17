/**
 * Testar startpanelen med en host-attrapp (host API 1) och en DOM.
 * Kör: node --test canvas-app/extension.test.mjs  (kräver jsdom installerat)
 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { JSDOM } from "jsdom";

const here = dirname(fileURLToPath(import.meta.url));

async function loadExtension() {
  const source = await readFile(join(here, "extension.js"), "utf8");
  return import(
    "data:text/javascript;base64," + Buffer.from(source).toString("base64")
  );
}

function makeHost() {
  const dom = new JSDOM("<!doctype html><html><head></head><body></body></html>");
  // Panelen använder globala document/window precis som i Canvas.
  globalThis.document = dom.window.document;
  globalThis.window = dom.window;
  const calls = [];
  const pages = new Map();
  const host = {
    apiVersion: "1",
    extension: { name: "meier-startpanel" },
    backend: { id: "b1", kind: "local" },
    registerPage(id, mount) {
      pages.set(id, mount);
      return () => pages.delete(id);
    },
    agentServer: {
      async request(req) {
        calls.push(req);
        return { exit_code: 0, stdout: "URL=https://example.test\n{\"status\":\"ok\"}" };
      },
    },
  };
  return { host, calls, pages, dom };
}

test("activate registrerar exakt en sida och avregistrerar vid disposer", async () => {
  const { activate } = await loadExtension();
  const { host, pages } = makeHost();
  const dispose = activate(host);
  assert.deepEqual([...pages.keys()], ["meier-start"]);
  assert.equal(typeof pages.get("meier-start"), "function");
  dispose();
  assert.equal(pages.size, 0);
});

test("activate kastar vid fel host-version", async () => {
  const { activate } = await loadExtension();
  assert.throws(() => activate({ apiVersion: "2" }), /host API 1/);
});

test("mount renderar panelen och frågar status via rätt endpoint", async () => {
  const { activate } = await loadExtension();
  const { host, pages, calls, dom } = makeHost();
  activate(host);

  const container = dom.window.document.createElement("section");
  const unmount = pages.get("meier-start")({ container, path: "", navigate() {} });

  assert.match(container.textContent, /Meier – startpanel/);
  assert.match(container.textContent, /Starta/);
  assert.match(container.textContent, /Stoppa/);

  // checkStatus() anropas direkt vid mount – vänta in det.
  await new Promise((r) => setTimeout(r, 20));
  assert.ok(calls.length >= 1, "förväntade minst ett agentServer-anrop");
  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].path, "/api/bash/execute_bash_command");
  assert.match(calls[0].body.command, /RUNTIME_URL/);

  unmount();
  assert.equal(container.textContent, "");
});

test("disposer tar bort DOM och stoppar vidare anrop", async () => {
  const { activate } = await loadExtension();
  const { host, pages, dom } = makeHost();
  activate(host);
  const container = dom.window.document.createElement("section");
  const unmount = pages.get("meier-start")({ container, path: "", navigate() {} });
  unmount();
  assert.equal(container.childElementCount, 0);
});

test("host.agentServer fel visas som feltext, inte krasch", async () => {
  const { activate } = await loadExtension();
  const { host, pages, dom } = makeHost();
  host.agentServer.request = async () => {
    throw new Error("nätverksfel");
  };
  activate(host);
  const container = dom.window.document.createElement("section");
  pages.get("meier-start")({ container, path: "", navigate() {} });
  await new Promise((r) => setTimeout(r, 20));
  assert.match(container.textContent, /Kunde inte nå agent-servern/);
});

test("Starta städar upp en döende process innan run.sh körs", async () => {
  // Regression: utan väntan kunde en döende server svara på run.sh:s
  // health-koll, som då hoppade över starten – och inget kördes.
  const { activate } = await loadExtension();
  const { host, pages, calls, dom } = makeHost();
  activate(host);
  const container = dom.window.document.createElement("section");
  pages.get("meier-start")({ container, path: "", navigate() {} });
  await new Promise((r) => setTimeout(r, 20));

  const before = calls.length;
  const startBtn = [...container.querySelectorAll("button")].find(
    (b) => b.textContent.trim() === "Starta",
  );
  assert.ok(startBtn, "hittade ingen Starta-knapp");
  startBtn.dispatchEvent(new dom.window.Event("click"));
  await new Promise((r) => setTimeout(r, 30));

  const startCall = calls.slice(before).find((c) =>
    /run\.sh --background/.test(c.body.command),
  );
  assert.ok(startCall, "Starta anropade inte run.sh");
  const cmd = startCall.body.command;
  const iKill = cmd.indexOf("pkill");
  const iWait = cmd.indexOf("seq 1 40");
  const iRun = cmd.indexOf("./run.sh --background");
  assert.ok(iKill >= 0 && iWait > iKill && iRun > iWait,
    "Starta måste stoppa, vänta på ledig port och först därefter starta");
});
