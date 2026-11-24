/* PixPlot v2 — Atlas : notions apprises par un regard (auto-encodeur parcimonieux, ARCHITECTURE § 37)
 * et onglet « Cadres (n° 88) » dans « À vérifier ».
 *
 * Liste des notions vivantes (numéro, étiquette Iconclass si z ≥ 5 sinon « sans nom », nombre
 * d'œuvres actives), filtrable par texte. Un clic surligne sur la carte les œuvres les plus actives
 * et permet de les envoyer au carnet ou dans un Research Pack, comme les filtres combinés.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

const NOTIONS_PAGE = 100;
const NOTION_HIGHLIGHT_MAX = 500;
const framedFeature = () => ((state.info && state.info.notions && state.info.notions.framed) || {}).feature;
const nt = { space: "sujet", query: "", filter: "all", sort: "feature", shown: NOTIONS_PAGE, active: null, detail: null, qTimer: null };
const notionsCache = {};   // une liste par regard (sujet, forme)

const META_KEY = { style: "style", genre: "genre", artist: "artiste" };
// étiquette du catalogue partagée par ≥ 60 % des œuvres les plus marquées (ce que disent les
// métadonnées, pas un nom donné par le modèle)
const metaText = (m) => m ? `${META_KEY[m.key] || m.key} : ${pretty(m.value)} (${Math.round(m.share * 100)} %)` : "";

function notionTitle(d) {
  const lbl = d.named ? d.label : (d.editorial_label || metaText(d.meta) || "sans nom");
  return `Notion n° ${d.feature} (${lbl})`;
}

function clearNotionSelection() {
  nt.active = null;
  nt.detail = null;
  state.notionsSeq++;
  document.querySelectorAll(".notion-row.on").forEach((b) => b.classList.remove("on"));
  const box = $("notion-active");
  if (box) { box.hidden = true; box.innerHTML = ""; }
}

function filteredNotions() {
  const items = (state.notionsData && state.notionsData.items) || [];
  const q = nt.query.trim().toLowerCase();
  let out = items;
  if (nt.filter === "named") out = out.filter((it) => it.named);
  else if (nt.filter === "unnamed") out = out.filter((it) => !it.named);
  if (q) {
    out = out.filter((it) => {
      const hay = `n° ${it.feature} #${it.feature} ${it.feature} ${it.label} ${it.meta ? `${it.meta.value} ${pretty(it.meta.value)}` : ""} ${it.iconclass ? it.iconclass.notation : ""}`.toLowerCase();
      return hay.includes(q);
    });
  }
  if (nt.sort === "count") out = out.slice().sort((a, b) => (b.count - a.count) || (a.feature - b.feature));
  else if (nt.sort === "z") out = out.slice().sort((a, b) => ((b.iconclass ? b.iconclass.z : -1) - (a.iconclass ? a.iconclass.z : -1)) || (a.feature - b.feature));
  return out;
}

async function renderNotions() {
  const seq = panelTurn();
  showPanel("notions", "Notions apprises");
  state.lastList = renderNotions;
  state.selected = state.selectedData = null;
  if (!state.notionsData) {
    $("fiche-body").innerHTML = `<div class="loading">Chargement des notions…</div>`;
    try {
      state.notionsData = notionsCache[nt.space] || await getJSON(`/api/notions?space=${nt.space}`);
      notionsCache[nt.space] = state.notionsData;
    } catch (err) {
      if (!panelStale(seq)) $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`;
      return;
    }
    if (panelStale(seq)) return;
  }
  const data = state.notionsData;
  const unnamed = data.total - data.named;
  const spaces = data.spaces || [data.space];
  const spaceChips = spaces.length > 1
    ? `<div class="chips" style="margin:0 0 6px" role="group" aria-label="Regard des notions">${spaces.map((sp) =>
        `<button class="chip ${sp === data.space ? "on" : ""}" data-nspace="${sp}">${esc(SPACE_SHORT[sp] || sp)}</button>`).join("")}</div>`
    : "";
  const via = data.named_via
    ? ` · noms donnés à travers le regard « ${esc(SPACE_SHORT[data.named_via] || data.named_via)} » (ce que montrent ses œuvres)`
    : "";
  $("fiche-body").innerHTML = `<div class="results-head">${spaceChips}
      <div class="sub">${data.total.toLocaleString("fr-FR")} notions vivantes · regard « ${esc(SPACE_SHORT[data.space] || data.space)} »
        · ${data.named.toLocaleString("fr-FR")} nommées (Iconclass z ≥ ${data.z_min})${via}</div>
      <input type="search" id="notions-q" class="flt-q" style="margin-top:8px" value="${esc(nt.query)}"
        placeholder="Filtrer par n°, nom Iconclass, style, genre, artiste…" aria-label="Filtrer les notions">
      <div class="chips" style="margin-bottom:6px">
        <button class="chip ${nt.filter === "all" ? "on" : ""}" data-nf="all">Toutes <small>${data.total}</small></button>
        <button class="chip ${nt.filter === "named" ? "on" : ""}" data-nf="named">Nommées <small>${data.named}</small></button>
        <button class="chip ${nt.filter === "unnamed" ? "on" : ""}" data-nf="unnamed">Sans nom <small>${unnamed}</small></button>
      </div>
      <div class="notion-sort">
        <label>Trier par <select id="notions-sort">
          <option value="feature" ${nt.sort === "feature" ? "selected" : ""}>Ordre général → fin (n°)</option>
          <option value="count" ${nt.sort === "count" ? "selected" : ""}>Nombre d'œuvres actives</option>
          <option value="z" ${nt.sort === "z" ? "selected" : ""}>Score Iconclass (z)</option>
        </select></label>
        <span class="sub" id="notions-shown"></span>
      </div>
    </div>
    <div id="notion-active" class="notion-active" hidden></div>
    <ol class="notions-list" id="notions-list"></ol>
    <div class="pager" id="notions-pager"></div>
    <p class="prov" style="margin:0 16px 20px">Chaque notion est une direction apprise par un auto-encodeur parcimonieux sur les
      vecteurs du regard (ARCHITECTURE §§ 37 et 42) : c'est ce que le modèle sépare, pas une catégorie d'histoire de l'art. L'étiquette
      Iconclass n'est affichée qu'à partir de z ≥ ${data.z_min} et reste à vérifier à l'œil.</p>`;
  const body = $("fiche-body");
  body.querySelectorAll("[data-nspace]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.nspace === nt.space) return;
    nt.space = b.dataset.nspace;   // les numéros de notion sont propres à chaque regard
    nt.shown = NOTIONS_PAGE;
    if (nt.active != null) setHighlight(null, "");   // la notion surlignée appartient à l'autre regard
    clearNotionSelection();
    state.notionsData = null;
    renderNotions();
  }));
  $("notions-q").addEventListener("input", (e) => {
    nt.query = e.target.value;
    nt.shown = NOTIONS_PAGE;
    clearTimeout(nt.qTimer);
    nt.qTimer = setTimeout(drawNotionsList, 120);
  });
  body.querySelectorAll("[data-nf]").forEach((b) => b.addEventListener("click", () => {
    nt.filter = b.dataset.nf;
    nt.shown = NOTIONS_PAGE;
    body.querySelectorAll("[data-nf]").forEach((x) => x.classList.toggle("on", x === b));
    drawNotionsList();
  }));
  $("notions-sort").addEventListener("change", (e) => {
    nt.sort = e.target.value;
    nt.shown = NOTIONS_PAGE;
    drawNotionsList();
  });
  drawNotionsList();
  if (nt.detail && nt.active === nt.detail.feature) drawNotionActive(nt.detail);
  $("fiche").scrollTop = 0;
}

function drawNotionsList() {
  const list = $("notions-list");
  if (!list) return;
  const matches = filteredNotions();
  const slice = matches.slice(0, nt.shown);
  $("notions-shown").textContent = `${matches.length.toLocaleString("fr-FR")} affichée${matches.length > 1 ? "s" : ""}`;
  list.innerHTML = slice.map((it) => `<li><button class="notion-row ${it.feature === nt.active ? "on" : ""}" data-feature="${it.feature}">
      <span class="notion-num">n° ${it.feature}</span>
      ${!it.named && it.meta
        ? `<span class="notion-lbl meta" title="Pas de nom Iconclass sûr : étiquette du catalogue partagée par les œuvres les plus marquées">${esc(metaText(it.meta))}</span>`
        : `<span class="notion-lbl ${it.named ? "" : "unnamed"}">${esc(it.label)}${it.iconclass ? ` <small>${esc(it.iconclass.notation)}</small>` : ""}</span>`}
      <span class="notion-n" title="${it.count.toLocaleString("fr-FR")} œuvres actives">${it.count.toLocaleString("fr-FR")}</span>
    </button></li>`).join("") || `<li class="empty-note">Aucune notion ne correspond.</li>`;
  list.querySelectorAll("[data-feature]").forEach((b) => b.addEventListener("click", () => selectNotion(Number(b.dataset.feature))));
  const pager = $("notions-pager");
  if (matches.length > slice.length) {
    pager.innerHTML = `<button class="chip" id="notions-more">Afficher plus (${slice.length} / ${matches.length})</button>`;
    $("notions-more").addEventListener("click", () => { nt.shown += NOTIONS_PAGE; drawNotionsList(); });
  } else {
    pager.innerHTML = "";
  }
}

async function selectNotion(feature) {
  const seq = ++state.notionsSeq;
  nt.active = feature;
  document.querySelectorAll(".notion-row").forEach((b) => b.classList.toggle("on", Number(b.dataset.feature) === feature));
  const box = $("notion-active");
  if (box) {
    box.hidden = false;
    box.innerHTML = `<div class="sub">Chargement des œuvres actives pour la notion n° ${feature}…</div>`;
    box.scrollIntoView({ block: "nearest" });
  }
  let d;
  try {
    d = await getJSON(`/api/notions/${feature}?space=${nt.space}&limit=24&highlight_limit=${NOTION_HIGHLIGHT_MAX}`);
  } catch (err) {
    if (seq === state.notionsSeq && box) box.innerHTML = `<div class="sub">Indisponible : ${esc(err.message)}</div>`;
    return;
  }
  if (seq !== state.notionsSeq) return;
  nt.detail = d;
  // Met à jour le compte exact dans la liste si l'index vient d'être calculé.
  if (state.notionsData) {
    const row = state.notionsData.items.find((x) => x.feature === feature);
    if (row) row.count = d.total;
  }
  document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
  const set = new Set(d.highlight_ids.map((id) => state.rowOf.get(id)).filter((r) => r !== undefined));
  setHighlight(set, notionTitle(d));
  drawNotionActive(d);
}

function drawNotionActive(d) {
  const box = $("notion-active");
  if (!box) return;
  box.hidden = false;
  const dom = Object.entries(d.labels || {}).map(([k, v]) => {
    const val = SLUG_KEYS.has(k) ? pretty(v.value) : v.value;
    return `${LABELS[k] || (k === "century" ? "Siècle" : pretty(k))} : ${val} (${Math.round(v.share * 100)} %)`;
  }).join(" · ");
  const ic = d.iconclass
    ? `<a class="iconclass sure" href="${esc(d.iconclass.url)}" target="_blank" rel="noopener"
         title="Iconclass ${esc(d.iconclass.notation)} · z = ${d.iconclass.z.toFixed(2)}, proposition du modèle à vérifier${d.iconclass.via ? ` (donnée à travers le regard « ${esc(SPACE_SHORT[d.iconclass.via] || d.iconclass.via)} » : ce que montrent ces œuvres, pas ce que ce regard y voit)` : ""}">
         <span>${esc(d.iconclass.notation)}</span> ${esc(d.iconclass.fr)} · z = ${d.iconclass.z.toFixed(1)}</a>`
    : `<div class="sub" style="margin:2px 0 4px">sans nom (aucune étiquette Iconclass à z ≥ ${state.notionsData ? state.notionsData.z_min : 5})</div>`;
  const shownInfo = d.total > d.highlight_ids.length
    ? `<b>${d.total.toLocaleString("fr-FR")}</b> œuvres actives · ${d.highlight_ids.length.toLocaleString("fr-FR")} plus actives surlignées`
    : `<b>${d.total.toLocaleString("fr-FR")}</b> œuvre${d.total > 1 ? "s" : ""} active${d.total > 1 ? "s" : ""}`;
  const preview = d.items.map((it) => `<button class="result" data-id="${it.id}" title="${esc(prettyLabel(it.label))}">
      <img src="/api/thumb/256/${it.id}" alt="" loading="lazy">
      ${it.score != null ? `<div class="score">activation ${it.score.toFixed(2)}</div>` : ""}
      <div class="lbl">${esc(prettyLabel(it.label))}</div></button>`).join("");
  box.innerHTML = `<div class="notion-active-head">
      <div><strong>Notion n° ${d.feature}</strong>${d.named ? ` — ${esc(d.label)}` : d.meta ? ` — <span class="notion-lbl meta">${esc(metaText(d.meta))}</span>` : ""}${d.editorial_label ? ` · <em>${esc(d.editorial_label)}</em>` : ""}</div>
      ${ic}
      <div class="sub" style="margin:4px 0 0">${shownInfo}</div>
      ${dom ? `<div class="sub" style="margin:2px 0 0">${esc(dom)}</div>` : ""}
      <div class="chips" style="margin:8px 0 4px">
        <button class="chip" id="nt-fit" title="Cadrer la carte sur les œuvres surlignées">Cadrer</button>
        <button class="chip" id="nt-note" title="Garder les œuvres les plus actives dans le carnet">Ajouter au carnet</button>
        <button class="chip" id="nt-export" title="Research Pack des ${PACK_MAX} œuvres les plus actives">Exporter</button>
        <button class="chip" id="nt-clear">Effacer</button>
      </div>
    </div>
    <div class="results-grid flt-preview">${preview || `<p class="sub">Aucune œuvre.</p>`}</div>`;
  $("nt-fit").addEventListener("click", () => {
    if (!state.highlight) return;
    const [x, y] = centerOf(state.highlight);
    flyTo(x, y, state.viewState.zoom);
  });
  $("nt-note").addEventListener("click", () => {
    const ids = d.highlight_ids.slice(0, NOTEBOOK_MAX);
    if (!ids.length) { toast("Aucune œuvre active"); return; }
    addToNotebook({
      kind: "selection", title: notionTitle(d), artwork_ids: ids,
      context: { "méthode": `notion apprise n° ${d.feature} (${SPACE_SHORT[d.space] || d.space})`,
                 "œuvres actives": d.total, "retenues": ids.length },
    });
  });
  $("nt-export").addEventListener("click", (e) => {
    const ids = d.highlight_ids.slice(0, PACK_MAX);
    if (!ids.length) { toast("Aucune œuvre active"); return; }
    exportPack({
      ids, title: notionTitle(d),
      selection: { "méthode": `notion apprise n° ${d.feature} (${ids.length} œuvres les plus actives sur ${d.total})`,
                   "regard": SPACE_SHORT[d.space] || d.space },
    }, e.currentTarget);
  });
  $("nt-clear").addEventListener("click", () => { clearHighlight(); });
  box.querySelectorAll("[data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
}

// ------------------------------------------------------------------ à vérifier : cadres (notion n° 88)
async function renderFramed(offset = 0) {
  const FRAMED_FEATURE = framedFeature();
  if (FRAMED_FEATURE == null) return;
  const seq = panelTurn();
  showPanel("framed", "À vérifier");
  state.lastList = () => renderFramed(offset);
  $("fiche-body").innerHTML = `<div class="loading">Chargement des œuvres avec cadre (notion n° ${FRAMED_FEATURE})…</div>`;
  let res;
  try {
    res = await getJSON(`/api/notions/${FRAMED_FEATURE}?offset=${offset}&limit=40&highlight_limit=40`);
  } catch (err) {
    if (!panelStale(seq)) $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`;
    return;
  }
  if (panelStale(seq)) return;
  const rows = res.items.map((d) => `<li class="suspect">
      <button class="s-main" data-id="${d.id}" title="${esc(prettyLabel(d.label))}"><img src="/api/thumb/256/${d.id}" alt="" loading="lazy"></button>
      <div class="s-text"><div><b>n° ${d.id}</b> · ${esc(prettyLabel(d.label))}</div>
        <div class="s-sugg">Groupe ${d.cluster}${d.score != null ? ` · activation ${d.score.toFixed(2)}` : ""}</div>
        <div class="pair-actions" style="margin-top:6px"><button class="chip" data-id="${d.id}">Voir la fiche</button></div></div></li>`).join("");
  const more = offset + res.items.length < res.total;
  const body = $("fiche-body");
  body.innerHTML = `<div class="results-head">${reviewTabs("framed")}
      <div class="sub" style="margin-top:10px">${res.total.toLocaleString("fr-FR")} œuvres · notion n° ${FRAMED_FEATURE} « ${esc(res.editorial_label || "tableau photographié avec son cadre")} » · triées par activation décroissante</div></div>
    ${rows ? `<ol class="suspects">${rows}</ol>` : `<p class="empty-note">Aucune œuvre ici.</p>`}
    <div class="pager">${offset > 0 ? `<button class="chip" id="fr-prev">← Précédentes</button>` : ""}
      ${more ? `<button class="chip" id="fr-next">Suivantes →</button>` : ""}
      ${res.items.length ? `<button class="chip" id="fr-note">Ajouter cette page au carnet</button>` : ""}</div>
    <p class="prov" style="margin:0 16px 20px">Repéré par la notion n° ${FRAMED_FEATURE} de l'auto-encodeur sur le regard « ${esc(SPACE_SHORT[res.space] || res.space)} »
      (ARCHITECTURE § 37) : un cadre photographié autour du tableau est un fait de reproduction, pas de l'œuvre. Liste à
      vérifier à l'œil : certaines images peuvent être sans cadre ou encadrées par l'artiste.</p>`;
  wireReviewTabs(body);
  body.querySelectorAll(".suspects [data-id]").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
  if ($("fr-prev")) $("fr-prev").addEventListener("click", () => renderFramed(Math.max(0, offset - 40)));
  if ($("fr-next")) $("fr-next").addEventListener("click", () => renderFramed(offset + 40));
  if ($("fr-note")) $("fr-note").addEventListener("click", () => addToNotebook({
    kind: "selection", title: `Cadres à vérifier (notion n° ${FRAMED_FEATURE}, page ${Math.floor(offset / 40) + 1})`,
    artwork_ids: res.items.map((d) => d.id),
    context: { "méthode": `notion apprise n° ${FRAMED_FEATURE} (cadre photographié)`, "total": res.total },
  }));
  const set = new Set(res.items.map((d) => state.rowOf.get(d.id)).filter((r) => r !== undefined));
  state.selected = state.selectedData = null;
  setHighlight(set, `À vérifier (cadres, n° ${FRAMED_FEATURE})`);
}
