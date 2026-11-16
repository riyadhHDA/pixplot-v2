# PixPlot v2 — Architecture

**English** · [Français](ARCHITECTURE.fr.md)

A visual exploration lab for art history: map 100,000 to 500,000 artworks, find formal
kinships and details, and pass discoveries on to a language model (MCP, Research Pack)
without ever losing traceability.

> **Roles:** PixPlot computes, observes and organises. The LLM asks and suggests.
> The art historian checks, interprets and builds knowledge.

---

## 1. Principles

1. **One core.** All the logic lives in the `pixplot` Python library. The CLI, the web API
   and the MCP server are three thin façades over that core.
2. **Versioned stages.** Each stage reads the outputs of the previous one and writes a
   *run* to `data/runs/<stage>/<name>_<timestamp>/` with a `manifest.json` (model,
   parameters, parent run, versions, status). Nothing is overwritten.
3. **Resumable.** 500,000 images with 16 GB of RAM: everything is processed in batches,
   written to disk (FP16 memmaps) and can resume after a stop.
4. **Interchangeable models.** Every model goes through the `Encoder` interface.
5. **Whole image.** Never a `CenterCrop`: images are resized and padded (letterbox) to
   preserve the composition.
6. **Stable identifiers.** An artwork = an `artwork_id` + the SHA-256 of the file, never its
   file name.
7. **Local first.** No image is sent anywhere, no telemetry.

## 2. Overview

```
 Images + metadata (folders, CSV, IIIF, museums)
            │
 ① INGESTION ─────────── CPU
            │  SQLite catalogue, SHA-256, dHash (near-duplicates), thumbnails
            ▼
 ② EXTRACTION ────────── GPU (RX 7900 GRE)
            │  DINOv3 ViT-B/16: global vector (768) + region vectors
            │  SigLIP 2: image↔text vector · colour and touch spaces
            ▼
 ③ INDEX ─────────────── CPU
            │  FAISS: global / regions / text
            ▼
 ④ ANALYSIS ──────────── CPU
            │  e-means, HDBSCAN, PCA→UMAP, k-nearest-neighbour graph, atypical works,
            │  group names, labels to check
            ▼
 ⑤ SERVICES ──────────── pixplot library
            ├── FastAPI API ──► ⑥ web INTERFACE (Atlas, record, comparator, notebook)
            ├── MCP server ───► Claude / another LLM
            └── ⑦ EXPORT ─────► Research Pack (.zip)
```

## 3. Layers

### ① Ingestion — `pixplot.catalog`, `pixplot.importers`
- Folder scan, stable identifier, SHA-256 (exact duplicates), perceptual hash
  (near-duplicates: two scans of the same work).
- An unreadable image is **set aside and logged**; it never blocks processing.
- Metadata import: artist, date, place, technique, institution, source, rights, with the
  source recorded for every value.
- **IIIF importer** for museum and library collections (§ 12).
- Thumbnails at 64 / 256 / 1024 px + thumbnail sheets (texture atlases) for WebGL rendering.

### ② Extraction — `pixplot.encoders`, `pixplot.features`
- Preprocessing: letterbox to the model's resolution (padding = ImageNet mean colour);
  padding patches are excluded from region vectors.
- **DINOv3 ViT-B/16** (Meta):
  - global vector (normalised CLS token, 768 d) → overall resemblance;
  - region vectors: patches mean-pooled over 1×1, 2×2 and 4×4 grids (21 regions) →
    search by detail. Stored as is (768 d, FP16, ~16 GB on disk for 500,000 works), then
    reduced to 256 d by PCA and compressed in the region index. (Keeping every patch
    would cost ~150 GB for 500,000 images.)
- **SigLIP 2 So400m** (Google, `google/siglip2-so400m-patch16-384`, Apache 2.0, open
  access) → free-text search, **multilingual** (French queries work). Letterbox with
  SigLIP's own normalisation (0.5 / 0.5). No region vectors.
- **Touch** (`dinov3_vitb16_texture`) and **colour** (`color_lab`) spaces: see § 12.
- Option: **DINOv3 ViT-L/16**: +2 to 3 points on artist and style, 1.8× slower (§ 9).
  Recommended for the final processing of a large corpus.
