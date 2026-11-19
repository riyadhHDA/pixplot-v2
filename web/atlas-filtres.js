/* PixPlot v2 — Atlas : filtres combinés (d'après Collection Space Navigator, Ohm et al., 2023).
 *
 * Plusieurs critères à la fois : étiquettes du catalogue (artiste, style, genre…), groupes,
 * atypicité, dates. À l'intérieur d'un critère, les valeurs cochées s'ajoutent (« ou ») ; d'un
 * critère à l'autre, elles se combinent (« et »). Chaque valeur affiche le nombre d'œuvres qu'elle
 * donnerait avec les autres critères déjà choisis. La sélection s'allume sur la carte et peut
 * partir au carnet ou dans un Research Pack.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

const FILTER_SKIP = new Set(["source"]);           // le fichier d'origine n'est pas un critère d'historien
const FACET_SHOWN = 12;                            // valeurs visibles avant « voir tout »
const PACK_MAX = 500, NOTEBOOK_MAX = 5000;          // limites de l'API

const flt = { facets: {}, atyp: [0, 100], year: null, open: new Set(), query: {} };

// Les critères disponibles : une « facette » par étiquette du catalogue, plus les groupes.
function filterFacets() {
  const out = [];
  for (const [key, cat] of Object.entries(state.map.categories)) {
    if (FILTER_SKIP.has(key)) continue;
    out.push({ key, label: LABELS[key] || pretty(key), codes: cat.codes,
               names: cat.values.map((v) => (v && !/^unknown/i.test(v) ? (SLUG_KEYS.has(key) ? pretty(v) : v) : "inconnu")) });
  }
  const names = [];
  for (const g of state.clusters) names[g.cluster] = `${g.cluster + 1}${g.name ? ` · ${g.name}` : ""}`;
  out.push({ key: "cluster", label: "Groupe", codes: state.map.cluster, names });
  return out;
}

function filtersActive() {
  return Object.values(flt.facets).some((s) => s.size) || flt.atyp[0] > 0 || flt.atyp[1] < 100 || !!flt.year;
}

// Une passe sur toutes les œuvres : la sélection, et pour chaque facette le compte de chaque
// valeur parmi les œuvres qui passent tous les AUTRES critères (comptes « croisés »).
function filterCompute(facets) {
  const n = state.n, rows = [];
  const counts = Object.fromEntries(facets.map((f) => [f.key, new Uint32Array(f.names.length)]));
  const a = state.map.atypicality, years = state.map.year;
  const [lo, hi] = [flt.atyp[0] / 100, flt.atyp[1] / 100];
  for (let r = 0; r < n; r++) {
    if (a && (a[r] < lo - 1e-9 || a[r] > hi + 1e-9)) continue;
    if (flt.year && years && !(years[r] >= flt.year[0] && years[r] <= flt.year[1])) continue;
    let failed = null, fails = 0;
    for (const f of facets) {
      const sel = flt.facets[f.key];
      if (sel && sel.size && !sel.has(f.codes[r])) { failed = f; if (++fails > 1) break; }
    }
    if (fails === 0) {
      rows.push(r);
      for (const f of facets) counts[f.key][f.codes[r]]++;
    } else if (fails === 1) counts[failed.key][failed.codes[r]]++;
  }
  return { rows, counts };
}

function filterLabel(facets) {
  const bits = facets.filter((f) => flt.facets[f.key] && flt.facets[f.key].size).map((f) =>
    `${f.label} : ${[...flt.facets[f.key]].map((c) => f.names[c]).slice(0, 3).join(" ou ")}${flt.facets[f.key].size > 3 ? "…" : ""}`);
  if (flt.atyp[0] > 0 || flt.atyp[1] < 100) bits.push(`atypicité ${flt.atyp[0]}–${flt.atyp[1]} %`);
  if (flt.year) bits.push(`dates ${flt.year[0]}–${flt.year[1]}`);
  return `Filtre (${bits.join(" · ")})`;
}

function saveFilters() {
  store.set(`filters:${state.info.analysis}`, {
    facets: Object.fromEntries(Object.entries(flt.facets).map(([k, s]) => [k, [...s]])), atyp: flt.atyp, year: flt.year });
}

function loadFilters() {
  const saved = store.get(`filters:${state.info.analysis}`, null);
  if (!saved) return;
  flt.facets = Object.fromEntries(Object.entries(saved.facets || {}).map(([k, v]) => [k, new Set(v)]));
  flt.atyp = Array.isArray(saved.atyp) ? saved.atyp : [0, 100];
  flt.year = saved.year || null;
}

// Vide les filtres (appelé aussi par « Vue d'ensemble » et l'effacement de la recherche).
function resetFilters() {
  flt.facets = {}; flt.atyp = [0, 100]; flt.year = null; flt.query = {};
  saveFilters();
  if (state.panel === "filters" && !$("fiche").hidden) renderFilters();
}

let fltLoaded = false;
function renderFilters() {
  if (!fltLoaded) { loadFilters(); fltLoaded = true; }   // les filtres de la dernière visite
  panelTurn();
  showPanel("filters", "Filtres combinés");
  state.lastList = renderFilters;
  state.selected = state.selectedData = null;
  const years = state.map.year;
  let yearRow = "";
  if (years) {
    const [y0, y1] = minMax(years.filter((y) => y != null && Number.isFinite(y)));
    if (Number.isFinite(y0)) {
      const [a, b] = flt.year || [y0, y1];
      yearRow = `<div class="flt-range"><span>Dates</span>
        <input type="number" id="flt-y0" min="${y0}" max="${y1}" value="${a}" aria-label="Année de début">
        <span>à</span><input type="number" id="flt-y1" min="${y0}" max="${y1}" value="${b}" aria-label="Année de fin"></div>`;
    }
  }
  $("fiche-body").innerHTML = `<div class="results-head flt-head">
      <div class="flt-count" id="flt-count" aria-live="polite"></div>
      <div class="chips" style="margin-top:8px">
        <button class="chip" id="flt-fit" title="Cadrer la carte sur les œuvres retenues">Cadrer</button>
        <button class="chip" id="flt-note" title="Garder la sélection dans le carnet (${NOTEBOOK_MAX.toLocaleString("fr-FR")} œuvres au plus)">Ajouter au carnet</button>
        <button class="chip" id="flt-export" title="Research Pack des ${PACK_MAX} œuvres les plus typiques de la sélection">Exporter</button>
        <button class="chip" id="flt-reset">Tout effacer</button></div>
      <p class="sub" style="margin-top:8px">Dans un critère, les valeurs cochées s'ajoutent (ou) ; d'un critère à l'autre, elles
        se combinent (et). Le nombre à côté d'une valeur : ce qu'elle donnerait avec les autres critères.</p></div>
    <div class="flt-body">
      <div class="flt-range"><span>Atypicité</span>
        <input type="number" id="flt-a0" min="0" max="100" step="5" value="${flt.atyp[0]}" aria-label="Atypicité minimale (%)">
        <span>à</span><input type="number" id="flt-a1" min="0" max="100" step="5" value="${flt.atyp[1]}" aria-label="Atypicité maximale (%)"><span>%</span></div>
      ${yearRow}
      <div id="flt-facets"></div>
      <h4 class="flt-preview-title">Les plus typiques de la sélection</h4>
      <div class="results-grid flt-preview" id="flt-preview"></div>
      <p class="prov" style="margin:0 0 20px">Les étiquettes viennent du catalogue (WikiArt : bénévoles, à vérifier) ; les groupes
        et l'atypicité sont calculés par PixPlot. Une sélection n'explique rien par elle-même : elle dit où regarder.</p></div>`;
  const num = (id, lo, hi, d) => { const v = Number($(id).value); return Number.isFinite(v) ? Math.max(lo, Math.min(hi, v)) : d; };
  const onRange = () => {
    flt.atyp = [num("flt-a0", 0, 100, 0), num("flt-a1", 0, 100, 100)].sort((x, y) => x - y);
    if ($("flt-y0")) {
      const [y0, y1] = [Number($("flt-y0").min), Number($("flt-y0").max)];
      const v = [num("flt-y0", y0, y1, y0), num("flt-y1", y0, y1, y1)].sort((x, y) => x - y);
      flt.year = v[0] > y0 || v[1] < y1 ? v : null;
    }
    applyFilters();
  };
  ["flt-a0", "flt-a1", "flt-y0", "flt-y1"].forEach((id) => $(id) && $(id).addEventListener("change", onRange));
  $("flt-reset").addEventListener("click", () => { resetFilters(); applyFilters(); });
  $("flt-fit").addEventListener("click", () => {
    if (!state.highlight) return;
    const [x, y] = centerOf(state.highlight); flyTo(x, y, state.viewState.zoom);
  });
  $("flt-note").addEventListener("click", () => {
    const rows = filterRowsTypical();
    if (!rows.length) { toast("Aucune œuvre retenue"); return; }
    addToNotebook({ kind: "selection", title: filterLabel(filterFacets()), artwork_ids: rows.slice(0, NOTEBOOK_MAX).map((r) => state.map.ids[r]),
      context: { "méthode": "filtres combinés de l'Atlas", "œuvres": rows.length } });
  });
  $("flt-export").addEventListener("click", (e) => {
    const rows = filterRowsTypical().slice(0, PACK_MAX);
    if (!rows.length) { toast("Aucune œuvre retenue"); return; }
    exportPack({ ids: rows.map((r) => state.map.ids[r]), title: filterLabel(filterFacets()),
      selection: { "méthode": `filtres combinés de l'Atlas (${rows.length} œuvres les plus typiques de la sélection)`,
                   "critères": filterLabel(filterFacets()) } }, e.currentTarget);
  });
  $("fiche").scrollTop = 0;
  applyFilters();
}

// Les œuvres retenues, de la plus typique (atypicité basse) à la plus isolée.
function filterRowsTypical() {
  const rows = filterCompute(filterFacets()).rows;
  if (!filtersActive()) return [];
  const a = state.map.atypicality;
  return a ? rows.sort((x, y) => a[x] - a[y]) : rows;
}

function applyFilters() {
  const facets = filterFacets();
  const { rows, counts } = filterCompute(facets);
  saveFilters();
  const active = filtersActive();
  document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
  setHighlight(active ? new Set(rows) : null, active ? filterLabel(facets) : "");
  if (state.panel !== "filters" || !$("flt-facets")) return;
  $("flt-count").innerHTML = active
    ? `<b>${rows.length.toLocaleString("fr-FR")}</b> œuvres sur ${state.n.toLocaleString("fr-FR")}`
    : `Aucun filtre : les ${state.n.toLocaleString("fr-FR")} œuvres`;
  $("flt-facets").innerHTML = facets.map((f) => facetHTML(f, counts[f.key])).join("");
  wireFacets(facets);
  const a = state.map.atypicality;
  const preview = active ? (a ? rows.slice().sort((x, y) => a[x] - a[y]) : rows).slice(0, 24) : [];
  $("flt-preview").innerHTML = preview.map((r) => `<button class="result" data-id="${state.map.ids[r]}" title="${esc(labelOf(r))}">
      <img src="/api/thumb/256/${state.map.ids[r]}" alt="" loading="lazy"><div class="lbl">${esc(labelOf(r))}</div></button>`).join("")
    || `<p class="sub">Cochez une valeur pour voir les œuvres.</p>`;
  $("flt-preview").querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
}

function facetHTML(f, count) {
  const sel = flt.facets[f.key] || new Set();
  const q = (flt.query[f.key] || "").toLowerCase();
  let codes = f.names.map((_, c) => c).filter((c) => count[c] > 0 || sel.has(c));
  if (q) codes = codes.filter((c) => f.names[c].toLowerCase().includes(q));
  codes.sort((x, y) => (sel.has(y) - sel.has(x)) || (count[y] - count[x]));
  const all = flt.open.has(f.key);
  const shown = all ? codes : codes.slice(0, FACET_SHOWN);
  const rows = shown.map((c) => `<label class="flt-val ${sel.has(c) ? "on" : ""}">
      <input type="checkbox" data-f="${esc(f.key)}" data-c="${c}" ${sel.has(c) ? "checked" : ""}>
      <span class="flt-name">${esc(f.names[c])}</span><span class="flt-n">${count[c].toLocaleString("fr-FR")}</span></label>`).join("");
  const search = f.names.length > 20
    ? `<input type="search" class="flt-q" data-q="${esc(f.key)}" value="${esc(flt.query[f.key] || "")}" placeholder="Chercher un ${esc(f.label.toLowerCase())}…" aria-label="Chercher dans ${esc(f.label)}">` : "";
  const more = codes.length > FACET_SHOWN
    ? `<button class="ghost flt-more" data-more="${esc(f.key)}">${all ? "Réduire" : `Voir les ${codes.length}`}</button>` : "";
  return `<section class="flt-facet"><h4>${esc(f.label)}${sel.size ? ` <small>${sel.size} choisi${sel.size > 1 ? "s" : ""}</small>` : ""}
      ${sel.size ? `<button class="ghost flt-clear" data-clear="${esc(f.key)}">effacer</button>` : ""}</h4>
    ${search}<div class="flt-vals">${rows || `<p class="sub">Aucune valeur.</p>`}</div>${more}</section>`;
}

function wireFacets() {
  const box = $("flt-facets");
  box.querySelectorAll("input[type=checkbox]").forEach((cb) => cb.addEventListener("change", () => {
    const k = cb.dataset.f, c = Number(cb.dataset.c);
    const s = flt.facets[k] || (flt.facets[k] = new Set());
    if (cb.checked) s.add(c); else s.delete(c);
    applyFilters();
  }));
  box.querySelectorAll("[data-clear]").forEach((b) => b.addEventListener("click", () => {
    delete flt.facets[b.dataset.clear]; applyFilters();
  }));
  box.querySelectorAll("[data-more]").forEach((b) => b.addEventListener("click", () => {
    const k = b.dataset.more;
    if (flt.open.has(k)) flt.open.delete(k); else flt.open.add(k);
    applyFilters();
  }));
  box.querySelectorAll("[data-q]").forEach((inp) => inp.addEventListener("input", () => {
    const k = inp.dataset.q, at = inp.selectionStart;
    flt.query[k] = inp.value;
    clearTimeout(flt.qTimer);
    flt.qTimer = setTimeout(() => {
      applyFilters();
      const again = document.querySelector(`.flt-q[data-q="${CSS.escape(k)}"]`);
      if (again) { again.focus(); again.setSelectionRange(at, at); }
    }, 150);
  }));
}
