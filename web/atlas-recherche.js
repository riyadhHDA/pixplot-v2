/* PixPlot v2 — Atlas : recherche par détail et par zone décrite, résultats, Research Pack.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

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

async function runZoneSearch(q) {
  showPanel("results", "Zones décrites");
  $("fiche-body").innerHTML = `<div class="loading">Recherche des zones « ${esc(q)} »…<br><small>La toute première recherche charge SigLIP 2 (jusqu'à une minute).</small></div>`;
  try {
    const res = await getJSON(`/api/search/zones?q=${encodeURIComponent(q)}&k=60`);
    renderResults({ kind: "zone", title: `« ${q} »`, sub: `${res.results.length} œuvres dont une zone répond à la description`, results: res.results });
  } catch (err) {
    $("fiche-body").innerHTML = `<div class="loading">Échec : ${esc(err.message)}</div>`;
  }
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
      ${r.kind === "region" || r.kind === "zone" ? `<canvas width="300" height="130" data-n="${n}"></canvas>` : `<img src="/api/thumb/256/${x.id}" alt="" loading="lazy">`}
      <div class="score">${x.score.toFixed(3)} · groupe ${x.cluster}</div>
      <div class="lbl">${esc(pretty(x.label))}</div></button>`).join("");
  $("fiche-body").innerHTML = `<div class="results-head"><h3>${esc(r.title)}</h3><div class="sub">${esc(r.sub)}</div>
      ${r.query ? `<canvas id="query-crop" width="360" height="160"></canvas>` : ""}
      <div class="chips" style="margin-top:10px"><button class="chip" id="export-results" title="Dossier .zip : images, métadonnées, relations, résumé pour un LLM">Exporter en Research Pack</button>
        <button class="chip" id="note-results" title="Garder ces résultats dans le carnet, avec une note">Ajouter au carnet</button></div></div>
    <div class="results-grid">${cards}</div>
    <div class="prov" style="margin:0 16px 20px">${r.kind === "region"
      ? "Chaque vignette montre la zone de l'œuvre la plus proche du détail tracé (grilles 2×2 et 4×4)."
      : r.kind === "zone"
        ? "Chaque vignette montre la zone de l'œuvre (grilles 2×2 et 4×4) que SigLIP 2 rapproche le plus de la description. Une zone couvre un quart ou un seizième de l'œuvre : le détail est dedans, pas forcément au centre. À vérifier œuvre par œuvre."
        : "Classement par SigLIP 2 : ressemblance entre la description et l'image, à vérifier œuvre par œuvre."}</div>`;
  if (r.query) drawCrop($("query-crop"), r.query.id, r.query.box, 160);
  if (r.kind === "region" || r.kind === "zone") $("fiche-body").querySelectorAll(".result canvas").forEach((c) => {
    const x = r.results[Number(c.dataset.n)];
    drawCrop(c, x.id, x.box, 130);
  });
  $("fiche-body").querySelectorAll(".result").forEach((b) => b.addEventListener("click", () => select(Number(b.dataset.id), true)));
  showPanel("results", r.kind === "region" ? "Détails semblables" : r.kind === "zone" ? "Zones décrites" : "Recherche par description");
  state.lastList = () => renderResults(r);
  $("note-results").addEventListener("click", () => addToNotebook({
    kind: r.kind === "region" ? "detail" : "recherche", title: r.kind === "region" ? `Détail de l'œuvre n° ${r.query.id}` : r.title,
    artwork_ids: (r.query ? [r.query.id] : []).concat(r.results.map((x) => x.id)),
    context: r.kind === "region" ? { "œuvre": r.query.id, cadre: r.query.box.map((v) => +v.toFixed(3)).join(", ") } : { requête: r.title },
  }));
  $("export-results").addEventListener("click", (e) => {
    const ids = (r.query ? [r.query.id] : []).concat(r.results.map((x) => x.id));
    const details = {};
    if (r.kind === "region") details[r.query.id] = r.query.box;
    if (r.kind === "region" || r.kind === "zone") r.results.forEach((x) => { if (x.box) details[x.id] = x.box; });
    exportPack({
      ids, title: r.kind === "region" ? "Détails semblables" : r.title,
      selection: r.kind === "region"
        ? { "méthode": "recherche par détail dans l'Atlas", "œuvre de départ": String(r.query.id), "cadre": JSON.stringify(r.query.box.map((v) => +v.toFixed(3))) }
        : { "méthode": r.kind === "zone" ? "zone décrite par des mots (SigLIP 2 sur 20 zones par œuvre)" : "recherche en texte libre (SigLIP 2) dans l'Atlas", "requête": r.title },
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
