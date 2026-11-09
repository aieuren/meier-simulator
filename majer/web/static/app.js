const $ = (id) => document.getElementById(id);

let state = { role: "kalkyl", ranking: [] };

async function boot() {
  // Fyll tärningsval
  for (const sel of [$("die1"), $("die2")]) {
    for (let i = 1; i <= 6; i++) {
      const o = document.createElement("option");
      o.value = i;
      o.textContent = i;
      sel.appendChild(o);
    }
  }
  $("die1").value = "2";
  $("die2").value = "5";

  const res = await fetch("/api/roles");
  const data = await res.json();
  state.ranking = data.ranking;

  // Rollkort
  const list = $("roleList");
  data.roles.forEach((r) => {
    const div = document.createElement("div");
    div.className = "role" + (r.key === state.role ? " active" : "");
    div.dataset.key = r.key;
    div.innerHTML = `<span class="rname">${r.name}</span><span class="rdesc">${r.description}</span>`;
    div.onclick = () => {
      state.role = r.key;
      document.querySelectorAll(".role").forEach((el) => el.classList.toggle("active", el.dataset.key === r.key));
    };
    list.appendChild(div);
  });

  // Tidigare bud + motståndarbud
  for (const v of data.ranking) {
    const o1 = document.createElement("option");
    o1.value = v.value;
    o1.textContent = v.name;
    $("previousBid").appendChild(o1);

    const o2 = o1.cloneNode(true);
    $("oppBid").appendChild(o2);
  }

  // Poängordning
  const rank = $("ranking");
  data.ranking.forEach((v) => {
    const s = document.createElement("span");
    s.textContent = v.name;
    rank.appendChild(s);
  });

  updatePreview();
  $("die1").onchange = updatePreview;
  $("die2").onchange = updatePreview;
  $("announceBtn").onclick = doAnnounce;
  $("decideBtn").onclick = doDecide;
  $("newSessionBtn").onclick = newSession;
  $("okBtn").onclick = advanceSession;
  $("runBtn").onclick = runToCall;
}

function readDice(a, b) {
  const hi = Math.max(a, b);
  const lo = Math.min(a, b);
  return hi * 10 + lo;
}

function updatePreview() {
  const a = +$("die1").value;
  const b = +$("die2").value;
  $("dicePreview").textContent = readDice(a, b);
}

