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
- **MCP server** (`pixplot mcp`, stdio, official `mcp` 2.x SDK): 16 tools —
  `corpus_overview`, `search_by_text`, `similar_artworks` (with a `space` parameter),
  `search_detail`, `search_zones`, `get_artwork`, `view_artwork`, `view_detail`, `compare_artworks`, `why_similar`,
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
├── web/                   ⑥ Atlas: index.html, atlas-*.js, atlas.css, vendor/deck.gl
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

What comes next (Leiden groups, disagreements between ways of seeing, searching a region with words, Iconclass, composition) is in [ROADMAP.md](ROADMAP.md).

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

## 15. Leiden groups: nested, per way of seeing (16/11/2026)

`pixplot communities` computes, for each way of seeing, Leiden communities on the graph of
the 15 nearest neighbours (weighted by similarity): **groups** (as many as e-means, for a
fair comparison; resolution found by bisection) and **families** (Leiden on the graph of
groups: a family is always a union of groups). Communities under 5 works are merged into
the most connected neighbour. In the Atlas, "Vue" menu → colour: "Familles Leiden" and
"Groupes Leiden" for each way of seeing.

Comparison on WikiArt 81k, 142 groups, three seeds per method (stability = mean adjusted
Rand index between seeds; labels = normalised mutual information):

| way of seeing | method | stability | artist | style | genre | time |
|---|---|---|---|---|---|---|
| form | e-means | 0.522 | 0.379 | 0.276 | 0.386 | 5 s |
| form | Leiden | **0.645** | **0.400** | 0.277 | 0.390 | 40 s |
| subject | e-means | 0.573 | 0.508 | 0.374 | 0.409 | 7 s |
| subject | Leiden | **0.675** | 0.504 | 0.364 | 0.404 | 39 s |
| touch | e-means | 0.423 | 0.360 | 0.225 | 0.243 | 8 s |
| touch | Leiden | **0.528** | **0.437** | **0.266** | 0.263 | 41 s |
| colour | e-means | **0.423** | 0.197 | 0.086 | 0.084 | 2 s |
| colour | Leiden | 0.355 | 0.198 | 0.085 | 0.083 | 22 s |

Leiden is clearly more stable for form, subject and touch, and as good or better on labels,
especially for touch (artist: 0.36 → 0.44). Colour is the exception: a palette histogram
has no clear communities, and e-means stays more stable there. Group sizes are more uneven
(26 to 2,036 works for form, against 140 to 1,190): they follow the corpus instead of
equalising it. On pairs the differences are within noise (only 11 annotated pairs): to be
redone with the validated pairs of step 0.12.

Decision: the roadmap criterion is met for form, touch and subject, not for colour. Leiden
groups are available for every way of seeing; the Atlas's **named** groups stay e-means
until names, the groups panel and labels-to-check are ported to Leiden (next step).

## 16. Disagreements between ways of seeing, and pair review (16/11/2026)

`pixplot disagreements` finds, for each couple of ways of seeing, pairs of works that are
very close in one (rank ≤ 5 among neighbours) and far in the other (percentile < 0.35,
estimated on a fixed sample of 2,048 works). A work may appear only twice per list,
otherwise a few "hub" images would fill it; 300 pairs are kept per couple. In the Atlas:
**Désaccords** button (key D).

On WikiArt 81k, the number of candidate pairs tells how much two ways of seeing agree: form
and subject almost always (321 pairs close in form but far in subject, 87 the other way),
touch a little less (≈ 2,000 to 3,700), colour very little (18,000 to 52,000: the same
composition can have any palette). Examples: close in subject but far in form, Warhol's
*Chanel No. 5* and *Coca-Cola* (product images); close in form but far in subject,
pointillist canvases of different subjects (handling outweighs form).

The **À vérifier** button now has two tabs: labels contradicted by the neighbours, and the
proposed **reference pairs**, to validate or reject in one click (with "Comparer" to look at
them side by side). Only validated pairs count in `pixplot pairs bench`. The success
criterion of step 0.12 (≈ 100 validated pairs covering the eight types) depends on this
review, which is the art historian's work.

## 17. Quick pair review, Anki-style (16/11/2026)

Reviewing a list of pairs card by card was too slow. **Quick review** (key R in the Atlas, or
the button in the "Paires de référence" tab) shows one pair at a time, large, and each
decision is one key: Enter validates with the suggested kind of resemblance; 1 to 7 validate
as same subject, same composition, same hand, same handling, same motif, same palette,
filiation; R rejects (proposed pair) or marks "no link" (candidate); Space skips; Z undoes
the last decision; Escape quits.

The queue starts with proposed pairs, then **candidates** drawn from disagreements between
ways of seeing, alternating the couples of ways of seeing; the default kind of resemblance
depends on the way of seeing that brings the pair together (form → same composition,
subject → same subject, touch → same handling, colour → same palette). A validated
candidate becomes an annotated pair (source "relecture : désaccord forme > sujet"); a
dismissed one is logged in `bench/review_log.csv` and never comes back. At the top: progress
towards 100 validated pairs and the count per kind, to see which are missing.

## 18. First benchmark on 104 validated pairs (16/11/2026)

104 pairs validated by the art historian (plus 1 rejected and 23 dismissed candidates): 36 "same
subject", 26 "same palette", 16 "same handling", 14 "same composition", 9 filiations, 2 "same
motif", 1 "same hand". 10 come from Honour and Fleming or well-known filiations, 94 from the
quick review of disagreements between ways of seeing.

