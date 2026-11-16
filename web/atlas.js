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
  const MAX_HD = 300;            // vignettes haute définition posées à la fois (au centre de l écran)
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
    info: null, map: null, clusters: [], n: 0, comm: {},
    positions: null, rowOf: new Map(),
    colorMode: "cluster", highlight: null, highlightLabel: "",
    selected: null, selectedData: null,
    viewState: { target: [0, 0, 0], zoom: 0, minZoom: -4, maxZoom: 9 },
    fitZoom: 0, iconSize: 20, iconTimer: null,
    sprites: null, spriteSize: null, hd: [], display: "sprites",
    searchStatus: { region: false, text: false }, lastResults: null, drawing: false,
    spaces: [], mainSpace: null, space: null,          // espaces de ressemblance (voisines)
    layout: "map", umapPositions: null, axis: [],      // carte, chronologie ou géographie
    groupLabels: [], layoutCache: {}, world: undefined, panelHistory: [],
    compare: [],                                       // œuvres mises de côté pour comparer
  };
  const svg = (d) => `<svg viewBox="0 0 20 20" aria-hidden="true"><path d="${d}"/></svg>`;
  const ICON = {
    detail: svg("M3 3h5M3 3v5M17 3h-5M17 3v5M3 17h5M3 17v-5M17 17h-5M17 17v-5"),
    compare: svg("M2 4h7v12H2z M11 4h7v12h-7z"),
    note: svg("M5 2h10v16H5z M8 6h5 M8 9h5 M8 12h3"),
    export: svg("M10 3v10 M6 9l4 4 4-4 M4 17h12"),
  };
  const SPACE_SHORT = { forme: "Forme", sujet: "Sujet et style", couleur: "Couleur", touche: "Touche", forme_v2: "DINOv2" };
  const store = {   // préférences de ce navigateur seulement (peuvent être indisponibles)
    get(k, d) { try { return JSON.parse(localStorage.getItem(`pixplot:${k}`)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(`pixplot:${k}`, JSON.stringify(v)); } catch { /* navigation privée */ } },
  };
  function toast(msg) {
    const t = $("toast");
    t.textContent = msg; t.hidden = false;
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
  }
  function groupName(c) {
    const g = state.clusters.find((x) => x.cluster === c);
    return g && g.name ? g.name : "";
  }
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
    state.umapPositions = state.positions.slice();
    state.iconSize = Math.max(2, Math.min(40, (2 * WORLD / Math.sqrt(state.n)) * 0.9));
    try { state.searchStatus = await getJSON("/api/search/status"); } catch { /* recherches avancées indisponibles */ }
    try {
      const sp = await getJSON("/api/spaces");
      state.spaces = sp.spaces; state.mainSpace = state.space = sp.main;
      const saved = store.get("space", null);
      if (saved && state.spaces.some((s) => s.key === saved)) state.space = saved;
    } catch { /* un seul espace */ }
    state.compare = store.get(`compare:${state.info.analysis}`, []).filter((id) => state.rowOf.has(id));
    updateCompareButton();
    // Cartes proposées : la carte de l'analyse, une par autre regard, puis dates et lieux.
    const mainLabel = SPACE_SHORT[state.info.main_space] || "forme";
    const groups = [[`Ressemblance`, [["map", `${mainLabel} (carte principale)`],
      ...(state.info.space_maps || []).map((k) => [`map:${k}`, SPACE_SHORT[k] || k])]]];
    const other = [];
    if (m.year) other.push(["time", "Chronologie"]);
    if (m.lat) other.push(["geo", "Géographie"]);
    if (other.length) groups.push(["Dates et lieux", other]);
    $("layout").innerHTML = groups.map(([g, opts]) => `<optgroup label="${esc(g)}">${opts.map(([v, l]) =>
      `<option value="${v}">${esc(l)}</option>`).join("")}</optgroup>`).join("");
    $("groups-count").textContent = `· ${state.clusters.length}`;
    $("open-suspects").hidden = !Object.keys(state.info.suspects || {}).length && !Object.keys(state.info.annotated_pairs || {}).length;
    $("open-disagreements").hidden = !Object.keys(state.info.disagreements || {}).length;
    const textOpt = $("search-mode").querySelector('option[value="text"]');
    textOpt.disabled = !state.searchStatus.text;
    textOpt.title = state.searchStatus.text ? "" : "Calculez d'abord les vecteurs SigLIP 2";
    buildColorOptions();
    renderGroups();
    computeGroupLabels();
    setupDeck();
    updateStats();
    wireUI();
    loadSprites();
    const fromHash = parseInt(location.hash.replace("#oeuvre-", ""), 10);
    if (state.rowOf.has(fromHash)) select(fromHash, true);
  }

  // ------------------------------------------------------------------ couleurs
  function buildColorOptions() {
    const sel = $("colorby");
    const opts = [["cluster", "Groupes (e-means)"]];
    if (state.map.hdbscan) opts.push(["hdbscan", "Familles (HDBSCAN)"]);
    const ORDER = ["forme", "sujet", "couleur", "touche"];
    const comm = [...(state.info.communities || [])].sort((a, b) => (ORDER.indexOf(a) + 99) % 99 - (ORDER.indexOf(b) + 99) % 99);
    for (const sp of comm) {
      const name = SPACE_SHORT[sp] || sp;
      opts.push([`leiden:${sp}:family`, `Familles Leiden · ${name}`], [`leiden:${sp}:group`, `Groupes Leiden · ${name}`]);
    }
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
    if (mode.startsWith("leiden:")) {
      const [, sp, kind] = mode.split(":");
      const v = state.comm[sp][kind][i];
      return v < 0 ? [70, 70, 74] : PALETTE[v % PALETTE.length];
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
    if (mode.startsWith("leiden:")) {
      const [, sp, kind] = mode.split(":");
      const c = state.comm[sp];
      el.innerHTML = `<div>${kind === "family" ? `${c.n_families} familles` : `${c.n_groups} groupes`} Leiden · ${esc(SPACE_SHORT[sp] || sp)}</div>
        <div style="color:var(--muted);max-width:240px">Communautés du graphe des voisines dans ce regard${kind === "family" ? " ; chaque famille réunit plusieurs groupes" : ""}. En gris : œuvres absentes de ce regard.</div>`;
      return;
    }
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
    if (changed && !state.userMoved && isMapLayout()) {
      state.viewState = { minZoom: fit - 2, maxZoom: 9, zoom: fit, target: [0, 0, 0] };
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
    if (!info || !info.layer || info.index < 0) return null;
    const id = info.layer.id;
    if (id.startsWith("sheet-") || id === "hd") return state.map.ids[info.object.r ?? info.object];
    if (id === "points") return state.map.ids[info.index];
    return null;
  }

  // ------------------------------------------------------------------ vignettes
  // Toutes les vignettes viennent de quelques planches (atlas de textures) chargées une
  // fois sur le GPU : elles restent toutes affichées, sans scintillement. Au zoom, des
  // versions haute définition se posent PAR-DESSUS les mêmes vignettes (jamais à la place).
  async function loadSprites() {
    let meta;
    try { meta = await getJSON("/api/sprites"); } catch { return; } // à défaut : les points
    const sheets = [];
    for (let s = 0; s < meta.sheets; s++) sheets.push({ rows: [], mapping: {} });
    state.spriteSize = new Float32Array(state.n);
    for (let r = 0; r < state.n; r++) {
      const s = meta.atlas[r], w = meta.w[r], h = meta.h[r];
      sheets[s].rows.push(r);
      sheets[s].mapping[r] = { x: meta.x[r], y: meta.y[r], width: w, height: h };
      // getSize règle la HAUTEUR de l'icône : on la réduit pour les œuvres en largeur,
      // afin que chaque vignette tienne dans la même case carrée.
      state.spriteSize[r] = state.iconSize * h / Math.max(w, h, 1);
    }
    state.sprites = sheets;
    redraw();
    scheduleHD();
  }

  function onScreenSize() { return state.iconSize * Math.pow(2, state.viewState.zoom); }
  function showSprites() { return state.sprites && state.display === "sprites" && onScreenSize() >= 4; }

  function scheduleIcons() { scheduleHD(); }
  function scheduleHD() {
    clearTimeout(state.iconTimer);
    state.iconTimer = setTimeout(() => { computeHD(); redraw(); }, 180);
  }

  function computeHD() {
    const px = onScreenSize();
    if (!showSprites() || px < 72) {
      state.hd = [];
      $("hint").textContent = state.display === "sprites"
        ? `${state.n.toLocaleString("fr-FR")} vignettes · zoomez pour la haute définition · clic : fiche`
        : "Molette : zoomer · glisser : se déplacer · clic sur une œuvre : sa fiche";
      return;
    }
    const el = $("map"), scale = Math.pow(2, state.viewState.zoom);
    const halfW = el.clientWidth / 2 / scale + state.iconSize, halfH = el.clientHeight / 2 / scale + state.iconSize;
    const [cx, cy] = state.viewState.target;
    let visible = [];
    for (let r = 0; r < state.n; r++) {
      if (state.highlight && !state.highlight.has(r)) continue;
      const dx = state.positions[2 * r] - cx, dy = state.positions[2 * r + 1] - cy;
      if (Math.abs(dx) < halfW && Math.abs(dy) < halfH) visible.push([r, dx * dx + dy * dy]);
    }
    visible.sort((a, b) => a[1] - b[1]); // le centre de l'écran d'abord
    const size = px > 160 ? 1024 : 256;
    state.hd = visible.slice(0, MAX_HD).map(([r]) => {
      const a = state.map.aspect[r] || 1;
      return { r, id: state.map.ids[r], size, w: a >= 1 ? size : Math.round(size * a), h: a >= 1 ? Math.round(size / a) : size };
    });
    $("hint").textContent = `Haute définition : ${state.hd.length} vignettes au centre · clic : fiche`;
  }

  function spriteColor(r) {
    return !state.highlight || state.highlight.has(r) ? [255, 255, 255, 255] : [255, 255, 255, 30];
  }

  function redraw() {
    const layers = [];
    const sprites = showSprites();
    const showingIcons = sprites;
    if (state.layout === "geo" && state.world) {
      // fond de carte (Natural Earth 1:110 M, embarqué : fonctionne hors ligne)
      layers.push(new deck.SolidPolygonLayer({
        id: "world-land", data: state.world.land, getPolygon: (d) => d, getFillColor: [34, 34, 38],
      }));
      layers.push(new deck.PathLayer({
        id: "world-borders", data: state.world.arcs, getPath: (d) => d, getColor: [90, 88, 84, 200],
        getWidth: 1, widthUnits: "pixels",
      }));
    }
    layers.push(new ScatterplotLayer({
      id: "points",
      visible: !sprites,
      data: { length: state.n, attributes: {
        getPosition: { value: state.positions, size: 2 },
        getFillColor: { value: colorArray(), size: 4, normalized: true },
      } },
      radiusUnits: "pixels",
      getRadius: 3,
      radiusMinPixels: 1, radiusMaxPixels: 6,
      pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 255],
      updateTriggers: { getFillColor: [state.colorMode, state.highlightLabel], getPosition: [state.layout] },
    }));
    if (state.sprites) {
      state.sprites.forEach((sheet, s) => layers.push(new IconLayer({
        id: `sheet-${s}`,
        visible: sprites,
        data: sheet.rows,
        iconAtlas: `/api/sprites/${s}.jpg`,
        iconMapping: sheet.mapping,
        getIcon: (r) => String(r),
        getPosition: (r) => [state.positions[2 * r], state.positions[2 * r + 1]],
        getSize: (r) => state.spriteSize[r],
        sizeUnits: "common",
        getColor: spriteColor,
        pickable: true,
        autoHighlight: true, highlightColor: [224, 176, 64, 255],
        alphaCutoff: 0,
        updateTriggers: { getColor: [state.highlightLabel], getPosition: [state.layout] },
      })));
    }
    if (sprites && state.hd.length) {
      layers.push(new IconLayer({
        id: "hd",
        data: state.hd,
        getIcon: (d) => ({ url: `/api/thumb/${d.size}/${d.id}`, width: d.w, height: d.h, id: `${d.size}-${d.id}` }),
        getPosition: (d) => [state.positions[2 * d.r], state.positions[2 * d.r + 1]],
        getSize: (d) => state.spriteSize[d.r],
        sizeUnits: "common",
        pickable: true,
        alphaCutoff: 0,
      }));
    }
    if (state.selectedData) {
      const s = state.selectedData;
      const from = posOf(s.id);
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
    if (state.axis.length) {
      layers.push(new LineLayer({
        id: "axis-lines", data: state.axis.filter((a) => a.line), getSourcePosition: (d) => d.line[0], getTargetPosition: (d) => d.line[1],
        getColor: [255, 255, 255, 40], getWidth: 1, widthUnits: "pixels",
      }));
      layers.push(new TextLayer({
        id: "axis-labels", data: state.axis.filter((a) => a.text), getPosition: (d) => d.at, getText: (d) => d.text,
        getSize: 12, getColor: [200, 196, 186], getTextAnchor: "middle", getAlignmentBaseline: "top",
        fontFamily: "Segoe UI, sans-serif",
      }));
    }
    if (isMapLayout() && state.groupLabels.length && onScreenSize() < 40 && (state.colorMode === "cluster" || sprites)) {
      layers.push(new TextLayer({
        id: `group-labels-${state.layout}`,
        data: state.groupLabels,
        getPosition: (d) => d.at,
        getText: (d) => String(d.number),
        getSize: 13, getColor: [255, 255, 255],
        background: true, getBackgroundColor: (d) => [...PALETTE[d.cluster % PALETTE.length].map((c) => c * 0.35), 230],
        backgroundPadding: [5, 2], fontWeight: 700, fontFamily: "Segoe UI, sans-serif",
        getTextAnchor: "middle", getAlignmentBaseline: "center",
        // Avec des centaines de groupes, les étiquettes se chevauchent : celles des plus
        // grands groupes passent devant, les autres apparaissent en zoomant.
        extensions: deck.CollisionFilterExtension ? [new deck.CollisionFilterExtension()] : [],
        collisionEnabled: true, getCollisionPriority: (d) => d.size || 0,
        collisionTestProps: { sizeScale: 1.6 },
      }));
    }
    deckgl.setProps({ layers });
  }

  function flyTo(x, y, zoom) {
    // Un zoom vers une œuvre ou un groupe n'est plus « la vue d'ensemble » : un
    // redimensionnement (ouverture de la fiche…) ne doit pas l'annuler.
    state.userMoved = !(x === 0 && y === 0 && zoom === state.fitZoom);
    // deck.gl ajoute zoomX / zoomY / minZoomX… à l'état de vue : s'ils restent, ils priment
    // sur « zoom » et la vue ne bouge plus. On repart d'un état propre.
    const { minZoom = -4, maxZoom = 9 } = state.viewState;
    state.viewState = {
      target: [x, y, 0], zoom, minZoom: Math.min(minZoom, zoom - 1), maxZoom,
      transitionDuration: 700, transitionInterpolator: new LinearInterpolator(["target", "zoom"]),
    };
    deckgl.setProps({ viewState: state.viewState });
    scheduleIcons();
    setTimeout(scheduleIcons, 750);
  }

  // ------------------------------------------------------------------ dispositions
  // Carte : la projection UMAP (ressemblance). Chronologie : une colonne par période, les
  // œuvres empilées par groupe. Géographie : longitude / latitude (sans fond de carte, pour
  // rester hors ligne), les œuvres d'un même lieu disposées en spirale.
  function posOf(id) {
    const r = state.rowOf.get(id);
    return r === undefined ? [0, 0] : [state.positions[2 * r], state.positions[2 * r + 1]];
  }

  function timePositions() {
    const m = state.map, n = state.n, cell = state.iconSize * 1.08;
    const years = m.year.filter((y) => y != null);
    const lo = Math.min(...years), hi = Math.max(...years);
    // pas plus de colonnes que l'écran n'en tient, ni beaucoup plus que d'œuvres (petits corpus)
    const maxCols = Math.max(8, Math.min(Math.floor((2 * WORLD) / cell), Math.round(4 * Math.sqrt(n))));
    const step = [1, 2, 5, 10, 20, 25, 50, 100, 200].find((s) => (hi - lo) / s + 1 <= maxCols) || 500;
    const start = Math.floor(lo / step) * step;
    const bins = Math.floor((hi - start) / step) + 2; // + un bloc « sans date »
    const binOf = (y) => (y == null ? bins - 1 : Math.floor((y - start) / step));
    const counts = new Array(bins).fill(0);
    for (const y of m.year) counts[binOf(y)]++;
    // Chaque période est un bloc de w vignettes de large ; w est choisi pour que l'ensemble
    // ait à peu près les proportions de l'écran (sinon les périodes chargées font des tours).
    const el = $("map"), target = el.clientWidth / Math.max(1, el.clientHeight);
    const maxCount = Math.max(...counts);
    let w = 1, best = Infinity;
    for (let k = 1; k <= Math.max(1, Math.ceil(Math.sqrt(maxCount)) * 3); k++) {
      const ratio = (bins * (k + 1)) / Math.max(1, Math.ceil(maxCount / k));
      const err = Math.abs(Math.log(ratio / target));
      if (err < best) { best = err; w = k; }
    }
    const blockW = (w + 1) * cell, x0 = -(bins * blockW) / 2, base = 0;
    const order = [...Array(n).keys()].sort((a, b) => (m.cluster[a] - m.cluster[b]) || (a - b));
    const fill = new Array(bins).fill(0);
    const pos = new Float32Array(n * 2);
    for (const r of order) {
      const b = binOf(m.year[r]), k = fill[b]++;
      pos[2 * r] = x0 + b * blockW + ((k % w) + 0.5) * cell;
      pos[2 * r + 1] = base + (Math.floor(k / w) + 0.5) * cell;
    }
    const top = Math.ceil(maxCount / w) * cell;
    const axis = [];
    // Un libellé tous les k blocs, pour qu'ils gardent ~70 px d'écart à la vue d'ensemble.
    const pxPerBin = el.clientWidth / 1.2 / bins;
    const every = Math.max(1, Math.ceil(70 / Math.max(pxPerBin, 1)));
    for (let b = 0; b < bins; b++) {
      const x = x0 + b * blockW;
      if (b < bins - 1) axis.push({ line: [[x - cell / 2, base], [x - cell / 2, top]] });
      if (b === bins - 1 ? counts[b] > 0 : b % every === 0)
        axis.push({ at: [x + (w * cell) / 2, base - cell * 0.3], text: b === bins - 1 ? "sans date" : String(start + b * step) });
    }
    return { pos, axis, note: `un bloc = ${step === 1 ? "une année" : `${step} ans`}, œuvres rangées par groupe` };
  }

  function geoPositions() {
    const m = state.map, n = state.n, cell = state.iconSize * 1.05;
    const pos = new Float32Array(n * 2);
    const placed = new Map();
    // Échelle large par rapport aux vignettes : les spirales de villes voisines (Paris,
    // Londres, Amsterdam…) ne se recouvrent pas ; on zoome pour voir le détail.
    const scale = (WORLD / 180) * 8;
    for (let r = 0; r < n; r++) {
      const lat = m.lat[r], lon = m.lon[r];
      let x, y;
      if (lat == null || lon == null) { x = 190 * scale; y = -100 * scale; }  // sans lieu : en bas à droite
      else { x = lon * scale; y = lat * scale; }
      const key = `${Math.round(x / cell)}:${Math.round(y / cell)}`;
      const k = placed.get(key) || 0;
      placed.set(key, k + 1);
      // spirale de Vogel : les œuvres d'un même lieu se rangent autour du point
      const rad = cell * 0.6 * Math.sqrt(k), th = k * 2.39996;
      pos[2 * r] = x + rad * Math.cos(th);
      pos[2 * r + 1] = y + rad * Math.sin(th);
    }
    const axis = [];
    // graticule discret tous les 30°, et un bloc à part pour les œuvres sans lieu
    for (let lon = -180; lon <= 180; lon += 30) axis.push({ line: [[lon * scale, -60 * scale], [lon * scale, 85 * scale]] });
    for (let lat = -60; lat <= 85; lat += 30) axis.push({ line: [[-180 * scale, lat * scale], [180 * scale, lat * scale]] });
    const unplaced = m.lat.filter((v, r) => v == null || m.lon[r] == null).length;
    if (unplaced) axis.push({ at: [190 * scale, -100 * scale + cell * (0.6 * Math.sqrt(unplaced) + 4)], text: `sans lieu (${unplaced})` });
    return { pos, axis, note: "longitude / latitude · fond Natural Earth" };
  }

  // Fond de carte : TopoJSON (world-atlas, Natural Earth 1:110 M, domaine public) embarqué
  // dans web/vendor/, décodé ici sans bibliothèque : arcs en deltas quantifiés → lon/lat.
  async function loadWorld() {
    if (state.world !== undefined) return state.world;
    try {
      const topo = await getJSON("vendor/world-110m.json");
      const [sx, sy] = topo.transform.scale, [tx, ty] = topo.transform.translate;
      const scale = (WORLD / 180) * 8;
      const arcs = topo.arcs.map((arc) => {
        let x = 0, y = 0;
        return arc.map(([dx, dy]) => { x += dx; y += dy; return [(x * sx + tx) * scale, (y * sy + ty) * scale]; });
      });
      const ring = (idx) => idx.flatMap((i, k) => {
        const pts = i >= 0 ? arcs[i] : arcs[~i].slice().reverse();
        return k ? pts.slice(1) : pts;
      });
      const land = [];
      for (const g of topo.objects.land.geometries) {
        const polys = g.type === "Polygon" ? [g.arcs] : g.arcs;
        for (const p of polys) land.push(p.map(ring));
      }
      state.world = { arcs, land };
    } catch { state.world = null; }  // pas de fond : la grille suffit
    return state.world;
  }

  function isMapLayout() { return state.layout === "map" || state.layout.startsWith("map:"); }

  // Étiquettes de groupes : au centre du groupe sur la carte affichée (sur une carte d'un
  // autre regard, un groupe peut être éclaté : l'étiquette va à sa médiane approchée).
  function computeGroupLabels() {
    if (state.layout === "map") {
      state.groupLabels = state.clusters.map((g) => ({ ...g, at: [g.center[0] * WORLD, g.center[1] * WORLD] }));
      return;
    }
    if (!isMapLayout()) { state.groupLabels = []; return; }
    const sums = new Map();
    for (let r = 0; r < state.n; r++) {
      const x = state.positions[2 * r], y = state.positions[2 * r + 1];
      if (!Number.isFinite(x) || Math.abs(x) > 1.1 * WORLD) continue;
      const c = state.map.cluster[r], s = sums.get(c) || [0, 0, 0, 0];
      s[0] += x; s[1] += y; s[2] += x * x + y * y; s[3]++;
      sums.set(c, s);
    }
    // Sur la carte d'un autre regard, un groupe de la carte principale peut être éclaté :
    // son numéro n'a de sens que s'il reste groupé (dispersion < 18 % de la carte).
    state.groupLabels = state.clusters.filter((g) => sums.has(g.cluster)).flatMap((g) => {
      const [sx, sy, sq, k] = sums.get(g.cluster);
      const mx = sx / k, my = sy / k, spread = Math.sqrt(Math.max(0, sq / k - mx * mx - my * my));
      return spread < 0.18 * WORLD ? [{ ...g, at: [mx, my] }] : [];
    });
  }

  async function setLayout(layout) {
    let note = "";
    if (layout.startsWith("map:")) {
      const key = layout.slice(4);
      let res;
      try { res = state.layoutCache[key] || (state.layoutCache[key] = await getJSON(`/api/layout/${key}`)); }
      catch (err) { toast(`Carte indisponible : ${err.message}`); $("layout").value = state.layout; return; }
      const pos = new Float32Array(state.n * 2);
      for (let r = 0; r < state.n; r++) {
        const ok = res.x[r] != null;
        pos[2 * r] = ok ? res.x[r] * WORLD : 1.25 * WORLD;  // absentes de cet espace : rangées à droite
        pos[2 * r + 1] = ok ? res.y[r] * WORLD : -WORLD;
      }
      state.positions = pos; state.axis = [];
      const s = state.spaces.find((x) => x.key === key);
      note = s ? `Voisines selon ${s.label} : ${s.about}. Les couleurs restent celles des groupes de la carte principale.` : "";
    } else if (layout === "time") ({ pos: state.positions, axis: state.axis, note } = timePositions());
    else if (layout === "geo") {
      await loadWorld();
      ({ pos: state.positions, axis: state.axis, note } = geoPositions());
    } else { state.positions = state.umapPositions.slice(); state.axis = []; }
    state.layout = layout;
    state.layoutNote = note;
    $("layout-note").textContent = note;
    computeGroupLabels();
    state.userMoved = false;
    if (isMapLayout()) flyTo(0, 0, state.fitZoom);
    else fitToPositions();
    computeHD();
    redraw();
    updateStats();
  }

  function fitToPositions() {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (let r = 0; r < state.n; r++) {
      const x = state.positions[2 * r], y = state.positions[2 * r + 1];
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    const el = $("map");
    // marge de 8 % : les libellés des axes (années, degrés) restent visibles
    const zoom = Math.log2(Math.min(el.clientWidth / ((x1 - x0) * 1.16 + 4 * state.iconSize),
      el.clientHeight / ((y1 - y0) * 1.16 + 4 * state.iconSize)));
    flyTo((x0 + x1) / 2, (y0 + y1) / 2, zoom);
    state.userMoved = true;
  }

  function centerOf(set) {
    let sx = 0, sy = 0, k = 0;
    for (const r of set) { sx += state.positions[2 * r]; sy += state.positions[2 * r + 1]; k++; }
    return k ? [sx / k, sy / k] : [0, 0];
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
      <div style="color:var(--muted)">Groupe ${state.map.cluster[i] + 1}${groupName(state.map.cluster[i]) ? ` — ${esc(groupName(state.map.cluster[i]))}` : ""} · n° ${id}</div>`;
    const rect = $("map").getBoundingClientRect();
    tip.style.left = `${Math.min(rect.left + info.x + 16, innerWidth - 200)}px`;
    tip.style.top = `${Math.min(rect.top + info.y + 16, innerHeight - 200)}px`;
    tip.hidden = false;
  }

  // ------------------------------------------------------------------ groupes
  function renderGroups() {
    $("groups").innerHTML = state.clusters.map((g) => {
      const dom = Object.entries(g.dominant).slice(0, 3).map(([k, vs]) =>
        `${esc(LABELS[k] || k)} : ${esc(SLUG_KEYS.has(k) && /^[\w-]+$/.test(vs[0].value) ? pretty(vs[0].value) : vs[0].value)} (${Math.round(vs[0].share * 100)} %)`).join("<br>");
      const col = PALETTE[g.cluster % PALETTE.length].join(",");
      return `<li class="group" data-cluster="${g.cluster}">
        <img src="/api/thumb/256/${g.representative}" alt="" loading="lazy">
        <div><div class="title"><span class="swatch" style="background:rgb(${col})"></span>Groupe ${g.number}
          <span class="size">${g.size} œuvres</span></div>
          ${g.name ? `<div class="gname" title="Nom proposé par SigLIP 2 d'après un vocabulaire d'histoire de l'art — à vérifier">${esc(g.name)}</div>` : ""}
          <div class="dom">${dom}</div></div></li>`;
    }).join("");
    $("groups").querySelectorAll(".group").forEach((li) => li.addEventListener("click", () => {
      const c = Number(li.dataset.cluster);
      const g = state.clusters.find((x) => x.cluster === c);
      if (li.classList.contains("active")) { clearHighlight(); return; }
      const set = new Set();
      state.map.cluster.forEach((v, i) => { if (v === c) set.add(i); });
      setHighlight(set, `Groupe ${g.number}${g.name ? ` (${g.name})` : ""}`);
      document.querySelectorAll(".group").forEach((x) => x.classList.toggle("active", x === li));
      if (state.layout === "map") flyTo(g.center[0] * WORLD, g.center[1] * WORLD, state.fitZoom + 1.6);
      else { const [x, y] = centerOf(set); flyTo(x, y, state.viewState.zoom); }
    }));
  }

  // ------------------------------------------------------------------ surbrillance
  function setHighlight(set, label) {
    state.highlight = set && set.size ? set : null;
    state.highlightLabel = label || "";
    computeHD();
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
    const base = `${state.n.toLocaleString("fr-FR")} œuvres · ${i.clusters} groupes · ${i.encoder} @${i.input_size}`
      + (state.layout === "time" || state.layout === "geo" ? ` · ${state.layoutNote}` : "")
      + (state.layout.startsWith("map:") ? ` · carte « ${SPACE_SHORT[state.layout.slice(4)] || state.layout.slice(4)} »` : "");
    $("stats").textContent = state.highlight
      ? `${state.highlightLabel} : ${state.highlight.size.toLocaleString("fr-FR")} œuvres  —  ${base}`
      : base;
  }

  // ------------------------------------------------------------------ fiche
  async function select(id, fly) {
    let data;
    const space = state.space && state.space !== state.mainSpace ? `?space=${state.space}` : "";
    try { data = await getJSON(`/api/artwork/${id}${space}`); } catch { return; }
    state.selected = id;
    state.selectedData = data;
    history.replaceState(null, "", `#oeuvre-${id}`);
    renderFiche(data);
    redraw();
    if (fly) { const [x, y] = posOf(id); flyTo(x, y, Math.max(state.viewState.zoom, state.fitZoom + 3)); }
  }

  function spaceLabel(key) { const s = state.spaces.find((x) => x.key === key); return s ? s.label : (key || "DINOv3"); }
  function spaceAbout(key) {
    const s = state.spaces.find((x) => x.key === key);
    return s ? `Voisines selon ${s.label} : ${s.about}.` : "";
  }

  function spaceTabs(current) {
    if (state.spaces.length < 2) return "";
    return `<div class="spaces" role="tablist" aria-label="Voisines selon">${state.spaces.map((s) =>
      `<button class="space ${s.key === current ? "on" : ""}" data-space="${s.key}" title="${esc(s.about)}" role="tab"
        aria-selected="${s.key === current}">${esc(SPACE_SHORT[s.key] || s.label)}</button>`).join("")}</div>`;
  }

  function labelChecks(d) {
    if (!d.label_checks || !d.label_checks.length) return "";
    const space = state.spaces.find((s) => s.key === d.label_checks_space);
    const rows = d.label_checks.map((c) => `<li><b>${esc(LABELS[c.key] || c.key)}</b> : « ${esc(pretty(c.value))} »,
      mais ${Math.round(c.majority * 100)} % de ses voisines étiquetées sont « ${esc(pretty(c.suggested))} »</li>`).join("");
    return `<div class="checks"><div class="checks-title">Étiquette à vérifier</div><ul>${rows}</ul>
      <small>Voisines selon ${esc(space ? space.label : d.label_checks_space)}. Erreur de catalogue, ou œuvre réellement à part ? À regarder.</small></div>`;
  }

  // ------------------------------------------------------------------ comparateur
  function saveCompare() { store.set(`compare:${state.info.analysis}`, state.compare); updateCompareButton(); }
  function updateCompareButton() {
    $("compare-count").textContent = state.compare.length;
    $("open-compare").hidden = !state.compare.length;
  }
  function toggleCompare(id) {
    const i = state.compare.indexOf(id);
    if (i >= 0) state.compare.splice(i, 1);
    else {
      if (state.compare.length >= 6) { toast("Six œuvres au plus dans le comparateur"); return false; }
      state.compare.push(id);
    }
    saveCompare();
    toast(i >= 0 ? "Retirée du comparateur" : `Ajoutée au comparateur (${state.compare.length})`);
    return i < 0;
  }

  async function openCompare() {
    if (state.compare.length < 2) { toast("Ajoutez au moins deux œuvres (bouton « Comparer » d'une fiche)"); return; }
    $("compare").hidden = false;
    $("compare-body").innerHTML = `<div class="loading">Chargement…</div>`;
    let res;
    try { res = await getJSON(`/api/compare?ids=${state.compare.join(",")}`); } catch (err) {
      $("compare-body").innerHTML = `<div class="loading">Échec : ${esc(err.message)}</div>`; return;
    }
    const n = res.ids.length;
    const cols = res.artworks.map((a, k) => {
      const meta = Object.entries(a.metadata).filter(([, v]) => v).map(([key, v]) =>
        `<div><span>${esc(LABELS[key] || pretty(key))}</span> ${esc(SLUG_KEYS.has(key) ? pretty(v) : v)}</div>`).join("");
      return `<figure class="cmp" data-id="${a.id}">
        <div class="cmp-img"><span class="cmp-n">${k + 1}</span><img src="/api/thumb/1024/${a.id}" alt="${esc(a.label)}"></div>
        <figcaption><b>n° ${a.id}</b> · groupe ${a.cluster}${a.group_name ? ` — ${esc(a.group_name)}` : ""}
          <div class="cmp-meta">${meta}</div>
          <div class="cmp-act"><button class="chip" data-open="${a.id}">Fiche</button><button class="chip" data-remove="${a.id}">Retirer</button>
          <a class="chip" href="/api/image/${a.id}" target="_blank" rel="noopener">Original</a></div></figcaption></figure>`;
    }).join("");
    // Tableau des similarités : une ligne par paire, une colonne par espace.
    const pairs = [];
    for (let a = 0; a < n; a++) for (let b = a + 1; b < n; b++) pairs.push([a, b]);
    const spaces = res.spaces.filter((s) => res.similarity[s.key]);
    const head = spaces.map((s) => `<th title="${esc(s.about)}">${esc(SPACE_SHORT[s.key] || s.label)}</th>`).join("");
    let ref = { types: [], pairs: [] };
    try { ref = await getJSON(`/api/pairs?ids=${res.ids.join(",")}`); } catch (_) { /* banc d'essai indisponible */ }
    const typeLabel = Object.fromEntries(ref.types.map((t) => [t.key, t.label]));
    const annotations = (a, b) => ref.pairs.filter((p) =>
      (p.a === res.ids[a] && p.b === res.ids[b]) || (p.a === res.ids[b] && p.b === res.ids[a]));
    const body = pairs.map(([a, b]) => {
      const tags = annotations(a, b).map((p) =>
        `<span class="pair-tag ${p.status === "validée" ? "ok" : ""}" title="${esc([p.status, p.source, p.note].filter(Boolean).join(" · "))}">${esc(typeLabel[p.type] || p.type)}</span>`).join("");
      return `<tr><td>${a + 1} ↔ ${b + 1}</td>${spaces.map((s) => {
        const v = res.similarity[s.key][a][b];
        return v == null ? "<td>—</td>" : `<td><span class="bar" style="--v:${Math.max(0, v)}"></span>${v.toFixed(3)}</td>`;
      }).join("")}<td class="pair-cell">${tags}${ref.types.length ? `<button class="chip" data-annotate="${a},${b}">Annoter</button>` : ""}</td></tr>`;
    }).join("");
    $("compare-body").innerHTML = `<div class="cmp-row" style="--n:${n}">${cols}</div>
      <div class="cmp-table"><h3>Similarités (cosinus) selon chaque regard</h3>
        <table><thead><tr><th>paire</th>${head}<th title="Paires de référence du banc d'essai (pixplot pairs bench)">référence</th></tr></thead><tbody>${body}</tbody></table>
        <form class="pair-form" id="pair-form" hidden>
          <h4>Paire de référence <span id="pair-which"></span></h4>
          <label>Type de ressemblance <select name="type">${ref.types.map((t) =>
            `<option value="${t.key}" title="${esc(t.question)}">${esc(t.label)}</option>`).join("")}</select></label>
          <label>Statut <select name="status">${(ref.statuses || []).map((s) => `<option>${esc(s)}</option>`).join("")}</select></label>
          <label>Source <input name="source" placeholder="ex. Honour et Fleming, p. 670" maxlength="500"></label>
          <label>Note <input name="note" placeholder="ce que vous voyez de commun" maxlength="5000"></label>
          <div class="pair-btns"><button type="submit" class="chip">Enregistrer</button><button type="button" class="chip" id="pair-cancel">Annuler</button></div>
          <p class="prov">Les paires validées servent au banc d'essai : <code>pixplot pairs bench</code> mesure quel regard les retrouve.</p>
        </form>
        <p class="prov">Chaque colonne répond à une question différente : formes et composition (DINOv3), sujet et style tels qu'on
        les décrit (SigLIP 2), palette (couleur), facture (touche). Les valeurs ne sont pas des probabilités et ne se comparent
        qu'à l'intérieur d'une même colonne.</p></div>`;
    $("compare-body").querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => {
      $("compare").hidden = true; select(Number(b.dataset.open), true);
    }));
    $("compare-body").querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => {
      toggleCompare(Number(b.dataset.remove)); if (state.compare.length >= 2) openCompare(); else $("compare").hidden = true;
    }));
    const form = $("pair-form");
    if (!form) return;
    let current = null;
    $("compare-body").querySelectorAll("[data-annotate]").forEach((btn) => btn.addEventListener("click", () => {
      const [a, b] = btn.dataset.annotate.split(",").map(Number);
      current = [res.ids[a], res.ids[b]];
      $("pair-which").textContent = `${a + 1} ↔ ${b + 1} (n° ${current[0]} et n° ${current[1]})`;
      form.hidden = false; form.querySelector("select").focus();
    }));
    $("pair-cancel").addEventListener("click", () => { form.hidden = true; });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(form);
      try {
        const r = await fetch("/api/pairs", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ a: current[0], b: current[1], type: f.get("type"), status: f.get("status"),
                                 source: f.get("source") || "", note: f.get("note") || "" }) });
        if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
        toast("Paire enregistrée pour le banc d'essai");
        openCompare();
      } catch (err) { toast(`Échec : ${err.message}`); }
    });
  }

  // ------------------------------------------------------------------ carnet de recherche
  async function addToNotebook(entry) {
    const note = prompt(`Note pour « ${entry.title} » (facultatif) :`, entry.note || "");
    if (note === null) return;
    try {
      const r = await fetch("/api/notebook", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...entry, note }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      toast("Ajouté au carnet");
      if (state.panel === "notebook") renderNotebook();
    } catch (err) { alert(`Ajout impossible : ${err.message}`); }
  }

  const KIND_LABEL = { note: "Note", oeuvre: "Œuvre", selection: "Sélection", recherche: "Recherche", detail: "Détail",
    comparaison: "Comparaison", groupe: "Groupe" };

  async function renderNotebook() {
    showPanel("notebook", "Carnet de recherche");
    state.lastList = renderNotebook;
    state.selected = state.selectedData = null;
    redraw();
    $("fiche").hidden = false;
    let res;
    try { res = await getJSON("/api/notebook"); } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">Carnet indisponible : ${esc(err.message)}</div>`; return;
    }
    const items = res.entries.map((e) => `<li class="entry" data-id="${e.id}">
        <div class="entry-head"><span class="chip">${esc(KIND_LABEL[e.kind] || e.kind)}</span>
          <input class="entry-title" value="${esc(e.title)}" aria-label="Titre"></div>
        <div class="entry-thumbs">${e.artwork_ids.slice(0, 8).map((i) => `<img src="/api/thumb/256/${i}" data-id="${i}" alt="" loading="lazy">`).join("")}
          ${e.artwork_ids.length > 8 ? `<span class="more">+${e.artwork_ids.length - 8}</span>` : ""}</div>
        <textarea class="entry-note" placeholder="Vos observations, hypothèses, références…" aria-label="Note">${esc(e.note)}</textarea>
        <div class="entry-foot"><small>${e.created.slice(0, 16).replace("T", " ")} UTC${Object.keys(e.context).length
          ? " · " + esc(Object.entries(e.context).map(([k, v]) => `${k} : ${v}`).join(" ; ")) : ""}</small>
          <span>${e.artwork_ids.length ? `<button class="chip" data-show="${e.id}">Montrer sur la carte</button>` : ""}
          ${e.artwork_ids.length >= 2 && e.artwork_ids.length <= 6 ? `<button class="chip" data-cmp="${e.id}">Comparer</button>` : ""}
          <button class="chip" data-del="${e.id}">Supprimer</button></span></div></li>`).join("");
    $("fiche-body").innerHTML = `<div class="results-head">
        <div class="sub">${res.entries.length} entrée${res.entries.length > 1 ? "s" : ""} · enregistré dans le dossier de données (notebook.sqlite)</div>
        <div class="chips" style="margin-top:10px"><button class="chip" id="nb-new">Nouvelle note</button>
          <a class="chip" href="/api/notebook/export.md" download>Exporter en Markdown</a></div></div>
      ${res.entries.length ? `<ol class="entries">${items}</ol>` : `<div class="empty"><b>Le carnet est vide.</b><br>Depuis la fiche d'une œuvre : « Carnet ».<br>Depuis des résultats ou une comparaison : « Ajouter au carnet ».<br>Ou bien : « Nouvelle note ».</div>`}`;
    const body = $("fiche-body");
    $("nb-new").addEventListener("click", () => addToNotebook({ kind: "note", title: "Note", artwork_ids: [] }));
    const patch = (id, data) => fetch(`/api/notebook/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) })
      .then((r) => { if (r.ok) toast("Enregistré"); });
    body.querySelectorAll(".entry").forEach((li) => {
      const id = Number(li.dataset.id);
      li.querySelector(".entry-title").addEventListener("change", (e) => patch(id, { title: e.target.value }));
      li.querySelector(".entry-note").addEventListener("change", (e) => patch(id, { note: e.target.value }));
      li.querySelectorAll(".entry-thumbs img").forEach((img) => img.addEventListener("click", () => select(Number(img.dataset.id), true)));
    });
    const entryOf = (id) => res.entries.find((e) => e.id === Number(id));
    body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
      if (!confirm("Supprimer cette entrée du carnet ?")) return;
      await fetch(`/api/notebook/${b.dataset.del}`, { method: "DELETE" });
      renderNotebook();
    }));
    body.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => {
      const e = entryOf(b.dataset.show);
      const set = new Set(e.artwork_ids.map((i) => state.rowOf.get(i)).filter((r) => r !== undefined));
      setHighlight(set, `Carnet : ${e.title}`);
      const [x, y] = centerOf(set); flyTo(x, y, state.viewState.zoom);
    }));
    body.querySelectorAll("[data-cmp]").forEach((b) => b.addEventListener("click", () => {
      state.compare = entryOf(b.dataset.cmp).artwork_ids.filter((i) => state.rowOf.has(i)).slice(0, 6);
      saveCompare(); openCompare();
    }));
  }

  // ------------------------------------------------------------------ étiquettes à vérifier
  const prettyLabel = (l) => String(l).split(" · ").map((x) => pretty(x)).join(" · ");

  // ------------------------------------------------------------------ relecture rapide (façon Anki)
  // Une paire à la fois, une touche par décision : Entrée valide, 1–7 choisit le type,
  // R écarte, Espace passe, Z annule, Échap quitte.
  const rv = { queue: [], i: 0, history: [], skipped: new Set(), types: [], stats: null, busy: false };
  const pairKey = (a, b) => `${Math.min(a, b)}-${Math.max(a, b)}`;

  async function loadReviewQueue() {
    const exclude = [...rv.skipped, ...rv.history.map((h) => pairKey(h.item.a, h.item.b))].join(",");
    const res = await getJSON(`/api/review/queue?limit=30&exclude=${exclude}`);
    rv.queue = res.items; rv.i = 0; rv.types = res.types; rv.stats = res.stats;
  }

  async function openReviewSession() {
    $("review").hidden = false;
    $("rv-card").innerHTML = `<div class="loading">Préparation de la file…</div>`;
    rv.history = []; rv.skipped = new Set();
    try { await loadReviewQueue(); } catch (err) {
      $("rv-card").innerHTML = `<div class="loading">${esc(err.message)}</div>`; return;
    }
    showReviewCard();
  }

  function closeReviewSession() {
    $("review").hidden = true;
    if (state.panel === "pairs" && state.lastList) state.lastList();
  }

  function renderReviewStats() {
    const s = rv.stats;
    if (!s) return;
    const done = rv.history.length;
    $("rv-progress").textContent = `${done} relue${done > 1 ? "s" : ""} dans cette séance`;
    $("rv-goal").style.setProperty("--v", Math.min(1, s.validated / s.goal));
    $("rv-count").textContent = `${s.validated} / ${s.goal} paires validées`;
    $("rv-types-count").innerHTML = rv.types.map((t, n) =>
      `<span class="${s.by_type[t.key] ? "" : "zero"}" title="${esc(t.label)}">${n + 1}·${s.by_type[t.key] || 0}</span>`).join("");
  }

  async function showReviewCard() {
    renderReviewStats();
    if (rv.i >= rv.queue.length) {
      try { await loadReviewQueue(); } catch (err) { /* garde l'écran de fin */ }
      if (!rv.queue.length) {
        $("rv-card").innerHTML = `<div class="rv-end"><h3>Plus rien à relire pour l'instant</h3>
          <p>Toutes les paires proposées et les désaccords disponibles ont été vus. Pour en avoir d'autres :
          <code>pixplot disagreements --keep 1000</code>, ou annotez vos propres paires depuis le comparateur.</p>
          <button class="chip" id="rv-done">Fermer</button></div>`;
        $("rv-done").addEventListener("click", closeReviewSession);
        return;
      }
    }
    const it = rv.queue[rv.i];
    const suggested = rv.types.findIndex((t) => t.key === it.type);
    const why = it.origin === "proposée"
      ? `<b>Paire proposée</b>${it.source ? ` · ${esc(it.source)}` : ""}${it.note ? `<br>${esc(it.note)}` : ""}`
      : `<b>${it.rank === 1 ? "Plus proche voisine" : `${it.rank}ᵉ voisine`}</b> selon ${esc(SPACE_SHORT[it.near] || it.near)}, mais plus loin
         que ${Math.min(99, Math.floor((1 - it.centile) * 100))} % du corpus selon ${esc(SPACE_SHORT[it.far] || it.far)}. Y a-t-il un lien ?`;
    $("rv-card").innerHTML = `<div class="rv-why">${why}</div>
      <div class="rv-imgs">
        <figure><a href="/api/image/${it.a}" target="_blank" rel="noopener"><img src="/api/thumb/1024/${it.a}" alt=""></a>
          <figcaption>n° ${it.a} · ${esc(prettyLabel(it.label_a))}</figcaption></figure>
        <figure><a href="/api/image/${it.b}" target="_blank" rel="noopener"><img src="/api/thumb/1024/${it.b}" alt=""></a>
          <figcaption>n° ${it.b} · ${esc(prettyLabel(it.label_b))}</figcaption></figure>
      </div>
      <div class="rv-types">${rv.types.map((t, n) => `<button class="rv-type ${n === suggested ? "sugg" : ""}" data-n="${n}" title="${esc(t.question)}">
        <kbd>${n + 1}</kbd> ${esc(t.label)}</button>`).join("")}</div>
      <div class="rv-actions">
        <button class="btn-main" id="rv-ok"><kbd>Entrée</kbd> Valider${suggested >= 0 ? ` : ${esc(rv.types[suggested].label)}` : ""}</button>
        <button class="chip" id="rv-no"><kbd>R</kbd> ${it.origin === "proposée" ? "Rejeter" : "Pas de lien"}</button>
        <button class="chip" id="rv-skip"><kbd>Espace</kbd> Passer</button>
        <button class="chip" id="rv-undo" ${rv.history.length ? "" : "disabled"}><kbd>Z</kbd> Annuler</button>
      </div>`;
    $("rv-card").querySelectorAll(".rv-type").forEach((b) => b.addEventListener("click", () => reviewDecide("valider", Number(b.dataset.n))));
    $("rv-ok").addEventListener("click", () => reviewDecide("valider", suggested));
    $("rv-no").addEventListener("click", () => reviewDecide("rejeter"));
    $("rv-skip").addEventListener("click", reviewSkip);
    $("rv-undo").addEventListener("click", reviewUndo);
    // précharge la suivante, pour que l'enchaînement soit instantané
    const next = rv.queue[rv.i + 1];
    if (next) { new Image().src = `/api/thumb/1024/${next.a}`; new Image().src = `/api/thumb/1024/${next.b}`; }
  }

  async function reviewDecide(decision, n) {
    if (rv.busy || rv.i >= rv.queue.length) return;
    const it = rv.queue[rv.i];
    const type = decision === "valider" ? (rv.types[n] || {}).key : it.type;
    if (!type) { toast("Choisissez la sorte de ressemblance (touches 1 à 7)"); return; }
    const body = { a: it.a, b: it.b, decision, type, origin: it.origin, proposed_type: it.origin === "proposée" ? it.type : "",
                   source: it.origin === "proposée" ? it.source : `relecture : ${it.source}`, note: it.note || "" };
    rv.busy = true;
    try {
      const r = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || r.statusText);
      rv.stats = out.stats;
      rv.history.push({ item: it, body });
      rv.i++;
      showReviewCard();
    } catch (err) { toast(`Échec : ${err.message}`); } finally { rv.busy = false; }
  }

  function reviewSkip() {
    if (rv.i >= rv.queue.length) return;
    const it = rv.queue[rv.i];
    rv.skipped.add(pairKey(it.a, it.b));
    rv.i++;
    showReviewCard();
  }

  async function reviewUndo() {
    const last = rv.history.pop();
    if (!last || rv.busy) return;
    rv.busy = true;
    try {
      const r = await fetch("/api/review/undo", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(last.body) });
      const out = await r.json();
      if (!r.ok) throw new Error(out.detail || r.statusText);
      rv.stats = out.stats;
      rv.queue.splice(rv.i, 0, last.item);
      toast("Décision annulée");
      showReviewCard();
    } catch (err) { rv.history.push(last); toast(`Échec : ${err.message}`); } finally { rv.busy = false; }
  }

  function reviewKeys(e) {
    if ($("review").hidden) return;
    const k = e.key;
    let handled = true;
    if (k === "Escape") closeReviewSession();
    else if (k === "Enter") $("rv-ok") && $("rv-ok").click();
    else if (/^[1-7]$/.test(k)) reviewDecide("valider", Number(k) - 1);
    else if (k.toLowerCase() === "r") reviewDecide("rejeter");
    else if (k === " ") reviewSkip();
    else if (k.toLowerCase() === "z") reviewUndo();
    else handled = false;
    if (handled) { e.preventDefault(); e.stopPropagation(); }
  }

  // ------------------------------------------------------------------ à vérifier : onglets
  function reviewTabs(active) {
    const nLabels = Object.values(state.info.suspects || {}).reduce((a, b) => a + b, 0);
    const nPairs = (state.info.annotated_pairs || {})["proposée"] || 0;
    return `<div class="spaces">
      ${nLabels ? `<button class="space ${active === "labels" ? "on" : ""}" data-review="labels">Étiquettes <small>${nLabels}</small></button>` : ""}
      <button class="space ${active === "pairs" ? "on" : ""}" data-review="pairs">Paires de référence <small>${nPairs} à relire</small></button></div>`;
  }
  function wireReviewTabs(body) {
    body.querySelectorAll("[data-review]").forEach((b) => b.addEventListener("click", () =>
      b.dataset.review === "labels" ? renderSuspects(null, 0) : renderPairs("proposée")));
  }
  function openReview() {
    if (Object.keys(state.info.suspects || {}).length) renderSuspects(null, 0); else renderPairs("proposée");
  }

  // ------------------------------------------------------------------ paires de référence à relire
  async function renderPairs(status) {
    showPanel("pairs", "À vérifier");
    state.lastList = () => renderPairs(status);
    $("fiche-body").innerHTML = `<div class="loading">Chargement…</div>`;
    let res;
    try { res = await getJSON("/api/pairs"); } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`; return;
    }
    const typeLabel = Object.fromEntries(res.types.map((t) => [t.key, t.label]));
    const counts = {};
    for (const p of res.pairs) counts[p.status] = (counts[p.status] || 0) + 1;
    state.info.annotated_pairs = counts;
    const items = res.pairs.filter((p) => !status || p.status === status);
    const filters = [["proposée", "à relire"], ["validée", "validées"], ["rejetée", "rejetées"], ["", "toutes"]].map(([v, l]) =>
      `<button class="chip ${v === (status || "") ? "on" : ""}" data-status="${v}">${l} <small>${v ? counts[v] || 0 : res.pairs.length}</small></button>`).join("");
    const rows = items.map((p, n) => `<li class="pair-item" data-n="${n}">
        <div class="pair-thumbs">
          <button data-id="${p.a}" title="${esc(prettyLabel(p.label_a))}"><img src="/api/thumb/256/${p.a}" alt="" loading="lazy"></button>
          <button data-id="${p.b}" title="${esc(prettyLabel(p.label_b))}"><img src="/api/thumb/256/${p.b}" alt="" loading="lazy"></button>
        </div>
        <div class="pair-info"><div><span class="pair-tag ${p.status === "validée" ? "ok" : ""}">${esc(typeLabel[p.type] || p.type)}</span>
          <small class="pair-status">${esc(p.status)}</small></div>
          ${p.note ? `<div class="pair-note">${esc(p.note)}</div>` : ""}
          ${p.source ? `<div class="pair-src">${esc(p.source)}</div>` : ""}
          <div class="pair-actions">
            ${p.status !== "validée" ? `<button class="chip" data-set="validée">Valider</button>` : ""}
            ${p.status !== "rejetée" ? `<button class="chip" data-set="rejetée">Rejeter</button>` : ""}
            <button class="chip" data-compare>Comparer</button></div></div></li>`).join("");
    const body = $("fiche-body");
    body.innerHTML = `<div class="results-head">${reviewTabs("pairs")}
        <div class="sub" style="margin-top:10px">Paires choisies par l'historien pour le banc d'essai. Seules les paires
          validées comptent dans <code>pixplot pairs bench</code>.</div>
        <button class="btn-main rv-start" id="rv-start"><kbd>R</kbd> Relecture rapide, une paire à la fois</button>
        <div class="chips" style="margin-top:10px">${filters}</div></div>
      ${items.length ? `<ol class="pairs-review">${rows}</ol>` : `<p class="empty-note">Aucune paire ici. Pour en créer une : mettez deux
        œuvres dans le comparateur et cliquez « Annoter ».</p>`}`;
    wireReviewTabs(body);
    $("rv-start").addEventListener("click", openReviewSession);
    body.querySelectorAll("[data-status]").forEach((b) => b.addEventListener("click", () => renderPairs(b.dataset.status)));
    body.querySelectorAll(".pair-thumbs [data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    body.querySelectorAll(".pair-item").forEach((li) => {
      const p = items[Number(li.dataset.n)];
      li.querySelectorAll("[data-set]").forEach((b) => b.addEventListener("click", async () => {
        try {
          const r = await fetch("/api/pairs", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ a: p.a, b: p.b, type: p.type, status: b.dataset.set, source: p.source, note: p.note }) });
          if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
          toast(b.dataset.set === "validée" ? "Paire validée" : "Paire rejetée");
          renderPairs(status);
        } catch (err) { toast(`Échec : ${err.message}`); }
      }));
      li.querySelector("[data-compare]").addEventListener("click", () => {
        state.compare = [p.a, p.b]; saveCompare(); openCompare();
      });
    });
  }

  // ------------------------------------------------------------------ désaccords entre regards
  async function renderDisagreements(near, far, offset = 0) {
    showPanel("disagreements", "Désaccords entre regards");
    const combos = Object.keys(state.info.disagreements || {});
    if (!near || !far) [near, far] = (combos.find((c) => c === "forme>sujet") || combos[0]).split(">");
    state.lastList = () => renderDisagreements(near, far, offset);
    $("fiche-body").innerHTML = `<div class="loading">Chargement…</div>`;
    let res;
    try { res = await getJSON(`/api/disagreements?near=${near}&far=${far}&offset=${offset}&limit=40`); } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`; return;
    }
    const spaces = [...new Set(combos.flatMap((c) => c.split(">")))];
    const opt = (sel) => spaces.map((s) => `<option value="${s}" ${s === sel ? "selected" : ""}>${esc(SPACE_SHORT[s] || s)}</option>`).join("");
    const rows = res.items.map((d) => `<li class="pair-item">
        <div class="pair-thumbs">
          <button data-id="${d.a}" title="${esc(prettyLabel(d.label_a))}"><img src="/api/thumb/256/${d.a}" alt="" loading="lazy"></button>
          <button data-id="${d.b}" title="${esc(prettyLabel(d.label_b))}"><img src="/api/thumb/256/${d.b}" alt="" loading="lazy"></button>
        </div>
        <div class="pair-info">
          <div><b>${d.rank === 1 ? "Plus proche voisine" : `${d.rank}ᵉ voisine`}</b> selon ${esc(SPACE_SHORT[near] || near)}</div>
          <div class="pair-src">mais plus loin que ${Math.min(99, Math.floor((1 - d.centile) * 100))} % du corpus selon ${esc(SPACE_SHORT[far] || far)}</div>
          <div class="pair-note">${esc(prettyLabel(d.label_a))}<br>${esc(prettyLabel(d.label_b))}</div>
          <div class="pair-actions"><button class="chip" data-compare="${d.a},${d.b}">Comparer</button></div></div></li>`).join("");
    const more = offset + res.items.length < res.total;
    const body = $("fiche-body");
    body.innerHTML = `<div class="results-head">
        <div class="dis-pick"><label>Proches selon <select id="dis-near">${opt(near)}</select></label>
          <label>mais loin selon <select id="dis-far">${opt(far)}</select></label></div>
        <div class="sub" style="margin-top:8px">${res.total} paires · ${esc(res.rule)} · ${res.n} œuvres connues de tous les regards</div></div>
      <ol class="pairs-review">${rows}</ol>
      <div class="pager">${offset > 0 ? `<button class="chip" id="d-prev">← Précédentes</button>` : ""}
        ${more ? `<button class="chip" id="d-next">Suivantes →</button>` : ""}</div>
      <p class="prov" style="margin:0 16px 20px">Un désaccord est une piste : une composition reprise pour un autre sujet, un
        même thème par deux mains… ou une reproduction médiocre, un recadrage, une étiquette fausse. Regardez avant de conclure.</p>`;
    const pick = () => {
      const n = $("dis-near").value, f = $("dis-far").value;
      if (n === f) { toast("Choisissez deux regards différents"); return; }
      renderDisagreements(n, f, 0);
    };
    $("dis-near").addEventListener("change", pick);
    $("dis-far").addEventListener("change", pick);
    body.querySelectorAll(".pair-thumbs [data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    body.querySelectorAll("[data-compare]").forEach((b) => b.addEventListener("click", () => {
      state.compare = b.dataset.compare.split(",").map(Number); saveCompare(); openCompare();
    }));
    if ($("d-prev")) $("d-prev").addEventListener("click", () => renderDisagreements(near, far, Math.max(0, offset - 40)));
    if ($("d-next")) $("d-next").addEventListener("click", () => renderDisagreements(near, far, offset + 40));
  }


  async function renderSuspects(key, offset) {
    showPanel("suspects", "À vérifier");
    state.lastList = () => renderSuspects(key, offset);
    $("fiche-body").innerHTML = `<div class="loading">Chargement…</div>`;
    let res;
    try { res = await getJSON(`/api/suspects?limit=40&offset=${offset}${key ? `&key=${encodeURIComponent(key)}` : ""}`); } catch (err) {
      $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`; return;
    }
    const space = state.spaces.find((s) => s.key === res.space);
    const tabs = res.keys.map((k) => `<button class="space ${k === res.key ? "on" : ""}" data-key="${k}">${esc(LABELS[k] || pretty(k))}
      <small>${state.info.suspects[k] ?? ""}</small></button>`).join("");
    const rows = res.items.map((d) => `<li class="suspect">
        <button class="s-main" data-id="${d.id}"><img src="/api/thumb/256/${d.id}" alt="" loading="lazy"></button>
        <div class="s-text"><div>n° ${d.id} : « <b>${esc(pretty(d.value))}</b> »</div>
          <div class="s-sugg">voisines : ${esc(pretty(d.suggested))} (${Math.round(d.majority * 100)} %)</div>
          <div class="s-neigh">${d.neighbors.slice(0, 4).map((i) => `<img src="/api/thumb/256/${i}" data-id="${i}" alt="" loading="lazy">`).join("")}</div></div></li>`).join("");
    const more = offset + res.items.length < res.total;
    $("fiche-body").innerHTML = `<div class="results-head">${reviewTabs("labels")}
        <div class="sub" style="margin-top:10px">${res.total} œuvres · ${esc(res.rule)} · voisines selon ${esc(space ? space.label : res.space)}</div>
        <div class="spaces" style="margin-top:10px">${tabs}</div></div>
      <ol class="suspects">${rows}</ol>
      <div class="pager">${offset > 0 ? `<button class="chip" id="s-prev">← Précédentes</button>` : ""}
        ${more ? `<button class="chip" id="s-next">Suivantes →</button>` : ""}
        <button class="chip" id="s-note">Ajouter cette page au carnet</button></div>
      <p class="prov" style="margin:0 16px 20px">Ce ne sont pas des corrections : une étiquette peut être fausse, ou l'œuvre réellement
        à part dans le corpus (un paysage chez un portraitiste). Les deux méritent un regard.</p>`;
    const body = $("fiche-body");
    wireReviewTabs(body);
    body.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", () => renderSuspects(b.dataset.key, 0)));
    body.querySelectorAll(".suspects [data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    if ($("s-prev")) $("s-prev").addEventListener("click", () => renderSuspects(res.key, Math.max(0, offset - 40)));
    if ($("s-next")) $("s-next").addEventListener("click", () => renderSuspects(res.key, offset + 40));
    $("s-note").addEventListener("click", () => addToNotebook({
      kind: "selection", title: `Étiquettes « ${LABELS[res.key] || res.key} » à vérifier`, artwork_ids: res.items.map((d) => d.id),
      context: { règle: res.rule, espace: res.space },
    }));
    const set = new Set(res.items.map((d) => state.rowOf.get(d.id)).filter((r) => r !== undefined));
    state.selected = state.selectedData = null;
    setHighlight(set, `À vérifier (${LABELS[res.key] || res.key})`);
    if (isMapLayout()) flyTo(0, 0, state.fitZoom); else fitToPositions();
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
        <div class="actions">
          ${state.searchStatus.region ? `<button class="action" id="chip-detail" title="Tracez un cadre sur l'image : main, drapé, objet…">${ICON.detail}Chercher un détail</button>` : ""}
          <button class="action ${state.compare.includes(d.id) ? "on" : ""}" id="chip-compare" title="Mettre de côté pour comparer (6 au plus)">${ICON.compare}<span>${state.compare.includes(d.id) ? "Dans le comparateur" : "Comparer"}</span></button>
          <button class="action" id="chip-note" title="Garder cette œuvre et ses voisines dans le carnet, avec une note">${ICON.note}Carnet</button>
          <button class="action" id="chip-export" title="Dossier .zip : l'œuvre, ses voisines, relations et métadonnées">${ICON.export}Exporter</button>
        </div>
        <div class="chips">
          <button class="chip" id="chip-group" title="Voir tout le groupe sur la carte">Groupe ${d.cluster}${d.group_name ? ` · ${esc(d.group_name)}` : ""}</button>${fam}
          <span class="chip ${atyp >= 90 ? "warn" : ""}" title="Rang d'isolement parmi toutes les œuvres : 100 % = la plus isolée">Atypicité ${atyp} %</span>
          <button class="chip" id="chip-fly">Voir sur la carte</button>
        </div>
        ${labelChecks(d)}
        ${meta ? `<table>${meta}</table>` : ""}
        <h4>Œuvres les plus proches</h4>
        ${spaceTabs(d.space)}
        <div class="neighbors">${neigh}</div>
        <div class="prov">${esc(spaceAbout(d.space))} Vecteurs de l'analyse : ${esc(d.provenance.features)} · ${esc(d.provenance.analysis)}.
          Une proximité est une piste à examiner, pas une preuve de filiation.</div>
      </div>`;
    $("fiche-body").querySelectorAll(".space[data-space]").forEach((b) => b.addEventListener("click", () => {
      state.space = b.dataset.space;
      store.set("space", state.space);
      select(d.id, false);
    }));
    $("chip-compare").addEventListener("click", (e) => {
      const on = toggleCompare(d.id);
      e.currentTarget.classList.toggle("on", on);
      e.currentTarget.querySelector("span").textContent = on ? "Dans le comparateur" : "Comparer";
    });
    $("chip-note").addEventListener("click", () => addToNotebook({
      kind: "oeuvre", title: pretty(d.label), artwork_ids: [d.id, ...d.neighbors.slice(0, 11).map((n) => n.id)],
      context: { "œuvre": d.id, voisines: spaceLabel(d.space) },
    }));
    showPanel("fiche", `Œuvre n° ${d.id}`, state.lastList);
    $("fiche-body").querySelectorAll(".neighbor").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
    $("chip-fly").addEventListener("click", () => { const [x, y] = posOf(d.id); flyTo(x, y, Math.max(state.viewState.zoom, state.fitZoom + 3)); });
    $("chip-group").addEventListener("click", () => {
      const li = document.querySelector(`.group[data-cluster="${d.cluster - 1}"]`);
      if (li) { li.scrollIntoView({ block: "nearest" }); if (!li.classList.contains("active")) li.click(); }
    });
    if ($("chip-detail")) $("chip-detail").addEventListener("click", () => toggleDrawing(d));
    $("chip-export").addEventListener("click", (e) => exportPack({
      ids: [d.id, ...d.neighbors.map((n) => n.id)],
      title: `${pretty(d.label)} et ses voisines`,
      selection: { "méthode": `œuvre et ses plus proches voisines (${spaceLabel(d.space)}), depuis l'Atlas`, "œuvre de départ": `${d.id} — ${d.label}` },
      scores: Object.fromEntries(d.neighbors.map((n) => [n.id, n.score])),
    }, e.currentTarget));
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
        <div class="chips" style="margin-top:10px"><button class="chip" id="export-results" title="Dossier .zip : images, métadonnées, relations, résumé pour un LLM">Exporter en Research Pack</button>
          <button class="chip" id="note-results" title="Garder ces résultats dans le carnet, avec une note">Ajouter au carnet</button></div></div>
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
    showPanel("results", r.kind === "region" ? "Détails semblables" : "Recherche par description");
    state.lastList = () => renderResults(r);
    $("note-results").addEventListener("click", () => addToNotebook({
      kind: r.kind === "region" ? "detail" : "recherche", title: r.kind === "region" ? `Détail de l'œuvre n° ${r.query.id}` : r.title,
      artwork_ids: (r.query ? [r.query.id] : []).concat(r.results.map((x) => x.id)),
      context: r.kind === "region" ? { "œuvre": r.query.id, cadre: r.query.box.map((v) => +v.toFixed(3)).join(", ") } : { requête: r.title },
    }));
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

  // Panneau de droite : un titre, et « Retour » vers la liste d'où l'on vient (résultats,
  // carnet, étiquettes à vérifier) quand on a ouvert une œuvre depuis elle.
  function showPanel(kind, title, back) {
    state.panel = kind;
    state.panelBack = back || null;
    $("fiche-title").textContent = title;
    $("fiche-back").hidden = !back;
    $("fiche").hidden = false;
  }

  function closeFiche() {
    $("fiche").hidden = true;
    state.selected = state.selectedData = null;
    state.lastResults = null;
    state.lastList = null;
    history.replaceState(null, "", location.pathname);
    redraw();
  }

  // ------------------------------------------------------------------ interface
  function wireUI() {
    $("display").addEventListener("change", (e) => {
      state.display = e.target.value;
      computeHD();
      redraw();
    });
    $("colorby").addEventListener("change", async (e) => {
      const mode = e.target.value;
      if (mode.startsWith("leiden:")) {
        const sp = mode.split(":")[1];
        if (!state.comm[sp]) {
          try { state.comm[sp] = await getJSON(`/api/communities/${sp}`); } catch (err) {
            toast(`Groupes Leiden indisponibles : ${err.message}`); e.target.value = state.colorMode; return;
          }
        }
      }
      state.colorMode = mode;
      // Les couleurs ne se voient que sur les points : on y bascule.
      state.display = "points";
      $("display").value = "points";
      computeHD();
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
    $("reset-view").addEventListener("click", () => {
      clearHighlight();
      if (isMapLayout()) flyTo(0, 0, state.fitZoom); else fitToPositions();
    });
    $("layout").addEventListener("change", (e) => setLayout(e.target.value));
    $("open-compare").addEventListener("click", openCompare);
    $("compare-close").addEventListener("click", () => { $("compare").hidden = true; });
    $("compare-clear").addEventListener("click", () => { state.compare = []; saveCompare(); $("compare").hidden = true; });
    $("compare-export").addEventListener("click", (e) => exportPack({
      ids: state.compare, title: "Comparaison",
      selection: { "méthode": "comparaison d'œuvres choisies dans l'Atlas" },
    }, e.currentTarget));
    $("compare-note").addEventListener("click", () => addToNotebook({
      kind: "comparaison", title: `Comparaison de ${state.compare.length} œuvres`, artwork_ids: state.compare,
      context: { espaces: state.spaces.map((s) => s.key).join(", ") },
    }));
    $("open-notebook").addEventListener("click", renderNotebook);
    $("open-suspects").addEventListener("click", openReview);
    $("open-disagreements").addEventListener("click", () => renderDisagreements());
    $("fiche-close").addEventListener("click", closeFiche);
    $("fiche-back").addEventListener("click", () => { if (state.panelBack) state.panelBack(); });

    // panneau des groupes : replié / déplié (mémorisé) ; en écran étroit, il passe par-dessus
    const root = $("layout-root");
    const narrow = () => matchMedia("(max-width: 1100px)").matches;
    const setGroups = (open) => {
      root.classList.toggle("no-groups", !open && !narrow());
      root.classList.toggle("groups-open", open && narrow());
      $("toggle-groups").setAttribute("aria-expanded", String(open));
      if (!narrow()) store.set("groups", open);  // en écran étroit, le panneau se ferme seul : ne pas le retenir
      setTimeout(onResize, 50);
    };
    setGroups(narrow() ? false : store.get("groups", true));
    $("toggle-groups").addEventListener("click", () => setGroups($("toggle-groups").getAttribute("aria-expanded") !== "true"));

    // menu « Vue » : carte, affichage, couleurs
    const menu = $("view-menu"), viewBtn = $("open-view");
    const setMenu = (open) => { menu.hidden = !open; viewBtn.setAttribute("aria-expanded", String(open)); };
    viewBtn.addEventListener("click", (e) => { e.stopPropagation(); setMenu(menu.hidden); });
    menu.addEventListener("click", (e) => e.stopPropagation());
    document.addEventListener("click", () => setMenu(false));

    // aide : à la première visite, puis par « ? »
    const help = $("help");
    const setHelp = (open) => { help.hidden = !open; if (!open) store.set("seenHelp", true); else $("help-start").focus(); };
    $("open-help").addEventListener("click", () => setHelp(true));
    $("help-close").addEventListener("click", () => setHelp(false));
    $("help-start").addEventListener("click", () => setHelp(false));
    help.addEventListener("click", (e) => { if (e.target === help) setHelp(false); });
    $("help-lead").textContent = `${state.n.toLocaleString("fr-FR")} œuvres, réparties en ${state.clusters.length} groupes. `
      + "Chaque vignette est une œuvre ; celles qui se ressemblent sont voisines sur la carte.";
    if (!store.get("seenHelp", false)) { setHelp(true); store.set("seenHelp", true); }

    // raccourcis clavier (sauf quand on écrit dans un champ)
    addEventListener("keydown", (e) => {
      if (!$("review").hidden) return;   // la relecture garde le clavier pour elle
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
      if (e.key === "Escape") {
        if (!help.hidden) setHelp(false);
        else if (!menu.hidden) setMenu(false);
        else if (!$("compare").hidden) $("compare").hidden = true;
        else if (narrow() && root.classList.contains("groups-open")) setGroups(false);
        else closeFiche();
        if (typing) document.activeElement.blur();
        return;
      }
      if (typing || e.ctrlKey || e.metaKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (e.key === "/") { e.preventDefault(); $("search").focus(); }
      else if (e.key === "?") setHelp(true);
      else if (k === "g") setGroups($("toggle-groups").getAttribute("aria-expanded") !== "true");
      else if (k === "c") openCompare();
      else if (k === "n") renderNotebook();
      else if (k === "v" && !$("open-suspects").hidden) openReview();
      else if (k === "d" && !$("open-disagreements").hidden) renderDisagreements();
      else if (k === "r") openReviewSession();
      else if (e.key === "0") $("reset-view").click();
    });
    document.addEventListener("keydown", reviewKeys, true);
    $("rv-close").addEventListener("click", closeReviewSession);
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
