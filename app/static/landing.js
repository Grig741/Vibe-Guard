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
    L(["p", "$ "], ["", "vibeguard scan demo-app"]),
    L(["m", "→ resolving project "], ["u", "demo-app"], ["m", " … "], ["ok", "ok"]),
    L(["m", "→ firestore  "], ["u", "GET  /users          "], ["m", "200  "], ["bad", "OPEN READ      ✗ HIGH"]),
    L(["m", "→ firestore  "], ["u", "POST /__probe__      "], ["m", "200  "], ["bad", "OPEN WRITE     ✗ CRITICAL"], ["m", "  (probe deleted)"]),
    L(["m", "→ rtdb       "], ["u", "GET  /.json          "], ["m", "401  "], ["ok", "denied         ✓"]),
    L(["m", "→ rtdb       "], ["u", "PUT  /__probe__      "], ["m", "401  "], ["ok", "denied         ✓"]),
    L(["m", "→ storage    "], ["u", "LIST demo-app bucket "], ["m", "200  "], ["warn", "LISTABLE       ✗ HIGH"]),
    L(["m", "→ auth       "], ["u", "signUp(email)        "], ["m", "200  "], ["med", "OPEN SIGN-UP   ✗ MEDIUM"], ["m", " (user removed)"]),
    L(["m", "→ auth       "], ["u", "signUp(anonymous)    "], ["m", "400  "], ["ok", "disabled       ✓"]),
    L(["m", "→ apikey     "], ["u", "origin check         "], ["m", "—    "], ["low", "unrestricted   ✗ LOW"]),
    L(["ok", "✓ scan complete in 2.1s"]),
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
    .from(".chip", { scale: .5, opacity: 0, y: 20, duration: .8, stagger: .15, ease: "back.out(1.8)" }, 1)
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

  // Check cards — staggered 3D flip-in
  gsap.from(".check-card", {
    y: 70, opacity: 0, rotateX: -35, transformOrigin: "50% 100%", duration: 1, stagger: { each: .08, grid: "auto", from: "start" },
    ease: "power3.out", clearProps: "transform",
    scrollTrigger: { trigger: ".check-grid", start: "top 82%", once: true },
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
