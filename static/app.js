/* Kirogotchi front end. Plain JS, no build step.
 * Reading status is not a measurement. Only "Look" calls /look. */

const $ = (sel) => document.querySelector(sel);
const app = $("#app");
const KEY = "kirogotchi";

let ghostSvg = "";
let me = load();
let current = null;

function load() {
  try { return JSON.parse(localStorage.getItem(KEY)) || null; } catch { return null; }
}
function save(v) {
  try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* private window: fine, the session still works */ }
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  if (me?.secret) headers["X-Ghost-Secret"] = me.secret;
  const r = await fetch(path, { ...opts, headers });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch { /* keep statusText */ }
    const err = new Error(msg); err.status = r.status;
    throw err;
  }
  return r.json();
}

function setScreen(name) { app.dataset.screen = name; }

let lookingNow = false;
let lookBefore = null;
function friendLooked(prev, g) {
  // Our ghost was measured while we were not looking: a bound friend looked.
  if (lookingNow) return null;
  const ev = [...g.history].reverse().find((e) => e.event === "looked" && e.by);
  if (!ev) return null;
  let seen = null;
  try { seen = localStorage.getItem(KEY + ":seen"); } catch { /* fine */ }
  if (String(ev.t) === seen) return null;
  try { localStorage.setItem(KEY + ":seen", String(ev.t)); } catch { /* fine */ }
  return ev;
}
function render(g) {
  const ev = friendLooked(current, g);
  current = g;
  if (typeof g.now === "number") clockSkew = g.now - Date.now() / 1000; // run the ring on the server's clock
  if (ev) {
    showReveal({
      ...g, alive: ev.alive, odds_alive_before: ev.odds, circuit: ev.circuit, steps: ev.steps,
      cause: ev.cause, bitstring: ev.bitstring, bound_outcome: { name: ev.by, alive: ev.partner_alive }, by: ev.by,
    });
    $("#reveal-close").onclick = () => { $("#reveal").hidden = true; render(g); };
  }
  $("#ghost-name").textContent = g.name;
  $("#share-code").textContent = g.id;

  const odds = oddsAlive(g); // not shown: the two ghosts are the only hint
  $("#vitals").textContent = vitals(g);
  const friendPress = friendPressed(g);
  if (friendPress) hint(friendPress);
  else if (Date.now() - hintAt < 20_000 && hintText) hint(hintText, true);
  else hint(defaultHint(g, odds));
  if (!g.alive) moveDot(dialTheta < 0 ? -Math.PI : Math.PI); // while alive, the frame loop moves it

  const wrap = $("#ghost");
  const chip = $("#state-chip");
  const tomb = $("#tombstone");
  const actions = $("#actions");
  const after = $("#after-death");

  wrap.classList.remove("superposed", "collapsing", "alive-collapsed", "dead-collapsed");
  if (!g.alive) {
    wrap.classList.add("dead-collapsed");
    tomb.hidden = false;
    $("#stone-name").textContent = g.name;
    $("#stone-sub").textContent = `lived ${age(g)} · gone on look ${g.looks}`;
    chip.textContent = "gone";
    chip.className = "chip dead";
    actions.hidden = true;
    $("#more").hidden = true;
    $("#bind-form").hidden = true;
    after.hidden = false;
  } else {
    tomb.hidden = true;
    wrap.classList.add("superposed");
    chip.textContent = g.looks ? `alive at look ${g.looks}` : "not looked yet";
    chip.className = "chip" + (g.looks ? " alive" : "");
    actions.hidden = false;
    $("#more").hidden = false;
    after.hidden = true;
  }

  const bn = $("#bound-note");
  if (g.bound_to) {
    bn.hidden = false;
    bn.textContent = `Bound to ${g.bound_name || g.bound_to}. Feed and Play from either of you turn it. The first Look from either of you answers both.`;
    $("#bind-btn").disabled = true;
  } else {
    bn.hidden = true;
    $("#bind-btn").disabled = false;
  }
  setScreen("ghost");
}

async function refresh() {
  if (!me?.id) { setScreen("hatch"); return; }
  try {
    const g = await api(`/api/ghosts/${me.id}`);
    render(g);
  } catch (e) {
    if (e.status === 404) { me = null; save(null); setScreen("hatch"); }
    else toast("No connection. Your ghost is still there.");
  }
}

/* the stage is the circle: angle 0 is the top (alive), pi the bottom (the grave). Negative angles go over the top. */
let dialTheta = 0;
let dialAnim = null;
let clockSkew = 0;
let ghostHeld = false;
/* the circle's radius, read from the page: smaller on short screens */
function orbitR(sel = "#stage .orbit") { const o = document.querySelector(sel); return o && o.offsetWidth ? o.offsetWidth / 2 : 92; }

/* The ring never stops: a new random speed and direction every 3 seconds.
 * Same functions as app/spin.py, so the page and the Look agree on the angle. */
