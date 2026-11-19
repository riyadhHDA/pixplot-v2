/* PixPlot v2 — Atlas : à vérifier : étiquettes, bilan du corpus, relecture rapide, paires, désaccords.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

// ------------------------------------------------------------------ étiquettes à vérifier
const prettyLabel = (l) => String(l).split(" · ").map((x) => pretty(x)).join(" · ");

// ------------------------------------------------------------------ bilan du corpus et fiches des regards
// D'après A. Wasielewski (Computational Formalism) et T. Arnold & L. Tilton (Distant Viewing) :
// dire ce que voit chaque regard, d'où viennent les étiquettes, et ce qui manque au corpus.
function regardCard(sp) {
  const c = sp.card || {};
  return `<section class="card-regard">
    <h3>${esc(SPACE_SHORT[sp.key] || sp.label)} <small>${esc(c.model || sp.encoder)}</small></h3>
    <dl>
      <dt>Entraîné sur</dt><dd>${esc(c.trained_on || "—")}</dd>
      <dt>Voit</dt><dd>${esc(c.sees || "—")}</dd>
      <dt>Ne voit pas</dt><dd>${esc(c.blind_to || "—")}</dd>
      ${(c.biases || []).length ? `<dt>Biais connus</dt><dd><ul>${c.biases.map((b) => `<li>${esc(b)}</li>`).join("")}</ul></dd>` : ""}
      <dt>Mesuré</dt><dd>${esc(c.measured || "—")}</dd>
    </dl></section>`;
}

async function renderCorpus() {
  showPanel("corpus", "Le corpus et les regards");
  state.lastList = () => renderCorpus();
  $("fiche-body").innerHTML = `<div class="loading">Chargement…</div>`;
  let res;
  try { res = await getJSON("/api/corpus"); } catch (err) {
    $("fiche-body").innerHTML = `<div class="loading">${esc(err.message)}</div>`; return;
  }
  const r = res.report;
  const rows = Object.entries(r.coverage).map(([k, c]) => {
    const src = c.sources[0] || {};
    return `<tr><th>${esc(LABELS[k] || pretty(k))}</th><td>${Math.round(c.share * 100)} %</td><td>${c.distinct}</td></tr>
      <tr class="src"><td colspan="3">source : ${esc(src.source || "—")}${src.note ? `<small>${esc(src.note)}</small>` : ""}</td></tr>`;
  }).join("");
  const principles = (res.principles || []).map((p) =>
    `<li><b>${esc(p.title)}.</b> ${esc(p.text)} <small>(${esc(p.source)})</small></li>`).join("");
  $("fiche-body").innerHTML = `<div class="corpus-panel">
    <p class="sub">${r.n.toLocaleString("fr-FR")} œuvres. Ce bilan dit de quoi le corpus est fait — et donc ce qu'aucun
      résultat ne peut dire au-delà.</p>
    <h3>Ce qui manque, ce qui déséquilibre</h3>
    <ul class="corpus-notes">${r.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
    <h3>Étiquettes : couverture et source</h3>
    <table class="corpus-table"><thead><tr><th></th><th>connues</th><th>valeurs différentes</th></tr></thead>
      <tbody>${rows}</tbody></table>
    ${principles ? `<h3>Principes de lecture</h3><ul class="corpus-principles">${principles}</ul>` : ""}
    <h3>Les regards</h3>
    <p class="sub">Chaque regard est une manière de voir, construite par un modèle et ses données. Ils regardent des traits
      que l'historien ne regarde pas (grain, contours, qualité de la reproduction) : une proximité est une piste.</p>
    ${res.spaces.map(regardCard).join("")}
    <p class="prov">Sources : A. Wasielewski, <i>Computational Formalism</i> (MIT Press, 2023) ; T. Arnold et L. Tilton,
      <i>Distant Viewing</i> (MIT Press, 2023) ; L. Impett et F. Offert, <i>Visual Resources</i> (2024) ; D. G. Stork,
      <i>Pixels &amp; Paintings</i> (Wiley, 2024) ; J.-L. Giavitto et P. Saint-Germier (dir.), <i>L'art au temps de l'IA</i>
      (Centre Pompidou, 2025). Résultats détaillés : ARCHITECTURE § 11 à 26.</p></div>`;
}

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
  if (e.ctrlKey || e.metaKey || e.altKey) return;       // Ctrl+R = recharger, pas « rejeter »
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
  const opt = (sel) => spaces.map((s) => `<option value="${esc(s)}" ${s === sel ? "selected" : ""}>${esc(SPACE_SHORT[s] || s)}</option>`).join("");
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
  const tabs = res.keys.map((k) => `<button class="space ${k === res.key ? "on" : ""}" data-key="${esc(k)}">${esc(LABELS[k] || pretty(k))}
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
