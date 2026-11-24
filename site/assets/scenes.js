// Démonstrations du site : de vraies œuvres de WikiArt 81k et de vraies réponses de PixPlot (voisines, zones,
// squelettes, étiquettes, notions), posées sur un plan de 1200 × 750. Une « caméra » glisse et zoome d'une œuvre
// à l'autre ; les zones calculées s'allument et se relient. Données : assets/scenes.json (scripts/site_scenes.py).
// Au repos (mouvement réduit, ou avant lecture) la scène montre son état final : toutes les œuvres, toutes les zones.
(function () {
  "use strict";
  const me = document.currentScript;
  const BASE = (me && me.dataset.base) || "assets/";
  const FR = document.documentElement.lang === "fr";
  const L = (fr, en) => (FR ? fr : en);
  const W = 1200, H = 750, SVGNS = "http://www.w3.org/2000/svg";
  const motionOK = matchMedia("(prefers-reduced-motion: no-preference)").matches && "IntersectionObserver" in window;
  const num = (v, d = 2) => (FR ? v.toFixed(d).replace(".", ",") : v.toFixed(d));
  const nice = (s) => (s || "").replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  // nom court d'un artiste : « El Greco », « Van Gogh », « Rosso Fiorentino » plutôt que le seul dernier mot
  const short = (s) => { const p = nice(s).replace(/ The (Elder|Younger)$/, "").split(" "); const k = p.findIndex((w) => /^(El|Van|De|Della|Da|Del|Le|Rosso)$/.test(w));
    return k >= 0 ? p.slice(k).join(" ") : p.pop(); };

  // ------------------------------------------------------------------ construction d'une scène
  function Scene(fig, data) {
    const A = data.art;
    const stage = document.createElement("div"); stage.className = "stage";
    const fit = document.createElement("div"); fit.className = "fit";
    const world = document.createElement("div"); world.className = "world";
    const svg = document.createElementNS(SVGNS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("class", "ov"); svg.setAttribute("aria-hidden", "true");
    const under = svg.cloneNode();                 // liens entre œuvres et blocs : sous eux, pour ne pas les barrer
    world.append(under, svg); fit.append(world); stage.append(fit);
    fig.insertBefore(stage, fig.firstChild);
    new ResizeObserver(() => { fit.style.scale = String(stage.clientWidth / W); }).observe(stage);

    const els = {}, steps = [];
    let rest = [0, 0, W];
    const S = {
      fig, world, svg,
      /** œuvre posée en (x, y), largeur w ou hauteur h ; renvoie son rectangle */
      art(key, id, x, y, size, opt = {}) {
        const a = A[id], r = a.w / a.h;
        const w = opt.box ? opt.box[0] : opt.byH ? size * r : size, h = opt.box ? opt.box[1] : opt.byH ? size : size / r;
        const f = document.createElement("div");
        f.className = "w-art" + (opt.cls ? " " + opt.cls : "");
        Object.assign(f.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" });
        const img = new Image(); img.loading = "lazy"; img.decoding = "async"; img.alt = "";
        img.src = `${BASE}oeuvres/${id}${opt.large && a.large ? "-l" : ""}.webp`;
        f.append(img);
        if (opt.cap !== false) {
          const c = document.createElement("div"); c.className = "w-cap";
          c.innerHTML = opt.cap || `${nice(a.artist)}${a.date ? ", " + a.date : ""}`;
          f.append(c);
        }
        world.append(f);
        return (els[key] = { el: f, x, y, w, h, id });
      },
      text(key, x, y, html, cls = "") {
        const t = document.createElement("div"); t.className = "w-text " + cls;
        Object.assign(t.style, { left: x + "px", top: y + "px" }); t.innerHTML = html;
        world.append(t); return (els[key] = { el: t, x, y });
      },
      /** zone [x0, y0, x1, y1] (coordonnées 0–1 de l'œuvre) dessinée sur l'œuvre */
      box(key, on, b, cls = "hot") {
        // tracé comme un chemin (pathLength n'est pas pris en compte sur <rect> partout)
        const o = els[on], r = document.createElementNS(SVGNS, "path");
        const x = o.x + b[0] * o.w, y = o.y + b[1] * o.h, w = (b[2] - b[0]) * o.w, h = (b[3] - b[1]) * o.h;
        Object.entries({ d: `M${x} ${y} h${w} v${h} h${-w} Z`, class: cls, pathLength: 1 }).forEach(([k, v]) => r.setAttribute(k, v));
        svg.append(r); return (els[key] = { el: r, x, y, w, h, cx: x + w / 2, cy: y + h / 2 });
      },
      dot(key, x, y, rad = 6, cls = "hot-dot") {
        const c = document.createElementNS(SVGNS, "circle");
        Object.entries({ cx: x, cy: y, r: rad, class: cls }).forEach(([k, v]) => c.setAttribute(k, v));
        svg.append(c); return (els[key] = { el: c, cx: x, cy: y, x, y });
      },
      /** ligne courbe entre deux éléments (centres), tracée au fil de l'animation */
      link(key, from, to, cls = "link", bend = 0.18, below = !/^z|^lk/.test(key)) {
        // centre d'un élément : zone, point, œuvre, ou bloc de texte (mesuré dans le plan, hors caméra)
        const ctr = (e) => (e.cx != null ? [e.cx, e.cy] : [e.x + (e.w ?? e.el.offsetWidth) / 2, e.y + (e.h ?? e.el.offsetHeight) / 2]);
        const [ax, ay] = ctr(els[from]), [bx, by] = ctr(els[to]);
        const mx = (ax + bx) / 2 - (by - ay) * bend, my = (ay + by) / 2 + (bx - ax) * bend;
        const p = document.createElementNS(SVGNS, "path");
        p.setAttribute("d", `M${ax} ${ay} Q${mx} ${my} ${bx} ${by}`); p.setAttribute("class", cls); p.setAttribute("pathLength", 1);
        (below ? under : svg).append(p); return (els[key] = { el: p });
      },
      path(key, d, cls) {
        const p = document.createElementNS(SVGNS, "path");
        p.setAttribute("d", d); p.setAttribute("class", cls); p.setAttribute("pathLength", 1);
        svg.append(p); return (els[key] = { el: p });
      },
      rect(key) { return els[key]; },
      /** déroulé : à l'instant t (s), caméra [x, y, largeur], apparitions, tracés, mises en lumière */
      at(t, op) { steps.push({ t, ...op }); return S; },
      rest(cam) { rest = cam; },
      els, steps, get restCam() { return rest; },
    };
    return S;
  }

  // ------------------------------------------------------------------ caméra et lecture
  const camT = ([x, y, w]) => { const z = W / w; return `scale(${z}) translate(${-x}px, ${-y}px)`; };
  function hidden(S) {           // ce que la lecture fait apparaître
    const ids = new Set();
    S.steps.forEach((s) => ["show", "draw"].forEach((k) => (s[k] || []).forEach((id) => ids.add(id))));
    return ids;
  }
  function restState(S) {
    S.world.style.transform = camT(S.restCam);
    Object.values(S.els).forEach((e) => { e.el.style.opacity = ""; e.el.classList.remove("armed-hide"); });
    S.steps.forEach((s) => (s.lit || []).forEach((id) => S.els[id] && S.els[id].el.classList.add("lit")));
    S.steps.forEach((s) => (s.unlit || []).forEach((id) => S.els[id] && S.els[id].el.classList.remove("lit")));
  }
  function arm(S) {
    S.timers && S.timers.forEach(clearTimeout);
    S.world.getAnimations().forEach((a) => a.cancel());
    const first = S.steps.find((s) => s.cam);
    S.world.style.transform = camT(first ? first.cam : S.restCam);
    hidden(S).forEach((id) => S.els[id] && S.els[id].el.classList.add("armed-hide"));
    Object.values(S.els).forEach((e) => e.el.classList.remove("lit"));
  }
  function play(S) {
    arm(S);
    let cam = S.steps.find((s) => s.cam)?.cam || S.restCam;
    S.timers = S.steps.map((s) => setTimeout(() => {
      if (s.cam) {
        const to = s.cam, d = (s.d ?? 1.1) * 1000;
        S.world.animate([{ transform: camT(cam) }, { transform: camT(to) }],
          { duration: d, easing: "cubic-bezier(.45,.05,.2,1)", fill: "forwards" });
        cam = to;
      }
      (s.show || []).forEach((id) => { const e = S.els[id]; if (!e) return; e.el.classList.remove("armed-hide");
        e.el.animate([{ opacity: 0, translate: "0 8px" }, { opacity: 1, translate: "0 0" }], { duration: 450, easing: "ease-out" }); });
      (s.draw || []).forEach((id) => { const e = S.els[id]; if (!e) return; e.el.classList.remove("armed-hide");
        e.el.animate([{ strokeDashoffset: 1 }, { strokeDashoffset: 0 }], { duration: (s.dd ?? 0.7) * 1000, easing: "ease-in-out" }); });
      (s.lit || []).forEach((id) => S.els[id] && S.els[id].el.classList.add("lit"));
      (s.unlit || []).forEach((id) => S.els[id] && S.els[id].el.classList.remove("lit"));
      if (s.count) countUp(S.els[s.count[0]].el.querySelector("[data-n]"), s.count[1]);
    }, s.t * 1000));
    const end = Math.max(...S.steps.map((s) => s.t + (s.d ?? 0))) + 0.4;
    S.timers.push(setTimeout(() => {
      S.world.animate([{ transform: camT(cam) }, { transform: camT(S.restCam) }],
        { duration: 1300, easing: "cubic-bezier(.45,.05,.2,1)", fill: "forwards" });
    }, end * 1000));
  }
  function countUp(el, n) {
    if (!el) return; const t0 = performance.now();
    const step = (t) => { const k = Math.min(1, (t - t0) / 900); el.textContent = Math.round(n * k).toLocaleString(FR ? "fr-FR" : "en"); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------------ les scènes (réponses réelles)
  const BUILD = {};

  BUILD.reprise = (S, d, A) => {
    const r = d.scenes.reprise;
    const base = S.art("base", r.base, 40, 70, 330, { large: true, cap: `Van Gogh, <i>${L("Le Semeur, d'après Millet", "The Sower, after Millet")}</i>, 1889` });
    S.text("q", 850, 40, L("Voisines · regard « forme »", "Neighbours · \"form\" regard"), "lbl");
    r.neighbors.forEach((n, i) => {
      const k = "n" + i;
      S.art(k, n.id, 850 + (i % 2) * 165, 90 + Math.floor(i / 2) * 265, 135, { cap: `<b>${L("rang", "rank")} ${i + 1}</b> · ${short(A[n.id].artist)}, ${A[n.id].date}<br><span class="mono">${num(n.score, 3)}</span>` });
    });
    const m = S.art("match", r.match, 440, 70, 330, { large: true, cap: `Millet, <i>${L("Le Semeur", "The Sower")}</i>, 1850 · ${L("rang 2", "rank 2")}` });
    S.link("l0", "n1", "match", "link soft", 0.15);
    r.pairs.forEach((p, i) => { S.box("za" + i, "base", p.a); S.box("zb" + i, "match", p.b); S.link("zl" + i, "za" + i, "zb" + i, "link", i % 2 ? 0.08 : -0.08); });
    S.text("note", 40, 690, L("La 1ʳᵉ voisine est la copie que Van Gogh fit en 1881 ; l'original de Millet vient au 2ᵉ rang.",
      "The 1st neighbour is the copy Van Gogh made in 1881; Millet's original comes 2nd."), "note");
    S.at(0, { cam: [20, 40, 560], show: ["q"] })
      .at(0.9, { cam: [700, 20, 520], d: 1.4 })
      .at(1.5, { show: ["n0"] }).at(1.75, { show: ["n1"] }).at(2.0, { show: ["n2"] }).at(2.25, { show: ["n3"] })
      .at(2.8, { lit: ["n1"] })
      .at(3.3, { cam: [0, 20, 1200], d: 1.3, draw: ["l0"], show: ["match"] })
      .at(4.6, { draw: ["za0", "zb0"], lit: ["za0", "zb0"] }).at(4.9, { draw: ["zl0"] })
      .at(5.3, { draw: ["za1", "zb1", "zl1"] }).at(5.7, { draw: ["za2", "zb2", "zl2"] }).at(6.1, { draw: ["za3", "zb3", "zl3"] })
      .at(6.6, { show: ["note"] });
    void base; void m;
  };

  BUILD.motif = (S, d, A) => {
    const r = d.scenes.motif;
    S.text("q", 40, 34, `<span class="field">${r.query}</span> <span class="muted">${L("· recherche de zone dans 1,6 million de zones", "· zone search in 1.6 million zones")}</span>`, "lbl");
    const cams = [];
    r.hits.forEach((h, i) => {
      const x = 40 + i * 190, y = 120 + (i % 2) * 60;
      const o = S.art("a" + i, h.id, x, y, 170, { large: true, cap: `${short(A[h.id].artist)}, ${A[h.id].date}` });
      const b = S.box("b" + i, "a" + i, h.box);
      cams.push([b.cx - 170, b.cy - 106, 340]); void o;
    });
    S.at(0, { cam: [0, 0, 1200], show: ["q"] });
    r.hits.forEach((_, i) => S.at(0.5 + i * 0.18, { show: ["a" + i] }));
    S.at(1.8, { cam: cams[0], d: 1.2 }).at(2.6, { draw: ["b0"], lit: ["b0"] })
      .at(3.2, { cam: cams[2], d: 1.1 }).at(3.9, { draw: ["b2"], lit: ["b2"] })
      .at(4.5, { cam: cams[4], d: 1.1 }).at(5.2, { draw: ["b4"], lit: ["b4"] })
      .at(5.8, { cam: [0, 0, 1200], d: 1.2, draw: ["b1", "b3", "b5"], lit: ["b1", "b3", "b5"] });
    S.text("note", 40, 560, L("Le crâne du <i>Saint François</i> d'El Greco, la <i>Pyramide de crânes</i> de Cézanne, les armoiries de Dürer : la zone est encadrée à chaque fois.",
      "The skull in El Greco's <i>Saint Francis</i>, Cézanne's <i>Pyramid of Skulls</i>, Dürer's coat of arms: the zone is boxed each time."), "note");
    S.at(6.6, { show: ["note"] });
  };

  BUILD.motif2 = (S, d, A) => {
    const r = d.scenes.motif2;
    S.text("q", 40, 34, `<span class="field">${r.query}</span>`, "lbl");
    const cams = [];
    r.hits.forEach((h, i) => {
      // cinq colonnes, deux rangées ; chaque œuvre tient dans une case de 200 × 250
      const a = A[h.id], col = i % 5, row = Math.floor(i / 5), wide = a.w / a.h > 200 / 250;
      S.art("a" + i, h.id, 40 + col * 228, 100 + row * 320, wide ? 200 : 250, { byH: !wide, large: true,
        cap: `${short(a.artist)}, ${a.date || ""} · ${L("rang", "rank")} ${h.rank}` });
      const b = S.box("b" + i, "a" + i, h.box);
      cams.push([b.cx - 150, b.cy - 94, 300]);
    });
    S.at(0, { cam: [0, 0, 1200], show: ["q"] });
    r.hits.forEach((_, i) => S.at(0.4 + i * 0.12, { show: ["a" + i] }));
    [0, 3, 6, 8].forEach((k, n) => S.at(1.8 + n * 1.3, { cam: cams[k], d: 1.0 }).at(2.5 + n * 1.3, { draw: ["b" + k], lit: ["b" + k] }));
    S.at(7.2, { cam: [0, 0, 1200], d: 1.2, draw: r.hits.map((_, i) => "b" + i).filter((k) => !["b0", "b3", "b6", "b8"].includes(k)),
      lit: r.hits.map((_, i) => "b" + i) });
  };

  BUILD.theme = (S, d, A) => {
    const r = d.scenes.theme;
    S.text("q", 40, 34, `<span class="field">${r.query}</span> <span class="muted">${L("· phrase libre (SigLIP 2)", "· free text (SigLIP 2)")}</span>`, "lbl");
    let x = 40, y = 110; const rowH = 190;
    r.hits.forEach((h, i) => {
      const a = A[h.id], w = Math.min(rowH * a.w / a.h, 640);
      if (x + w > 1170) { x = 40; y += rowH + 90; }
      S.art("a" + i, h.id, x, y, w, { cap: `<b>${L("rang", "rank")} ${h.rank}</b> · ${short(a.artist)}${a.date ? ", " + a.date : ""}<br><span class="mono">${num(h.score, 3)}</span>` });
      x += w + 28;
    });
    S.at(0, { cam: [0, 0, 700], show: ["q"] });
    r.hits.forEach((_, i) => S.at(0.6 + i * 0.35, { show: ["a" + i] }));
    S.at(0.8, { cam: [500, 0, 700], d: 2.0 }).at(2.9, { cam: [0, 300, 700], d: 1.4 }).at(4.4, { cam: [500, 300, 700], d: 1.6 })
      .at(2.0, { lit: ["a0"] });
  };

  BUILD.geste = (S, d, A) => {
    const r = d.scenes.geste;
    const a = S.art("a", r.a, 40, 80, 560, { large: true, cap: L("Titien, <i>Vénus</i>, 1565", "Titian, <i>Venus</i>, 1565") });
    const b = S.art("b", r.b, 640, 120, 520, { large: true, cap: L("Mantegna, <i>Le Christ au jardin des Oliviers</i>, 1455", "Mantegna, <i>Agony in the Garden</i>, 1455") });
    const draw = (key, on, k) => {
      const o = S.els[on], P = k.map(([x, y, c]) => [o.x + x * o.w, o.y + y * o.h, c]);
      let dd = "";
      r.limbs.forEach(([i, j]) => { if (P[i][2] > r.thr && P[j][2] > r.thr) dd += `M${P[i][0]} ${P[i][1]} L${P[j][0]} ${P[j][1]} `; });
      S.path(key + "s", dd, "bones");
      P.forEach(([x, y, c], i) => { if (c > r.thr) S.dot(key + i, x, y, 5, "joint"); });
      return P;
    };
    const PA = draw("ka", "a", r.kpts_a), PB = draw("kb", "b", r.kpts_b);
    const MIRROR = { 1: 2, 2: 1, 3: 4, 4: 3, 5: 6, 6: 5, 7: 8, 8: 7, 9: 10, 10: 9, 11: 12, 12: 11, 13: 14, 14: 13, 15: 16, 16: 15 };
    const keep = [0, 9, 10, 11, 15].filter((i) => PA[i][2] > r.thr && PB[r.mirrored ? (MIRROR[i] ?? i) : i][2] > r.thr);
    keep.forEach((i, n) => S.link("lk" + n, "ka" + i, "kb" + (r.mirrored ? (MIRROR[i] ?? i) : i), "link", n % 2 ? 0.1 : -0.1));
    const joints = (k, P) => P.map((p, i) => (p[2] > r.thr ? k + i : null)).filter(Boolean);
    const fa = r.raw_a.box, fb = r.raw_b.box;
    const camOn = (o, bx) => { const cx = o.x + (bx[0] + bx[2]) / 2 * o.w, cy = o.y + (bx[1] + bx[3]) / 2 * o.h, w = Math.max((bx[2] - bx[0]) * o.w * 1.6, 380); return [cx - w / 2, cy - w * 0.3125, w]; };
    S.text("note", 40, 690, L(`Même pose, en miroir (similarité ${num(r.score, 2)}) : une formule gestuelle, pas la preuve qu'un artiste a vu l'autre.`,
      `Same pose, mirrored (similarity ${num(r.score, 2)}): a gestural formula, not proof that one artist saw the other.`), "note");
    S.at(0, { cam: camOn(a, fa) }).at(0.5, { draw: ["kas"], show: joints("ka", PA) })
      .at(1.6, { cam: camOn(b, fb), d: 1.3 }).at(2.4, { draw: ["kbs"], show: joints("kb", PB) })
      .at(3.4, { cam: [0, 30, 1200], d: 1.3 });
    keep.forEach((_, n) => S.at(4.4 + n * 0.25, { draw: ["lk" + n] }));
    S.at(5.8, { show: ["note"], lit: ["a", "b"] });
  };

  BUILD.catalogue = (S, d, A) => {
    const r = d.scenes.catalogue;
    const c = S.art("s", r.suspect, 230, 250, 250, { large: true, cap: `<span class="strike">Sisley</span>, 1894 <span class="tag">${L("à vérifier", "to check")}</span>` });
    const ring = [[40, 60], [270, 40], [500, 60], [40, 470], [270, 500], [500, 470]];
    r.neighbors.forEach((id, i) => { S.art("m" + i, id, ring[i][0], ring[i][1], 170, { cap: `Monet, ${A[id].date}` }); S.link("ml" + i, "m" + i, "s", "link soft", 0.05); });
    S.text("t1", 40, 680, L("Ses 10 voisines étiquetées sont des Monet :<br>erreur de catalogue, ou Sisley très proche de Monet ?",
      "Its 10 labelled neighbours are all Monets:<br>a catalogue error, or a Sisley very close to Monet?"), "note");
    const d0 = S.art("d0", r.dup[0], 800, 120, 240, { byH: true, cap: `Corot, 1873<br><b>${L("romantisme", "Romanticism")}</b>` });
    const d1 = S.art("d1", r.dup[1], 800 + d0.w + 30, 120, 240, { byH: true, cap: `Corot, 1873<br><b>${L("réalisme", "Realism")}</b>` });
    S.text("t2", 800, 60, L("La même image, entrée deux fois", "The same image, entered twice"), "lbl");
    S.text("t3", 800, 430, L(`Mêmes pixels (cosinus ${num(r.dup_cos || 1, 2)}),<br>deux styles dans le catalogue`, `Same pixels (cosine ${num(r.dup_cos || 1, 2)}),<br>two styles in the catalogue`), "muted-t");
    S.link("dl", "d0", "d1", "link hotline", 0.5);
    S.at(0, { cam: [0, 0, 760] });
    r.neighbors.forEach((_, i) => S.at(0.4 + i * 0.2, { show: ["m" + i], draw: ["ml" + i] }));
    S.at(1.9, { lit: ["s"] }).at(2.4, { show: ["t1"] })
      .at(3.4, { cam: [700, 0, 560], d: 1.3, show: ["t2"] }).at(4.3, { show: ["d1"], draw: ["dl"], lit: ["d0", "d1"] })
      .at(5.0, { show: ["t3"] });
    void c; void d0; void d1;
  };

  BUILD.regards = (S, d, A) => {
    const r = d.scenes.regards;
    const a = S.art("a", r.a, 40, 40, 420, { byH: true, large: true, cap: L("d'après Rembrandt, <i>La Fille de Jaïre</i> (gravure)", "after Rembrandt, <i>Jairus' Daughter</i> (engraving)") });
    const b = S.art("b", r.b, 40 + a.w + 50, 40, 420, { byH: true, large: true, cap: "Bryullov, 1831" });
    S.link("lab", "a", "b", "link", 0);
    const pct = Math.round(r.centile_sujet * 100);
    S.text("m1", 40, 560, `<b>${L("Forme", "Form")}</b> <span class="bar"><i style="width:97%"></i></span> <span class="mono">${L("voisine n°", "neighbour no.")} ${r.rank_forme}</span>`, "metric");
    S.text("m2", 40, 615, `<b>${L("Sujet", "Subject")}</b> <span class="bar dim"><i style="width:${pct}%"></i></span> <span class="mono">${L("centile", "percentile")} ${pct}</span>`, "metric");
    S.text("m3", 760, 560, L("<b class=\"hot-t\">Désaccord</b> : même mise en page<br>(un lit, une lumière), autre sujet", "<b class=\"hot-t\">Disagreement</b>: same layout<br>(a bed, a light), another subject"), "lbl");
    S.at(0, { cam: [0, 0, 640] }).at(0.9, { cam: [b.x - 60, 0, 640], d: 1.6 }).at(1.2, { lit: ["a"] }).at(2.2, { lit: ["b"] })
      .at(2.7, { cam: [0, 0, 1200], d: 1.2, draw: ["lab"] })
      .at(3.6, { show: ["m1"] }).at(4.2, { show: ["m2"] }).at(4.9, { show: ["m3"] });
  };

  BUILD.filtres = (S, d) => {
    const r = d.scenes.filtres, pts = d.carte.pts, lit = new Set(r.sample);
    let base = "", hot = "";
    for (let i = 0; i < pts.length / 3; i++) {
      const x = 40 + (pts[3 * i] / 999) * 760, y = 40 + (1 - pts[3 * i + 1] / 999) * 640;
      if (lit.has(i)) hot += `M${x.toFixed(1)} ${y.toFixed(1)}h0 `; else base += `M${x.toFixed(1)} ${y.toFixed(1)}h0 `;
    }
    S.path("base", base, "mapdots");
    S.path("hot", hot, "mapdots-hot");
    S.text("c1", 860, 90, `${L("style", "style")} <span class="chip">Baroque</span>`, "lbl");
    S.text("c2", 860, 150, `${L("genre", "genre")} <span class="chip">portrait</span>`, "lbl");
    S.text("n", 860, 240, `<span class="big"><span data-n>${r.total}</span></span><br>${L("œuvres dans le corpus,<br>allumées en 14 ms", "works in the collection,<br>lit in 14 ms")}`, "lbl");
    S.text("s", 860, 380, L(`Sur cet échantillon de 6 000 : ${r.sample.length} points.`, `In this sample of 6,000: ${r.sample.length} dots.`), "muted-t");
    S.at(0, { cam: [0, 0, 1200] }).at(0.5, { show: ["c1"] }).at(1.1, { show: ["c2"] })
      .at(1.6, { show: ["hot", "n"], count: ["n", r.total] }).at(2.6, { cam: [100, 60, 640], d: 1.4 }).at(4.4, { show: ["s"] });
  };

  BUILD.notions = (S, d, A) => {
    const r = d.scenes.notions;
    S.text("q", 40, 30, L(`Notion apprise n° ${r.feature} · regard « forme » · nommée par Iconclass : <b>« ${r.label} »</b> (${r.iconclass.notation})`,
      `Learned notion no. ${r.feature} · "form" regard · named with Iconclass: <b>"ladder"</b> (${r.iconclass.notation})`), "lbl");
    // chaque œuvre tient dans une case de 250 × 230, en quatre colonnes et deux rangées
    r.works.forEach((w, i) => {
      const a = A[w.id], col = i % 4, row = Math.floor(i / 4), wide = a.w / a.h > 250 / 230;
      S.art("w" + i, w.id, 40 + col * 285, 80 + row * 300, wide ? 250 : 230, { byH: !wide, cap: `${short(a.artist)}, ${a.date || ""} · ${L("rang", "rank")} ${w.rank}` });
    });
    S.at(0, { cam: [0, 0, 640], show: ["q"] });
    r.works.forEach((_, i) => S.at(0.6 + i * 0.4, { lit: ["w" + i] }));
    S.at(1.0, { cam: [560, 0, 640], d: 1.6 }).at(2.6, { cam: [0, 280, 640], d: 1.2 }).at(3.8, { cam: [560, 280, 640], d: 1.2 });
    S.text("note", 40, 680, L(`Ce sont des Descentes de croix : l'échelle y est un motif récurrent, que le catalogue n'indexe pas (${r.total} œuvres en tout).`,
      `These are Depositions: the ladder is a recurring motif there, one the catalogue does not index (${r.total} works in all).`), "note");
    S.at(5.0, { show: ["note"] });
  };

  BUILD.axes = (S, d, A) => {
    // deux rangées (1500–1549, 1550–1599) ; chaque vignette est reliée à sa position exacte sur l'axe
    const r = d.scenes.axes, X = (z) => 620 + z * 300, TW = 96, TH = 120;
    S.text("l1", 60, 690, L("← linéaire : contours nets", "← linear: firm outlines"), "muted-t");
    S.text("l2", 1140, 690, L("pictural : touche visible →", "painterly: visible touch →"), "muted-t right");
    [["a", 40, "1500–1549"], ["b", 345, "1550–1599"]].forEach(([k, y, lab]) => {
      const ay = y + 250;
      S.path("ax" + k, `M80 ${ay} L1140 ${ay}`, "axis");
      S.text("y" + k, 40, y, lab, "mono-t");
      r[k].works.forEach((w, i) => {
        const x = X(w.z);
        S.art(k + i, w.id, x - TW / 2, y + 40, 0, { box: [TW, TH], cap: `${short(A[w.id].artist)}<br><span class="mono">${num(w.z, 2)}</span>` });
        S.path(k + "s" + i, `M${x} ${y + 40 + TH + 44} L${x} ${ay}`, "link soft");
        S.dot(k + "d" + i, x, ay, 6, "joint");
      });
      S.path("m" + k, `M${X(r[k].median)} ${ay - 18} L${X(r[k].median)} ${ay + 18}`, "median");
      S.text("mt" + k, X(r[k].median) + 8, ay + 6, `${L("médiane", "median")} ${num(r[k].median, 2)}`, "mono-t hot-t");
    });
    S.path("swing", `M${X(r.a.median)} 310 C ${X(r.a.median)} 420, ${X(r.b.median)} 480, ${X(r.b.median)} 577`, "link");
    S.at(0, { cam: [0, 0, 760] });
    r.a.works.forEach((_, i) => S.at(0.3 + i * 0.2, { show: ["a" + i], draw: ["as" + i] }));
    S.at(1.4, { draw: ["ma"], show: ["mta"] }).at(2.0, { cam: [300, 300, 760], d: 1.4 });
    r.b.works.forEach((_, i) => S.at(2.5 + i * 0.2, { show: ["b" + i], draw: ["bs" + i] }));
    S.at(3.6, { draw: ["mb"], show: ["mtb"] }).at(4.2, { cam: [0, 0, 1200], d: 1.2 }).at(5.0, { draw: ["swing"] });
  };

  BUILD.trace = (S, d) => {
    const r = d.scenes.reprise;
    S.text("q", 40, 50, `<span class="bubble">${L("Cherche les reprises du <i>Semeur</i> de Millet", "Find reworkings of Millet's <i>Sower</i>")}</span>`, "lbl");
    S.text("t1", 60, 130, "similar_artworks(id=41274, space=\"forme\")", "mono-t");
    S.text("t2", 60, 165, "why_similar(79294, 41274)", "mono-t");
    S.art("a", r.base, 60, 230, 230, { cap: "Van Gogh, 1889" });
    S.art("b", r.match, 320, 230, 230, { cap: "Millet, 1850" });
    S.text("nb", 640, 250,`<span class="card"><b>${L("Carnet de recherche", "Research notebook")}</b><br>${L("+ piste : Van Gogh d'après Millet, 1889 (à vérifier)", "+ lead: Van Gogh after Millet, 1889 (to check)")}</span>`, "lbl");
    S.text("pk", 760, 420,`<span class="pack"><b>Research Pack</b> <span class="mono">.zip</span><br>${["images/", L("métadonnées sourcées", "sourced metadata"), L("scores par regard", "scores per regard"), L("méthode et modèles", "method and models"), L("fiche du corpus", "corpus datasheet")].join("<br>")}</span>`, "lbl");
    S.link("la", "b", "nb", "link soft", 0.1); S.link("lp", "nb", "pk", "link", 0.25);
    S.at(0, { cam: [0, 0, 760], show: ["q"] }).at(0.7, { show: ["t1"] }).at(1.1, { show: ["t2"] })
      .at(1.5, { show: ["a", "b"] }).at(2.2, { draw: ["la"], show: ["nb"] })
      .at(3.0, { cam: [0, 0, 1200], d: 1.2 }).at(3.6, { draw: ["lp"], show: ["pk"], lit: ["pk"] });
  };

  // ------------------------------------------------------------------ agrandir une démonstration
  // Boîte de dialogue modale (showModal : focus piégé, Échap) ; fermeture aussi par un clic à côté
  // (closedby="any", avec un repli là où il manque) et par un bouton visible. La planche y est déplacée,
  // puis remise à sa place à la fermeture ; elle se remet à l'échelle toute seule.
  let zoom = null;
  function zoomDialog() {
    if (zoom) return zoom;
    const dlg = document.createElement("dialog");
    dlg.className = "zoom"; dlg.setAttribute("closedby", "any");
    dlg.setAttribute("aria-labelledby", "zoom-title");
    dlg.innerHTML = `<div class="zoom-bar"><span class="zoom-title" id="zoom-title"></span>
      <button type="button" class="zoom-replay">${L("Rejouer", "Replay")}</button>
      <button type="button" class="zoom-close">${L("Fermer", "Close")}</button></div><div class="zoom-slot"></div>`;
    document.body.append(dlg);
    if (!("closedBy" in HTMLDialogElement.prototype)) {
      dlg.addEventListener("click", (e) => {
        if (e.target !== dlg) return;
        const r = dlg.getBoundingClientRect();
        if (r.top <= e.clientY && e.clientY <= r.bottom && r.left <= e.clientX && e.clientX <= r.right) return;
        dlg.close();
      });
    }
    zoom = { dlg, fig: null, ph: null };
    dlg.querySelector(".zoom-close").addEventListener("click", () => dlg.close());
    dlg.querySelector(".zoom-replay").addEventListener("click", () => zoom.fig && play(zoom.fig._scene));
    dlg.addEventListener("close", () => {
      if (!zoom.fig) return;
      const st = dlg.querySelector(".stage");
      zoom.ph.replaceWith(st);
      zoom.fig.querySelector(".zoom-open")?.focus();
      zoom.fig = null;
    });
    return zoom;
  }
  function openZoom(fig) {
    const z = zoomDialog();
    if (z.fig) return;
    const st = fig.querySelector(".stage");
    z.ph = document.createElement("div"); z.ph.className = "stage-ph"; z.ph.style.height = st.offsetHeight + "px";
    st.replaceWith(z.ph);
    z.dlg.querySelector(".zoom-slot").append(st);
    z.dlg.querySelector(".zoom-title").textContent = fig.closest(".plate")?.querySelector("h3")?.textContent || "";
    z.dlg.querySelector(".zoom-replay").hidden = !motionOK;
    z.fig = fig;
    z.dlg.showModal();
    if (motionOK) play(fig._scene);
  }

  // ------------------------------------------------------------------ montage
  const figures = [...document.querySelectorAll("figure.scene[data-scene]")];
  if (!figures.length || !window.fetch) return;
  Promise.all([fetch(BASE + "scenes.json").then((r) => r.json()), fetch(BASE + "carte.json").then((r) => r.json())])
    .then(([data, carte]) => {
      data.carte = carte;
      const io = motionOK ? new IntersectionObserver((es) => es.forEach((e) => {
        // 30 % visible suffit : une planche haute dans une fenêtre basse n'atteindrait jamais 50 %
        if (e.isIntersecting && e.intersectionRatio >= 0.3) { play(e.target._scene); io.unobserve(e.target); } }),
        { threshold: [0.3, 0.6] }) : null;
      for (const fig of figures) {
        const make = BUILD[fig.dataset.scene];
        if (!make) continue;
        const S = Scene(fig, data);
        make(S, data, data.art);
        S.world.append(S.svg);                       // zones et liens par-dessus les œuvres
        fig._scene = S;
        const stage = fig.querySelector(".stage");
        stage.setAttribute("role", "img"); stage.setAttribute("aria-label", fig.dataset.label || "");
        restState(S);
        // agrandir : un clic sur la planche, ou le bouton (clavier) placé avant « Rejouer »
        const open = document.createElement("button");
        open.type = "button"; open.className = "replay zoom-open"; open.textContent = L("Agrandir", "Enlarge");
        const cartel = fig.querySelector(".cartel");
        if (cartel) { const box = document.createElement("span"); box.className = "cartel-actions";
          box.append(open); const rp = cartel.querySelector(".replay:not(.zoom-open)"); if (rp) box.append(rp); cartel.append(box); }
        open.addEventListener("click", () => openZoom(fig));
        stage.addEventListener("click", () => { if (!zoom || zoom.fig !== fig) openZoom(fig); });
        const btn = fig.querySelector(".replay:not(.zoom-open)");
        if (motionOK) {
          arm(S); io.observe(fig);
          if (btn) { btn.hidden = false; btn.addEventListener("click", () => play(S)); }
        }
      }
    })
    .catch(() => { /* sans données, la planche garde son texte ; la légende décrit la démonstration */ });
})();