const SEGMENT = 3;
function rnd(seed, k, salt) {
  let x = (seed ^ Math.imul(k, 0x9E3779B1) ^ Math.imul(salt, 0x85EBCA77)) >>> 0;
  x ^= x >>> 16; x = Math.imul(x, 0x7FEB352D) >>> 0;
  x ^= x >>> 15; x = Math.imul(x, 0x846CA68B) >>> 0;
  x ^= x >>> 16;
  return (x >>> 0) / 4294967296;
}
function velocity(seed, k) {
  const lap = 10 + 10 * rnd(seed, k, 1);
  return (rnd(seed, k, 2) < 0.5 ? -1 : 1) * 2 * Math.PI / lap;
}
let spinCache = null; // {key, k, a}: the angle at the start of segment k, so a frame never re-adds every segment
function spinAt(g, t) {
  const seed = g.spin_seed >>> 0, t0 = g.spin_t0 || 0, base = g.spin_base || 0;
  if (t <= t0) return base;
  const key = `${seed}|${t0}|${base}`;
  const K = Math.floor((t - t0) / SEGMENT);
  if (!spinCache || spinCache.key !== key || spinCache.k > K) spinCache = { key, k: 0, a: base };
  while (spinCache.k < K) { spinCache.a += velocity(seed, spinCache.k) * SEGMENT; spinCache.k += 1; }
  return spinCache.a + velocity(seed, K) * (t - (t0 + SEGMENT * K));
}
function serverNow() { return Date.now() / 1000 + clockSkew; }
function gateAngle(c) { return c.startsWith("fire:") ? Number(c.slice(5)) : (CARE[c] || 0); }
function netTheta(g) {
  let theta = (g.birth_angle || 0) + spinAt(g, serverNow());
  for (const c of g.care_gates) theta -= gateAngle(c);
  return theta;
}
/* every frame: the ghost follows the ring; a press glides it to its new place instead of jumping */
let lastFrame = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - lastFrame) / 1000);
  lastFrame = now;
  if (current && current.alive && !lookingNow && $("#reveal").hidden && !ghostHeld) {
    dialTheta += (netTheta(current) - dialTheta) * Math.min(1, dt * 5);
    placeDot(dialTheta);
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);
function placeDot(theta) {
  const R = orbitR(), x = R * Math.sin(theta), y = -R * Math.cos(theta);
  $("#ghost").style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
  const h = (Math.cos(theta) + 1) / 2; // 1 at the top, 0 at the bottom
  const alive = $("#ghost-alive"), dead = $("#ghost-dead");
  alive.style.filter = ""; alive.style.opacity = (0.15 + 0.6 * h).toFixed(2);
  dead.style.opacity = (0.15 + 0.6 * (1 - h)).toFixed(2);
}
function moveDot(target, ms = 1100) {
  if (dialAnim) cancelAnimationFrame(dialAnim);
  const from = dialTheta, start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / ms), e = 1 - Math.pow(1 - t, 3);
    dialTheta = from + (target - from) * e;
    placeDot(dialTheta);
    if (t < 1) dialAnim = requestAnimationFrame(step);
  };
  dialAnim = requestAnimationFrame(step);
}