**A bias to correct.** A pair drawn from a disagreement was chosen because one way of seeing
brought it together and another pulled it apart: those two ways of seeing won or lost in
advance. For these pairs, only the two ways of seeing not used to choose them are measured
("neutral" ways of seeing). Mean percentile of the twin (0.5 = chance, 1 = nearest):

| kind of resemblance | form | subject | colour | touch |
|---|---|---|---|---|
| same subject, other composition | 0.950 | **0.966** | 0.369 | 0.847 |
| same composition, other subject | 0.675 (3) | **0.992** | 0.537 | 0.887 |
| other artists, comparable handling | 0.830 | 0.745 | 0.626 | **0.886** (3) |
| same palette, other traditions | 0.539 | 0.390 | **0.719** | 0.570 |
| filiation (book pairs, unbiased) | 0.993 | **0.997** | 0.626 | 0.890 |

In brackets: fewer than 5 pairs. Each way of seeing wins on the kind of resemblance it is meant
to see, except "same composition", where subject wins: SigLIP 2 also describes the layout ("a
temple on a square"), and too few pairs measure form without bias. Colour is below chance for
"same subject": two treatments of one theme change palette.

**Leiden against e-means, on pairs** (share of validated pairs in the same group, 142 groups):
form 24.0% → **32.7%**, subject 16.3% → **26.0%**, touch 19.2% → **26.0%**, colour 11.5% = 11.5%.
This confirms § 15: Leiden follows the kinships the art historian recognises better, except for
colour.

**The criterion of step 0.12** (≈ 100 validated pairs covering the eight kinds) is met in number,
not in coverage: "same hand" (1) and "same motif" (2) still need more, and more "same
composition" pairs outside disagreements are needed to judge form.

## 19. Searching a region with words: TIPSv2 evaluated, not adopted (16/11/2026)

Question: can one type "a halo" or "the church tower in the left background" and find the
**region** that answers it across the corpus? Benchmark `pixplot zonebench` on the test split of
RichArt (ICMR 2026, CC BY-NC 4.0, local use): 709 paintings, 1,243 objects described by museum
catalogues, 2,174 boxes; two queries per object (its short name, its catalogue sentence of ~35
words). Methods: SigLIP 2 on the cropped region, TIPSv2 on the cropped region, TIPSv2 "dense"
(one pass on the whole painting, mean of the 14-px region vectors inside the box); TIPSv2 in two
sizes, B/14 and SO400m/14 (same size as SigLIP 2).

**Finding the region among 2,174** (R@1 / R@10 / median rank): SigLIP 2 on crops wins clearly —
name 16.0% / 43.8% / 17, sentence **28.2% / 61.1% / 5**; TIPSv2 SO400m on crops: sentence 20.4% /
47.9% / 12; TIPSv2 B/14 on crops: 15.1% / 41.7% / 19; TIPSv2 dense: 13.3–15.4% / 38.6–41.0%.

**Pointing at the region in its painting**: TIPSv2 B/14 61.9% (name) and 56.6% (sentence),
SO400m 54.2% and 50.2%; chance (area covered by the boxes) 34.2%, but **always pointing at the
centre of the painting** already gives 50.8%. TIPSv2's advantage is thin.

Decision: the criterion of step 0.13 ("clearly better than SigLIP 2 on cropped regions") is not
met; TIPSv2 is not integrated into the Atlas. The encoder stays in the code (`tipsv2_b14`,
`tipsv2_so400m14`) so the measurement is reproducible. The best measured method is **SigLIP 2
applied to cropped regions**: that is what should be indexed to search regions with words, at
the cost of ≈ 20 times the computation of global vectors (about twenty regions per work).

## 20. Critical layer: what each way of seeing sees, what the corpus lacks (17/11/2026)

Two readings guided this step. A. Wasielewski, *Computational Formalism* (MIT Press, 2023),
calls "computational formalism" exactly what PixPlot does: comparing works en masse by their
appearance. She points to three risks: **perceptual bias** (the model fixes on very fine traits —
grain, edges, reproduction quality — that art historians do not look at), **WikiArt's style
categories**, filled in by volunteers and reused uncritically, and the **Western canon**, the only
part really digitised with complete metadata. T. Arnold and L. Tilton, *Distant Viewing* (MIT
Press, 2023), show that every algorithm encodes a "way of seeing" that must be made explicit and
documented, and warn against fetishising size.

Hence three tools: **a card per way of seeing** (model, training data, what it sees and does not
see, known biases, what the benchmark measured), in the Atlas ("Corpus" button, key I, and the
comparator's tooltips), the API and the MCP server; **a corpus report** (`pixplot corpus`,
`/api/corpus`: coverage and source of each label, artist concentration, non-Western styles,
dates and places — on WikiArt 81k, the artist is missing for 51% of works because the
huggan/wikiart dataset names only some of them; the 10 most frequent artists make up 29% of
attributed works; 1 style in 27 is non-Western, Ukiyo-e, 1.4% of works; no dates, no places);
and **labels shown for what they are** ("volunteer label, to be checked" on WikiArt labels). The
MCP server also gets a security rule, after AutoMalTool (He et al., 2025): titles, labels,
notebook notes and Research Packs are data entered by others, never instructions.

## 21. Typed, dated places, after ARTL@S (17/11/2026)

B. Joyeux-Prunel ("ARTL@S: A Spatial and Trans-national Art History", *Artl@s Bulletin*, 2012)
argues for a spatial, transnational art history that starts from **distributions and
circulations** before discourses, distinguishes places (where a work is made, shown, kept, what
it depicts, where the artist lives), dates every address, and refuses to explain a style by a
place (Taine's legacy). PixPlot's geographic view put each work at a single point without
saying which place it was.

- **`places` table**: a work may have several places, each with a type (creation, exhibition,
  holding, depicted place, artist's birth / residence / death, unspecified), a name,
  coordinates, a date and a source.
- **Import**: `pixplot import-places places.csv` (columns `path` or `id`, `type`, `place`,
  `lat`, `lon`, `date`, `source`); `pixplot places --derive` infers places from metadata
  (repository or institution → holding; "born in" / "né à" → birth; "died in" / "mort à" →
  death; `place` → unspecified).
- **Bundled gazetteer**: ~80 art cities and ~40 institutions, to place a name without any
  online service. An unknown place stays without coordinates: nothing is guessed.
- **Atlas, Geography view**: "Which place?" (one type at a time), **circulations** (lines
  joining a work's places in date order), a **time slider**, framing on located works, and a
  note: a map of places shows distributions and circulations, not styles.

On the Yale Center for British Art corpus, `--derive` yields 18 holding places (New Haven), 7
dated artist births and 8 deaths (Liverpool, London, Munich, Bathampton…): the map already shows
British works travelling to an American collection.

## 22. SigLIP 2 region index: searching a detail with words (17/11/2026)

The logical follow-up to § 19: since SigLIP 2 applied to **cropped regions** is the best method
measured on RichArt, `pixplot zones` cuts each work along 2 × 2 and 4 × 4 grids (20 regions, a
quarter or a sixteenth of the work), runs each region through SigLIP 2 and indexes them.

- **Extraction** (GPU, resumable, log in `<data>/zones.log`): regions cut from the 1,024-px
  thumbnails, letterboxed to the model's input without cropping, vectors kept in float16
  (`features/zones_*`, 3.7 GB for 80,716 works).
- **Index** (`index/textzones_*`): PCA to 256 dimensions, float16 FAISS index. Projected vectors
  are **not renormalised**: the dot product with a sentence is then q·v − q·mean, whose second
  term is the same for all regions, so the ranking is preserved. The best candidates are then
  **re-ranked exactly** with their original vectors: on the test corpus the top five results
  match a full computation for every query tested.
- **Atlas**: **"Zone décrite"** search mode ("a halo", "a skull", "a blessing hand"); each
  result shows the cropped region. `/api/search/zones` API, `search_zones` MCP tool (15 tools).
- Region runs are excluded from feature listings (`list_runs`): they are not ways of seeing, and
  text search must never mistake them for whole-work vectors (a bug found in testing and fixed).

**On WikiArt 81k** (2026-11-17): 1,614,320 regions for 80,716 works, computed in one go in 6 h 21
on the RX 7900 GRE (71 regions per second, no errors); PCA keeps 92% of the variance; the index
weighs 818 MB (original vectors 3.5 GB). A search answers in 0.5 s. Trials: "a halo around a
saint's head" → six halos, including radiant ones; "a skull" → six skulls, painted or engraved;
"a hand holding a letter" → six hands holding a letter; "a sailing ship" → sailing ships.

## 23. Naming groups with Iconclass (17/11/2026)

[Iconclass](https://iconclass.org) (H. van de Waal, 1972-1985) is the iconographic
classification used by museums: about 40,000 coded concepts, from "25H landscape" to "73A5
the Annunciation", with French labels. The data is CC0 (`pixplot iconclass --fetch`, into
`data/iconclass/`, not versioned).

- **Method** (as in § 12, with Iconclass instead of our lexicon): each concept is described
  to SigLIP 2 by its cleaned English label ("a painting of the Annunciation"); each group
  centre is compared with the concepts; among the 10 closest, the 3 that most distinguish
  the group from the others are kept (deviation from the mean over groups, in standard
  deviations: z).
- **Concepts kept** (17,126 of 40,712): no "keys" (doubled letters, "31AA" = female
  version), at most 7 characters, proper names only for saints and species, no literature
  (81-83), Bible and mythology limited to 4 characters ("73A5" yes, the detailed episode
  no), no Ripa allegories, no entry without a French name.
- **Confidence**: z ≥ 4 "sure", 3 to 4 "possible", nothing shown below. Thresholds checked
  on WikiArt 81k: above 4 the name is almost always right; below 3 Iconclass has no word for
  the group (portraits, abstraction) and forces one ("journalist", "graphology test").
- **Atlas**: under the group name, the Iconclass concept(s) with their code, linked to
  iconclass.org (solid border: sure; dotted: possible). API: `iconclass` field of groups;
  MCP: `corpus_overview` and `get_group`.

**On WikiArt 81k**: 142 groups, 37 "sure", 47 "possible", 58 with no concept shown;
encoding and naming in 76 s. Iconclass **complements** the lexicon: more precise on subject
("47D31 windmill", "25G41 water-lily", "25H154 clearing", "26C32 storm at sea", "42B742
mother and child", "11D356 Christ crucified"), silent on manner, portraiture and
abstraction, which the lexicon names better. Typical remaining errors: Hokusai's wrestlers →
"43C393 jiu-jitsu, judo", specific saints on altarpieces ("Philip Neri").

**Review by the historian** (2026-11-19, `bench/wikiart81k_iconclass_review.csv`): the 84 groups with an
Iconclass name were judged, current name (A) against the Iconclass proposal (B), on
six typical works per group; 83 answers.

| | B Iconclass better | equivalent | A current better | both wrong |
|---|---|---|---|---|
| all (83) | **39 (47 %)** | 17 | 24 (29 %) | 3 |
| "sure" (37) | **21 (57 %)** | 4 | 12 (32 %) | 0 |
| "possible" (46) | **18 (39 %)** | 13 | 12 (26 %) | 3 |

On decided answers, Iconclass wins 39 to 24 (one-sided sign test: p = 0.04). **Roadmap criterion met**:
Iconclass names are judged more accurate. They are added to the current name without replacing it: the
lexicon is still better in one group in three (often handling, portraiture, abstraction), and the "sure"
threshold is confirmed as the most reliable.

## 24. Composition: PE-Spatial evaluated, not adopted (18/11/2026)

Step 0.15. Question: does a "spatial" model, or a cell-by-cell comparison, find a work that reuses
the **layout** of another (same composition, different subject) better than an existing regard?

- **Candidates.** [PE-Spatial B/16](https://huggingface.co/timm/vit_pe_spatial_base_patch16_512.fb)
  (Meta, 2025, Apache 2.0, via `timm`), vectors computed for all 80,716 works (68 images/s, 1.4 GB of
  GPU memory, about 20 min): global vector = mean of patches. And, for PE-Spatial and DINOv3, a **4×4
  layout**: the work as 16 cells, each compared with the cell at the same place in the other work
  (mean of the 16 cosines). STELLAR (Microsoft) was not tried: trained on ImageNet only, it had no
  expected advantage over DINOv3.
- **Measure.** `pixplot composition`: the user-validated pairs (§ 18), exact ranks over the whole
  corpus, both directions, as in `pixplot pairs bench`.
- **Review by Codex** (OpenAI, first two-assistant job): cell slicing, rank computation and work
  alignment checked; two fairer variants suggested and measured: global vector **over the work only**
  (without the bands added to square it) and layout **over the cells filled in both works** (two
  different formats are no longer penalised).

| "Same composition, different subject" (14 pairs, 28 queries) | in top 10 | in top 100 | median rank |
|---|---|---|---|
| **Form (DINOv3), current regard** | **54 %** | **71 %** | **8** |
| Form, work only | 18 % | 46 % | 203 |
| Form, 4×4 layout (common cells) | 0 % | 32 % | 332 |
| PE-Spatial, 4×4 layout (common cells) | 7 % | 29 % | 286 |
| PE-Spatial, global | 4 % | 29 % | 960 |
| PE-Spatial, global over the work only | 11 % | 25 % | 1,406 |
| Subject (SigLIP 2) | 21 % | 29 % | 814 |

**Conclusion: PE-Spatial is not adopted, nor is the 4×4 layout.** DINOv3's global regard remains
clearly the best at finding the same composition. The cell-by-cell comparison fails because a reused
composition is rarely in the same place: shifted, cropped or in another format, it no longer falls in
the same cells. One nuance: DINOv3's 4×4 layout fails badly less often (centile 0.958 vs 0.928),
without ever putting the twin first. On attested filiations (18 queries) all variants are within a
few ranks of each other; the sample is too small to separate them.

PE-Spatial vectors stay on disk for benchmarks (`features/pe_spatial_b16_*`), but the Atlas and the
MCP server do not offer them as a regard (`NOT_KEPT` in `api/spaces.py`). Limit: 14 "same
composition" pairs; a broader conclusion would need more validated pairs, and a grid aligned on the
work rather than on the square (new computation).

## 25. "Why do these two works look alike?" (19/11/2026)

In the comparator, a pair's **"Pourquoi ?"** button draws on both images the zones that answer each
other most, with the same number and colour, and a legend with figures. The aim: to make a computed
proximity open to discussion, by showing what the regard relies on.

- **Computation** (`pixplot/analysis/correspondences.py`, API `/api/correspond`): for a regard that
  keeps region vectors (today form, DINOv3), each work is cut into 16 cells (4×4); the 16×16 cosines
  between the cells of the two works are computed and **mutual matches** are kept (each is the other's
  nearest). They are ranked by what sets them apart: the cosine minus the two cells' mean similarity
  to all others, so that two ordinary backgrounds do not come first. Cells that fall in the bands added
  to square the work are excluded; boxes are mapped back to the image.
- **Cost**: nothing in advance, a few milliseconds on demand (region vectors already exist).
- **Example** (validated "same composition" pair): Raphael, *Marriage of the Virgin*, and Perugino,
  *Delivery of the Keys*: the zones found are the central temple and the groups of figures in the
  foreground, in both works. On Rubens's copy after Titian's *Rape of Europa*, the four zones are at
  the same places in both paintings.
- **Limits**: a fixed grid, aligned on the square rather than the work; a cell of a very wide format
  covers a tall band of the image. The regard compares shapes: it is for the historian to say whether
  the zones share a motif, a pose, a composition, or only a similar background.

## 26. Three integrated readings: conceptual axes, visual measures and critical layer (19/11/2026)

Three recent readings were integrated directly into the code, the Atlas and the MCP server:

1. **2D conceptual axes, after *2D CLIP* (L. Impett and F. Offert, "There Is a Digital Art
   History", *Visual Resources*, 38:2, 2024).** The authors argue that a multimodal model carries a
   "vector imaginary" and that reading a corpus through the model always means reading the model
   through the corpus as well. The Atlas now offers a **Conceptual axes (2 words)** layout
   (`/api/layout/concepts`, MCP tool `probe_concepts`) that projects the entire corpus along two
   SigLIP 2 text prompts (normalised by p1–p99 percentiles), with the `X = Y` diagonal and the works
   that deviate most from it.
   - **Measured on WikiArt 81k (80,716 works)**: **582 to 592 ms** warm per pair of words (after
     initial SigLIP 2 loading), with no precomputation.
   - **Revealing examples**: `naked` / `nude` yields a strong correlation (`r = 0.87`) with clear
     off-diagonal deviations mirroring Fig. 8 of the paper; `linéaire` / `pictural` (Wölfflin's axes,
     discussed in Stork § 9.1) gives `r = 0.16` and cleanly separates geometric Minimalism from
     atmospheric Romanticism/Expressionism (Aivazovsky); `sacré` / `profane` (`r = 0.41`) directly
     demonstrates Impett and Offert's thesis: the works pulled most strongly toward "sacré" away
     from "profane" are Parisian cityscapes by Édouard Cortès — because "sacré" triggers
     "Sacré-Cœur" in the web's vector imaginary.
2. **Explicit neural-free visual measures, after D. G. Stork (*Pixels & Paintings: Foundations of
   Computer-assisted Connoisseurship*, Wiley, 2024).** `pixplot/analysis/connoisseur.py`
   (`/api/artwork/{id}/measures`, collapsible **Visual measures** block on the artwork card, MCP
   tool `measure_artwork`) computes on demand: lightness and saturation barycentres plus local
   sub-window barycentre spread (§ 9.3, Park 2019), left–right symmetry (§ 9.3.1), tonal dynamics
   (§ 1.5.3), and chromatic Shannon entropy `H(C)` with the optimal horizontal or vertical
   compositional split (§ 9.5.1, Alg. 8, Lee et al., PNAS 2020).
   - **Measured on WikiArt 81k**: **14.5 ms** per work on average across 100 thumbnails (256 px,
     100 % CPU). An initial adaptive-quantisation (`MEDIANCUT`, 16 colours) version compressed
     entropy near its ceiling (~3.9–4.0 bits); switching to a fixed 4 × 4 × 4 colour grid (64 bins,
     max 6 bits) spreads entropy from **0.07 to 3.52 bits** (median 1.56): 0.02 bit for a
     monochrome Dürer sketch (`#101`) versus 3.31 and 2.80 bits for the Rubens / Titian pair
     (`#64269` / `#67405`), whose lightness barycentres align (`[0.52, 0.44]` vs `[0.53, 0.47]`).
   - **Limits**: these figures describe the *digital reproduction* (resolution, varnish, white
     balance) and carry no normative judgement ("balanced" never means "better").
3. **Expanded critical layer, after J.-L. Giavitto and P. Saint-Germier (eds.), *L'art au temps de
   l'IA* (Centre Pompidou, 2025).** The **Corpus** panel (`critique.PRINCIPLES`, `/api/corpus`,
   `corpus_overview` and MCP instructions) incorporates three safeguards: a latent distance is only
   meaningful *relative* to the corpus and never replaces the performative act of human expertise
   (S. Bureau and G. Doras); text–image models reduce the visible to the "sayable" (M. Lista, after
   A. Somaini and H. Steyerl); digitised reproductions carry their material conditions of capture
   (F. Ebner and O. Frydryszak-Rétat).

## 27. Copy detection: SSCD evaluated, not adopted as a default regard (19/11/2026)

Question: does a dedicated **copy-detection** model (SSCD) merit becoming a fifth regard for finding
attested filiations (copies, replicas, prints after paintings)?

- **Candidate and licence.** [SSCD](https://github.com/facebookresearch/sscd-copy-detection) (*A
  Self-Supervised Descriptor for Image Copy Detection*, Pizzi et al., Meta, CVPR 2022, **MIT
  licence**), `sscd_disc_large` variant (ResNeXt-101 32×4d, 1,024 dimensions, trained on DISC with
  advanced augmentations and mixup; standalone TorchScript weights stored locally in
  `data/wikiart81k/models/`, never in git). Input: full work letterboxed to 320 px (the square size
  recommended by the repository for GPU batch inference), ImageNet normalisation.
- **Extraction.** `pixplot/encoders/sscd.py`, computed on all 80,716 WikiArt 81k works
  (`features/sscd_disc_large_20261119-184816`): **4 min 41 s**, **274.9 images/s**, **926 MiB** GPU
  memory (RX 7900 GRE, FP16), **0 failures**.
- **Measure.** `pixplot pairs bench --spaces forme,sujet,couleur,touche,copie` on the **104
  historian-validated pairs** (`bench/wikiart81k_pairs.csv`, 208 queries, exact ranks in both
  directions). A **centred** variant (corpus mean subtracted then L2-normalised, as recommended by
  the SSCD repository) was also measured in memory.

| "Attested filiation (copy, citation, model)" (9 pairs, 18 queries) | R@10 | R@100 | median rank | centile |
|---|---|---|---|---|
| **Subject (SigLIP 2)** | **38.9 %** | **66.7 %** | **25** | **0.997** |
| **Form (DINOv3)** | **38.9 %** | **66.7 %** | **26** | **0.993** |
| Copy (SSCD raw) | 33.3 % | 44.4 % | 216 | 0.902 |
| *Copy (SSCD centred, in-memory test)* | *33.3 %* | *50.0 %* | *108* | *0.904* |
| Touch (DINOv3, layer 6) | 16.7 % | 27.8 % | 578 | 0.902 |
| Colour (CIELAB) | 0.0 % | 0.0 % | 17,656 | 0.557 |

Across the other validated categories, SSCD trails the dedicated regards by a wide margin:

| Validated category (n queries) | SSCD R@10 | SSCD median rank | Best current regard (R@10 · median rank) |
|---|---|---|---|
| Same subject, different composition (72) | 4.2 % | 27,374 | Subject (37.5 % · 30) |
| Same composition, different subject (28) | 7.1 % | 13,736 | Form (53.6 % · 8) |
| Different artists, comparable handling (32) | 0.0 % | 6,952 | Touch (31.2 % · 136) |
| Same palette, different traditions (52) | 0.0 % | 32,982 | Colour (50.0 % · 10) |
| Same iconographic motif, different period (4) | 0.0 % | 5,612 | Subject (50.0 % · 26) |
| Same artist, different handling (2) | 0.0 % | 53,312 | Colour (100.0 % · 2) |

On the 600 "control" metadata queries (disjoint artist, style and genre), SSCD has median rank
40,528 (centile 0.490, almost exact chance), reflecting its differential-entropy regularisation.

**Pair-by-pair reading of the 9 filiations.** SSCD ranks literal, geometrically faithful copies at
the very top: Van Gogh / Millet (*The Sower*, ranks 1 and 1), Raphael / Perugino (*Marriage of the
Virgin*, ranks 1 and 1), Manet / Titian (*Olympia* ← *Venus of Urbino*, ranks 6 and 3; centred 1
and 3 — the only case where SSCD clearly beats Form [4, 23] and Subject [4, 58]). Outside the
validated set, on the proposed Rubens / Titian pair (*Rape of Europa*), SSCD also gives (1, 1), but
Form and Subject already achieve (1, 1). As soon as a filiation involves free reinterpretation,
mirroring, cropping a fragment or changing medium — Manet / Goya (110, 983), Manet / Giorgione–Titian
(323, 461), Monet / Manet (803, 732), Picasso / El Greco (13,406, 21,382), Van Gogh after Rembrandt's
etching (60,102, 44,044) — SSCD pushes the source far down: it is trained to separate anything that
is not near-identical.

**Conclusion: SSCD is not adopted as a default fifth regard.** Form (DINOv3) and Subject (SigLIP 2)
already recover literal copies and handle artistic reinterpretations far better. The vectors stay on
disk (`features/sscd_disc_large_*`) for benchmarks (`pixplot pairs bench --spaces …,copie`), while
the Atlas and MCP server keep SSCD hidden (`NOT_KEPT` in `pixplot/api/spaces.py`).

**Limits and secondary use.** The validated filiation sample is small (9 pairs mixing direct copies
and free reinterpretations, with no dedicated set of reproductive prints yet). On the other hand, a
random sample of 2,000 WikiArt 81k works shows **2.6 %** (52/2,000) have another work at SSCD cosine
≥ 0.75 (including re-encoded JPEG near-duplicates carrying conflicting metadata that slip past
`ingest`'s SHA-256 check): SSCD could therefore serve later as a **perceptual deduplication** tool
at ingest time rather than as an art-historical regard.

## 28. Depth-based composition: Depth Anything V2 evaluated, not kept (19/11/2026)

Question (follow-up to § 24): after PE-Spatial and 4 × 4 spatial layouts failed to beat Form
(DINOv3) on "same composition, different subject", does the arrangement of **depth planes**
(foreground, midground, background) add a signal that Form misses?

- **Candidate and licence.** [Depth Anything V2 Small](https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf)
  (Yang et al., NeurIPS 2024, DINOv2 ViT-S/14 backbone + DPT head, loaded via `transformers`,
  **Apache 2.0 licence** verified on the Hugging Face model card). Base and Large are released under
  CC BY-NC 4.0 and were excluded. Weights stay in the local Hugging Face cache, never in git.
- **Descriptor (`pixplot/encoders/depth.py`).** Each full artwork is letterboxed (ImageNet
  normalisation) at the model's native 518 px resolution (37 × 14). The predicted relative depth map
  (affine-invariant disparity: higher = closer) is **cropped to the artwork's content box alone** —
  letterbox padding bands are completely discarded, which also addresses § 24's limitation of a grid
  aligned on the padded square rather than the artwork. It is then average-pooled onto an **8 × 8
  grid** (64 values), mean-centred and L2-normalised per artwork (unit-norm z-score): the vector is
  strictly invariant to any positive affine transform $a \cdot d + b$ ($a > 0$), and cosine
  similarity between two artworks equals the exact Pearson correlation between their 8 × 8 depth
  grids. Z-scores were chosen over ranks for simplicity and alignment with the model's training
  loss; both variants (and corpus centring) were measured.
- **Extraction.** Computed on all 80,716 WikiArt 81k works
  (`features/depth_anything_v2_small_20261119-191351`, log `data/wikiart81k/depth.log`):
  **14 min 3 s**, **95.7 images/s**, **3,082 MiB** GPU memory (RX 7900 GRE, FP16, batch size 32),
  **0 failures** and 0 degenerate flat maps.
- **Measure.** `pixplot composition` and `pixplot pairs bench --spaces forme,sujet,couleur,touche,profondeur`
  on the **104 historian-validated pairs** (208 queries, exact ranks across 80,716 works). Three
  in-memory variants were also evaluated: **corpus-centred** (corpus mean grid subtracted then
  L2-renormalised), **rank-normalised** (Spearman correlation across the 64 cells) and
  **corpus-centred ranks**.

| "Same composition, different subject" (14 pairs, 28 queries) | R@10 | R@100 | median rank | centile |
|---|---|---|---|---|
| **Form (DINOv3), current regard** | **53.6 %** | **71.4 %** | **8** | **0.928** |
| Form, 4 × 4 layout (shared cells, § 24) | 0.0 % | 32.1 % | 332 | 0.958 |
| PE-Spatial, 4 × 4 layout (shared cells, § 24) | 7.1 % | 28.6 % | 286 | 0.878 |
| Subject (SigLIP 2) | 21.4 % | 28.6 % | 814 | 0.738 |
| Touch (DINOv3, layer 6) | 10.7 % | 32.1 % | 1,017 | 0.857 |
| **Depth (Depth Anything V2 Small, raw 8 × 8)** | **3.6 %** | **7.1 %** | **13,754** | **0.677** |
| *Depth corpus-centred (in-memory test)* | *3.6 %* | *7.1 %* | *6,874* | *0.682* |
| *Depth ranks / Spearman (in-memory test)* | *3.6 %* | *3.6 %* | *13,424* | *0.640* |

Across all other validated categories, Depth likewise trails the dedicated regards by a wide margin
(and stays close to chance on metadata pairs: centile 0.544–0.552, control 0.479):

| Validated category (n queries) | Depth R@10 | Depth median rank (centred) | Best current regard (R@10 · median rank) |
|---|---|---|---|
| Attested filiation (18) | 11.1 % | 14,889 (11,784) | Subject (38.9 % · 25) / Form (38.9 % · 26) |
| Same subject, different composition (72) | 2.8 % | 32,444 (32,471) | Subject (37.5 % · 30) |
| Different artists, comparable handling (32) | 0.0 % | 28,682 (28,509) | Touch (31.2 % · 136) |
| Same palette, different traditions (52) | 0.0 % | 51,211 (43,698) | Colour (50.0 % · 10) |
| Same motif, different period (4) | 0.0 % | 41,282 (—) | Subject (50.0 % · 26) |
| Same artist, different handling (2) | 0.0 % | 30,958 (—) | Colour (100.0 % · 2) |

**Why standalone depth fails: two measured effects.**
1. *A universal vertical gradient dominates the corpus.* Across all 80,716 works, the corpus-mean
   8 × 8 grid rises strictly from top (−0.108: sky, wall, background) to bottom (+0.181: ground,
   foreground). Two random paintings already share an average raw cosine of **0.539** (vs 0.175 in
   Form). Subtracting this corpus mean brings random cosine down to **0.016** and halves median rank
   on "same composition" (13,754 → 6,874; filiation 14,889 → 11,784, centile 0.809), yet still
   fails to bring pairs into the top 100. Rank normalisation (Spearman) performs slightly worse than
   z-scores (centile 0.640 vs 0.677).
2. *A photography-trained 3D model breaks on non-perspectival art.* Pair-by-pair inspection shows
   that depth works on figurative compositions with crisp spatial planes: Van Gogh / Millet (*The
   Sower*, filiation: ranks **3 and 1**, cosine 0.948), the proposed Rubens / Titian pair (*Rape of
   Europa*: ranks **1 and 1**, cosine 0.987), Perugino (*Delivery of the Keys* ↔ *Marriage of the
   Virgin*: ranks 1,285 and **85**; centred 433 and 86), or Michelangelo / High Renaissance
   (`24374 ↔ 54823`: ranks **7** and 6,183; centred 9 and 950). On flat, decorative or modern works,
   however (Pop Art `65822 ↔ 71779`: ranks 68,987 and 80,552; Chagall / Expressionism
   `22435 ↔ 60995`: 79,814 and 79,803; Expressionism / Pop Art `48392 ↔ 76646`: 75,807 and 64,679),
   the model hallucinates arbitrary depth planes from tonal contrast and pushes the pair to the very
   bottom of the corpus. Even between two perspectival works of differing aspect ratio — Raphael
   (*Marriage of the Virgin*, tall arched altarpiece) and Perugino (*Delivery of the Keys*, wide
   frieze) — the vertical shift of the horizon on the 8 × 8 grid drops the pair to ranks 2,256 and
   25,374 (Form: 3 and 7).

**Combining Form + Depth (honest split-half cross-validation).** A weighted similarity sum
$S = (1 - \alpha)\, S_{\text{form}} + \alpha\, S_{\text{depth}}$ (raw cosines, corpus-centred depth,
and per-query z-scored similarities) was tested by selecting $\alpha \in \{0, 0.05, \dots, 0.5, 1\}$
on one half of the 14 "same composition" pairs and evaluating on the held-out half:

| Combination (14 "same composition" pairs, 28 queries) | R@10 | R@100 | median rank | centile |
|---|---|---|---|---|
| **Form alone ($\alpha = 0$)** | **53.6 %** | **71.4 %** | **8** | **0.9275** |
| 2-fold alternating CV (raw cosine, $\alpha = 0.05 / 0.10$) | 42.9 % | 75.0 % | 26 | 0.9314 |
| 2-fold contiguous CV (raw cosine, $\alpha = 0.10 / 0.10$) | 42.9 % | 71.4 % | 26 | 0.9334 |
| 2-fold alternating CV (z-scored sim, centred depth, $\alpha = 0.05 / 0.40$) | 50.0 % | 64.3 % | 15 | 0.9283 |
| 200 random 7/7 splits (raw cosine, median $\alpha = 0.10$, centile-tuned) | 42.1 % | — | 691 (mean) | 0.9037 |
| 200 random 7/7 splits (R@10 / median-tuned: $\alpha = 0$ in 74 % of splits) | — | — | — | — |

A small depth weight ($\alpha \approx 0.05\text{–}0.10$) slightly pulls up the two pairs where Form
fails badly (`20355 ↔ 50955` Hokusai / Art Nouveau and `16620 ↔ 65443` Bilibin / Realism), adding
+0.004 centile on fixed splits, **but markedly degrades top ranks** (R@10 drops from 53.6 % to
42.9 % and median rank worsens from 8 to 26) and **underperforms Form alone on average across 200
random 7/7 splits** (centile 0.9037 vs 0.9275; when tuning for R@10/median, CV picks $\alpha = 0$ in
74 % of splits). The same degradation holds on `filiation` (at $\alpha = 0.10$, R@10 drops from
38.9 % to 33.3 %).

**Conclusion: Depth Anything V2 is not kept, neither standalone nor combined with Form.** Form
(DINOv3) remains by far the best regard for shared composition. The vectors remain on disk
(`features/depth_anything_v2_small_*`, 10 MB) for benchmarks (`pixplot composition`, `pixplot pairs
bench --spaces …,profondeur`), while `"profondeur"` stays hidden from the Atlas and MCP server
(`NOT_KEPT` in `pixplot/api/spaces.py`).

**Limits.** The "same composition" sample is small (14 pairs) and largely drawn from reviewing
disagreements where Form already ranked the pair high (giving Form a built-in advantage, though this
does not explain depth's collapse on non-perspectival works). Only the Small variant (Apache 2.0)
and a fixed 8 × 8 grid were tested: monocular depth estimation is primarily meaningful on strictly
figurative, perspectival corpora (landscapes, interiors, history painting) rather than a broad
corpus mixing prints, flat modern compositions and decorative works.

## 29. LocalMAP versus UMAP, and duplicates found by SSCD (19/11/2026)

### LocalMAP: evaluated, kept as a trial map

Question: does [LocalMAP](https://github.com/YingfanWang/PaCMAP) (Wang et al., AAAI 2025, `pacmap`
package, Apache 2.0, CPU only) draw a better map than UMAP, especially in the dense areas where works
overlap?

- **Method.** Same vectors as the main map (form, DINOv3, PCA 64), same 80,716 works, fixed seed.
  Five measures on the map normalised to [-1, 1]: share of the 10 true neighbours (cosine of the full
  vectors) still among the 10 closest on the map (5,000 random works); share of works whose map
  neighbours mostly carry the same label (style, artist, genre); share of thumbnails overlapping their
  neighbour in the overview; occupied area (128 × 128 grid); map rank of the twin work in validated
  pairs (§ 18).

| Form regard, 80,716 works | UMAP (current map) | LocalMAP, 10 neighbours | LocalMAP, 20 neighbours |
|---|---|---|---|
| Computing time (CPU) | — | 28 s | 44 s |
| 10 true neighbours kept | 7.4 % | **7.8 %** | 5.8 % |
| Neighbours with the same style | 45.8 % | **47.3 %** | 45.0 % |
| Neighbours by the same artist | 32.0 % | **33.5 %** | 30.1 % |
| Neighbours with the same genre | 75.9 % | 75.5 % | 76.1 % |
| Occupied area | **41 %** | 20 % | 20 % |
| Overlapping thumbnails | **83 %** | 95 % | 95 % |
| Validated pairs: median rank on the map | **6,994** | 8,879 | 9,851 |
| Validated pairs: within the 100 closest | 9.6 % | 10.6 % | **12.0 %** |

- **Reading.** LocalMAP splits the corpus into six islands separated by empty space: the large
  families read better, but works pile up inside each island (half the area) and validated pairs
  drift apart. The gain on labels (+1.5 points) is too small to make up for what is lost on screen in
  an atlas of thumbnails.
- **Decision.** UMAP remains the main map. At the user's request, LocalMAP is offered as a **trial
  map** (`pixplot maps --localmap`, optional dependency `[localmap]`), in the menu as "Forme ·
  LocalMAP (essai, pas mieux)", with a note recalling these figures.
- **Limits.** One regard (form) and two settings; measures over the whole map, not area by area.
  Overlap is measured in the overview: when zooming, the Atlas spaces thumbnails the same way for
  both maps.

### Duplicates and variants: SSCD where it is good

SSCD was not kept as a regard (§ 27): it finds lineages less well than Form and Subject. But it is
built to recognise **the same image** despite cropping, different lighting or another scan.
`pixplot doublons` uses it to flag works entered twice in the catalogue, which the hash in
`pixplot ingest` misses (it only catches byte-identical files).

- **Method.** Centred SSCD vectors (the authors' advice), 5 nearest neighbours per work, exact FAISS.
  Thresholds were chosen **by looking** at eight random pairs per cosine band: from 0.95, the same
  image; 0.85 to 0.95, the same work reproduced differently (colour and black and white, another
  crop); 0.65 to 0.85, replicas, series (Monet's Rouen cathedrals), states of a Rembrandt etching, the
  copy of a Rococo portrait, and still a few poor reproductions of one work; 0.55 to 0.65, mostly
  works from the same series.
- **Levels kept.** "Same image" from 0.85; "variant" from 0.65 to 0.85. For each pair, the catalogue
  labels that contradict each other (artist, style, genre, date; "Unknown" does not count).

| WikiArt 81k | pairs | contradicting labels | of which style | genre | artist |
|---|---|---|---|---|---|
| Same image (≥ 0.85) | 839 | **702** | 689 | 12 | 8 |
| Variant (0.65–0.85) | 785 | 68 | 29 | 33 | 9 |

- **Reading.** WikiArt often files the same reproduction under **two styles** (a Corot as both
  "Romanticism" and "Realism"), and 598 "same image" pairs have a known artist on one side only
  ("Unknown Artist" on the other). This is a limit of the corpus to keep in mind: it also affects
  label benchmarks (§ 9), where a work can find its own duplicate under another label.
- **In the Atlas and the MCP server.** "Doublons" tab under "À vérifier" (same image or variants,
  contradicting labels only or all, Compare button); MCP tool `find_duplicates`. A pair is a lead:
  two paintings from a series remain two works.
- **Limits.** Thresholds chosen by eye on 40 pairs, not on an annotated set; 5 neighbours per work (a
  group of more than six reproductions is only seen piecewise); SSCD judges the likeness of images,
  not the history of works.
