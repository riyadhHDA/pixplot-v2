/* PixPlot v2 — Atlas : couleurs des points et légende.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

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
  sel.innerHTML = opts.map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join("");
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

// Le tableau n'est recalculé que si le mode de couleur, la surbrillance ou les groupes chargés
// changent : même référence → deck.gl ne le renvoie pas à la carte graphique.
let colorCache = { key: null, hl: null, out: null };
function colorArray() {
  const key = `${state.colorMode}|${state.highlightLabel}|${Object.keys(state.comm || {}).length}`;
  if (colorCache.out && colorCache.key === key && colorCache.hl === state.highlight) return colorCache.out;
  const out = new Uint8Array(state.n * 4);
  const ctx = state.colorMode.startsWith("meta:") ? categoryInfo(state.colorMode.slice(5)) : null;
  for (let i = 0; i < state.n; i++) {
    const c = baseColor(i, ctx);
    const on = !state.highlight || state.highlight.has(i);
    out[4 * i] = c[0]; out[4 * i + 1] = c[1]; out[4 * i + 2] = c[2];
    out[4 * i + 3] = on ? 230 : 28;
  }
  colorCache = { key, hl: state.highlight, out };
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
