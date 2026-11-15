# PixPlot v2 — Architecture

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
  déclaré à part (28 % sur WikiArt, contre 2 % ainsi).
- **Cartes** : PCA 64 d → UMAP 2D, appris sur un échantillon (~100k) puis appliqué au reste.
  L'échelle ignore 0,5 % d'œuvres extrêmes de chaque côté, posées sur le bord.
  Une carte par espace : formel (DINOv3), sémantique (SigLIP), chromatique (plus tard).
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
- **Serveur MCP** (`pixplot mcp`, stdio, SDK officiel `mcp` 2.x) : 11 outils —
  `corpus_overview`, `search_by_text`, `similar_artworks`, `search_detail`, `get_artwork`,
  `view_artwork`, `view_detail`, `compare_artworks`, `get_group`, `find_atypical`,
  `export_research_pack`. Les outils `view_*` et `compare_artworks` **renvoient des images**
  au LLM. Consignes de méthode et de prudence intégrées. Branchement : `docs/MCP.md`.

### ⑥ Interface — `web/`
**deck.gl 9.4** (rendu WebGL), en JavaScript simple **sans étape de compilation** : le
fichier deck.gl est rangé dans `web/vendor/`, donc ni Node ni connexion Internet ne sont
nécessaires pour utiliser l'Atlas. Choisi plutôt que PixiJS pour son zoom/déplacement,
sa sélection au clic et son rendu de centaines de milliers de points prêts à l'emploi.
Les vignettes ne sont chargées que pour les œuvres visibles à l'écran (1 500 au plus),
ce qui garde l'Atlas fluide quelle que soit la taille du corpus.

Fait (étape 4) : carte des groupes, coloration (groupes, familles HDBSCAN, atypicité,
artiste, style…), légende cliquable, recherche, fiche œuvre avec ses 20 voisines reliées
sur la carte, lien partageable `#oeuvre-<id>`. Écrans suivants, dans l'ordre :
Atlas (choix de l'espace) → Fiche œuvre (voisins par espace) → Sélection de zone →
Comparateur (zoom synchronisé, superposition) → Carnet de recherche.

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
├── ARCHITECTURE.md
├── pyproject.toml
├── pixplot/
│   ├── config.py          chemins et réglages (PIXPLOT_DATA)
│   ├── runs.py            runs versionnés + manifests
│   ├── cli.py             pixplot ingest | embed | index | analyze | serve
│   ├── catalog/           ① SQLite, ingestion, vignettes, doublons
│   ├── encoders/          ② interface Encoder, letterbox, dinov3, dinov2, siglip2
│   ├── features/          ② extraction par lots, reprise, régions
│   ├── index/             ③ FAISS
│   ├── analysis/          ④ e-means, hdbscan, umap, voisins, atypiques
│   ├── export/            ⑦ Research Pack
│   ├── api/               ⑤ FastAPI
│   └── mcp/               ⑤ serveur MCP
├── web/                   ⑥ Atlas : index.html, atlas.js, atlas.css, vendor/deck.gl
├── tests/
├── data/                  (hors git) catalog.sqlite, thumbs/, runs/
└── pix-plot-0.0.1.1/      PixPlot v1 (Yale, 2018) — référence locale, non publiée
```

## 5. Feuille de route

1. Ingestion + extraction DINOv3 sur 1 000 images ; validation du GPU.
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
7. Comparateur, carnet de recherche, chronologie et géographie.

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
