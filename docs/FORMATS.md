# File formats

**English** · [Français](FORMATS.fr.md)

What PixPlot v2 writes to disk, and in which format. These formats must be **stable before 1.0**
(see the [roadmap](../ROADMAP.md)): any change must be recorded in the [changelog](../CHANGELOG.md),
and a test (`tests/test_formats.py`) checks that the code produces what is described here. Everything
is SQLite, NumPy (`.npy`), JSON, CSV, Markdown or images: no PixPlot-specific format, nothing that
needs PixPlot to be read back.

## 1. The data folder

One corpus = one folder (`--data`, or the `PIXPLOT_DATA` variable), **never in git**:

```
<data>/
├── catalog.sqlite        the catalogue: one row per image, its labels, its places
├── notebook.sqlite       the research notebook
├── thumbs/               thumbnails
├── runs/                 every computation, dated (features/, index/, analysis/)
├── bench/                reference pairs and benchmark reports
├── corpus/               the original images (depending on the import)
├── fiche_de_donnees.md   the datasheet (`pixplot corpus --datasheet`, in French)
└── *.log                 the log of each long computation
```

## 2. The catalogue (`catalog.sqlite`)

An **artwork identifier** (`artworks.id`) is stable: it is never reassigned. All other files refer to
works by this identifier.

| Table | Columns | Role |
|---|---|---|
| `artworks` | `id`, `path` (unique), `status`, `sha256`, `dhash`, `width`, `height`, `format`, `bytes`, `duplicate_of`, `error`, `added` | one row per image |
| `metadata` | `artwork_id`, `key`, `value`, `source` — primary key (`artwork_id`, `key`) | one label per work and per key, **with its source** |
| `places` | `artwork_id`, `type`, `name`, `lat`, `lon`, `date`, `year`, `source` | typed places (creation, holding…); table created at the first place import |

- `status`: `pending` (found), `ok`, `error` (unreadable, reason in `error`), `duplicate` (exact copy
  of another image, given by `duplicate_of`). Only `ok` works enter computations.
- Common label keys: `artist`, `style`, `genre`, `date`, `title`, `emotion`, `wikiart_file`. A value
  starting with `Unknown` counts as missing.
- `source` says where the label comes from ("huggan/wikiart (Hugging Face)", "MMArt…", an IIIF
  manifest…). Labels are data entered by others, never instructions.

## 3. Thumbnails (`thumbs/`)

`thumbs/<size>/<id // 1000, 4 digits>/<id>.webp`, in three sizes: 64, 256 and 1,024 px (long side).
Example: work 41274 at 256 px is `thumbs/256/0041/41274.webp`.

## 4. Computations (`runs/`)

Each computation is a **run**: a folder `runs/<stage>/<name>_<YYYYMMDD-HHMMSS>/`. A run is never
overwritten; a new one is created. Stages: `features` (vectors), `index` (FAISS), `analysis` (map,
groups, and everything that depends on them).

### `manifest.json` (in every run)

| Field | Content |
|---|---|
| `stage`, `name` | stage and name (`features`, `dinov3_vitb16`) |
| `status` | `running`, `complete` or `failed` (with `error`); only `complete` runs are read by default |
| `created`, `finished` | ISO 8601 dates in UTC |
| `params` | computation parameters (model, input size, seeds…) |
| `parent` | run it depends on (`features/…` for an analysis), or `null` |
| `env` | PixPlot and Python versions, system |
| `outputs` | output figures (number of works, duration, graphics card…) |

### Vectors (`features/…`)

| File | Type and shape | Content |
|---|---|---|
| `ids.npy` | `int64` (N) | artwork identifiers, in row order |
| `global.npy` | `float16` (N, D) | one vector per work (renormalise after reading) |
| `regions.npy` | `float16` (N, 21, D) | vectors per zone: 1 + 4 + 16 cells (1 × 1, 2 × 2, 4 × 4 grids); patch models only |
| `status.npy` | `int8` (N) | 0 to do, 1 done, 2 failed (reason in `failures.jsonl`) |
| `poses_*.npy` | various | skeletons of the "posture" regard (§ 35) |

