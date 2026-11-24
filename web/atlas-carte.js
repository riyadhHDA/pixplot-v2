/* PixPlot v2 — Atlas : deck.gl, vignettes (planches et haute définition), dessin des couches.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

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
      const wasTiles = useTiles();
      state.viewState = viewState;
      deckgl.setProps({ viewState });
      if (useTiles() !== wasTiles) redraw();
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

function pickRowAt(wx, wy) {
  // Sur les tuiles (image précalculée), on retrouve l'œuvre sous le pointeur en parcourant
  // les positions en ordre inverse (l'œuvre dessinée en dernier est au-dessus).
  const half = Math.max(state.iconSize * 0.55, 6 / Math.pow(2, state.viewState.zoom));
  const pos = state.positions;
  for (let r = state.n - 1; r >= 0; r--) {
    if (Math.abs(pos[2 * r] - wx) <= half && Math.abs(pos[2 * r + 1] - wy) <= half) return r;
  }
  return -1;
}

function pickedId(info) {
  if (!info || !info.layer) return null;
  const id = info.layer.id;
  if (id.startsWith("map-tiles")) {
    if (!info.coordinate) return null;
    const r = pickRowAt(info.coordinate[0], info.coordinate[1]);
    return r >= 0 ? state.map.ids[r] : null;
  }
  if (info.index < 0) return null;
  if (id.startsWith("sheet-") || id.startsWith("hd-")) return state.map.ids[info.object.r ?? info.object];
  if (id === "points") return state.map.ids[info.index];
  return null;
}

// ------------------------------------------------------------------ tuiles & vignettes
// Les tuiles précalculées servent aux zooms éloignés de la carte principale (sans filtre ni
// surbrillance) : elles évitent de télécharger et d'envoyer sur le GPU toutes les planches
// dès l'ouverture. Au zoom (ou dès qu'un filtre/une autre carte demande les vignettes), on
// charge les planches puis la haute définition.
const TILE_MAX_PX = 24;

async function loadTiles() {
  state.tilesLoading = true;
  try {
    const meta = await getJSON("/api/tiles");
    const sets = {};
    for (const [lv, keys] of Object.entries(meta.levels || {})) sets[lv] = new Set(keys);
    state.tiles = meta;
    state.tileSet = sets;
    state.tilesLoading = false;
    if ($("tiles-row")) $("tiles-row").hidden = false;
    if ($("use-tiles")) $("use-tiles").checked = state.tilesEnabled;
    computeHD();
    redraw();
  } catch {
    state.tiles = null;
    state.tilesLoading = false;
    loadSprites();
  }
}

function ensureSprites() {
  if (!state.sprites && !state.spritesLoading) loadSprites();
}

async function loadSprites() {
  if (state.sprites || state.spritesLoading) return;
  state.spritesLoading = true;
  let meta;
  try { meta = await getJSON("/api/sprites"); } catch { state.spritesLoading = false; return; } // à défaut : les points
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
  state.spritesLoading = false;
  redraw();
  scheduleHD();
}

function onScreenSize() { return state.iconSize * Math.pow(2, state.viewState.zoom); }
function tilesAllowed() {
  return Boolean(state.tiles && state.tilesEnabled && state.display === "sprites"
    && state.layout === "map" && !state.highlight);
}
function useTiles() {
  if (!tilesAllowed()) return false;
  // On garde les tuiles aux zooms éloignés (< TILE_MAX_PX), et aussi le temps que les
  // planches finissent de se charger si l'utilisateur vient de franchir le seuil.
  return onScreenSize() < TILE_MAX_PX || !state.sprites;
}
function showSprites() { return !useTiles() && state.sprites && state.display === "sprites" && onScreenSize() >= 4; }

function scheduleIcons() { scheduleHD(); }
function scheduleHD() {
  clearTimeout(state.iconTimer);
  state.iconTimer = setTimeout(() => { computeHD(); redraw(); }, 120);
}

// Haute définition : trois niveaux, chacun dans UNE texture de taille fixe (8 192 px de côté
// si la carte graphique le permet), gérée ici (cases recyclées : les moins récemment vues partent).
// Un niveau ne sert que s'il peut couvrir TOUTES les vignettes à l'écran, et il les dessine dans
// le même ordre que les planches : une œuvre ne passe jamais devant ou derrière sa voisine selon
// le zoom (les vignettes se chevauchent sur la carte).
// Avant, deck.gl empilait chaque vignette dans une texture qui grandissait sans limite
// (cases noires, ralentissements). Les images arrivent du centre de l'écran vers les bords,
// huit à la fois ; celles qui ne sont plus à l'écran ne sont pas téléchargées.
//   cell : taille d'une case (px) · src : vignette demandée au serveur
//   from : taille à l'écran (px physiques) à partir de laquelle ce niveau sert
const HD_TIERS = [
  { cell: 128, src: 256, from: 34 },
  { cell: 512, src: 1024, from: 150 },
  { cell: 1024, src: 1024, from: 520 },
].map((t) => ({ ...t, tex: null, slots: [], cap: 0, cache: new Map(), pending: new Set(), mapping: {}, shown: [], version: 0 }));
state.hdTiers = HD_TIERS; state.flyTo = (...a) => flyTo(...a); // pour mesurer depuis la console
const COLLISION_EXT = deck.CollisionFilterExtension ? [new deck.CollisionFilterExtension()] : [];
const HD_PARALLEL = 6;          // lots en cours à la fois
const hdQueue = [];
const HD_RETRIES = 2;           // nouvelles tentatives pour un lot qui a échoué
let hdActive = 0, hdFlush = null, hdClock = 0, hdFinest = null;

function hdCapacity(t) {
  // nombre de cases d'un niveau, sans créer sa texture (marge de 10 % pour recycler)
  if (t.cap) return t.cap;
  const device = deckgl && deckgl.device;
  const side = Math.min(8192, (device && device.limits && device.limits.maxTextureDimension2D) || 4096);
  const per = side / t.cell;
  return Math.floor(per * per * 0.9);
}

function hdTexture(t) {
  if (t.tex) return t.tex;
  const device = deckgl && deckgl.device;
  if (!device) return null;
  const side = Math.min(8192, (device.limits && device.limits.maxTextureDimension2D) || 4096);
  t.tex = device.createTexture({
    width: side, height: side, format: "rgba8unorm",
    // sans mipmaps : essayés, ils provoquaient des erreurs WebGL et ralentissaient le chargement
    sampler: { minFilter: "linear", magFilter: "linear", addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge" },
  });
  const per = side / t.cell;
  t.cap = Math.floor(per * per * 0.9); // on garde une marge pour recycler
  for (let i = 0; i < per * per; i++) t.slots.push({ x: (i % per) * t.cell, y: Math.floor(i / per) * t.cell, id: null, used: 0 });
  return t.tex;
}

function hdFree(t, keep) {
  // une case vide, sinon la moins récemment vue parmi celles qui ne sont pas à l'écran
  let best = null;
  for (const s of t.slots) {
    if (s.id == null) return s;
    if (keep.has(s.id)) continue;
    if (!best || s.used < best.used) best = s;
  }
  if (best) { t.cache.delete(best.id); delete t.mapping[best.id]; }
  return best;
}

// Les vignettes partent par lots (une requête pour plusieurs dizaines d'images : le navigateur
// n'ouvre que 6 connexions à la fois) vers deux « workers » qui les décodent et les mettent à la
// taille de leur case hors du fil principal ; il ne reste ici qu'à les copier dans la texture.
const HD_BATCH = { 256: 48, 1024: 8 };     // vignettes par lot, selon leur taille
const hdWorkers = [];
const hdJobs = new Map();
let hdJobId = 0;

function hdWorker() {
  if (!hdWorkers.length) {
    for (let k = 0; k < 2; k++) {
      const w = new Worker("hd-worker.js");
      w.onmessage = (e) => hdReceive(e.data);
      hdWorkers.push(w);
    }
  }
  return hdWorkers[hdJobId % hdWorkers.length];
}

function hdSize(t, r) {
  const a = state.map.aspect[r] || 1; // largeur / hauteur
  return a >= 1 ? [t.cell, Math.max(1, Math.round(t.cell / a))] : [Math.max(1, Math.round(t.cell * a)), t.cell];
}

function hdPump() {
  while (hdActive < HD_PARALLEL && hdQueue.length) {
    const t = hdQueue[0].t, max = HD_BATCH[t.src] || 16, batch = [];
    while (hdQueue.length && hdQueue[0].t === t && batch.length < max) {
      const job = hdQueue.shift();
      if (!t.cache.has(job.id) && job.gen === hdClock && !t.pending.has(job.id)) batch.push(job);
    }
    if (!batch.length) continue;
    const job = ++hdJobId;
    batch.forEach((b) => t.pending.add(b.id));
    hdJobs.set(job, { t, batch });
    hdActive++;
    hdWorker().postMessage({
      job, url: `/api/thumbs/${t.src}?ids=${batch.map((b) => b.id).join(",")}`,
      dims: batch.map((b) => hdSize(t, state.rowOf.get(b.id))),
    });
  }
}

function hdReceive({ job, images }) {
  const { t, batch } = hdJobs.get(job) || {};
  hdJobs.delete(job);
  hdActive--;
  if (!t) return;
  batch.forEach((b) => t.pending.delete(b.id));
  if (!images) hdRetry(t, batch);
  if (images && !hdTexture(t)) images.forEach((img) => img && img.close());
  if (images && hdTexture(t)) {
    const now = performance.now();
    batch.forEach((b, k) => {
      const img = images[k];
      if (!img) return;
      const slot = t.cache.has(b.id) ? null : hdFree(t, t.wanted || new Set());
      if (slot) {
        t.tex.copyExternalImage({ image: img, x: slot.x, y: slot.y, width: img.width, height: img.height });
        slot.id = b.id; slot.used = now;
        t.cache.set(b.id, slot);
        t.mapping[b.id] = { x: slot.x, y: slot.y, width: img.width, height: img.height };
      }
      img.close();
    });
    hdChanged();
  }
  hdPump();
}

// Lot échoué (serveur occupé, réseau) : les vignettes encore à l'écran repartent, un peu plus tard,
// au plus HD_RETRIES fois ; sinon elles restaient en basse définition jusqu'au prochain mouvement.
function hdRetry(t, batch) {
  const again = batch.filter((b) => (b.tries || 0) < HD_RETRIES && t === hdFinest
    && t.wanted && t.wanted.has(b.id) && !t.cache.has(b.id));
  if (!again.length) return;
  setTimeout(() => {
    if (t !== hdFinest) return;
    for (const b of again) if (t.wanted.has(b.id) && !t.cache.has(b.id)) hdQueue.push({ t, id: b.id, gen: hdClock, tries: (b.tries || 0) + 1 });
    hdPump();
  }, 800);
}

function hdChanged() {
  // regrouper : une mise à jour de l'affichage toutes les 40 ms au plus
  if (hdFlush) return;
  hdFlush = setTimeout(() => {
    hdFlush = null;
    HD_TIERS.forEach(hdShown);
    redraw();
  }, 40);
}

function hdShown(t) {
  const now = performance.now();
  t.shown = (t.order || []).filter((d) => t.cache.has(d.id)).map((d) => {
    t.cache.get(d.id).used = now;
    return { ...d, key: String(d.id) };
  });
  t.mapping = { ...t.mapping }; // nouvelle référence : deck.gl relit les coordonnées
  t.version++;
}

function computeHD() {
  const px = onScreenSize();
  const dpx = px * (window.devicePixelRatio || 1);
  hdClock++;
  hdQueue.length = 0;
  if (!showSprites() || dpx < HD_TIERS[0].from) {
    HD_TIERS.forEach((t) => { t.order = []; t.wanted = new Set(); t.shown = []; });
    hdFinest = null;
    if (useTiles()) {
      $("hint").textContent = `${state.n.toLocaleString("fr-FR")} œuvres (tuiles) · zoomez pour les vignettes et la haute définition · clic : fiche`;
    } else {
      $("hint").textContent = state.display === "sprites"
        ? `${state.n.toLocaleString("fr-FR")} vignettes · zoomez pour la haute définition · clic : fiche`
        : "Molette : zoomer · glisser : se déplacer · clic sur une œuvre : sa fiche";
    }
    return;
  }
  const el = $("map"), scale = Math.pow(2, state.viewState.zoom);
  const halfW = el.clientWidth / 2 / scale + state.iconSize, halfH = el.clientHeight / 2 / scale + state.iconSize;
  const [cx, cy] = state.viewState.target;
  const visible = [];
  for (let r = 0; r < state.n; r++) {
    if (state.highlight && !state.highlight.has(r)) continue;
    const dx = state.positions[2 * r] - cx, dy = state.positions[2 * r + 1] - cy;
    if (Math.abs(dx) < halfW && Math.abs(dy) < halfH) visible.push([r, dx * dx + dy * dy]);
  }
  visible.sort((a, b) => a[1] - b[1]); // le centre de l'écran d'abord
  let total = 0;
  const byRow = visible.map(([r]) => r).sort((a, b) => a - b); // l'ordre des planches
  // Un seul niveau se charge : le plus fin qui couvre tout l'écran. Les niveaux plus grossiers
  // déjà en mémoire restent affichés dessous le temps qu'il arrive, sans rien télécharger de plus
  // (avant : les trois niveaux téléchargeaient les mêmes vignettes, et 768 Mo de textures).
  let finest = null;
  for (const t of HD_TIERS) if (dpx >= t.from && visible.length <= hdCapacity(t)) finest = t;
  hdFinest = finest;
  HD_TIERS.forEach((t) => {
    const active = t === finest && hdTexture(t);
    const fallback = !active && finest && t.tex && HD_TIERS.indexOf(t) < HD_TIERS.indexOf(finest);
    t.order = active || fallback ? byRow.map((r) => ({ r, id: state.map.ids[r] })) : [];
    t.wanted = new Set(t.order.map((d) => d.id));
    if (active) total = visible.length;
  });
  // file d'attente : du centre vers les bords, pour le seul niveau actif
  if (finest && finest.tex) {
    for (const [r] of visible) {
      const id = state.map.ids[r];
      if (!finest.cache.has(id)) hdQueue.push({ t: finest, id, gen: hdClock });
    }
  }
  HD_TIERS.forEach(hdShown);
  hdPump();
  $("hint").textContent = total
    ? `Haute définition : ${total} vignettes · clic : fiche`
    : `${state.n.toLocaleString("fr-FR")} vignettes · zoomez pour la haute définition · clic : fiche`;
}

function spriteColor(r) {
  return !state.highlight || state.highlight.has(r) ? [255, 255, 255, 255] : [255, 255, 255, 30];
}

function redraw() {
  const layers = [];
  const tilesOn = useTiles();
  const sprites = showSprites();
  const showingIcons = sprites || tilesOn;
  // Charger les planches dès que l'utilisateur quitte le domaine des tuiles (zoom proche,
  // filtre actif, autre carte ou tuiles désactivées) et veut des vignettes.
  if (state.display === "sprites" && !state.tilesLoading && (!tilesAllowed() || onScreenSize() >= TILE_MAX_PX)) ensureSprites();
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
  if (state.layout === "geo") {
    const paths = circulationPaths();
    if (paths.length) layers.push(new deck.PathLayer({
      id: "circulations", data: paths, getPath: (d) => d.path,
      getColor: (d) => [...d.color, 150], getWidth: 1.5, widthUnits: "pixels", jointRounded: true,
    }));
  }
  layers.push(new ScatterplotLayer({
    id: "points",
    visible: !sprites && !tilesOn,
    data: { length: state.n, attributes: {
      getPosition: { value: state.positions, size: 2 },
      getFillColor: { value: colorArray(), size: 4, normalized: true },
    } },
    radiusUnits: "pixels",
    getRadius: 3,
    radiusMinPixels: 1, radiusMaxPixels: 6,
    pickable: true, autoHighlight: true, highlightColor: [255, 255, 255, 255],
    updateTriggers: { getFillColor: [state.colorMode, state.highlightLabel], getPosition: [state.layout, state.posVersion] },
  }));
  if (state.tiles && state.tilesEnabled) {
    const tm = state.tiles, ext = tm.extent;
    layers.push(new TileLayer({
      id: "map-tiles",
      visible: tilesOn,
      tileSize: tm.tile_size,
      extent: [-ext, -ext, ext, ext],
      minZoom: -1,
      maxZoom: Math.max(-1, tm.max_level - 2),
      refinementStrategy: "best-available",
      pickable: true,
      getTileData: async ({ index: { x, y, z }, signal }) => {
        const level = z + 2;
        if (level < 0 || level > tm.max_level) return null;
        const grid = 1 << level, half = grid >> 1;
        const tx = x + half, ty = (grid - 1) - (y + half);
        if (tx < 0 || tx >= grid || ty < 0 || ty >= grid) return null;
        const set = state.tileSet && state.tileSet[level];
        if (set && !set.has(`${tx}/${ty}`)) return null;
        const resp = await fetch(`/api/tiles/${level}/${tx}/${ty}.${tm.format}`, { signal });
        if (!resp.ok) return null;
        return createImageBitmap(await resp.blob());
      },
      // une tuile sortie du cache libère son image (sinon la mémoire grossit à chaque zoom)
      onTileUnload: (tile) => { if (tile.content && tile.content.close) tile.content.close(); },
      renderSubLayers: (props) => {
        if (!props.data) return null;
        const { left, top, right, bottom } = props.tile.bbox;
        return new BitmapLayer(props, {
          data: null,
          image: props.data,
          bounds: [left, top, right, bottom],
          pickable: true,
          textureParameters: {
            minFilter: "linear", magFilter: "linear",
            addressModeU: "clamp-to-edge", addressModeV: "clamp-to-edge",
          },
        });
      },
    }));
  }
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
      updateTriggers: { getColor: [state.highlightLabel], getPosition: [state.layout, state.posVersion] },
    })));
  }
  if (sprites) HD_TIERS.forEach((t) => {
    if (!t.tex || !t.shown.length) return;
    layers.push(new IconLayer({
      id: `hd-${t.cell}`,
      data: t.shown,
      iconAtlas: t.tex,
      iconMapping: t.mapping,
      getIcon: (d) => d.key,
      getPosition: (d) => [state.positions[2 * d.r], state.positions[2 * d.r + 1]],
      getSize: (d) => state.spriteSize[d.r],
      sizeUnits: "common",
      getColor: (d) => spriteColor(d.r),
      updateTriggers: { getColor: [state.highlightLabel], getPosition: [state.layout, state.posVersion], getIcon: [t.version] },
    }));
  });
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
  if (isMapLayout() && state.groupLabels.length && onScreenSize() < 40 && (state.colorMode === "cluster" || sprites || tilesOn)) {
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
      extensions: COLLISION_EXT,
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
