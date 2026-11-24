// Menu sur mobile, barre cachée en descendant (repli des requêtes « scroll-state »), numéro de la dernière
// version lu sur GitHub, et carte d'ouverture : un échantillon de la vraie carte de WikiArt 81k.
(function () {
  "use strict";
  const btn = document.querySelector(".menu-btn");
  const links = document.querySelector(".nav-links");
  if (btn && links) {
    btn.addEventListener("click", () => {
      const open = links.classList.toggle("open");
      btn.setAttribute("aria-expanded", String(open));
    });
    links.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => {
      links.classList.remove("open"); btn.setAttribute("aria-expanded", "false"); }));
  }

  // barre : là où les requêtes « scroll-state » manquent, un petit écouteur fait la même chose
  const bar = document.querySelector(".nav");
  if (bar && !CSS.supports("container-type", "scroll-state")) {
    let lastY = scrollY;
    addEventListener("scroll", () => {
      const y = Math.max(0, Math.min(scrollY, document.documentElement.scrollHeight - innerHeight));
      if (y === lastY) return;
      bar.classList.toggle("is-hidden", y > lastY && y > bar.offsetHeight && !(links && links.classList.contains("open")));
      lastY = y;
    }, { passive: true });
  }

  const slot = document.querySelector("[data-version]");
  if (slot && window.fetch) {
    fetch("https://api.github.com/repos/riyadhHDA/pixplot-v2/releases/latest", { headers: { Accept: "application/vnd.github+json" } })
      .then((r) => (r.ok ? r.json() : null))
      .then((rel) => { if (rel && rel.tag_name) slot.textContent = rel.tag_name; })
      .catch(() => { /* hors ligne ou limite de l'API : on garde la valeur écrite */ });
  }

  // ---------------------------------------------------------------- carte d'ouverture
  const cv = document.querySelector("canvas[data-map]");
  if (!cv || !window.fetch) return;
  const FR = document.documentElement.lang === "fr";
  const motion = matchMedia("(prefers-reduced-motion: no-preference)").matches;
  fetch(cv.dataset.map).then((r) => r.json()).then((m) => {
    const n = m.pts.length / 3;
    const tx = new Float32Array(n), ty = new Float32Array(n), sx = new Float32Array(n), sy = new Float32Array(n);
    const grp = new Int16Array(n);
    const shown = new Set(m.labels.map((l) => l.c));
    let seed = 3; const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < n; i++) {
      tx[i] = m.pts[3 * i] / 999; ty[i] = 1 - m.pts[3 * i + 1] / 999; grp[i] = m.pts[3 * i + 2];
      // départ : les images en vrac, comme un dossier non trié, en bandes serrées
      sx[i] = 0.08 + rnd() * 0.84; sy[i] = 0.9 + rnd() * 0.06;
    }
    const css = getComputedStyle(document.documentElement);
    let W = 0, H = 0, dpr = 1;
    function size() {
      const r = cv.getBoundingClientRect(); dpr = Math.min(2, devicePixelRatio || 1);
      W = r.width; H = r.height; cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    }
    function draw(t) {
      const ctx = cv.getContext("2d");
      const ink = css.getPropertyValue("--ink-2").trim(), pr = css.getPropertyValue("--prussian").trim();
      const pad = 18, iw = W - 2 * pad, ih = H - 2 * pad - 14;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
      const ease = (k) => 1 - Math.pow(1 - k, 3);
      for (let pass = 0; pass < 2; pass++) {
        ctx.fillStyle = pass ? pr : ink; ctx.globalAlpha = pass ? 0.95 : 0.42;
        for (let i = 0; i < n; i++) {
          const hi = shown.has(grp[i]); if ((pass === 1) !== hi) continue;
          const k = ease(Math.min(1, Math.max(0, (t - (i % 97) / 97 * 0.35) / 0.65)));
          const x = pad + (sx[i] + (tx[i] - sx[i]) * k) * iw, y = pad + (sy[i] + (ty[i] - sy[i]) * k) * ih;
          ctx.fillRect(x - 1, y - 1, hi && t >= 1 ? 2.4 : 2, hi && t >= 1 ? 2.4 : 2);
        }
      }
      const la = Math.min(1, Math.max(0, (t - 1) / 0.4));
      if (la > 0) {
        ctx.globalAlpha = la; ctx.fillStyle = css.getPropertyValue("--ink").trim();
        ctx.strokeStyle = css.getPropertyValue("--paper-2").trim(); ctx.lineWidth = 3.5; ctx.lineJoin = "round";
        ctx.font = `600 ${W < 480 ? 11 : 12.5}px ${css.getPropertyValue("--text")}`;
        for (const l of m.labels) {
          const x = pad + (l.x / 999) * iw, y = Math.max(pad + 12, pad + (1 - l.y / 999) * ih - 4);
          const txt = (FR ? l.fr : l.en).split(" · ")[0];
          ctx.textAlign = x > W * 0.7 ? "right" : "left";
          const tx0 = x + (ctx.textAlign === "right" ? -6 : 6);
          ctx.strokeText(txt, tx0, y); ctx.fillText(txt, tx0, y);
        }
      }
      ctx.globalAlpha = 1;
    }
    size();
    let now = motion ? 0 : 1.4;                     // instant de l'animation (1,4 = carte finie, noms posés)
    if (!motion) draw(now); else {
      let t0 = null;
      const step = (ts) => { if (t0 === null) t0 = ts; now = Math.min(1.4, (ts - t0) / 2200 * 1.4); draw(now);
        if (now < 1.4) requestAnimationFrame(step); };
      requestAnimationFrame(step);
    }
    new ResizeObserver(() => { size(); draw(now); }).observe(cv);
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => draw(now));
  }).catch(() => { /* sans la carte, la page reste lisible : la légende décrit l'image */ });
})();