/* plain language helpers */
const CARE = { feed: Math.PI / 4, play: Math.PI / 6 };
function oddsAlive(g) {
  // Same as app/quantum.py at this second. Reading it is not a measurement.
  return Math.cos(netTheta(g) / 2) ** 2;
}
let hintText = "", hintAt = 0;
function hint(text, keep = false) { $("#hint").textContent = text; if (!keep) { hintText = ""; hintAt = 0; } }
function sayHint(text) { hintText = text; hintAt = Date.now(); hint(text, true); }
/* a bound friend pressed Feed or Play: say so, once */
let friendPressAt = 0;
function friendPressed(g) {
  if (!g.bound_to || lookingNow) return null;
  const ev = [...g.history].reverse().find((e) => (e.event === "feed" || e.event === "play") && e.by_id && e.by_id !== g.id);
  if (!ev || ev.t <= friendPressAt || Date.now() / 1000 - ev.t > 20) return null;
  friendPressAt = ev.t;
  return `${ev.by} pressed ${ev.event === "feed" ? "Feed" : "Play"}: it turned for both of you.`;
}
/* steps from the top, on either side of the wheel; the sign says which side */
function stepsSigned(g) { return Math.round(netTheta(g) / Math.PI * 24); }
function stepsDown(g) { return Math.abs(stepsSigned(g)); }
/* The wheel turns one way for Feed and Play, the other way for the hours. Past the top (the far side) a press turns it away from the top. */
function age(g) {
  const h = (Date.now() / 1000 - g.created_at) / 3600;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${Math.floor(h)} h`;
  return `${Math.floor(h / 24)} days`;
}
function survived(g) { return g.alive ? g.looks : Math.max(0, g.looks - 1); }
function best(g) {
  let b = 0;
  try { b = Number(localStorage.getItem(KEY + ":best")) || 0; } catch { /* fine */ }
  const n = survived(g);
  if (n > b) { b = n; try { localStorage.setItem(KEY + ":best", String(b)); } catch { /* fine */ } }
  return b;
}
function looksText(n) { return `${n} look${n === 1 ? "" : "s"}`; }
function vitals(g) {
  return `age ${age(g)} · best ${looksText(best(g))}`;
}
function defaultHint(g, odds) {
  if (!g.alive) return `Gone. It lived ${age(g)} and survived ${looksText(survived(g))}. A Look is final. Hatch another.`;
  return "It never stops turning. Look when the alive ghost is brightest.";
}
function careHint(care, name) {
  return care === "feed" ? `${name} ate. That was a gate: a fixed turn.` : `${name} played. That was a gate: a smaller fixed turn.`;
}

/* physics toggle */
/* physics meters removed: the Look box "Show the physics" details handles transparency */

/* the 10-second play: watch it roll down, feed it up, look */
const SCENES = [
  { theta: Math.PI * 12 / 24, caption: "NAME is born half alive, half gone." },
  { theta: Math.PI * 8 / 24,  caption: "It never stops turning." },
  { theta: Math.PI * 2 / 24,  caption: "Press Feed or Play. NAME eats or plays, and that turns it a fixed amount." },
  { theta: -Math.PI * 4 / 24, caption: "In the game, drag the candle onto it. The heat turns it by an amount nobody knows." },
  { theta: 0,                 caption: "In the game, press Look when the alive ghost is brightest. The computer forces one answer: alive or gone.", look: true },
  { theta: 0,                 caption: "Alive, and it keeps going. Gone is final. Survive as many Looks as you can." },
]
let sceneAt = 0;
function placePlayGhost(theta) {
  const R = orbitR("#play-stage .orbit"), x = R * Math.sin(theta), y = -R * Math.cos(theta);
  const h = (Math.cos(theta) + 1) / 2;
  const w = $("#play-ghost");
  w.style.transition = "transform 0.9s cubic-bezier(.3,1,.4,1)";
  w.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)`;
  const el = $("#play-ghost-svg");
  el.style.transition = "opacity 0.9s, filter 0.9s";
  el.style.opacity = (0.08 + 0.92 * h).toFixed(2);
  el.style.filter = `grayscale(${(1 - h).toFixed(2)}) blur(${((1 - h) * 2).toFixed(1)}px)`;
}
function showScene(i) {
  sceneAt = i;
  const sc = SCENES[i];
  placePlayGhost(sc.theta);
  $("#play-caption").textContent = sc.caption.replace("NAME", current ? current.name : "Your ghost"); // the ghost's own name
  $("#play-next").textContent = i === SCENES.length - 1 ? "Your turn" : (sc.look ? "Look" : "Next");
}
function showIntro() {
  $("#play-ghost-svg").innerHTML = ghostSvg;
  $("#intro").hidden = false;
  showScene(0);
}
function closeIntro() {
  $("#intro").hidden = true;
  try { localStorage.setItem(KEY + ":intro", "1"); } catch { /* fine */ }
}
$("#play-next").addEventListener("click", () => {
  if (sceneAt < SCENES.length - 1) return showScene(sceneAt + 1);
  closeIntro();
});
$("#play-skip").addEventListener("click", closeIntro);
$("#intro-again").addEventListener("click", showIntro);
function maybeIntro() {
  let seen = false;
  try { seen = localStorage.getItem(KEY + ":intro") === "1"; } catch { /* fine */ }
  if (!seen) showIntro();
}

/* hatch */
$("#hatch-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const btn = $("#hatch-form button[type=submit]");
  btn.disabled = true;
  btn.textContent = "Hatching…";
  try {
    const name = $("#name").value.trim() || "Kiro";
    const g = await api("/api/ghosts", { method: "POST", body: JSON.stringify({ name }) });
    me = { id: g.id, secret: g.secret };
    save(me);
    render(g);
    maybeIntro();
  } catch (e) {
    toast(e.message || "Something went wrong. Try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Hatch";
  }
});
$("#hatch-again").addEventListener("click", () => { me = null; save(null); setScreen("hatch"); $("#name").value = ""; });

/* care */
$("#actions").addEventListener("click", async (ev) => {
  const care = ev.target.closest("[data-care]")?.dataset.care;
  if (!care) return;
  try {
    const before = current ? oddsAlive(current) : 1;
    const beforeSteps = current ? stepsSigned(current) : 0;
    const g = await api(`/api/ghosts/${me.id}/care/${care}`, { method: "POST" });
    render(g);
    sayHint(careHint(care, g.name));
    nudge(care);
  } catch (e) { toast(e.message); }
});

