"""Couche critique : dire ce que voit chaque regard, d'où viennent les étiquettes, et de quoi
est fait le corpus.

Deux livres en sont à l'origine.

- A. Wasielewski, *Computational Formalism* (MIT Press, 2023) : les modèles regardent des
  traits très fins (grain, contours, textures) que l'historien ne regarde pas — un « biais
  perceptif » ; les étiquettes de style de WikiArt sont remplies par des bénévoles et reprises
  sans examen ; le canon occidental, seul vraiment numérisé avec des métadonnées complètes,
  domine les corpus.
- T. Arnold et L. Tilton, *Distant Viewing* (MIT Press, 2023) : chaque algorithme encode une
  « manière de voir » qu'il faut rendre explicite ; annoter, c'est perdre et interpréter ; ne
  pas « fétichiser la taille ».

D'où trois outils : une **fiche par regard** (ce qu'il voit, sur quoi il a été entraîné, ses
biais, ce que le banc d'essai a mesuré), des **notes sur les sources d'étiquettes**, et un
**bilan du corpus** qui rend visibles ses trous et ses déséquilibres.
"""

from __future__ import annotations

from collections import Counter

# ------------------------------------------------------------------ fiches des regards
CARDS: dict[str, dict] = {
    "forme": {
        "model": "DINOv3 ViT-B/16 (Meta, 2025), sortie globale",
        "trained_on": "LVD-1689M : environ 1,7 milliard d'images du web, sans légendes "
                      "(apprentissage auto-supervisé)",
        "sees": "formes, contours, composition, motifs",
        "blind_to": "le sens des choses représentées, leur nom, le contexte de l'œuvre",
        "biases": [
            "entraîné sur des photographies du web, pas sur des œuvres : il voit une peinture comme une photo",
            "biais perceptif : sensible au cadrage, à la qualité et au format de la reproduction",
        ],
        "measured": "retrouve copies et reprises de composition au premier rang (paires de Honour et "
                    "Fleming) ; mais sur les autres paires « même composition », le sujet fait mieux "
                    "(ARCHITECTURE § 14, 18)",
    },
    "sujet": {
        "model": "SigLIP 2 So400m/16 (Google, 2025)",
        "trained_on": "WebLI : des milliards de paires image-légende du web, en plusieurs langues",
        "sees": "ce que l'on décrirait avec des mots : sujet, genre, école, manière",
        "blind_to": "ce qui n'a pas de nom dans les légendes du web",
        "biases": [
            "a appris des légendes qui nomment styles et artistes : il peut reconnaître une étiquette "
            "plutôt que voir une facture",
            "a peut-être vu WikiArt pendant son entraînement : ses scores sur WikiArt sont sans doute optimistes",
            "légendes du web majoritairement en anglais et centrées sur l'art occidental",
        ],
        "measured": "le meilleur sur les étiquettes et les filiations ; bat la forme sur « même composition » "
                    "(ARCHITECTURE § 11, 18)",
    },
    "couleur": {
        "model": "histogramme CIELAB (5 × 7 × 7), sans apprentissage",
        "trained_on": "rien : une mesure directe de la palette",
        "sees": "les proportions des teintes, des clartés et des saturations",
        "blind_to": "la disposition des couleurs, les formes, le sujet",
        "biases": [
            "mesure la couleur de la reproduction, pas de l'œuvre : balance des blancs, vernis jauni, "
            "scan ou photographie changent tout",
        ],
        "measured": "seul regard qui retrouve « même palette » ; sous le hasard pour « même sujet » "
                    "(ARCHITECTURE § 18)",
    },
    "touche": {
        "model": "DINOv3 ViT-B/16, couche 6 : moyenne et écart-type des zones",
        "trained_on": "comme « forme » (LVD-1689M), mais lu à mi-profondeur du réseau",
        "sees": "la texture de la surface : facture, trait, grain",
        "blind_to": "la composition d'ensemble et le sujet",
        "biases": [
            "très sensible à la résolution et à la compression de la reproduction",
            "les styles larges (impressionnisme) n'ont pas une facture unique",
        ],
        "measured": "pointillisme 21 % → 62 % de voisines du même style ; meilleur sur « même facture » "
                    "(ARCHITECTURE § 11, 14, 18)",
    },
    "couleur_rvb": {
        "model": "histogramme RVB (encodeur de test)",
        "trained_on": "rien",
        "sees": "une palette approximative",
        "blind_to": "presque tout le reste",
        "biases": ["encodeur de démonstration, sans valeur d'analyse"],
        "measured": "—",
    },
    "forme_v2": {
        "model": "DINOv2 ViT-B/14 (Meta, 2023)",
        "trained_on": "LVD-142M : 142 millions d'images du web",
        "sees": "formes et composition",
        "blind_to": "le sens",
        "biases": ["ancien modèle, gardé pour comparaison"],
        "measured": "remplacé par DINOv3 (ARCHITECTURE § 9)",
    },
}


