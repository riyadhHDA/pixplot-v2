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
- **Serveur MCP** (`pixplot mcp`, stdio, SDK officiel `mcp` 2.x) : 16 outils —
  `corpus_overview`, `search_by_text`, `similar_artworks` (paramètre `space`),
  `search_detail`, `search_zones`, `get_artwork`, `view_artwork`, `view_detail`, `compare_artworks`, `why_similar`,
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
├── web/                   ⑥ Atlas : index.html, atlas-*.js, atlas.css, vendor/deck.gl
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

## 18. Premier banc d'essai sur 104 paires validées (16/11/2026)

104 paires validées par l'historien (et 1 rejetée, 23 candidates écartées) : 36 « même sujet »,
26 « même palette », 16 « même facture », 14 « même composition », 9 filiations, 2 « même motif »,
1 « même main ». 10 viennent de Honour et Fleming ou de filiations connues, 94 de la relecture
rapide des désaccords entre regards.

**Un biais à corriger.** Une paire tirée d'un désaccord a été choisie parce qu'un regard la
rapprochait et qu'un autre l'éloignait : ces deux regards ont gagné ou perdu d'avance. On ne
mesure donc, pour ces paires, que les deux regards qui n'ont pas servi à les choisir
(« regards neutres »). Centile moyen de l'œuvre jumelle (0,5 = hasard, 1 = la plus proche) :

| sorte de ressemblance | forme | sujet | couleur | touche |
|---|---|---|---|---|
| même sujet, autre composition | 0,950 | **0,966** | 0,369 | 0,847 |
| même composition, autre sujet | 0,675 (3) | **0,992** | 0,537 | 0,887 |
| autres artistes, facture comparable | 0,830 | 0,745 | 0,626 | **0,886** (3) |
| même palette, autres traditions | 0,539 | 0,390 | **0,719** | 0,570 |
| filiation (paires du livre, sans biais) | 0,993 | **0,997** | 0,626 | 0,890 |

Entre parenthèses : moins de 5 paires. Chaque regard gagne sur la sorte de ressemblance qu'il
est censé voir, sauf « même composition », où le sujet l'emporte : SigLIP 2 décrit aussi la
mise en page (« un temple sur une place »), et trop peu de paires mesurent la forme sans biais.
La couleur est sous le hasard pour « même sujet » : deux traitements d'un même thème changent
de palette.

**Leiden contre e-means, sur les paires** (part des paires validées rangées dans le même
groupe, 142 groupes) : forme 24,0 % → **32,7 %**, sujet 16,3 % → **26,0 %**, touche 19,2 % →
**26,0 %**, couleur 11,5 % = 11,5 %. Cela confirme le § 15 : Leiden suit mieux les parentés que
l'historien reconnaît, sauf pour la couleur.

**Le critère de l'étape 0.12** (≈ 100 paires validées couvrant les huit sortes) est atteint en
nombre, pas en couverture : « même main » (1) et « même motif » (2) restent à étoffer, et il
faudrait plus de paires « même composition » hors désaccords pour juger la forme.

## 19. Chercher une zone avec des mots : TIPSv2 évalué, non retenu (16/11/2026)