/* bind */
$("#bind-btn").addEventListener("click", () => { $("#bind-form").hidden = false; $("#bind-id").focus(); });
$("#bind-cancel").addEventListener("click", () => { $("#bind-form").hidden = true; });
$("#bind-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  try {
    const g = await api(`/api/ghosts/${me.id}/bind`, { method: "POST", body: JSON.stringify({ other_id: $("#bind-id").value.trim() }) });
    render(g);
    $("#bind-form").hidden = true;
    sayHint(`Bound to ${g.bound_name}. A press from either of you turns it.`);
    toast(`Bound to ${g.bound_name}. One answer for both.`);
  } catch (e) { $("#bind-form").hidden = true; toast(e.message, 6000); }
});

/* look: the measurement */
$("#look-btn").addEventListener("click", async () => {
  const btn = $("#look-btn");
  btn.disabled = true;
  lookingNow = true;
  lookBefore = current ? {
    steps: stepsDown(current), net: stepsSigned(current),
    birth: Math.round((current.birth_angle || 0) / Math.PI * 24),
    hunger: 0, // no hours any more
    feeds: current.care_gates.filter((c) => c === "feed").length,
    plays: current.care_gates.filter((c) => c === "play").length,
    fires: current.care_gates.filter((c) => c.startsWith("fire:")).length,
    days: 0, bumped: 0,
  } : null;
  const wrap = $("#ghost");
  wrap.classList.add("collapsing");
  try {
    const [res] = await Promise.all([
      api(`/api/ghosts/${me.id}/look`, { method: "POST" }),
      new Promise((r) => setTimeout(r, 950)),
    ]);
    wrap.classList.remove("superposed", "collapsing");
    wrap.classList.add(res.alive ? "alive-collapsed" : "dead-collapsed");
    // the read: the dot can only go to the top or the bottom
    moveDot(res.alive ? 0 : (dialTheta < 0 ? -Math.PI : Math.PI), 600); // the short way: down the side it is on
    showReveal(res);
    // After the reveal closes, re-render. If alive the ghost goes back to superposition:
    // closing the box means nobody is looking again.
    $("#reveal-close").onclick = () => { $("#reveal").hidden = true; render(res); };
  } catch (e) {
    wrap.classList.remove("collapsing");
    toast(e.message);
  } finally {
    btn.disabled = false;
    lookingNow = false;
  }
});

