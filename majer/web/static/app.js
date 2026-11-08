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
    btn.textContent = "OK – låt spelaren svara";
  }
}

function renderSession(data) {
  $("sessionStatus").hidden = false;

  // Ordning
  const orderNames = data.order.map((p) => p.name).join(" → ");
  $("turnInfo").innerHTML = `<span class="muted">Spelordning:</span> ${orderNames}`;

  const finished = data.phase === "finished";
  if (finished) {
    $("okBtn").hidden = true;
    $("pendingDice").hidden = true;
    $("turnInfo").innerHTML += ` <span class="muted">(avslutad)</span>`;
  } else {
    const cur = data.current;
    $("turnInfo").innerHTML += `<br><span class="muted">I tur:</span> <strong>${cur.name}</strong>`;
    if (data.pending) {
      $("okBtn").hidden = false;
      $("pendingDice").hidden = false;
      $("pendingValue").textContent = data.pending.shown_name;
      $("pendingDetail").textContent = `(tärning ${data.pending.dice[0]} och ${data.pending.dice[1]})`;
    }
  }

  renderLog(data.log);
}

function renderLog(entries) {
  const box = $("log");
  if (!entries || entries.length === 0) {
    box.innerHTML = '<p class="hint">Ingen logg än.</p>';
    return;
  }
  box.innerHTML = "";
  // Nyaste först.
  [...entries].reverse().forEach((e) => {
    const row = document.createElement("div");
    row.className = "log-row";
    const ref = e.referee || {};
    const refClass = ref.ok ? "ok" : "objection";
    const refText = ref.ok ? "Domaren: OK" : "Domaren: invändning";
    const refDetail = ref.ok ? "" : `<div class="ref-detail">${(ref.objections || []).join(" ")}</div>`;
    const corrected = e.corrected
      ? `<span class="log-corrected" title="Modellen föreslog ${e.proposed}">korrigerat bud</span>`
      : "";
    row.innerHTML = `
      <div class="log-head">
        <span class="log-player">${e.player_name}</span>
        <span class="log-dice">🎲 ${e.shown_name}</span>
        <span class="log-bid ${e.lie ? "lie" : "truth"}">säger ${e.bid_name}</span>
        ${corrected}
        <span class="log-referee ${refClass}">${refText}</span>
      </div>
      <div class="log-line">“${e.line || ""}”</div>
      <div class="log-reasoning">${e.reasoning || ""}</div>
      ${refDetail}
    `;
    box.appendChild(row);
  });
}

boot();