Question : peut-on taper « une auréole » ou « le clocher au fond à gauche » et retrouver la
**zone** qui y répond, dans tout le corpus ? Banc d'essai `pixplot zonebench` sur la partie
test de [RichArt](https://huggingface.co/datasets/MihaiBogdanBindila/RichArt) (ICMR 2026,
CC BY-NC 4.0, usage local) : 709 tableaux, 1 243 objets décrits par les catalogues de musées,
2 174 cadres. Deux requêtes par objet : son nom court (« church tower ») et sa phrase de
catalogue (~35 mots). Trois méthodes : SigLIP 2 sur la zone découpée, TIPSv2 sur la zone
découpée, TIPSv2 « dense » (une passe sur le tableau entier, moyenne des vecteurs de zones de
14 px dans le cadre). TIPSv2 en deux tailles : B/14 (86 M de paramètres pour l'image) et
SO400m/14 (même taille que SigLIP 2).

**Retrouver la zone parmi les 2 174** (part des objets dont une zone sort en 1ʳᵉ position / dans
les 10 premières ; rang médian) :

| méthode | nom : R@1 | R@10 | rang | phrase : R@1 | R@10 | rang |
|---|---|---|---|---|---|---|
| **SigLIP 2, zone découpée** | **16,0 %** | **43,8 %** | **17** | **28,2 %** | **61,1 %** | **5** |
| TIPSv2 SO400m, zone découpée | 12,7 % | 36,8 % | 32 | 20,4 % | 47,9 % | 12 |
| TIPSv2 B/14, zone découpée | 11,6 % | 34,7 % | 37 | 15,1 % | 41,7 % | 19 |
| TIPSv2 SO400m, dense | 10,5 % | 31,4 % | 43 | 15,4 % | 41,0 % | 17 |
| TIPSv2 B/14, dense | 7,6 % | 25,7 % | 67 | 13,3 % | 38,6 % | 24 |

**Pointer la zone dans son tableau** (la zone de 14 px la plus proche de la requête est-elle
dans un cadre de l'objet ?) : TIPSv2 B/14 61,9 % (nom) et 56,6 % (phrase), SO400m 54,2 % et
50,2 %. Hasard (surface couverte par les cadres) : 34,2 % ; mais **désigner toujours le centre
du tableau** donne déjà 50,8 %. L'avantage de TIPSv2 est donc mince.

Décision : le critère de l'étape 0.13 (« nettement meilleur que SigLIP 2 sur les zones
découpées ») n'est pas rempli ; TIPSv2 n'est pas intégré à l'Atlas. L'encodeur reste dans le
code (`tipsv2_b14`, `tipsv2_so400m14`) pour que la mesure soit reproductible. La meilleure
méthode mesurée est **SigLIP 2 appliqué à des zones découpées** : c'est elle qu'il faudrait
indexer pour chercher des zones par des mots, au prix d'un calcul ≈ 20 fois plus long que les
vecteurs globaux (une vingtaine de zones par œuvre).

## 20. Couche critique : ce que voit chaque regard, ce qui manque au corpus (17/11/2026)

Deux lectures ont guidé cette étape. A. Wasielewski, *Computational Formalism* (MIT Press,
2023), appelle « formalisme computationnel » exactement ce que fait PixPlot : comparer des
œuvres en masse par leur apparence. Elle en pointe trois risques : le **biais perceptif** (le
modèle s'attache à des traits très fins — grain, contours, qualité de la reproduction — que
l'historien ne regarde pas), les **catégories de style de WikiArt**, remplies par des bénévoles
et reprises sans examen, et le **canon occidental**, seul vraiment numérisé avec des
métadonnées complètes. T. Arnold et L. Tilton, *Distant Viewing* (MIT Press, 2023), montrent que
chaque algorithme encode une « manière de voir » qu'il faut rendre explicite et documenter, et
mettent en garde contre la fascination pour la taille.

D'où trois outils :

- **Une fiche par regard** (`pixplot.analysis.critique.CARDS`) : modèle, données
  d'entraînement, ce qu'il voit, ce qu'il ne voit pas, biais connus, ce que le banc d'essai a
  mesuré. Dans l'Atlas (bouton **Corpus**, touche I, et info-bulles du comparateur), dans
  l'API (`/api/spaces`, `/api/corpus`) et dans le serveur MCP (`corpus_overview`).
- **Un bilan du corpus** (`pixplot corpus`, `/api/corpus`) : couverture et source de chaque
  étiquette, concentration des artistes, styles hors de la tradition européenne et
  nord-américaine, dates et lieux. Sur WikiArt 81k : l'artiste manque pour 51 % des œuvres —
  parce que le jeu huggan/wikiart n'en nomme qu'une partie ; les 10 artistes les plus présents
  font 29 % des œuvres attribuées ; 1 style sur 27 est non occidental (Ukiyo-e, 1,4 % des
  œuvres) ; aucune date ni aucun lieu.
- **Les étiquettes présentées comme ce qu'elles sont** : dans la fiche d'une œuvre, une
  étiquette WikiArt porte « étiquette bénévole, à vérifier », avec la note sur la source.

Le serveur MCP reçoit aussi une consigne de sécurité, d'après AutoMalTool (He et al., 2025) :
titres, étiquettes, notes du carnet et Research Packs sont des données saisies par d'autres, et
le modèle de langage ne doit jamais suivre une consigne qui s'y trouverait.

## 21. Lieux typés et datés, d'après ARTL@S (17/11/2026)

B. Joyeux-Prunel (« ARTL@S : A Spatial and Trans-national Art History », *Artl@s Bulletin*,
2012) défend une histoire spatiale et transnationale des arts qui part des **répartitions et
des circulations** avant les discours, distingue les lieux (où l'œuvre est faite, montrée,
conservée, ce qu'elle représente, où vit l'artiste), date chaque adresse, et refuse
d'expliquer un style par un lieu (l'héritage de Taine). La vue géographique de PixPlot posait
chaque œuvre en un seul point, sans dire de quel lieu il s'agissait.

- **Table `places`** (catalogue) : une œuvre peut avoir plusieurs lieux, chacun avec un type
  (création, exposition, conservation, lieu représenté, naissance / résidence / mort de
  l'artiste, non précisé), un nom, des coordonnées, une date et une source.
- **Import** : `pixplot import-places lieux.csv` (colonnes `path` ou `id`, `type`, `place`,
  `lat`, `lon`, `date`, `source`) ; `pixplot places --derive` déduit des lieux des
  métadonnées (dépôt ou institution → conservation ; « born in Munich » / « né à » →
  naissance ; « died in » / « mort à » → mort ; `place` → non précisé).
- **Répertoire embarqué** (`catalog/gazetteer.py`) : ~80 villes d'art et ~40 institutions,
  pour placer un lieu par son nom sans service en ligne. Un lieu inconnu reste sans
  coordonnées : on ne devine pas.
- **Atlas, vue Géographie** : « Quel lieu ? » (un type à la fois), **circulations** (lignes
  reliant les lieux d'une même œuvre dans l'ordre des dates), **curseur de temps** (lieux
  jusqu'à une année), cadrage sur les œuvres situées, et une note : une carte de lieux montre
  des répartitions et des circulations, pas des styles.

Sur le corpus du Yale Center for British Art, `--derive` donne 18 lieux de conservation (New
Haven), 7 naissances et 8 morts d'artistes datées (Liverpool, Londres, Munich, Bathampton…) :
la carte montre déjà le trajet des œuvres britanniques vers une collection américaine.
L'import Paris Musées (en attente : leur site était hors service) fournira lieux de
conservation, dates et lieux représentés à grande échelle.

## 22. Index des zones SigLIP 2 : chercher un détail avec des mots (17/11/2026)

Suite logique du § 19 : puisque SigLIP 2 appliqué à des **zones découpées** est la meilleure
méthode mesurée sur RichArt, `pixplot zones` découpe chaque œuvre selon des grilles 2 × 2 et
4 × 4 (20 zones, un quart ou un seizième de l'œuvre), passe chaque zone dans SigLIP 2 et
indexe le tout.

- **Extraction** (GPU, reprenable, journal dans `<données>/zones.log`) : zones découpées dans
  les vignettes de 1 024 px, mises au format du modèle sans recadrage (letterbox), vecteurs
  gardés en float16 (`features/zones_*`, 3,7 Go pour 80 716 œuvres).
- **Index** (`index/textzones_*`) : PCA à 256 dimensions, index FAISS en float16. Les vecteurs
  projetés ne sont **pas renormalisés** : le produit scalaire avec une phrase vaut alors
  q·v − q·moyenne, dont le second terme est le même pour toutes les zones, ce qui préserve le
  classement. Les meilleures candidates sont ensuite **reclassées exactement** avec leurs
  vecteurs d'origine : sur le corpus d'essai, les cinq premiers résultats sont identiques à
  ceux d'un calcul complet, pour toutes les requêtes testées.
- **Atlas** : mode de recherche **« Zone décrite »** (« une auréole », « un crâne », « une
  main qui bénit ») ; chaque résultat montre la zone découpée. API `/api/search/zones`, outil
  MCP `search_zones` (15 outils).
- Les runs de zones sont exclus des listes de vecteurs (`list_runs`) : ce ne sont pas des
  regards, et la recherche par description ne doit jamais les prendre pour des vecteurs
  d'œuvres entières (bug trouvé en test et corrigé).

**Sur WikiArt 81k** (17/11/2026) : 1 614 320 zones pour 80 716 œuvres, calculées d'une traite
en 6 h 21 sur la RX 7900 GRE (71 zones par seconde, sans erreur) ; la PCA garde 92 % de la
variance ; l'index pèse 818 Mo (les vecteurs d'origine 3,5 Go). Une recherche répond en
0,5 s. Essais : « a halo around a saint's head » → six auréoles, dont des auréoles
rayonnantes ; « a skull » → six crânes, peints ou gravés ; « a hand holding a letter » → six
mains tenant une lettre ; « a sailing ship » → des voiliers. Une location de GPU (H100) aurait
ramené le calcul à 30–45 min, mais avec l'envoi des images et la mise en route, le gain réel
aurait été de l'ordre de 2 à 3 h de bout en bout, au prix d'images sorties de la machine.

## 23. Nommer les groupes avec Iconclass (17/11/2026)

[Iconclass](https://iconclass.org) (H. van de Waal, 1972-1985) est la classification
iconographique des musées : environ 40 000 notions codées, de « 25H paysage » à « 73A5
l'Annonciation », avec des libellés français. Les données sont sous licence CC0
(`pixplot iconclass --fetch`, dans `data/iconclass/`, non versionné).

- **Méthode** (comme le § 12, Iconclass à la place de notre lexique) : chaque notion est
  décrite à SigLIP 2 par son libellé anglais nettoyé (« a painting of the Annunciation ») ;
  le centre de chaque groupe est comparé aux notions ; parmi les 10 plus proches, on garde
  les 3 qui distinguent le plus ce groupe des autres (écart à la moyenne des groupes, en
  écarts-types : z).
- **Notions retenues** (17 126 sur 40 712) : pas de « clés » (lettres doublées, « 31AA »
  = version féminine), pas plus de 7 caractères, noms propres seulement pour les saints et
  les espèces, pas de littérature (81-83), Bible et mythologie limitées à 4 caractères
  (« 73A5 » oui, l'épisode de détail non), pas d'allégories de Ripa, pas d'entrée sans nom
  français.
- **Confiance** : z ≥ 4 « sûr », 3 à 4 « possible », en dessous rien n'est affiché. Seuils
  relus sur WikiArt 81k : au-dessus de 4, le nom est presque toujours juste ; en dessous de
  3, Iconclass n'a pas de mot pour le groupe (portraits, abstractions) et en force un
  (« journaliste », « test graphologique »).
- **Atlas** : sous le nom du groupe, la ou les notions Iconclass avec leur code, en lien
  vers iconclass.org (bordure pleine : sûr ; pointillée : possible). API : champ
  `iconclass` des groupes ; MCP : `corpus_overview` et `get_group`.

**Sur WikiArt 81k** : 142 groupes, 37 « sûr », 47 « possible », 58 sans notion affichée ;
encodage des notions et nommage en 76 s. Iconclass est **complémentaire** du lexique : plus
précis sur le sujet (« 47D31 moulin à vent », « 25G41 nénuphar », « 25H154 clairière »,
« 26C32 tempête sur mer », « 42B742 mère et enfant », « 11D356 le Christ crucifié »),
muet sur la manière, le genre du portrait et l'abstraction, que le lexique nomme mieux.
Erreurs typiques restantes : lutteurs de Hokusai → « 43C393 jiu-jitsu, judo », saints
précis sur des retables (« Philippe Neri »).

**Relecture par l'historien** (19/11/2026, `bench/wikiart81k_iconclass_review.csv`) : les 84 groupes qui ont
un nom Iconclass ont été jugés, nom actuel (A) contre proposition
Iconclass (B), sur six œuvres typiques de chaque groupe ; 83 réponses.

| | B Iconclass plus juste | équivalents | A actuel plus juste | les deux faux |
|---|---|---|---|---|
| tous (83) | **39 (47 %)** | 17 | 24 (29 %) | 3 |
| « sûr » (37) | **21 (57 %)** | 4 | 12 (32 %) | 0 |
| « possible » (46) | **18 (39 %)** | 13 | 12 (26 %) | 3 |

Sur les avis tranchés, Iconclass l'emporte 39 contre 24 (test du signe unilatéral : p = 0,04).
**Critère de la feuille de route rempli** : les noms Iconclass sont jugés plus justes. Ils s'ajoutent au
nom actuel sans le remplacer : le lexique reste meilleur dans un groupe sur trois (souvent la manière,
le portrait, l'abstraction), et le seuil « sûr » se confirme comme le plus fiable.

## 24. La composition : PE-Spatial évalué, non retenu (18/11/2026)

Étape 0.15. Question : un modèle « spatial » ou une comparaison case à case retrouve-t-il mieux
qu'un regard existant une œuvre qui reprend la **disposition** d'une autre (même composition,
sujet différent) ?

- **Candidats.** [PE-Spatial B/16](https://huggingface.co/timm/vit_pe_spatial_base_patch16_512.fb)
  (Meta, 2025, Apache 2.0, par `timm`), vecteurs calculés pour les 80 716 œuvres (68 images/s, 1,4 Go
  de mémoire graphique, environ 20 min) : vecteur global = moyenne des patchs. Et, pour PE-Spatial et
  pour DINOv3, une **disposition 4 × 4** : l'œuvre en 16 cases, chaque case comparée à la case au
  même endroit dans l'autre œuvre (moyenne des 16 cosinus). STELLAR (Microsoft) n'a pas été essayé :
  entraîné sur ImageNet seul, il n'avait pas d'avantage attendu sur DINOv3.
- **Mesure.** `pixplot composition` : les paires validées par l'utilisateur (§ 18), rangs exacts sur
  tout le corpus, dans les deux sens, comme `pixplot pairs bench`.
- **Relecture par Codex** (OpenAI, premier travail à deux assistants) : découpage des cases, calcul
  des rangs et alignement des œuvres vérifiés ; deux variantes plus équitables proposées et mesurées :
  vecteur global **sur l'œuvre seule** (sans les bandes ajoutées pour la mettre au carré) et
  disposition **sur les seules cases remplies dans les deux œuvres** (deux formats différents ne sont
  plus pénalisés).

| « Même composition, sujet différent » (14 paires, 28 recherches) | dans les 10 premières | dans les 100 premières | rang médian |
|---|---|---|---|
| **Forme (DINOv3), regard actuel** | **54 %** | **71 %** | **8** |
| Forme, œuvre seule | 18 % | 46 % | 203 |
| Forme, disposition 4 × 4 (cases communes) | 0 % | 32 % | 332 |
| PE-Spatial, disposition 4 × 4 (cases communes) | 7 % | 29 % | 286 |
| PE-Spatial, global | 4 % | 29 % | 960 |
| PE-Spatial, global sur l'œuvre seule | 11 % | 25 % | 1 406 |
| Sujet (SigLIP 2) | 21 % | 29 % | 814 |

**Conclusion : PE-Spatial n'est pas retenu, la disposition 4 × 4 non plus.** Le regard global de
DINOv3 reste nettement le meilleur pour retrouver une même composition. La comparaison case à case
échoue parce qu'une composition reprise est rarement au même endroit : décalée, recadrée, dans un autre
format, elle ne tombe plus dans les mêmes cases. Seule nuance : la disposition 4 × 4 de DINOv3 rate
moins souvent de très loin (centile 0,958 contre 0,928), sans jamais placer l'œuvre jumelle en tête.
Sur les filiations attestées (18 recherches), toutes les variantes se valent à quelques rangs près ;
l'échantillon est trop petit pour les départager.

Les vecteurs PE-Spatial restent sur le disque pour les bancs d'essai (`features/pe_spatial_b16_*`),
mais l'Atlas et le serveur MCP ne les proposent pas comme regard (`NOT_KEPT` dans `api/spaces.py`).
Limite : 14 paires « même composition » ; une conclusion plus large demanderait plus de paires
validées, et une grille calée sur l'œuvre plutôt que sur le carré (nouveau calcul).

## 25. « Pourquoi ces deux œuvres se ressemblent ? » (19/11/2026)

Dans le comparateur, le bouton **« Pourquoi ? »** d'une paire dessine sur les deux images les zones
qui se répondent le plus, avec le même numéro et la même couleur, et une légende chiffrée. Le but :
qu'une proximité calculée devienne discutable, en montrant sur quoi le regard s'appuie.

- **Calcul** (`pixplot/analysis/correspondences.py`, API `/api/correspond`) : pour un regard qui
  garde des vecteurs par zone (aujourd'hui la forme, DINOv3), chaque œuvre est découpée en 16 cases
  (4 × 4) ; on calcule les 16 × 16 cosinus entre les cases des deux œuvres et on garde les
  **correspondances mutuelles** (chacune est la plus proche de l'autre). Elles sont classées par ce
  qui les distingue : le cosinus moins la ressemblance moyenne des deux cases avec toutes les autres,
  pour ne pas mettre en tête deux fonds quelconques. Les cases qui tombent dans les bandes ajoutées
  pour mettre l'œuvre au carré sont exclues ; les cadres sont ramenés à l'image.
- **Coût** : nul à l'avance, quelques millisecondes à la demande (les vecteurs par zone existent déjà).
- **Exemple** (paire validée « même composition ») : Raphaël, *Mariage de la Vierge*, et Pérugin,
  *Remise des clés* : les zones retenues sont le temple central et les groupes de personnages au
  premier plan, dans les deux œuvres. Sur la copie de Rubens d'après l'*Enlèvement d'Europe* de
  Titien, les quatre zones sont aux mêmes endroits dans les deux tableaux.
- **Limites** : une grille fixe, calée sur le carré et non sur l'œuvre ; une case d'un format très
  large couvre une bande haute de l'image. Le regard compare des formes : c'est à l'historien de dire
  si les zones partagent un motif, une pose, une composition, ou seulement un fond semblable.

## 26. Trois lectures intégrées : axes conceptuels, mesures visuelles et couche critique (19/11/2026)

Trois lectures récentes ont été intégrées directement dans le code, l'Atlas et le serveur MCP :

1. **Axes conceptuels 2D, d'après *2D CLIP* (L. Impett et F. Offert, « There Is a Digital Art
   History », *Visual Resources*, 38:2, 2024).** Les auteurs montrent qu'un modèle multimodal porte
   un « imaginaire vectoriel » (*vector imaginary*) et qu'en lisant un corpus à travers le modèle, on
   lit toujours aussi le modèle à travers le corpus. L'Atlas propose désormais une vue **Axes
   conceptuels (2 mots)** (`/api/layout/concepts`, outil MCP `probe_concepts`) qui projette tout le
   corpus sur deux requêtes textuelles SigLIP 2 (normalisées par centiles p1–p99), avec la diagonale
   `X = Y` et les œuvres qui s'en écartent le plus.
   - **Mesure sur WikiArt 81k (80 716 œuvres)** : **582 à 592 ms** par paire de mots à chaud (après
     le chargement initial de SigLIP 2), sans précalcul.
   - **Exemples révélateurs** : `naked` / `nude` donne une corrélation forte (`r = 0,87`), avec des
     écarts à la diagonale nets comme dans la fig. 8 de l'article ; `linéaire` / `pictural` (axes de
     Wölfflin, repris par Stork § 9.1) donne `r = 0,16` et sépare nettement le Minimalisme géométrique
     du Romantisme/Expressionnisme atmosphérique (Aïvazovski) ; `sacré` / `profane` (`r = 0,41`)
     illustre la thèse même d'Impett et Offert : les œuvres tirées le plus fortement vers « sacré »
     loin de « profane » sont des vues parisiennes d'Édouard Cortès — parce que « sacré » active
     « Sacré-Cœur » dans l'imaginaire vectoriel du web.
2. **Mesures visuelles explicites, sans modèle de neurones, d'après D. G. Stork (*Pixels &
   Paintings: Foundations of Computer-assisted Connoisseurship*, Wiley, 2024).** Le module
   `pixplot/analysis/connoisseur.py` (`/api/artwork/{id}/measures`, bloc pliable **Mesures visuelles**
   dans la fiche d'œuvre, outil MCP `measure_artwork`) calcule à la demande : le barycentre de
   luminance et de saturation ainsi que la dispersion des barycentres de sous-fenêtres (§ 9.3, Park
   2019), la symétrie gauche-droite (§ 9.3.1), la dynamique tonale (§ 1.5.3), et l'entropie
   chromatique `H(C)` avec la première coupe horizontale ou verticale maximisant le gain
   d'information (§ 9.5.1, alg. 8, Lee et al., PNAS 2020).
   - **Mesure sur WikiArt 81k** : **14,5 ms** par œuvre en moyenne sur 100 vignettes 256 px (100 %
     CPU). Une première version à quantification adaptative (`MEDIANCUT`, 16 couleurs) écrasait
     l'entropie près du maximum (~3,9–4,0 bits) ; remplacée par une grille chromatique fixe
     4 × 4 × 4 (64 teintes, max 6 bits), l'entropie s'étale de **0,07 à 3,52 bits** (médiane 1,56) :
     0,02 bit pour une esquisse monochrome de Dürer (`#101`) contre 3,31 et 2,80 bits pour la paire
     Rubens / Titien (`#64269` / `#67405`), dont les barycentres coïncident (`[0,52 ; 0,44]` vs
     `[0,53 ; 0,47]`).
   - **Limites** : ces chiffres décrivent la *reproduction numérique* (résolution, vernis, balance
     des blancs) et ne portent aucun jugement normatif (« équilibré » ne veut pas dire « meilleur »).
3. **Couche critique enrichie, d'après J.-L. Giavitto et P. Saint-Germier (dir.), *L'art au temps de
   l'IA* (Centre Pompidou, 2025).** La fiche **Corpus** (`critique.PRINCIPLES`, `/api/corpus`,
   `corpus_overview` et consignes MCP) intègre trois garde-fous issus de l'ouvrage : une distance
   latente n'a de sens que *relative* au corpus et ne remplace pas l'acte performatif d'expertise
   humaine (S. Bureau et G. Doras) ; les modèles texte-image réduisent le visible au « dicible »
   (M. Lista, d'après A. Somaini et H. Steyerl) ; la numérisation porte ses conditions matérielles
   (F. Ebner et O. Frydryszak-Rétat).

## 27. Détection de copies : SSCD évalué, non retenu comme regard par défaut (19/11/2026)

Question : un modèle spécialisé en **détection de copies** (SSCD) mérite-t-il de devenir un
cinquième regard pour retrouver les filiations attestées (copies, répliques, gravures d'après) ?

- **Candidat et licence.** [SSCD](https://github.com/facebookresearch/sscd-copy-detection) (*A
  Self-Supervised Descriptor for Image Copy Detection*, Pizzi et al., Meta, CVPR 2022, **licence
  MIT**), variante `sscd_disc_large` (ResNeXt-101 32×4d, 1 024 dimensions, entraînée sur DISC avec
  augmentations avancées et mixup ; poids TorchScript autonomes stockés localement dans
  `data/wikiart81k/models/`, hors git). Entrée : œuvre entière en *letterbox* à 320 px (taille carrée
  recommandée par le dépôt pour l'inférence GPU par lots), normalisation ImageNet.
- **Extraction.** `pixplot/encoders/sscd.py`, calculée sur les 80 716 œuvres de WikiArt 81k
  (`features/sscd_disc_large_20261119-184816`) : **4 min 41 s**, **274,9 images/s**, **926 MiB** de
  mémoire graphique (RX 7900 GRE, FP16), **0 échec**.
- **Mesure.** `pixplot pairs bench --spaces forme,sujet,couleur,touche,copie` sur les **104 paires
  annotées validées** par l'historien (`bench/wikiart81k_pairs.csv`, 208 requêtes, rangs exacts dans
  les deux sens). Une variante **centrée** (soustraction de la moyenne du corpus puis normalisation
  L2, recommandée par le dépôt SSCD) a également été mesurée en mémoire.

| « Filiation attestée (copie, citation, modèle) » (9 paires, 18 recherches) | R@10 | R@100 | rang médian | centile |
|---|---|---|---|---|
| **Sujet (SigLIP 2)** | **38,9 %** | **66,7 %** | **25** | **0,997** |
| **Forme (DINOv3)** | **38,9 %** | **66,7 %** | **26** | **0,993** |
| Copie (SSCD brut) | 33,3 % | 44,4 % | 216 | 0,902 |
| *Copie (SSCD centré, essai en mémoire)* | *33,3 %* | *50,0 %* | *108* | *0,904* |
| Touche (DINOv3, couche 6) | 16,7 % | 27,8 % | 578 | 0,902 |
| Couleur (CIELAB) | 0,0 % | 0,0 % | 17 656 | 0,557 |

Sur les autres catégories annotées validées, SSCD reste nettement en retrait des regards spécialisés :

| Catégorie annotée validée (n recherches) | SSCD R@10 | SSCD rang méd. | Meilleur regard actuel (R@10 · rang méd.) |
|---|---|---|---|
| Même sujet, composition différente (72) | 4,2 % | 27 374 | Sujet (37,5 % · 30) |
| Même composition, sujet différent (28) | 7,1 % | 13 736 | Forme (53,6 % · 8) |
| Artistes différents, facture comparable (32) | 0,0 % | 6 952 | Touche (31,2 % · 136) |
| Même palette, traditions différentes (52) | 0,0 % | 32 982 | Couleur (50,0 % · 10) |
| Même motif iconographique, époque différente (4) | 0,0 % | 5 612 | Sujet (50,0 % · 26) |
| Même artiste, facture différente (2) | 0,0 % | 53 312 | Couleur (100,0 % · 2) |

Sur les 600 recherches « témoin » (métadonnées disjointes), SSCD obtient un rang médian de 40 528
(centile 0,490, quasi-hasard parfait), effet attendu de sa régularisation d'entropie différentielle.

**Lecture paire par paire des 9 filiations.** SSCD classe en tête les copies très fidèles qui
conservent la géométrie d'ensemble : Van Gogh / Millet (*Le Semeur*, rangs 1 et 1), Raphaël /
Pérugin (*Mariage de la Vierge*, rangs 1 et 1), Manet / Titien (*Olympia* ← *Vénus d'Urbin*,
rangs 6 et 3 ; centré 1 et 3 — seul cas où SSCD devance nettement Forme [4, 23] et Sujet [4, 58]).
Hors banc, sur la paire proposée Rubens / Titien (*L'Enlèvement d'Europe*), SSCD donne aussi (1, 1),
mais Forme et Sujet y sont déjà à (1, 1). En revanche, dès que la filiation passe par une
réinterprétation libre, une inversion, un fragment ou un changement de technique — Manet / Goya
(110, 983), Manet / Giorgione-Titien (323, 461), Monet / Manet (803, 732), Picasso / El Greco
(13 406, 21 382), Van Gogh d'après l'eau-forte de Rembrandt (60 102, 44 044) — SSCD repousse le
modèle très loin : son entraînement est fait pour séparer tout ce qui n'est pas quasi-identique.

**Conclusion : SSCD n'est pas retenu comme cinquième regard par défaut.** Les regards Forme (DINOv3)
et Sujet (SigLIP 2) retrouvent déjà les copies fidèles et résistent beaucoup mieux aux reprises
artistiques. Les vecteurs restent sur disque (`features/sscd_disc_large_*`) pour les bancs d'essai
(`pixplot pairs bench --spaces …,copie`), mais l'Atlas et le serveur MCP ne proposent pas SSCD par
défaut (`NOT_KEPT` dans `pixplot/api/spaces.py`).

**Limites et piste utile.** L'échantillon de filiations validées reste petit (9 paires, mêlant copies
directes et réinterprétations libres ; pas encore de corpus dédié de gravures de reproduction).
En revanche, un sondage sur 2 000 œuvres aléatoires de WikiArt 81k montre que **2,6 %** (52/2 000)
ont une autre œuvre à cosinus SSCD ≥ 0,75 (dont des quasi-doublons JPEG réencodés sous deux
étiquettes différentes qui échappent au hachage SHA-256 d'`ingest`) : SSCD pourrait donc servir à
l'avenir d'outil de **dédoublonnage perceptuel** lors de l'ingestion, plutôt que de regard
d'exploration historique.

## 28. Composition par la profondeur : Depth Anything V2 évalué, non retenu (19/11/2026)

Question (suite du § 24) : après l'échec de PE-Spatial et des dispositions 4 × 4 face au regard
Forme (DINOv3) sur « même composition, sujet différent », l'agencement des plans en **profondeur**
(premier plan, plans intermédiaires, fond) apporte-t-il un signal complémentaire que Forme ne voit pas ?

- **Candidat et licence.** [Depth Anything V2 Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf)
  (Yang et al., NeurIPS 2024, backbone DINOv2 ViT-S/14 + tête DPT, chargé via `transformers`,
  **licence Apache 2.0** vérifiée sur la fiche Hugging Face). Les variantes Base et Large sont sous
  licence CC BY-NC 4.0 et ont été écartées par principe. Poids stockés dans le cache Hugging Face
  local, jamais dans git.
- **Descripteur (`pixplot/encoders/depth.py`).** L'œuvre entière est mise au carré par bandes
  neutres (*letterbox*, normalisation ImageNet) à la résolution native de 518 px (37 × 14). La carte
  de profondeur relative prédite (disparité affine-invariante : valeurs plus grandes pour les plans
  proches) est **recadrée sur la seule boîte de l'œuvre** — les bandes du *letterbox* sont totalement
  ignorées, ce qui répond aussi à la limite relevée au § 24 d'une grille calée sur le carré plutôt
  que sur l'œuvre. Elle est ensuite moyennée sur une **grille 8 × 8** (64 valeurs), centrée et
  normalisée L2 par œuvre (z-score de norme 1) : l'empreinte est strictement invariante à toute
  transformation affine positive $a \cdot d + b$ ($a > 0$), et le cosinus entre deux œuvres vaut
  exactement la corrélation de Pearson entre leurs grilles de profondeur 8 × 8. Le choix du z-score
  plutôt que des rangs a été préféré par simplicité et fidélité à la perte d'entraînement du modèle ;
  les deux variantes (ainsi que le centrage sur le corpus) ont été mesurées.
- **Extraction.** Calculée sur les 80 716 œuvres de WikiArt 81k
  (`features/depth_anything_v2_small_20261119-191351`, journal `data/wikiart81k/depth.log`) :
  **14 min 3 s**, **95,7 images/s**, **3 082 MiB** de mémoire graphique (RX 7900 GRE, FP16, lots de
  32), **0 échec** et 0 carte plate dégénérée.
- **Mesure.** `pixplot composition` et `pixplot pairs bench --spaces forme,sujet,couleur,touche,profondeur`
  sur les **104 paires annotées validées** (208 requêtes, rangs exacts sur 80 716 œuvres). Trois
  variantes en mémoire ont aussi été testées : **centrée sur le corpus** (soustraction de la grille
  moyenne du corpus puis renormalisation), **par rangs** (corrélation de Spearman sur les 64 cases)
  et **par rangs centrée**.

| « Même composition, sujet différent » (14 paires, 28 recherches) | R@10 | R@100 | rang médian | centile |
|---|---|---|---|---|
| **Forme (DINOv3), regard actuel** | **53,6 %** | **71,4 %** | **8** | **0,928** |
| Forme, disposition 4 × 4 (cases communes, § 24) | 0,0 % | 32,1 % | 332 | 0,958 |
| PE-Spatial, disposition 4 × 4 (cases communes, § 24) | 7,1 % | 28,6 % | 286 | 0,878 |
| Sujet (SigLIP 2) | 21,4 % | 28,6 % | 814 | 0,738 |
| Touche (DINOv3, couche 6) | 10,7 % | 32,1 % | 1 017 | 0,857 |
| **Profondeur (Depth Anything V2 Small, 8 × 8 brut)** | **3,6 %** | **7,1 %** | **13 754** | **0,677** |
| *Profondeur centrée sur le corpus (essai en mémoire)* | *3,6 %* | *7,1 %* | *6 874* | *0,682* |
| *Profondeur par rangs / Spearman (essai en mémoire)* | *3,6 %* | *3,6 %* | *13 424* | *0,640* |

Sur toutes les autres catégories annotées validées, la profondeur reste également très loin des
regards spécialisés (et proche du hasard sur les paires de métadonnées : centile 0,544–0,552,
témoin 0,479) :

| Catégorie annotée validée (n recherches) | Profondeur R@10 | Profondeur rang méd. (centré) | Meilleur regard actuel (R@10 · rang méd.) |
|---|---|---|---|
| Filiation attestée (18) | 11,1 % | 14 889 (11 784) | Sujet (38,9 % · 25) / Forme (38,9 % · 26) |
| Même sujet, composition différente (72) | 2,8 % | 32 444 (32 471) | Sujet (37,5 % · 30) |
| Artistes différents, facture comparable (32) | 0,0 % | 28 682 (28 509) | Touche (31,2 % · 136) |
| Même palette, traditions différentes (52) | 0,0 % | 51 211 (43 698) | Couleur (50,0 % · 10) |
| Même motif, époque différente (4) | 0,0 % | 41 282 (—) | Sujet (50,0 % · 26) |
| Même artiste, facture différente (2) | 0,0 % | 30 958 (—) | Couleur (100,0 % · 2) |

**Pourquoi la profondeur seule échoue : deux effets mesurés.**
1. *Un gradient vertical universel domine le corpus.* Sur les 80 716 œuvres, la grille moyenne 8 × 8
   croît strictement du haut (−0,108 : ciel, mur, fond) vers le bas (+0,181 : sol, premier plan).
   Deux tableaux pris au hasard ont déjà un cosinus brut moyen de **0,539** (contre 0,175 pour
   Forme). Retirer cette moyenne ramène le cosinus aléatoire à **0,016** et divise par deux le rang
   médian sur « même composition » (13 754 → 6 874 ; filiation : 14 889 → 11 784, centile 0,809),
   sans pour autant faire émerger les paires dans les 100 premières. Les rangs (Spearman) font
   légèrement moins bien que le z-score (centile 0,640 contre 0,677).
2. *Un modèle 3D entraîné sur la photographie se trompe sur l'art non perspectif.* La lecture paire
   par paire confirme que la profondeur fonctionne bien sur les compositions figuratives à plans
   nets : Van Gogh / Millet (*Le Semeur*, filiation : rangs **3 et 1**, cosinus 0,948), la paire
   proposée Rubens / Titien (*L'Enlèvement d'Europe* : rangs **1 et 1**, cosinus 0,987), Pérugin
   (*Remise des clés* ↔ *Mariage de la Vierge* : rangs 1 285 et **85** ; centré 433 et 86), ou
   Michel-Ange / Haute Renaissance (`24374 ↔ 54823` : rangs **7** et 6 183 ; centré 9 et 950). Mais
   sur les œuvres planes, décoratives ou modernes (Pop Art `65822 ↔ 71779` : rangs 68 987 et
   80 552 ; Chagall / Expressionnisme `22435 ↔ 60995` : 79 814 et 79 803 ; Expressionnisme / Pop Art
   `48392 ↔ 76646` : 75 807 et 64 679), le modèle invente des plans de profondeur à partir des
   contrastes tonaux et place la paire en toute fin de corpus. Même entre deux œuvres à perspective
   de formats différents — Raphaël (*Mariage de la Vierge*, retable haut) et Pérugin (*Remise des
   clés*, fresque large) — le décalage de la ligne d'horizon sur la grille 8 × 8 fait chuter la
   paire aux rangs 2 256 et 25 374 (Forme : 3 et 7).

**Combinaison Forme + profondeur (validation croisée sans triche).** Une somme pondérée des
similarités $S = (1 - \alpha)\, S_{\text{forme}} + \alpha\, S_{\text{profondeur}}$ (en cosinus bruts,
avec profondeur centrée, ou sur similarités normalisées par z-score par requête) a été testée en
choisissant $\alpha \in \{0 ; 0{,}05 ; \dots ; 0{,}5 ; 1\}$ sur une moitié des 14 paires
« même composition » et en mesurant sur l'autre moitié :

| Combinaison (14 paires « même composition », 28 requêtes) | R@10 | R@100 | rang médian | centile |
|---|---|---|---|---|
| **Forme seule ($\alpha = 0$)** | **53,6 %** | **71,4 %** | **8** | **0,9275** |
| CV 2 moitiés alternées (cosinus brut, $\alpha = 0{,}05 / 0{,}10$) | 42,9 % | 75,0 % | 26 | 0,9314 |
| CV 2 moitiés consécutives (cosinus brut, $\alpha = 0{,}10 / 0{,}10$) | 42,9 % | 71,4 % | 26 | 0,9334 |
| CV 2 moitiés alternées (z-score sim, prof. centrée, $\alpha = 0{,}05 / 0{,}40$) | 50,0 % | 64,3 % | 15 | 0,9283 |
| CV 200 tirages aléatoires 7/7 (cosinus brut, $\alpha$ méd. 0,10, opt. centile) | 42,1 % | — | 691 (moy.) | 0,9037 |
| CV 200 tirages aléatoires 7/7 (opt. R@10 puis médiane : $\alpha = 0$ dans 74 % des cas) | — | — | — | — |

Un léger poids de profondeur ($\alpha \approx 0{,}05\text{–}0{,}10$) remonte marginalement les deux
paires où Forme échoue très loin (`20355 ↔ 50955` Hokusai / Art Nouveau et `16620 ↔ 65443`
Bilibin / Réalisme), ce qui grappille +0,004 de centile sur les découpages fixes, **mais dégrade
nettement le haut du classement** (R@10 chute de 53,6 % à 42,9 % et le rang médian passe de 8 à
26) et **fait moins bien que Forme seule en moyenne sur 200 tirages 7/7** (centile 0,9037 contre
0,9275 ; dès qu'on optimise R@10/médiane, la validation croisée retient $\alpha = 0$ dans 74 % des
tirages). Le même constat vaut sur `filiation` (à $\alpha = 0{,}10$, R@10 recule de 38,9 % à
33,3 %).

**Conclusion : Depth Anything V2 n'est pas retenu, ni seul ni combiné à Forme.** Le regard Forme
(DINOv3) reste nettement le meilleur pour retrouver une composition partagée. Les vecteurs restent
sur disque (`features/depth_anything_v2_small_*`, 10 Mo) pour les bancs d'essai (`pixplot
composition`, `pixplot pairs bench --spaces …,profondeur`), mais le regard `"profondeur"` reste hors
de l'Atlas et du serveur MCP (`NOT_KEPT` dans `pixplot/api/spaces.py`).

**Limites.** L'échantillon « même composition » reste petit (14 paires) et majoritairement issu de la
relecture de désaccords où Forme était déjà en tête (ce qui donne un biais favorable à Forme, mais
n'explique pas l'effondrement de la profondeur sur les œuvres non perspectives). Par ailleurs, seule
la variante Small (Apache 2.0) et une grille fixe 8 × 8 ont été mesurées : une carte de profondeur
est surtout pertinente sur un corpus strictement figuratif et perspectif (paysages, scènes
d'intérieur, peinture d'histoire), plutôt que sur un corpus généraliste mêlant gravures, aplats et
art moderne.

## 29. LocalMAP contre UMAP, et doublons repérés par SSCD (19/11/2026)

### LocalMAP : évalué, gardé comme carte d'essai

Question : [LocalMAP](https://github.com/YingfanWang/PaCMAP) (Wang et al., AAAI 2025, paquet `pacmap`,
Apache 2.0, processeur seul) dessine-t-il une meilleure carte qu'UMAP, en particulier dans les zones
denses où les œuvres se chevauchent ?

- **Méthode.** Mêmes vecteurs que la carte principale (forme, DINOv3, PCA 64), mêmes 80 716 œuvres,
  graine fixe. Cinq mesures, sur la carte normalisée dans [-1, 1] : part des 10 vraies voisines
  (cosinus des vecteurs complets) restées parmi les 10 plus proches sur la carte (5 000 œuvres tirées
  au sort) ; part des œuvres dont les voisines sur la carte portent majoritairement la même étiquette
  (style, artiste, genre) ; part des vignettes qui chevauchent leur voisine à la vue d'ensemble ;
  surface occupée (grille 128 × 128) ; rang, sur la carte, de l'œuvre jumelle des paires validées
  (§ 18).

| Regard forme, 80 716 œuvres | UMAP (carte actuelle) | LocalMAP, 10 voisines | LocalMAP, 20 voisines |
|---|---|---|---|
| Temps de calcul (processeur) | — | 28 s | 44 s |
| 10 vraies voisines gardées | 7,4 % | **7,8 %** | 5,8 % |
| Voisines de même style | 45,8 % | **47,3 %** | 45,0 % |
| Voisines du même artiste | 32,0 % | **33,5 %** | 30,1 % |
| Voisines du même genre | 75,9 % | 75,5 % | 76,1 % |
| Surface occupée | **41 %** | 20 % | 20 % |
| Vignettes superposées | **83 %** | 95 % | 95 % |
| Paires validées : rang médian sur la carte | **6 994** | 8 879 | 9 851 |
| Paires validées : dans les 100 plus proches | 9,6 % | 10,6 % | **12,0 %** |

- **Lecture.** LocalMAP coupe le corpus en six îlots séparés par du vide : les grandes familles se
  lisent mieux, mais les œuvres s'entassent dans chaque îlot (deux fois moins de surface) et les
  paires validées s'éloignent. Le gain sur les étiquettes (+1,5 point) est trop faible pour
  compenser ce que l'on perd à l'écran, dans un atlas de vignettes.
- **Décision.** UMAP reste la carte principale. À la demande de l'utilisateur, LocalMAP est proposé
  comme **carte d'essai** (`pixplot maps --localmap`, dépendance facultative `[localmap]`), dans le
  menu « Forme · LocalMAP (essai, pas mieux) », avec une note qui rappelle ces chiffres.
- **Limites.** Un seul regard (forme) et deux réglages ; mesures sur l'ensemble de la carte, pas
  zone par zone. Le chevauchement est mesuré à la vue d'ensemble : en zoomant, l'Atlas espace les
  vignettes de la même façon pour les deux cartes.

### Doublons et variantes : SSCD là où il est bon

SSCD n'a pas été retenu comme regard (§ 27) : il retrouve moins bien les filiations que Forme et
Sujet. Mais il est fait pour reconnaître **la même image** malgré un recadrage, un autre éclairage ou
une autre numérisation. `pixplot doublons` s'en sert pour signaler les œuvres entrées deux fois au
catalogue, que le hachage de `pixplot ingest` ne voit pas (il ne repère que les fichiers identiques
octet pour octet).

- **Méthode.** Vecteurs SSCD centrés (conseil des auteurs), 5 plus proches voisines par œuvre, FAISS
  exact. Les seuils ont été choisis **en regardant** huit paires tirées au sort par tranche de
  cosinus : à partir de 0,95, la même image ; de 0,85 à 0,95, la même œuvre autrement reproduite
  (couleur et noir et blanc, autre cadrage) ; de 0,65 à 0,85, des répliques, des séries (les
  cathédrales de Rouen de Monet), des états d'une eau-forte de Rembrandt, la copie d'un portrait
  rococo, et encore quelques reproductions médiocres d'une même œuvre ; de 0,55 à 0,65, surtout des
  œuvres d'une même série.
- **Niveaux retenus.** « Même image » dès 0,85 ; « variante » de 0,65 à 0,85. Pour chaque paire, les
  étiquettes du catalogue qui se contredisent (artiste, style, genre, date ; « Unknown » ne compte
  pas).

| WikiArt 81k | paires | étiquettes contradictoires | dont style | dont genre | dont artiste |
|---|---|---|---|---|---|
| Même image (≥ 0,85) | 839 | **702** | 689 | 12 | 8 |
| Variante (0,65–0,85) | 785 | 68 | 29 | 33 | 9 |

- **Lecture.** WikiArt range souvent la même reproduction sous **deux styles** (un Corot à la fois
  « Romanticism » et « Realism »), et 598 paires « même image » ont un artiste connu d'un côté
  seulement (« Unknown Artist » de l'autre). C'est une limite du corpus à garder en tête : elle
  touche aussi les bancs d'essai par étiquette (§ 9), où une œuvre peut retrouver son propre doublon
  sous une autre étiquette.
- **Dans l'Atlas et le serveur MCP.** Onglet « Doublons » de « À vérifier » (même image ou variantes,
  étiquettes contradictoires seulement ou toutes, bouton Comparer) ; outil MCP `find_duplicates`.
  Une paire est une piste : deux tableaux d'une série restent deux œuvres.
- **Limites.** Seuils choisis à l'œil sur 40 paires, pas sur un jeu annoté ; 5 voisines par œuvre
  (un groupe de plus de six reproductions n'est vu que par morceaux) ; SSCD juge la ressemblance des
  images, pas l'histoire des œuvres.

## 30. Ce que mesure P@1 : la première voisine étiquetée (19/11/2026)

Point 9 de l'audit de Gemini 4 Argon. Dans `pixplot bench`, P@1 ne regarde pas la toute première
voisine d'une œuvre, mais **la première voisine qui porte l'étiquette** (artiste, style, genre) : une
voisine sans étiquette (« Unknown Artist ») est sautée. C'est une règle défendable (on ne juge que ce
que le catalogue permet de juger), mais elle n'était écrite nulle part. Décision de l'utilisateur :
**garder cette règle et la dire** (docstring de `bench.py`, sortie de la commande, cette section) ;
aucun chiffre publié ne change.

Écart avec les deux autres règles possibles, mesuré sur WikiArt 81k (10 voisines, vecteurs complets) :

| P@1 | actuel (voisines sans étiquette sautées) | strict (œuvre non comptée) | strict (compté comme échec) | 1re voisine sans étiquette |
|---|---|---|---|---|
| Forme, artiste | 65,6 % | 72,1 % | 59,3 % | 17,9 % |
| Sujet, artiste | 73,0 % | 77,8 % | 66,6 % | 14,4 % |
| Forme, genre | 80,9 % | 82,1 % | 75,7 % | 7,7 % |
| Sujet, genre | 83,4 % | 84,4 % | 78,2 % | 7,4 % |
| Forme, style | 64,8 % | 64,8 % | 64,8 % | 0 % |
| Sujet, style | 71,4 % | 71,4 % | 71,4 % | 0 % |

- **Le style ne bouge pas** : toutes les œuvres de WikiArt en ont un. L'artiste et le genre bougent de
  quelques points, dans un sens ou dans l'autre selon la règle.
- **Aucune conclusion ne change** : Sujet reste devant Forme pour les trois étiquettes, avec les trois
  règles.
- **Doublons** (§ 29) : les retirer change P@1 de moins d'un point (style : 64,8 % → 65,3 % pour
  Forme, 71,4 % → 72,0 % pour Sujet).