- **DINOv2 ViT-B/14 (registers)**: no access request needed; was used to start while
  DINOv3 access was pending, and as a baseline.
- Weight loading: Hugging Face (`transformers`) by default; Meta `.pth` format as a
  fallback for DINOv3.
- Default resolution: 448 px (confirmed by the benchmark: +3 points on artist over 224 px,
  for 2.5× more compute).
- Acceleration: **native PyTorch ROCm on Windows 11** first; WSL2 + ROCm as a fallback,
  then CPU.

### ③ Index — `pixplot.index`

| Index | Content | FAISS type | Size (500k) |
|---|---|---|---|
| `global` | one per space (form, subject, colour, touch) | `IndexFlatIP` | ~1.5 GB (DINOv3) |
| `regions` | ~10 M regions | `IndexFlatIP` up to 1.5 M, `IVF-PQ` beyond | ~0.5 GB |

### ④ Analysis — `pixplot.analysis`
Command: `pixplot analyze [--clusters N] [--hdbscan]`. Fixed seed: reproducible.
- **Clustering**: spherical e-means (`faiss.contrib.e_means.NumpyEmeans`, shipped with
  `faiss-cpu` 1.16, including on Windows), ≈ √N / 2 groups by default (8 to 200); for each
  group, the work closest to the centre is its representative image.
- **HDBSCAN** (optional, scikit-learn) on an intermediate 10-dimensional UMAP: "natural"
  families and works "on their own". Works on small corpora, unusable at scale (§ 11): the
  Atlas hides it when more than 30 % of the works would be declared isolated.
- **Maps**: PCA 64 d → 2D UMAP, fitted on a sample (~100k) then applied to the rest. The
  scale ignores the 0.5 % most extreme works on each side, placed on the edge.
- **Neighbour graph**: 20 nearest neighbours per work (`neighbors.npy` + scores).
- **Atypicality**: percentile rank of isolation (low mean similarity to its neighbours).
- **Group names** and **labels to check**: § 12.
- **Static map**: a large JPEG of the thumbnails at their UMAP positions (`data/maps/`).

### ⑤ Services — `pixplot.api`, `pixplot.mcp`
- **FastAPI API** (`pixplot serve`, listens on 127.0.0.1 only by default): map, groups,
  artwork records (metadata + sources, neighbours in each space, provenance of the
  computation), search (metadata, text, detail), comparator, notebook, labels to check,
  thumbnails and images (served by identifier only, never by path). Automatic
  documentation: `/api/docs`.
- **MCP server** (`pixplot mcp`, stdio, official `mcp` 2.x SDK): 14 tools —
  `corpus_overview`, `search_by_text`, `similar_artworks` (with a `space` parameter),
  `search_detail`, `get_artwork`, `view_artwork`, `view_detail`, `compare_artworks`,
  `get_group`, `find_atypical`, `check_labels`, `notebook_add`, `notebook_list`,
  `export_research_pack`. The `view_*` and `compare_artworks` tools **return images** to
  the LLM. Method and caution guidelines are built in. Setup: `docs/MCP.md`.

### ⑥ Interface — `web/`
**deck.gl 9.4** (WebGL rendering), plain JavaScript **with no build step**: the deck.gl file
lives in `web/vendor/`, so neither Node nor an Internet connection is needed to use the
Atlas. Chosen over PixiJS for its zoom/pan, click picking and ready-made rendering of
hundreds of thousands of points.
**Every thumbnail stays on screen**, without flicker: thumbnails come from 4096 × 4096 px
sheets (texture atlases, as in PixPlot v1) built by `pixplot analyze` and uploaded once to
the GPU. 64 px cells up to 30,000 works, 32 px beyond (500,000 works ≈ 2 GB of VRAM). When
zooming in, 256 then 1024 px thumbnails are laid **over** the 300 works closest to the
centre, never removing those underneath. The interface is served with
`Cache-Control: no-cache` (no mix of an old page and a new script after an update).

