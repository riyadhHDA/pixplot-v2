/* PixPlot v2 — Atlas : infobulle, groupes, surbrillance, fiche d'une œuvre, comparateur, carnet.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

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
    const dom = Object.entries(g.dominant).filter(([, vs]) => vs && vs.length).slice(0, 3).map(([k, vs]) =>
      `${esc(LABELS[k] || k)} : ${esc(SLUG_KEYS.has(k) && /^[\w-]+$/.test(vs[0].value) ? pretty(vs[0].value) : vs[0].value)} (${Math.round(vs[0].share * 100)} %)`).join("<br>");
    const col = PALETTE[g.cluster % PALETTE.length].join(",");
    return `<li class="group" data-cluster="${g.cluster}">
      <img src="/api/thumb/256/${g.representative}" alt="" loading="lazy">
      <div><div class="title"><span class="swatch" style="background:rgb(${col})"></span>Groupe ${g.number}
        <span class="size">${g.size} œuvres</span></div>
        ${g.name ? `<div class="gname" title="Nom proposé par SigLIP 2 d'après un vocabulaire d'histoire de l'art — à vérifier">${esc(g.name)}</div>` : ""}
        ${(g.iconclass || []).map((t) => `<a class="iconclass ${t.confidence === "sûr" ? "sure" : ""}" href="${esc(t.url)}" target="_blank" rel="noopener"
          title="Iconclass ${esc(t.notation)} — ${esc(t.en)} · ${t.confidence === "sûr" ? "proposition solide" : "proposition possible"}, à vérifier"
          ><span>${esc(t.notation)}</span> ${esc(t.fr)}</a>`).join("")}
        <div class="dom">${dom}</div></div></li>`;
  }).join("");
  $("groups").querySelectorAll(".group a.iconclass").forEach((a) => a.addEventListener("click", (e) => e.stopPropagation()));
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
  clearTimeout(state.searchTimer); state.searchSeq++;   // annule une recherche instantanée en cours
  if (typeof filtersActive === "function" && filtersActive()) resetFilters();   // « Vue d'ensemble » efface aussi les filtres
  if (typeof clearNotionSelection === "function") clearNotionSelection();
  document.querySelectorAll(".group.active").forEach((x) => x.classList.remove("active"));
  $("search").value = "";
  $("search-clear").hidden = true;
  setHighlight(null, "");
}
function updateStats() {
  const i = state.info;
  const base = `${state.n.toLocaleString("fr-FR")} œuvres · ${i.clusters} groupes · ${i.encoder} @${i.input_size}`
    + (state.layout === "time" || state.layout === "geo" ? ` · ${state.layoutNote}` : "")
    + (state.layout === "concepts" ? ` · axes « ${state.conceptAxes.x} » / « ${state.conceptAxes.y} »` : "")
    + (state.layout.startsWith("map:") ? ` · carte « ${SPACE_SHORT[state.layout.slice(4)] || state.layout.slice(4)} »` : "");
  $("stats").textContent = state.highlight
    ? `${state.highlightLabel} : ${state.highlight.size.toLocaleString("fr-FR")} œuvres  —  ${base}`
    : base;
}

// ------------------------------------------------------------------ fiche
async function select(id, fly) {
  let data;
  const seq = panelTurn();
  const space = state.space && state.space !== state.mainSpace ? `?space=${state.space}` : "";
  try { data = await getJSON(`/api/artwork/${id}${space}`); } catch (err) {
    if (!panelStale(seq)) toast(`Œuvre n° ${id} indisponible : ${err.message}`);
    return;
  }
  if (panelStale(seq)) return;                       // un autre clic est passé entre-temps
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
  const main = state.spaces.filter((s) => !s.experimental);
  const exp = state.spaces.filter((s) => s.experimental);
  const btn = (s) => `<button class="space ${s.experimental ? "essai " : ""}${s.key === current ? "on" : ""}" data-space="${esc(s.key)}"
      title="${esc(s.about)}" role="tab" aria-selected="${s.key === current}">${esc(SPACE_SHORT[s.key] || s.label)}${s.experimental ? "<small>essai</small>" : ""}</button>`;
  const sep = main.length && exp.length ? `<span class="spaces-sep" aria-hidden="true"></span>` : "";
  return `<div class="spaces" role="tablist" aria-label="Voisines selon">${main.map(btn).join("")}${sep}${exp.map(btn).join("")}</div>`;
}

// Squelettes posture (COCO-17) : dessin SVG simple superposé à l'image réelle (sans bibliothèque).
const POSE_LIMBS = [[0, 5], [0, 6], [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
  [5, 11], [6, 12], [11, 12], [11, 13], [13, 15], [12, 14], [14, 16]];

function clearPoseOverlay(container) {
  if (!container) return;
  container.querySelectorAll(".pose-svg, .pose-badge").forEach((el) => el.remove());
}

function drawPoseOverlay(container, img, figures, activeFig, limbs, thr, badgeText) {
  if (!container || !img) return;
  const place = () => {
    clearPoseOverlay(container);
    if (!img.naturalWidth || !img.naturalHeight) return;
    const rect = imageRect(img);
    if (!rect.w || !rect.h) return;
    const segs = limbs && limbs.length ? limbs : POSE_LIMBS;
    const minC = thr ?? 0.30;
    const ns = "http://www.w3.org/2000/svg";
    const el = document.createElementNS(ns, "svg");
    el.setAttribute("class", "pose-svg");
    el.setAttribute("viewBox", `0 0 ${rect.w.toFixed(1)} ${rect.h.toFixed(1)}`);
    el.setAttribute("width", rect.w.toFixed(1));
    el.setAttribute("height", rect.h.toFixed(1));
    el.style.left = `${rect.left}px`;
    el.style.top = `${rect.top}px`;
    el.style.width = `${rect.w.toFixed(1)}px`;
    el.style.height = `${rect.h.toFixed(1)}px`;
    // Dessine d'abord les figures secondaires (discrètes), puis la figure active (dorée) par-dessus.
    const ordered = (figures || []).slice().sort((a, b) => (a.fig === activeFig ? 1 : 0) - (b.fig === activeFig ? 1 : 0));
    const lw = Math.max(2, Math.min(4, rect.w / 110));
    for (const f of ordered) {
      const isMain = activeFig == null || f.fig === activeFig;
      const kp = f.kpts || [];
      const g = document.createElementNS(ns, "g");
      g.setAttribute("opacity", isMain ? "0.95" : "0.28");
      for (const [p, q] of segs) {
        const a = kp[p], b = kp[q];
        if (!a || !b || a[2] < minC || b[2] < minC) continue;
        const x1 = a[0] * rect.w, y1 = a[1] * rect.h, x2 = b[0] * rect.w, y2 = b[1] * rect.h;
        if (isMain) {
          const halo = document.createElementNS(ns, "line");
          halo.setAttribute("x1", x1); halo.setAttribute("y1", y1);
          halo.setAttribute("x2", x2); halo.setAttribute("y2", y2);
          halo.setAttribute("stroke", "rgba(0,0,0,0.68)");
          halo.setAttribute("stroke-width", (lw + 2.5).toFixed(1));
          halo.setAttribute("stroke-linecap", "round");
          g.appendChild(halo);
        }
        const line = document.createElementNS(ns, "line");
        line.setAttribute("x1", x1); line.setAttribute("y1", y1);
        line.setAttribute("x2", x2); line.setAttribute("y2", y2);
        line.setAttribute("stroke", isMain ? "#e0b040" : "#cccccc");
        line.setAttribute("stroke-width", (isMain ? lw : Math.max(1.2, lw * 0.65)).toFixed(1));
        line.setAttribute("stroke-linecap", "round");
        g.appendChild(line);
      }
      if (isMain) {
        for (const pt of kp) {
          if (!pt || pt[2] < minC) continue;
          const dot = document.createElementNS(ns, "circle");
          dot.setAttribute("cx", pt[0] * rect.w); dot.setAttribute("cy", pt[1] * rect.h);
          dot.setAttribute("r", (lw * 0.95).toFixed(1));
          dot.setAttribute("fill", "#fff5dc");
          dot.setAttribute("stroke", "rgba(0,0,0,0.7)");
          dot.setAttribute("stroke-width", "1");
          g.appendChild(dot);
        }
      }
      el.appendChild(g);
    }
    container.appendChild(el);
    if (badgeText) {
      const bd = document.createElement("span");
      bd.className = "pose-badge";
      bd.textContent = badgeText;
      container.appendChild(bd);
    }
  };
  if (img.complete && img.naturalWidth) place(); else img.addEventListener("load", place, { once: true });
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
  const hasPosture = spaces.some((s) => s.key === "posture");
  const pMatches = res.posture_matches || {};
  const head = spaces.map((s) => `<th title="${esc([s.about, s.card && `Entraîné sur : ${s.card.trained_on}`, ...((s.card || {}).biases || []).map((b) => `Biais : ${b}`)].filter(Boolean).join(" · "))}">${esc(SPACE_SHORT[s.key] || s.label)}${s.experimental ? " <small>essai</small>" : ""}</th>`).join("");
  let ref = { types: [], pairs: [] };
  try { ref = await getJSON(`/api/pairs?ids=${res.ids.join(",")}`); } catch (_) { /* banc d'essai indisponible */ }
  const typeLabel = Object.fromEntries(ref.types.map((t) => [t.key, t.label]));
  const annotations = (a, b) => ref.pairs.filter((p) =>
    (p.a === res.ids[a] && p.b === res.ids[b]) || (p.a === res.ids[b] && p.b === res.ids[a]));
  const body = pairs.map(([a, b]) => {
    const tags = annotations(a, b).map((p) =>
      `<span class="pair-tag ${p.status === "validée" ? "ok" : ""}" title="${esc([p.status, p.source, p.note].filter(Boolean).join(" · "))}">${esc(typeLabel[p.type] || p.type)}</span>`).join("");
    const pm = pMatches[`${a},${b}`];
    return `<tr><td>${a + 1} ↔ ${b + 1}</td>${spaces.map((s) => {
      const v = res.similarity[s.key][a][b];
      if (v == null) return "<td>—</td>";
      const mir = s.key === "posture" && pm && pm.mirrored ? `<span class="mirror-tag" title="Meilleure correspondance en miroir gauche-droite">miroir</span>` : "";
      return `<td><span class="bar" style="--v:${Math.max(0, v)}"></span>${v.toFixed(3)}${mir}</td>`;
    }).join("")}<td class="pair-cell"><button class="chip" data-why="${a},${b}" title="Montrer les zones de ces deux œuvres qui se répondent le plus">Pourquoi ?</button>${hasPosture ? `<button class="chip" data-pose="${a},${b}" title="Dessiner les squelettes des figures qui se répondent (essai)">Squelettes</button>` : ""}${tags}${ref.types.length ? `<button class="chip" data-annotate="${a},${b}">Annoter</button>` : ""}</td></tr>`;
  }).join("");
  $("compare-body").innerHTML = `<div class="cmp-row" style="--n:${n}">${cols}</div>
    <div class="cmp-why" id="cmp-why" hidden></div>
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
  $("compare-body").querySelectorAll("[data-why]").forEach((btn) => btn.addEventListener("click", () => {
    const [a, b] = btn.dataset.why.split(",").map(Number);
    showWhy(res.ids[a], res.ids[b], a, b, btn);
  }));
  $("compare-body").querySelectorAll("[data-pose]").forEach((btn) => btn.addEventListener("click", () => {
    const [a, b] = btn.dataset.pose.split(",").map(Number);
    showPosturePair(res.ids[a], res.ids[b], a, b, btn);
  }));
  if (state.space === "posture" && hasPosture) {
    const firstPoseBtn = $("compare-body").querySelector('[data-pose="0,1"]');
    if (firstPoseBtn) showPosturePair(res.ids[0], res.ids[1], 0, 1, firstPoseBtn);
  }
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
      await sendJSON("/api/pairs", { a: current[0], b: current[1], type: f.get("type"), status: f.get("status"),
                                     source: f.get("source") || "", note: f.get("note") || "" });
      toast("Paire enregistrée pour le banc d'essai");
      openCompare();
    } catch (err) { toast(`Échec : ${err.message}`); }
  });
}

// « Pourquoi ces deux œuvres se ressemblent ? » : les zones qui se répondent (cases 4 × 4, regard
// forme), dessinées sur les deux images avec le même numéro et la même couleur.
const WHY_COLORS = ["#e0b040", "#56b4e9", "#cc79a7", "#00b079", "#f0e442", "#d55e00", "#0072b2", "#ffffff"];

let whySeq = 0;
function clearWhy() {
  whySeq++;
  document.querySelectorAll("#compare-body .why-box, #compare-body .pose-svg, #compare-body .pose-badge").forEach((el) => el.remove());
  document.querySelectorAll("#compare-body [data-why], #compare-body [data-pose]").forEach((el) => el.classList.remove("on"));
  const box = $("cmp-why"); if (box) { box.hidden = true; box.innerHTML = ""; }
}

async function showPosturePair(idA, idB, nA, nB, btn) {
  const wasOn = btn.classList.contains("on");
  clearWhy();
  if (wasOn) return;
  const seq = whySeq;
  let r;
  try { r = await getJSON(`/api/posture/match?a=${idA}&b=${idB}`); } catch (err) { toast(`Échec : ${err.message}`); return; }
  if (seq !== whySeq) return;
  btn.classList.add("on");
  const drawOn = (id, figs, activeFig, badge) => {
    const fig = document.querySelector(`#compare-body .cmp[data-id="${id}"] .cmp-img`);
    const img = fig && fig.querySelector("img");
    if (!img) return;
    drawPoseOverlay(fig, img, figs, activeFig, r.limbs, r.kpt_threshold, badge);
  };
  if (r.matched) {
    drawOn(idA, r.figures_a, r.fig_a, `figure ${r.fig_a + 1}`);
    drawOn(idB, r.figures_b, r.fig_b, `figure ${r.fig_b + 1}${r.mirrored ? " · en miroir" : ""}`);
  } else {
    if (r.figures_a.length) drawOn(idA, r.figures_a, null, `${r.figures_a.length} figure${r.figures_a.length > 1 ? "s" : ""}`);
    if (r.figures_b.length) drawOn(idB, r.figures_b, null, `${r.figures_b.length} figure${r.figures_b.length > 1 ? "s" : ""}`);
  }
  const box = $("cmp-why");
  box.hidden = false;
  box.innerHTML = r.matched
    ? `<h3>Postures qui se répondent (${nA + 1} ↔ ${nB + 1}) <small>regard « posture » (essai)</small></h3>
       <p style="margin:0 0 6px;font-size:13px">Ressemblance de pose : <b>${r.score.toFixed(3)}</b> · figure ${r.fig_a + 1} ↔ figure ${r.fig_b + 1}${r.mirrored ? ` <span class="mirror-tag">en miroir</span>` : ""}</p>
       <p class="prov">${esc(r.note)}</p>`
    : `<p class="prov">Aucune figure corporelle détectée dans au moins l'une de ces deux œuvres (regard « posture », en essai).</p>`;
}

