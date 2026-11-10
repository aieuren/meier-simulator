const $ = (id) => document.getElementById(id);

let state = { role: "kalkyl", ranking: [] };

async function boot() {
  setupTabs();

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

  renderPlayers(data);

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
  $("roundBtn").onclick = () => runSession("/api/session/round", "roundBtn", "Spelar…", "Till slut på runda");
  $("runBtn").onclick = () => runSession("/api/session/run", "runBtn", "Spelar…", "Till syn");
  $("matchRunBtn").onclick = runMatchSeries;

  // Om en matchserie redan kör i servern (t.ex. efter omladdning): visa och följ.
  resumeMatchSeries();
}

function setupTabs() {
  const tabs = document.querySelectorAll(".tab");
  tabs.forEach((tab) => {
    tab.onclick = () => {
      tabs.forEach((t) => {
        const on = t === tab;
        t.classList.toggle("active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      document.querySelectorAll(".tab-panel").forEach((p) => {
        p.hidden = p.id !== tab.dataset.tab;
      });
    };
  });
}

// -- Flik 1: de fyra spelarna och deras karaktärer --------------------------

function playerCard(r) {
  const div = document.createElement("div");
  div.className = "player-card";
  div.innerHTML = `
    <div class="player-name">${r.name}</div>
    <div class="player-desc">${r.description}</div>
    <p class="player-style">${r.style || ""}</p>
  `;
  return div;
}

function renderPlayers(data) {
  const list = $("playerList");
  if (!list) return;
  list.innerHTML = "";
  (data.roles || []).forEach((r) => list.appendChild(playerCard(r)));
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
    btn.textContent = "Ett drag";
  }
}