Screens: map of the groups (named), colouring (groups, atypicality, artist, style…),
clickable legend, search (metadata, description, detail), artwork record with its
neighbours in each space and labels to check, comparator, research notebook, "labels to
check" panel, map / timeline / geography layouts, shareable link `#oeuvre-<id>`.

### ⑦ Research Pack — `pixplot.export`
`pixplot pack` (CLI), the Atlas's "Export" buttons, MCP tool `export_research_pack`.
Selection: list of works, group, a work's neighbours, text search or detail.
```
<date>_<title>.zip            (≈ 50 KB per work)
├── manifest.json      title, question, models, runs and parameters, provenance of the selection
├── summary.md         the written dossier: method, composition, works, strongest relations,
│                      atypical works, caveats, suggested prompt for an LLM
├── artworks.csv       metadata, group, family, atypicality, search score
├── relations.csv      every pair: visual (DINOv3) and semantic (SigLIP) similarity
├── evidence/          512 px thumbnail per work + cropped details (readable by an LLM)
└── vectors.npy        (option `--vectors`) to reproduce the computations
```
CSV / JSON / Markdown / JPEG rather than Parquet: readable by any LLM or spreadsheet with
no special tool. An LLM can do nothing with raw vectors: what matters are **explicit
relations, sourced metadata and images**.

## 4. Layout

```
pixplot-v2/
├── ARCHITECTURE.md / ARCHITECTURE.fr.md
├── pyproject.toml
├── pixplot/
│   ├── config.py          paths and settings (PIXPLOT_DATA)
│   ├── runs.py            versioned runs + manifests
│   ├── cli.py             pixplot ingest | embed | index | analyze | serve | …
│   ├── catalog/           ① SQLite, ingestion, thumbnails, duplicates
│   ├── importers/         ① IIIF
│   ├── encoders/          ② Encoder interface, letterbox, dinov3, siglip2, texture, colorlab
│   ├── features/          ② batch extraction, resume, regions
│   ├── index/             ③ FAISS
│   ├── analysis/          ④ e-means, hdbscan, umap, neighbours, naming, suspects, audit
│   ├── export/            ⑦ Research Pack
│   ├── notebook.py        research notebook (SQLite)
│   ├── api/               ⑤ FastAPI, similarity spaces
│   └── mcp/               ⑤ MCP server
├── web/                   ⑥ Atlas: index.html, atlas.js, atlas.css, vendor/deck.gl
├── scripts/               full_pipeline.sh, Parquet extraction, synthetic variants
├── tests/
└── data/                  (not in git) catalog.sqlite, thumbs/, runs/, notebook.sqlite
```

## 5. Roadmap

1. ~~Ingestion + DINOv3 extraction on 1,000 images; GPU validation~~ **done**.
2. ~~Global FAISS index + benchmark~~ **done** (see § 9).
3. ~~PCA→UMAP + e-means → first map~~ **done**.
4. ~~API + Atlas interface + artwork record~~ **done** *(= "PixPlot v1, but better")*.
5. ~~Search by detail, then SigLIP 2 (text)~~ **done** *(= the real gain for the historian)*.
   - Detail: `pixplot index --regions` indexes the 2×2 and 4×4 regions (PCA 256 d; exact up
     to 1.5 M regions, IVF-PQ beyond). In the Atlas, "Search a detail": draw a box; it is
     cropped from the original and analysed at a resolution that respects its scale (112,
     224, 336 or 448 px: 4 fixed sizes, because the AMD GPU compiles for ~20 s per new size,
     once). Result: the closest region of each work, cropped and displayed.
   - Text: `pixplot embed --encoder siglip2_so400m`, `pixplot index --encoder
     siglip2_so400m`, then `pixplot search-text "…"` or the Atlas's "Description (AI)" mode.
     Models are only loaded at the first search.
   - Trials (WikiArt): "Annonciation" → Doré's *Annunciation* first; "saint Sébastien" →
     Titian's *Saint Sebastian* second (first: a suffering Christ by the same painter);
     "un navire dans la tempête" (a ship in a storm) → 5 seascapes by Aivazovsky. Useful
     for clearing the ground, to be checked work by work.