async function showWhy(idA, idB, nA, nB, btn) {
  const wasOn = btn.classList.contains("on");
  clearWhy();
  if (wasOn) return;                                       // second clic : on efface
  const seq = whySeq;
  let r;
  try { r = await getJSON(`/api/correspond?a=${idA}&b=${idB}`); } catch (err) { toast(`Échec : ${err.message}`); return; }
  if (seq !== whySeq) return;                              // un autre clic est passé entre-temps
  btn.classList.add("on");
  const draw = (id, key) => {
    const fig = document.querySelector(`#compare-body .cmp[data-id="${id}"] .cmp-img`);
    const img = fig && fig.querySelector("img");
    if (!img) return;
    const place = () => {
      if (seq !== whySeq) return;
      fig.querySelectorAll(".why-box").forEach((el) => el.remove());
      const rect = imageRect(img);
      r.pairs.forEach((p, k) => {
        const [x0, y0, x1, y1] = p[key];
        const el = document.createElement("div");
        el.className = "why-box";
        el.style.cssText = `left:${rect.left + x0 * rect.w}px;top:${rect.top + y0 * rect.h}px;` +
          `width:${(x1 - x0) * rect.w}px;height:${(y1 - y0) * rect.h}px;--c:${WHY_COLORS[k % WHY_COLORS.length]}`;
        el.innerHTML = `<span>${k + 1}</span>`;
        fig.appendChild(el);
      });
    };
    if (img.complete && img.naturalWidth) place(); else img.addEventListener("load", place, { once: true });
  };
  draw(idA, "box_a"); draw(idB, "box_b");
  const box = $("cmp-why");
  box.hidden = false;
  box.innerHTML = r.pairs.length
    ? `<h3>Pourquoi ${nA + 1} et ${nB + 1} se ressemblent-elles ? <small>regard « ${esc(SPACE_SHORT[r.space] || r.space)} », cases ${esc(r.grid)}</small></h3>
       <ol>${r.pairs.map((p, k) => `<li style="--c:${WHY_COLORS[k % WHY_COLORS.length]}">zone ${k + 1} ↔ zone ${k + 1} :
         cosinus ${p.sim.toFixed(2)}, ${p.lift >= 0 ? "+" : ""}${p.lift.toFixed(2)} au-dessus de leur ressemblance moyenne</li>`).join("")}</ol>
       ${r.pairs.length < 4 ? `<p class="prov">Seule${r.pairs.length > 1 ? "s" : ""} ${r.pairs.length} zone${r.pairs.length > 1 ? "s se répondent" : " se répond"}
       nettement (sur 4 cherchées) : la ressemblance tient moins à des parties précises qu'à l'ensemble, ou à peu de
       choses. C'est fréquent entre œuvres éloignées (paires du banc d'essai : 4 en médiane, moins de 4 pour 31 % ;
       voisines proches : 7, moins de 4 pour 10 %).</p>` : ""}
       <p class="prov">Zones qui se ressemblent le plus (correspondances mutuelles centrées par position et pondérées
       par leur poids global) : une piste à regarder, pas une explication. Le regard compare des formes : à vous de
       dire si ces zones partagent un motif, une pose, une composition, ou seulement un fond semblable.</p>`
    : `<p class="prov">Aucune zone ne se répond nettement entre ces deux œuvres (selon le regard « ${esc(r.space)} »).</p>`;
}