function showReveal(res) {
  hintText = ""; hintAt = 0;  // a look ends the story of the last press
  const pct = Math.round(res.odds_alive_before * 100);
  $("#reveal-title").textContent = res.by ? `${res.by} looked. ${res.name} is ${res.alive ? "alive" : "gone"}.` : res.alive ? `${res.name} is alive.` : `${res.name} is gone.`;
  $("#reveal-why").innerHTML = revealWhy(res, pct).map((v) => `<div><dd>${v}</dd></div>`).join("");
  $("#reveal-circuit").textContent = drawCircuit(res);
  $("#key-x").innerHTML = res.boxes && !res.boxes.includes("H")
    ? "<strong>X</strong> makes it alive. After a Look that finds it alive, it starts again fully alive."
    : "<strong>X</strong> makes it alive. <strong>H</strong>, the Hadamard gate, then makes it half alive, half gone. Together they are the birth.";
  $("#reveal-bits").textContent = res.bitstring;
  $("#reveal").hidden = false;
}
/* Three lines: what moved it, what the Look did, what now. */
function revealWhy(res, pct) {
  const p = res.odds_alive_before;
  const partner = res.bound_outcome ? escapeHtml(res.bound_outcome.name) : null;
  const who = res.by ? escapeHtml(res.by) : null;
  const out = [];
  // 1. what moved it since the last Look
  if (!who && lookBefore) {
    const n = (k, one, many) => `${k} ${k === 1 ? one : many}`;
    const presses = [lookBefore.feeds ? n(lookBefore.feeds, "Feed", "Feeds") : "", lookBefore.plays ? n(lookBefore.plays, "Play", "Plays") : ""].filter(Boolean).join(" and ");
    let s = res.looks === 1 ? "Since it hatched it kept turning on its own." : "Since your last Look it kept turning on its own.";
    const one = lookBefore.feeds + lookBefore.plays === 1;
    if (presses) s += one ? ` Your ${presses} is a <strong>gate</strong>: a fixed turn.` : ` Your ${presses} are <strong>gates</strong>: each one a fixed turn.`;
    if (lookBefore.fires) s += " The candle's heat turned it by an amount nobody knows. That is <strong>decoherence</strong>.";
    out.push(s);
  } else if (who) {
    out.push(`Your ghost and ${who}'s shared one answer.`);
  }
  // 2. what the Look did
  const lead = who ? `${who} pressed Look.` : "You looked.";
  let line = `${lead} That is a <strong>measurement</strong>: it forces the ghost to be just one, alive or gone. It came out <strong>${res.alive ? "alive" : "gone"}</strong>.`;
  if (partner && !who) line += ` One answer for both: ${partner}'s ghost came out the same, on ${partner}'s screen.`;
  out.push(line);
  // 3. what now
  const bond = (who || partner) ? " The bond is used up: a look ends it." : "";
  out.push((res.alive ? "Now it is fully alive and keeps turning." : "Gone is final.") + bond);
  return out;
}
/* the real circuit, with what each box was written under it */
const BOX_WORDS = {
  start: ["start", "fully alive"], spin: ["turned on", "its own"],
  feed: ["your Feed"], play: ["your Play"], candle: ["the candle's", "heat"],
  hunger: ["hunger"], noise: ["noise"],
};
function drawCircuit(res) {
  const raw = res.circuit || "";
  const all = raw.split("\n");
  const boxes = res.boxes;
  // a bound pair has two lines; that one is shown as Braket prints it
  if (!boxes || all.some((l) => l.startsWith("q1"))) return raw;
  // a long circuit is printed in wrapped blocks; join them back into one line
  const qs = all.map((l, k) => (l.startsWith("q0 :") ? k : -1)).filter((k) => k >= 2);
  if (!qs.length) return raw;
  const strip = (l) => l.replace(/[ ╏┃]+$/, "");
  const lines = ["", "", "", ""];
  qs.forEach((qi, b) => {
    const blk = [all[qi - 2], all[qi - 1], all[qi], all[qi + 1]].map((l) => strip(l || ""));
    // later blocks drop their "T  : " / "q0 : " start so the boxes continue the first line
    lines[0] += b ? blk[0].slice(6) : blk[0];
    lines[1] += b ? blk[1].slice(5) : blk[1];
    lines[2] += b ? blk[2].slice(6) : blk[2];
    lines[3] += b ? blk[3].slice(5) : blk[3];
  });
  const q = 2;
  const mid = lines[q];
  const centers = [];
  for (let i = 0; i < mid.length; i++) {
    if (mid[i] !== "┤") continue;
    const j = mid.indexOf("├", i);
    if (j < 0) break;
    centers.push(Math.floor((i + j) / 2));
    i = j;
  }
  if (centers.length !== boxes.length) return raw;
  const width = mid.length + 20;
  const rows = [0, 1, 2, 3].map(() => Array(width).fill(" "));
  const ends = [0, 6, 6, 6]; // per row: first free column; labels never overlap "your ghost" or each other
  const put = (r, col, txt) => {
    const st = Math.max(ends[r], col - Math.floor(txt.length / 2));
    for (let k = 0; k < txt.length && st + k < width; k++) rows[r][st + k] = txt[k];
    ends[r] = st + txt.length + 1;
  };
  rows[0][0] = "│";
  "your".split("").forEach((c, k) => { rows[1][k] = c; });
  "ghost".split("").forEach((c, k) => { rows[2][k] = c; });
  for (let i = 0; i < boxes.length; i++) {
    if (boxes[i] === "X" && boxes[i + 1] === "H") {
      const a = centers[i], b = centers[i + 1], m = Math.floor((a + b) / 2);
      for (let c = a; c <= b; c++) rows[0][c] = "─";
      rows[0][a] = "└"; rows[0][b] = "┘"; rows[0][m] = "┬";
      ["born", "half alive", "half gone"].forEach((t, k) => put(k + 1, m, t));
      i += 1;
      continue;
    }
    const words = boxes[i] === "X" ? ["start", "alive"] : (BOX_WORDS[boxes[i]] || [boxes[i]]);
    rows[0][centers[i]] = "│";
    words.forEach((t, k) => put(k + 1, centers[i], t));
  }
  return [lines[q - 2] + "   ← step number", lines[q - 1], mid + "▶ your Look", lines[q + 1], ...rows.map((r) => r.join("").replace(/\s+$/, ""))]
    .filter((l, k) => k < 4 || l.length).join("\n");
}
function escapeHtml(s) { return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]); }