6. ~~MCP server + Research Pack~~ **done**.
7. ~~Comparator, research notebook, timeline and geography~~ **done** (see § 12).

## 6. Lessons from PixPlot v1 (0.0.1.1)

| v1 problem | v2 answer |
|---|---|
| Images identified by file name (collisions) | `artwork_id` + SHA-256 |
| Vector order ≠ position order when an image fails | Order fixed by the catalogue, rows aligned by id |
| One corrupt image stops everything | Set aside and logged |
| One `.npy` per image, all loaded into RAM | One FP16 memmap per run |
| Inception (object classification), JPEG only | DINOv3 + SigLIP 2, all formats |
| k-means fixed at 20, labels edited by hand in JSON | e-means, suggested group names |
| No similarity search | FAISS: image, region, text |
| Google Analytics built in | No telemetry |

**Kept from v1:** thumbnail sheets (texture atlases) and batched rendering, generalised to
several zoom levels; "hotspots" with a representative image.

## 7. Scientific principles

Traceability (model, version, parameters for every result) · Reproducibility (any run can
be re-run) · Provenance (source of every work and every metadata value) · Uncertainty (a
score is not a historical probability) · Contradiction (look for counter-examples) · Human
control (the researcher validates).

## 8. Licences

- **PixPlot v2: GPL-3.0**
- PixPlot v1: MIT · FAISS / e-means: MIT
- **DINOv3: Meta's own licence, weights on request**: read it before any public or
  commercial distribution of results or software. The weights are never published here.
- SigLIP 2: Apache 2.0

## 9. Benchmark (15/11/2026)

RX 7900 GRE, native Windows 11, PyTorch 2.14 + ROCm 10.1. Corpus: 2,263 WikiArt works
(124 artists, 27 styles) + 1,000 synthetic variants of 250 of them.
Command: `pixplot bench` (separate catalogue `data/bench`).

| Configuration | Artist P@1 | Style P@1 | Genre P@1 | Variants R@1 | img/s | VRAM |
|---|---|---|---|---|---|---|
| DINOv2 B/14 @448 | 37.1 % | 41.1 % | 68.0 % | 98.8 % | 56 | 834 MB |
| DINOv3 B/16 @224 | 39.4 % | 46.7 % | 72.4 % | 99.6 % | 150 | 585 MB |
| **DINOv3 B/16 @448** (default) | 42.6 % | 49.3 % | 72.7 % | 99.6 % | 60 | 758 MB |
| DINOv3 L/16 @448 | **45.3 %** | **51.5 %** | 71.5 % | 99.5 % | 34 | 1,466 MB |

Chance: artist 2.9 %, style 10.0 %, genre 14.7 %.

- **Variants** (reversed engraving, black-and-white reproduction, cropped detail, altered
  copy): every configuration finds the original ~99 % of the time. Excellent in practice,
  but too easy to separate the models: real pairs (workshop copies, interpretive
  engravings) will be needed for a more discriminating test.
- **Estimated time for 500,000 works**: B@448 ≈ 2 h 20, L@448 ≈ 4 h, B@224 ≈ 1 h.
- Caveat: WikiArt labels are imperfect, and "same artist" is only an indirect indicator of
  what the historian is looking for.

## 10. Blind audit (16/11/2026)

The models only read pixels; metadata is used only for evaluation. `pixplot audit`
compares neighbourhoods and groups with the labels and produces
`data/audits/<analysis>/audit.md` (figures) and `audit.html` (examples of failures).

On WikiArt (DINOv3 B/16, 24 groups): group purity 26 % (artist), 38 % (style), 70 %
(genre). Four families of "failures", from examples examined one by one:

1. **Subject outweighs manner.** A Fauve portrait by Matisse has realist, expressionist and
   post-impressionist portraits as neighbours: same bust framing, palette ignored. The
   model sees *what is depicted and how it is composed* before colour and brushwork.
2. **Technique and medium bring works together.** A Warhol *Pop Art* drawing (a telephone
   in line) falls among drawings and Cubist still lifes; engravings and drawings cluster
   together whatever their style.
