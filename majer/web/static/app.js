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

boot();