/* small feedback: Feed drops a hamburger that falls through the ghost, Play makes it play */
const BURGER_SVG = `<svg viewBox="0 0 44 36" aria-hidden="true">
  <path d="M4 16C4 5 40 5 40 16Z" fill="#d9963b"/>
  <ellipse cx="14" cy="10" rx="1.6" ry="1" fill="#f6e7c1"/><ellipse cx="22" cy="8" rx="1.6" ry="1" fill="#f6e7c1"/><ellipse cx="30" cy="10" rx="1.6" ry="1" fill="#f6e7c1"/>
  <path d="M3 17Q8 21 13 17T23 17T33 17T41 17L41 20L3 20Z" fill="#6cc24a"/>
  <rect x="5" y="19.5" width="34" height="3" fill="#f5c542"/>
  <rect x="4" y="22" width="36" height="6" rx="3" fill="#6b3a1f"/>
  <rect x="5" y="28" width="34" height="6" rx="3" fill="#d9963b"/>
</svg>`;
/* the ghost pulls out a hamburger, chews once, twice, and the chewed bits fall through it */
function eatBurger() {
  const stage = $("#stage"), ghost = $("#ghost");
  const b = document.createElement("div");
  b.className = "burger";
  b.innerHTML = BURGER_SVG;
  b.style.left = "37px"; b.style.top = "46px"; // at the mouth, below the eyes
  ghost.appendChild(b);
  b.animate(
    [{ transform: "translate(-40px, 20px) scale(0.2)", opacity: 0 }, { transform: "translate(0, 0) scale(1)", opacity: 1 }],
    { duration: 400, easing: "cubic-bezier(.3,1.4,.5,1)", fill: "forwards" }
  );
  const chew = (at, size) => setTimeout(() => {
    b.animate([{ transform: `scale(${size + 0.25})` }, { transform: `scale(${size}) translateY(2px)` }], { duration: 250, easing: "ease-out", fill: "forwards" });
    for (const id of ["ghost-alive", "ghost-dead", "ghost-solid"]) {
      document.getElementById(id).animate([{ transform: "scale(1, 1)" }, { transform: "scale(1.06, 0.9)" }, { transform: "scale(1, 1)" }], { duration: 300, easing: "ease-in-out" });
    }
  }, at);
  chew(500, 0.72);
  chew(950, 0.45);
  setTimeout(() => {
    const s = stage.getBoundingClientRect(), r = b.getBoundingClientRect();
    const x0 = r.left - s.left + r.width / 2, y0 = r.top - s.top + r.height / 2;
    b.remove();
    ["#d9963b", "#6b3a1f", "#6cc24a", "#f5c542", "#d9963b", "#6b3a1f"].forEach((color, i) => {
      const p = document.createElement("div");
      p.className = "crumb";
      p.style.background = color;
      p.style.left = (x0 - 4).toFixed(1) + "px";
      p.style.top = (y0 - 3).toFixed(1) + "px";
      stage.appendChild(p);
      const dx = (i - 2.5) * 7 + (Math.random() * 8 - 4);
      const fall = p.animate(
        [{ transform: "translate(0, 0) rotate(0)" }, { transform: `translate(${dx.toFixed(1)}px, ${(s.height - y0 + 20).toFixed(0)}px) rotate(${(Math.random() * 540 - 270).toFixed(0)}deg)` }],
        { duration: 1100 + i * 60, easing: "cubic-bezier(.5,0,1,1)", fill: "forwards" }
      );
      fall.onfinish = () => p.remove();
    });
  }, 1400);
}
function playSpin() {
  const kf = [
    { transform: "translateY(0) rotate(0)" },
    { transform: "translateY(-26px) rotate(-20deg)", offset: 0.25 },
    { transform: "translateY(0) rotate(180deg) scale(1.05)", offset: 0.5 },
    { transform: "translateY(-18px) rotate(340deg)", offset: 0.75 },
    { transform: "translateY(0) rotate(360deg)" },
  ];
  for (const id of ["ghost-alive", "ghost-dead", "ghost-solid"]) document.getElementById(id).animate(kf, { duration: 1100, easing: "ease-in-out" });
}
function nudge(kind) {
  if (kind === "feed") eatBurger();
  else playSpin();
}
let toastTimer;
function toast(msg, ms = 2600) {
  let t = $("#toast");
  if (!t) { t = document.createElement("div"); t.id = "toast"; document.body.appendChild(t);
    Object.assign(t.style, { position: "fixed", left: "50%", bottom: "24px", transform: "translateX(-50%)", background: "#120b22", color: "#e9e2f7", border: "1px solid #9046ff", padding: "10px 14px", borderRadius: "10px", zIndex: 30, fontFamily: "inherit" }); }
  t.textContent = msg; t.style.opacity = 1;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.style.opacity = 0), ms);
}
$("#copy-code").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(me.id); toast("Copied"); } catch { toast(me.id); }
});

/* easter egg: type k i r o anywhere */
let typed = "";
document.addEventListener("keydown", (ev) => {
  if (ev.target.matches("input, textarea")) return;
  typed = (typed + ev.key.toLowerCase()).slice(-4);
  if (typed === "kiro") { typed = ""; swarm(); }
});
function swarm() {
  const host = $("#swarm");
  for (let i = 0; i < 14; i++) {
    const d = document.createElement("div");
    d.className = "mini";
    d.style.left = Math.random() * 100 + "vw";
    d.style.animationDelay = Math.random() * 1.2 + "s";
    d.innerHTML = ghostSvg;
    host.appendChild(d);
    setTimeout(() => d.remove(), 5000);
  }
  const wm = $("#wordmark");
  wm.hidden = false;
  wm.style.animation = "none";
  requestAnimationFrame(() => { wm.style.animation = ""; });
  setTimeout(() => (wm.hidden = true), 3000);
}

