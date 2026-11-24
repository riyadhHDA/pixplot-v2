# Formats de fichiers

[English](FORMATS.md) · **Français**

Ce que PixPlot v2 écrit sur le disque, et dans quel format. Ces formats doivent être **stables avant
la 1.0** (voir la [feuille de route](../ROADMAP.fr.md)) : tout changement doit être noté dans le
[CHANGELOG](../CHANGELOG.fr.md), et un test (`tests/test_formats.py`) vérifie que le code produit bien
ce qui est décrit ici. Tout est en SQLite, NumPy (`.npy`), JSON, CSV, Markdown ou image : aucun format
propre à PixPlot, rien qui demande PixPlot pour être relu.

## 1. Le dossier de données

Un corpus = un dossier (`--data`, ou la variable `PIXPLOT_DATA`), **jamais dans git** :

```
<données>/
├── catalog.sqlite        le catalogue : une ligne par image, ses étiquettes, ses lieux
├── notebook.sqlite       le carnet de recherche
├── thumbs/               les vignettes
├── runs/                 chaque calcul, daté (features/, index/, analysis/, tiles/)
├── bench/                paires de référence et rapports des bancs d'essai
├── corpus/               les images d'origine (selon l'import)
├── fiche_de_donnees.md   la fiche de données (`pixplot corpus --datasheet`)
└── *.log                 le journal de chaque calcul long
```

## 2. Le catalogue (`catalog.sqlite`)

L'**identifiant d'une œuvre** (`artworks.id`) est stable : on ne le réattribue jamais. Tous les
autres fichiers désignent les œuvres par cet identifiant.

| Table | Colonnes | Rôle |
|---|---|---|
| `artworks` | `id`, `path` (unique), `status`, `sha256`, `dhash`, `width`, `height`, `format`, `bytes`, `duplicate_of`, `error`, `added` | une ligne par image |
| `metadata` | `artwork_id`, `key`, `value`, `source` — clé primaire (`artwork_id`, `key`) | une étiquette par œuvre et par clé, **avec sa source** |
| `places` | `artwork_id`, `type`, `name`, `lat`, `lon`, `date`, `year`, `source` | lieux typés (création, conservation…) ; table créée au premier import de lieux |