// Kör flödet vidare med ett anrop: till rundans slut eller till en syn.
async function runSession(path, btnId, busyLabel, idleLabel) {
  const btn = $(btnId);
  btn.disabled = true;
  btn.textContent = busyLabel;
  try {
    const res = await fetch(path, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").insertAdjacentHTML("afterbegin", `<p class="error">Fel: ${err.message}</p>`);
  } finally {
    btn.disabled = false;
    btn.textContent = idleLabel;
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

  renderOrderNote(data);
  renderLog(data.log, data.result);
  placeControls(data, pending);
}

// Visa spelordningen och vem som börjar – slumpas fram vid Ny session.
function renderOrderNote(data) {
  const box = $("orderNote");
  if (!box) return;
  const order = data.order || [];
  if (order.length === 0) {
    box.hidden = true;
    return;
  }
  box.hidden = false;
  const chain = order
    .map((p) => {
      const lives = `<span class="order-lives">${p.lives} liv</span>`;
      return `<span class="order-player">${p.name}${lives}</span>`;
    })
    .join('<span class="order-arrow">→</span>');
  box.innerHTML = `
    <div class="order-title">Spelordning</div>
    <div class="order-chain">${chain}</div>
    <div class="order-start"><strong>${textOr(data.starter, "?")}</strong> börjar</div>
  `;
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

// Sammanfattning av en syn, placerad kronologiskt i loggen (efter liv-raden).
function callResultBlock(result) {
  const box = document.createElement("div");
  box.className = "log-row is-call-result";
  const holder = result.holder || result.bidder;
  const holderLine =
    holder !== result.bidder
      ? `<div>Budet sattes av ${result.bidder}, men ansvaret hade gått vidare till ${holder}.</div>`
      : "";
  box.innerHTML = `
    <div class="call-title">Syn!</div>
    <div>Tärningarna visade <strong>${result.shown_name}</strong> mot budet
      <strong>${result.bid_name}</strong>.</div>
    <div>${result.caller} synade ${holder}.</div>
    ${holderLine}
    <div class="call-loser"><strong>${result.loser}</strong> förlorar
      ${result.lives} liv${result.lives === 2 ? " (Mejer kostar dubbelt)" : ""}.</div>
  `;
  return box;
}

function renderLog(entries, result) {
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

  // Sista synen i loggen – resultatrutan hör hemma direkt efter dess liv-rad.
  let lastCallIdx = -1;
  entries.forEach((e, i) => {
    if (e.action === "syna") lastCallIdx = i;
  });

  const frag = document.createDocumentFragment();
  let prevRound = null;

  entries.forEach((e, i) => {
    // Ny runda: en tydlig avdelare så att man ser var rundan börjar.
    if (prevRound !== null && e.round !== prevRound) {
      const sep = document.createElement("div");
      sep.className = "log-round";
      const starter = e.kind === "roll" && e.player_name ? ` · ${e.player_name} börjar` : "";
      sep.innerHTML = `<span class="log-round-label">Runda ${e.round}${starter}</span>`;
      frag.appendChild(sep);
    }
    prevRound = e.round;

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

    // Förlorat liv: en egen rad direkt efter synen.
    if (e.kind === "life") {
      row.className = "log-row is-life";
      const lost = e.lives_lost || 1;
      const double = lost === 2 ? " (Mejer kostar dubbelt)" : "";
      row.innerHTML = `
        <div class="log-head">
          <span class="log-action">Liv förlorat</span>
          <span class="log-player">${textOr(e.player_name, "?")}</span>
          <span class="log-life">−${lost} liv${double} → ${e.lives_left} kvar</span>
        </div>
      `;
      frag.appendChild(row);
      // Direkt efter liv-raden för den senaste synen: synens resultat.
      if (result && i === lastCallIdx + 1) {
        frag.appendChild(callResultBlock(result));
      }
      return;
    }

    // Spelarens svar: en egen rad per åtgärd.
    row.className = "log-row is-action" + (e.action === "syna" ? " is-call" : "");
    const corrected = e.corrected
      ? `<span class="log-corrected" title="Modellen föreslog ${e.proposed}">korrigerat bud</span>`
      : "";
    const who = e.player_name ? `<span class="log-player">${e.player_name}</span>` : "";

    let main;
    if (e.action === "syna") {
      main = `<span class="log-action">Synar</span> <span class="log-prev">budet ${textOr(e.accepted_bid_name, "?")}</span>`;
    } else if (e.action === "skicka") {
      main =
        `<span class="log-action">Skickar vidare</span> <strong>${textOr(e.accepted_bid_name, "?")}</strong>` +
        `<span class="log-prev">utan att slå</span>`;
    } else if (e.action === "slå") {
      main =
        `<span class="log-action">Accepterar och slår</span>` +
        `<span class="log-prev">över ${textOr(e.accepted_bid_name, "?")}</span>` +
        `<span class="log-says">säger</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    } else if (e.action === "höja") {
      main =
        `<span class="log-action">Höjer</span>` +
        `<span class="log-prev">över ${textOr(e.previous_bid_name, "?")}</span>` +
        `<span class="log-says">säger</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    } else {
      main = `<span class="log-action">Säger</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    }
    const truthTag =
      e.action === "bud" || e.action === "slå" || e.action === "höja"
        ? `<span class="log-bid ${e.lie ? "lie" : "truth"}">${e.lie ? "bluff" : "sant"}</span>`
        : "";

    row.innerHTML = `
      <div class="log-head">
        ${who}
        ${main}
        ${truthTag}
      </div>
      ${corrected}
    `;
    frag.appendChild(row);
  });
  box.insertBefore(frag, ctl && ctl.parentNode === box ? ctl : null);
  box.scrollTop = box.scrollHeight;
}

// -- Flik 4: matchserie och statistik ---------------------------------------

const pct = (v) => `${((v || 0) * 100).toFixed(1)} %`;

function matchRow(rec) {
  const div = document.createElement("details");
  div.className = "match-row";
  const order = (rec.order || []).join(" → ");
  const stats = rec.player_stats || {};
  const lines = (rec.players || [])
    .map((p) => {
      const s = stats[p.name] || {};
      return (
        `<div class="match-stat-line">` +
        `<span class="ms-name">${p.name}</span>` +
        `<span class="ms-cell">bud ${s.bids || 0}</span>` +
        `<span class="ms-cell">bluff ${s.bluffs || 0}</span>` +
        `<span class="ms-cell">syn ${s.calls || 0}</span>` +
        `<span class="ms-cell">liv −${s.lives_lost || 0}</span>` +
        `<span class="ms-cell">${s.eliminated ? "ute" : (p.name === rec.winner ? "vinnare" : "kvar")}</span>` +
        `</div>`
      );
    })
    .join("");
  div.innerHTML = `
    <summary>
      <span class="match-no">Match ${rec.game}</span>
      <span class="match-winner">Vinnare: ${rec.winner}</span>
      <span class="match-meta">${rec.rounds} rundor</span>
    </summary>
    <div class="match-body">
      <p class="match-order"><strong>Spelordning:</strong> ${order}. <strong>Börjar:</strong> ${rec.starter}.</p>
      ${lines}
    </div>
  `;
  return div;
}

function renderMatchSummary(summary) {
  const box = $("matchSummaryBody");
  const roles = summary.roles || {};
  const rows = Object.keys(roles)
    .map((role) => {
      const b = roles[role];
      return (
        `<tr>` +
        `<td>${b.name}</td>` +
        `<td>${b.wins}/${b.games}</td>` +
        `<td>${pct(b.win_rate)}</td>` +
        `<td>${pct(b.bluff_rate)}</td>` +
        `<td>${pct(b.raise_rate)}</td>` +
        `<td>${pct(b.call_rate)}</td>` +
        `<td>${pct(b.call_success_rate)}</td>` +
        `<td>${b.avg_lives_lost}</td>` +
        `</tr>`
      );
    })
    .join("");
  box.innerHTML = `
    <p class="hint">
      ${summary.games} matcher, i snitt ${summary.avg_rounds} rundor per match.
      Startspelaren vinner ${pct(summary.starter_win_rate)} av matcherna.
    </p>
    <table class="stat-table">
      <thead>
        <tr>
          <th>Spelare</th><th>Vinster</th><th>Vinst%</th>
          <th>Bluff%</th><th>Höj%</th><th>Syn%</th><th>Syn lyckas</th><th>Snitt liv −</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
  $("matchSummary").hidden = false;
}

async function runMatchSeries() {
  const btn = $("matchRunBtn");
  const count = parseInt($("matchCount").value, 10) || 1;
  const lives = parseInt($("matchLives").value, 10) || 3;
  const workers = parseInt($("matchWorkers").value, 10) || 1;
  const seedRaw = $("matchSeed").value.trim();
  const baseSeed = seedRaw === "" ? null : parseInt(seedRaw, 10);

  btn.disabled = true;
  const status = $("matchStatus");
  status.hidden = false;
  status.textContent = `Startar serien (${count} matcher)…`;

  try {
    const res = await fetch("/api/matches/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count, lives, workers, base_seed: baseSeed }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    await pollMatchSeries();
  } catch (e) {
    status.textContent = `Fel: ${e.message}`;
    btn.disabled = false;
  }
}

// Om sidan laddas om mitt i en serie: visa det som redan är klart och fortsätt
// följa serien. Annars står fliken tom trots att jobbet kör vidare i servern.
async function resumeMatchSeries() {
  let data;
  try {
    const res = await fetch("/api/matches/status");
    if (!res.ok) return;
    data = await res.json();
  } catch (e) {
    return;
  }
  renderMatchList(data);
  if (data.summary) renderMatchSummary(data.summary);
  if (data.running) {
    $("matchStatus").hidden = false;
    $("matchStatus").textContent = matchProgressText(data);
    $("matchRunBtn").disabled = true;
    await pollMatchSeries();
  }
}

function matchProgressText(data) {
  const base = `${data.done} av ${data.count} matcher klara`;
  const avg = data.summary ? ` · snitt ${data.summary.avg_rounds} rundor/match` : "";
  return `${base}${avg}…`;
}

function renderMatchList(data) {
  const list = $("matchList");
  list.innerHTML = "";
  (data.records || []).forEach((rec) => list.appendChild(matchRow(rec)));
}

async function pollMatchSeries() {
  const status = $("matchStatus");
  const btn = $("matchRunBtn");

  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    let data;
    try {
      const res = await fetch("/api/matches/status");
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      data = await res.json();
    } catch (e) {
      status.textContent = `Fel vid hämtning av status: ${e.message}`;
      btn.disabled = false;
      return;
    }

    renderMatchList(data);
    if (data.summary) renderMatchSummary(data.summary);

    if (data.error) {
      status.textContent = `Fel: ${data.error}`;
      btn.disabled = false;
      return;
    }
    if (!data.running) {
      status.textContent = `Klart: ${data.done} matcher spelade.`;
      btn.disabled = false;
      return;
    }
    status.textContent = matchProgressText(data);
  }
}

boot();
