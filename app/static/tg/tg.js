"use strict";

/* VibeGuard — Telegram Mini App.
 * Works inside Telegram (MainButton, BackButton, haptics, Stars payments) and
 * degrades gracefully in a normal browser (in-page button, license key, payment link).
 */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

  const tg = window.Telegram && window.Telegram.WebApp;
  const inTG = !!(tg && tg.initData);
  const ver = (v) => !!(tg && tg.isVersionAtLeast && tg.isVersionAtLeast(v));

  const SEV = { critical: "Critical", high: "High", medium: "Medium", low: "Low", pass: "Passed", info: "Info" };
  const GRADE = { A: "var(--ok)", B: "var(--ok)", C: "var(--med)", D: "var(--high)", F: "var(--crit)" };

  let pricing = { stars: 450, pack_scans: 10, price: "$9", payment_url: null };
  let me = null;           // /api/tg/me (inside Telegram)
  let current = null;      // scan on the result screen
  let tab = "scan";
  let mode = "url";
  const ICO = {
    shield: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z"/></svg>',
    ok: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z"/><path d="m8.5 12 2.4 2.4L16 9.3"/></svg>',
    lock: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    unlock: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.7-1.5"/></svg>',
    info: '<svg class="ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>',
    chev: '<svg class="chev ico" viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
  };
  const URL_RE = /^(https?:\/\/)?([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24}(:\d{2,5})?([/?#]\S*)?$/i;

  /* ---------------- Telegram setup ---------------- */
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      if (ver("6.1")) { tg.setHeaderColor("#06090f"); tg.setBackgroundColor("#06090f"); }
      if (ver("7.10") && tg.setBottomBarColor) tg.setBottomBarColor("#06090f");
      if (ver("7.7") && tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    } catch (_) {}
  }
  if (inTG) document.body.classList.add("tg-mode");

  const haptic = {
    tap() { try { inTG && tg.HapticFeedback.impactOccurred("light"); } catch (_) {} },
    soft() { try { inTG && tg.HapticFeedback.selectionChanged(); } catch (_) {} },
    ok() { try { inTG && tg.HapticFeedback.notificationOccurred("success"); } catch (_) {} },
    warn() { try { inTG && tg.HapticFeedback.notificationOccurred("warning"); } catch (_) {} },
    err() { try { inTG && tg.HapticFeedback.notificationOccurred("error"); } catch (_) {} },
  };

  /* ---------------- Storage ---------------- */
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (_) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (_) {} },
    del(k) { try { localStorage.removeItem(k); } catch (_) {} },
  };
  const getKey = () => store.get("vg_license", null);
  function setKey(k) {
    k ? store.set("vg_license", k) : store.del("vg_license");
    try { if (inTG && ver("6.9")) k ? tg.CloudStorage.setItem("vg_license", k) : tg.CloudStorage.removeItem("vg_license"); } catch (_) {}
  }
  const localIds = () => store.get("vg_scans", []);
  const addLocalId = (id) => store.set("vg_scans", [id, ...localIds().filter((x) => x !== id)].slice(0, 30));

  /* ---------------- API ---------------- */
  async function api(path, opts = {}) {
    const headers = { "Content-Type": "application/json" };
    if (inTG) headers["X-Telegram-Init-Data"] = tg.initData;
    const res = await fetch(path, { ...opts, headers });
    if (!res.ok) {
      let d = res.statusText;
      try { d = (await res.json()).detail || d; } catch (_) {}
      const e = new Error(d); e.status = res.status; throw e;
    }
    return res.json();
  }

  /* ---------------- Primary button (MainButton or in-page) ---------------- */
  const pageBtn = $("#pageBtn");
  const primary = {
    fn: null,
    set(text, fn, { stars = false } = {}) {
      this.fn = fn;
      if (inTG) {
        try {
          tg.MainButton.setParams({
            text, is_visible: true, is_active: true,
            color: stars ? "#2aabee" : "#5eead4", text_color: stars ? "#ffffff" : "#03121a",
          });
          tg.MainButton.hideProgress();
        } catch (_) {}
      } else {
        pageBtn.textContent = text;
        pageBtn.classList.toggle("stars", stars);
        pageBtn.hidden = false;
        pageBtn.disabled = false;
      }
    },
    hide() {
      this.fn = null;
      if (inTG) { try { tg.MainButton.hide(); } catch (_) {} } else pageBtn.hidden = true;
    },
    loading(on) {
      if (inTG) { try { on ? tg.MainButton.showProgress(false) : tg.MainButton.hideProgress(); } catch (_) {} }
      else { pageBtn.disabled = on; pageBtn.style.opacity = on ? .6 : 1; }
    },
  };
  const firePrimary = () => { if (primary.fn) { haptic.tap(); primary.fn(); } };
  if (inTG) tg.MainButton.onClick(firePrimary);
  pageBtn.addEventListener("click", firePrimary);

  /* ---------------- Back button ---------------- */
  let backFn = null;
  function setBack(fn) {
    backFn = fn;
    if (!inTG || !ver("6.1")) return;
    try { fn ? tg.BackButton.show() : tg.BackButton.hide(); } catch (_) {}
  }
  if (inTG && ver("6.1")) tg.BackButton.onClick(() => { if (backFn) { haptic.soft(); backFn(); } });

  /* ---------------- Screens & tabs ---------------- */
  function show(id) {
    $$(".screen").forEach((s) => s.classList.toggle("active", s.id === "scr-" + id));
    window.scrollTo(0, 0);
    $("#tabs").classList.toggle("hide", id === "scanning");
  }

  function goTab(name) {
    tab = name;
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    setBack(null);
    if (name === "scan") { show("scan"); primary.set("Run security scan", runScan); }
    if (name === "history") { show("history"); primary.hide(); loadHistory(); }
    if (name === "key") { show("key"); primary.hide(); renderKey(); }
  }
  $$(".tab").forEach((t) => t.addEventListener("click", () => { haptic.soft(); goTab(t.dataset.tab); }));

  /* ---------------- Config parsing ---------------- */
  function parseConfig(raw) {
    if (!raw || !raw.trim()) return { error: null };
    const a = raw.indexOf("{"), b = raw.lastIndexOf("}");
    if (a === -1 || b < a) return { error: "No { … } object found" };
    const body = raw.slice(a, b + 1);
    try { return { config: JSON.parse(body) }; } catch (_) {}
    try {
      return { config: JSON.parse(body
        .replace(/\/\/[^\n\r]*/g, "").replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/([{,]\s*)([A-Za-z_$][\w$]*)\s*:/g, '$1"$2":')
        .replace(/'/g, '"').replace(/,(\s*[}\]])/g, "$1")) };
    } catch (_) { return { error: "Couldn't parse the config" }; }
  }
  // → { kind:"url", url } | { kind:"config", config } | { kind:"raw", raw } | null
  function checkConfig() {
    const el = $("#parse"), before = el.className;
    const r = parseInput(el);
    if (el.className !== before && el.textContent) VGMotion.flash(el);
    return r;
  }
  function parseInput(el) {
    const raw = $("#cfg").value.trim();
    if (!raw) { el.textContent = ""; el.className = "parse"; return null; }
    const tok = raw.split(/\s+/)[0];
    const hasObject = raw.includes("{");
    const looksUrl = !hasObject && (URL_RE.test(tok) || /^https?:\/\/\S+$/i.test(tok));
    if (!hasObject && (looksUrl || (mode === "url" && raw.split(/\s+/).length === 1))) {
      el.textContent = "✓ " + tok.replace(/^https?:\/\//, ""); el.className = "parse ok";
      return { kind: "url", url: tok };
    }
    const { config } = parseConfig(raw);
    if (config && config.projectId) {
      el.textContent = "✓ " + config.projectId + (config.apiKey ? " · apiKey" : "") + (config.storageBucket ? " · storage" : "");
      el.className = "parse ok";
      return { kind: "config", config };
    }
    if (/supabase\.(co|in)/.test(raw) && /eyJ[\w-]+\.eyJ[\w-]+/.test(raw)) {
      el.textContent = "✓ Supabase project"; el.className = "parse ok";
      return { kind: "raw", raw };
    }
    el.textContent = mode === "url" ? "✗ Not a valid URL" : "✗ No projectId / Supabase key";
    el.className = "parse err";
    return null;
  }
  const tabInd = VGMotion.tabIndicator($("#modeTabs"), ".mode-tab");
  function setMode(m) {
    mode = m;
    $$("#modeTabs .mode-tab").forEach((b) => b.classList.toggle("active", b.dataset.mode === m));
    tabInd.update();
    const lbl = $("#cfgLbl"), hint = $("#cfgHint"), cfg = $("#cfg");
    if (m === "url") { lbl.firstChild.textContent = "Website URL "; hint.textContent = "your app's live address"; cfg.placeholder = "https://my-app.netlify.app"; }
    else { lbl.firstChild.textContent = "Firebase / Supabase config "; hint.textContent = "paste from your app"; cfg.placeholder = 'firebaseConfig = { apiKey:"AIza…", projectId:"my-app" }\n— or —\ncreateClient("https://xxx.supabase.co","eyJ…")'; }
    checkConfig();
  }
  $$("#modeTabs .mode-tab").forEach((b) => b.addEventListener("click", () => { haptic.soft(); setMode(b.dataset.mode); }));
  $("#cfg").addEventListener("input", checkConfig);
  $("#howBtn").addEventListener("click", () => { haptic.soft(); $("#how").hidden = !$("#how").hidden; });
  $("#pasteBtn").addEventListener("click", async () => {
    haptic.tap();
    try {
      const t = await navigator.clipboard.readText();
      if (t) { $("#cfg").value = t; checkConfig(); return; }
    } catch (_) {}
    $("#cfg").focus();
    toast("Long-press the field and choose Paste");
  });

  /* ---------------- Scan ---------------- */
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  async function runScan() {
    const target = checkConfig();
    if (!target) { haptic.err(); toast("Enter a URL or paste a config first", true); $("#cfg").focus(); return; }

    show("scanning");
    primary.hide();
    setBack(null);
    const label = target.kind === "config" ? target.config.projectId
      : target.kind === "raw" ? "Supabase project" : (target.url || "your app").replace(/^https?:\/\//, "").replace(/\/$/, "");
    const kind = target.kind === "config" ? "firebase" : target.kind === "raw" ? "supabase" : "url";
    const mount = $("#scanMount");
    mount.innerHTML = "";
    const live = VGMotion.scanLog(mount, kind, label, { compact: true, onStep: () => haptic.soft() });

    let done = false, result = null, error = null;
    const body = { label: $("#label").value.trim() || null, authorized: !!($("#ownCheck") && $("#ownCheck").checked) };
    if (target.kind === "config") body.config = target.config;
    else body.target = target.url || target.raw;
    const key = getKey();
    if (key) body.license_key = key;

    const req = api("/api/scan", { method: "POST", body: JSON.stringify(body) })
      .catch(async (e) => {
        // A dead saved key shouldn't block a free scan.
        if (key && (e.status === 402 || e.status === 403)) {
          setKey(null);
          delete body.license_key;
          return api("/api/scan", { method: "POST", body: JSON.stringify(body) });
        }
        throw e;
      })
      .then((r) => { result = r; }, (e) => { error = e; })
      .finally(() => { done = true; });

    // Keep the live log on screen for at least ~1.8s so it reads well.
    await Promise.all([req, sleep(1800)]);

    if (error) {
      live.fail(); haptic.err(); toast("Scan failed: " + error.message, true);
      await sleep(900); live.destroy(); goTab("scan"); return;
    }
    await live.finish();
    live.destroy();
    if (!inTG) addLocalId(result.id);
    if (result.locked) haptic.warn(); else haptic.ok();
    if (!result.locked && inTG) refreshMe();
    showResult(result);
  }

  /* ---------------- Result ---------------- */
  function verdict(s) {
    if (s.critical) return "Critical — anyone can read or modify your data.";
    if (s.high) return "Serious gaps. Unauthenticated access is possible.";
    if (s.medium) return "Mostly solid, a few weak spots.";
    if (s.low) return "Looking good — minor hardening left.";
    return "No exposures found. Nicely locked down.";
  }

  function showResult(s) {
    current = s;
    show("result");
    setBack(() => goTab(tab === "history" ? "history" : "scan"));
    const R = 48, C = 2 * Math.PI * R, color = GRADE[s.grade] || "var(--info)";

    let html = `
      <div class="r-top">
        <div class="gauge" style="--orbit:${color}">
          <div class="gauge-orbit"></div>
          <svg width="112" height="112" viewBox="0 0 112 112">
            <circle class="g-track" cx="56" cy="56" r="${R}"/>
            <circle class="g-fill" cx="56" cy="56" r="${R}" stroke="${color}" stroke-dasharray="${C}" stroke-dashoffset="${C}" data-off="${C * (1 - s.score / 100)}"/>
          </svg>
          <div class="g-center"><div class="g-grade" style="color:${color}" data-grade="${s.grade}">${s.grade}</div><div class="g-score"><span data-count="${s.score}">${s.score}</span>/100</div></div>
        </div>
        <div class="r-head">
          <div class="r-proj">${esc(s.project_id)}</div>
          <div class="r-title">${esc(s.target_label || "Security report")}</div>
          <div class="r-verdict">${verdict(s)}</div>
          ${(s.stack && s.stack.length) ? `<div class="stack-row">${s.stack.map((t, i) => `<span class="stack-badge mv-pop" style="--d:${500 + i * 90}ms">${esc(t)}</span>`).join("")}</div>` : ""}
        </div>
      </div>
      <div class="sev-row">
        <div class="sev c"><b data-count="${s.critical}">${s.critical}</b><small>Crit</small></div>
        <div class="sev h"><b data-count="${s.high}">${s.high}</b><small>High</small></div>
        <div class="sev m"><b data-count="${s.medium}">${s.medium}</b><small>Med</small></div>
        <div class="sev l"><b data-count="${s.low}">${s.low}</b><small>Low</small></div>
        <div class="sev p"><b data-count="${s.passed}">${s.passed}</b><small>Pass</small></div>
      </div>
      ${s.active_skipped ? `<div class="active-note mv">${ICO.info}<span>${s.active_skipped} write/sign-up test${s.active_skipped === 1 ? "" : "s"} didn't run. Tick <b>“This is my project”</b> and scan again for the full check.</span></div>` : ""}`;

    html += s.locked ? lockedHTML(s) : fullHTML(s);
    $("#result").innerHTML = html;
    VGMotion.revealReport($("#result"));

    requestAnimationFrame(() => requestAnimationFrame(() => {
      const g = $("#result .g-fill"); if (g) g.style.strokeDashoffset = g.dataset.off;
    }));

    const ownKey = (me && me.license && me.license.remaining > 0 && me.license.key) || getKey();
    if (s.locked && s.issues > 0 && ownKey) {
      // Already paid for a pack → spend one scan from it instead of paying again.
      const left = me && me.license && me.license.key === ownKey ? me.license.remaining : null;
      primary.set(left != null ? `Unlock · uses 1 of ${left} scans` : "Unlock with my key", () => unlockWith(s, ownKey));
    } else if (s.locked && s.issues > 0) {
      primary.set(`Unlock full report — $${pricing.price_usd || "9"}`, () => VGPay.open(s, payCtx(s)));
      const k = $("#lockKeyBtn");
      if (k) k.addEventListener("click", (e) => { e.preventDefault(); haptic.soft(); goTab("key"); });
    } else {
      primary.set("Scan again", () => goTab("scan"));
    }

    $$("#result .f").forEach((f) => {
      const h = f.querySelector(".f-h");
      if (!f.querySelector(".f-b")) return;
      h.addEventListener("click", () => { haptic.soft(); f.classList.toggle("open"); });
    });
    $$("#result .copy").forEach((b) => b.addEventListener("click", (e) => {
      e.stopPropagation();
      copyText(b.closest(".f-b").querySelector("pre").textContent);
    }));
    const first = $("#result .f.critical, #result .f.high, #result .f.medium, #result .f.low");
    if (first && first.querySelector(".f-b")) first.classList.add("open");
  }

  function lockedHTML(s) {
    const n = s.issues;
    if (!n) return `<div class="lock-hero"><div class="lock-n good">0</div><div class="lock-l">No holes found</div><div class="lock-s">Every check that ran came back clean.</div></div>`;
    const cls = s.critical || s.high ? "bad" : "warn";
    const sevs = [];
    ["critical", "high", "medium", "low"].forEach((k) => { for (let i = 0; i < s[k]; i++) sevs.push(k); });
    const fakes = sevs.slice(0, 3).map((k, i) => `
      <div class="f ${k}"><div class="f-h"><span class="badge ${k}">${SEV[k]}</span><span class="f-t"><span class="fake fake-shimmer" style="width:${[70, 55, 62][i]}%"></span></span></div></div>`).join("");
    return `
      <div class="lock-hero"><div class="lock-n ${cls}${s.critical ? " shake-on-reveal" : ""}" data-count="${n}">${n}</div>
        <div class="lock-l">security hole${n === 1 ? "" : "s"} in your project</div>
        <div class="lock-s">Which ones, and how to fix them, is in the full report.</div></div>
      <div class="blur-list">${fakes}</div>
      <div class="paywall shine">
        <h3>${ICO.unlock} See every hole and how to close it</h3>
        <ul>
          <li>What each hole is and what an attacker can do</li>
          <li>Proof: the exact request that got through</li>
          <li>Copy-paste security rules to fix it</li>
          <li>${pricing.pack_scans} full scans to re-check after fixing</li>
        </ul>
        <div class="price"><b>$${esc(pricing.price_usd || "9")}</b> · card, bank transfer or crypto</div>
        <p class="fine left"><a href="#" id="lockKeyBtn" style="color:var(--accent)">I already have a key →</a></p>
      </div>`;
  }

  function fullHTML(s) {
    const v = s.findings.filter((f) => f.status === "vulnerable");
    const p = s.findings.filter((f) => f.status === "ok");
    const o = s.findings.filter((f) => f.status !== "vulnerable" && f.status !== "ok");
    const sec = (title, arr) => arr.length ? `<div class="sec">${title}</div><div class="list">${arr.map(card).join("")}</div>` : "";
    return sec("Fix these", v) + sec("Passed", p) + sec("Not determined", o);
  }

  function card(f, i) {
    const detail = f.status === "vulnerable" || (f.evidence && f.status !== "ok");
    const body = detail ? `<div class="f-b"><div>
        ${f.status === "vulnerable" && f.description ? `<p>${esc(f.description)}</p>` : ""}
        ${f.evidence ? `<div class="ev">${esc(f.evidence)}</div>` : ""}
        ${f.status === "vulnerable" && f.remediation ? `<div class="fix-h"><b>How to fix</b><button class="copy">Copy</button></div><pre>${esc(f.remediation)}</pre>` : ""}
      </div></div>` : "";
    return `<div class="f ${f.severity}" style="animation-delay:${i * 50}ms">
      <div class="f-h"><span class="badge ${f.severity}">${SEV[f.severity] || f.severity}</span><span class="f-t">${esc(f.title)}</span>${detail ? ICO.chev : ""}</div>
      ${body}</div>`;
  }


  /* ---------------- Payment ---------------- */
  function payCtx(s) {
    return {
      api, toast, inTG, tg,
      haptic: { tap: haptic.tap, ok: haptic.ok, err: haptic.err },
      onStars: s ? () => buy(s) : null,
      onHaveKey: () => goTab("key"),
      async onPaid(scanId, key) {
        if (key) setKey(key);
        await refreshMe();
        try { showResult(await api("/api/scans/" + scanId)); } catch (_) {}
      },
    };
  }

  async function unlockWith(scan, key) {
    primary.loading(true);
    try {
      const s = await api(`/api/scans/${scan.id}/unlock`, { method: "POST", body: JSON.stringify({ license_key: key }) });
      primary.loading(false);
      haptic.ok();
      await refreshMe();
      showResult(s);
      toast("Full report unlocked");
    } catch (e) {
      primary.loading(false);
      haptic.err();
      if (e.status === 402 || e.status === 403) {
        // Key is spent or invalid → forget it and fall back to paying.
        if (key === getKey()) setKey(null);
        me = null;
        await refreshMe();
        showResult(scan);
        toast(e.status === 402 ? "No scans left on your key" : "Key is no longer valid", true);
      } else toast(e.message, true);
    }
  }

  async function buy(scan) {
    if (!inTG) {
      if (pricing.payment_url) { window.open(pricing.payment_url, "_blank", "noopener"); toast("After paying, enter your key in Access"); }
      else goTab("key");
      return;
    }
    primary.loading(true);
    try {
      const { invoice_link } = await api("/api/tg/invoice", { method: "POST", body: JSON.stringify({ scan_id: scan.id }) });
      tg.openInvoice(invoice_link, async (status) => {
        primary.loading(false);
        if (status === "paid") {
          haptic.ok();
          toast("Payment received — unlocking…");
          await waitUnlocked(scan.id);
        } else if (status === "failed") {
          haptic.err(); toast("Payment failed", true);
        }
      });
    } catch (e) {
      primary.loading(false);
      if (e.status === 409) { showResult(await api("/api/scans/" + scan.id)); return; }
      haptic.err(); toast(e.message, true);
    }
  }

  async function waitUnlocked(id) {
    primary.loading(true);
    for (let i = 0; i < 25; i++) {
      try {
        const s = await api("/api/scans/" + id);
        if (!s.locked) { primary.loading(false); refreshMe(); showResult(s); toast("Full report unlocked"); return; }
      } catch (_) {}
      await sleep(1000);
    }
    primary.loading(false);
    toast("Payment is processing — check History in a moment", true);
  }

  /* ---------------- History ---------------- */
  async function loadHistory() {
    const ul = $("#hist");
    ul.innerHTML = `<li class="empty" style="border:0;background:none">Loading…</li>`;
    let scans = [];
    try {
      if (inTG) scans = await api("/api/tg/scans");
      else scans = (await Promise.all(localIds().map((id) => api("/api/scans/" + id).catch(() => null)))).filter(Boolean);
    } catch (_) {}
    if (!scans.length) {
      ul.innerHTML = `<div class="empty mv"><b class="empty-ico">${ICO.shield}</b>No scans yet.<br/>Run your first one from the Scan tab.</div>`;
      return;
    }
    ul.innerHTML = scans.map((s, i) => {
      const t = new Date(s.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
      return `<li data-id="${s.id}" style="animation-delay:${i * 40}ms">
        <div class="h-g" style="color:${GRADE[s.grade] || "var(--info)"}">${s.grade}</div>
        <div class="h-i"><div class="h-n">${esc(s.target_label || s.project_id)}</div><div class="h-m">${s.issues} holes · ${t}</div></div>
        <span class="h-lock ${!s.issues ? "is-ok" : s.locked ? "is-locked" : "is-open"}">${!s.issues ? ICO.ok : s.locked ? ICO.lock : ICO.unlock}</span></li>`;
    }).join("");
    const byId = Object.fromEntries(scans.map((s) => [s.id, s]));
    $$("#hist li[data-id]").forEach((li) => li.addEventListener("click", () => { haptic.tap(); showResult(byId[li.dataset.id]); }));
  }

  /* ---------------- Access / key ---------------- */
  async function refreshMe() {
    if (!inTG) return;
    try { me = await api("/api/tg/me"); } catch (_) { me = null; }
  }

  async function renderKey() {
    const box = $("#keyBox");
    await refreshMe();
    let lic = me && me.license ? { key: me.license.key, remaining: me.license.remaining, source: "Telegram" } : null;
    const manual = getKey();
    if (!lic && manual) {
      try { const st = await api("/api/license/" + encodeURIComponent(manual)); lic = { key: manual, remaining: st.remaining, source: "Saved key" }; }
      catch (_) { setKey(null); }
    }
    if (lic) {
      const pct = Math.max(0, Math.min(100, (lic.remaining / pricing.pack_scans) * 100));
      box.innerHTML = `<div class="key-card"><small>${lic.source} · active</small>
        <div class="key-val">${esc(lic.key)}</div>
        <div class="key-left"><span>${lic.remaining} scans left</span><div class="bar"><i style="width:0"></i></div>
        <button class="copy" id="copyKey">Copy</button></div></div>`;
      requestAnimationFrame(() => requestAnimationFrame(() => { const i = $(".key-card .bar i"); if (i) i.style.width = pct + "%"; }));
      $("#copyKey").addEventListener("click", () => copyText(lic.key));
    } else {
      box.innerHTML = `<div class="no-key mv"><b class="empty-ico">${ICO.lock}</b>No active access.<br/>Unlock any report to get ${pricing.pack_scans} full scans${inTG ? ` for ${pricing.stars} Stars` : ""}.</div>`;
    }
  }

  $("#keySave").addEventListener("click", async () => {
    const k = $("#keyInp").value.trim().toUpperCase();
    if (!k) return;
    haptic.tap();
    try {
      const st = await api("/api/license/" + encodeURIComponent(k));
      setKey(k);
      $("#keyInp").value = "";
      haptic.ok();
      toast(`Key saved — ${st.remaining} scans left`);
      if (current && current.locked) {
        try { const s = await api(`/api/scans/${current.id}/unlock`, { method: "POST", body: JSON.stringify({ license_key: k }) }); showResult(s); return; }
        catch (_) {}
      }
      renderKey();
    } catch (_) { haptic.err(); toast("Invalid key", true); }
  });

  /* ---------------- Utils ---------------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); }
    catch (_) {
      const ta = document.createElement("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); } catch (_) {} ta.remove();
    }
    haptic.ok(); toast("Copied");
  }
  let tt;
  function toast(m, err = false) {
    const t = $("#toast"); t.textContent = m; t.className = "toast" + (err ? " err" : "");
    requestAnimationFrame(() => t.classList.add("show"));
    clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 2800);
  }

  /* ---------------- Boot ---------------- */
  (async () => {
    try { pricing = { ...pricing, ...(await api("/api/pricing")) }; } catch (_) {}
    // Restore a key saved in Telegram CloudStorage (syncs across the user's devices)
    if (inTG && ver("6.9") && !getKey()) {
      try { tg.CloudStorage.getItem("vg_license", (e, v) => { if (!e && v) store.set("vg_license", v); }); } catch (_) {}
    }
    await refreshMe();
    goTab("scan");
    // Deep link: t.me/bot/app?startapp=history|key|scan_<id>, or a web_app button URL (#scan_<id>).
    let sp = inTG && tg.initDataUnsafe && tg.initDataUnsafe.start_param;
    if (!sp) {
      const h = (location.hash || "").replace(/^#/, "");
      let q = ""; try { q = new URLSearchParams(location.search).get("startapp") || ""; } catch (_) {}
      sp = h || q;
    }
    if (sp === "history") goTab("history");
    else if (sp === "key") goTab("key");
    else if (sp && sp.indexOf("scan_") === 0) {
      const id = sp.slice(5);
      try { showResult(await api("/api/scans/" + id)); } catch (_) {}
    }
    // Came back after paying (CryptoBot) or the admin approved a transfer meanwhile.
    VGPay.resume(payCtx(null));
  })();
})();