async function doAnnounce() {
  const btn = $("announceBtn");
  const card = $("resultCard");
  btn.disabled = true;
  card.hidden = false;
  $("verdict").textContent = "Tänker…";
  $("verdict").className = "verdict loading";
  $("say").textContent = "";
  $("facts").innerHTML = "";
  $("reasoning").textContent = "";

  const body = {
    die1: +$("die1").value,
    die2: +$("die2").value,
    role: state.role,
  };
  const prev = $("previousBid").value;
  if (prev) body.previous_bid = +prev;

  try {
    const res = await fetch("/api/announce", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderAnnounce(data);
  } catch (err) {
    $("verdict").textContent = "Fel: " + err.message;
    $("verdict").className = "verdict error";
  } finally {
    btn.disabled = false;
  }
}

function renderAnnounce(data) {
  const a = data.announcement;
  const v = $("verdict");
  v.className = "verdict " + (a.truth ? "truth" : "lie");
  v.textContent = a.truth ? "Sanning" : "Bluff";

  $("say").textContent = a.line ? `“${a.line}”` : "";

  const facts = $("facts");
  facts.innerHTML = "";
  const rows = [
    ["Tärningarna visar", data.shown_name],
    ["Spelaren säger", a.bid_name],
    ["Lögn?", a.lie ? "Ja" : "Nej"],
  ];
  if (data.previous_bid) rows.push(["Tidigare bud", data.previous_bid]);
  rows.forEach(([k, val]) => {
    const dt = document.createElement("dt");
    dt.textContent = k;
    const dd = document.createElement("dd");
    dd.textContent = val;
    facts.append(dt, dd);
  });

  $("reasoning").textContent = a.reasoning ? "Motivering: " + a.reasoning : "";
}

async function doDecide() {
  const btn = $("decideBtn");
  const out = $("decision");
  btn.disabled = true;
  out.hidden = false;
  out.textContent = "Tänker…";
  out.className = "verdict loading";

  try {
    const res = await fetch("/api/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ bid: +$("oppBid").value, role: state.role, lives: 3 }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    let text = `Spelaren väljer: ${data.action.toUpperCase()}`;
    if (data.bid_name) text += ` → ${data.bid_name}`;
    if (data.line) text += `  “${data.line}”`;
    out.textContent = text;
    out.className = "verdict";
    if (data.reasoning) {
      const r = document.createElement("div");
      r.className = "reasoning";
      r.textContent = "Motivering: " + data.reasoning;
      out.appendChild(r);
    }
  } catch (err) {
    out.textContent = "Fel: " + err.message;
    out.className = "verdict error";
  } finally {
    btn.disabled = false;
  }
}

// -- Interaktiv spelsession -------------------------------------------------

async function newSession() {
  const btn = $("newSessionBtn");
  btn.disabled = true;
  btn.textContent = "Startar…";
  try {
    const res = await fetch("/api/session/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles: ["arling", "rackar", "kalkyl", "trygg"] }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").innerHTML = `<p class="error">Fel: ${err.message}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Ny session";
  }
}

async function advanceSession() {
  const btn = $("okBtn");
  btn.disabled = true;
  btn.textContent = "Spelaren svarar…";
  try {
    const res = await fetch("/api/session/advance", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").insertAdjacentHTML("afterbegin", `<p class="error">Fel: ${err.message}</p>`);
  } finally {
    btn.disabled = false;
    btn.textContent = "OK – nästa steg";
  }
}

async function runToCall() {
  const btn = $("runBtn");
  btn.disabled = true;
  btn.textContent = "Spelar…";
  try {
    const res = await fetch("/api/session/run", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").insertAdjacentHTML("afterbegin", `<p class="error">Fel: ${err.message}</p>`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Kör till syn";
  }
}

const DICE_FACE = ["", "⚀", "⚁", "⚂", "⚃", "⚄", "⚅"];

function diceFaces(dice) {
  if (!Array.isArray(dice) || dice.length < 2) return "";
  return dice
    .slice(0, 2)
    .map((d) => `<span class="die" title="tärning ${d}">${DICE_FACE[d] || d}</span>`)
    .join("");
}

function textOr(value, fallback) {
  return value === undefined || value === null || value === "" ? fallback : value;
}

function renderSession(data) {
  $("sessionStatus").hidden = false;

  const finished = data.phase === "finished";
  const pending = data.pending || {};

  $("sessionNote").textContent = finished ? "Sessionen är avslutad." : "";

  renderResult(data.result);
  renderLog(data.log);
  placeControls(data, pending);
}

// Flytta OK-knappen till tärningsutfallet i loggen och visa vad som väntar.
function placeControls(data, pending) {
  const ctl = $("pendingCtl");
  const log = $("log");
  const what = $("pendingWhat");

  if (data.phase === "finished") {
    ctl.hidden = true;
    what.textContent = "";
    return;
  }

  ctl.hidden = false;
  if (data.step_kind === "roll") {
    what.textContent = `${textOr((data.current || {}).name, "?")} ska säga sitt bud`;
  } else if (data.step_kind === "raise") {
    what.textContent = `${textOr((data.current || {}).name, "?")} måste höja`;
  } else {
    what.textContent = `${textOr((data.current || {}).name, "?")} ska svara på budet`;
  }
  log.appendChild(ctl);
  log.scrollTop = log.scrollHeight;
}

function renderResult(result) {
  let box = $("callResult");
  if (!box) {
    box = document.createElement("div");
    box.id = "callResult";
    box.className = "call-result";
    $("sessionStatus").appendChild(box);
  }
  if (!result) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  box.innerHTML = `
    <div class="call-title">Syn!</div>
    <div>Tärningarna visade <strong>${result.shown_name}</strong> mot budet
      <strong>${result.bid_name}</strong>.</div>
    <div>${result.caller} synade ${result.bidder}.</div>
    <div class="call-loser"><strong>${result.loser}</strong> förlorar
      ${result.lives} liv${result.lives === 2 ? " (Mejer kostar dubbelt)" : ""}.</div>
  `;
}

function renderLog(entries) {
  const box = $("log");
  const ctl = $("pendingCtl");
  // Behåll OK-panelen (den ligger inuti loggen) när vi bygger om raderna.
  [...box.children].forEach((c) => {
    if (c.id !== "pendingCtl") c.remove();
  });

  if (!entries || entries.length === 0) {
    box.insertAdjacentHTML("afterbegin", '<p class="hint">Ingen logg än.</p>');
    return;
  }

  // Bygg alla rader i ordning (äldst först) och sätt dem ovanför OK-panelen.
  const frag = document.createDocumentFragment();
  entries.forEach((e) => {
    const row = document.createElement("div");

    // Tärningsutfall: en egen rad med tärningarna som indata.
    if (e.kind === "roll") {
      row.className = "log-row is-roll";
      const who = e.player_name ? `<span class="log-player">${e.player_name}</span> slår` : "Tärningsslag";
      row.innerHTML = `
        <div class="log-head">
          <span class="log-action">${who}</span>
          <span class="log-dice">${diceFaces(e.dice)} <strong>${textOr(e.shown_name, "?")}</strong></span>
        </div>
      `;
      frag.appendChild(row);
      return;
    }

    // Spelarens svar: bara siffran eller åtgärden – ingen replik.
    row.className = "log-row is-action" + (e.action === "syna" ? " is-call" : "");
    const ref = e.referee || {};
    const refClass = ref.ok ? "ok" : "objection";
    const refText = ref.ok ? "Domaren: OK" : "Domaren: invändning";
    const refDetail = ref.ok
      ? ""
      : `<div class="ref-detail">${(ref.objections || []).join(" ")}</div>`;
    const corrected = e.corrected
      ? `<span class="log-corrected" title="Modellen föreslog ${e.proposed}">korrigerat bud</span>`
      : "";

    let main;
    if (e.action === "syna") {
      main = `<span class="log-action">Synar</span>`;
    } else if (e.action === "skicka") {
      main = `<span class="log-action">Skickar vidare</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    } else if (e.action === "slå") {
      main = `<span class="log-action">Slår</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    } else if (e.action === "höja") {
      main = `<span class="log-action">Höjer</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    } else {
      main = `<span class="log-action">Säger</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    }
    const prev =
      e.previous_bid_name && (e.action === "slå" || e.action === "höja")
        ? `<span class="log-prev">(över ${e.previous_bid_name})</span>`
        : "";
    const truthTag =
      e.action === "bud" || e.action === "slå" || e.action === "höja"
        ? `<span class="log-bid ${e.lie ? "lie" : "truth"}">${e.lie ? "bluff" : "sant"}</span>`
        : "";
    const who = e.player_name ? `<span class="log-player">${e.player_name}</span>` : "";

    row.innerHTML = `
      <div class="log-head">
        ${who}
        ${main} ${prev}
        ${truthTag}
        <span class="log-referee ${refClass}">${refText}</span>
      </div>
      ${corrected}
      ${refDetail}
    `;
    frag.appendChild(row);
  });
  box.insertBefore(frag, ctl && ctl.parentNode === box ? ctl : null);
  box.scrollTop = box.scrollHeight;
}

boot();