/* every 4 to 7 seconds Kiro looks straight at you for a moment, sometimes with a blink */
function glance() {
  if (current && current.alive && !lookingNow) {
    const blink = Math.random() < 0.4;
    const at = (x, closed) => `translateX(${x}px)${closed ? " scaleY(0.15)" : ""}`;
    const frames = (closed) => [
      { transform: at(0, closed) },
      { transform: at(-75, closed), offset: 0.2 },
      ...(blink && !closed ? [{ transform: "translateX(-75px) scaleY(0.1)", offset: 0.5 }] : []),
      { transform: at(-75, closed), offset: 0.8 },
      { transform: at(0, closed) },
    ];
    for (const eye of document.querySelectorAll("#ghost .eye")) {
      const closed = !!eye.closest(".copy.dead"); // the gone copy keeps its eyes shut
      eye.animate(frames(closed), { duration: 1600, easing: "ease-in-out" });
    }
  }
  setTimeout(glance, 4000 + Math.random() * 3000);
}
setTimeout(glance, 4000);

/* boot */
(async function boot() {
  ghostSvg = await (await fetch("/static/kiro-ghost.svg")).text();
  for (const id of ["ghost-alive", "ghost-dead", "ghost-solid"]) document.getElementById(id).innerHTML = ghostSvg;

  await refresh();
  if (me?.id) maybeIntro();
  // poll every few seconds: a friend may bind to us, or look, at any moment
  // only poll if we're bound; an unbound ghost can't be changed by anyone else
  setInterval(() => { if (me?.id && current?.alive && current?.bound_to && $("#reveal").hidden && !lookingNow) refresh(); }, 6_000);
})();

/* learn panels: game stays centred, explanations open on demand */
(function () {
  const backdrop = document.getElementById("panel-backdrop");
  const open = (id) => {
    const panel = document.getElementById(id);
    if (!panel) return;
    for (const el of document.querySelectorAll(".panel")) el.hidden = el.id !== id;
    panel.hidden = false; backdrop.hidden = false; panel.scrollTop = 0;
  };
  const closeAll = () => {
    for (const el of document.querySelectorAll(".panel")) el.hidden = true;
    backdrop.hidden = true;
  };
  document.addEventListener("click", (ev) => {
    const o = ev.target.closest("[data-open]");
    if (o) { open(o.getAttribute("data-open")); return; }
    if (ev.target.closest("[data-close]") || ev.target === backdrop) closeAll();
  });
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") closeAll(); });
})();

