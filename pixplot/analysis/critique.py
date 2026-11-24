"""Couche critique : dire ce que voit chaque regard, d'où viennent les étiquettes, et de quoi
est fait le corpus.

Cinq lectures en sont à l'origine :

- A. Wasielewski, *Computational Formalism* (MIT Press, 2023) : biais perceptif (traits fins de
  la reproduction que l'historien ne regarde pas), étiquettes WikiArt bénévoles, canon occidental.
- T. Arnold et L. Tilton, *Distant Viewing* (MIT Press, 2023) : chaque algorithme encode une
  « manière de voir » qu'il faut rendre explicite ; annoter, c'est perdre et interpréter ; ne
  pas « fétichiser la taille ».
- L. Impett et F. Offert, « There Is a Digital Art History » (*Visual Resources*, 38:2, 2024) :
  un modèle multimodal porte un « imaginaire vectoriel » (*vector imaginary*) ; en lisant un
  corpus à travers le modèle, on lit toujours aussi le modèle à travers le corpus.
- D. G. Stork, *Pixels & Paintings: Foundations of Computer-assisted Connoisseurship* (Wiley,
  2024) : le calcul assiste l'œil du connaisseur sans jugement normatif, porte sur la reproduction
  numérique plutôt que l'œuvre matérielle, et n'a de sens que replacé dans le contexte historique.
- J.-L. Giavitto et P. Saint-Germier (dir.), *L'art au temps de l'IA* (Centre Pompidou, 2025) :
  les espaces latents réduisent le visible au « dicible » (Lista / Somaini) ; une distance
  calculée n'a de sens que relative au corpus et ne remplace jamais l'acte d'expertise humaine
  (Bureau et Doras) ; la numérisation porte ses conditions matérielles (Ebner et Frydryszak-Rétat).

D'où quatre outils : une **fiche par regard**, des **principes de lecture**, des **notes sur les
sources d'étiquettes**, et un **bilan du corpus** qui rend visibles ses trous et ses déséquilibres.
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
        "measured": "le meilleur sur « même composition » : 54 % des paires retrouvées parmi les 10 "
                    "premières voisines, l'un des deux seuls écarts sûrs du banc ; à égalité avec le sujet "
                    "sur les filiations (10 paires, trop peu pour conclure) (ARCHITECTURE § 38)",
    },
    "sujet": {
        "model": "SigLIP 2 So400m/16 (Google, 2025)",
        "trained_on": "WebLI : des milliards de paires image-légende du web, en plusieurs langues",
        "sees": "ce que l'on décrirait avec des mots : sujet, genre, école, manière",
        "blind_to": "ce qui n'a pas de nom dans les légendes du web",
        "biases": [
            "a appris des légendes qui nomment styles et artistes : il peut reconnaître une étiquette "
            "plutôt que voir une facture",
            "réduit le visible au « dicible » et porte son propre imaginaire vectoriel : lire le corpus "
            "par SigLIP 2, c'est aussi lire SigLIP 2 à travers le corpus (Impett et Offert, 2024 ; "
            "Lista / Somaini, 2025)",
            "a peut-être vu WikiArt pendant son entraînement : ses scores sur WikiArt sont sans doute optimistes",
            "légendes du web majoritairement en anglais et centrées sur l'art occidental",
        ],
        "measured": "le meilleur sur les étiquettes (style, genre, artiste) ; sur « même sujet », devant "
                    "la forme mais pas de façon sûre ; à égalité avec la forme sur les filiations "
                    "(ARCHITECTURE §§ 30, 38)",
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
        "measured": "seul regard qui retrouve « même palette » (48 % des paires parmi les 10 premières "
                    "voisines, écart sûr) ; presque aveugle au sujet (ARCHITECTURE §§ 18, 38)",
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
        "measured": "pointillisme 21 % → 62 % de voisines du même style ; en tête sur « même facture », "
                    "mais de façon sûre seulement devant le sujet (ARCHITECTURE §§ 11, 38)",
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
    "copie": {
        "model": "SSCD disc_large (Meta, CVPR 2022, ResNeXt-101 32×4d, licence MIT)",
        "trained_on": "DISC : 1 million d'images du web avec fortes transformations synthétiques "
                      "(recadrages, filtres, collages, mixup)",
        "sees": "empreinte de copie quasi-identique : répliques fidèles, quasi-doublons numériques",
        "blind_to": "réinterprétations libres, fragments inversés, changements de style ou de technique",
        "biases": [
            "conçu pour la détection de copies numériques sur le web, pas pour la filiation artistique",
            "sa régularisation d'entropie sépare fortement tout ce qui s'écarte d'une copie littérale",
        ],
        "measured": "évalué, non retenu par défaut : sur « filiation » (9 paires), R@10 33,3 %, "
                    "rang médian 216 (108 centré), derrière Forme (38,9 %, 26) et Sujet (38,9 %, 25) "
                    "(ARCHITECTURE § 27)",
    },
    "profondeur": {
        "model": "Depth Anything V2 Small (NeurIPS 2024, DINOv2 ViT-S/14 + DPT, licence Apache 2.0), "
                 "grille 8 × 8 calée sur l'œuvre (z-score)",
        "trained_on": "595 000 scènes synthétiques étiquetées en profondeur et 62 millions d'images "
                      "réelles pseudo-étiquetées",
        "sees": "l'agencement relatif des plans en profondeur (premier plan, plans intermédiaires, fond)",
        "blind_to": "les couleurs, la facture, le sujet, l'iconographie et les compositions sans profondeur "
                    "(abstraction, aplat, enluminure)",
        "biases": [
            "entraîné sur des scènes photographiques et 3D à perspective linéaire : les peintures sans "
            "perspective ou très planes reçoivent souvent un gradient vertical par défaut (bas proche, haut loin)",
            "sensible au contraste tonal et aux cadres/bordures présents dans la reproduction",
        ],
        "measured": "évalué, non retenu par défaut : sur « même composition » (14 paires), R@10 3,6 %, "
                    "rang médian 13 754 (6 874 centré), loin derrière Forme (53,6 %, rang 8) ; "
                    "la combinaison Forme + profondeur n'améliore pas Forme en validation croisée "
                    "(ARCHITECTURE § 28)",
    },
    "profondeur_dp2": {
        "model": "Depth Pro 2 Base (Apple, nov. 2026, DINOv3 ViT-B/16 + DPT, poids sous licence "
                 "apple-amlr non commerciale), grille 8 × 8 calée sur l'œuvre (z-score)",
        "trained_on": "mélange d'images uniques, vidéos et séquences multi-vues (détail non publié "
                      "par Apple)",
        "sees": "l'agencement relatif des plans en profondeur (contours nets, premier plan / fond)",
        "blind_to": "les couleurs, la facture, le sujet, l'iconographie et les compositions sans "
                    "profondeur perspective (abstraction, aplat, enluminure)",
        "biases": [
            "entraîné sur des photographies et vidéos 3D : invente des plans sur l'art non perspectif",
            "sensible au gradient vertical universel (haut loin, bas proche) et aux changements de format",
            "poids sous licence de recherche non commerciale (apple-amlr)",
        ],
        "measured": "évalué contre Depth Anything V2 et Forme, non retenu par défaut : sur "
                    "« même composition » (14 paires), R@10 0,0 %, R@100 7,1 %, rang médian "
                    "4 836 (4 266 centré), centile 0,851 — bien meilleur en rang médian que "
                    "Depth Anything V2 (13 754, centile 0,677) grâce à un biais de gradient "
                    "vertical quasi nul, mais largement battu par Forme (R@10 53,6 %, rang 8, "
                    "écart sûr +53,6 pts, p < 0,001)",
    },
    "sujet_pe": {
        "model": "PE-Core L/14 @336 (Meta, Perception Encoder, 2025, licence Apache 2.0), "
                 "images et textes (32 jetons)",
        "trained_on": "milliards de paires image-texte du web (majoritairement anglaises) puis "
                      "affinage sur vidéos légendées synthétiquement",
        "sees": "ce qui se décrit par des mots en anglais : sujet, genre, artiste, école, scène",
        "blind_to": "le vocabulaire iconographique français hors mots transparents (biais vers le "
                    "texte imprimé dans l'image) et ce qui échappe aux légendes du web",
        "biases": [
            "tour texte entraînée principalement en anglais (vocabulaire BPE CLIP de 49 408 jetons, "
            "fenêtre de 32 jetons) : perte nette en recherche par phrase en français",
            "sensible au texte imprimé ou inscrit sur les reproductions (titres, affiches, cartels)",
            "a probablement vu des reproductions de WikiArt lors de son entraînement sur le web",
        ],
        "measured": "évalué contre SigLIP 2, non retenu par défaut : légèrement devant sur les "
                    "étiquettes (+0,2 à +1,5 pt) et égal sur « filiation » (R@10 45,0 %, rang 18 vs 17), "
                    "mais nettement en retrait en recherche par phrase en français (81/100 contre "
                    "97/100 ; 92/100 contre 96/100 en anglais) (ARCHITECTURE § 31)",
    },
    "touche_csd": {
        "model": "CSD ViT-L/14 @224 (Somepalli et al., ECCV 2024, code MIT, poids CC BY 4.0), "
                 "tête style (768 d)",
        "trained_on": "initialisé sur OpenAI CLIP ViT-L/14, affiné par apprentissage contrastif "
                      "multi-étiquettes sur LAION-Styles (511 921 images de LAION-Aesthetics 6+, "
                      "3 840 étiquettes d'artistes, médiums et mouvements)",
        "sees": "la manière globale, l'école, le médium et le mouvement artistique tels que "
                "nommés dans les légendes du web",
        "blind_to": "la facture fine à haute résolution (entrée 224 px) et les gestes sans "
                    "étiquette stylistique courante dans LAION",
        "biases": [
            "risque de contamination sur WikiArt : LAION-Aesthetics 6+ contient de nombreuses "
            "reproductions issues de WikiArt (non écartées à l'entraînement) et des étiquettes "
            "d'artistes et mouvements, ce qui peut gonfler les scores sur ce corpus",
            "le checkpoint public Hugging Face est sauvegardé à l'itération 15 000 (les auteurs "
            "signalent un écart avec les chiffres de l'article)",
            "plus proche du regard « sujet » (16,2 % de voisines communes) que « touche » (12,0 %) : "
            "mesure autant le style nommé que la facture de surface",
        ],
        "measured": "évalué contre Touche (DINOv3 couche 6), non retenu par défaut : devant sur "
                    "les étiquettes de style (P@1 67,0 % vs 61,3 %, P@10 57,7 % vs 49,6 %) et les "
                    "paires de métadonnées « même facture » (méd. 2 157 vs 7 750), mais scores "
                    "possiblement gonflés par LAION-Styles et moins spécifique à la texture pure "
                    "(ARCHITECTURE § 32)",
    },
    "posture": {
        "experimental": True,
        "specialized": True,
        "status": "spécialisé · en essai",
        "model": "RT-DETRv2 + ViTPose Base Simple (Apache 2.0), descripteur de squelette 50 d "
                 "(13 articulations + 12 vecteurs de membres) avec miroir gauche-droite",
        "trained_on": "MS COCO (photographies annotées en personnes et 17 points clés)",
        "sees": "la posture et les gestes des figures humaines détectées (inclinaison du torse, "
                "position des bras et jambes, toutes figures comparées en direct et en miroir)",
        "blind_to": "le sujet, la couleur, la facture, les paysages, natures mortes, abstractions, "
                    "les portraits serrés sans corps et les figures très déformées (cubisme)",
        "biases": [
            "entraîné sur des photographies modernes (MS COCO) : fiable sur la peinture figurative "
            "occidentale et les gravures, mais échoue sur le cubisme et les figures fortement déformées",
            "ne couvre que 48,4 % de WikiArt 81k (œuvres où au moins une figure corporelle est détectée)",
            "une pose semblable est une piste visuelle (Pathosformel possible), jamais la preuve "
            "qu'un artiste a vu l'autre",
        ],
        "measured": "regard spécialisé, en essai : couvre 48,4 % de WikiArt 81k (39 043 œuvres, "
                    "102 515 figures ; 87,4 % en peinture religieuse, 2,7 % en abstraction). Ne bat "
                    "pas la forme sur les paires validées « filiation » (multi-figures : R@10 22,2 %, "
                    "méd. 1 754) et « même composition » (méd. 1 276), mais retrouve Le Semeur et "
                    "L'Enlèvement d'Europe au rang 1/1. Sur les paires « même geste » (25 validées "
                    "sur 37 proposées, 7 rejetées, 5 à relire), retrouve des formules gestuelles en "
                    "direct et en miroir que forme, sujet et touche manquent (ARCHITECTURE § 35)",
    },
}


def card(space: str) -> dict:
    return CARDS.get(space, {"model": space, "trained_on": "inconnu", "sees": "", "blind_to": "",
                             "biases": [], "measured": ""})


# ------------------------------------------------------------------ principes de lecture
PRINCIPLES: list[dict[str, str]] = [
    {
        "title": "Un score n'a de sens que relatif au corpus",
        "text": "Une similarité cosinus ne vaut pas décision binaire (proche / loin) : elle situe "
                "deux œuvres par rapport aux autres paires du corpus. Juger d'une parenté reste "
                "un acte d'expertise humaine multifactoriel.",
        "source": "S. Bureau et G. Doras, dans L'art au temps de l'IA (Centre Pompidou, 2025)",
    },
    {
        "title": "Lire le corpus par le modèle, c'est aussi lire le modèle",
        "text": "Les modèles multimodaux (SigLIP 2) encodent un « imaginaire vectoriel » issu "
                "du web et réduisent l'image au dicible. La carte par axes conceptuels (2 mots) "
                "permet d'éprouver ces biais sur votre corpus.",
        "source": "L. Impett et F. Offert, Visual Resources (2024) ; M. Lista, Centre Pompidou (2025)",
    },
    {
        "title": "La reproduction numérique n'est pas l'œuvre matérielle",
        "text": "Résolution, vernis jauni, balance des blancs, recadrage ou traces de numérisation "
                "pèsent sur tous les calculs. Les mesures visuelles (équilibre, entropie) assistent "
                "l'œil du connaisseur sans jugement normatif et toujours en contexte historique.",
        "source": "D. G. Stork, Pixels & Paintings (Wiley, 2024) ; F. Ebner et O. Frydryszak-Rétat (2025)",
    },
]


# ------------------------------------------------------------------ sources d'étiquettes
SOURCE_NOTES = [
    ("retrouvé par mmart", "Artiste lu dans le nom de fichier d'origine de WikiArt, retrouvé par empreinte d'image "
                           "(MMArt) : aucun désaccord sur les 35 717 œuvres qui avaient déjà un artiste (ARCHITECTURE § 34)."),
    ("mmart", "MMArt : titres, dates et noms de fichier de WikiArt, rattachés à nos images par empreinte "
              "(70 902 œuvres, 32 rattachements vérifiés à l'œil, ARCHITECTURE § 34)."),
    ("artemis", "ArtEmis : réactions de spectateurs recrutés en ligne (environ 5 par œuvre) ; on garde "
                "l'émotion citée par au moins 40 % d'entre eux (ARCHITECTURE § 34)."),
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
KEY_LABELS = {"artist": "artiste", "style": "style", "genre": "genre", "date": "date", "title": "titre", "emotion": "émotion (ArtEmis)",
              "wikiart_file": "nom de fichier WikiArt"}
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
        recovered = sum(x["count"] for x in a["sources"] if "MMArt" in x["source"])
        missing = 100 - round(a["share"] * 100)
        notes.append(("Le jeu huggan/wikiart ne nomme qu'une partie des artistes de WikiArt"
                      + (f" ; {recovered:,} ont été retrouvés".replace(",", " ") + " d'après les noms de fichier (MMArt)" if recovered else "")
                      + f" ; {missing} % des œuvres restent « Unknown Artist » : l'absence d'artiste vient du "
                      "jeu de données, pas des œuvres.") if missing else
                     "Le jeu huggan/wikiart ne nommait qu'une partie des artistes ; tous ont été retrouvés ici.")
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
        notes.append(f"Lieux : {places} œuvres situées ({round(places / n * 100) if n else 0} %), par au moins un lieu typé."
                     if places else "Aucune œuvre située : la vue géographique est vide (voir `pixplot places --derive`).")
    out = {"n": n, "coverage": coverage, "notes": notes}
    if years is not None and any(y is not None for y in years):
        cent = Counter((y // 100) + 1 for y in years if y is not None)
        out["centuries"] = [{"century": c, "count": cent[c]} for c in sorted(cent)]
    return out
