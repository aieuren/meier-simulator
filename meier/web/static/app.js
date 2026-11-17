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
  $("endBtn").onclick = () => runSession("/api/session/end", "endBtn", "Spelar klart…", "Hela matchen");
  $("matchRunBtn").onclick = runMatchSeries;

  // Om en matchserie redan kör i servern (t.ex. efter omladdning): visa och följ.
  resumeMatchSeries();


  setupLogRepo();
  setupAnalysis();
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
  setSessionBusy(true);
  btn.textContent = "Spelaren svarar…";
  try {
    const res = await fetch("/api/session/advance", { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").insertAdjacentHTML("afterbegin", `<p class="error">Fel: ${err.message}</p>`);
  } finally {
    setSessionBusy(false);
    btn.textContent = "Ett drag";
  }
}

// Kör flödet vidare med ett anrop: till en syn, till rundans slut eller hela matchen.
async function runSession(path, btnId, busyLabel, idleLabel) {
  const btn = $(btnId);
  setSessionBusy(true);
  btn.textContent = busyLabel;
  try {
    const res = await fetch(path, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderSession(data);
  } catch (err) {
    $("log").insertAdjacentHTML("afterbegin", `<p class="error">Fel: ${err.message}</p>`);
  } finally {
    setSessionBusy(false);
    btn.textContent = idleLabel;
  }
}

const SESSION_BTNS = ["okBtn", "runBtn", "roundBtn", "endBtn"];

// Lås alla styrknappar medan ett anrop pågår, så inget dubbelklick hinner iväg.
function setSessionBusy(busy) {
  for (const id of SESSION_BTNS) {
    const b = $(id);
    if (b) b.disabled = busy;
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
  const winner = data.winner;

  const note = $("sessionNote");
  if (finished && winner) {
    note.innerHTML = `Matchen är slut. <strong>${winner.name}</strong> vinner!`;
    note.className = "session-note is-winner";
  } else if (finished) {
    note.textContent = "Sessionen är avslutad.";
    note.className = "session-note";
  } else {
    note.textContent = "";
    note.className = "session-note";
  }

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
    what.textContent = `${textOr((data.current || {}).name, "?")} slår om och måste höja`;
  } else {
    what.textContent = `${textOr((data.current || {}).name, "?")} ska svara på budet`;
  }
  log.appendChild(ctl);
  log.scrollTop = log.scrollHeight;
}

// Rangordningsindex för ett utfall (0 = högst). Använder rankninglistan.
function rankIndex(value) {
  return (state.ranking || []).findIndex((v) => v.value === value);
}

// Är utfallet ett par (två lika tärningar)?
function isPair(value) {
  const hi = Math.floor(value / 10);
  const lo = value % 10;
  return hi === lo && value !== 21;
}

// Kort förklaring till varför synen föll ut som den gjorde.
function explainCall(result) {
  const shown = result.shown;
  const bid = result.bid;
  const shownName = result.shown_name;
  const bidName = result.bid_name;
  if (shown === bid) {
    return `Tärningarna visade exakt ${bidName} – alltså förlorar den som synade.`;
  }
  if (rankIndex(shown) < rankIndex(bid)) {
    const why = shown === 21 ? "Meier är högst" : isPair(shown) ? `${shownName} är ett par` : `${shownName} är högre`;
    return `${why} och slår budet ${bidName} – alltså förlorar den som synade.`;
  }
  return `${shownName} är lägre än budet ${bidName} – alltså förlorar budgivaren.`;
}

// Sammanfattning av en syn, placerad kronologiskt i loggen (efter liv-raden).
function callResultBlock(result) {
  const box = document.createElement("div");
  box.className = "log-row is-call-result";
  const holder = result.holder || result.bidder;
  const holderLine =
    holder !== result.bidder
      ? `<div>Ansvaret för budet hade gått vidare från ${result.bidder} till ${holder}.</div>`
      : "";
  const why = result.reasoning
    ? `<div class="call-why">Motivering: ${escapeHtml(result.reasoning)}</div>`
    : "";
  box.innerHTML = `
    <div class="call-title">Syn!</div>
    <div>Tärningarna visade <strong>${result.shown_name}</strong> mot budet
      <strong>${result.bid_name}</strong>.</div>
    <div>${result.caller} synade ${holder}.</div>
    ${holderLine}
    <div class="call-why">${explainCall(result)}</div>
    ${why}
    <div class="call-loser"><strong>${result.loser}</strong> förlorar
      ${result.lives} liv${result.lives === 2 ? " (Meier kostar dubbelt)" : ""}.</div>
  `;
  return box;
}

// Sammanställning av kvarvarande liv för alla spelare – visas efter en syn.
function standingsBlock(standings) {
  const box = document.createElement("div");
  box.className = "log-row is-standings";
  const items = (standings || [])
    .map((p) => {
      const state = p.active ? `${p.lives} liv` : "ute";
      const cls = p.active ? "is-active" : "is-out";
      return `<span class="standings-item ${cls}">
        <span class="standings-name">${p.name}</span>
        <span class="standings-lives">${state}</span>
      </span>`;
    })
    .join("");
  box.innerHTML = `
    <div class="standings-title">Livsställning</div>
    <div class="standings-list">${items}</div>
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
      const double = lost === 2 ? " (Meier kostar dubbelt)" : "";
      row.innerHTML = `
        <div class="log-head">
          <span class="log-action">Liv förlorat</span>
          <span class="log-player">${textOr(e.player_name, "?")}</span>
          <span class="log-life">−${lost} liv${double} → ${e.lives_left} kvar</span>
        </div>
      `;
      frag.appendChild(row);
      // Direkt efter liv-raden för den senaste synen: synens resultatruta.
      if (result && i === lastCallIdx + 1) {
        frag.appendChild(callResultBlock(result));
      }
      // Livsställningen hör till just den här synen (snapshot i loggraden).
      if (e.standings) {
        frag.appendChild(standingsBlock(e.standings));
      }
      return;
    }

    // Matchen är slut: en egen rad om vinnaren, sist i loggen.
    if (e.kind === "game_over") {
      row.className = "log-row is-game-over";
      row.innerHTML = `
        <div class="log-head">
          <span class="log-action">Matchen är slut</span>
          <span class="log-player">${textOr(e.winner_name, "?")}</span>
          <span class="log-winner">vinner!</span>
        </div>
      `;
      frag.appendChild(row);
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
      main = `<span class="log-action">Skickar vidare</span> <strong>${textOr(e.accepted_bid_name, "?")}</strong>`;
    } else if (e.action === "slå") {
      main =
        `<span class="log-action">Höjer till</span> <strong>${textOr(e.bid_name, "?")}</strong>` +
        `<span class="log-prev">(över ${textOr(e.accepted_bid_name, "?")})</span>`;
    } else if (e.action === "höja") {
      const reroll = e.dice
        ? ` <span class="log-prev">(slog om: ${textOr(e.shown_name, "?")})</span>`
        : "";
      main =
        `<span class="log-action">Måste höja till</span> <strong>${textOr(e.bid_name, "?")}</strong>` +
        `<span class="log-prev">(över ${textOr(e.previous_bid_name, "?")})</span>` +
        reroll;
    } else {
      main = `<span class="log-action">Säger</span> <strong>${textOr(e.bid_name, "?")}</strong>`;
    }
    // Etiketten "sant/bluff" gäller bara bud där spelaren tittat på sina tärningar.
    // Ett blint bud ("slå") kan inte vara en bluff – spelaren såg dem inte.
    const showsTruth =
      (e.action === "bud" || e.action === "höja") && !e.blind;
    const truthTag = showsTruth
      ? `<span class="log-bid ${e.lie ? "lie" : "truth"}">${e.lie ? "bluff" : "sant"}</span>`
      : "";
    const blindTag = e.blind
      ? `<span class="log-blind">blint bud – tittar inte på egna tärningarna</span>`
      : "";
    // Vid tvingad höjning valde spelaren att titta eller bjuda blint; visa varför.
    const choiceTag = e.choice_reasoning
      ? `<span class="log-choice">Val: ${e.blind ? "blint" : "tittade"} – ${escapeHtml(e.choice_reasoning)}</span>`
      : "";

    row.innerHTML = `
      <div class="log-head">
        ${who}
        ${main}
        ${truthTag}
      </div>
      ${blindTag}
      ${choiceTag}
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
        `<span class="ms-cell">blind ${s.blinds || 0}</span>` +
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
        `<td>${pct(b.blind_rate)}</td>` +
        `<td>${pct(b.raise_rate)}</td>` +
        `<td>${pct(b.call_rate)}</td>` +
        `<td>${pct(b.call_success_rate)}</td>` +
        `<td>${b.avg_lives_lost}</td>` +
        `</tr>`
      );
    })
    .join("");
  const tok = summary.tokens;
  const tokenLine = tok
    ? `<p class="hint">
         LLM-förbrukning: i snitt ${Math.round(tok.per_game.total_tokens).toLocaleString("sv-SE")} tokens
         per match (${Math.round(tok.per_game.prompt_tokens).toLocaleString("sv-SE")} in,
         ${Math.round(tok.per_game.completion_tokens).toLocaleString("sv-SE")} ut),
         ${Math.round(tok.calls_per_game)} anrop per match.
         Hela serien: ${tok.total.total_tokens.toLocaleString("sv-SE")} tokens, ${tok.calls} anrop.
       </p>`
    : "";
  box.innerHTML = `
    <p class="hint">
      ${summary.games} matcher, i snitt ${summary.avg_rounds} rundor per match.
      Startspelaren vinner ${pct(summary.starter_win_rate)} av matcherna.
    </p>
    ${tokenLine}
    <table class="stat-table">
      <thead>
        <tr>
          <th>Spelare</th><th>Vinster</th><th>Vinst%</th>
          <th>Bluff%</th><th>Blint bud%</th><th>Höj%</th><th>Syn%</th><th>Syn lyckas</th><th>Snitt liv −</th>
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
  const checkIn = $("matchCheckIn").checked;

  btn.disabled = true;
  const status = $("matchStatus");
  status.hidden = false;
  status.textContent = `Startar serien (${count} matcher)…`;

  try {
    const res = await fetch("/api/matches/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ count, lives, workers, base_seed: baseSeed, check_in: checkIn }),
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
      const name = data.file ? ` (${data.file})` : "";
      status.textContent = `Klart: ${data.done} matcher spelade${name}.`;
      if (data.push_status) status.textContent += ` ${data.push_status}.`;
      btn.disabled = false;
      return;
    }
    status.textContent = matchProgressText(data);
    if (data.push_status) status.textContent += ` ${data.push_status}.`;
  }
}
async function setupLogRepo() {
  const hint = $("matchLogRepoHint");
  const box = $("matchCheckIn");
  if (!hint || !box) return;
  try {
    const res = await fetch("/api/matches/logrepo");
    if (!res.ok) return;
    const data = await res.json();
    hint.hidden = false;
    if (data.ready && data.push_enabled) {
      hint.textContent = `Incheckning är redo mot ${data.repo}. Loggen sparas som en egen fil med datum och klockslag.`;
      box.disabled = false;
    } else {
      box.disabled = true;
      box.checked = false;
      hint.textContent = data.ready
        ? "Automatisk incheckning är avstängd på servern (MEIER_LOGS_PUSH=0)."
        : "Incheckning är inte konfigurerad på servern. Loggen sparas lokalt tills vidare.";
    }
  } catch (e) {
    /* tyst: incheckning är valfritt */
  }
}

// -- Flik 5: analys mot insamlade matchprotokoll ---------------------------

function setupAnalysis() {
  const refresh = $("analysisRefreshBtn");
  if (!refresh) return;
  refresh.onclick = refreshAnalysisLogs;
  $("analysisAskBtn").onclick = askAnalysis;
  refreshAnalysisLogs();
  refreshAnalysisData();
}

// Hämta listan över loggar som finns incheckade i loggrepet.
async function refreshAnalysisLogs() {
  const box = $("analysisLogList");
  box.innerHTML = '<p class="hint">Hämtar loggar…</p>';
  try {
    const res = await fetch("/api/analysis/logs");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderAnalysisLogs(data);
  } catch (e) {
    box.innerHTML = `<p class="error">Kunde inte hämta loggar: ${e.message}</p>`;
  }
}

function renderAnalysisLogs(data) {
  const box = $("analysisLogList");
  box.innerHTML = "";
  if (!data.ready) {
    box.innerHTML = '<p class="hint">Inget loggrepo är konfigurerat på servern.</p>';
    return;
  }
  if (!data.logs.length) {
    box.innerHTML =
      '<p class="hint">Inga loggar incheckade än. Spela en serie med incheckning påslagen.</p>';
    return;
  }
  data.logs.forEach((log) => {
    const label = document.createElement("label");
    label.className = "analysis-log";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = log.name;
    cb.checked = !!log.loaded;
    cb.onchange = syncSelectedLogs;
    const name = document.createElement("span");
    name.className = "analysis-log-name";
    name.textContent = log.label || log.name;
    name.title = log.name;
    const meta = document.createElement("span");
    meta.className = "analysis-log-meta";
    meta.textContent = `${log.games} matcher`;
    label.append(cb, name, meta);
    box.appendChild(label);
  });
}

// Markerade loggar läses in, avmarkerade tas bort. Sker direkt, utan feedback.
async function syncSelectedLogs() {
  const names = Array.from(
    $("analysisLogList").querySelectorAll("input[type=checkbox]:checked")
  ).map((cb) => cb.value);
  try {
    const res = await fetch("/api/analysis/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    await refreshAnalysisData();
  } catch (e) {
    $("analysisLogList").innerHTML =
      `<p class="error">Kunde inte läsa in: ${e.message}</p>`;
  }
}

async function refreshAnalysisData() {
  let data;
  try {
    const res = await fetch("/api/analysis/data");
    data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
  } catch (e) {
    return;
  }
  $("analysisDigest").textContent = data.digest_text || "";
}

async function askAnalysis() {
  const q = $("analysisQuestion").value.trim();
  if (!q) return;
  const btn = $("analysisAskBtn");
  const card = $("analysisResultCard");
  btn.disabled = true;
  btn.textContent = "Analyserar…";
  card.hidden = false;
  $("analysisAnswer").innerHTML = '<p class="hint">Tänker…</p>';
  $("analysisCannot").hidden = true;
  $("analysisChart").innerHTML = "";
  $("analysisFollowups").innerHTML = "";
  $("analysisUsage").textContent = "";

  try {
    const res = await fetch("/api/analysis/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Fel");
    renderAnalysisResult(data);
  } catch (e) {
    $("analysisAnswer").innerHTML = `<p class="error">Fel: ${e.message}</p>`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Analysera";
  }
}

function renderAnalysisResult(data) {
  const note = $("analysisCannot");
  if (data.cannot_answer) {
    note.hidden = false;
    note.textContent = `Underlaget räcker inte: ${data.cannot_answer}`;
  } else {
    note.hidden = true;
    note.textContent = "";
  }
  $("analysisAnswer").innerHTML = markdownLite(data.answer || "");
  $("analysisChart").innerHTML = "";
  if (data.chart) renderChart($("analysisChart"), data.chart);

  const fu = $("analysisFollowups");
  fu.innerHTML = "";
  (data.followups || []).forEach((f) => {
    const b = document.createElement("button");
    b.className = "analysis-suggest";
    b.type = "button";
    b.textContent = f;
    b.onclick = () => {
      $("analysisQuestion").value = f;
      askAnalysis();
    };
    fu.appendChild(b);
  });

  const u = data.usage || {};
  $("analysisUsage").textContent = u.total_tokens
    ? `Modellanrop: ${u.total_tokens} tokens.`
    : "";
}

// Minimal markdown: fetstil, kursiv, radbrytningar, punktlistor och tabeller.
// Ingen HTML från modellen släpps igenom, så svaret kan inte injicera markup.
function markdownLite(text) {
  const esc = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  const lines = esc.split(/\r?\n/);
  const out = [];
  let inList = false;
  let table = [];

  const flushTable = () => {
    if (table.length) {
      out.push(renderMdTable(table));
      table = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trim();

    // Tabellrad: samla ihop och rendera när tabellen tar slut.
    if (line.startsWith("|") && line.endsWith("|")) {
      if (inList) {
        out.push("</ul>");
        inList = false;
      }
      table.push(line);
      continue;
    }
    flushTable();

    const bullet = /^[-*]\s+(.*)$/.exec(line);
    if (bullet) {
      if (!inList) {
        out.push("<ul>");
        inList = true;
      }
      out.push(`<li>${inlineMd(bullet[1])}</li>`);
      continue;
    }
    if (inList) {
      out.push("</ul>");
      inList = false;
    }
    if (line === "") out.push("");
    else out.push(`<p>${inlineMd(line)}</p>`);
  }
  if (inList) out.push("</ul>");
  flushTable();
  return out.join("");
}

// Dela en tabellrad "| a | b |" i celler.
function mdCells(row) {
  return row
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function renderMdTable(rows) {
  if (rows.length === 0) return "";
  const header = mdCells(rows[0]);
  // Rad 2 är en avgränsare (---|---) om den bara består av streck och kolon.
  const isSep = (r) => /^[\s|:-]+$/.test(r);
  const bodyRows = rows.slice(isSep(rows[1] || "") ? 2 : 1);
  const head = header.map((c) => `<th>${inlineMd(c)}</th>`).join("");
  const body = bodyRows
    .map((r) => `<tr>${mdCells(r).map((c) => `<td>${inlineMd(c)}</td>`).join("")}</tr>`)
    .join("");
  return (
    `<table class="stat-table analysis-table"><thead><tr>${head}</tr></thead>` +
    `<tbody>${body}</tbody></table>`
  );
}

function inlineMd(s) {
  return s
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

// Diagram ritas som ren SVG – inga externa bibliotek behövs.
function renderChart(box, chart) {
  const type = chart.type;
  if (type === "table") {
    renderChartTable(box, chart);
    return;
  }
  if (type === "bar") {
    renderChartBar(box, chart);
    return;
  }
  if (type === "line") {
    renderChartLine(box, chart);
    return;
  }
}

function chartTitle(chart) {
  return chart.title ? `<div class="chart-title">${escapeHtml(chart.title)}</div>` : "";
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderChartTable(box, chart) {
  const cols = chart.columns || [];
  const rows = chart.rows || [];
  const head = cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const body = rows
    .map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`)
    .join("");
  box.innerHTML =
    chartTitle(chart) +
    `<table class="stat-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

const CHART_W = 640;
const CHART_H = 300;
const PAD = { top: 20, right: 16, bottom: 64, left: 48 };

function chartScaffold(chart, maxVal) {
  const plotW = CHART_W - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;
  return { plotW, plotH, maxVal: maxVal > 0 ? maxVal : 1 };
}

function svgOpen() {
  return `<svg viewBox="0 0 ${CHART_W} ${CHART_H}" class="chart-svg" role="img" preserveAspectRatio="xMidYMid meet">`;
}

function renderChartBar(box, chart) {
  const labels = chart.labels || [];
  const values = (chart.values || []).map((v) => Number(v) || 0);
  const maxVal = Math.max(1, ...values);
  const { plotW, plotH } = chartScaffold(chart, maxVal);
  const n = Math.max(1, labels.length);
  const slot = plotW / n;
  const barW = Math.min(56, slot * 0.6);
  const baseY = PAD.top + plotH;

  let bars = "";
  labels.forEach((lab, i) => {
    const v = values[i] || 0;
    const h = (v / maxVal) * plotH;
    const x = PAD.left + slot * i + (slot - barW) / 2;
    const y = baseY - h;
    bars +=
      `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" rx="3" class="chart-bar"></rect>` +
      `<text x="${(x + barW / 2).toFixed(1)}" y="${(y - 4).toFixed(1)}" class="chart-val" text-anchor="middle">${escapeHtml(v)}</text>` +
      `<text x="${(PAD.left + slot * i + slot / 2).toFixed(1)}" y="${baseY + 16}" class="chart-lbl" text-anchor="middle">${escapeHtml(lab)}</text>`;
  });

  const axis = `<line x1="${PAD.left}" y1="${baseY}" x2="${CHART_W - PAD.right}" y2="${baseY}" class="chart-axis"></line>`;
  box.innerHTML = chartTitle(chart) + svgOpen() + axis + bars + "</svg>";
}