/* ===== touch: the ghost springs back (you can't set a qubit by hand), the candle drags freely ===== */
(function () {
  const stage = document.getElementById("stage");
  const ghost = document.getElementById("ghost");
  const candle = document.querySelector(".candle");

  // --- ghost: grab, wobble, spring back to its real (physics) spot ---
  if (ghost) {
    let dragging = false, sx = 0, sy = 0;
    const baseXY = () => {
      const R = orbitR(), x = R * Math.sin(dialTheta), y = -R * Math.cos(dialTheta);
      return [x, y];
    };
    ghost.addEventListener("pointerdown", (e) => {
      if (!current || !current.alive) return;      // no grabbing a departed ghost
      if (typeof dialAnim !== "undefined" && dialAnim) cancelAnimationFrame(dialAnim);
      dragging = true; ghostHeld = true; sx = e.clientX; sy = e.clientY;
      ghost.setPointerCapture(e.pointerId);
      ghost.classList.add("grabbed");
      ghost.style.transition = "none";
      e.preventDefault();
    });
    ghost.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const [bx, by] = baseXY();
      const dx = e.clientX - sx, dy = e.clientY - sy;
      // a little resistance so it feels springy, not a free drag
      ghost.style.transform = `translate(${(bx + dx * 0.8).toFixed(1)}px, ${(by + dy * 0.8).toFixed(1)}px)`;
    });
    const release = () => {
      if (!dragging) return;
      dragging = false;
      ghost.classList.remove("grabbed");
      const [bx, by] = baseXY();
      ghost.style.transition = "transform 0.7s cubic-bezier(.2,1.5,.35,1)"; // bouncy snap back
      ghost.style.transform = `translate(${bx.toFixed(1)}px, ${by.toFixed(1)}px)`;
      setTimeout(() => { ghost.style.transition = ""; ghostHeld = false; }, 720);
    };
    ghost.addEventListener("pointerup", release);
    ghost.addEventListener("pointercancel", release);
  }

  // --- candle: free drag within the stage ---
  if (candle && stage) {
    let dragging = false, ox = 0, oy = 0;
    candle.addEventListener("pointerdown", (e) => {
      dragging = true;
      const r = candle.getBoundingClientRect(); ox = e.clientX - r.left; oy = e.clientY - r.top;
      candle.setPointerCapture(e.pointerId);
      // pin it where it stands before dropping right/bottom, so it never jumps to the corner
      const s = stage.getBoundingClientRect();
      candle.style.left = (r.left - s.left) + "px"; candle.style.top = (r.top - s.top) + "px";
      candle.style.right = "auto"; candle.style.bottom = "auto";
      candle.classList.add("grabbed");
      e.preventDefault();
    });
    candle.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const s = stage.getBoundingClientRect();
      let x = e.clientX - s.left - ox, y = e.clientY - s.top - oy;
      x = Math.max(0, Math.min(x, s.width - candle.offsetWidth));
      y = Math.max(0, Math.min(y, s.height - candle.offsetHeight));
      candle.style.left = x + "px"; candle.style.top = y + "px";
    });
    // the candle on the ghost sets it on fire for a few seconds, then the candle goes home
    let burning = false;
    const touchesGhost = () => {
      const a = candle.getBoundingClientRect(), b = ghost.getBoundingClientRect();
      return a.left < b.right && a.right > b.left && a.top - 22 < b.bottom && a.bottom > b.top;
    };
    const returnCandle = () => {
      const s = stage.getBoundingClientRect();
      candle.style.transition = "left 0.7s ease, top 0.7s ease";
      candle.style.left = (s.width - 18 - candle.offsetWidth) + "px";
      candle.style.top = (s.height - 10 - candle.offsetHeight) + "px";
      setTimeout(() => { for (const p of ["transition", "left", "top", "right", "bottom"]) candle.style[p] = ""; }, 720);
    };
    // Kiro burns for 3 seconds: its body glows with fire and sparks rise off it, then it fades back to white
    const ignite = () => {
      burning = true;
      ghost.classList.add("on-fire");
      // the fire turns the ring by an unknown amount: the server draws it and keeps it
      api(`/api/ghosts/${me.id}/care/fire`, { method: "POST" }).then((g) => render(g)).catch((e) => toast(e.message));
      const sparks = document.createElement("div");
      sparks.className = "sparks";
      ghost.appendChild(sparks);
      const spawn = setInterval(() => {
        for (let k = 0; k < 2; k++) {
          const sp = document.createElement("div");
          sp.className = "spark";
          const size = 10 + Math.random() * 12;
          sp.style.width = sp.style.height = size.toFixed(0) + "px";
          sp.style.left = (12 + Math.random() * 70).toFixed(0) + "%";
          sp.style.top = (25 + Math.random() * 65).toFixed(0) + "%";
          sparks.appendChild(sp);
          const rise = sp.animate(
            [
              { transform: "translate(0, 0) scale(1)", backgroundColor: "#fff3a0", opacity: 1 },
              { backgroundColor: "#ffb020", opacity: 0.95, offset: 0.35 },
              { backgroundColor: "#ff5a1a", opacity: 0.7, offset: 0.7 },
              { transform: `translate(${(Math.random() * 16 - 8).toFixed(0)}px, -${(60 + Math.random() * 50).toFixed(0)}px) scale(0.2)`, backgroundColor: "#c81e0a", opacity: 0 },
            ],
            { duration: 600 + Math.random() * 400, easing: "ease-out", fill: "forwards" }
          );
          rise.onfinish = () => sp.remove();
        }
      }, 30);
      setTimeout(() => {
        clearInterval(spawn);
        setTimeout(() => sparks.remove(), 1000);
        ghost.classList.remove("on-fire");
        // a little smoke when the fire is gone
        for (const left of [30, 48, 62, 75]) {
          const puff = document.createElement("div");
          puff.className = "smoke";
          puff.style.left = left + "%";
          ghost.appendChild(puff);
          const rise = puff.animate(
            [{ transform: "translateY(0) scale(0.6)", opacity: 0.7 }, { transform: "translateY(-55px) scale(2)", opacity: 0 }],
            { duration: 800 + left * 3, delay: (left % 3) * 80, easing: "ease-out", fill: "both" }
          );
          rise.onfinish = () => puff.remove();
        }
        for (const id of ["ghost-alive", "ghost-dead", "ghost-solid"]) {
          document.getElementById(id).animate(
            [{ filter: "sepia(1) saturate(5) hue-rotate(-25deg) brightness(1.2)" }, { filter: "none" }],
            { duration: 600, easing: "ease-out" }
          );
        }
        returnCandle();
        burning = false;
      }, 3000);
    };
    const drop = () => {
      if (!dragging) return;
      dragging = false;
      candle.classList.remove("grabbed");
      if (!burning && ghost && current && current.alive && touchesGhost()) ignite();
    };
    candle.addEventListener("pointerup", drop);
    candle.addEventListener("pointercancel", drop);
  }
})();