// ------------------------------------------------------------------ carnet de recherche
async function addToNotebook(entry) {
  const note = prompt(`Note pour « ${entry.title} » (facultatif) :`, entry.note || "");
  if (note === null) return;
  try {
    await sendJSON("/api/notebook", { ...entry, note });
    toast("Ajouté au carnet");
    if (state.panel === "notebook") renderNotebook();
  } catch (err) { alert(`Ajout impossible : ${err.message}`); }
}

const KIND_LABEL = { note: "Note", oeuvre: "Œuvre", selection: "Sélection", recherche: "Recherche", detail: "Détail",
  comparaison: "Comparaison", groupe: "Groupe" };

async function renderNotebook() {
  const seq = panelTurn();
  showPanel("notebook", "Carnet de recherche");
  state.lastList = renderNotebook;
  state.selected = state.selectedData = null;
  redraw();
  $("fiche").hidden = false;
  let res;
  try { res = await getJSON("/api/notebook"); } catch (err) {
    if (!panelStale(seq)) $("fiche-body").innerHTML = `<div class="loading">Carnet indisponible : ${esc(err.message)}</div>`;
    return;
  }
  if (panelStale(seq)) return;
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
  // Une note non enregistrée doit se voir : le texte reste dans le champ, l'erreur s'affiche.
  const patch = (id, data, field) => sendJSON(`/api/notebook/${id}`, data, "PATCH")
    .then(() => { field.classList.remove("unsaved"); toast("Enregistré"); })
    .catch((err) => { field.classList.add("unsaved"); alert(`Note non enregistrée (${err.message}). Votre texte est encore dans le champ : copiez-le avant de recharger la page.`); });
  body.querySelectorAll(".entry").forEach((li) => {
    const id = Number(li.dataset.id);
    li.querySelector(".entry-title").addEventListener("change", (e) => patch(id, { title: e.target.value }, e.target));
    li.querySelector(".entry-note").addEventListener("change", (e) => patch(id, { note: e.target.value }, e.target));
    li.querySelectorAll(".entry-thumbs img").forEach((img) => img.addEventListener("click", () => select(Number(img.dataset.id), true)));
  });
  const entryOf = (id) => res.entries.find((e) => e.id === Number(id));
  body.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    if (!confirm("Supprimer cette entrée du carnet ?")) return;
    try { await sendJSON(`/api/notebook/${b.dataset.del}`, undefined, "DELETE"); }
    catch (err) { alert(`Suppression impossible : ${err.message}`); return; }
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


function renderMeasuresBody(m) {
  const r = Math.max(0.4, Math.min(2.4, m.aspect_ratio || 1));
  const w = r >= 1 ? 84 : Math.round(84 * r), h = r >= 1 ? Math.round(84 / r) : 84;
  const [lx, ly] = m.balance.lightness, [sx, sy] = m.balance.saturation;
  const sp = m.chromatic;
  const splitLine = sp.split_orientation === "horizontale"
    ? `<line x1="0" y1="${(sp.split_position * h).toFixed(1)}" x2="${w}" y2="${(sp.split_position * h).toFixed(1)}" stroke="#e0b040" stroke-width="1.2" stroke-dasharray="3 2"/>`
    : `<line x1="${(sp.split_position * w).toFixed(1)}" y1="0" x2="${(sp.split_position * w).toFixed(1)}" y2="${h}" stroke="#e0b040" stroke-width="1.2" stroke-dasharray="3 2"/>`;
  return `<div class="measures-grid">
      <svg class="measures-svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" style="width:${w}px;height:${h}px" role="img"
        aria-label="Schéma du barycentre de luminance, de saturation et de la première coupe compositionnelle">
        <rect x="0.5" y="0.5" width="${w - 1}" height="${h - 1}" fill="#121214" stroke="#3a3a42"/>
        <line x1="${(w / 2).toFixed(1)}" y1="0" x2="${(w / 2).toFixed(1)}" y2="${h}" stroke="#ffffff22"/>
        <line x1="0" y1="${(h / 2).toFixed(1)}" x2="${w}" y2="${(h / 2).toFixed(1)}" stroke="#ffffff22"/>
        ${splitLine}
        <circle cx="${(sx * w).toFixed(1)}" cy="${(sy * h).toFixed(1)}" r="3.2" fill="none" stroke="#e9e6df" stroke-width="1.2"/>
        <circle cx="${(lx * w).toFixed(1)}" cy="${(ly * h).toFixed(1)}" r="3.8" fill="#e0b040"/>
      </svg>
      <dl class="measures-dl">
        <dt>Barycentre (clarté)</dt><dd>${Math.round(lx * 100)} % → · ${Math.round(ly * 100)} % ↓ <small>(écart centre ${(m.balance.center_offset * 100).toFixed(1)} %, dispersion ${(m.balance.local_spread * 100).toFixed(1)} %)</small></dd>
        <dt>Symétrie gauche-droite</dt><dd>${m.symmetry_lr.toFixed(2)} <small>(−1 à +1)</small></dd>
        <dt>Entropie chromatique</dt><dd>${sp.entropy_bits.toFixed(2)} / ${sp.max_bits.toFixed(1)} bits · coupe ${esc(sp.split_orientation)} à ${Math.round(sp.split_position * 100)} % <small>(gain ${sp.split_gain_bits.toFixed(2)} bits)</small></dd>
        ${m.order ? `<dt>Ordre de la matière</dt><dd>désordre ${m.order.permutation_entropy.toFixed(2)} <small>(0 aplat → 1 bruit)</small> · complexité ${m.order.complexity.toFixed(2)} <small>(Sigaki et al., 2018)</small></dd>` : ""}
        <dt>Clarté et part sombre</dt><dd>moy. ${Math.round(m.tone.mean_lightness * 100)} % · contraste ${Math.round(m.tone.contrast_p5_p95 * 100)} % · tons sombres ${Math.round(m.tone.dark_share * 100)} %</dd>
      </dl>
    </div>
    <p class="prov">${esc(m.note)}</p>`;
}

let fichePoseSeq = 0;

function renderFiche(d) {
  const isPosture = d.space === "posture";
  const noFigures = isPosture && (d.posture_figures === 0 || (!d.neighbors.length && d.posture_figures == null));
  const meta = Object.entries(d.metadata).filter(([, v]) => v).map(([k, v]) =>
    `<tr><th>${esc(LABELS[k] || pretty(k))}</th><td>${esc(SLUG_KEYS.has(k) ? pretty(v) : v)}${d.metadata_sources[k] ? `<small title="${esc((d.metadata_source_notes || {})[k] || "")}">source : ${esc(d.metadata_sources[k])}${(d.metadata_source_notes || {})[k] ? " · étiquette bénévole, à vérifier" : ""}</small>` : ""}</td></tr>`).join("");
  const fam = d.hdbscan == null ? "" : d.hdbscan < 0
    ? `<span class="chip warn" title="HDBSCAN ne la rattache à aucune famille">Œuvre « à part »</span>`
    : `<span class="chip">Famille ${d.hdbscan + 1}</span>`;
  const atyp = Math.round(d.atypicality * 100);
  const neigh = noFigures
    ? `<div class="empty-posture"><b>Aucune figure détectée</b> dans cette œuvre. Le regard « posture » (spécialisé, en essai) ne s'applique qu'aux œuvres figuratives (~48 % du corpus).</div>`
    : d.neighbors.map((n) => {
      const mir = n.mirrored ? `<span class="mirror-tag" title="Meilleure correspondance en miroir gauche-droite">miroir</span>` : "";
      const figAttrs = isPosture && n.fig_a != null
        ? ` data-fig-a="${n.fig_a}" data-fig-b="${n.fig_b ?? 0}" data-mirrored="${n.mirrored ? 1 : 0}"` : "";
      return `<button class="neighbor" data-id="${n.id}"${figAttrs} title="${esc(n.label)}${n.mirrored ? " (en miroir)" : ""}">
      <img src="/api/thumb/256/${n.id}" alt="" loading="lazy">
      <div class="score">${n.score.toFixed(3)} · groupe ${n.cluster ?? "?"}${mir}</div>
      <div class="lbl">${esc(pretty(n.label))}</div></button>`;
    }).join("");
  const provNote = isPosture
    ? "Regard spécialisé (en essai) : une pose semblable est une piste, pas la preuve qu'un artiste a vu l'autre."
    : "Une proximité est une piste à examiner, pas une preuve de filiation.";
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
      <details class="measures-box" id="fiche-measures">
        <summary>Mesures visuelles <small>équilibre, symétrie, entropie · Stork</small></summary>
        <div id="fiche-measures-body" class="measures-body"><span class="sub">Cliquez pour calculer…</span></div>
      </details>
      <h4>Œuvres les plus proches</h4>
      ${spaceTabs(d.space)}
      <div class="neighbors">${neigh}</div>
      <div class="prov">${esc(spaceAbout(d.space))} Vecteurs de l'analyse : ${esc(d.provenance.features)} · ${esc(d.provenance.analysis)}.
        ${provNote}</div>
    </div>`;
  const pSeq = ++fichePoseSeq;
  if (isPosture && !noFigures) {
    const hero = $("fiche-body").querySelector(".hero");
    const heroImg = hero && hero.querySelector("img");
    getJSON(`/api/posture/${d.id}`).then((pose) => {
      if (pSeq !== fichePoseSeq || state.selected !== d.id || state.drawing) return;
      if (!pose.figures || !pose.figures.length) return;
      const defFig = d.neighbors.length && d.neighbors[0].fig_a != null ? d.neighbors[0].fig_a : pose.figures[0].fig;
      const defBadge = `${pose.count} figure${pose.count > 1 ? "s" : ""} · essai`;
      drawPoseOverlay(hero, heroImg, pose.figures, defFig, pose.limbs, pose.kpt_threshold, defBadge);
      $("fiche-body").querySelectorAll(".neighbor[data-fig-a]").forEach((btn) => {
        btn.addEventListener("mouseenter", () => {
          if (pSeq !== fichePoseSeq || state.drawing) return;
          const fa = Number(btn.dataset.figA);
          const mir = btn.dataset.mirrored === "1";
          drawPoseOverlay(hero, heroImg, pose.figures, fa, pose.limbs, pose.kpt_threshold,
            `figure ${fa + 1}${mir ? " · en miroir" : ""}`);
        });
        btn.addEventListener("mouseleave", () => {
          if (pSeq !== fichePoseSeq || state.drawing) return;
          drawPoseOverlay(hero, heroImg, pose.figures, defFig, pose.limbs, pose.kpt_threshold, defBadge);
        });
      });
    }).catch(() => { /* squelette indisponible */ });
  }
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
  if ($("chip-detail")) $("chip-detail").addEventListener("click", () => {
    clearPoseOverlay($("fiche-body").querySelector(".hero"));
    toggleDrawing(d);
  });
  const mbox = $("fiche-measures");
  if (mbox) mbox.addEventListener("toggle", async () => {
    if (!mbox.open || mbox.dataset.loaded) return;
    const seq = ++state.measuresSeq;
    const body = $("fiche-measures-body");
    body.innerHTML = `<span class="sub">Calcul…</span>`;
    try {
      const m = await getJSON(`/api/artwork/${d.id}/measures`);
      if (seq !== state.measuresSeq || state.selected !== d.id) return;
      mbox.dataset.loaded = "1";
      body.innerHTML = renderMeasuresBody(m);
    } catch (err) {
      if (seq !== state.measuresSeq) return;
      body.innerHTML = `<span class="sub">Indisponible : ${esc(err.message)}</span>`;
    }
  });
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
