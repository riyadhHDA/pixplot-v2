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
- **SigLIP 2** (Google) → recherche en texte libre.
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
| `text` | SigLIP 2 | `IndexFlatIP` | ~1,5 Go |

### ④ Analyse — `pixplot.analysis`
- **Regroupement** : e-means (`faiss.contrib.e_means`, inclus dans `faiss-cpu` 1.16, y
  compris sous Windows) par défaut ; HDBSCAN (celui de scikit-learn) en option, pour
  isoler les œuvres « à part ».
- **Cartes** : PCA 64 d → UMAP appris sur un échantillon (~100k) puis appliqué au reste.
  Une carte par espace : formel (DINOv3), sémantique (SigLIP), chromatique (plus tard).
- **Graphe de voisinage** : top-20 voisins par œuvre et par espace (Parquet).
- **Atypiques** : faible densité locale, ou voisins très différents d'un espace à l'autre.

### ⑤ Services — `pixplot.api`, `pixplot.mcp`
- API FastAPI pour l'interface.
- Serveur MCP, outils : `search_similar`, `search_text`, `search_region`, `get_artwork`,
  `get_neighbors`, `get_cluster`, `export_pack`.

### ⑥ Interface — `web/`
React + TypeScript + rendu WebGL. **Moteur à choisir à l'étape 4** (deck.gl ou PixiJS),
sur un prototype avec le vrai corpus. Écrans, dans l'ordre :
Atlas (choix de l'espace) → Fiche œuvre (voisins par espace) → Sélection de zone →
Comparateur (zoom synchronisé, superposition) → Carnet de recherche.

### ⑦ Research Pack — `pixplot.export`
```
pack.zip
├── manifest.json      modèles, runs, paramètres, requête d'origine
├── artworks.parquet   métadonnées des œuvres concernées
├── relations.parquet  paires, scores, espace, groupe
├── evidence/          vignettes et détails recadrés (lisibles par un LLM multimodal)
├── summary.md         résumé rédigé pour un LLM
└── vectors.npy        (option « expert » : reproductibilité)
```
Un LLM ne sait rien faire de vecteurs bruts : ce qui compte, ce sont les **relations
explicites, les métadonnées et les images**. Les vecteurs ne servent qu'à reproduire.

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
├── web/                   ⑥ React + TypeScript
├── tests/
├── data/                  (hors git) catalog.sqlite, thumbs/, runs/
└── pix-plot-0.0.1.1/      PixPlot v1 (Yale, 2018) — référence locale, non publiée
```

## 5. Feuille de route

1. Ingestion + extraction DINOv3 sur 1 000 images ; validation du GPU.
2. ~~Index FAISS global + banc d'essai~~ **fait** (voir § 9).
3. PCA→UMAP + e-means → première carte.
4. API + interface Atlas + fiche œuvre. *(= « PixPlot v1 en mieux »)*
5. Recherche par région, puis SigLIP 2 (texte). *(= le vrai apport pour l'historien)*
6. Serveur MCP + Research Pack.
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