def card(space: str) -> dict:
    return CARDS.get(space, {"model": space, "trained_on": "inconnu", "sees": "", "blind_to": "",
                             "biases": [], "measured": ""})


# ------------------------------------------------------------------ sources d'étiquettes
SOURCE_NOTES = [
    ("huggan/wikiart", "Étiquettes de WikiArt, encyclopédie en ligne remplie par des contributeurs bénévoles "
                       "(principe du wiki), reprises par le jeu huggan/wikiart : des propositions, pas une vérité."),
    ("wikiart", "Étiquettes de WikiArt, encyclopédie remplie par des contributeurs bénévoles : à vérifier."),
    ("iiif", "Notice du musée, transmise par son manifeste IIIF : la source la plus sûre, mais au vocabulaire de ce musée."),
    ("yale", "Notice du Yale Center for British Art (IIIF)."),
]


def source_note(source: str | None) -> str:
    s = (source or "").lower()
    for key, note in SOURCE_NOTES:
        if key in s:
            return note
    return ""


# ------------------------------------------------------------------ bilan du corpus
KEY_LABELS = {"artist": "artiste", "style": "style", "genre": "genre", "date": "date", "title": "titre"}
NON_WESTERN_HINTS = ("ukiyo", "japan", "chinese", "china", "islamic", "persian", "mughal", "indian",
                     "african", "aboriginal", "ottoman", "byzantine", "pre-columbian", "korean", "edo")


def _known(v) -> bool:
    return bool(v) and not str(v).lower().startswith(("unknown", "inconnu"))


def corpus_report(meta: dict[int, dict[str, str]], sources: dict[str, Counter], years: list | None = None,
                  places: int | None = None) -> dict:
    """``meta`` : œuvre → étiquettes ; ``sources`` : étiquette → Counter(source) ;
    ``years`` : une année (ou None) par œuvre ; ``places`` : nombre d'œuvres situées."""
    n = len(meta)
    keys = sorted({k for m in meta.values() for k in m if k not in ("source",)})
    coverage = {}
    for k in keys:
        vals = [m.get(k) for m in meta.values()]
        known = [v for v in vals if _known(v)]
        top = Counter(known).most_common(10)
        coverage[k] = {
            "known": len(known), "share": round(len(known) / n, 4) if n else 0, "distinct": len(set(known)),
            "top": [{"value": v, "count": c, "share": round(c / max(len(known), 1), 4)} for v, c in top],
            "top10_share": round(sum(c for _, c in top) / max(len(known), 1), 4),
            "sources": [{"source": s, "count": c, "note": source_note(s)} for s, c in sources.get(k, Counter()).most_common(3)],
        }
    notes = []
    for k, c in coverage.items():
        if c["share"] < 0.7:
            notes.append(f"L'étiquette « {KEY_LABELS.get(k, k)} » manque pour {100 - round(c['share'] * 100)} % des œuvres.")
    a = coverage.get("artist")
    if a and any("huggan" in x["source"] for x in a["sources"]):
        notes.append("Le jeu huggan/wikiart ne nomme qu'une partie des artistes de WikiArt ; les autres "
                     "œuvres sont « Unknown Artist » : l'absence d'artiste vient du jeu de données, pas des œuvres.")
    if a and a["known"]:
        notes.append(f"Les 10 artistes les plus présents font {round(a['top10_share'] * 100)} % des œuvres attribuées "
                     f"({a['distinct']} artiste{'s' if a['distinct'] > 1 else ''} nommé{'s' if a['distinct'] > 1 else ''} en tout).")
    st = coverage.get("style")
    if st and st["distinct"]:
        styles = [v for m in meta.values() if _known(v := m.get("style"))]
        cnt = Counter(styles)
        nw = [s for s in cnt if any(h in s.lower() for h in NON_WESTERN_HINTS)]
        share_nw = sum(cnt[s] for s in nw) / max(len(styles), 1)
        notes.append(f"{len(cnt)} styles, dont {len(nw)} hors de la tradition européenne et nord-américaine"
                     + (f" ({', '.join(nw)})" if nw else "") + f" : {share_nw * 100:.1f} % des œuvres stylées.".replace(".", ",", 1).replace("stylées,", "stylées."))
    if years is not None:
        ys = [y for y in years if y is not None]
        if ys:
            cent = Counter((y // 100) + 1 for y in ys)
            notes.append(f"Dates : {len(ys)} œuvres datées ({round(len(ys) / n * 100)} %).")
        else:
            notes.append("Aucune œuvre datée : la chronologie est indisponible.")
    if places is not None:
        notes.append(f"Lieux : {places} œuvres situées." if places else "Aucune œuvre située : la vue géographique est vide.")
    out = {"n": n, "coverage": coverage, "notes": notes}
    if years is not None and any(y is not None for y in years):
        cent = Counter((y // 100) + 1 for y in years if y is not None)
        out["centuries"] = [{"century": c, "count": cent[c]} for c in sorted(cent)]
    return out