function renderChartLine(box, chart) {
  const labels = chart.labels || [];
  const series = chart.series || [];
  const allVals = series.flatMap((s) => (s.values || []).map((v) => Number(v) || 0));
  const maxVal = Math.max(1, ...allVals);
  const { plotW, plotH } = chartScaffold(chart, maxVal);
  const baseY = PAD.top + plotH;
  const n = Math.max(1, labels.length);
  const stepX = n > 1 ? plotW / (n - 1) : 0;
  const xAt = (i) => PAD.left + stepX * i;
  const yAt = (v) => baseY - (v / maxVal) * plotH;

  let paths = "";
  const palette = ["#9aa4b8", "#6fae8a", "#cf8378", "#c9b98f", "#8fa9cf"];
  series.forEach((s, si) => {
    const vals = (s.values || []).map((v) => Number(v) || 0);
    const pts = vals.map((v, i) => `${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`).join(" ");
    const color = palette[si % palette.length];
    paths += `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" class="chart-line"></polyline>`;
    vals.forEach((v, i) => {
      paths += `<circle cx="${xAt(i).toFixed(1)}" cy="${yAt(v).toFixed(1)}" r="3" fill="${color}"></circle>`;
    });
  });

  const axis = `<line x1="${PAD.left}" y1="${baseY}" x2="${CHART_W - PAD.right}" y2="${baseY}" class="chart-axis"></line>`;
  let xl = "";
  labels.forEach((lab, i) => {
    xl += `<text x="${xAt(i).toFixed(1)}" y="${baseY + 16}" class="chart-lbl" text-anchor="middle">${escapeHtml(lab)}</text>`;
  });
  let legend = "";
  series.forEach((s, si) => {
    const color = palette[si % palette.length];
    legend += `<span class="chart-legend-item"><i style="background:${color}"></i>${escapeHtml(s.name || "")}</span>`;
  });

  box.innerHTML =
    chartTitle(chart) +
    svgOpen() +
    axis +
    paths +
    xl +
    "</svg>" +
    (legend ? `<div class="chart-legend">${legend}</div>` : "");
}

boot();