3. **Historiographical boundaries are not visual.** Mannerism ↔ Baroque, Early ↔ High
   Renaissance, Minimalism ↔ Colour Field: frequent confusions, but often real kinships.
   Pissarro's pointillism is filed with his impressionist landscapes — same artist, same
   motif; the divided touch is invisible at the analysis scale.
4. **The labels themselves are wrong.** Several "portraits" are actually genre scenes,
   figures in a landscape or a fresco with several saints; a "Minimalism" is a gestural
   abstraction. The model was right: the audit also **finds cataloguing errors**.

Leads (since implemented, § 12): a colour space and a "touch" space for styles defined by
colour or brushwork; several spaces side by side; flagging probably wrong labels to the
historian.

## 11. Scaling up: the full WikiArt corpus (16/11/2026)

81,444 images (72 Parquet files, 33.7 GB), RX 7900 GRE, native Windows, 16 GB of RAM.
Single command: `bash scripts/full_pipeline.sh data/wikiart81k` (timed log).

| Stage | Time | Note |
|---|---|---|
| Parquet extraction | 1 min 31 | |
| Ingestion (hash, thumbnails 64/256/1024) | 35 min 47 | 80,716 works, 728 exact duplicates, 0 errors |
| DINOv3 B/16 @448 | 14 min 17 | 96.8 img/s, 1.1 GB of VRAM |
| SigLIP 2 So400m @384 | 18 min 51 | 73.2 img/s, 5.1 GB of VRAM |
| Global indexes (flat) | 2 s | |
| Region index | 57 s | 1.58 M regions → IVF-PQ (nlist 5032, m 32) |
| Analysis (e-means 142 groups, UMAP, sheets) | 8 min 30 | 5 sheets of 4096 px, 32 px cells |
| Audit + benchmark | 1 min 10 | |
| **Total** | **≈ 1 h 21** | |

**Atlas**: all 80,716 thumbnails displayed at once; loads in ≈ 3 s (2 MB gzipped map,
35 MB of sheets), 144 frames/s at rest. With 142 groups the numbers overlapped: deck.gl
collision filter, larger groups drawn first. **Search**: 0.25 s per query (text or detail)
once the models are loaded; first call 15 to 27 s.

**Benchmark (P@1, k=10)** — more possible neighbours than with 2,263 works, hence higher
scores: DINOv3 artist 65.6 %, style 64.8 %, genre 80.9 %; **SigLIP 2 artist 73.0 %, style
71.4 %, genre 83.4 %**. On art-history categories, the text–image space retrieves better
than the purely visual one. The audit confirms § 10 (Fauvism 20 %, Pointillism 21 % at
P@10; Delacroix, Manet, Serov poorly retrieved).

**HDBSCAN does not scale on this corpus.** With the setting that gives 7 families and 1.6 %
"on their own" on 2,263 works, we get 692 micro-families and 52 % "on their own" on 80,716.
No middle ground: `min_cluster_size` 40 → 261 families / 53 % isolated; ≥ 100 → one block of
70 % of the corpus and 0.2 % isolated. WikiArt is a continuum without clear density gaps.
HDBSCAN remains an option (`--hdbscan`, with a warning above 30 % isolated); for isolated
works, the atypicality score (neighbour density) is the reliable signal.

## 12. Step 7: several ways of seeing, comparator, notebook, timeline (16/11/2026)

**Four similarity spaces.** Every completed `features` run is a "way of seeing" the corpus;
the Atlas record, the comparator and the MCP server (`similar_artworks`, `space`
parameter) let you choose:

| Space | Encoder | What it looks at | Speed at 81k |
|---|---|---|---|
| form | `dinov3_vitb16` (CLS) | shapes, composition, motifs | 97 img/s |
| subject | `siglip2_so400m` | what you would describe in words: subject, genre, school | 73 img/s |
| colour | `color_lab` | palette (CIELAB histogram 5×7×7, no GPU) | 127 img/s |
| touch | `dinov3_vitb16_texture` | brushwork: mean + standard deviation of layer-6 patches | 125 img/s |

