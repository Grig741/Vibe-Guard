"use strict";

(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hasGsap = typeof window.gsap !== "undefined" && typeof window.ScrollTrigger !== "undefined";
  const finePointer = window.matchMedia("(pointer: fine)").matches;

  if (hasGsap && !reduce) document.documentElement.classList.add("js");

  /* ---------------- Scroll progress + nav ---------------- */
  const bar = $("#progressBar");
  const nav = $("#nav");
  function onScroll() {
    const h = document.documentElement;
    const p = h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight);
    bar.style.transform = `scaleX(${p})`;
    nav.classList.toggle("scrolled", h.scrollTop > 30);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ---------------- Cursor spotlight ---------------- */
  if (finePointer && !reduce) {
    window.addEventListener("mousemove", (e) => {
      document.body.style.setProperty("--mx", e.clientX + "px");
      document.body.style.setProperty("--my", e.clientY + "px");
    }, { passive: true });
  }

  /* ---------------- Typer ---------------- */
  const typer = $("#typer");
  const words = ["Firestore", "Supabase RLS", "Storage", "leaked keys", "your .env"];
  if (typer && !reduce) {
    let wi = 0, ci = words[0].length, deleting = true;
    const tick = () => {
      const w = words[wi];
      if (deleting) {
        ci--;
        if (ci <= 0) { deleting = false; wi = (wi + 1) % words.length; }
      } else {
        ci++;
        if (ci >= words[wi].length) { deleting = true; typer.textContent = words[wi]; return setTimeout(tick, 1700); }
      }
      typer.textContent = (deleting ? w : words[wi]).slice(0, Math.max(0, ci));
      setTimeout(tick, deleting ? 45 : 85);
    };
    setTimeout(tick, 2200);
  }

  /* ---------------- Particle network (hero) ---------------- */
  const canvas = $("#net");
  if (canvas && !reduce) {
    const ctx = canvas.getContext("2d");
    let W = 0, H = 0, dpr = Math.min(2, window.devicePixelRatio || 1);
    let pts = [];
    const mouse = { x: -9999, y: -9999 };
    let running = true;

    const resize = () => {
      const r = canvas.getBoundingClientRect();
      W = r.width; H = r.height;
      canvas.width = W * dpr; canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const n = Math.round(Math.min(90, (W * H) / 16000));
      pts = Array.from({ length: n }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - .5) * .35, vy: (Math.random() - .5) * .35,
        r: Math.random() * 1.6 + .6, hot: Math.random() < .06,
      }));
    };
    resize();
    window.addEventListener("resize", resize);
    canvas.parentElement.addEventListener("mousemove", (e) => {
      const r = canvas.getBoundingClientRect();
      mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top;
    });
    canvas.parentElement.addEventListener("mouseleave", () => { mouse.x = mouse.y = -9999; });

    new IntersectionObserver(([e]) => {
      const was = running; running = e.isIntersecting;
      if (running && !was) requestAnimationFrame(frame);
    }).observe(canvas);

    const LINK = 130;
    function frame() {
      if (!running) return;
      ctx.clearRect(0, 0, W, H);
      for (const p of pts) {
        const dx = p.x - mouse.x, dy = p.y - mouse.y, d2 = dx * dx + dy * dy;
        if (d2 < 140 * 140) { const f = (1 - Math.sqrt(d2) / 140) * .6; p.vx += dx / 140 * f * .1; p.vy += dy / 140 * f * .1; }
        p.vx *= .985; p.vy *= .985;
        p.vx += (Math.random() - .5) * .01; p.vy += (Math.random() - .5) * .01;
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
      }
      for (let i = 0; i < pts.length; i++) {
        for (let j = i + 1; j < pts.length; j++) {
          const a = pts[i], b = pts[j], dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy);
          if (d < LINK) {
            ctx.strokeStyle = (a.hot || b.hot) ? `rgba(240,80,110,${(1 - d / LINK) * .35})` : `rgba(94,234,212,${(1 - d / LINK) * .22})`;
            ctx.lineWidth = .8;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      }
      for (const p of pts) {
        ctx.fillStyle = p.hot ? "rgba(240,80,110,.95)" : "rgba(94,234,212,.75)";
        ctx.beginPath(); ctx.arc(p.x, p.y, p.hot ? p.r + 1 : p.r, 0, Math.PI * 2); ctx.fill();
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /* ---------------- Magnetic buttons ---------------- */
  if (finePointer && !reduce) {
    $$(".magnetic").forEach((el) => {
      el.addEventListener("mousemove", (e) => {
        const r = el.getBoundingClientRect();
        const x = e.clientX - r.left - r.width / 2, y = e.clientY - r.top - r.height / 2;
        el.style.transform = `translate(${x * .22}px, ${y * .3}px)`;
      });
      el.addEventListener("mouseleave", () => { el.style.transform = ""; });
    });
  }

  /* ---------------- 3D tilt cards ---------------- */
  if (finePointer && !reduce) {
    $$(".tilt").forEach((card) => {
      card.addEventListener("mousemove", (e) => {
        const r = card.getBoundingClientRect();
        const px = (e.clientX - r.left) / r.width, py = (e.clientY - r.top) / r.height;
        card.style.transform = `rotateY(${(px - .5) * 14}deg) rotateX(${(.5 - py) * 12}deg) translateZ(0)`;
        card.style.setProperty("--cx", px * 100 + "%");
        card.style.setProperty("--cy", py * 100 + "%");
      });
      card.addEventListener("mouseleave", () => {
        card.style.transition = "transform .5s cubic-bezier(.2,.7,.2,1), border-color .3s, box-shadow .3s";
        card.style.transform = "";
        setTimeout(() => { card.style.transition = ""; }, 500);
      });
    });
  }

  /* ---------------- Animated diff (scroll-scrubbed) ---------------- */
  function setupDiff() {
    const diff = $("#diff");
    if (!diff) return;
    const dels = $$(".ln-del", diff), adds = $$(".ln-add", diff);
    const status = $("#diffStatus");
    const lineH = dels[0].getBoundingClientRect().height;

    // Start: rules look "normal" (vulnerable lines not yet flagged, fixes not yet there)
    gsap.set(dels, { backgroundColor: "rgba(240,80,110,0)", color: "#c9d6e8", textDecorationColor: "rgba(240,80,110,0)", "--sym": 0 });
    gsap.set(adds, { height: 0, opacity: 0, "--sym": 0 });

    const tl = gsap.timeline({
      scrollTrigger: {
        trigger: diff, start: "top 72%", end: "bottom 38%", scrub: .7,
        onUpdate: (self) => {
          const fixed = self.progress > .82;
          status.textContent = fixed ? "locked · owner-only access" : self.progress > .2 ? "2 vulnerable lines found" : "test mode · wide open";
          status.classList.toggle("ok", fixed);
        },
      },
    });
    tl.fromTo(".diff-scan", { y: 0, opacity: 0 }, { y: diff.offsetHeight, opacity: 1, duration: 1, ease: "none" })
      .to(".diff-scan", { opacity: 0, duration: .15 }, ">-0.15")
      .to(dels, { backgroundColor: "rgba(240,80,110,.14)", color: "#f7a3b4", "--sym": 1, duration: .4, stagger: .1 }, .55)
      .to(dels, { textDecorationColor: "rgba(240,80,110,.8)", duration: .3, stagger: .1 }, ">")
      .to(dels, { height: 0, opacity: 0, duration: .5, stagger: .08 }, "+=.3")
      .fromTo(adds, { height: 0, opacity: 0, "--sym": 0 }, { height: lineH, opacity: 1, "--sym": 1, duration: .5, stagger: .12 }, "<.15")
      .to(".g-bad", { rotateX: -90, opacity: 0, duration: .3 }, ">-.1")
      .to(".g-ok", { rotateX: 0, opacity: 1, duration: .3 }, ">-.05");
  }

  /* ---------------- Terminal demo ---------------- */
  const termBody = $("#termBody"), termResult = $("#termResult");
  const L = (...segs) => segs;
  const script = [
    L(["p", "$ "], ["", "vibeguard scan habit-tracker.netlify.app"]),
    L(["m", "→ fetch      "], ["u", "GET  /                     "], ["m", "200  "], ["ok", "3 bundles · Vite"]),
    L(["m", "→ secrets    "], ["u", "/assets/index-4f1c.js      "], ["m", "     "], ["bad", "OPENAI KEY     ✗ CRITICAL"]),
    L(["m", "→ detect     "], ["u", "supabase · firebase config "], ["m", "     "], ["ok", "found"]),
    L(["m", "→ supabase   "], ["u", "GET  /rest/v1/profiles     "], ["m", "200  "], ["bad", "RLS OFF        ✗ HIGH"]),
    L(["m", "→ firestore  "], ["u", "GET  /users                "], ["m", "403  "], ["ok", "denied         ✓"]),
    L(["m", "→ storage    "], ["u", "LIST avatars               "], ["m", "200  "], ["warn", "PUBLIC         ✗ HIGH"]),
    L(["m", "→ files      "], ["u", "GET  /.env                 "], ["m", "200  "], ["bad", "EXPOSED        ✗ CRITICAL"]),
    L(["m", "→ files      "], ["u", "GET  /.git/config          "], ["m", "404  "], ["ok", "not served     ✓"]),
    L(["m", "→ headers    "], ["u", "CSP · HSTS                 "], ["m", "—    "], ["low", "missing        ✗ LOW"]),
    L(["ok", "✓ scan complete in 6.4s · read-only"]),
  ];
  let termRun = 0;

  async function runTerminal() {
    const run = ++termRun;
    termBody.innerHTML = "";
    termResult.classList.remove("show");
    $("#trScore").textContent = "0";
    $("#trHoles").textContent = "0";
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    for (let li = 0; li < script.length; li++) {
      if (run !== termRun) return;
      const line = document.createElement("div");
      line.className = "tl";
      termBody.appendChild(line);
      const cursor = document.createElement("span");
      cursor.className = "cursor-block";
      const speed = li === 0 ? 38 : 7;
      for (const [cls, text] of script[li]) {
        const span = document.createElement("span");
        if (cls) span.className = cls;
        line.appendChild(span);
        line.appendChild(cursor);
        if (reduce) { span.textContent = text; continue; }
        for (let i = 0; i < text.length; i++) {
          if (run !== termRun) return;
          span.textContent += text[i];
          if (text[i] !== " ") await sleep(speed);
        }
      }
      cursor.remove();
      await sleep(li === 0 ? 450 : 170 + Math.random() * 180);
    }
    termResult.classList.add("show");
    countTo($("#trHoles"), 5, 900);
    if (window.VGMotion) VGMotion.scramble($("#trGrade"), "F", 700);
  }

  function countTo(el, to, ms) {
    const start = performance.now();
    const step = (t) => {
      const k = Math.min(1, (t - start) / ms);
      el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3)));
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  if (termBody) {
    let started = false;
    new IntersectionObserver((entries, obs) => {
      if (entries[0].isIntersecting && !started) { started = true; runTerminal(); obs.disconnect(); }
    }, { threshold: .35 }).observe($("#terminal"));
    $("#termReplay").addEventListener("click", runTerminal);
  }

  /* ---------------- Hero: looping live scan ---------------- */
  const SAMPLES = [
    { url: "habit-tracker.netlify.app", stack: ["Vite", "Supabase"], grade: "F", score: 12, color: "var(--crit)", sev: [2, 1, 0, 1],
      log: [["Fetching the page", "200"], ["Pulling 3 JS bundles", "1.2 MB"], ["Hunting leaked keys", "OPENAI KEY", 1], ["Supabase RLS", "RLS OFF", 1], ["Exposed files", ".env", 1], ["Security headers", "2 missing"]],
      finds: [["critical", "OpenAI API key in your frontend"], ["critical", ".env is publicly downloadable"], ["high", "Table “profiles” readable by anyone"]] },
    { url: "ai-notes.vercel.app", stack: ["Next.js", "Firebase"], grade: "D", score: 58, color: "var(--high)", sev: [0, 2, 1, 1],
      log: [["Fetching the page", "200"], ["Pulling 7 JS bundles", "2.4 MB"], ["Hunting leaked keys", "clean"], ["Firestore rules", "OPEN READ", 1], ["Storage bucket", "LISTABLE", 1], ["Auth providers", "open sign-up"]],
      finds: [["high", "Firestore readable by anyone"], ["high", "Storage bucket is listable"], ["medium", "Email sign-up is open"]] },
    { url: "shop-demo.web.app", stack: ["React", "Firebase"], grade: "A", score: 94, color: "var(--ok)", sev: [0, 0, 0, 1],
      log: [["Fetching the page", "200"], ["Pulling 2 JS bundles", "640 KB"], ["Hunting leaked keys", "clean"], ["Firestore rules", "locked"], ["Storage bucket", "private"], ["Security headers", "1 missing"]],
      finds: [["pass", "Firestore blocks anonymous access"], ["pass", "No secret keys in the bundle"], ["low", "Content-Security-Policy missing"]] },
  ];

  function heroDemo() {
    const card = $("#hvCard");
    if (!card) return;
    const urlEl = $("#hvUrl"), log = $("#hvLog"), prog = $("#hvProg"), time = $("#hvTime");
    const fill = $("#hvFill"), gradeEl = $("#hvGrade"), holes = $("#hvHoles"), stackEl = $("#hvStack"), sevEl = $("#hvSev"), finds = $("#hvFinds");
    const C = 213.6;
    let visible = true;
    new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(card);
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const waitVisible = async () => { while (!visible || document.hidden) await sleep(300); };

    function paintReport(sm, animate) {
      fill.style.stroke = sm.color;
      gradeEl.style.color = sm.color;
      fill.style.strokeDashoffset = C;
      const n = sm.sev.reduce((a, b) => a + b, 0);
      stackEl.innerHTML = sm.stack.map((t, i) => `<span class="mv-pop" style="--d:${350 + i * 90}ms">${t}</span>`).join("");
      const labels = ["Crit", "High", "Med", "Low"], colors = ["var(--crit)", "var(--high)", "var(--med)", "var(--low)"];
      sevEl.innerHTML = sm.sev.map((v, i) => `<div class="mv" style="--d:${200 + i * 60}ms"><b style="color:${colors[i]}" data-count="${v}">${v}</b><small>${labels[i]}</small></div>`).join("");
      finds.innerHTML = sm.finds.map(([sev, t], i) => `<div class="hv-find ${sev} mv" style="--d:${520 + i * 110}ms"><span class="t">${sev === "pass" ? "Pass" : sev}</span>${t}</div>`).join("");
      if (!animate || !window.VGMotion) { gradeEl.textContent = sm.grade; holes.textContent = n; fill.style.strokeDashoffset = C * (1 - sm.score / 100); return; }
      requestAnimationFrame(() => requestAnimationFrame(() => { fill.style.strokeDashoffset = C * (1 - sm.score / 100); }));
      VGMotion.scramble(gradeEl, sm.grade, 650);
      VGMotion.countUp(holes, n, 900);
      sevEl.querySelectorAll("[data-count]").forEach((b, i) => setTimeout(() => VGMotion.countUp(b, +b.dataset.count, 700), 200 + i * 60));
    }

    if (reduce) { card.classList.add("report"); urlEl.textContent = SAMPLES[0].url; paintReport(SAMPLES[0], false); return; }

    (async function loop() {
      for (let k = 0; ; k = (k + 1) % SAMPLES.length) {
        const sm = SAMPLES[k];
        await waitVisible();
        // 1. type the URL
        card.className = "hv-card typing";
        urlEl.textContent = "";
        log.innerHTML = ""; prog.style.transform = "scaleX(0)"; time.textContent = "0.0s";
        await sleep(400);
        for (const ch of sm.url) { urlEl.textContent += ch; await sleep(38 + Math.random() * 40); }
        await sleep(350);
        // 2. scan log
        card.className = "hv-card scanning";
        const t0 = performance.now();
        const tick = setInterval(() => { time.textContent = ((performance.now() - t0) / 1000).toFixed(1) + "s"; }, 100);
        for (let i = 0; i < sm.log.length; i++) {
          const [label, res, bad] = sm.log[i];
          const li = document.createElement("li");
          li.innerHTML = `<span class="ic"></span><span class="tx"></span><span class="r"></span>`;
          log.appendChild(li);
          if (window.VGMotion) VGMotion.scramble(li.querySelector(".tx"), label, 320); else li.querySelector(".tx").textContent = label;
          prog.style.transform = `scaleX(${(i + 1) / sm.log.length})`;
          await sleep(430 + Math.random() * 200);
          li.classList.add(bad ? "bad" : "done");
          li.querySelector(".r").textContent = res;
        }
        clearInterval(tick);
        await sleep(450);
        // 3. report
        card.className = "hv-card report";
        paintReport(sm, true);
        await sleep(4800);
        card.className = "hv-card";
        await sleep(500);
      }
    })();
  }
  heroDemo();

  /* ---------------- Bento: perpetual micro-loops (only while on screen) ---------------- */
  function whileVisible(el, everyMs, fn) {
    if (!el || reduce) return;
    let timer = null;
    new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !timer) { fn(); timer = setInterval(fn, everyMs); }
      else if (!e.isIntersecting && timer) { clearInterval(timer); timer = null; }
    }, { threshold: .2 }).observe(el);
  }
  // Secrets: the leaked key keeps re-decoding
  const KEYS = ["sk-proj-8fK2…Qx9a", "sk-ant-api03-…7Hd", "sk_live_51N…v2Lq", "AKIAQ3…7XZP", "ghp_4mT9…Lk2w"];
  let ki = 0;
  whileVisible($(".b-secrets"), 2600, () => { ki = (ki + 1) % KEYS.length; if (window.VGMotion) VGMotion.scramble($("#leakKey"), KEYS[ki], 700); });
  // Supabase: rows get read one after another
  const sbRows = $$(".sb-row"); let sbi = 0;
  whileVisible($(".b-supabase"), 650, () => {
    sbRows.forEach((r, i) => r.classList.toggle("read", i <= sbi % (sbRows.length + 2) && sbi % (sbRows.length + 2) < sbRows.length));
    sbi++;
  });
  // Firebase: checklist runs, two checks fail, then resets
  const fbItems = $$(".fb-item"); const FB_BAD = [1, 3]; let fbi = 0;
  whileVisible($(".b-firebase"), 520, () => {
    const step = fbi % (fbItems.length + 4);
    fbItems.forEach((it, i) => {
      it.classList.remove("run", "ok", "bad");
      if (step >= fbItems.length + 3) return;               // brief blank pause before looping
      if (i < step) it.classList.add(FB_BAD.includes(i) ? "bad" : "ok");
      else if (i === step) it.classList.add("run");
    });
    fbi++;
  });
  // Website: probes light up row by row
  const wpRows = $$(".wp-row"); let wpi = 0;
  whileVisible($(".b-web"), 700, () => {
    const step = wpi % (wpRows.length + 3);
    wpRows.forEach((r, i) => r.classList.toggle("on", i < step || step >= wpRows.length));
    wpi++;
  });

  /* ---------------- Count-up on hero meta, ripple + spotlight ---------------- */
  if (window.VGMotion) {
    $$("[data-count-to]").forEach((el) => {
      if (!reduce) el.textContent = "0" + (el.dataset.suffix || "");
      new IntersectionObserver(([e], o) => {
        if (!e.isIntersecting) return; o.disconnect();
        setTimeout(() => VGMotion.countUp(el, +el.dataset.countTo, 1400, el.dataset.suffix || ""), 900);
      }).observe(el);
    });
    $$(".btn, .term-replay").forEach((b) => b.classList.add("rp"));
    VGMotion.spotlight($$(".bento-card, .plan, .terminal, .diff, .faq-item"));
  }

  /* ---------------- FAQ smooth open ---------------- */
  $$(".faq-item").forEach((d) => {
    const s = d.querySelector("summary"), a = d.querySelector(".faq-a");
    s.addEventListener("click", (e) => {
      if (!hasGsap || reduce) return;
      e.preventDefault();
      if (d.open) {
        gsap.to(a, { height: 0, duration: .35, ease: "power2.inOut", onComplete: () => { d.open = false; a.style.height = ""; } });
      } else {
        d.open = true;
        gsap.fromTo(a, { height: 0 }, { height: a.scrollHeight, duration: .45, ease: "power3.out", onComplete: () => { a.style.height = ""; } });
      }
    });
  });

  /* ---------------- Pricing / Telegram links from the API ---------------- */
  fetch("/api/pricing").then((r) => r.ok ? r.json() : null).then((p) => {
    if (!p) return;
    if (p.price) $("#priceWeb").textContent = p.price;
    if (p.stars) { $("#priceStars").textContent = p.stars; $$(".ps-stars").forEach((e) => { e.textContent = p.stars; }); }
    if (p.pack_scans) $("#packScans").textContent = p.pack_scans;
    if (p.payment_url) $("#buyBtn").href = p.payment_url;
    if (p.bot_username) {
      const url = "https://t.me/" + p.bot_username;
      $("#tgOpenBtn").href = url;
      $$(".tg-link").forEach((a) => { a.href = url; a.target = "_blank"; a.rel = "noopener"; });
    }
  }).catch(() => {});

  /* ---------------- GSAP choreography ---------------- */
  if (!hasGsap || reduce) return;
  gsap.registerPlugin(ScrollTrigger);

  // Hero intro
  const intro = gsap.timeline({ defaults: { ease: "power4.out" } });
  intro
    .from(".hero-title .word", { yPercent: 115, rotate: 4, duration: 1.1, stagger: .06 })
    .from(".reveal-hero", { y: 26, opacity: 0, duration: .9, stagger: .12 }, "-=.7")
    .from(".radar", { scale: .6, opacity: 0, duration: 1.4, ease: "expo.out" }, .2)
    .fromTo(".shield-line", { strokeDashoffset: 70 }, { strokeDashoffset: 0, duration: 1.8, ease: "power2.inOut" }, .4)
    .fromTo(".shield-check", { strokeDashoffset: 12 }, { strokeDashoffset: 0, duration: .7, ease: "power2.out" }, 1.8)
    .from(".shield-fill", { opacity: 0, duration: 1 }, 1.4)
    .from(".hv-card", { y: 40, opacity: 0, scale: .94, duration: 1.2, ease: "expo.out" }, .5)
    .from(".chip", { scale: .5, opacity: 0, y: 20, duration: .8, stagger: .15, ease: "back.out(1.8)" }, 1.3)
    .from(".nav", { y: -40, opacity: 0, duration: .8 }, 0);

  // Hero parallax on scroll
  gsap.to(".hero-visual", { yPercent: 18, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });
  gsap.to(".hero-copy", { yPercent: -10, opacity: .2, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });
  gsap.to(".orb-a", { y: 200, ease: "none", scrollTrigger: { trigger: ".hero", start: "top top", end: "bottom top", scrub: true } });

  // Split section headings into words
  $$(".split").forEach((h) => {
    h.innerHTML = h.textContent.trim().split(/\s+/).map((w) => `<span class="w">${w}</span>`).join(" ");
    gsap.from(h.querySelectorAll(".w"), {
      y: 40, opacity: 0, rotateX: -50, transformOrigin: "50% 100%", duration: .9, stagger: .06, ease: "power3.out",
      scrollTrigger: { trigger: h, start: "top 85%", once: true },
    });
  });
  $$(".section-head .lead, .section-head .eyebrow, .tg-copy .lead, .tg-copy .eyebrow").forEach((el) => {
    gsap.from(el, { y: 20, opacity: 0, duration: .8, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 88%", once: true } });
  });

  setupDiff();

  // Generic reveal
  $$(".reveal-up").forEach((el) => {
    gsap.from(el, { y: 50, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: el, start: "top 88%", once: true } });
  });

  // Scroll-scrubbed problem text: words light up as you scroll
  const scrub = $("#scrubText");
  if (scrub) {
    scrub.innerHTML = scrub.textContent.trim().split(/\s+/).map((w) => `<span class="sw">${w}</span>`).join(" ");
    const ws = scrub.querySelectorAll(".sw");
    const danger = /stranger|download|users|wipe|orders|junk|bill|angry/i;
    gsap.to(ws, {
      color: (i, el) => danger.test(el.textContent) ? "#f0506e" : "#eaf0f8",
      stagger: .1, ease: "none",
      scrollTrigger: { trigger: scrub, start: "top 80%", end: "bottom 45%", scrub: .6 },
    });
  }

  // Bento cards — staggered rise
  gsap.from(".bento-card", {
    y: 70, opacity: 0, duration: 1, stagger: .1, ease: "power3.out", clearProps: "transform",
    scrollTrigger: { trigger: ".bento", start: "top 82%", once: true },
  });

  // How it works — line draws with scroll, steps pop
  gsap.fromTo("#stepsPath", { strokeDashoffset: 1000 }, {
    strokeDashoffset: 0, ease: "none",
    scrollTrigger: { trigger: ".steps", start: "top 75%", end: "bottom 60%", scrub: .5 },
  });
  gsap.from(".step", {
    y: 40, opacity: 0, duration: .8, stagger: .2, ease: "power3.out",
    scrollTrigger: { trigger: ".steps", start: "top 80%", once: true },
  });
  gsap.from(".step-num", {
    scale: 0, rotate: -90, duration: .9, stagger: .2, ease: "back.out(2)",
    scrollTrigger: { trigger: ".steps", start: "top 80%", once: true },
  });

  // Pricing plans — slide from sides
  gsap.from(".plan:not(.plan-pro)", { x: -60, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".plans", start: "top 80%", once: true } });
  gsap.from(".plan-pro", { x: 60, opacity: 0, duration: 1, ease: "power3.out", scrollTrigger: { trigger: ".plans", start: "top 80%", once: true } });
  gsap.from(".plan li", { x: -14, opacity: 0, duration: .5, stagger: .05, ease: "power2.out", scrollTrigger: { trigger: ".plans", start: "top 70%", once: true } });

  // Telegram — phone rotates into place while scrolling
  gsap.fromTo("#phone", { rotateY: -38, rotateX: 14, y: 80 }, {
    rotateY: -8, rotateX: 4, y: 0, ease: "none",
    scrollTrigger: { trigger: ".telegram", start: "top 85%", end: "center 55%", scrub: .8 },
  });
  gsap.from(".tg-list li", { x: -30, opacity: 0, duration: .7, stagger: .12, ease: "power3.out", scrollTrigger: { trigger: ".tg-list", start: "top 85%", once: true } });
  gsap.from(".ps-rows .ps-row", { x: 40, opacity: 0, duration: .6, stagger: .15, ease: "power3.out", scrollTrigger: { trigger: "#phone", start: "top 70%", once: true } });

  // Marquee labels subtle skew by scroll velocity
  const track = $(".marquee-track");
  ScrollTrigger.create({
    onUpdate: (self) => {
      const v = gsap.utils.clamp(-12, 12, self.getVelocity() / 200);
      gsap.to(track, { skewX: -v, duration: .4, ease: "power3.out", overwrite: true });
    },
  });

  // Final CTA
  gsap.from(".final-title", { scale: .7, opacity: 0, duration: 1.2, ease: "expo.out", scrollTrigger: { trigger: ".final", start: "top 75%", once: true } });
  gsap.from(".final .lead, .final .btn", { y: 30, opacity: 0, duration: .8, stagger: .12, delay: .3, ease: "power3.out", scrollTrigger: { trigger: ".final", start: "top 75%", once: true } });
})();
