# PixPlot v2 — Architecture

[English](ARCHITECTURE.md) · **Français**

Laboratoire d'exploration visuelle pour l'histoire de l'art : cartographier 100 000 à
500 000 œuvres, retrouver des parentés formelles et des détails, et transmettre les
découvertes à un LLM (MCP, Research Pack) sans jamais perdre la traçabilité.

> **Rôles :** PixPlot calcule, observe et organise. Le LLM questionne et propose.
> L'historien vérifie, interprète et construit le savoir.

---

## 1. Principes

1. **Un seul cœur.** Toute la logique vit dans la bibliothèque Python `pixplot`. La CLI,
   l'API web et le serveur MCP sont trois façades fines sur ce cœur.
2. **Étapes versionnées.** Chaque étape lit les sorties de la précédente et écrit un
   *run* dans `data/runs/<étape>/<nom>_<horodatage>/` avec un `manifest.json`
   (modèle, paramètres, run parent, versions, statut). Rien n'est écrasé.
3. **Reprenable.** 500 000 images avec 16 Go de RAM : tout est traité par lots, écrit sur
   disque (memmap FP16) et peut reprendre après un arrêt.
4. **Modèles interchangeables.** Chaque modèle passe par l'interface `Encoder`.
5. **Image entière.** Jamais de `CenterCrop` : on redimensionne et on complète par des
   bandes (letterbox) pour préserver la composition.
6. **Identifiants stables.** Une œuvre = un `artwork_id` + l'empreinte SHA-256 du fichier,
   jamais son nom de fichier.
7. **Local d'abord.** Aucun envoi d'images vers l'extérieur, aucune télémétrie.

## 2. Vue d'ensemble

```
 Images + métadonnées (dossiers, CSV, IIIF, musées)
            │
 ① INGESTION ─────────── CPU
            │  catalogue SQLite, SHA-256, pHash (quasi-doublons), vignettes
            ▼
 ② EXTRACTION ────────── GPU (RX 7900 GRE)
            │  DINOv3 ViT-B/16 : vecteur global (768) + vecteurs régionaux
            │  SigLIP 2 : vecteur image↔texte
            ▼
 ③ INDEX ─────────────── CPU
            │  FAISS : global / régions / texte
            ▼
 ④ ANALYSE ───────────── CPU
            │  e-means, HDBSCAN, PCA→UMAP, graphe des k voisins, œuvres atypiques
            ▼
 ⑤ SERVICES ──────────── bibliothèque pixplot
            ├── API FastAPI ──► ⑥ INTERFACE web (Atlas, fiche, comparateur, carnet)
            ├── serveur MCP ──► Claude / autre LLM
            └── ⑦ EXPORT ─────► Research Pack (.zip)
```

## 3. Couches

