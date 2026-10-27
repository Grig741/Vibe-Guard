"use strict";
/* VibeGuard payment sheet — shared by the web scanner (/app) and the Mini App (/tg/).
 *
 *   VGPay.open(scan, ctx)   open the sheet for a locked scan
 *   VGPay.resume(ctx)       on page load: continue a pending order (after the buyer
 *                           came back from paying / the admin approved meanwhile)
 *
 * ctx = {
 *   api(path, opts)           fetch wrapper (adds Telegram initData when in Mini App)
 *   toast(msg, isErr)
 *   inTG, tg                  Telegram WebApp (optional)
 *   haptic                    { tap, ok, err } (optional)
 *   onStars()                 start the Telegram Stars flow (Mini App only)
 *   onHaveKey()               user already has a key
 *   onPaid(scanId, key)       payment confirmed → unlock UI
 * }
 */
window.VGPay = (() => {
  const ORDER_KEY = "vg_order";
  let pricing = null;
  let overlay = null;
  let pollTimer = null;
  let ctx = null;
  let scan = null;

  const store = {
    get() { try { return JSON.parse(localStorage.getItem(ORDER_KEY) || "null"); } catch (_) { return null; } },
    set(v) { try { localStorage.setItem(ORDER_KEY, JSON.stringify(v)); } catch (_) {} },
    del() { try { localStorage.removeItem(ORDER_KEY); } catch (_) {} },
  };
  const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const h = (k) => { try { ctx.haptic && ctx.haptic[k] && ctx.haptic[k](); } catch (_) {} };

  async function loadPricing() {
    if (!pricing) {
      try { pricing = await ctx.api("/api/pricing"); } catch (_) { pricing = { methods: {} }; }
    }
    return pricing;
  }

  /* ---------- sheet shell ---------- */
  function mount() {
    close(true);
    overlay = document.createElement("div");
    overlay.className = "vgp-overlay";
    overlay.innerHTML = `<div class="vgp-sheet" role="dialog" aria-modal="true">
      <div class="vgp-grab"></div><button class="vgp-close" aria-label="Close">✕</button><div class="vgp-body"></div></div>`;
    document.body.appendChild(overlay);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) close(); });
    overlay.querySelector(".vgp-close").addEventListener("click", () => close());
    requestAnimationFrame(() => overlay.classList.add("show"));
  }
  function body(html) {
    const b = overlay.querySelector(".vgp-body");
    b.innerHTML = html;
    return b;
  }
  function close(instant) {
    stopPoll();
    if (!overlay) return;
    const o = overlay;
    overlay = null;
    if (instant) { o.remove(); return; }
    o.classList.remove("show");
    setTimeout(() => o.remove(), 260);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && overlay) close(); });

  /* ---------- views ---------- */
  async function open(s, c) {
    ctx = c;
    scan = s;
    mount();
    body(`<div class="vgp-wait"><div class="vgp-spin"></div></div>`);
    const p = await loadPricing();
    const m = p.methods || {};
    const usd = p.price_usd || "9";
    const opts = [];

    if (m.manual) opts.push(`
      <button class="vgp-opt" data-m="manual">
        <span class="vgp-ico">🏦</span>
        <span class="vgp-ot"><b>Card / bank / crypto wallet</b><small>${p.manual_mode === "relay" ? "We send you payment details · confirmed manually" : "Transfer to our details · confirmed manually"}</small></span>
        <span class="vgp-price">$${esc(usd)}</span></button>`);
    if (m.contact && p.contact_url) opts.push(`
      <button class="vgp-opt" data-m="contact">
        <span class="vgp-ico">💬</span>
        <span class="vgp-ot"><b>Card, bank or crypto</b><small>Message ${esc(p.support)} — you'll get the payment details</small></span>
        <span class="vgp-price">$${esc(usd)}</span></button>`);
    if (m.crypto) opts.push(`
      <button class="vgp-opt crypto" data-m="crypto">
        <span class="vgp-ico">💎</span>
        <span class="vgp-ot"><b>Crypto via @CryptoBot <span class="vgp-tag">instant</span></b><small>USDT, TON, BTC, ETH and more</small></span>
        <span class="vgp-price">$${esc(usd)}</span></button>`);
    if (m.stars && ctx.inTG && ctx.onStars) opts.push(`
      <button class="vgp-opt stars" data-m="stars">
        <span class="vgp-ico">⭐</span>
        <span class="vgp-ot"><b>Telegram Stars <span class="vgp-tag">instant</span></b><small>Pay inside Telegram in one tap</small></span>
        <span class="vgp-price">⭐ ${esc(p.stars)}</span></button>`);
    if (m.link && p.payment_url) opts.push(`
      <button class="vgp-opt" data-m="link">
        <span class="vgp-ico">💳</span>
        <span class="vgp-ot"><b>Pay online</b><small>You'll get a key after paying</small></span>
        <span class="vgp-price">${esc(p.price || "$" + usd)}</span></button>`);

    const b = body(`
      <h3 class="vgp-h">Unlock the full report</h3>
      <p class="vgp-sub">Every hole, proof and copy-paste fixes · <b>${esc(p.pack_scans || 10)} full scans</b> included.</p>
      <div class="vgp-opts">${opts.join("") || `<p class="vgp-sub">Payments aren't set up yet${p.support ? " — contact " + esc(p.support) : ""}.</p>`}</div>
      ${ctx.onHaveKey ? `<button class="vgp-link" data-a="key">I already have a key →</button>` : ""}`);
    b.querySelectorAll(".vgp-opt").forEach((el, i) => { el.style.animationDelay = i * 60 + "ms"; });

    b.addEventListener("click", (e) => {
      const opt = e.target.closest("[data-m]");
      const a = e.target.closest("[data-a]");
      if (a && a.dataset.a === "key") { h("tap"); close(); ctx.onHaveKey(); return; }
      if (!opt) return;
      h("tap");
      const kind = opt.dataset.m;
      if (kind === "manual") (p.manual_mode === "relay" ? relayStart() : manualView());
      if (kind === "contact") contactView();
      if (kind === "crypto") cryptoStart();
      if (kind === "stars") { close(); ctx.onStars(); }
      if (kind === "link") { window.open(p.payment_url, "_blank", "noopener"); ctx.toast("After paying you'll get a key — enter it under the report"); close(); }
    });
  }

  /* --- manual (requisites) --- */
  function manualView() {
    const p = pricing;
    const b = body(`
      <button class="vgp-back">← Back</button>
      <h3 class="vgp-h">Pay by transfer</h3>
      <p class="vgp-sub">Send the amount to any of the details below, then tell us how you paid.</p>
      <div class="vgp-amount"><span>Amount</span><b>$${esc(p.price_usd || "9")}</b></div>
      <div class="vgp-details"><button class="vgp-copy">Copy</button>${esc(p.manual_details || "")}</div>
      <p class="vgp-hint">Paying in another currency? Send the equivalent at today's rate.</p>
      ${ctx.inTG ? "" : `<label class="vgp-lbl" for="vgpContact">Your Telegram or email</label>
      <input class="vgp-inp" id="vgpContact" placeholder="@username or you@mail.com" autocomplete="off" />`}
      <label class="vgp-lbl" for="vgpNote">Payment proof</label>
      <input class="vgp-inp" id="vgpNote" placeholder="Tx hash, or card last 4 digits + payer name" autocomplete="off" />
      <button class="vgp-btn" id="vgpPaid">I've paid</button>
      <p class="vgp-err" id="vgpErr"></p>`);
    b.querySelector(".vgp-back").addEventListener("click", () => open(scan, ctx));
    b.querySelector(".vgp-copy").addEventListener("click", () => copy(p.manual_details || ""));
    b.querySelector("#vgpPaid").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      const note = b.querySelector("#vgpNote").value.trim();
      const contactEl = b.querySelector("#vgpContact");
      const contact = contactEl ? contactEl.value.trim() : null;
      const err = b.querySelector("#vgpErr");
      err.textContent = "";
      if (contactEl && !contact) { h("err"); err.textContent = "Leave a contact so we can send you the key."; contactEl.focus(); return; }
      if (!note) { h("err"); err.textContent = "Add the tx hash or the card's last 4 digits + payer name."; b.querySelector("#vgpNote").focus(); return; }
      btn.disabled = true;
      try {
        const o = await ctx.api("/api/pay/manual", { method: "POST", body: JSON.stringify({ scan_id: scan.id, contact, note }) });
        store.set({ id: o.id, scan_id: scan.id, method: "manual" });
        h("ok");
        waitView(o, "manual");
      } catch (ex) {
        btn.disabled = false;
        h("err");
        if (ex.status === 409) { close(); ctx.onPaid(scan.id, null); return; }
        err.textContent = ex.message;
      }
    });
  }

  /* --- contact the seller (details sent personally) --- */
  function contactView() {
    const p = pricing;
    const msg = `Hi! I'd like the VibeGuard full report ($${p.price_usd || "9"}).`;
    const b = body(`
      <button class="vgp-back">← Back</button>
      <h3 class="vgp-h">Pay by card, bank or crypto</h3>
      <p class="vgp-sub">Message us — we'll send the payment details. After you pay, you get a key for <b>${esc(p.pack_scans || 10)} full scans</b>.</p>
      <div class="vgp-amount"><span>Amount</span><b>$${esc(p.price_usd || "9")}</b></div>
      <div class="vgp-details"><button class="vgp-copy">Copy</button>${esc(msg)}</div>
      <p class="vgp-hint">Copy this message and send it to ${esc(p.support)}.</p>
      <button class="vgp-btn" id="vgpWrite">Message ${esc(p.support)}</button>
      ${ctx.onHaveKey ? `<button class="vgp-link" id="vgpGotKey">I've got my key →</button>` : ""}`);
    b.querySelector(".vgp-back").addEventListener("click", () => open(scan, ctx));
    b.querySelector(".vgp-copy").addEventListener("click", () => copy(msg));
    b.querySelector("#vgpWrite").addEventListener("click", () => {
      h("tap");
      try { navigator.clipboard.writeText(msg); } catch (_) {}
      const url = p.contact_url;
      try {
        if (ctx.inTG && ctx.tg && url.startsWith("https://t.me/")) { ctx.tg.openTelegramLink(url); return; }
      } catch (_) {}
      window.open(url, "_blank", "noopener");
    });
    const gk = b.querySelector("#vgpGotKey");
    if (gk) gk.addEventListener("click", () => { close(); ctx.onHaveKey(); });
  }

  /* --- relay: request details, admin sends them through the bot --- */
  let stage = null; // "details-wait" | "details" | "confirm"
  async function relayStart() {
    body(`<div class="vgp-wait"><div class="vgp-spin"></div><h3>Requesting payment details…</h3></div>`);
    try {
      const o = await ctx.api("/api/pay/manual", { method: "POST", body: JSON.stringify({ scan_id: scan.id }) });
      store.set({ id: o.id, scan_id: scan.id, method: "manual" });
      h("ok");
      if (o.details && !o.buyer_paid) detailsView(o);
      else waitView(o, "manual");
    } catch (ex) {
      h("err");
      if (ex.status === 409) { close(); ctx.onPaid(scan.id, null); return; }
      ctx.toast(ex.message, true);
      open(scan, ctx);
    }
  }

  function detailsView(o) {
    if (!overlay) mount();
    stage = "details";
    const b = body(`
      <h3 class="vgp-h">Payment details</h3>
      <p class="vgp-sub">Send the amount using the details below, then tell us how you paid.</p>
      <div class="vgp-amount"><span>Amount</span><b>$${esc(o.amount)}</b></div>
      <div class="vgp-details"><button class="vgp-copy">Copy</button>${esc(o.details)}</div>
      <label class="vgp-lbl" for="vgpNote">Payment proof</label>
      <input class="vgp-inp" id="vgpNote" placeholder="Tx hash, or card last 4 digits + payer name" autocomplete="off" />
      ${ctx.inTG ? `<p class="vgp-hint" style="margin-top:8px">Or just send a screenshot to the bot chat.</p>` : ""}
      <button class="vgp-btn" id="vgpPaid">I've paid</button>
      <p class="vgp-err" id="vgpErr"></p>`);
    b.querySelector(".vgp-copy").addEventListener("click", () => copy(o.details || ""));
    b.querySelector("#vgpPaid").addEventListener("click", async (e) => {
      const btn = e.currentTarget, note = b.querySelector("#vgpNote").value.trim(), err = b.querySelector("#vgpErr");
      if (!note) { h("err"); err.textContent = "Add the tx hash or the card's last 4 digits + payer name."; return; }
      btn.disabled = true;
      try {
        const r = await ctx.api(`/api/pay/order/${o.id}/paid`, { method: "POST", body: JSON.stringify({ note }) });
        h("ok");
        waitView(r, "manual");
      } catch (ex) { btn.disabled = false; h("err"); err.textContent = ex.message; }
    });
    startPoll(o.id, 6000);
  }

  /* --- crypto (CryptoBot) --- */
  async function cryptoStart() {
    body(`<div class="vgp-wait"><div class="vgp-spin"></div><h3>Creating invoice…</h3></div>`);
    try {
      const o = await ctx.api("/api/pay/crypto", { method: "POST", body: JSON.stringify({ scan_id: scan.id }) });
      store.set({ id: o.id, scan_id: scan.id, method: "cryptobot" });
      openInvoice(o);
      waitView(o, "cryptobot");
    } catch (ex) {
      h("err");
      if (ex.status === 409) { close(); ctx.onPaid(scan.id, null); return; }
      ctx.toast(ex.message, true);
      open(scan, ctx);
    }
  }
  function openInvoice(o) {
    const tgLink = o.mini_app_url && o.mini_app_url.startsWith("https://t.me/") ? o.mini_app_url : null;
    try {
      if (ctx.inTG && ctx.tg && tgLink) { ctx.tg.openTelegramLink(tgLink); return; }
      if (ctx.inTG && ctx.tg && o.pay_url) { ctx.tg.openLink(o.pay_url); return; }
    } catch (_) {}
    window.open(o.pay_url || o.mini_app_url, "_blank", "noopener");
  }

  /* --- waiting / done --- */
  function waitView(o, method) {
    if (!overlay) mount();
    const manual = method === "manual";
    const needDetails = manual && !o.details && !o.buyer_paid;
    stage = needDetails ? "details-wait" : "confirm";
    if (needDetails) {
      const bd = body(`
        <div class="vgp-wait">
          <div class="vgp-spin"></div>
          <h3>Waiting for payment details</h3>
          <p>${ctx.inTG ? "We'll send the details to this chat and here — usually within minutes."
                        : "Keep this page open — the details will appear here, usually within minutes. You can also come back later."}</p>
        </div>
        <button class="vgp-link" id="vgpLater">Close — I'll come back</button>`);
      bd.querySelector("#vgpLater").addEventListener("click", () => close());
      startPoll(o.id, 4000);
      return;
    }
    const b = body(`
      <div class="vgp-wait">
        <div class="vgp-spin"></div>
        <h3>${manual ? "Waiting for confirmation" : "Waiting for payment"}</h3>
        <p>${manual
          ? (ctx.inTG ? "We'll check the transfer and send your key to this chat. Usually within a few hours."
                      : "We'll check the transfer and unlock the report. You can close this page — the key will appear here when you come back.")
          : "Finish the payment in @CryptoBot. This page updates by itself as soon as it's paid."}</p>
      </div>
      ${manual ? "" : `<button class="vgp-btn ghost" id="vgpReopen">Open payment again</button>`}
      <button class="vgp-link" id="vgpLater">${manual ? "OK, close" : "I'll pay later"}</button>`);
    const re = b.querySelector("#vgpReopen");
    if (re) re.addEventListener("click", () => { h("tap"); openInvoice(o); });
    b.querySelector("#vgpLater").addEventListener("click", () => close());
    startPoll(o.id, manual ? 6000 : 3000);
  }

  function doneView(scanId, key) {
    if (!overlay) mount();
    h("ok");
    const b = body(`
      <div class="vgp-done">
        <div class="vgp-check"><svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg></div>
        <h3 class="vgp-h">Payment confirmed</h3>
        <p class="vgp-sub" style="margin:0">Your full report is unlocked. Save your key — it works on the website and in Telegram.</p>
        ${key ? `<div class="vgp-key">${esc(key)}</div><button class="vgp-link" id="vgpCopyKey">Copy key</button>` : ""}
        <button class="vgp-btn" id="vgpShow">Show my report</button>
      </div>`);
    const ck = b.querySelector("#vgpCopyKey");
    if (ck) ck.addEventListener("click", () => copy(key));
    b.querySelector("#vgpShow").addEventListener("click", () => close());
    ctx.onPaid(scanId, key);
  }

  /* ---------- polling ---------- */
  function stopPoll() { if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; } }
  function startPoll(orderId, every) {
    stopPoll();
    const started = Date.now();
    const tick = async () => {
      if (!overlay) return;
      try {
        const o = await ctx.api("/api/pay/order/" + orderId);
        if (o.status === "paid") { store.del(); doneView(o.scan_id, o.license_key); return; }
        if (o.method === "manual" && o.details && !o.buyer_paid && stage !== "details") { h("ok"); detailsView(o); return; }
        if (o.status === "rejected" || o.status === "expired") {
          store.del();
          h("err");
          body(`<div class="vgp-wait"><h3>${o.status === "rejected" ? "Payment not confirmed" : "Invoice expired"}</h3>
            <p>${o.status === "rejected" ? "We couldn't find your transfer. If you did pay, contact support." : "The invoice timed out. You can start a new one."}</p></div>
            <button class="vgp-btn ghost" id="vgpAgain">Try again</button>`).querySelector("#vgpAgain")
            .addEventListener("click", () => open(scan, ctx));
          return;
        }
      } catch (_) {}
      if (Date.now() - started < 30 * 60 * 1000) pollTimer = setTimeout(tick, every);
    };
    pollTimer = setTimeout(tick, every);
  }

  /* ---------- resume after reload / return ---------- */
  async function resume(c, orderIdFromUrl) {
    ctx = c;
    const saved = store.get();
    const id = orderIdFromUrl || (saved && saved.id);
    if (!id) return;
    try {
      const o = await ctx.api("/api/pay/order/" + id);
      scan = { id: o.scan_id };
      if (o.status === "paid") { store.del(); doneView(o.scan_id, o.license_key); }
      else if (o.status === "pending" && o.method === "manual" && o.details && !o.buyer_paid) { mount(); detailsView(o); }
      else if (o.status === "pending") { mount(); waitView(o, o.method); }
      else store.del();
    } catch (_) { store.del(); }
  }

  async function copy(t) {
    try { await navigator.clipboard.writeText(t); }
    catch (_) {
      const ta = document.createElement("textarea");
      ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } catch (_) {}
      ta.remove();
    }
    h("ok");
    ctx.toast("Copied");
  }

  return { open, resume, close };
})();