"Colour" and "touch" are statistics: a common component would dominate every similarity,
hence **centring on the corpus mean** at the end of extraction (`center.npy` kept in the
run). The choice of layer 6 comes from a trial on 6,424 works balanced by style (layers 2
to 12, mean / standard deviation / both): middle layers see the brushwork, the last one
sees objects.

WikiArt benchmark on 80,716 works, P@10 (same label among the 10 nearest):

| | artist | style | genre | Pointillism | Fauvism | Ukiyo-e |
|---|---|---|---|---|---|---|
| form (DINOv3) | 50.8 % | 52.4 % | 76.8 % | 21 % | 20 % | 93 % |
| subject (SigLIP 2) | **61.6 %** | **62.0 %** | **79.5 %** | 44 % | 26 % | **99 %** |
| touch | 53.0 % | 49.6 % | 62.8 % | **62 %** | **30 %** | 80 % |
| colour | 15.0 % | 19.4 % | 30.3 % | | | |

Touch recognises the artist's hand better than form and genre much less well: exactly what
to expect from a view that ignores the subject. Colour alone classifies poorly, but answers
another question ("which works share this palette?").

**Group names** (`pixplot name-groups`): the centre of each group in SigLIP 2 space is
compared with a vocabulary of 34 subjects and 23 techniques or manners; the most
*distinctive* term (deviation from the mean over groups) among the 3 closest is kept.
Examples at 81k: « Scènes religieuses · icône » (Angelico), « Scènes nocturnes · estampe
japonaise » (Hokusai), « Batailles · gravure » (Doré), « Jardins · empâtements » (Monet).
Works without metadata; these are suggestions to review.

**Labels to check** (`pixplot suspects`, "À vérifier" panel, MCP tool `check_labels`):
≥ 70 % of the labelled neighbours (subject space) share another value, ≤ 10 % share the
work's own. At 81k: 506 artists, 2,771 styles, 1,607 genres. For artists it is mostly "who
looks like whom" (Sisley → Monet, Morisot → Renoir); for genres, real cataloguing errors
(religious scenes labelled "genre_painting"). Never an automatic correction.

**Comparator**: up to 6 works side by side, large, with metadata and the similarity of each
pair in each space. **Research notebook** (`<data>/notebook.sqlite`, separate from the
catalogue): works, selections, searches, details and comparisons, with a note, context and
Markdown export; the LLM can also write to it through MCP (`notebook_add`), identifying
itself.

**Timeline and geography**: offered when the metadata has dates (first readable year in
`date`, `year`, `datation`…) or `latitude` / `longitude`. Timeline: one block per period
(step chosen to fit the screen), works ordered by group, an "undated" block. Geography:
longitude / latitude without a base map (works offline), works from the same place laid
out in a spiral.

**IIIF importer** (`pixplot import-iiif`): v2 / v3 manifests and collections (nested,
paginated), image of the first canvas (or all) through the Image API at the requested size,
normalised metadata (title, artist, date, place, technique, rights, call number) in
`metadata.csv`, resume without re-downloading, one request at a time.

Real-world trial (16/11/2026): 18 paintings from the **Yale Center for British Art** (public
domain, 3.7 MB), all imported, full pipeline in 2 min 30. Lessons:
- the **Art Institute of Chicago** serves its images behind a Cloudflare bot check: any
  automated download is refused (403). We do not work around it; use another institution
  or their official exports;
- Yale gives **the date only in the label** ("Turner, 1775–1851, Dort, 1818"): it is
  extracted (last segment containing a year, never the life dates right after the name) and
  marked `date_source = déduite du libellé du manifeste` (inferred from the manifest label);
- the timeline then appears by itself (20-year blocks, 1740 → 1920);
- with 18 works, group names remain approximate (« Marines · aquarelle » for oils by
  Gainsborough and Turner): the vocabulary judges appearance, not the actual technique.


## 13. Interface: one map per way of seeing, world base map, ergonomics (16/11/2026)