- `status` : `pending` (repérée), `ok`, `error` (illisible, raison dans `error`), `duplicate` (copie
  exacte d'une autre image, désignée par `duplicate_of`). Seules les œuvres `ok` entrent dans les calculs.
- Clés d'étiquettes courantes : `artist`, `style`, `genre`, `date`, `title`, `emotion`,
  `wikiart_file`. Une valeur qui commence par `Unknown` compte comme absente.
- `source` dit d'où vient l'étiquette (« huggan/wikiart (Hugging Face) », « MMArt… », un manifeste
  IIIF…). Les étiquettes sont des données saisies par d'autres, jamais des consignes.

## 3. Les vignettes (`thumbs/`)

`thumbs/<taille>/<id // 1000, sur 4 chiffres>/<id>.webp`, en trois tailles : 64, 256 et 1 024 px
(grand côté). Exemple : l'œuvre 41274 en 256 px est `thumbs/256/0041/41274.webp`.

## 4. Les calculs (`runs/`)

Chaque calcul est un **run** : un dossier `runs/<étape>/<nom>_<AAAAMMJJ-HHMMSS>/`. Un run n'est jamais
écrasé ; on en crée un nouveau. Étapes : `features` (vecteurs), `index` (FAISS), `analysis` (carte,
groupes, et tout ce qui en dépend), `tiles` (pyramide de tuiles de la carte principale).

### `manifest.json` (dans chaque run)

| Champ | Contenu |
|---|---|
| `stage`, `name` | étape et nom (`features`, `dinov3_vitb16`) |
| `status` | `running`, `complete` ou `failed` (avec `error`) ; seuls les runs `complete` sont lus par défaut |
| `created`, `finished` | dates ISO 8601 en UTC |
| `params` | paramètres du calcul (modèle, taille d'entrée, graines…) |
| `parent` | run dont il dépend (`features/…` pour une analyse), ou `null` |
| `env` | versions de PixPlot et de Python, système |
| `outputs` | chiffres de sortie (nombre d'œuvres, durée, carte graphique…) |

### Vecteurs (`features/…`)

| Fichier | Type et forme | Contenu |
|---|---|---|
| `ids.npy` | `int64` (N) | identifiants des œuvres, dans l'ordre des lignes |
| `global.npy` | `float16` (N, D) | un vecteur par œuvre (à renormaliser après lecture) |
| `regions.npy` | `float16` (N, 21, D) | vecteurs par zone : 1 + 4 + 16 cases (grilles 1 × 1, 2 × 2, 4 × 4) ; modèles à patchs seulement |
| `status.npy` | `int8` (N) | 0 à faire, 1 fait, 2 échec (raison dans `failures.jsonl`) |
| `poses_*.npy` | divers | squelettes du regard « posture » (§ 35) |

Les vecteurs sont écrits avant la marque « fait » : une coupure ne laisse jamais une œuvre marquée
faite sans vecteur. Un run inachevé reprend où il s'était arrêté.

### Index (`index/…`)

`global.faiss` (index FAISS des vecteurs globaux) et `ids.npy` ; `regions_…` pour les zones,
`textzones_…` pour les zones décrites par des mots.

### Analyse (`analysis/…`)

| Fichier | Type et forme | Contenu |
|---|---|---|
| `ids.npy` | `int64` (N) | œuvres de l'analyse |
| `coords.npy` | `float32` (N, 2) | position sur la carte (UMAP) |
| `clusters.npy`, `clusters.json` | `int32` (N) ; liste | groupe de chaque œuvre ; description des groupes |
| `neighbors.npy`, `neighbor_scores.npy` | `int64` / `float32` (N, k) | identifiants des voisines les plus proches (−1 s'il en manque) et leurs cosinus |
| `atypicality.npy` | `float32` (N) | 0 = très entourée, 1 = très isolée (rang centile) |
| `names.json`, `names_iconclass.json` | objet (`source`, `method`, `groups`) | noms de groupes (lexique, Iconclass) |
| `suspects.json` | objet (`rule`, `counts`, `suspects`) | étiquettes que les voisines contredisent |
| `doublons.json` | objet (`counts`, `pairs`) | doublons et variantes (SSCD) |
| `disagreements.json` | objet (`spaces`, `pairs`) | désaccords entre regards |
| `ordre.npy` | `float32` (N, 2) | entropie H et complexité C de la matière (§ 33) |
| `communities/<regard>.json`, `.npz` | | groupes Leiden emboîtés, par regard |
| `maps/<regard>.npy`, `maps/maps.json` | `float32` (N, 2) | cartes des autres regards |

Les runs `analysis/notions_<regard>_…` (§ 37) ne sont pas des analyses de carte : `sae.npz` (poids de
l'auto-encodeur) et `notions.json` (`space`, `explained_variance`, `dead`, `baseline`, `features` :
une entrée par notion avec `feature`, `frequency`, `top`, `labels`, `iconclass`).

### Tuiles (`tiles/…`)

Pyramide de tuiles précalculées pour la carte principale (`pixplot tiles`), rattachée à son analyse
par `parent` dans `manifest.json`. Chaque fichier est écrit de façon atomique (`.tmp` puis
remplacement), ce qui permet la reprise après coupure.

| Fichier | Format | Contenu |
|---|---|---|
| `tiles.json` | JSON | paramètres (`format`, `tile_size`, `extent`, `world`, `min_level`, `max_level`, `background`, `icon_size`, `count`, `analysis`) et `levels` (tuiles non vides `"x/y"` par niveau) |
| `<niveau>/<x>/<y>.webp` | WebP (ou JPEG/PNG) | tuile de `tile_size × tile_size` px (512 px par défaut), `x` de gauche à droite, `y` de haut en bas, sur fond `#0f0f10` |

## 5. Les paires de référence

**`<données>/bench/pairs.csv`** (de travail), colonnes `a,b,type,origin,status,source,note` :

- `type` : `meme_sujet`, `meme_composition`, `meme_main`, `meme_facture`, `meme_motif`,
  `meme_palette`, `meme_geste`, `filiation`, `temoin` ;
- `origin` : `annotée` (choisie par un historien) ou une origine automatique (métadonnées,
  désaccord, proposition d'un modèle) ;
- `status` : `validée`, `proposée` (à relire) ou `rejetée`.

**`bench/wikiart81k_pairs.csv`** (versionnée dans git) : l'export des paires relues, colonnes
`a,b,type,status,source,note,label_a,label_b`.

**`<données>/bench/review_log.csv`** : journal de la relecture rapide, colonnes
`a,b,decision,origin,time`.

**`bench/<corpus>_pairs_travail.csv`** et **`bench/<corpus>_review_log.csv`** (versionnées, écrites par
`pixplot sauvegarde`) : copies exactes de `<données>/bench/pairs.csv` et `review_log.csv`, mêmes colonnes.
**`bench/<corpus>_notebook.json`** (avec `--carnet`) : liste des entrées du carnet, mêmes champs que la table
`entries`, `artwork_ids` et `context` décodés.

Les rapports des bancs d'essai (`bench/*_report_*.json`) sont des sorties, pas des formats stables.

## 6. Le carnet de recherche (`notebook.sqlite`)

Table `entries` : `id`, `created`, `updated`, `kind`, `title`, `note`, `artwork_ids` (liste JSON),
`context` (objet JSON). `kind` : `note`, `oeuvre`, `selection`, `recherche`, `detail`,
`comparaison`, `groupe`.

## 7. Le Research Pack (`.zip`)

`manifest.json` porte `"format": "pixplot-research-pack"` et `"format_version": 1`.

| Fichier | Contenu |
|---|---|
| `manifest.json` | titre, question, date, œuvres, provenance de la sélection, modèles et runs, mises en garde, liste des fichiers |
| `summary.md` | le dossier rédigé, lisible par un historien et par un modèle de langage |
| `datasheet.md` | la fiche de données du corpus entier |
| `artworks.csv` | une ligne par œuvre : étiquettes, groupe, atypicité, image |
| `relations.csv` | paires d'œuvres du dossier et leur similarité |
| `evidence/` | une image par œuvre (512 px) et les détails recadrés |
| `vectors.npy` | (option) les vecteurs, pour refaire les calculs |

Un changement incompatible de ce contenu fera passer `format_version` à 2.
