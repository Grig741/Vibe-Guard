"use strict";

const $ = (sel) => document.querySelector(sel);

const els = {
  config: $("#configInput"),
  label: $("#labelInput"),
  collections: $("#collectionsInput"),
  parseStatus: $("#parseStatus"),
  modeTabs: $("#modeTabs"),
  inputLabel: $("#inputLabel"),
  inputHint: $("#inputHint"),
  scanBtn: $("#scanBtn"),
  reportEmpty: $("#reportEmpty"),
  reportContent: $("#reportContent"),
  historyList: $("#historyList"),
  refreshHistory: $("#refreshHistory"),
  healthBadge: $("#healthBadge"),
  proStatus: $("#proStatus"),
};

const SEV_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low", pass: "Passed", info: "Info" };
const GRADE_COLOR = { A: "var(--pass)", B: "var(--pass)", C: "var(--med)", D: "var(--high)", F: "var(--crit)" };

let pricing = { price: "$9", payment_url: null };
let currentScan = null;
let mode = "url"; // "url" | "config"

const URL_RE = /^(https?:\/\/)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(:\d{2,5})?([/?#]\S*)?$/i;

/* ---------- Safe localStorage ---------- */

const store = {
  get(k, fallback) {
    try { const v = localStorage.getItem(k); return v == null ? fallback : JSON.parse(v); }
    catch (_) { return fallback; }
  },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
  del(k) { try { localStorage.removeItem(k); } catch (_) {} },
};

function getKey() { return store.get("vg_license", null); }
function setKey(k) { k ? store.set("vg_license", k) : store.del("vg_license"); renderProStatus(); }
function getHistoryIds() { return store.get("vg_scans", []); }
function addHistoryId(id) {
  const ids = getHistoryIds().filter((x) => x !== id);
  ids.unshift(id);
  store.set("vg_scans", ids.slice(0, 30));
}
function removeHistoryId(id) { store.set("vg_scans", getHistoryIds().filter((x) => x !== id)); }

/* ---------- Firebase config parsing ---------- */

function parseFirebaseConfig(raw) {
  if (!raw || !raw.trim()) return { error: "Config is empty." };
  const start = raw.indexOf("{");
  const end = raw.lastIndexOf("}");
  if (start === -1 || end === -1 || end < start) return { error: "No { … } object found." };
  const body = raw.slice(start, end + 1);

  try { return { config: JSON.parse(body) }; } catch (_) { /* fall through */ }

  try {
    const s = body
      .replace(/\/\/[^\n\r]*/g, "")
      .replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":')
      .replace(/'/g, '"')
      .replace(/,(\s*[}\]])/g, "$1");
    return { config: JSON.parse(s) };
  } catch (e) {
    return { error: "Couldn't parse the config object." };
  }
}

// Returns what will be scanned: { kind:"url", url } | { kind:"config", config } | null
function refreshParseStatus() {
  const raw = els.config.value.trim();
  if (!raw) { els.parseStatus.textContent = ""; els.parseStatus.className = "parse-status"; return null; }

  // A single URL-looking token → URL scan (unless it clearly is a config object).
  const firstTok = raw.split(/\s+/)[0];
  const hasObject = raw.includes("{");
  const looksUrl = !hasObject && (URL_RE.test(firstTok) || /^https?:\/\/\S+$/i.test(firstTok));
  // In URL mode, accept any single non-config token and let the server (which
  // SSRF-validates) have the final say — don't block real hosts on a regex.
  if (!hasObject && (looksUrl || (mode === "url" && raw.split(/\s+/).length === 1))) {
    els.parseStatus.textContent = "✓ will scan " + firstTok.replace(/^https?:\/\//, "");
    els.parseStatus.className = "parse-status ok";
    return { kind: "url", url: firstTok };
  }

  const { config } = parseFirebaseConfig(raw);
  if (config && config.projectId) {
    const bits = ["projectId"];
    if (config.apiKey) bits.push("apiKey");
    if (config.databaseURL) bits.push("databaseURL");
    if (config.storageBucket) bits.push("storageBucket");
    els.parseStatus.textContent = "✓ parsed — " + config.projectId + " (" + bits.join(", ") + ")";
    els.parseStatus.className = "parse-status ok";
    return { kind: "config", config };
  }

  // Supabase URL + key pasted?
  if (/supabase\.(co|in)/.test(raw) && /eyJ[\w-]+\.eyJ[\w-]+/.test(raw)) {
    els.parseStatus.textContent = "✓ Supabase project detected";
    els.parseStatus.className = "parse-status ok";
    return { kind: "raw", raw };
  }

  els.parseStatus.textContent = mode === "url"
    ? "✗ That doesn't look like a URL. Switch to “Paste config” to paste a firebaseConfig."
    : "✗ Couldn't find a projectId or Supabase key.";
  els.parseStatus.className = "parse-status err";
  return null;
}

function setMode(m) {
  mode = m;
  els.modeTabs.querySelectorAll(".mode-tab").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
  if (m === "url") {
    els.inputLabel.firstChild.textContent = "Website URL ";
    els.inputHint.textContent = "the live address of your app";
    els.config.placeholder = "https://my-app.netlify.app";
  } else {
    els.inputLabel.firstChild.textContent = "Firebase / Supabase config ";
    els.inputHint.textContent = "paste it straight from your app";
    els.config.placeholder = 'const firebaseConfig = {\n  apiKey: "AIza...",\n  projectId: "my-app",\n  storageBucket: "my-app.appspot.com"\n};\n\n— or —\ncreateClient("https://xxxx.supabase.co", "eyJ...anon key...")';
  }
  refreshParseStatus();
}

els.modeTabs.querySelectorAll(".mode-tab").forEach((b) =>
  b.addEventListener("click", () => setMode(b.dataset.mode)));
els.config.addEventListener("input", refreshParseStatus);

/* ---------- API ---------- */

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/* ---------- Scan ---------- */

els.scanBtn.addEventListener("click", runScan);

function buildBody() {
  const target = refreshParseStatus();
  if (!target) return null;
  const collections = els.collections.value.split(",").map((c) => c.trim()).filter(Boolean);
  const label = els.label.value.trim() || null;
  const base = { collections, label };
  if (target.kind === "config") base.config = target.config;
  else if (target.kind === "url") base.target = target.url;
  else base.target = target.raw;
  return base;
}

async function runScan() {
  const body = buildBody();
  if (!body) { toast("Enter a URL or paste a config first.", true); return; }
  const license_key = getKey();

  setLoading(true);
  try {
    let scan;
    try {
      scan = await api("/api/scan", {
        method: "POST",
        body: JSON.stringify({ ...body, license_key }),
      });
    } catch (e) {
      // Saved key is dead/empty → fall back to a free scan instead of failing.
      if (license_key && (e.status === 402 || e.status === 403)) {
        toast(e.status === 402 ? "Your key has no scans left — running a free scan." : "Saved key is invalid — running a free scan.", true);
        setKey(null);
        scan = await api("/api/scan", { method: "POST", body: JSON.stringify(body) });
      } else throw e;
    }
    addHistoryId(scan.id);
    renderReport(scan);
    loadHistory();
    renderProStatus();
  } catch (e) {
    toast("Scan failed: " + e.message, true);
  } finally {
    setLoading(false);
  }
}

function setLoading(on) {
  els.scanBtn.classList.toggle("loading", on);
  els.scanBtn.disabled = on;
  els.scanBtn.querySelector(".btn-label").textContent = on ? "Scanning…" : "Run security scan";
}

/* ---------- Unlock ---------- */

async function unlock(key) {
  key = (key || "").trim().toUpperCase();
  if (!key) { toast("Enter your license key.", true); return; }
  if (!currentScan) return;
  try {
    const scan = await api(`/api/scans/${currentScan.id}/unlock`, {
      method: "POST",
      body: JSON.stringify({ license_key: key }),
    });
    setKey(key);
    renderReport(scan);
    loadHistory();
    toast("Full report unlocked.");
  } catch (e) {
    toast(e.message, true);
  }
}

/* ---------- Render report ---------- */

function verdictText(s) {
  if (s.critical > 0) return "Critical exposure — your data can be read or modified by anyone.";
  if (s.high > 0) return "Serious gaps found. Unauthenticated access is possible.";
  if (s.medium > 0) return "Mostly solid, with a few weak spots worth tightening.";
  if (s.low > 0) return "Looking good — only minor hardening left.";
  return "No exposures detected across the checks that ran. Nicely locked down.";
}

function reportHeader(s) {
  const R = 65, C = 2 * Math.PI * R;
  const color = GRADE_COLOR[s.grade] || "var(--info)";
  const created = new Date(s.created_at).toLocaleString();
  return `
    <div class="report-top">
      <div class="gauge">
        <svg width="150" height="150" viewBox="0 0 150 150">
          <circle class="gauge-track" cx="75" cy="75" r="${R}"></circle>
          <circle class="gauge-fill" cx="75" cy="75" r="${R}" data-offset="${C * (1 - s.score / 100)}"
            stroke="${color}" stroke-dasharray="${C}" stroke-dashoffset="${C}"></circle>
        </svg>
        <div class="gauge-center">
          <div class="gauge-grade" style="color:${color}">${s.grade}</div>
          <div class="gauge-score">${s.score}/100</div>
        </div>
      </div>
      <div class="report-head">
        <div class="project">${esc(s.project_id)}</div>
        <h2>${esc(s.target_label || "Security report")}</h2>
        <div class="verdict">${verdictText(s)}</div>
        ${(s.stack && s.stack.length) ? `<div class="stack-row">${s.stack.map((t) => `<span class="stack-badge">${esc(t)}</span>`).join("")}</div>` : ""}
        <div class="report-meta">
          <span>${s.duration_ms} ms</span>
          <span>${created}</span>
          <span>${s.locked ? "free report" : "full report"}</span>
        </div>
      </div>
    </div>
    <div class="sev-row">
      ${sevPill("crit", s.critical, "Critical")}
      ${sevPill("high", s.high, "High")}
      ${sevPill("med", s.medium, "Medium")}
      ${sevPill("low", s.low, "Low")}
      ${sevPill("pass", s.passed, "Passed")}
    </div>`;
}

function renderReport(s) {
  currentScan = s;
  els.reportEmpty.hidden = true;
  els.reportContent.hidden = false;
  els.reportContent.innerHTML = reportHeader(s) + (s.locked ? lockedBody(s) : fullBody(s));

  requestAnimationFrame(() => {
    const fill = els.reportContent.querySelector(".gauge-fill");
    if (fill) fill.style.strokeDashoffset = fill.dataset.offset;
  });

  if (s.locked) bindLocked(s); else bindFull(s);
  els.reportContent.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* Locked (free) view: count only + paywall */
function lockedBody(s) {
  const n = s.issues;
  const cls = s.critical || s.high ? "bad" : n ? "warn" : "good";
  const word = n === 1 ? "security hole" : "security holes";

  if (n === 0) {
    return `
      <div class="lock-hero">
        <div class="lock-count good">0</div>
        <div class="lock-label">No security holes found</div>
        <div class="lock-sub">Every check that ran came back clean.</div>
      </div>`;
  }

  // Placeholder cards — real titles never reach the browser while locked.
  const sevs = [];
  ["critical", "high", "medium", "low"].forEach((k) => { for (let i = 0; i < s[k]; i++) sevs.push(k); });
  const fakes = sevs.slice(0, 4).map((sev, i) => `
    <div class="finding sev-${sev}">
      <div class="finding-head">
        <span class="badge ${sev}">${SEV_LABEL[sev]}</span>
        <span class="finding-title"><span class="fake-line" style="width:${[62, 48, 70, 55][i]}%"></span></span>
      </div>
    </div>`).join("");

  const m = pricing.methods || {};
  const buy = (m.manual || m.crypto || m.link)
    ? `<button class="buy-btn" id="buyBtn" type="button" style="border:0;cursor:pointer;font-family:inherit">Get full report — $${esc(pricing.price_usd || "9")}</button>
       <div class="or-line">card, bank transfer or crypto · already have a key?</div>`
    : "";

  return `
    <div class="lock-hero">
      <div class="lock-count ${cls}">${n}</div>
      <div class="lock-label">${word} found in your project</div>
      <div class="lock-sub">Details and fixes are in the full report.</div>
    </div>
    <div class="blurred">${fakes}</div>
    <div class="unlock-box">
      <h3>See every hole and how to close it</h3>
      <p>The full report shows exactly what's exposed and gives copy-paste fixes for your Firebase rules.</p>
      <ul class="unlock-perks">
        <li>What each hole is and what an attacker can do with it</li>
        <li>Proof from the scan (the exact request that got through)</li>
        <li>Step-by-step fix with ready-to-paste security rules</li>
        <li>Unlimited re-scans to confirm the fix — within your key's limit</li>
      </ul>
      ${buy}
      <div class="key-row">
        <input id="keyInput" type="text" placeholder="VG-XXXX-XXXX-XXXX" autocomplete="off" />
        <button class="ghost-btn" id="unlockBtn">Unlock</button>
      </div>
    </div>`;
}

function payCtx() {
  return {
    api, toast, inTG: false,
    onHaveKey: () => { const i = $("#keyInput"); if (i) { i.focus(); i.scrollIntoView({ block: "center" }); } },
    async onPaid(scanId, key) {
      if (key) setKey(key);
      addHistoryId(scanId);
      try { renderReport(await api("/api/scans/" + scanId)); } catch (_) {}
      loadHistory();
    },
  };
}

function bindLocked(s) {
  const buyBtn = $("#buyBtn");
  if (buyBtn) buyBtn.addEventListener("click", () => VGPay.open(s, payCtx()));
  const input = $("#keyInput");
  const btn = $("#unlockBtn");
  if (!input || !btn) return;
  const saved = getKey();
  if (saved) input.value = saved;
  btn.addEventListener("click", () => unlock(input.value));
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") unlock(input.value); });
}

/* Unlocked view: everything */
function fullBody(s) {
  const vulns = s.findings.filter((f) => f.status === "vulnerable");
  const passes = s.findings.filter((f) => f.status === "ok");
  const other = s.findings.filter((f) => f.status !== "vulnerable" && f.status !== "ok");
  return `
    <div class="findings">
      ${vulns.length ? `<div class="section-label">Issues to fix</div>` : ""}
      ${vulns.map(findingCard).join("")}
      ${passes.length ? `<div class="section-label">Passed checks</div>` : ""}
      ${passes.map(findingCard).join("")}
      ${other.length ? `<div class="section-label">Not determined</div>` : ""}
      ${other.map(findingCard).join("")}
    </div>
    <div class="report-actions">
      <button class="ghost-btn" id="copyJson">Copy JSON</button>
      <button class="ghost-btn" id="rescanBtn">Re-scan</button>
    </div>`;
}

function bindFull(s) {
  els.reportContent.querySelectorAll(".finding").forEach((card) => {
    if (card.classList.contains("no-detail")) return;
    card.querySelector(".finding-head").addEventListener("click", () => card.classList.toggle("open"));
  });
  // Open the most severe issue by default.
  const first = els.reportContent.querySelector(".finding:not(.no-detail):not(.sev-pass):not(.sev-info)");
  if (first) first.classList.add("open");

  $("#copyJson").addEventListener("click", () => {
    try { navigator.clipboard.writeText(JSON.stringify(s, null, 2)); toast("Report JSON copied."); }
    catch (_) { toast("Couldn't copy.", true); }
  });
  $("#rescanBtn").addEventListener("click", runScan);
}

function sevPill(cls, n, label) {
  return `<div class="sev-pill c-${cls}"><span class="n">${n}</span><span class="l">${label}</span></div>`;
}

function findingCard(f) {
  const hasDetail = f.status === "vulnerable" || (f.evidence && f.status !== "ok");
  const badge = SEV_LABEL[f.severity] || f.severity;
  const evidence = f.evidence ? `<div class="evidence">${esc(f.evidence)}</div>` : "";
  const desc = f.status === "vulnerable" && f.description ? `<p>${esc(f.description)}</p>` : "";
  const fix = f.status === "vulnerable" && f.remediation
    ? `<div class="fix-label">How to fix</div><pre>${esc(f.remediation)}</pre>` : "";
  const body = hasDetail ? `<div class="finding-body">${desc}${evidence}${fix}</div>` : "";
  return `
    <div class="finding sev-${f.severity}${hasDetail ? "" : " no-detail"}">
      <div class="finding-head">
        <span class="badge ${f.severity}">${badge}</span>
        <span class="finding-title">${esc(f.title)}</span>
        ${hasDetail ? `<span class="chevron">▶</span>` : ""}
      </div>
      ${body}
    </div>`;
}

/* ---------- Pro status ---------- */

async function renderProStatus() {
  const key = getKey();
  if (!key) { els.proStatus.hidden = true; return; }
  try {
    const st = await api("/api/license/" + encodeURIComponent(key));
    els.proStatus.hidden = false;
    els.proStatus.innerHTML = `<span><b>Pro</b> · <span class="key">${esc(key)}</span> · ${st.remaining} scans left</span>
      <button class="link-btn" id="forgetKey" title="Remove key">✕</button>`;
    $("#forgetKey").addEventListener("click", () => setKey(null));
  } catch (_) {
    setKey(null);
  }
}

/* ---------- History (this browser only) ---------- */

async function loadHistory() {
  const ids = getHistoryIds();
  if (!ids.length) { els.historyList.innerHTML = `<li class="empty">No scans yet.</li>`; return; }

  const scans = (await Promise.all(ids.map(async (id) => {
    try { return await api("/api/scans/" + id); }
    catch (e) { if (e.status === 404) removeHistoryId(id); return null; }
  }))).filter(Boolean);

  if (!scans.length) { els.historyList.innerHTML = `<li class="empty">No scans yet.</li>`; return; }

  els.historyList.innerHTML = scans.map((s) => {
    const color = GRADE_COLOR[s.grade] || "var(--info)";
    const name = s.target_label || s.project_id;
    const time = new Date(s.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
    return `<li class="hist-item" data-id="${s.id}">
      <span class="hist-grade" style="color:${color}">${s.grade}</span>
      <span class="hist-info">
        <span class="hist-name">${esc(name)}</span>
        <span class="hist-time">${s.issues} holes · ${s.locked ? "free" : "full"} · ${time}</span>
      </span>
      <span class="hist-del" data-del="${s.id}" title="Delete">✕</span>
    </li>`;
  }).join("");

  const byId = Object.fromEntries(scans.map((s) => [s.id, s]));
  els.historyList.querySelectorAll(".hist-item").forEach((li) => {
    li.addEventListener("click", (ev) => {
      if (ev.target.dataset.del) return;
      renderReport(byId[li.dataset.id]);
    });
  });
  els.historyList.querySelectorAll(".hist-del").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const id = btn.dataset.del;
      try { await api("/api/scans/" + id, { method: "DELETE" }); } catch (_) {}
      removeHistoryId(id);
      loadHistory();
    });
  });
}

els.refreshHistory.addEventListener("click", loadHistory);

/* ---------- Health & pricing ---------- */

async function boot() {
  try {
    const h = await api("/api/health");
    els.healthBadge.textContent = "v" + h.version + " · online";
    els.healthBadge.className = "health ok";
  } catch (_) {
    els.healthBadge.textContent = "offline";
    els.healthBadge.className = "health down";
  }
  try { pricing = await api("/api/pricing"); } catch (_) {}
  renderProStatus();
  loadHistory();
  // Back from CryptoBot (?order=…) or returning after a manual transfer was approved.
  let orderId = null;
  try { orderId = new URLSearchParams(location.search).get("order"); } catch (_) {}
  if (orderId) { try { history.replaceState(null, "", location.pathname); } catch (_) {} }
  VGPay.resume(payCtx(), orderId);
}

/* ---------- Utils ---------- */

function esc(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

let toastTimer;
function toast(msg, isErr = false) {
  let t = $(".toast");
  if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = "toast" + (isErr ? " err" : "");
  requestAnimationFrame(() => t.classList.add("show"));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 3200);
}

boot();
