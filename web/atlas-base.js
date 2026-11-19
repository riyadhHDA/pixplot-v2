/* PixPlot v2 — Atlas : carte interactive du corpus (deck.gl, sans étape de compilation).
 *
 * Vue d'ensemble : un point par œuvre, coloré selon le mode choisi.
 * En zoomant : les vignettes remplacent les points (seulement celles visibles à l'écran,
 * pour rester fluide avec des centaines de milliers d'œuvres).
 * Clic : fiche de l'œuvre + liens vers ses plus proches voisines.
 *
 * Ce fichier : constantes, état commun, utilitaires, chargement des données (init).
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale).
 */
"use strict";

const { Deck, OrthographicView, ScatterplotLayer, IconLayer, TextLayer, LineLayer, LinearInterpolator } = deck;

const WORLD = 1000;            // les coordonnées [-1, 1] deviennent [-1000, 1000]
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
  sprites: null, spriteSize: null, display: "sprites",
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
  if (m.lat || Object.keys(state.info.places || {}).length) other.push(["geo", "Géographie (lieux)"]);
  if (other.length) groups.push(["Dates et lieux", other]);
  $("layout").innerHTML = groups.map(([g, opts]) => `<optgroup label="${esc(g)}">${opts.map(([v, l]) =>
    `<option value="${v}">${esc(l)}</option>`).join("")}</optgroup>`).join("");
  $("groups-count").textContent = `· ${state.clusters.length}`;
  $("open-suspects").hidden = !Object.keys(state.info.suspects || {}).length && !Object.keys(state.info.annotated_pairs || {}).length;
  $("open-disagreements").hidden = !Object.keys(state.info.disagreements || {}).length;
  const textOpt = $("search-mode").querySelector('option[value="text"]');
  textOpt.disabled = !state.searchStatus.text;
  textOpt.title = state.searchStatus.text ? "" : "Calculez d'abord les vecteurs SigLIP 2";
  const zoneOpt = $("search-mode").querySelector('option[value="zone"]');
  zoneOpt.disabled = !state.searchStatus.zones;
  zoneOpt.title = state.searchStatus.zones ? "Chercher une zone d'œuvre avec des mots : « une auréole », « un crâne »" : "Calculez d'abord l'index des zones : pixplot zones";
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
