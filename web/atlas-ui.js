/* PixPlot v2 — Atlas : branchement de l'interface (boutons, raccourcis), puis démarrage.
 *
 * L'Atlas est découpé en scripts classiques chargés dans l'ordre par index.html (voir
 * web/README.md) ; ils partagent leurs constantes et fonctions (même portée globale). */
"use strict";

// ------------------------------------------------------------------ interface
function wireUI() {
  $("display").addEventListener("change", (e) => {
    state.display = e.target.value;
    computeHD();
    redraw();
  });
  $("colorby").addEventListener("change", async (e) => {
    const mode = e.target.value;
    const seq = ++state.colorSeq;                    // un autre choix pendant le chargement l'emporte
    if (mode.startsWith("leiden:")) {
      const sp = mode.split(":")[1];
      if (!state.comm[sp]) {
        let comm;
        try { comm = await getJSON(`/api/communities/${sp}`); } catch (err) {
          if (seq !== state.colorSeq) return;
          toast(`Groupes Leiden indisponibles : ${err.message}`); e.target.value = state.colorMode; return;
        }
        state.comm[sp] = comm;
        if (seq !== state.colorSeq) return;
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
      : e.target.value === "zone"
        ? "Décrivez un détail, puis Entrée : « une auréole », « un crâne », « une main qui bénit »…"
        : "Rechercher : artiste, style, n° d'œuvre…";
    $("search").focus();
  });
  $("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = $("search").value.trim();
    if ($("search-mode").value === "text" && q.length >= 2) runTextSearch(q);
    if ($("search-mode").value === "zone" && q.length >= 2) runZoneSearch(q);
  });
  $("search").addEventListener("input", (e) => {
    clearTimeout(t);
    const q = e.target.value.trim();
    $("search-clear").hidden = !q;
    if ($("search-mode").value !== "meta") return; // recherche lancée par Entrée seulement
    const seq = ++state.searchSeq;
    state.searchTimer = t = setTimeout(async () => {
      if (!q) { clearHighlight(); return; }
      let res;
      try { res = await getJSON(`/api/search?q=${encodeURIComponent(q)}`); } catch (err) { toast(`Recherche impossible : ${err.message}`); return; }
      if (seq !== state.searchSeq) return;          // effacée ou remplacée entre-temps
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
  if ($("concept-controls")) {
    $("concept-controls").addEventListener("submit", (e) => {
      e.preventDefault();
      $("layout").value = "concepts";
      setLayout("concepts");
    });
    $("concept-controls").querySelectorAll(".concept-preset").forEach((b) => b.addEventListener("click", () => {
      $("concept-x").value = b.dataset.x;
      $("concept-y").value = b.dataset.y;
      // un préréglage mesuré garde sa mise en garde tant que ses phrases ne sont pas modifiées
      state.conceptPreset = b.dataset.note ? { x: b.dataset.x, y: b.dataset.y, note: b.dataset.note } : null;
      $("layout").value = "concepts";
      setLayout("concepts");
    }));
  }
  $("place-type").addEventListener("change", (e) => { state.placeType = e.target.value; setLayout("geo"); });
  $("place-paths").addEventListener("change", () => redraw());
  $("place-year").addEventListener("input", (e) => {
    const v = Number(e.target.value), max = Number(e.target.max);
    state.placeUntil = v >= max ? null : v;
    $("place-year-label").textContent = state.placeUntil == null ? `toutes les dates (${e.target.min}–${max})` : `jusqu'en ${v}`;
    clearTimeout(state.placeTimer);
    state.placeTimer = setTimeout(() => setLayout("geo"), 120);
  });
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
  $("open-filters").addEventListener("click", renderFilters);
  $("open-notions").addEventListener("click", renderNotions);
  $("open-suspects").addEventListener("click", openReview);
  $("open-disagreements").addEventListener("click", () => renderDisagreements());
  $("open-corpus").addEventListener("click", renderCorpus);
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
    else if (k === "f") renderFilters();
    else if (k === "o" && !$("open-notions").hidden) renderNotions();
    else if (k === "v" && !$("open-suspects").hidden) openReview();
    else if (k === "d" && !$("open-disagreements").hidden) renderDisagreements();
    else if (k === "r") openReviewSession();
    else if (k === "i") renderCorpus();
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