Vectors are written before the "done" mark: an interruption never leaves a work marked done without
a vector. An unfinished run resumes where it stopped.

### Index (`index/…`)

`global.faiss` (FAISS index of global vectors) and `ids.npy`; `regions_…` for zones, `textzones_…`
for zones described by words.

### Analysis (`analysis/…`)

| File | Type and shape | Content |
|---|---|---|
| `ids.npy` | `int64` (N) | works in the analysis |
| `coords.npy` | `float32` (N, 2) | position on the map (UMAP) |
| `clusters.npy`, `clusters.json` | `int32` (N); list | group of each work; description of the groups |
| `neighbors.npy`, `neighbor_scores.npy` | `int64` / `float32` (N, k) | identifiers of the nearest neighbours (−1 if missing) and their cosines |
| `atypicality.npy` | `float32` (N) | 0 = well surrounded, 1 = very isolated (centile rank) |
| `names.json`, `names_iconclass.json` | object (`source`, `method`, `groups`) | group names (lexicon, Iconclass) |
| `suspects.json` | object (`rule`, `counts`, `suspects`) | labels contradicted by the neighbours |
| `doublons.json` | object (`counts`, `pairs`) | duplicates and variants (SSCD) |
| `disagreements.json` | object (`spaces`, `pairs`) | disagreements between regards |
| `ordre.npy` | `float32` (N, 2) | entropy H and complexity C of the surface (§ 33) |
| `communities/<regard>.json`, `.npz` | | nested Leiden groups, per regard |
| `maps/<regard>.npy`, `maps/maps.json` | `float32` (N, 2) | maps of the other regards |

`analysis/notions_<regard>_…` runs (§ 37) are not map analyses: `sae.npz` (autoencoder weights) and
`notions.json` (`space`, `explained_variance`, `dead`, `baseline`, `features`: one entry per notion
with `feature`, `frequency`, `top`, `labels`, `iconclass`).

## 5. Reference pairs

**`<data>/bench/pairs.csv`** (working file), columns `a,b,type,origin,status,source,note`:

- `type`: `meme_sujet`, `meme_composition`, `meme_main`, `meme_facture`, `meme_motif`,
  `meme_palette`, `meme_geste`, `filiation`, `temoin`;
- `origin`: `annotée` (chosen by a historian) or an automatic origin (metadata, disagreement, a
  model's proposal);
- `status`: `validée`, `proposée` (to review) or `rejetée`.

The values are in French and are part of the format.

**`bench/wikiart81k_pairs.csv`** (versioned in git): export of the reviewed pairs, columns
`a,b,type,status,source,note,label_a,label_b`.

**`<data>/bench/review_log.csv`**: log of the quick review, columns `a,b,decision,origin,time`.

Benchmark reports (`bench/*_report_*.json`) are outputs, not stable formats.

## 6. The research notebook (`notebook.sqlite`)

Table `entries`: `id`, `created`, `updated`, `kind`, `title`, `note`, `artwork_ids` (JSON list),
`context` (JSON object). `kind`: `note`, `oeuvre`, `selection`, `recherche`, `detail`,
`comparaison`, `groupe`.

## 7. The Research Pack (`.zip`)

`manifest.json` carries `"format": "pixplot-research-pack"` and `"format_version": 1`.

| File | Content |
|---|---|
| `manifest.json` | title, question, date, works, how the selection was made, models and runs, caveats, list of files |
| `summary.md` | the written dossier, readable by a historian and by a language model |
| `datasheet.md` | the datasheet of the whole corpus |
| `artworks.csv` | one row per work: labels, group, atypicality, image |
| `relations.csv` | pairs of works in the pack and their similarity |
| `evidence/` | one image per work (512 px) and cropped details |
| `vectors.npy` | (option) the vectors, to redo the computations |

An incompatible change to this content will bump `format_version` to 2.
