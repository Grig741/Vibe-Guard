"use strict";
/* VibeGuard motion kit — shared by the web scanner (/app) and the Mini App (/tg/).
 * Vanilla, no deps. Everything animates transform / opacity only, runs outside any
 * render loop, and switches itself off under prefers-reduced-motion.
 */
(function () {
  const reduced = (() => {
    try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (_) { return false; }
  })();
  const finePointer = (() => {
    try { return window.matchMedia("(pointer: fine)").matches; } catch (_) { return false; }
  })();
  const easeOutExpo = (k) => (k >= 1 ? 1 : 1 - Math.pow(2, -10 * k));
  const raf = (fn) => window.requestAnimationFrame(fn);

  /* ---------- Count-up ---------- */
  function countUp(el, to, dur = 900, suffix = "") {
    if (!el) return;
    to = Number(to) || 0;
    if (reduced || to === 0) { el.textContent = to + suffix; return; }
    const t0 = performance.now();
    el.textContent = "0" + suffix;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      el.textContent = Math.round(to * easeOutExpo(k)) + suffix;
      if (k < 1) raf(step);
    };
    raf(step);
  }

  /* ---------- Text scramble ---------- */
  const GLYPHS = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789#$%&*+=<>/\\";
  function scramble(el, text, dur = 520) {
    if (!el) return;
    if (reduced) { el.textContent = text; return; }
    const t0 = performance.now();
    const len = text.length;
    const step = (t) => {
      const k = Math.min(1, (t - t0) / dur);
      const fixed = Math.floor(len * k);
      let out = text.slice(0, fixed);
      for (let i = fixed; i < len; i++) {
        out += text[i] === " " ? " " : GLYPHS[(Math.random() * GLYPHS.length) | 0];
      }
      el.textContent = out;
      if (k < 1) raf(step); else el.textContent = text;
    };
    raf(step);
  }

  /* ---------- Ripple (delegated: any .rp element) ---------- */
  document.addEventListener("pointerdown", (e) => {
    if (reduced) return;
    const host = e.target.closest && e.target.closest(".rp");
    if (!host || host.disabled) return;
    const r = host.getBoundingClientRect();
    const size = Math.max(r.width, r.height) * 2.2;
    const w = document.createElement("span");
    w.className = "rp-wave";
    w.style.width = w.style.height = size + "px";
    w.style.left = e.clientX - r.left - size / 2 + "px";
    w.style.top = e.clientY - r.top - size / 2 + "px";
    host.appendChild(w);
    w.addEventListener("animationend", () => w.remove(), { once: true });
  }, { passive: true });

  /* ---------- Magnetic pull ---------- */
  function magnetic(el, strength = 0.22) {
    if (!el || reduced || !finePointer) return;
    el.classList.add("magnetic");
    let frame = 0, tx = 0, ty = 0;
    const apply = () => { frame = 0; el.style.setProperty("--tx", tx + "px"); el.style.setProperty("--ty", ty + "px"); };
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      tx = (e.clientX - (r.left + r.width / 2)) * strength;
      ty = (e.clientY - (r.top + r.height / 2)) * strength * 1.4;
      if (!frame) frame = raf(apply);
    });
    el.addEventListener("pointerleave", () => { tx = 0; ty = 0; if (!frame) frame = raf(apply); });
  }

  /* ---------- Spotlight border (cursor-tracked) ---------- */
  function spotlight(els) {
    if (reduced || !finePointer) return;
    (els || []).forEach((el) => {
      if (!el) return;
      el.classList.add("spot");
      let frame = 0, x = 0, y = 0;
      const apply = () => { frame = 0; el.style.setProperty("--sx", x + "px"); el.style.setProperty("--sy", y + "px"); };
      el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        x = e.clientX - r.left; y = e.clientY - r.top;
        if (!frame) frame = raf(apply);
      });
    });
  }

  /* ---------- Sliding tab indicator ---------- */
  function tabIndicator(container, itemSel) {
    if (!container) return { update() {} };
    const items = () => Array.from(container.querySelectorAll(itemSel));
    let ind = container.querySelector(".tab-ind");
    if (!ind) { ind = document.createElement("span"); ind.className = "tab-ind"; container.prepend(ind); }
    container.classList.add("has-ind");
    const update = () => {
      const list = items();
      const i = Math.max(0, list.findIndex((t) => t.classList.contains("active")));
      container.style.setProperty("--n", list.length);
      container.style.setProperty("--i", i);
    };
    update();
    return { update };
  }

  /* ---------- Staggered reveal ---------- */
  function stagger(root, sel = ".mv", gap = 60, start = 0) {
    if (!root) return;
    root.querySelectorAll(sel).forEach((el, i) => {
      el.style.setProperty("--d", (start + i * gap) + "ms");
    });
  }

  /* ---------- Report reveal: count-ups, grade pop, stagger, shake ---------- */
  function revealReport(root) {
    if (!root) return;
    stagger(root, ".mv", 55, 80);
    root.querySelectorAll("[data-count]").forEach((el, i) => {
      const to = Number(el.dataset.count) || 0;
      if (!reduced) el.textContent = "0" + (el.dataset.suffix || "");  // no flash of the final value
      setTimeout(() => countUp(el, to, 800 + Math.min(to, 20) * 20, el.dataset.suffix || ""), reduced ? 0 : 160 + i * 70);
    });
    const grade = root.querySelector("[data-grade]");
    if (grade) scramble(grade, grade.dataset.grade, 650);
    const shake = root.querySelector(".shake-on-reveal");
    if (shake && !reduced) setTimeout(() => shake.classList.add("shake"), 1100);
  }

  /* ---------- Live scan log ---------- */
  const STEPS = {
    url: [
      "Fetching the page",
      "Pulling JavaScript bundles",
      "Hunting leaked API keys",
      "Locating Firebase / Supabase config",
      "Probing database rules",
      "Checking storage and auth",
      "Looking for exposed .env / .git",
      "Reading security headers",
    ],
    firebase: [
      "Connecting to Firebase",
      "Firestore read access",
      "Firestore write access",
      "Realtime Database rules",
      "Storage bucket listing",
      "Authentication providers",
      "API key restrictions",
    ],
    supabase: [
      "Connecting to Supabase",
      "Row Level Security on tables",
      "Anonymous write access",
      "Storage buckets",
      "Schema exposure",
      "service_role key exposure",
    ],
  };

  function scanLog(mount, kind, targetLabel, opts = {}) {
    const steps = STEPS[kind] || STEPS.url;
    const box = document.createElement("div");
    box.className = "scan-live" + (opts.compact ? " compact" : "");
    box.innerHTML = `
      <div class="sl-head">
        <div class="sl-radar" aria-hidden="true">
          <span class="sl-ring r1"></span><span class="sl-ring r2"></span><span class="sl-ring r3"></span>
          <span class="sl-sweep"></span>
          <i class="sl-blip b1"></i><i class="sl-blip b2"></i><i class="sl-blip b3"></i>
          <svg viewBox="0 0 24 24"><path d="M12 2 4 5v6c0 5 3.4 9.4 8 11 4.6-1.6 8-6 8-11V5l-8-3Z"/></svg>
        </div>
        <div class="sl-meta">
          <div class="sl-title">Scanning <b class="sl-target"></b></div>
          <div class="sl-sub"><span class="sl-dot"></span><span class="sl-time">0.0s</span><span class="sl-sep">·</span><span class="sl-count">0/${steps.length} checks</span></div>
        </div>
      </div>
      <div class="sl-bar"><i></i></div>
      <ol class="sl-log"></ol>
      ${opts.compact ? "" : `<div class="sl-skel" aria-hidden="true"><i style="width:72%"></i><i style="width:54%"></i><i style="width:64%"></i></div>`}`;
    mount.appendChild(box);
    const $ = (s) => box.querySelector(s);
    $(".sl-target").textContent = targetLabel || "your app";
    const log = $(".sl-log"), bar = $(".sl-bar i"), time = $(".sl-time"), count = $(".sl-count");

    const t0 = performance.now();
    let idx = -1, progress = 0, stopped = false;
    const timer = setInterval(() => { time.textContent = ((performance.now() - t0) / 1000).toFixed(1) + "s"; }, 100);

    const setBar = (p) => { progress = p; bar.style.transform = `scaleX(${p})`; };
    const lines = [];
    function next() {
      if (idx >= 0 && lines[idx]) { lines[idx].className = "done"; }
      idx++;
      count.textContent = Math.min(idx, steps.length) + "/" + steps.length + " checks";
      if (idx >= steps.length) return false;
      const li = document.createElement("li");
      li.className = "run";
      li.innerHTML = `<span class="sl-ico"></span><span class="sl-txt"></span><span class="sl-ms"></span>`;
      log.appendChild(li);
      lines.push(li);
      scramble(li.querySelector(".sl-txt"), steps[idx], 420);
      li.dataset.t = performance.now();
      if (opts.onStep) { try { opts.onStep(idx); } catch (_) {} }
      return true;
    }
    function stampPrev() {
      const prev = lines[idx - 1];
      if (prev && !prev.querySelector(".sl-ms").textContent) {
        prev.querySelector(".sl-ms").textContent = Math.max(40, Math.round(performance.now() - prev.dataset.t)) + "ms";
      }
    }

    next();
    // While the request runs, walk the checklist and creep the bar toward 92%.
    const walker = setInterval(() => {
      if (stopped) return;
      if (idx < steps.length - 1) { next(); stampPrev(); }
      setBar(Math.min(0.92, progress + (0.92 - progress) * 0.18 + 0.01));
    }, reduced ? 200 : 620);
    setBar(0.04);

    async function finish() {
      stopped = true;
      clearInterval(walker);
      while (idx < steps.length) {
        const more = next();
        stampPrev();
        setBar(Math.min(0.98, (idx + 1) / steps.length));
        if (!more) break;
        await new Promise((r) => setTimeout(r, reduced ? 0 : 90));
      }
      setBar(1);
      clearInterval(timer);
      box.classList.add("ok");
      await new Promise((r) => setTimeout(r, reduced ? 0 : 380));
    }
    function fail() {
      stopped = true;
      clearInterval(walker); clearInterval(timer);
      if (lines[idx]) lines[idx].className = "err";
      box.classList.add("fail");
    }
    function destroy() { stopped = true; clearInterval(walker); clearInterval(timer); box.remove(); }
    return { finish, fail, destroy, el: box };
  }

  /* ---------- Flash a status line when it changes ---------- */
  function flash(el) {
    if (!el || reduced) return;
    el.classList.remove("flash");
    void el.offsetWidth;  // restart the animation
    el.classList.add("flash");
  }

  /* ---------- Animate an element out, then remove ---------- */
  function out(el, then) {
    if (!el) return;
    if (reduced) { el.remove(); then && then(); return; }
    el.classList.add("mv-out");
    el.addEventListener("animationend", () => { el.remove(); then && then(); }, { once: true });
  }

  window.VGMotion = { reduced, countUp, scramble, magnetic, spotlight, tabIndicator, stagger,
                      revealReport, scanLog, flash, out };
})();