**One map per way of seeing** (`pixplot maps`): the same PCA → UMAP projection computed in each
other space (`maps/<space>.npy` in the analysis run, aligned on `ids.npy`; ≈ 4 min per space
at 81k). The groups stay those of the main map, so a group can be followed from one map to
another. Its number is only shown where it stays compact (spread < 18 % of the map). At 81k:
38 of the 142 form groups stay compact on the subject map, almost none on the touch and colour
maps — the "form" groups are not "touch" groups.

**World base map** for the Geography layout: world-atlas TopoJSON (Natural Earth 1:110 M,
public domain, 108 KB) shipped in `web/vendor/` and decoded in the browser (works offline).

**Ergonomics**: header reduced to search + four tools (the map, display and colour settings
moved to a "Vue" menu), counters in a status bar on the map, panel widths proportional to the
window (group panel collapsible, panels overlaid below 1,100 px), right panel with a title and
a "Back" button to the list it was opened from, welcome screen on first visit, help (`?`) and
keyboard shortcuts (`/` search, `G` groups, `C` compare, `N` notebook, `V` labels to check, `0`
overview, `Esc` close). Checked at 1,920, 1,536, 1,366 and 1,024 px wide.

## 14. Pair benchmark: which way of seeing finds which kind of resemblance? (16/11/2026)

Label scores (§ 11) say whether neighbours share an artist or a style, not *why* two works
look alike. `pixplot pairs` scores each way of seeing on typed pairs: same subject but a
different composition, same composition but a different subject, same artist but a
different handling, different artists but comparable handling, same motif across periods,
same palette across traditions, documented filiation, and a control (nothing in common).
For each pair, in both directions, the exact rank of the twin among the whole corpus is
computed: R@10, R@100, median rank and **percentile** (share of the corpus farther away
than the twin; 0.5 = chance).

Two origins, always reported separately: pairs **annotated** by the art historian (the
"Annoter" button in the Atlas comparator, or `pixplot pairs add`, with a source and a
validated / proposed / rejected status), and pairs **drawn from metadata**
(`pixplot pairs generate`), numerous but coarse. File: `<data>/bench/pairs.csv`.

First result on WikiArt 81k, metadata pairs (percentile; 300 pairs per type, 250 for
handling, spread evenly over five styles):

| type | form | subject | colour | touch |
|---|---|---|---|---|
| same subject (genre), other artists and styles | 0.725 | **0.726** | 0.517 | 0.622 |
| same artist, other style | 0.691 | **0.790** | 0.596 | 0.660 |
| same handling style, other artists and genres | 0.793 | **0.831** | 0.625 | 0.803 |
| — Fauvism | 0.635 | 0.682 | 0.702 | **0.818** |
| — Pointillism | 0.735 | **0.847** | 0.671 | 0.819 |
| — Impressionism | 0.639 | **0.656** | 0.477 | 0.541 |
| control | 0.456 | 0.450 | 0.468 | 0.447 |

Reading: SigLIP 2 wins almost everywhere, but it learnt from web captions that name
styles and artists (and may have seen WikiArt): it recognises a label more than it sees a
handling. Touch wins clearly where the handling is striking (Fauvism) and fails on a style
as broad as Impressionism. Form barely separates "same subject" from the rest: a WikiArt
genre is too loose a category. Hence the next step: **annotated pairs** (filiations
described by Honour and Fleming, review in the Atlas), the only way to test composition
and palette, before adding new models (STELLAR, PE-Spatial).

**First annotated pairs** (11 pairs, "proposed" status, to be validated in the Atlas; 4
documented by Honour and Fleming, pp. 671, 672, 709 and 772, the others from outside the
book). Exact copies and borrowed compositions are found at rank 1–2 by both form and
subject (Raphael ← Perugino *Marriage of the Virgin*, Van Gogh ← Millet *The Sower*,
Manet ← Goya *Maximilian*); as soon as the artist transforms the model (Picasso ← El
Greco, Picasso ← Delacroix *Women of Algiers*, Van Gogh's fragment after Rembrandt's
*Lazarus*), no way of seeing follows it. Form alone finds Manet's quotation of the
*Pastoral Concert* from the *Déjeuner* (rank 8). Colour finds no filiation: a copy changes
its palette. This is exactly what a new composition model (STELLAR) should be tested on.
See the French version for the full rank table.
