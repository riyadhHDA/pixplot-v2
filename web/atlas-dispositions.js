/* PixPlot v2 — Atlas : carte, chronologie, géographie et lieux typés (ARTL@S).
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

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
  if (!years.length) return { pos: state.positions, axis: [], note: "aucune œuvre datée" };
  const [lo, hi] = minMax(years);
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
  const maxCount = minMax(counts)[1];
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

// ------------------------------------------------------------------ lieux typés et datés (ARTL@S)
// Chaque œuvre peut avoir plusieurs lieux : création, exposition, conservation, lieu
// représenté, naissance / résidence / mort de l'artiste. La carte montre un type à la fois ;
// les « circulations » relient, dans l'ordre des dates, les lieux d'une même œuvre.
async function loadPlaces() {
  if (state.places !== undefined) return state.places;
  try { state.places = await getJSON("/api/places"); } catch { state.places = null; }
  return state.places;
}

function placeYearRange() {
  const ys = (state.places?.year || []).filter((y) => y != null);
  return ys.length ? minMax(ys) : null;
}

function setupPlaceControls() {
  const P = state.places;
  const box = $("place-controls");
  if (!P || !P.types.length) { box.hidden = true; return; }
  box.hidden = state.layout !== "geo";
  const sel = $("place-type");
  if (!sel.options.length) {
    sel.innerHTML = P.types.map((t) => `<option value="${t.key}">${esc(t.label)} (${t.count})</option>`).join("");
    const pref = ["conservation", "creation", "exposition", "represente", "naissance_artiste", "non_precise"]
      .find((k) => P.types.some((t) => t.key === k));
    sel.value = state.placeType || pref || P.types[0].key;
    state.placeType = sel.value;
    const range = placeYearRange();
    const yr = $("place-year");
    if (range) {
      yr.min = range[0]; yr.max = range[1]; yr.value = range[1]; state.placeUntil = null;
      $("place-year-label").textContent = `toutes les dates (${range[0]}–${range[1]})`;
      $("place-year-row").hidden = false;
    } else $("place-year-row").hidden = true;
  }
}

// Lieux d'une œuvre (rangée r), éventuellement d'un seul type, en tenant compte du curseur.
function placesOf(r, type) {
  const P = state.places;
  if (!P) return [];
  if (!state.placeIndex) {
    state.placeIndex = new Map();
    P.row.forEach((row, k) => { if (!state.placeIndex.has(row)) state.placeIndex.set(row, []); state.placeIndex.get(row).push(k); });
  }
  return (state.placeIndex.get(r) || []).filter((k) => (!type || P.type[k] === type) && P.lat[k] != null && P.lon[k] != null
    && (state.placeUntil == null || P.year[k] == null || P.year[k] <= state.placeUntil));
}

function circulationPaths() {
  const P = state.places, scale = (WORLD / 180) * 8, out = [];
  if (!P || !$("place-paths").checked) return out;
  for (const [r] of state.placeIndex || []) {
    const ks = placesOf(r, null);
    if (ks.length < 2) continue;
    // ordre : lieux datés par date, puis non datés (souvent la conservation actuelle)
    ks.sort((a, b) => (P.year[a] ?? 1e9) - (P.year[b] ?? 1e9));
    const path = ks.map((k) => [P.lon[k] * scale, P.lat[k] * scale]);
    if (path.some((p, i) => i && (p[0] !== path[i - 1][0] || p[1] !== path[i - 1][1])))
      out.push({ r, path, color: PALETTE[state.map.cluster[r] % PALETTE.length] });
  }
  return out;
}

function geoPositions() {
  const m = state.map, n = state.n, cell = state.iconSize * 1.05;
  const pos = new Float32Array(n * 2);
  const placed = new Map();
  // Échelle large par rapport aux vignettes : les spirales de villes voisines (Paris,
  // Londres, Amsterdam…) ne se recouvrent pas ; on zoome pour voir le détail.
  const scale = (WORLD / 180) * 8;
  const P = state.places, type = state.placeType;
  const latOf = (r) => { if (P && type) { const k = placesOf(r, type)[0]; return k == null ? null : [P.lat[k], P.lon[k]]; }
                         return m.lat && m.lat[r] != null && m.lon[r] != null ? [m.lat[r], m.lon[r]] : null; };
  let unplaced = 0;
  state.geoPlaced = new Set();
  for (let r = 0; r < n; r++) {
    const ll = latOf(r);
    const lat = ll ? ll[0] : null, lon = ll ? ll[1] : null;
    if (!ll) unplaced++; else state.geoPlaced.add(r);
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
  if (unplaced) axis.push({ at: [190 * scale, -100 * scale + cell * (0.6 * Math.sqrt(unplaced) + 4)], text: `sans lieu de ce type (${unplaced})` });
  const t = P && P.types.find((x) => x.key === type);
  const note = (t ? `${t.label} : ${t.about}. ` : "") + "Une carte de lieux montre des répartitions et des circulations, "
    + "pas des styles : un lieu n'explique pas une manière (ARTL@S). Fond Natural Earth.";
  return { pos, axis, note };
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

function conceptAxisOverlay(xLabel, yLabel) {
  const L = WORLD * 1.08;
  return [
    { line: [[-L, 0], [L, 0]] },
    { line: [[0, -L], [0, L]] },
    { line: [[-L, -L], [L, L]] },         // diagonale : même rang sur les deux axes
    { line: [[-L, -L], [L, -L]] },
    { line: [[-L, L], [L, L]] },
    { line: [[-L, -L], [-L, L]] },
    { line: [[L, -L], [L, L]] },
    { at: [L * 0.72, -L - 35], text: `plus « ${xLabel} » →` },
    { at: [-L * 0.72, -L - 35], text: `← moins « ${xLabel} »` },
    { at: [0, L + 55], text: `↑ plus « ${yLabel} »` },
    { at: [0, -L - 75], text: `↓ moins « ${yLabel} »` },
    { at: [L * 0.85, L * 0.92], text: "diagonale (X = Y)" },
  ];
}

async function setLayout(layout) {
  const seq = ++state.conceptSeq;
  let note = "";
  if (layout.startsWith("map:")) {
    const key = layout.slice(4);
    let res;
    try { res = state.layoutCache[key] || (state.layoutCache[key] = await getJSON(`/api/layout/${key}`)); }
    catch (err) { toast(`Carte indisponible : ${err.message}`); $("layout").value = state.layout; return; }
    if (seq !== state.conceptSeq) return;
    const pos = new Float32Array(state.n * 2);
    for (let r = 0; r < state.n; r++) {
      const ok = res.x[r] != null;
      pos[2 * r] = ok ? res.x[r] * WORLD : 1.25 * WORLD;  // absentes de cet espace : rangées à droite
      pos[2 * r + 1] = ok ? res.y[r] * WORLD : -WORLD;
    }
    state.positions = pos; state.axis = [];
    const s = state.spaces.find((x) => x.key === key);
    note = s ? `Voisines selon ${s.label} : ${s.about}. Les couleurs restent celles des groupes de la carte principale.` : "";
  } else if (layout === "concepts") {
    const xq = ($("concept-x")?.value || state.conceptAxes.x || "sacré").trim();
    const yq = ($("concept-y")?.value || state.conceptAxes.y || "profane").trim();
    if (xq.length < 2 || yq.length < 2) { toast("Entrez deux mots ou expressions (2 caractères au moins)"); return; }
    if ($("concept-controls")) $("concept-controls").hidden = false;
    $("layout-note").textContent = `Calcul des axes « ${xq} » et « ${yq} »…`;
    let res;
    try {
      res = await getJSON(`/api/layout/concepts?x=${encodeURIComponent(xq)}&y=${encodeURIComponent(yq)}`);
    } catch (err) {
      if (seq !== state.conceptSeq) return;
      toast(`Axes conceptuels indisponibles : ${err.message}`);
      $("layout").value = state.layout;
      if ($("concept-controls")) $("concept-controls").hidden = state.layout !== "concepts";
      $("layout-note").textContent = state.layoutNote || "";
      return;
    }
    if (seq !== state.conceptSeq) return;
    const pos = new Float32Array(state.n * 2);
    for (let r = 0; r < state.n; r++) {
      const ok = res.x[r] != null && res.y[r] != null;
      pos[2 * r] = ok ? res.x[r] * WORLD : 1.25 * WORLD;
      pos[2 * r + 1] = ok ? res.y[r] * WORLD : -WORLD;
    }
    state.positions = pos;
    state.axis = conceptAxisOverlay(xq, yq);
    state.conceptAxes = { x: xq, y: yq, corr: res.correlation };
    note = `→ « ${xq} » · ↑ « ${yq} » (corrélation r = ${res.correlation.toFixed(2)}). `
      + "Ce qui s'écarte de la diagonale éclaire à la fois le corpus et l'imaginaire vectoriel de SigLIP 2 (Impett et Offert, 2024).";
  } else if (layout === "time") ({ pos: state.positions, axis: state.axis, note } = timePositions());
  else if (layout === "geo") {
    await loadWorld();
    await loadPlaces();
    if (seq !== state.conceptSeq) return;
    state.layout = "geo";
    setupPlaceControls();
    ({ pos: state.positions, axis: state.axis, note } = geoPositions());
  } else { state.positions = state.umapPositions.slice(); state.axis = []; }
  state.layout = layout;
  state.posVersion = (state.posVersion || 0) + 1;
  if ($("place-controls")) $("place-controls").hidden = layout !== "geo" || !(state.places && state.places.types.length);
  if ($("concept-controls")) $("concept-controls").hidden = layout !== "concepts";
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
  const only = state.layout === "geo" && state.geoPlaced && state.geoPlaced.size ? state.geoPlaced : null;
  for (let r = 0; r < state.n; r++) {
    if (only && !only.has(r)) continue;  // carte : cadrer sur les œuvres situées
    const x = state.positions[2 * r], y = state.positions[2 * r + 1];
    if (state.layout === "concepts" && Math.abs(x) > 1.15 * WORLD) continue;
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
