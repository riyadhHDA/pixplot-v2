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
  };
  let deckgl;

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
  function setupDeck() {
    const el = $("map");
    const fit = Math.log2(Math.min(el.clientWidth, el.clientHeight) / (2.2 * WORLD));
    state.fitZoom = fit;
    state.viewState = { ...state.viewState, zoom: fit, minZoom: fit - 2 };
    deckgl = new Deck({
      parent: el,
      views: new OrthographicView({ id: "atlas", flipY: false }),
      viewState: state.viewState,
      controller: { dragRotate: false, doubleClickZoom: true, scrollZoom: { speed: 0.02, smooth: true } },
      onViewStateChange: ({ viewState }) => {
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
        <div class="chips">
          <button class="chip" id="chip-group">Groupe ${d.cluster}</button>${fam}
          <span class="chip ${atyp >= 90 ? "warn" : ""}" title="Rang d'isolement parmi toutes les œuvres">Atypicité ${atyp} %</span>
          <button class="chip" id="chip-fly">Voir sur la carte</button>
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
    $("fiche").scrollTop = 0;
    setTimeout(() => deckgl.redraw(true), 0);
  }

  function closeFiche() {
    $("fiche").hidden = true;
    state.selected = state.selectedData = null;
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
    $("search").addEventListener("input", (e) => {
      clearTimeout(t);
      const q = e.target.value.trim();
      $("search-clear").hidden = !q;
      t = setTimeout(async () => {
        if (!q) { clearHighlight(); return; }
        const res = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
        const set = new Set(res.ids.map((id) => state.rowOf.get(id)).filter((i) => i !== undefined));
        document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
        setHighlight(set, `Recherche « ${q} »`);
        if (set.size === 1) select(res.ids[0], true);
      }, 250);
    });
    $("search-form").addEventListener("submit", (e) => e.preventDefault());
    $("search-clear").addEventListener("click", clearHighlight);
    $("reset-view").addEventListener("click", () => { clearHighlight(); flyTo(0, 0, state.fitZoom); });
    $("fiche-close").addEventListener("click", closeFiche);
    addEventListener("keydown", (e) => { if (e.key === "Escape") closeFiche(); });
    addEventListener("resize", () => scheduleIcons());
    $("map").addEventListener("mouseleave", () => { $("tooltip").hidden = true; });
  }

  init();
})();
