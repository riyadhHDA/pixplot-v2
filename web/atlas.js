/* PixPlot v2 — Atlas : carte interactive du corpus (deck.gl, sans étape de compilation).
 *
 * Vue d'ensemble : un point par œuvre, coloré selon le mode choisi.
 * En zoomant : les vignettes remplacent les points (seulement celles visibles à l'écran,
 * pour rester fluide avec des centaines de milliers d'œuvres).
 * Clic : fiche de l'œuvre + liens vers ses plus proches voisines.
 */
(() => {
  "use strict";
  const { Deck, OrthographicView, ScatterplotLayer, IconLayer, TextLayer, LineLayer, LinearInterpolator } = deck;

  const WORLD = 1000;            // les coordonnées [-1, 1] deviennent [-1000, 1000]
  const MAX_ICONS = 1500;        // vignettes affichées au plus à la fois
  const PALETTE = [
    [230, 159, 0], [86, 180, 233], [0, 158, 115], [240, 228, 66], [0, 114, 178], [213, 94, 0],
    [204, 121, 167], [148, 103, 189], [140, 86, 75], [127, 201, 127], [253, 192, 134], [190, 174, 212],
    [255, 127, 80], [102, 194, 165], [252, 141, 98], [141, 160, 203], [231, 138, 195], [166, 216, 84],
    [255, 217, 47], [229, 196, 148], [179, 179, 179], [27, 158, 119], [217, 95, 2], [117, 112, 179],
  ];
  const GREY = [110, 110, 110];
  const LABELS = { artist: "Artiste", style: "Style", genre: "Genre", date: "Date", source: "Source" };
  // Valeurs écrites en « identifiant » (claude-monet, Early_Renaissance) : on les rend lisibles.
  // Les autres (titres, dates, sources, cotes) sont affichées telles quelles.
  const SLUG_KEYS = new Set(["artist", "style", "genre"]);
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pretty = (v) => String(v ?? "").replace(/_/g, " ").replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

  const state = {
    info: null, map: null, clusters: [], n: 0,
    positions: null, rowOf: new Map(),
    colorMode: "cluster", highlight: null, highlightLabel: "",
    selected: null, selectedData: null,
    viewState: { target: [0, 0, 0], zoom: 0, minZoom: -4, maxZoom: 9 },
    fitZoom: 0, iconSize: 20, icons: [], iconTimer: null,
    searchStatus: { region: false, text: false }, lastResults: null, drawing: false,
  };
  let deckgl;
  window.pixplot = state; // pour inspecter l'Atlas depuis la console du navigateur

  // ------------------------------------------------------------------ chargement
  async function getJSON(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`${url} : ${r.status} ${await r.text()}`);
    return r.json();
  }

  async function init() {
    try {
      [state.info, state.map, state.clusters] = await Promise.all([
        getJSON("/api/info"), getJSON("/api/map"), getJSON("/api/clusters"),
      ]);
    } catch (err) {
      $("stats").textContent = "Erreur de chargement";
      $("map").innerHTML = `<p style="padding:24px;color:#e0b040">${esc(err.message)}</p>`;
      return;
    }
    const m = state.map;
    state.n = m.ids.length;
    state.positions = new Float32Array(state.n * 2);
    for (let i = 0; i < state.n; i++) {
      state.positions[2 * i] = m.x[i] * WORLD;
      state.positions[2 * i + 1] = m.y[i] * WORLD;
      state.rowOf.set(m.ids[i], i);
    }
    state.iconSize = Math.max(2, Math.min(40, (2 * WORLD / Math.sqrt(state.n)) * 0.9));
    try { state.searchStatus = await getJSON("/api/search/status"); } catch { /* recherches avancées indisponibles */ }
    const textOpt = $("search-mode").querySelector('option[value="text"]');
    textOpt.disabled = !state.searchStatus.text;
    textOpt.title = state.searchStatus.text ? "" : "Calculez d'abord les vecteurs SigLIP 2";
    buildColorOptions();
    renderGroups();
    setupDeck();
    updateStats();
    wireUI();
    const fromHash = parseInt(location.hash.replace("#oeuvre-", ""), 10);
    if (state.rowOf.has(fromHash)) select(fromHash, true);
  }

  // ------------------------------------------------------------------ couleurs
  function buildColorOptions() {
    const sel = $("colorby");
    const opts = [["cluster", "Groupes (e-means)"]];
    if (state.map.hdbscan) opts.push(["hdbscan", "Familles (HDBSCAN)"]);
    opts.push(["atypicality", "Atypicité"]);
    for (const key of Object.keys(state.map.categories)) opts.push([`meta:${key}`, LABELS[key] || pretty(key)]);
    sel.innerHTML = opts.map(([v, l]) => `<option value="${v}">${esc(l)}</option>`).join("");
  }

  function categoryInfo(key) {
    const cat = state.map.categories[key];
    const counts = new Array(cat.values.length).fill(0);
    for (const c of cat.codes) counts[c]++;
    const ranked = counts.map((c, code) => [code, c])
      .filter(([code]) => cat.values[code] && !/^unknown/i.test(cat.values[code]))
      .sort((a, b) => b[1] - a[1]);
    const colorOf = new Map(ranked.slice(0, 12).map(([code], k) => [code, PALETTE[k]]));
    return { cat, counts, ranked, colorOf };
  }

  function baseColor(i, ctx) {
    const mode = state.colorMode;
    if (mode === "cluster") return PALETTE[state.map.cluster[i] % PALETTE.length];
    if (mode === "hdbscan") {
      const h = state.map.hdbscan[i];
      return h < 0 ? [235, 235, 235] : PALETTE[h % PALETTE.length];
    }
    if (mode === "atypicality") {
      const t = state.map.atypicality[i];
      return [40 + 215 * t, 70 + 110 * t, 140 - 100 * t];
    }
    return ctx.colorOf.get(ctx.cat.codes[i]) || GREY;
  }

  function colorArray() {
    const out = new Uint8Array(state.n * 4);
    const ctx = state.colorMode.startsWith("meta:") ? categoryInfo(state.colorMode.slice(5)) : null;
    for (let i = 0; i < state.n; i++) {
      const c = baseColor(i, ctx);
      const on = !state.highlight || state.highlight.has(i);
      out[4 * i] = c[0]; out[4 * i + 1] = c[1]; out[4 * i + 2] = c[2];
      out[4 * i + 3] = on ? 230 : 28;
    }
    return out;
  }

  function renderLegend() {
    const el = $("legend");
    const mode = state.colorMode;
    if (mode === "atypicality") {
      el.innerHTML = `<div>Atypicité</div><div class="ramp" style="background:linear-gradient(90deg,rgb(40,70,140),rgb(255,180,40))"></div>
        <div class="ends"><span>bien entourée</span><span>isolée</span></div>`;
      return;
    }
    if (mode === "cluster" || mode === "hdbscan") { el.innerHTML = ""; return; }
    const key = mode.slice(5);
    const { cat, ranked, colorOf } = categoryInfo(key);
    const rows = ranked.slice(0, 12).map(([code, c]) =>
      `<div class="row" data-code="${code}"><span class="swatch" style="background:rgb(${colorOf.get(code).join(",")})"></span>${esc(pretty(cat.values[code]))} <span style="color:var(--muted)">${c}</span></div>`);
    if (ranked.length > 12) rows.push(`<div class="row" style="cursor:default"><span class="swatch" style="background:rgb(${GREY.join(",")})"></span>autres (${ranked.length - 12})</div>`);
    el.innerHTML = `<div style="margin-bottom:4px">${esc(LABELS[key] || pretty(key))} — cliquez pour isoler</div>` + rows.join("");
    el.querySelectorAll(".row[data-code]").forEach((row) => row.addEventListener("click", () => {
      const code = Number(row.dataset.code);
      const set = new Set();
      cat.codes.forEach((c, i) => { if (c === code) set.add(i); });
      setHighlight(set, `${LABELS[key] || key} : ${pretty(cat.values[code])}`);
    }));
  }

  // ------------------------------------------------------------------ deck.gl
  function computeFit() {
    const el = $("map");
    return Math.log2(Math.max(50, Math.min(el.clientWidth, el.clientHeight)) / (2.2 * WORLD));
  }

  function onResize() {
    // Tant que l'utilisateur n'a pas bougé la carte, on garde la vue d'ensemble cadrée.
    const fit = computeFit();
    const changed = Math.abs(fit - state.fitZoom) > 1e-3;
    state.fitZoom = fit;
    if (changed && !state.userMoved) {
      state.viewState = { ...state.viewState, minZoom: fit - 2, zoom: fit, target: [0, 0, 0] };
      deckgl.setProps({ viewState: state.viewState });
    }
    scheduleIcons();
  }

  function setupDeck() {
    const el = $("map");
    const fit = computeFit();
    state.fitZoom = fit;
    state.viewState = { ...state.viewState, zoom: fit, minZoom: fit - 2 };
    deckgl = new Deck({
      parent: el,
      views: new OrthographicView({ id: "atlas", flipY: false }),
      viewState: state.viewState,
      controller: { dragRotate: false, doubleClickZoom: true, scrollZoom: { speed: 0.02, smooth: true } },
      onViewStateChange: ({ viewState, interactionState }) => {
        if (interactionState && (interactionState.isDragging || interactionState.isZooming || interactionState.isPanning)) state.userMoved = true;
        state.viewState = viewState;
        deckgl.setProps({ viewState });
        scheduleIcons();
      },
      getCursor: ({ isHovering, isDragging }) => (isDragging ? "grabbing" : isHovering ? "pointer" : "grab"),
      onHover: showTooltip,
      onClick: (info) => {
        const id = pickedId(info);
        if (id != null) select(id, false);
      },
      layers: [],
    });
    redraw();
    renderLegend();
  }

  function pickedId(info) {
    if (!info || !info.layer) return null;
    if (info.layer.id === "icons") return info.object?.id ?? null;
    if (info.layer.id === "points" && info.index >= 0) return state.map.ids[info.index];
    return null;
  }

  function scheduleIcons() {
    clearTimeout(state.iconTimer);
    state.iconTimer = setTimeout(() => { computeIcons(); redraw(); }, 120);
  }

  function computeIcons() {
    const vs = state.viewState;
    const el = $("map");
    const scale = Math.pow(2, vs.zoom);
    const onScreen = state.iconSize * scale; // taille d'une vignette en pixels
    if (onScreen < 14) { state.icons = []; $("hint").textContent = "Zoomez pour voir les vignettes · clic : fiche de l'œuvre"; return; }
    const halfW = el.clientWidth / 2 / scale + state.iconSize, halfH = el.clientHeight / 2 / scale + state.iconSize;
    const [cx, cy] = vs.target;
    let visible = [];
    for (let i = 0; i < state.n; i++) {
      if (state.highlight && !state.highlight.has(i)) continue;
      const x = state.positions[2 * i], y = state.positions[2 * i + 1];
      if (Math.abs(x - cx) < halfW && Math.abs(y - cy) < halfH) visible.push(i);
    }
    if (visible.length > MAX_ICONS) {
      // Trop d'œuvres à l'écran : on montre d'abord les plus représentatives (les moins atypiques).
      visible.sort((a, b) => state.map.atypicality[a] - state.map.atypicality[b]);
      visible = visible.slice(0, MAX_ICONS);
    }
    const px = onScreen > 90 ? 256 : 64;
    state.icons = visible.map((i) => {
      const a = state.map.aspect[i] || 1;
      const w = a >= 1 ? 64 : Math.round(64 * a), h = a >= 1 ? Math.round(64 / a) : 64;
      return { i, id: state.map.ids[i], w, h, px };
    });
    $("hint").textContent = `${visible.length} vignettes à l'écran · clic : fiche de l'œuvre`;
  }

  function redraw() {
    const layers = [];
    const showingIcons = state.icons.length > 0;
    layers.push(new ScatterplotLayer({
      id: "points",
      data: { length: state.n, attributes: {
        getPosition: { value: state.positions, size: 2 },
        getFillColor: { value: colorArray(), size: 4, normalized: true },
      } },
      radiusUnits: "pixels",
      getRadius: showingIcons ? 1.5 : 3,
      radiusMinPixels: 1, radiusMaxPixels: 6,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 255],
      updateTriggers: { getFillColor: [state.colorMode, state.highlightLabel] },
    }));
    if (showingIcons) {
      layers.push(new IconLayer({
        id: "icons",
        data: state.icons,
        getPosition: (d) => [state.positions[2 * d.i], state.positions[2 * d.i + 1]],
        getIcon: (d) => ({ url: `/api/thumb/${d.px}/${d.id}`, width: d.w * (d.px / 64), height: d.h * (d.px / 64), id: `${d.px}-${d.id}` }),
        getSize: state.iconSize,
        sizeUnits: "common",
        pickable: true,
        alphaCutoff: 0,
      }));
    }
    if (state.selectedData) {
      const s = state.selectedData;
      const from = [s.x * WORLD, s.y * WORLD];
      const links = s.neighbors.slice(0, 10).filter((n) => state.rowOf.has(n.id)).map((n) => {
        const j = state.rowOf.get(n.id);
        return { from, to: [state.positions[2 * j], state.positions[2 * j + 1]], score: n.score };
      });
      layers.push(new LineLayer({
        id: "links", data: links, getSourcePosition: (d) => d.from, getTargetPosition: (d) => d.to,
        getColor: [224, 176, 64, 200], getWidth: (d) => 1 + 3 * Math.max(0, d.score - 0.4), widthUnits: "pixels",
      }));
      layers.push(new ScatterplotLayer({
        id: "selected", data: [from], getPosition: (d) => d, radiusUnits: "pixels", getRadius: showingIcons ? state.iconSize * Math.pow(2, state.viewState.zoom) * 0.7 : 9,
        stroked: true, filled: false, getLineColor: [224, 176, 64], lineWidthUnits: "pixels", getLineWidth: 3,
      }));
    }
    if (!showingIcons && (state.colorMode === "cluster")) {
      layers.push(new TextLayer({
        id: "group-labels",
        data: state.clusters,
        getPosition: (d) => [d.center[0] * WORLD, d.center[1] * WORLD],
        getText: (d) => String(d.number),
        getSize: 13, getColor: [255, 255, 255],
        background: true, getBackgroundColor: (d) => [...PALETTE[d.cluster % PALETTE.length].map((c) => c * 0.35), 230],
        backgroundPadding: [5, 2], fontWeight: 700, fontFamily: "Segoe UI, sans-serif",
        getTextAnchor: "middle", getAlignmentBaseline: "center",
      }));
    }
    deckgl.setProps({ layers });
  }

  function flyTo(x, y, zoom) {
    // Un zoom vers une œuvre ou un groupe n'est plus « la vue d'ensemble » : un
    // redimensionnement (ouverture de la fiche…) ne doit pas l'annuler.
    state.userMoved = !(x === 0 && y === 0 && zoom === state.fitZoom);
    state.viewState = {
      ...state.viewState, target: [x, y, 0], zoom,
      transitionDuration: 700, transitionInterpolator: new LinearInterpolator(["target", "zoom"]),
    };
    deckgl.setProps({ viewState: state.viewState });
    scheduleIcons();
    setTimeout(scheduleIcons, 750);
  }

  // ------------------------------------------------------------------ infobulle
  function labelOf(i) {
    const bits = [];
    for (const key of ["artist", "style", "genre", "date"]) {
      const cat = state.map.categories[key];
      if (!cat) continue;
      const v = cat.values[cat.codes[i]];
      if (v && !/^unknown/i.test(v)) bits.push(pretty(v));
    }
    return bits.join(" · ") || `Œuvre ${state.map.ids[i]}`;
  }

  function showTooltip(info) {
    const tip = $("tooltip");
    const id = pickedId(info);
    if (id == null) { tip.hidden = true; return; }
    const i = state.rowOf.get(id);
    tip.innerHTML = `<img src="/api/thumb/256/${id}" alt=""><div>${esc(labelOf(i))}</div>
      <div style="color:var(--muted)">Groupe ${state.map.cluster[i] + 1} · n° ${id}</div>`;
    const rect = $("map").getBoundingClientRect();
    tip.style.left = `${Math.min(rect.left + info.x + 16, innerWidth - 200)}px`;
    tip.style.top = `${Math.min(rect.top + info.y + 16, innerHeight - 200)}px`;
    tip.hidden = false;
  }

  // ------------------------------------------------------------------ groupes
  function renderGroups() {
    $("groups").innerHTML = state.clusters.map((g) => {
      const dom = Object.entries(g.dominant).slice(0, 3).map(([k, vs]) =>
        `${esc(LABELS[k] || k)} : ${esc(pretty(vs[0].value))} (${Math.round(vs[0].share * 100)} %)`).join("<br>");
      const col = PALETTE[g.cluster % PALETTE.length].join(",");
      return `<li class="group" data-cluster="${g.cluster}">
        <img src="/api/thumb/256/${g.representative}" alt="" loading="lazy">
        <div><div class="title"><span class="swatch" style="background:rgb(${col})"></span>Groupe ${g.number}
          <span class="size">${g.size} œuvres</span></div><div class="dom">${dom}</div></div></li>`;
    }).join("");
    $("groups").querySelectorAll(".group").forEach((li) => li.addEventListener("click", () => {
      const c = Number(li.dataset.cluster);
      const g = state.clusters.find((x) => x.cluster === c);
      if (li.classList.contains("active")) { clearHighlight(); return; }
      const set = new Set();
      state.map.cluster.forEach((v, i) => { if (v === c) set.add(i); });
      setHighlight(set, `Groupe ${g.number}`);
      document.querySelectorAll(".group").forEach((x) => x.classList.toggle("active", x === li));
      flyTo(g.center[0] * WORLD, g.center[1] * WORLD, state.fitZoom + 1.6);
    }));
  }

  // ------------------------------------------------------------------ surbrillance
  function setHighlight(set, label) {
    state.highlight = set && set.size ? set : null;
    state.highlightLabel = label || "";
    computeIcons();
    redraw();
    updateStats();
  }
  function clearHighlight() {
    document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
    $("search").value = "";
    $("search-clear").hidden = true;
    setHighlight(null, "");
  }
  function updateStats() {
    const i = state.info;
    const base = `${state.n.toLocaleString("fr-FR")} œuvres · ${i.clusters} groupes · ${i.encoder} @${i.input_size}`;
    $("stats").textContent = state.highlight
      ? `${state.highlightLabel} : ${state.highlight.size.toLocaleString("fr-FR")} œuvres  —  ${base}`
      : base;
  }

  // ------------------------------------------------------------------ fiche
  async function select(id, fly) {
    let data;
    try { data = await getJSON(`/api/artwork/${id}`); } catch { return; }
    state.selected = id;
    state.selectedData = data;
    history.replaceState(null, "", `#oeuvre-${id}`);
    renderFiche(data);
    redraw();
    if (fly) flyTo(data.x * WORLD, data.y * WORLD, Math.max(state.viewState.zoom, state.fitZoom + 3));
  }

  function renderFiche(d) {
    const meta = Object.entries(d.metadata).filter(([, v]) => v).map(([k, v]) =>
      `<tr><th>${esc(LABELS[k] || pretty(k))}</th><td>${esc(SLUG_KEYS.has(k) ? pretty(v) : v)}${d.metadata_sources[k] ? `<small>source : ${esc(d.metadata_sources[k])}</small>` : ""}</td></tr>`).join("");
    const fam = d.hdbscan == null ? "" : d.hdbscan < 0
      ? `<span class="chip warn" title="HDBSCAN ne la rattache à aucune famille">Œuvre « à part »</span>`
      : `<span class="chip">Famille ${d.hdbscan + 1}</span>`;
    const atyp = Math.round(d.atypicality * 100);
    const neigh = d.neighbors.map((n) => `<button class="neighbor" data-id="${n.id}" title="${esc(n.label)}">
        <img src="/api/thumb/256/${n.id}" alt="" loading="lazy">
        <div class="score">${n.score.toFixed(3)} · groupe ${n.cluster ?? "?"}</div>
        <div class="lbl">${esc(pretty(n.label))}</div></button>`).join("");
    $("fiche-body").innerHTML = `
      <a class="hero" href="/api/image/${d.id}" target="_blank" rel="noopener" title="Ouvrir l'image originale">
        <img src="/api/thumb/1024/${d.id}" alt="${esc(d.label)}"></a>
      <div class="content">
        <h3>${esc(pretty(d.label))}</h3>
        <div class="sub">n° ${d.id} · ${esc(d.filename)} · ${d.width}×${d.height} px ${esc(d.format || "")}</div>
        ${state.lastResults ? `<button class="back" id="back-results" style="padding:0 0 10px">← Retour aux résultats</button>` : ""}
        <div class="chips">
          ${state.searchStatus.region ? `<button class="chip" id="chip-detail" title="Tracez un cadre sur l'image : main, drapé, objet…">Chercher un détail</button>` : ""}
          <button class="chip" id="chip-group">Groupe ${d.cluster}</button>${fam}
          <span class="chip ${atyp >= 90 ? "warn" : ""}" title="Rang d'isolement parmi toutes les œuvres">Atypicité ${atyp} %</span>
          <button class="chip" id="chip-fly">Voir sur la carte</button>
          <button class="chip" id="chip-export" title="Dossier .zip : l'œuvre, ses voisines, relations et métadonnées">Exporter avec ses voisines</button>
        </div>
        ${meta ? `<table>${meta}</table>` : ""}
        <h4>Œuvres les plus proches</h4>
        <div class="neighbors">${neigh}</div>
        <div class="prov">Calculé par ${esc(d.provenance.encoder)} · ${esc(d.provenance.features)} · ${esc(d.provenance.analysis)}.
          Une proximité visuelle est une piste à examiner, pas une preuve de filiation.</div>
      </div>`;
    $("fiche").hidden = false;
    $("fiche-body").querySelectorAll(".neighbor").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    $("chip-fly").addEventListener("click", () => flyTo(d.x * WORLD, d.y * WORLD, Math.max(state.viewState.zoom, state.fitZoom + 3)));
    $("chip-group").addEventListener("click", () => {
      const li = document.querySelector(`.group[data-cluster="${d.cluster - 1}"]`);
      if (li) { li.scrollIntoView({ block: "nearest" }); if (!li.classList.contains("active")) li.click(); }
    });
    if ($("chip-detail")) $("chip-detail").addEventListener("click", () => toggleDrawing(d));
    $("chip-export").addEventListener("click", (e) => exportPack({
      ids: [d.id, ...d.neighbors.map((n) => n.id)],
      title: `${pretty(d.label)} et ses voisines`,
      selection: { "méthode": "œuvre et ses plus proches voisines (DINOv3), depuis l'Atlas", "œuvre de départ": `${d.id} — ${d.label}` },
      scores: Object.fromEntries(d.neighbors.map((n) => [n.id, n.score])),
    }, e.currentTarget));
    if ($("back-results")) $("back-results").addEventListener("click", () => renderResults(state.lastResults));
    state.drawing = false;
    $("fiche").scrollTop = 0;
    setTimeout(() => deckgl.redraw(true), 0);
  }

  // ------------------------------------------------------------------ recherche par détail
  function imageRect(img) {
    // Position réelle de l'image dans son cadre (object-fit: contain).
    const cw = img.clientWidth, ch = img.clientHeight;
    const s = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    return { left: img.offsetLeft + (cw - w) / 2, top: img.offsetTop + (ch - h) / 2, w, h };
  }

  function toggleDrawing(d) {
    const hero = document.querySelector(".fiche .hero");
    const chip = $("chip-detail");
    state.drawing = !state.drawing;
    hero.classList.toggle("drawing", state.drawing);
    chip.classList.toggle("on", state.drawing);
    hero.querySelectorAll(".selbox, .draw-hint").forEach((x) => x.remove());
    if (!state.drawing) return;
    const hint = document.createElement("div");
    hint.className = "draw-hint";
    hint.textContent = "Tracez un cadre autour du détail";
    hero.appendChild(hint);
    const img = hero.querySelector("img");
    let start = null, box = null;
    const frac = (e) => {
      const r = imageRect(img), b = hero.getBoundingClientRect();
      return [Math.min(Math.max((e.clientX - b.left - r.left) / r.w, 0), 1), Math.min(Math.max((e.clientY - b.top - r.top) / r.h, 0), 1)];
    };
    const draw = (a, c) => {
      const r = imageRect(img);
      box = box || Object.assign(document.createElement("div"), { className: "selbox" });
      if (!box.parentNode) hero.appendChild(box);
      Object.assign(box.style, {
        left: `${r.left + Math.min(a[0], c[0]) * r.w}px`, top: `${r.top + Math.min(a[1], c[1]) * r.h}px`,
        width: `${Math.abs(c[0] - a[0]) * r.w}px`, height: `${Math.abs(c[1] - a[1]) * r.h}px`,
      });
    };
    hero.onclick = (e) => { if (state.drawing) e.preventDefault(); };
    hero.onpointerdown = (e) => {
      if (!state.drawing) return;
      e.preventDefault(); start = frac(e); hero.setPointerCapture(e.pointerId);
    };
    hero.onpointermove = (e) => { if (state.drawing && start) draw(start, frac(e)); };
    hero.onpointerup = (e) => {
      if (!state.drawing || !start) return;
      const end = frac(e);
      const q = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])];
      start = null;
      if (q[2] - q[0] < 0.03 || q[3] - q[1] < 0.03) return; // simple clic : on ignore
      state.drawing = false;
      hero.classList.remove("drawing");
      runRegionSearch(d, q);
    };
  }

  async function runRegionSearch(d, box) {
    $("fiche-body").innerHTML = `<div class="loading">Recherche du détail dans le corpus…<br><small>La toute première recherche charge le modèle (jusqu'à une demi-minute).</small></div>`;
    let res;
    try {
      const r = await fetch("/api/search/region", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: d.id, box, k: 40 }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      res = await r.json();
    } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">Échec : ${esc(err.message)}</div>`;
      return;
    }
    renderResults({ kind: "region", title: "Détails semblables", sub: `${res.results.length} œuvres · cadre tracé sur « ${pretty(d.label)} »`,
      query: { id: d.id, box }, results: res.results });
  }

  // ------------------------------------------------------------------ panneau de résultats
  function drawCrop(canvas, id, box, maxH) {
    const img = new Image();
    img.onload = () => {
      const [x0, y0, x1, y1] = box || [0, 0, 1, 1];
      const sw = (x1 - x0) * img.naturalWidth, sh = (y1 - y0) * img.naturalHeight;
      const s = Math.min(canvas.width / sw, maxH / sh);
      canvas.height = Math.round(Math.min(maxH, sh * s));
      const ctx = canvas.getContext("2d");
      const dw = sw * s, dh = sh * s;
      ctx.drawImage(img, x0 * img.naturalWidth, y0 * img.naturalHeight, sw, sh, (canvas.width - dw) / 2, (canvas.height - dh) / 2, dw, dh);
    };
    img.src = `/api/thumb/1024/${id}`;
  }

  function renderResults(r) {
    state.lastResults = r;
    const cards = r.results.map((x, n) => `<button class="result" data-id="${x.id}" title="${esc(x.label)}">
        ${r.kind === "region" ? `<canvas width="300" height="130" data-n="${n}"></canvas>` : `<img src="/api/thumb/256/${x.id}" alt="" loading="lazy">`}
        <div class="score">${x.score.toFixed(3)} · groupe ${x.cluster}</div>
        <div class="lbl">${esc(pretty(x.label))}</div></button>`).join("");
    $("fiche-body").innerHTML = `<div class="results-head"><h3>${esc(r.title)}</h3><div class="sub">${esc(r.sub)}</div>
        ${r.query ? `<canvas id="query-crop" width="360" height="160"></canvas>` : ""}
        <div class="chips" style="margin-top:10px"><button class="chip" id="export-results" title="Dossier .zip : images, métadonnées, relations, résumé pour un LLM">Exporter en Research Pack</button></div></div>
      <div class="results-grid">${cards}</div>
      <div class="prov" style="margin:0 16px 20px">${r.kind === "region"
        ? "Chaque vignette montre la zone de l'œuvre la plus proche du détail tracé (grilles 2×2 et 4×4)."
        : "Classement par SigLIP 2 : ressemblance entre la description et l'image, à vérifier œuvre par œuvre."}</div>`;
    if (r.query) drawCrop($("query-crop"), r.query.id, r.query.box, 160);
    if (r.kind === "region") $("fiche-body").querySelectorAll(".result canvas").forEach((c) => {
      const x = r.results[Number(c.dataset.n)];
      drawCrop(c, x.id, x.box, 130);
    });
    $("fiche-body").querySelectorAll(".result").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    $("export-results").addEventListener("click", (e) => {
      const ids = (r.query ? [r.query.id] : []).concat(r.results.map((x) => x.id));
      const details = {};
      if (r.kind === "region") {
        details[r.query.id] = r.query.box;
        r.results.forEach((x) => { if (x.box) details[x.id] = x.box; });
      }
      exportPack({
        ids, title: r.kind === "region" ? "Détails semblables" : r.title,
        selection: r.kind === "region"
          ? { "méthode": "recherche par détail dans l'Atlas", "œuvre de départ": String(r.query.id), "cadre": JSON.stringify(r.query.box.map((v) => +v.toFixed(3))) }
          : { "méthode": "recherche en texte libre (SigLIP 2) dans l'Atlas", "requête": r.title },
        scores: Object.fromEntries(r.results.map((x) => [x.id, x.score])), details,
      }, e.currentTarget);
    });
    $("fiche").hidden = false;
    $("fiche").scrollTop = 0;
    const set = new Set(r.results.map((x) => state.rowOf.get(x.id)).filter((i) => i !== undefined));
    if (r.query && state.rowOf.has(r.query.id)) set.add(state.rowOf.get(r.query.id));
    setHighlight(set, r.title);
  }

  // ------------------------------------------------------------------ Research Pack
  async function exportPack({ ids, title, selection, scores = {}, details = {} }, button) {
    const question = prompt("Question de recherche à inscrire dans le dossier (facultatif) :", "");
    if (question === null) return; // annulé
    const label = button ? button.textContent : "";
    if (button) { button.disabled = true; button.textContent = "Export en cours…"; }
    try {
      const r = await fetch("/api/pack", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids, title, question, selection, scores, details }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      const blob = await r.blob();
      const name = (r.headers.get("content-disposition") || "").match(/filename="?([^";]+)"?/)?.[1] || "research-pack.zip";
      const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: name });
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      if (button) button.textContent = `Exporté (${(blob.size / 1048576).toFixed(1)} Mo)`;
    } catch (err) {
      alert(`Export impossible : ${err.message}`);
      if (button) button.textContent = label;
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function runTextSearch(q) {
    $("fiche").hidden = false;
    $("fiche-body").innerHTML = `<div class="loading">Recherche de « ${esc(q)} »…<br><small>La toute première recherche charge SigLIP 2 (jusqu'à une minute).</small></div>`;
    try {
      const res = await getJSON(`/api/search/text?q=${encodeURIComponent(q)}&k=60`);
      renderResults({ kind: "text", title: `« ${q} »`, sub: `${res.results.length} œuvres les plus proches de la description`, results: res.results });
    } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">Échec : ${esc(err.message)}</div>`;
    }
  }

  function closeFiche() {
    $("fiche").hidden = true;
    state.selected = state.selectedData = null;
    state.lastResults = null;
    history.replaceState(null, "", location.pathname);
    redraw();
  }

  // ------------------------------------------------------------------ interface
  function wireUI() {
    $("colorby").addEventListener("change", (e) => {
      state.colorMode = e.target.value;
      if (state.highlightLabel && !state.highlightLabel.startsWith("Recherche")) clearHighlight();
      renderLegend();
      redraw();
    });
    let t;
    $("search-mode").addEventListener("change", (e) => {
      $("search").placeholder = e.target.value === "text"
        ? "Décrivez ce que vous cherchez, puis Entrée : « Annonciation dans un jardin »…"
        : "Rechercher : artiste, style, n° d'œuvre…";
      $("search").focus();
    });
    $("search-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const q = $("search").value.trim();
      if ($("search-mode").value === "text" && q.length >= 2) runTextSearch(q);
    });
    $("search").addEventListener("input", (e) => {
      clearTimeout(t);
      const q = e.target.value.trim();
      $("search-clear").hidden = !q;
      if ($("search-mode").value === "text") return; // recherche lancée par Entrée seulement
      t = setTimeout(async () => {
        if (!q) { clearHighlight(); return; }
        const res = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
        const set = new Set(res.ids.map((id) => state.rowOf.get(id)).filter((i) => i !== undefined));
        document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
        setHighlight(set, `Recherche « ${q} »`);
        if (set.size === 1) select(res.ids[0], true);
      }, 250);
    });
    $("search-clear").addEventListener("click", clearHighlight);
    $("reset-view").addEventListener("click", () => { clearHighlight(); flyTo(0, 0, state.fitZoom); });
    $("fiche-close").addEventListener("click", closeFiche);
    addEventListener("keydown", (e) => { if (e.key === "Escape") closeFiche(); });
    addEventListener("resize", onResize);
    new ResizeObserver(onResize).observe($("map"));
    addEventListener("hashchange", () => {
      const id = parseInt(location.hash.replace("#oeuvre-", ""), 10);
      if (state.rowOf.has(id) && id !== state.selected) select(id, true);
    });
    $("map").addEventListener("mouseleave", () => { $("tooltip").hidden = true; });
  }

  init();
})();