### ① Ingestion — `pixplot.catalog`
- Parcours des dossiers, identifiant stable, SHA-256 (doublons exacts), pHash
  (quasi-doublons : deux scans d'une même œuvre).
- Une image illisible est **écartée et journalisée**, elle ne bloque pas le traitement.
- Import de métadonnées : artiste, date, lieu, technique, institution, source, droits.
- Vignettes 64 / 256 / 1024 px + planches de vignettes (atlas) pour le rendu WebGL.

### ② Extraction — `pixplot.encoders`, `pixplot.features`
- Prétraitement : letterbox à la résolution du modèle (fond = moyenne ImageNet).
- **DINOv3 ViT-B/16** (Meta) :
  - vecteur global (token CLS normalisé, 768 d) → ressemblance d'ensemble ;
  - vecteurs régionaux : les patchs sont moyennés sur des grilles 1×1, 2×2 et 4×4
    (21 régions) → recherche par détail. Étape 1 : stockés tels quels (768 d, FP16,
    ~16 Go sur disque pour 500 000 œuvres) ; étape 5 : réduits à 256 d par PCA puis
    compressés dans l'index régional.
    (Garder tous les patchs coûterait ~150 Go pour 500 000 images.)
- **SigLIP 2 So400m** (Google, `google/siglip2-so400m-patch16-384`, Apache 2.0, accès
  libre) → recherche en texte libre, **multilingue** (requêtes en français). Letterbox avec
  la normalisation propre à SigLIP (0,5 / 0,5). Pas de vecteurs régionaux.
  Sur la 7900 GRE : 47 images/s, 4,7 Go de mémoire GPU.
- Option : **DINOv3 ViT-L/16** : +2 à 3 points sur l'artiste et le style, 1,8 fois plus
  lent (voir § 9). Conseillé pour le traitement final d'un grand corpus.
- **DINOv2 ViT-B/14 (registres)** : sans demande d'accès, pour démarrer en attendant la
  validation de DINOv3, puis comme point de comparaison.
- Chargement des poids : Hugging Face (`transformers`) par défaut ; format Meta `.pth`
  en secours pour DINOv3.
- Résolution par défaut : 448 px (confirmée au banc d'essai : +3 points sur l'artiste
  par rapport à 224 px, pour 2,5 fois plus de calcul).
- Accélération : **PyTorch ROCm natif sous Windows 11** en priorité ; secours WSL2 + ROCm,
  puis CPU (ONNX Runtime + DirectML envisageable, non implémenté).

### ③ Index — `pixplot.index`

| Index | Contenu | Type FAISS | Taille (500k) |
|---|---|---|---|
| `global` | DINOv3 global | `IndexFlatIP` | ~1,5 Go |
| `regions` | ~10 M régions | `IVF-PQ` | ~0,5 Go |
| `text` | SigLIP 2 (1 152 d) | `IndexFlatIP` | ~2,2 Go |

### ④ Analyse — `pixplot.analysis`
Commande : `pixplot analyze [--clusters N] [--hdbscan]`. Graine fixe : reproductible.
- **Regroupement** : e-means sphérique (`faiss.contrib.e_means.NumpyEmeans`, inclus dans
  `faiss-cpu` 1.16, y compris sous Windows), ≈ √N / 2 groupes par défaut (8 à 200) ; pour
  chaque groupe, l'œuvre la plus proche du centre sert d'image représentative.
- **HDBSCAN** (option, scikit-learn) sur une UMAP intermédiaire en 10 dimensions : familles
  « naturelles » et œuvres « à part ». Directement sur les vecteurs, presque tout serait
  déclaré à part (28 % sur WikiArt, contre 2 % ainsi). Inexploitable à grande échelle
  (§ 11) : l'Atlas le masque quand plus de 30 % des œuvres seraient « à part ».
- **Cartes** : PCA 64 d → UMAP 2D, appris sur un échantillon (~100k) puis appliqué au reste.
  L'échelle ignore 0,5 % d'œuvres extrêmes de chaque côté, posées sur le bord.
  Noms de groupes et étiquettes à vérifier : voir § 12.
- **Graphe de voisinage** : 20 plus proches voisines par œuvre (`neighbors.npy` + scores).
- **Atypicité** : rang centile de l'isolement (faible similarité moyenne avec ses voisines).
  Plus tard : voisines très différentes d'un espace à l'autre.
- **Carte statique** : grande image JPEG des vignettes à leur place UMAP, numéros de groupe
  au centre (`data/maps/`), en attendant l'interface de l'étape 4.

### ⑤ Services — `pixplot.api`, `pixplot.mcp`
- **API FastAPI** (`pixplot serve`, écoute sur 127.0.0.1 seulement par défaut) :
  `/api/info`, `/api/map` (colonnes compactes : position, groupe, atypicité, catégories),
  `/api/clusters`, `/api/artwork/{id}` (métadonnées + sources, voisines, provenance du calcul),
  `/api/search?q=`, `/api/thumb/{taille}/{id}`, `/api/image/{id}` (images servies par
  identifiant uniquement, jamais par chemin). Documentation automatique : `/api/docs`.
- **Serveur MCP** (`pixplot mcp`, stdio, SDK officiel `mcp` 2.x) : 14 outils —
  `corpus_overview`, `search_by_text`, `similar_artworks` (paramètre `space`),
  `search_detail`, `get_artwork`, `view_artwork`, `view_detail`, `compare_artworks`,
  `get_group`, `find_atypical`, `check_labels`, `notebook_add`, `notebook_list`,
  `export_research_pack`. Les outils `view_*` et `compare_artworks` **renvoient des images**
  au LLM. Consignes de méthode et de prudence intégrées. Branchement : `docs/MCP.fr.md`.

### ⑥ Interface — `web/`
**deck.gl 9.4** (rendu WebGL), en JavaScript simple **sans étape de compilation** : le
fichier deck.gl est rangé dans `web/vendor/`, donc ni Node ni connexion Internet ne sont
nécessaires pour utiliser l'Atlas. Choisi plutôt que PixiJS pour son zoom/déplacement,
sa sélection au clic et son rendu de centaines de milliers de points prêts à l'emploi.
**Toutes les vignettes sont affichées en permanence**, sans scintillement : elles viennent
de planches de 4096 × 4096 px (« atlas de textures », comme dans PixPlot v1) construites
par `pixplot analyze` (ou à la première ouverture de l'Atlas) et chargées une fois sur le
GPU. Cases de 64 px jusqu'à 30 000 œuvres, 32 px au-delà (500 000 œuvres ≈ 2 Go de VRAM).
Au zoom, des vignettes 256 puis 1024 px se posent **par-dessus** les 300 œuvres les plus
proches du centre, sans jamais retirer celles de dessous. Sélecteur « Affichage » :
vignettes ou points colorés (les couleurs par groupe, style… se lisent sur les points).
L'interface est servie en `Cache-Control: no-cache` (pas de mélange ancienne page /
nouveau script après une mise à jour).

Écrans : carte des groupes (nommés), coloration (groupes, atypicité, artiste, style…),
légende cliquable, recherche (métadonnées, description, détail), fiche œuvre avec ses
voisines selon chaque regard et ses étiquettes à vérifier, comparateur, carnet de
recherche, panneau « À vérifier », dispositions carte / chronologie / géographie, lien
partageable `#oeuvre-<id>`.

### ⑦ Research Pack — `pixplot.export`
`pixplot pack` (CLI), bouton « Exporter » de l'Atlas, outil MCP `export_research_pack`.
Sélection : liste d'œuvres, groupe, voisines d'une œuvre, recherche texte ou détail.
```
<date>_<titre>.zip            (≈ 50 Ko par œuvre)
├── manifest.json      titre, question, modèles, runs et paramètres, provenance de la sélection
├── summary.md         le dossier rédigé : méthode, composition, œuvres, relations les plus
│                      fortes, atypiques, mises en garde, consigne proposée pour un LLM
├── artworks.csv       métadonnées, groupe, famille, atypicité, score de la recherche
├── relations.csv      toutes les paires : similarité visuelle (DINOv3) et sémantique (SigLIP)
├── evidence/          vignette 512 px par œuvre + détails recadrés (lisibles par un LLM)
└── vectors.npy        (option `--vectors`) pour reproduire les calculs
```
CSV / JSON / Markdown / JPEG plutôt que Parquet : lisibles par n'importe quel LLM ou
tableur, sans outil particulier. Un LLM ne sait rien faire de vecteurs bruts : ce qui
compte, ce sont les **relations explicites, les métadonnées sourcées et les images**.

## 4. Arborescence

```
Pixplot V2/
├── ARCHITECTURE.md / ARCHITECTURE.fr.md
├── pyproject.toml
├── pixplot/
│   ├── config.py          chemins et réglages (PIXPLOT_DATA)
│   ├── runs.py            runs versionnés + manifests
│   ├── cli.py             pixplot ingest | embed | index | analyze | serve
│   ├── catalog/           ① SQLite, ingestion, vignettes, doublons
│   ├── importers/         ① IIIF
│   ├── encoders/          ② interface Encoder, letterbox, dinov3, siglip2, texture, colorlab
│   ├── features/          ② extraction par lots, reprise, régions
│   ├── index/             ③ FAISS
│   ├── analysis/          ④ e-means, hdbscan, umap, voisins, noms, étiquettes à vérifier, audit
│   ├── export/            ⑦ Research Pack
│   ├── notebook.py        carnet de recherche (SQLite)
│   ├── api/               ⑤ FastAPI, espaces de ressemblance
│   └── mcp/               ⑤ serveur MCP
├── web/                   ⑥ Atlas : index.html, atlas.js, atlas.css, vendor/deck.gl
├── tests/
├── data/                  (hors git) catalog.sqlite, thumbs/, runs/
├── scripts/               full_pipeline.sh, extraction Parquet, variantes synthétiques
└── pix-plot-0.0.1.1/      PixPlot v1 (Yale, 2018) — référence locale, non publiée
```

## 5. Feuille de route

1. ~~Ingestion + extraction DINOv3 sur 1 000 images ; validation du GPU~~ **fait**.
2. ~~Index FAISS global + banc d'essai~~ **fait** (voir § 9).
3. ~~PCA→UMAP + e-means → première carte~~ **fait**.
4. ~~API + interface Atlas + fiche œuvre~~ **fait** *(= « PixPlot v1 en mieux »)*.
5. ~~Recherche par détail, puis SigLIP 2 (texte)~~ **fait** *(= le vrai apport pour l'historien)*.
   - Détail : `pixplot index --regions` indexe les zones 2×2 et 4×4 (PCA 256 d ; exact
     jusqu'à 1,5 M de zones, IVF-PQ au-delà). Dans l'Atlas, « Chercher un détail » : on
     trace un cadre, il est découpé dans l'original et analysé à une résolution qui
     respecte son échelle (112, 224, 336 ou 448 px : 4 tailles fixes, car le GPU AMD
     compile ~20 s par nouvelle taille, une seule fois). Résultat : la zone la plus
     proche de chaque œuvre, découpée et affichée.
   - Texte : `pixplot embed --encoder siglip2_so400m`, `pixplot index --encoder
     siglip2_so400m`, puis `pixplot search-text "…"` ou le mode « Description (IA) » de
     l'Atlas. Les modèles ne sont chargés qu'à la première recherche.
   - Essais (WikiArt) : « Annonciation » → *L'Annonciation* de Doré en 1ʳᵉ position ;
     « saint Sébastien » → le *Saint Sébastien* de Titien en 2ᵉ (1ʳᵉ : un Christ souffrant
     du même peintre) ; « un navire dans la tempête » → 5 marines d'Aivazovsky. Utile pour
     défricher, à vérifier œuvre par œuvre.
6. ~~Serveur MCP + Research Pack~~ **fait**.
7. ~~Comparateur, carnet de recherche, chronologie et géographie~~ **fait** (voir § 12).

La suite (groupes Leiden, désaccords entre regards, recherche d'une zone par des mots, Iconclass, composition) est dans [ROADMAP.fr.md](ROADMAP.fr.md).

## 6. Leçons tirées de PixPlot v1 (0.0.1.1)

| Problème du v1 | Réponse du v2 |
|---|---|
| Images identifiées par nom de fichier (collisions) | `artwork_id` + SHA-256 |
| Ordre des vecteurs ≠ ordre des positions si une image échoue | Ordre fixé par le catalogue, lignes alignées par id |
| Une image corrompue arrête tout | Écartée et journalisée |
| Un `.npy` par image, tout chargé en RAM | Un memmap FP16 par run |
| Inception (classification d'objets), JPEG seulement | DINOv3 + SigLIP 2, tous formats |
| k-means fixe à 20, étiquettes à éditer dans le JSON | e-means + HDBSCAN, étiquettes proposées |
| Pas de recherche de similarité | FAISS : image, région, texte |
| Google Analytics intégré | Aucune télémétrie |

**À reprendre :** les planches de vignettes (atlas) et le découpage du rendu par paquets,
généralisés à plusieurs niveaux de zoom ; les « hotspots » avec image représentative.

## 7. Principes scientifiques

Traçabilité (modèle, version, paramètres par résultat) · Reproductibilité (tout run peut
être relancé) · Provenance (source de chaque œuvre et métadonnée) · Incertitude (un score
n'est pas une probabilité historique) · Contradiction (chercher les contre-exemples) ·
Contrôle humain (le chercheur valide).

## 8. Licences

- **PixPlot v2 : GPL-3.0**
- PixPlot v1 : MIT · FAISS / e-means : MIT
- **DINOv3 : licence propre à Meta, accès aux poids sur demande** — à relire avant toute
  diffusion publique ou commerciale des résultats ou du logiciel.
- SigLIP 2 : Apache 2.0

## 9. Banc d'essai (15/11/2026)

RX 7900 GRE, Windows 11 natif, PyTorch 2.14 + ROCm 10.1. Corpus : 2 263 œuvres WikiArt
(124 artistes, 27 styles) + 1 000 variantes synthétiques de 250 d'entre elles.
Commande : `pixplot bench` (catalogue séparé `data/bench`).

| Configuration | Artiste P@1 | Style P@1 | Genre P@1 | Variantes R@1 | img/s | VRAM |
|---|---|---|---|---|---|---|
| DINOv2 B/14 @448 | 37,1 % | 41,1 % | 68,0 % | 98,8 % | 56 | 834 Mo |
| DINOv3 B/16 @224 | 39,4 % | 46,7 % | 72,4 % | 99,6 % | 150 | 585 Mo |
| **DINOv3 B/16 @448** (défaut) | 42,6 % | 49,3 % | 72,7 % | 99,6 % | 60 | 758 Mo |
| DINOv3 L/16 @448 | **45,3 %** | **51,5 %** | 71,5 % | 99,5 % | 34 | 1 466 Mo |

Hasard : artiste 2,9 %, style 10,0 %, genre 14,7 %.

- **Variantes** (gravure inversée, reproduction N&B, détail recadré, copie altérée) : toutes
  les configurations retrouvent l'original dans ~99 % des cas. Excellent pour l'usage, mais
  trop facile pour départager les modèles : il faudra de vraies paires (copies d'atelier,
  gravures d'interprétation) pour un test plus discriminant.
- **Temps estimé pour 500 000 œuvres** : B@448 ≈ 2 h 20, L@448 ≈ 4 h, B@224 ≈ 1 h.
- Mise en garde : les étiquettes WikiArt sont imparfaites, et « même artiste » n'est qu'un
  indicateur indirect de ce que cherche l'historien.

## 10. Audit à l'aveugle (16/11/2026)

Les modèles ne lisent que les pixels ; les métadonnées ne servent qu'à évaluer.
`pixplot audit` compare voisinages et groupes aux étiquettes et produit
`data/audits/<analyse>/audit.md` (chiffres) et `audit.html` (exemples d'échecs).

Sur WikiArt (DINOv3 B/16, 24 groupes) : pureté des groupes 26 % (artiste), 38 % (style),
70 % (genre). Quatre familles d'« échecs », d'après les exemples regardés un à un :

1. **Le sujet l'emporte sur la manière.** Un portrait fauve de Matisse a pour voisins des
   portraits réalistes, expressionnistes, post-impressionnistes : même cadrage en buste,
   palette ignorée. Le modèle voit *ce qui est représenté et comment c'est composé* avant
   la couleur et la touche.
2. **La technique et le support rapprochent.** Un *Pop Art* de Warhol (téléphone au trait)
   tombe parmi les dessins et les natures mortes cubistes ; gravures et dessins se
   regroupent entre eux quel que soit le style.
3. **Les frontières historiographiques ne sont pas visuelles.** Maniérisme ↔ Baroque,
   Première ↔ Haute Renaissance, Minimalisme ↔ Color Field : confusions fréquentes, mais
   souvent de vraies parentés. Le pointillisme de Pissarro est rangé avec ses paysages
   impressionnistes — même artiste, même motif ; la touche divisée est invisible à
   l'échelle d'analyse.
4. **Les étiquettes elles-mêmes sont fausses.** Plusieurs œuvres « portrait » sont en réalité
   des scènes de genre, des figures dans un paysage ou une fresque à plusieurs saints ; un
   « Minimalisme » est une abstraction gestuelle. Le modèle avait raison : l'audit sert aussi
   à **repérer les erreurs de catalogue**.

Pistes : espace chromatique et espace « touche » (patchs fins) pour les styles définis par la
couleur ou la facture ; regroupement selon plusieurs espaces ; signaler à l'historien les
étiquettes probablement erronées.

## 11. Passage à l'échelle : WikiArt complet (16/11/2026)

81 444 images (72 fichiers Parquet, 33,7 Go), RX 7900 GRE, Windows natif, 16 Go de RAM.
Commande unique : `bash scripts/full_pipeline.sh data/wikiart81k` (journal chronométré).

| Étape | Durée | Remarque |
|---|---|---|
| Extraction des Parquet | 1 min 31 | |
| Ingestion (hash, vignettes 64/256/1024) | 35 min 47 | 80 716 œuvres, 728 doublons exacts, 0 erreur |
| DINOv3 B/16 @448 | 14 min 17 | 96,8 img/s, 1,1 Go de VRAM |
| SigLIP 2 So400m @384 | 18 min 51 | 73,2 img/s, 5,1 Go de VRAM |
| Index globaux (flat) | 2 s | |
| Index des zones | 57 s | 1,58 M zones → IVF-PQ (nlist 5032, m 32) |
| Analyse (e-means 142 groupes, UMAP, planches) | 8 min 30 | 5 planches de 4096 px, cases de 32 px |
| Audit + banc d'essai | 1 min 10 | |
| **Total** | **≈ 1 h 21** | |

**Atlas** : 80 716 vignettes affichées d'un coup ; chargement ≈ 3 s (carte 2 Mo gzip,
35 Mo de planches), 144 images/s à l'arrêt. Avec 142 groupes, les numéros se chevauchaient :
filtre de collision deck.gl, les plus grands groupes passent devant. **Recherche** : 0,25 s par
requête (texte comme détail) une fois les modèles chargés ; premier appel 15 à 27 s.

**Banc d'essai (P@1, k=10)** — plus de voisins possibles qu'à 2 263 œuvres, d'où des scores
plus hauts : DINOv3 artiste 65,6 %, style 64,8 %, genre 80,9 % ; **SigLIP 2 artiste 73,0 %,
style 71,4 %, genre 83,4 %**. Sur les catégories de l'histoire de l'art, l'espace texte-image
retrouve mieux que l'espace purement visuel : un second « mode de voisinage » SigLIP dans
l'Atlas serait utile. L'audit confirme § 10 (Fauvisme 20 %, Pointillisme 21 % en P@10 ;
Delacroix, Manet, Serov mal retrouvés).

**HDBSCAN ne passe pas l'échelle sur ce corpus.** Avec le réglage qui donne 7 familles et
1,6 % « à part » sur 2 263 œuvres, on obtient 692 micro-familles et 52 % « à part » sur
80 716. Aucun réglage intermédiaire : `min_cluster_size` 40 → 261 familles / 53 % à part ;
≥ 100 → un bloc de 70 % du corpus et 0,2 % à part. WikiArt est un continuum sans creux de
densité nets. HDBSCAN reste une option (`--hdbscan`, avertissement au-delà de 30 % à part) ;
pour les œuvres isolées, le score d'atypicité (densité des voisins) est le signal fiable.

## 12. Étape 7 : plusieurs regards, comparateur, carnet, chronologie (16/11/2026)

**Quatre espaces de ressemblance.** Chaque run `features` terminé est un « regard » sur le
corpus ; la fiche de l'Atlas, le comparateur et le serveur MCP (`similar_artworks`,
paramètre `space`) laissent choisir :

| Espace | Encodeur | Ce qu'il regarde | Calcul 81k |
|---|---|---|---|
| forme | `dinov3_vitb16` (CLS) | formes, composition, motifs | 97 img/s |
| sujet | `siglip2_so400m` | ce qu'on décrit avec des mots : sujet, genre, école | 73 img/s |
| couleur | `color_lab` | palette (histogramme CIELAB 5×7×7, sans GPU) | 127 img/s |
| touche | `dinov3_vitb16_texture` | facture : moyenne + écart-type des patchs de la couche 6 | 125 img/s |

« Couleur » et « touche » sont des statistiques : une composante commune dominerait toutes
les similarités, d'où un **centrage sur la moyenne du corpus** en fin d'extraction
(`center.npy` gardé dans le run). Le choix de la couche 6 vient d'un essai sur 6 424 œuvres
équilibrées par style (couches 2 à 12, moyenne / écart-type / les deux) : les couches
intermédiaires voient la facture, la dernière les objets.

Banc d'essai WikiArt 80 716 œuvres, P@10 (même étiquette parmi les 10 plus proches) :

| | artiste | style | genre | Pointillisme | Fauvisme | Ukiyo-e |
|---|---|---|---|---|---|---|
| forme (DINOv3) | 50,8 % | 52,4 % | 76,8 % | 21 % | 20 % | 93 % |
| sujet (SigLIP 2) | **61,6 %** | **62,0 %** | **79,5 %** | 44 % | 26 % | **99 %** |
| touche | 53,0 % | 49,6 % | 62,8 % | **62 %** | **30 %** | 80 % |
| couleur | 15,0 % | 19,4 % | 30,3 % | | | |

La touche reconnaît mieux la main de l'artiste que la forme et bien moins le genre :
c'est ce qu'on attend d'un regard qui ignore le sujet. La couleur seule classe mal, mais
répond à une autre question (« quelles œuvres ont cette palette ? »).

**Noms de groupes** (`pixplot name-groups`) : le centre de chaque groupe dans l'espace
SigLIP 2 comparé à un vocabulaire de 34 sujets et 23 techniques ou manières ; on garde le
terme le plus *distinctif* (écart à la moyenne des groupes) parmi les 3 plus proches.
Exemples à 81k : « Scènes religieuses · icône » (Angelico), « Scènes nocturnes · estampe
japonaise » (Hokusai), « Batailles · gravure » (Doré), « Jardins · empâtements » (Monet).
Ça marche sans métadonnées ; ce sont des propositions à relire.

**Étiquettes à vérifier** (`pixplot suspects`, panneau « À vérifier », outil MCP
`check_labels`) : ≥ 70 % des voisines étiquetées (espace « sujet ») partagent une autre
valeur, ≤ 10 % la sienne. À 81k : 506 artistes, 2 771 styles, 1 607 genres. Côté artiste,
c'est surtout « qui ressemble à qui » (Sisley → Monet, Morisot → Renoir) ; côté genre, de
vraies erreurs de catalogue (scènes religieuses étiquetées « genre_painting »). Jamais une
correction automatique.

**Comparateur** : jusqu'à 6 œuvres côte à côte en grand, métadonnées, et la similarité de
chaque paire dans chaque espace. **Carnet de recherche** (`<données>/notebook.sqlite`,
séparé du catalogue) : œuvres, sélections, recherches, détails et comparaisons, avec note,
contexte et export Markdown ; le LLM y écrit aussi via MCP (`notebook_add`), en se signalant.

**Chronologie et géographie** : proposées quand les métadonnées ont des dates (première
année lisible dans `date`, `year`, `datation`…) ou `latitude` / `longitude`. Chronologie :
un bloc par période (pas choisi pour tenir à l'écran), œuvres rangées par groupe, bloc
« sans date ». Géographie : longitude / latitude sans fond de carte (hors ligne), œuvres d'un
même lieu en spirale. WikiArt n'a ni dates ni lieux : la chronologie a été validée sur une
vraie collection importée par IIIF (ci-dessous).

**Importateur IIIF** (`pixplot import-iiif`) : manifestes et collections v2 / v3 (imbriquées,
paginées), image de la première vue (ou toutes) par l'API Image à la taille voulue,
métadonnées normalisées (titre, artiste, date, lieu, technique, droits, cote) dans
`metadata.csv`, reprise sans retéléchargement, une requête à la fois.

Essai réel (16/11/2026) : 18 peintures du **Yale Center for British Art** (domaine public,
3,7 Mo), toutes importées, pipeline complet en 2 min 30. Leçons :
- l'**Art Institute of Chicago** sert ses images derrière une vérification anti-robot
  Cloudflare : refus (403) pour tout téléchargement automatique. On ne la contourne pas ;
  passer par une autre institution ou par leurs exports officiels ;
- Yale ne donne **la date que dans le libellé** (« Turner, 1775–1851, Dort, 1818 ») : elle en
  est extraite (dernier segment contenant une année, jamais les dates de vie juste après le
  nom) et marquée `date_source = déduite du libellé du manifeste` ;
- la chronologie s'affiche alors d'elle-même (blocs de 20 ans, 1740 → 1920) ;
- sur 18 œuvres, les noms de groupes restent approximatifs (« Marines · aquarelle » pour des
  huiles de Gainsborough et Turner) : le vocabulaire juge l'apparence, pas la technique réelle.


## 13. Interface : une carte par regard, fond de carte, ergonomie (16/11/2026)

**Une carte par regard** (`pixplot maps`) : la même projection PCA → UMAP calculée dans chaque
autre espace (`maps/<espace>.npy` dans le run d'analyse, aligné sur `ids.npy` ; ≈ 4 min par
espace à 81k). Les groupes restent ceux de la carte principale, pour suivre un groupe d'une
carte à l'autre ; son numéro ne s'affiche que là où il reste groupé (dispersion < 18 % de la
carte). À 81k : 38 des 142 groupes « forme » restent groupés sur la carte « sujet », presque
aucun sur les cartes « touche » et « couleur » — les groupes de forme ne sont pas des groupes
de facture.

**Fond de carte du monde** pour la disposition « Géographie » : TopoJSON world-atlas (Natural
Earth 1:110 M, domaine public, 108 Ko) embarqué dans `web/vendor/` et décodé dans le
navigateur (fonctionne hors ligne).

**Ergonomie** : en-tête réduit à la recherche et quatre outils (carte, affichage et couleurs
dans un menu « Vue »), compteurs dans une barre d'état sur la carte, largeurs des panneaux
proportionnelles à la fenêtre (panneau des groupes repliable, panneaux par-dessus la carte
sous 1 100 px), panneau de droite avec un titre et un bouton « Retour » vers la liste d'où
l'on vient, écran d'accueil à la première visite, aide (`?`) et raccourcis clavier (`/`
chercher, `G` groupes, `C` comparer, `N` carnet, `V` à vérifier, `0` vue d'ensemble, `Échap`
fermer). Vérifié à 1 920, 1 536, 1 366 et 1 024 px de large.

## 14. Banc d'essai par paires : quel regard pour quelle ressemblance ? (16/11/2026)

Les scores par étiquette (§ 11) disent si les voisines partagent l'artiste ou le style, pas
*pourquoi* deux œuvres se ressemblent. `pixplot pairs` mesure chaque regard sur des paires
typées : même sujet mais composition différente, même composition mais sujet différent,
même artiste mais facture différente, artistes différents mais facture comparable, même
motif à des époques différentes, même palette dans des traditions différentes, filiation
attestée, et un témoin (rien en commun). Pour chaque paire, dans les deux sens, on calcule
le rang exact de l'œuvre jumelle parmi tout le corpus : R@10, R@100, rang médian et
**centile** (part du corpus plus éloignée que la jumelle ; 0,5 = hasard).

Deux origines, toujours séparées dans le rapport : les paires **annotées** par l'historien
(bouton « Annoter » du comparateur de l'Atlas, ou `pixplot pairs add`, avec leur source et
un statut validée / proposée / rejetée), et des paires **tirées des métadonnées**
(`pixplot pairs generate`), nombreuses mais grossières. Fichier : `<données>/bench/pairs.csv`.

Premier résultat sur WikiArt 81k, paires tirées des métadonnées (centile, 300 paires par
type, 250 pour la facture, réparties à parts égales entre cinq styles) :

| type | forme | sujet | couleur | touche |
|---|---|---|---|---|
| même sujet (genre), autres artistes et styles | 0,725 | **0,726** | 0,517 | 0,622 |
| même artiste, autre style | 0,691 | **0,790** | 0,596 | 0,660 |
| même style de facture, autres artistes et genres | 0,793 | **0,831** | 0,625 | 0,803 |
| — dont Fauvisme | 0,635 | 0,682 | 0,702 | **0,818** |
| — dont Pointillisme | 0,735 | **0,847** | 0,671 | 0,819 |
| — dont Impressionnisme | 0,639 | **0,656** | 0,477 | 0,541 |
| témoin | 0,456 | 0,450 | 0,468 | 0,447 |

Lecture : SigLIP 2 l'emporte presque partout, mais il a appris sur le web des légendes
qui nomment styles et artistes (et a peut-être vu WikiArt) : il reconnaît une étiquette
plus qu'il ne voit une facture. La touche gagne nettement là où la facture est
spectaculaire (Fauvisme) et échoue sur un style aussi large que l'Impressionnisme. Le
regard « forme » ne distingue presque pas « même sujet » du reste : un genre WikiArt est
une catégorie trop lâche. D'où la suite : des **paires annotées** (filiations décrites par
Honour et Fleming, relecture dans l'Atlas), seules capables de tester la composition et
la palette, avant d'ajouter de nouveaux modèles (STELLAR, PE-Spatial).

**Premières paires annotées** (11 paires, statut « proposée », à valider dans l'Atlas ; 4
attestées par Honour et Fleming, p. 671, 672, 709 et 772, les autres hors du livre). Rang
de la jumelle dans chaque sens, parmi 80 716 œuvres :

| paire | forme | sujet | couleur | touche |
|---|---|---|---|---|
| Raphaël ← Pérugin, *Mariage de la Vierge* | 2 / 1 | 1 / 1 | 9 656 | 8 / 19 |
| Van Gogh ← Millet, *Le Semeur* | 2 / 1 | 1 / 1 | 21 160 | 251 / 728 |
| Manet ← Goya, *Maximilien* / *Tres de mayo* (p. 672) | 2 / 68 | 2 / 12 | 41 279 | 391 / 998 |
| Manet ← Titien, *Olympia* / *Vénus d'Urbin* (p. 709) | 4 / 23 | 4 / 58 | 4 075 | 568 / 588 |
| Manet ← *Concert champêtre* (p. 671) | 8 / 796 | 155 / 130 | 14 153 | 1 070 / 2 062 |
| Monet ← Manet, *Déjeuner sur l'herbe* | 84 / 435 | 22 / 3 | 3 328 | 124 / 18 |
| Picasso ← El Greco, *Demoiselles* / *Vision de saint Jean* (p. 772) | 418 / 2 144 | 671 / 96 | 74 329 | 2 106 / 1 497 |
| Picasso ← Delacroix, *Femmes d'Alger* | 20 944 / 49 444 | 2 076 / 766 | 32 508 | 4 308 / 7 472 |
| Van Gogh ← Rembrandt, *Lazare* (fragment) | 1 856 / 3 645 | 591 / 1 814 | 77 018 | 67 412 |
| Pérugin, *Remise des clés* / *Mariage de la Vierge* (même composition) | 2 / 2 | 2 / 21 | 47 111 | 103 / 62 |

Les copies et reprises de composition sont retrouvées au tout premier rang par la forme
comme par le sujet ; dès que l'artiste transforme son modèle (Picasso, le fragment de
Lazare), aucun regard ne suit. La forme est le seul regard qui retrouve la citation de
Manet d'après le *Concert champêtre* depuis le Déjeuner (rang 8). La couleur ne retrouve
aucune filiation : une copie change de palette. C'est exactement ce que doit tester un
nouveau modèle de composition (STELLAR).

## 15. Groupes Leiden : emboîtés, par regard (16/11/2026)

`pixplot communities` calcule, pour chaque regard, des communautés Leiden sur le graphe des
15 plus proches voisines (pondéré par la similarité) : des **groupes** (autant qu'e-means,
pour comparer à armes égales, résolution trouvée par dichotomie) et des **familles**
(Leiden sur le graphe des groupes : une famille est toujours une réunion de groupes). Les
communautés de moins de 5 œuvres sont rattachées à la voisine la plus liée. Dans l'Atlas,
menu « Vue » → couleur : « Familles Leiden » et « Groupes Leiden » pour chaque regard.

Comparaison sur WikiArt 81k, 142 groupes, trois graines par méthode. Stabilité = indice de
Rand ajusté moyen entre graines ; étiquettes = information mutuelle normalisée.

| regard | méthode | stabilité | artiste | style | genre | durée |
|---|---|---|---|---|---|---|
| forme | e-means | 0,522 | 0,379 | 0,276 | 0,386 | 5 s |
| forme | Leiden | **0,645** | **0,400** | 0,277 | 0,390 | 40 s |
| sujet | e-means | 0,573 | 0,508 | 0,374 | 0,409 | 7 s |
| sujet | Leiden | **0,675** | 0,504 | 0,364 | 0,404 | 39 s |
| touche | e-means | 0,423 | 0,360 | 0,225 | 0,243 | 8 s |
| touche | Leiden | **0,528** | **0,437** | **0,266** | 0,263 | 41 s |
| couleur | e-means | **0,423** | 0,197 | 0,086 | 0,084 | 2 s |
| couleur | Leiden | 0,355 | 0,198 | 0,085 | 0,083 | 22 s |

Lecture : Leiden est nettement plus stable pour la forme, le sujet et la touche (deux calculs
donnent des groupes plus semblables), aussi bon ou meilleur pour les étiquettes, surtout
pour la touche (artiste : 0,36 → 0,44). La couleur fait exception : pas de communautés
nettes dans un histogramme de palette, e-means y reste plus stable. Les tailles de groupes
sont plus inégales (26 à 2 036 œuvres pour la forme, contre 140 à 1 190), ce qui suit le
corpus au lieu de l'égaliser. Sur les paires, les écarts sont dans le bruit (11 paires
annotées seulement) : à refaire avec les paires validées de l'étape 0.12.

Décision : le critère de la feuille de route est rempli pour la forme, la touche et le sujet,
pas pour la couleur. Les groupes Leiden sont disponibles pour chaque regard ; les groupes
**nommés** de l'Atlas restent ceux d'e-means tant que les noms, le panneau des groupes et
les étiquettes à vérifier n'ont pas été portés sur Leiden (étape suivante).

## 16. Désaccords entre regards et relecture des paires (16/11/2026)

`pixplot disagreements` cherche, pour chaque couple de regards, les paires d'œuvres très
proches selon l'un (rang ≤ 5 parmi les voisines) et lointaines selon l'autre (centile
< 0,35, estimé sur un échantillon fixe de 2 048 œuvres). Une œuvre ne peut apparaître que
deux fois par liste, sinon quelques images « carrefour » la rempliraient ; 300 paires sont
gardées par couple. Dans l'Atlas : bouton **Désaccords** (touche D).

Sur WikiArt 81k, le nombre de paires candidates dit à quel point deux regards s'accordent :
forme et sujet presque toujours (321 paires proches selon la forme mais loin selon le sujet,
87 dans l'autre sens), la touche un peu moins (≈ 2 000 à 3 700), la couleur très peu
(18 000 à 52 000 : une même composition peut avoir n'importe quelle palette). Exemples :
proches par le sujet, loin par la forme, la *Chanel n° 5* et les *Coca-Cola* de Warhol
(images de produits) ; proches par la forme, loin par le sujet, des toiles pointillistes de
sujets différents (la facture domine la forme).

Le bouton **À vérifier** a désormais deux onglets : les étiquettes contredites par les
voisines et les **paires de référence** proposées, à valider ou rejeter d'un clic (avec
« Comparer » pour les regarder côte à côte). Seules les paires validées comptent dans
`pixplot pairs bench`. Le critère de l'étape 0.12 (≈ 100 paires validées couvrant les huit
types) dépend de cette relecture, qui revient à l'historien.

## 17. Relecture rapide des paires, façon Anki (16/11/2026)

Relire une liste de paires carte par carte était trop lent. La **relecture rapide** (touche R
dans l'Atlas, ou le bouton de l'onglet « Paires de référence ») montre une paire à la fois,
en grand, et chaque décision tient en une touche :

| touche | effet |
|---|---|
| Entrée | valider avec la sorte de ressemblance proposée |
| 1 à 7 | valider comme : même sujet, même composition, même main, même facture, même motif, même palette, filiation |
| R | rejeter (paire proposée) ou « pas de lien » (candidate) |
| Espace | passer |
| Z | annuler la dernière décision |
| Échap | quitter |

La file commence par les paires proposées, puis enchaîne des **candidates** tirées des
désaccords entre regards, en alternant les couples de regards ; la sorte de ressemblance
proposée par défaut dépend du regard qui rapproche (forme → même composition, sujet →
même sujet, touche → même facture, couleur → même palette). Une candidate validée devient
une paire annotée (source « relecture : désaccord forme > sujet ») ; une candidate écartée est
notée dans `bench/review_log.csv` et ne revient plus. En haut : la progression vers les 100
paires validées et le compte par sorte, pour voir lesquelles manquent.
