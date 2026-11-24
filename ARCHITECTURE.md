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
├── README / ARCHITECTURE / ROADMAP / CHANGELOG (.md English, .fr.md French)
├── AGENTS.md              instructions shared by all coding assistants
├── pyproject.toml, CITATION.cff
├── pixplot/
│   ├── config.py          paths and settings (PIXPLOT_DATA)
│   ├── runs.py            dated runs + manifests
│   ├── cli.py             every `pixplot …` command
│   ├── catalog/           ① SQLite, ingestion, thumbnails, metadata, places, WikiArt titles (MMArt, ArtEmis)
│   ├── importers/         ① IIIF
│   ├── encoders/          ② Encoder interface, letterbox, DINOv3, SigLIP 2, colour, touch, posture,
│   │                         and the evaluated, non-adopted models (TIPSv2, PE-Spatial, SSCD, Depth Anything, PE-Core, CSD)
│   ├── features/          ② batch extraction, resume, regions
│   ├── index/             ③ FAISS, regions, regions described by words
│   ├── analysis/          ④ map (e-means, UMAP), Leiden groups, naming (lexicon, Iconclass), disagreements,
│   │                         duplicates, order of the surface, notions, benchmarks, critical layer, datasheet
│   ├── export/            ⑦ Research Pack
│   ├── notebook.py        research notebook (SQLite)
│   ├── api/               ⑤ FastAPI, ways of seeing
│   └── mcp/               ⑤ MCP server (20 tools)
├── web/                   ⑥ Atlas: index.html, atlas-*.js, atlas.css, vendor/deck.gl
├── site/                  presentation site (EN + FR), published by GitHub Actions
├── docs/                  MCP, GPU install, file formats, hand-over between assistants
├── bench/                 pairs of works reviewed by the user (versioned)
├── tests/
├── scripts/               full pipeline, Parquet extraction, site, assistants' working copies
└── data/                  (not in git) catalog.sqlite, thumbs/, runs/, notebook.sqlite — see docs/FORMATS.md
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
book). Rank of the twin in each direction, among 80,716 works:

| pair | form | subject | colour | touch |
|---|---|---|---|---|
| Raphael ← Perugino, *Marriage of the Virgin* | 2 / 1 | 1 / 1 | 9,656 | 8 / 19 |
| Van Gogh ← Millet, *The Sower* | 2 / 1 | 1 / 1 | 21,160 | 251 / 728 |
| Manet ← Goya, *Maximilian* / *Third of May* (p. 672) | 2 / 68 | 2 / 12 | 41,279 | 391 / 998 |
| Manet ← Titian, *Olympia* / *Venus of Urbino* (p. 709) | 4 / 23 | 4 / 58 | 4,075 | 568 / 588 |
| Manet ← *Pastoral Concert* (p. 671) | 8 / 796 | 155 / 130 | 14,153 | 1,070 / 2,062 |
| Monet ← Manet, *Déjeuner sur l'herbe* | 84 / 435 | 22 / 3 | 3,328 | 124 / 18 |
| Picasso ← El Greco, *Demoiselles* / *Vision of Saint John* (p. 772) | 418 / 2,144 | 671 / 96 | 74,329 | 2,106 / 1,497 |
| Picasso ← Delacroix, *Women of Algiers* | 20,944 / 49,444 | 2,076 / 766 | 32,508 | 4,308 / 7,472 |
| Van Gogh ← Rembrandt, *Lazarus* (fragment) | 1,856 / 3,645 | 591 / 1,814 | 77,018 | 67,412 |
| Perugino, *Delivery of the Keys* / *Marriage of the Virgin* (same composition) | 2 / 2 | 2 / 21 | 47,111 | 103 / 62 |

Exact copies and borrowed compositions are found at the very first rank by both form and
subject; as soon as the artist transforms the model (Picasso, the *Lazarus* fragment), no
way of seeing follows it. Form alone finds Manet's quotation of the *Pastoral Concert* from
the *Déjeuner* (rank 8). Colour finds no filiation: a copy changes its palette. This is
exactly what a new composition model (STELLAR) should be tested on.

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
decision is one key:

| key | effect |
|---|---|
| Enter | validate with the suggested kind of resemblance |
| 1 to 7 | validate as: same subject, same composition, same hand, same handling, same motif, same palette, filiation |
| R | reject (proposed pair) or "no link" (candidate) |
| Space | skip |
| Z | undo the last decision |
| Escape | quit |

The queue starts with proposed pairs, then **candidates** drawn from disagreements between
ways of seeing, alternating the couples of ways of seeing; the default kind of resemblance
depends on the way of seeing that brings the pair together (form → same composition,
subject → same subject, touch → same handling, colour → same palette). A validated
candidate becomes an annotated pair (source "relecture : désaccord forme > sujet"); a
dismissed one is logged in `bench/review_log.csv` and never comes back. At the top: progress
towards 100 validated pairs and the count per kind, to see which are missing.

*Since 21/11/2026 (§ 35): keys 1 to 8, "same gesture" on 7, "filiation" moves to 8.*

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

**Finding the region among 2,174** (share of objects with a region at rank 1 / in the top 10;
median rank):

| method | name: R@1 | R@10 | rank | sentence: R@1 | R@10 | rank |
|---|---|---|---|---|---|---|
| **SigLIP 2, cropped region** | **16.0%** | **43.8%** | **17** | **28.2%** | **61.1%** | **5** |
| TIPSv2 SO400m, cropped region | 12.7% | 36.8% | 32 | 20.4% | 47.9% | 12 |
| TIPSv2 B/14, cropped region | 11.6% | 34.7% | 37 | 15.1% | 41.7% | 19 |
| TIPSv2 SO400m, dense | 10.5% | 31.4% | 43 | 15.4% | 41.0% | 17 |
| TIPSv2 B/14, dense | 7.6% | 25.7% | 67 | 13.3% | 38.6% | 24 |

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

## 30. What P@1 measures: the first labelled neighbour (19/11/2026)

Point 9 of the Gemini 4 Argon audit. In `pixplot bench`, P@1 does not look at a work's very first
neighbour but at **the first neighbour that carries the label** (artist, style, genre): an unlabelled
neighbour ("Unknown Artist") is skipped. This is a defensible rule (we only judge what the catalogue
lets us judge), but it was written nowhere. User's decision: **keep the rule and state it**
(`bench.py` docstring, command output, this section); no published figure changes.

Gap with the two other possible rules, measured on WikiArt 81k (10 neighbours, full vectors):

| P@1 | current (unlabelled neighbours skipped) | strict (work not counted) | strict (counted as a miss) | 1st neighbour unlabelled |
|---|---|---|---|---|
| Form, artist | 65.6 % | 72.1 % | 59.3 % | 17.9 % |
| Subject, artist | 73.0 % | 77.8 % | 66.6 % | 14.4 % |
| Form, genre | 80.9 % | 82.1 % | 75.7 % | 7.7 % |
| Subject, genre | 83.4 % | 84.4 % | 78.2 % | 7.4 % |
| Form, style | 64.8 % | 64.8 % | 64.8 % | 0 % |
| Subject, style | 71.4 % | 71.4 % | 71.4 % | 0 % |

- **Style does not move**: every WikiArt work has one. Artist and genre move by a few points, one way
  or the other depending on the rule.
- **No conclusion changes**: Subject stays ahead of Form for all three labels, under all three rules.
- **Duplicates** (§ 29): removing them changes P@1 by less than a point (style: 64.8 % → 65.3 % for
  Form, 71.4 % → 72.0 % for Subject).

## 31. Evaluating PE-Core L/14 against SigLIP 2 So400m for the "subject" space (19/11/2026)

Question: can **PE-Core** (*Perception Encoder*, Bolya et al., Meta, 2025, `arXiv:2504.13181`) replace
**SigLIP 2 So400m** for the "subject" space (semantic similarity and free-text search)?

- **Licence and chosen variant.** Hugging Face card verified before download: **Apache 2.0** licence,
  no access request (`facebook/PE-Core-L14-336`, OpenCLIP remap maintained by `timm`:
  `timm/PE-Core-L-14-336`). Chosen variant: **PE-Core L/14 @336** (0.32B vision parameters + 0.31B
  text, 1,024 dimensions, 32-token context, 2.68 GB) — comparable in size to SigLIP 2 So400m @384
  (0.4B vision, 1,152 dimensions). `G/14 @448` (1.88B vision, 9.68 GB, 1,024 patches vs 576) would
  cost roughly 10× more compute (~3 h on 81k).
- **Implementation and extraction.** Encoder `pixplot/encoders/pe_core.py`: vision tower loaded via
  `timm` (`vit_pe_core_large_patch14_336`), causal PyTorch text tower faithful to Meta's official code
  (GELU, `0` padding, `argmax` EOT pooling, without requiring `open_clip`). Preprocessing: uncropped
  letterbox, neutral grey fill, `(x − 0.5) / 0.5` normalisation. Free-text search wired via
  `pixplot search-text --encoder pe_core_l14` (SigLIP 2 remains default). Full extraction on WikiArt
  81k (`features/pe_core_l14_20261119-225940`, log `data/wikiart81k/pe_core.log`): **80,716 artworks**,
  **0 failed**, **20 min 18 s**, **65.5 images/s**, **3,806 MiB** VRAM (RX 7900 GRE, FP16, batch 64).

### 1. WikiArt 81k labels (`pixplot bench`, k = 10, P@1 per § 30)

| Model | Label | n | P@1 | P@10 | Chance | Speed |
|---|---|---:|---:|---:|---:|---:|
| SigLIP 2 So400m @384 | Artist (`huggan/wikiart` only) | 39,499 | 73.0 % | 61.6 % | 1.5 % | 73.2 img/s |
| **PE-Core L/14 @336** | Artist (`huggan/wikiart` only) | 39,499 | **74.5 %** | **62.6 %** | 1.5 % | 65.5 img/s |
| SigLIP 2 So400m @384 | Artist (MMArt-enriched catalogue) | 74,684 | 59.3 % | 42.9 % | 0.5 % | 73.2 img/s |
| **PE-Core L/14 @336** | Artist (MMArt-enriched catalogue) | 74,684 | **61.5 %** | **44.3 %** | 0.5 % | 65.5 img/s |
| SigLIP 2 So400m @384 | Style | 80,716 | 71.4 % | 62.0 % | 7.9 % | 73.2 img/s |
| **PE-Core L/14 @336** | Style | 80,716 | **72.0 %** | **62.3 %** | 7.9 % | 65.5 img/s |
| SigLIP 2 So400m @384 | Genre | 64,929 | 83.4 % | 79.5 % | 14.6 % | 73.2 img/s |
| **PE-Core L/14 @336** | Genre | 64,929 | **83.6 %** | **79.7 %** | 14.6 % | 65.5 img/s |

Image-to-image, PE-Core L/14 slightly edges out SigLIP 2 So400m on every label metric (+1.5 to +2.2 pts
artist, +0.6 pt style, +0.2 pt genre).

### 2. Validated and metadata pairs (`pixplot pairs bench`, 80,716 artworks)

| Category (n queries) | SigLIP 2 R@10 / R@100 / med. / pct. | PE-Core L/14 R@10 / R@100 / med. / pct. |
|---|---|---|
| **Same subject, diff. composition** (annotated, 74) | **37.8 %** / **54.1 %** / **30** / 0.919 | 28.4 % / 43.2 % / 174 / **0.929** |
| *— of which 21 pairs from `subject > …` disagreements (42)* | *57.1 % / 69.0 % / 4 / 0.980* | *33.3 % / 54.8 % / 38 / 0.976* |
| *— of which 16 other pairs, unbiased wrt SigLIP 2 (32)* | *12.5 % / 34.4 % / 1,152 / 0.838* | ***21.9 %** / 28.1 % / **573** / **0.867*** |
| **Attested filiation** (annotated, 20) | **45.0 %** / **70.0 %** / **17** / **0.998** | **45.0 %** / **70.0 %** / 18 / 0.996 |
| Same composition, diff. subject (annotated, 28) | 21.4 % / 28.6 % / 814 / 0.738 | 21.4 % / **39.3 %** / **566** / **0.859** |
| Same motif, diff. period (annotated, 4) | **50.0 %** / 75.0 % / 26 / 0.980 | 0.0 % / 75.0 % / **21** / **0.996** |
| Metadata: same subject (600) | 0.0 % / 0.5 % / **15,424** / **0.726** | 0.0 % / **0.7 %** / 16,424 / 0.714 |
| Metadata: same artist, diff. styles (600) | 0.3 % / 2.2 % / **9,374** / 0.790 | **0.5 %** / **3.3 %** / 9,756 / **0.791** |
| Metadata: diff. artists, same brushwork (500) | 0.2 % / 5.8 % / 5,356 / 0.831 | **1.0 %** / **7.8 %** / **5,112** / **0.865** |

On the 10 `filiation` pairs, both models tie (R@10 45.0 %, R@100 70.0 %, median rank 17 vs 18). On
"same subject", SigLIP 2's apparent R@10 lead comes from selection bias on the 21 pairs sourced from
`subject > …` disagreements: on the 16 unbiased pairs, PE-Core scores higher (R@10 21.9 % vs 12.5 %,
median 573 vs 1,152).

### 3. Free-text search: 10 art-historian queries (visual check of top 10 results)

Each query was tested in **French** (actual PixPlot usage) and in its **English translation**, with all
200 top-10 thumbnails per model (10 × 10 per language) visually inspected on contact sheets:

| Query (FR / EN) | SigLIP 2 FR | PE-Core FR | SigLIP 2 EN | PE-Core EN |
|---|---:|---:|---:|---:|
| "Annonciation" / *Annunciation* | **10/10** | 4/10 | **10/10** | **10/10** |
| "vanité avec un crâne" / *vanitas still life with a skull* | **10/10** | **10/10** | **10/10** | **10/10** |
| "paysage d'hiver avec patineurs" / *winter landscape with ice skaters* | **9/10** | 6/10 | 9/10 | **10/10** |
| "Crucifixion" / *Crucifixion* | **10/10** | **10/10** | **10/10** | **10/10** |
| "bouquet de fleurs dans un vase" / *bouquet of flowers in a vase* | **10/10** | **10/10** | **10/10** | **10/10** |
| "tempête en mer avec un navire" / *stormy sea with a ship* | **10/10** | **10/10** | **10/10** | **10/10** |
| "autoportrait d'un peintre avec sa palette" / *self-portrait of a painter holding a palette* | **9/10** | 8/10 | **10/10** | 9/10 |
| "femme lisant une lettre" / *woman reading a letter* | **9/10** | 5/10 | **8/10** | 5/10 |
| "pont sur une rivière" / *bridge over a river* | **10/10** | **10/10** | **10/10** | **10/10** |
| "estampe japonaise du mont Fuji" / *Japanese woodblock print of Mount Fuji* | **10/10** | 8/10 | **9/10** | 8/10 |
| **Total (out of 100 inspected results)** | **97 / 100** | **81 / 100** | **96 / 100** | **92 / 100** |

- **Reading.** PE-Core's weakness shows immediately in French: its text tower uses an English-centric
  CLIP BPE vocabulary (49,408 tokens, 32-token context). On French "Annonciation", PE-Core drops to
  **4/10** (returning portraits by Corot and Holbein, a circled "A" logo by Roerich, and relying on
  printed captions *The Annunciation*), whereas it jumps to **10/10** on English *Annunciation*. The
  same drop appears on "paysage d'hiver avec patineurs" (6/10 FR → 10/10 EN). Even in English, SigLIP 2
  stays ahead (96/100 vs 92/100), notably on fine action scenes (*woman reading a letter*: 8/10 vs 5/10,
  where PE-Core returns four portraits with no letter).
- **Decision: keep SigLIP 2 So400m as the default "subject" space.** PE-Core's small image-to-image
  lead (+0.2 to +2.2 pts) does not offset the clear loss on French text search (−16 points) nor the
  cost of rebuilding the 1.61M-zone index, Iconclass names, and 2D concept axes. PE-Core L/14 stays in
  `NOT_KEPT` (hidden from Atlas and MCP), with vectors retained on disk (`pixplot search-text --encoder
  pe_core_l14`, `pixplot pairs bench --spaces …,sujet_pe`).
- **Limits.** Only L/14 @336 was tested (not G/14 @448, too heavy for a single local PC). Text search
  was judged on 10 queries without prompt engineering; both models likely saw WikiArt reproductions
  during web pretraining.

## 32. Evaluating CSD ViT-L/14 against "brushwork" (DINOv3, layer 6) (19/11/2026)

Question: can **CSD** (*Contrastive Style Descriptors*, Somepalli et al., ECCV 2024, `arXiv:2404.01292`)
replace the **"brushwork"** space (DINOv3 ViT-B/16, layer 6, patch mean and std, § 11) for retrieving
artworks with comparable brushwork or manner?

- **Licences verified before download.** Official repository (`learn2phoenix/CSD`): **MIT**; published
  Hugging Face weights (`tomg-group-umd/CSD-ViT-L`, `pytorch_model.bin`, 2.44 GB): **CC BY 4.0**, open
  access — suitable for local research use.
- **Implementation and extraction.** Encoder `pixplot/encoders/csd.py` (standalone PyTorch, no
  `openai/clip` dependency): CLIP ViT-L/14 backbone (QuickGELU, CLIP normalisation, uncropped 224 px
  letterbox) + L2-normalised `last_layer_style` projection head (768 dimensions). Inspecting
  `pytorch_model.bin` shows that the public Hugging Face checkpoint was saved at iteration **15,000**
  (`iters = 40,000`, `lambda_c = 0.0`, whereas the paper reports 80,000 iterations), matching the
  authors' GitHub disclaimer noting a discrepancy with paper numbers. Extraction on WikiArt 81k
  (`features/csd_vitl14_20261119-232036`, log `data/wikiart81k/csd.log`): **80,716 artworks**,
  **0 failed**, **8 min 38 s**, **149.8 images/s**, **1,985 MiB** VRAM (RX 7900 GRE, FP16, batch 64).

### 1. WikiArt 81k labels (`pixplot bench`, k = 10, P@1 per § 30)

| Model | Artist P@1 / P@10 (n = 74,684) | Style P@1 / P@10 (n = 80,716) | Genre P@1 / P@10 (n = 64,929) | Speed |
|---|---|---|---|---:|
| Brushwork (DINOv3 L6 @448) | 51.9 % / 35.0 % | 61.3 % / 49.6 % | 69.4 % / 62.8 % | 124.5 img/s |
| **CSD ViT-L/14 @224** | **54.8 %** / **40.0 %** | **67.0 %** / **57.7 %** | **75.4 %** / **69.8 %** | **149.8 img/s** |
| *Reference: Subject (SigLIP 2 @384)* | *59.3 % / 42.9 %* | *71.4 % / 62.0 %* | *83.4 % / 79.5 %* | *73.2 img/s* |

Per-style breakdown (P@10 on WikiArt 81k):

| Style (n) | Brushwork (DINOv3 L6) | CSD ViT-L/14 | Gap | Style type |
|---|---:|---:|---:|---|
| `Analytical_Cubism` (110) | **58.1 %** | 56.0 % | −2.1 pts | brushwork / structure |
| `Pointillism` (511) | 61.8 % | **63.0 %** | +1.2 pts | pure brushwork |
| `Fauvism` (822) | 29.8 % | **31.8 %** | +2.0 pts | brushwork / colour |
| `Impressionism` (13,025) | 64.9 % | **67.6 %** | +2.7 pts | broad brushwork |
| `Action_painting` (98) | 38.8 % | **46.9 %** | +8.2 pts | gesture / texture |
| `Minimalism` (1,331) | 59.8 % | **65.4 %** | +5.6 pts | form / movement |
| `Pop_Art` (1,473) | 39.0 % | **45.7 %** | +6.7 pts | movement / visual culture |
| `High_Renaissance` (1,340) | 33.7 % | **45.5 %** | **+11.8 pts** | historical school |
| `Baroque` (4,211) | 51.9 % | **67.4 %** | **+15.5 pts** | historical school |
| `Ukiyo_e` (1,163) | 80.3 % | **96.3 %** | **+16.0 pts** | medium / tradition |

### 2. Validated and metadata pairs (`pixplot pairs bench`, 80,716 artworks)

| Category (n queries) | Brushwork (DINOv3 L6) R@10 / R@100 / med. / pct. | CSD ViT-L/14 R@10 / R@100 / med. / pct. |
|---|---|---|
| **Diff. artists, comparable brushwork** (annotated, 34) | **29.4 %** / **47.1 %** / **202** / 0.710 | 0.0 % / 5.9 % / 7,666 / **0.836** |
| *— of which 9 pairs from `brushwork > …` disagreements (18)* | *55.6 % / 83.3 % / 5 / 0.999* | *0.0 % / 11.1 % / 3,583 / 0.890* |
| *— of which 8 other pairs (16, incl. 4 `… > brushwork`)* | *0.0 % / 6.2 % / 65,772 / 0.386* | *0.0 % / 0.0 % / **10,312** / **0.774*** |
| **Same artist, diff. brushwork** (annotated, 2) | 0.0 % / 0.0 % / 56,470 / 0.300 | 0.0 % / 0.0 % / **31,724** / **0.607** |
| **Metadata: diff. artists, same brushwork** (500) | 1.6 % / 7.0 % / 7,750 / 0.803 | **1.8 %** / **10.4 %** / **2,157** / **0.854** |
| **Metadata: same artist, diff. styles** (600) | 0.0 % / 1.0 % / 22,217 / 0.660 | **0.2 %** / **1.7 %** / **14,910** / **0.746** |
| **Metadata: same subject, diff. styles** (600) | 0.0 % / 0.0 % / 28,160 / 0.622 | 0.0 % / 0.3 % / **31,368** / **0.591** |

Mean top-10 neighbour overlap (random sample of 2,000 artworks):
`csd ∩ subject` = **16.2 %** · `csd ∩ brushwork` = 15.3 % · `csd ∩ form` = 12.2 % (vs
`brushwork ∩ subject` = **12.0 %** and `brushwork ∩ form` = **10.8 %**).

### 3. Critical reading and training-data contamination (key limit)

At first glance, CSD beats Brushwork on style labels (+5.7 pts P@1, +8.1 pts P@10) and on metadata
"different artists, comparable brushwork" pairs (median 2,157 vs 7,750, percentile 0.854 vs 0.803),
while staying slightly more decoupled from genre on metadata "same subject" pairs (percentile 0.591 vs
0.622).

**Three major caveats prevent reading these scores as proof of superior brushwork retrieval:**

1. **Direct WikiArt contamination and label supervision.** Section 4 of Somepalli et al. (2024) shows
   that CSD is initialised from OpenAI CLIP ViT-L/14 and fine-tuned on **LAION-Styles**: 511,921 images
   from **LAION-Aesthetics 6+** (deduplicated internally with SSCD, but **never deduplicated against
   WikiArt**) using **3,840 artist, medium, and movement tags** from CLIP Interrogator. Because
   LAION-Aesthetics 6+ contains abundant WikiArt reproductions captioned with artist and movement names,
   **our WikiArt artworks are likely present in CSD's training data** under their own labels. An
   inflated WikiArt score does not prove generalisation.
2. **CSD measures "named style", not pure surface brushwork.** The per-style table confirms it: on
   surface-texture styles (`Analytical_Cubism`, `Pointillism`, `Fauvism`, `Impressionism`), purely
   self-supervised Brushwork (which never saw an artist or style label) ties or beats CSD (58.1 % vs
   56.0 % on Analytical Cubism, 61.8 % vs 63.0 % on Pointillism). CSD's big gains come on historical
   schools and mediums prominent in web captions (`Ukiyo_e` +16.0 pts, `Baroque` +15.5 pts,
   `High_Renaissance` +11.8 pts). CSD also overlaps more with Subject (16.2 %) than Brushwork does
   (12.0 %), while still trailing SigLIP 2 on style overall (67.0 % vs 71.4 % P@1).
3. **Resolution and public checkpoint.** 224 px input (vs 448 px for Brushwork) blurs fine surface
   grain, and the public Hugging Face checkpoint stops at iteration 15,000 (discrepancy noted by the
   authors).

- **Decision: keep "brushwork" (DINOv3, layer 6) as default and leave CSD in `NOT_KEPT`.** Brushwork
  answers the stricter question of unsupervised surface texture, remains more orthogonal to Form and
  Subject, and has zero WikiArt label leakage. CSD remains on disk for benchmarks (`pixplot pairs bench
  --spaces …,touche_csd`) and can be re-evaluated later on a non-WikiArt museum corpus (e.g. Paris
  Musées IIIF).
- **Limits.** Only 17 annotated `meme_facture` pairs (13 drawn from disagreements involving Brushwork)
  and 1 annotated `meme_main` pair exist; unbiased evaluation rests mainly on metadata pairs. Exact
  image-level overlap between WikiArt 81k and LAION-Styles was not enumerated locally.

## 33. Order and disorder of the surface: entropy and complexity (19/11/2026)

Question: can we place a work's surface between the regular flat area and disordered grain, with no
neural model, and follow this measure across styles and periods? Method of H. Sigaki, M. Perc and
H. Ribeiro (*PNAS*, 2018), after Bandt and Pompe's "ordinal patterns".

- **Method.** Luminance of the 256 px thumbnail; each 2 × 2 pixel window is reduced to the order of its
  four values (24 possible orders). **Permutation entropy H** (0 to 1): 1 when orders are spread at
  random (noise, highly divided surface), near 0 when they concentrate on a few (flat areas,
  gradients). **Statistical complexity C**: high between the two extremes. Checks: pure noise H = 1.00
  and C ≈ 0; regular gradient H = 0.09. `connoisseur.entropy_complexity`, `pixplot ordre` (a few
  minutes for 80,716 works, CPU only), map colours "Désordre" and "Complexité" (by rank: raw values
  bunch between 0.90 and 0.98), "Ordre de la matière" line in the visual measures.
- **By style** (medians, WikiArt 81k): Minimalism H 0.622 · C 0.229; Color Field 0.712 · 0.221; Pop Art
  0.871 · 0.128; Baroque 0.916; Realism 0.927; Cubism 0.936; Impressionism 0.951; Post-Impressionism
  0.956; Pointillism 0.978 · 0.028. By genre: abstract_painting 0.835 to illustration 0.950. Large
  flat areas on one side, divided brushwork on the other.
- **Over time** (56,794 works dated thanks to MMArt, § 34): no simple trend (Spearman year / H = −0.03),
  but a curve:

| Period | 1400–1599 | 1600–1749 | 1750–1849 | 1850–1879 | 1880–1909 | 1910–1939 | 1940–1969 | 1970–2012 |
|---|---|---|---|---|---|---|---|---|
| Median H | 0.941 | 0.915 | **0.912** | 0.936 | **0.948** | 0.944 | 0.923 | **0.895** |
| Works | 5,813 | 3,569 | 4,214 | 6,156 | 16,431 | 10,449 | 5,911 | 4,251 |

  Smoothest surfaces between 1600 and 1850 (glazes), most disorder around 1900 (divided brushwork),
  back to order after 1940 (flat areas of abstraction and minimalism).
- **Limits.** The measure is taken on the reproduction: JPEG compression, thumbnail size, lighting and
  photographic grain count as much as the painting. WikiArt's periods are unbalanced (16,431 works
  between 1880 and 1909) and mix techniques (prints, drawings, oil). No value judgement: an ordered
  surface is neither better nor more "learned".

## 34. Titles, dates, artists and emotions recovered for WikiArt: MMArt and ArtEmis (19/11/2026)

Our WikiArt 81k comes from the Hugging Face dataset `huggan/wikiart`: artist (129 names, the rest as
"Unknown Artist"), style and genre, but no title, date or file name, and a shuffled order. Yet two
annotation sets identify each work by its original WikiArt file name ("Style/artist_title-date.jpg"):
**MMArt** (Wang et al., 2026, 74,234 works, CC BY 4.0, images included) and **ArtEmis** (Achlioptas et
al., CVPR 2021, 454,684 reactions on 80,031 works, non-commercial research use, obtained by the user
through the authors' form and kept locally).

- **Matching by image.** For each MMArt image, the same fingerprint as `pixplot ingest` (64-bit dHash),
  compared with our works of the same style and artist (then unknown artist on our side, then same
  artist in any style). A match is kept only if the closest fingerprint is within 8 bits and beats the
  second by at least 4 bits; otherwise nothing is guessed. Dimensions do not help: our copy is resized.
  `pixplot wikiart-noms`, `pixplot/catalog/wikiart_names.py`. MMArt (25.3 GB) downloaded in 14 min,
  matching in 3 min 38 s on CPU.
- **Result.** **70,902 works** matched; 3,281 MMArt images left aside. Check: 32 random pairs including
  edge cases (7–8 bits, artist-only match, unknown artist on our side): all correct. Of the 35,717
  matched works that already had an artist, **none** contradicts the file name.
- **Import** (each value keeps its source in the record): titles for 70,902 works; **dates for
  56,794** (1401–2012), which switch on the timeline view; **artists** for 35,185 "Unknown Artist" works
  (6,729 remain; 129 → 1,090 distinct artists; known labels are never replaced); **ArtEmis dominant
  emotion** for 55,120 works (at least 40 % of reactions, excluding "something else"; 70,324 works have
  reactions, details in `<data>/artemis.json`). MMArt's descriptions, written by a language model, are
  not imported as a source.
- **Do the regards capture emotion?** `pixplot bench --keys emotion,genre` (P@1 as in § 30):

| Regard | Same emotion (P@1 / P@10) | Same genre (P@1 / P@10) |
|---|---|---|
| Form (DINOv3) | 41.8 % / 39.8 % | 80.9 % / 76.8 % |
| Subject (SigLIP 2) | 41.7 % / 40.4 % | 83.4 % / 79.5 % |
| Touch (DINOv3, layer 6) | 37.5 % / 35.8 % | 69.4 % / 62.8 % |
| Colour (CIELAB) | 30.1 % / 29.6 % | 33.1 % / 30.3 % |
| Chance | 24.7 % | 14.6 % |

  The regards capture a little of the emotion a work arouses (1.7 times chance), far less than genre
  (5 to 6 times); mostly through what is depicted, hardly through colour.
- **Limits.** A work's emotion rests on about 5 viewers (Amazon Mechanical Turk) and contentment
  dominates (126,134 of 454,684 reactions). Part of the effect may come from genre (a portrait and a
  battle do not arouse the same reactions): see the control below. WikiArt file names are volunteer
  labels like the others. Consequence: artist benchmarks, `pixplot suspects` and group names computed
  earlier rest on the old labels and must be recomputed.

- **Emotion at equal genre** (added 21/11/2026). For each work, the first neighbour (among 50) that
  has an emotion **and the same genre**; chance is computed genre by genre (probability that two works
  of the same genre share the dominant emotion):

| Regard | All neighbours | Same-genre neighbour | Chance at equal genre | Ratio |
|---|---|---|---|---|
| Form | 42.5 % | 42.2 % | 30.8 % | 1.37 |
| Subject | 42.4 % | 42.4 % | 30.8 % | 1.37 |
| Touch | 38.2 % | 39.2 % | 30.9 % | 1.27 |
| Colour | 31.8 % | 34.7 % | 31.0 % | 1.12 |

  (about 45,000 works per regard.) Genre explains part of the effect: chance rises from 24.7 % to
  31 %. But about two thirds of the gap to chance remain: two portraits the model finds close more
  often arouse the same emotion than two random portraits. Colour stays almost silent.

## 35. "Posture" regard (Pathosformeln): RT-DETRv2 + ViTPose, evaluated and not kept by default (21/11/2026)

Question: can we retrieve **gestural formulas** (Aby Warburg's *Pathosformeln* — a raised arm, a reclining
body, a bent or striding figure) recurring across works even when subject, style, period or medium change
(sources: D. G. Stork, *Pixels & Paintings*, §§ 8.3 & 9.3.1; *Human-Art*, CVPR 2023; Madhu et al.)?

### 1. Model choice, licences and visual pilot

- **Licences verified before download.** Ultralytics YOLO-pose (AGPL) and weights fine-tuned on *Human-Art*
  (non-commercial CC BY-NC dataset) are excluded. We use a **100 % Apache 2.0** pipeline (code and weights,
  built into `transformers`, trained on MS COCO): person detector **RT-DETRv2-R50**
  (`PekingU/rtdetr_v2_r50vd`, 172 MB) followed by skeleton estimator **ViTPose Base Simple**
  (`usyd-community/vitpose-base-simple`, 344 MB, 17 COCO keypoints).
- **100-artwork visual pilot** (history/religious paintings, portraits & nudes, prints/drawings/Ukiyo-e,
  figurative modern art, and 15 figureless controls: landscapes, still lifes, abstraction), inspected
  skeleton by skeleton:
  - **RT-DETRv2-R50** clearly outperforms the lighter **R18** (`PekingU/rtdetr_v2_r18vd`) on graphic arts
    and multi-figure scenes: prints/drawings/Ukiyo-e **13/20 (65 %)** vs 4/20 (20 %) for R18;
    history/religious **19/20 (95 %)** vs 15/20 (75 %). R50 at 640 px is selected.
  - Skeletons are accurate across Western figurative painting, engravings (Doré, Rembrandt, Dürer), line
    drawings and Ukiyo-e prints: *Olympia* / *Venus of Urbino* (cosine 0.951) and Van Gogh's / Millet's
    *Sower* (0.981) match at **rank 1/100**. Zero false positives on abstraction and still lifes (rare
    detections in landscapes are real staffage figures, filtered by minimum box size). Expected failure
    on Cubism (*Les Demoiselles d'Avignon*: 0 figures in pilot) and strongly distorted modern figures.

### 2. 50-D descriptor, multi-figure matching and left-right mirror

Implementation: `pixplot/encoders/posture.py` (`vitpose_base`, in `NOT_KEPT` in `pixplot/api/spaces.py`).

- **Filtering**: box confidence $\ge 0.40$, NMS deduplication (IoU 0.65), minimum size ($\ge 8\,\%$ of
  artwork max side and $\ge 0.6\,\%$ of artwork area, removing tiny staffage), at least **4 body keypoints**
  (shoulders to ankles, conf $\ge 0.30$, mean $\ge 0.40$) to exclude tight face-only portraits without body
  posture. Up to **8 figures** stored per artwork (`poses_*.npy`), ranked by prominence.
- **Per-figure descriptor (50 dimensions, L2-normalised)**:
  1. **13 normalised joints (26 dims)**: one head centre (confidence-weighted average of the 5 face points,
     preventing the face from weighting 29 % of the vector) plus the 12 body joints, centred on the torso
     and scaled by RMS body radius.
  2. **12 unit limb vectors (24 dims)**: neck, shoulders, spine, hips, upper arms, forearms, thighs and
     shins — robust to elongated or stocky painted proportions (Mannerism, Botero) and half-length crops.
- **Left-right mirror and multi-figure matching.** Prints after paintings and reversed citations flip left
  and right: `mirror_pose_vector` applies an exact orthogonal involution $F$ on the 50-D vector ($x \mapsto -x$
  and L/R swap, verified to $< 10^{-6}$). Exact artwork-to-artwork similarity (`posture_multi`,
  `PostureIndex`) takes the best match across all figure pairs, direct and mirrored:
  $$\operatorname{sim}(A, B) = \max_{i \in A,\; j \in B} \max\big(v_i \cdot v_j,\; v_i \cdot F(v_j)\big).$$
  For compatibility with `FeatureStore` and `pixplot pairs bench`, `global.npy` stores the orientation-canonicalised
  primary figure (`posture`). Figureless artworks are excluded from the index (`Spaces._open`), preventing
  zero-vector tie artefacts.

### 3. Extraction and coverage on WikiArt 81k

Run `features/vitpose_base_20261121-182701` (`data/wikiart81k/posture.log`, RX 7900 GRE, FP16, rocBLAS
fallback `cudnn=False` avoiding a Windows ROCm MIOpen hang on RT-DETRv2, batch size 64):
**80,716 works**, **0 failures**, **53 min 55 s** (**25.0 images/s**), **7,375 MiB** VRAM, **139 MB** on
disk (`global.npy` 7.7 MB + `poses_*.npy` 130.6 MB).

- **Overall coverage**: **39,043 of 80,716 works (48.4 %)** have at least one valid body figure, yielding
  **102,515 figures** in total (2.63 figures per figurative work).
- **By genre**: religious painting **87.4 %** (3.65 figs/work), genre painting **83.2 %** (2.77), portrait
  **76.5 %** (0.99; remaining 23.5 % are mostly tight headshots), nude **64.9 %**, illustration **63.8 %**,
  sketch & study **50.7 %**, cityscape **30.9 %**, landscape **10.9 %** (staffage), still life **2.9 %**,
  abstract **2.7 %**.
- **By style**: Mannerism **88.5 %**, Early Renaissance **83.6 %**, High Renaissance **82.8 %**, Baroque
  **82.3 %**, Rococo **81.5 %**, Northern Renaissance **80.9 %**, Romanticism **63.9 %**, Realism **52.9 %**,
  Ukiyo-e **49.4 %**, Impressionism **41.8 %**, Pop Art **21.5 %**, Cubism **14.1 %**, Abstract
  Expressionism **4.4 %**, Minimalism **1.4 %**.

### 4. Benchmarks (`pixplot pairs bench` and `pixplot composition`)

Measured on the **39,043 figurative works** (pairs with $\ge 1$ figure on both sides; the random control
`Témoin` over 128 queries gives percentile **0.498**, median rank 19,648 — exact chance):

| Category (n figurative queries / total) | Form (DINOv3) | Subject (SigLIP 2) | Touch (L6) | **Posture** (main fig.) | **Posture multi+mirror** |
|---|---|---|---|---|---|
| **Attested filiation** (18 / 20) | **50.0 % / 66.7 % · med. 16** (0.993) | **50.0 % / 72.2 % · med. 8** (0.998) | 16.7 % / 27.8 % · 578 (0.902) | 11.1 % / 22.2 % · 4,366 (0.639) | **22.2 % / 27.8 % · 1,754** (0.790) |
| **Same composition, diff. subject** (12 / 28) | **66.7 % / 83.3 % · med. 2** (0.998) | 33.3 % / 50.0 % · 77 (0.995) | 0.0 % / 25.0 % · 494 (0.988) | **8.3 % / 25.0 % · 346** (0.910) | 0.0 % / 8.3 % · 1,276 (**0.967**) |
| **Same subject, diff. comp.** (26 / 74) | 27.0 % / 39.2 % · 506 *(all)* | **37.8 % / 54.1 % · 30** *(all)* | 5.4 % / 13.5 % · 24,922 *(all)* | 0.0 % / 7.7 % · 9,472 (0.631) | 0.0 % / 3.8 % · 10,934 (0.620) |
| **Metadata: Control** (128 / 600) | 0.0 % / 0.2 % · 45,138 (0.456) | 0.0 % / 0.0 % · 45,837 (0.450) | 0.0 % / 0.0 % · 45,880 (0.447) | 0.0 % / 0.8 % · 19,648 (**0.498**) | — |

*(Format: R@10 / R@100 · median rank (percentile). For Filiation and Same composition, Form/Subject/Touch
are shown on the same figurative subset; on all pairs — 10 filiation, 14 composition — Form scores
45.0 % / 70.0 % · med. 20 and 53.6 % / 71.4 % · med. 8 respectively. Evaluating `posture_multi` across all
80,716 works with figureless pairs ranked last drops percentiles to 0.809 on filiation and 0.422 on
same composition.)*

- **Pair-level hits and misses on filiation**: `posture_multi` retrieves Van Gogh / Millet (*The Sower*) at
  **rank [1, 1]** (cosine 0.979, ahead of Form [2, 1]), Rubens / Titian (*Rape of Europa*) at **rank [1, 1]**
  (0.946), *Olympia* → *Venus of Urbino* at **rank 13** (898 reverse, cos 0.951), and Van Gogh → Rembrandt
  (*Raising of Lazarus*) at rank **1,152** (ahead of Form 1,856). Conversely, crowded scenes with common
  standing/seated figures (Raphael / Perugino *Marriage of the Virgin* [2,267, 4,452], *Déjeuner sur
  l'herbe* [7,593, 19,129]) collide with thousands of similar poses, and Picasso *Demoiselles* ↔ El Greco
  fails on the Cubist skeleton ([30,617, 17,293]).
- **Form + posture combination** ($S = (1 - \alpha) S_{\text{form}} + \alpha S_{\text{posture}}$,
  out-of-sample cross-validation, posture set to 0 on figureless pairs):
  - **Same composition (14 pairs)**: no gain. Over 200 random 50/50 splits, $\alpha = 0$ is chosen in
    **90.5 %** of draws (mean percentile 0.9201 vs **0.9275** for Form alone).
  - **Filiation (10 pairs)**: a small weight ($\alpha = 0.05\text{–}0.10$) slightly lowers median rank on
    fixed splits (20 → 16, percentile 0.9941 → 0.9944), but across 200 50/50 splits R@10 dips slightly
    (43.7 % vs 45.0 %) with flat percentile (0.9942 vs 0.9941).

### 5. New "same gesture" (`meme_geste`) pairs and distinct value

Existing benchmarks had no *Pathosformeln* pairs. Pair type `meme_geste` ("Same gesture or posture,
different subject or style", expected regard: `posture`) was added in `pixplot/analysis/pairbench.py` and
`review.py`, and **37 diverse candidate pairs** (15th–20th c., frescoes, oils, engravings, drawings,
ukiyo-e, posters; 30 mirrored and 7 direct), all **visually inspected**, were added with status `proposée`
for expert review (R shortcut). Examples: Titian *Venus* (1546) ↔ *La Libre Esthétique* Art Nouveau poster
(mirrored); Michelangelo *Ignudo* (1509) ↔ Burne-Jones (1896, mirrored); Dürer drawing (1506) ↔
Petrov-Vodkin; Botero (2001) ↔ Jan van Hemessen (1543, proportion-invariant); Fra Angelico (1449) ↔ Ogata
Gekkō (ukiyo-e 1895, mirrored); Caillebotte *Floor Scrapers* (1876) ↔ Kirchner (mirrored).

For reference only (with obvious selection bias since these 37 pairs were mined using posture, prior to
human validation): Form (`R@10 = 0.0 %`, `R@100 = 2.7 %`, med. 9,600), Subject (`0.0 %`, med. 16,076) and
Touch (`0.0 %`, med. 15,108) miss nearly all of them. On these same pairs, enabling **mirror reversal**
improves `posture_multi` median rank from **8,914** (percentile 0.714) to **38** (percentile **0.972**),
and matching **all figures** instead of only the primary figure raises percentile from 0.809 to **0.972**.

- **Provisional decision.** `"posture"` stays in `NOT_KEPT` (hidden from Atlas and MCP by default): it
  covers only 48.4 % of the corpus and neither replaces nor improves Form on existing validated pairs.
  Unlike depth (§ 28), however, it answers a **genuinely orthogonal art-historical question** (*Pathosformeln*
  across styles, media and mirror reversals): the art historian's review of the 37 proposed `meme_geste`
  pairs will determine whether to expose it as a specialised regard for figurative works.
- **Limits.** Detector and pose estimator are trained on photographs (MS COCO): blind to Cubism and
  heavily stylised bodies, occasionally confused by heavy drapery or overlapping figures. Common poses
  (frontal standing, seated bust) crowd the 102,515-figure neighbourhood; the 2D descriptor ignores depth
  (front/back) and fine hand gestures (absent from COCO-17). Skeleton proximity is a formal lead, never
  proof of borrowing.

## 36. Sentence search: benchmark with MMArt descriptions (21/11/2026)

**Question.** Sentence search (§ 12) had only been measured on short hand-written queries (100
queries, § 31). MMArt (§ 34) gives five long descriptions for each matched work (formal, narrative,
emotional, historical, unified): each model can be asked to find **the right work among 80,716** from
its description.

**Method.** `pixplot textbench --mmart … -n 300 --encoders siglip2,pe_core`
(`pixplot/analysis/textbench.py`): 300 works drawn at random (seed 0) among the 70,902 matched; each
description becomes a query; we record the rank of the true work. The title is the control. CPU only
(SigLIP 2: 2 h 31; PE-Core: 1 h 02). Report: `<data>/bench/textbench_report.json`.

| Query | SigLIP 2: R@1 / R@10 / R@100 · median rank | PE-Core L/14: R@1 / R@10 / R@100 · median rank |
|---|---|---|
| Narrative (what happens) | 20.3 / 45.7 / 71.0 % · **13** | 28.3 / 59.0 / 85.0 % · **6** |
| Unified | 16.3 / 41.0 / 65.0 % · 26 | 21.7 / 46.7 / 75.3 % · 14 |
| Title (control) | 9.3 / 23.7 / 49.0 % · 102 | 10.0 / 23.7 / 47.3 % · 115 |
| Emotional | 5.7 / 18.0 / 43.3 % · 226 | 8.7 / 25.0 / 45.7 % · 136 |
| Formal (colours, brushwork, composition) | 2.3 / 8.3 / 24.3 % · 661 | 2.0 / 7.7 / 23.7 % · 807 |
| Historical (context, movement) | 0.7 / 6.7 / 14.0 % · 2,151 | 1.7 / 4.7 / 18.3 % · 1,404 |

**What we learn.**
- **The models find a work by what it shows**, not by how it is painted: the narrative description
  puts the right work in the top 10 almost half the time, the formal one almost never (median rank
  661 to 807). The art historian's vocabulary of facture ("impasto", "diagonal composition") barely
  gets through.
- **History is not visible**: the historical description (movement, context) is the worst, as expected
  since it speaks of what is not in the image.
- **PE-Core beats SigLIP 2 on long English descriptions** (median rank 6 against 13). This does not
  contradict § 31: SigLIP 2 remains clearly better in French (97/100 against 81/100), the interface
  language. Decision unchanged.

**Limits.**
- **Descriptions are truncated**: SigLIP 2 reads 64 tokens, PE-Core 77; MMArt descriptions have 82 to
  193 (medians). Each model reads only about the first two sentences; the unified description, the
  longest, is the most cut.
- MMArt descriptions were written by a language model looking at the image: their vocabulary is close
  to the models', which favours retrieval. This is not a historian describing from memory.
- 300 works: one R@10 point carries about ± 3 points of uncertainty.

## 37. Learned notions: sparse autoencoder on the "subject" regard (21/11/2026)

**Question.** A SigLIP 2 vector holds 1,152 unreadable numbers. Can it be broken down into a small
number of nameable **notions**, and do these notions say something other than the catalogue labels?

**Method.** `pixplot notions --space sujet` (`pixplot/analysis/sae.py`): "TopK Matryoshka" sparse
autoencoder (2,048 notions, 16 active per work; the first 64, 256 and 1,024 must already reconstruct
on their own, which orders notions from broadest to finest). 30 passes over the 80,716 works, 10 %
held out for measurement. For each notion: its 50 most marked works, the share sharing a style, genre,
artist, century (against chance), and the closest Iconclass name (SigLIP 2 vectors of the 17,126
Iconclass notions, z-score against the other notions). CPU only, 3 h 28 (shared with § 36). Run
`analysis/notions_sujet_*` (`sae.npz`, `notions.json`).

**Results.**
- **Reconstruction** (held-out works): 49.8 % of variance with 64 notions, 63.0 % with 256, 71.5 % with
  1,024, **73.7 % with 2,048**. 256 notions are never used: **1,792 alive**.
- **What explains them** (share of the top 50 works sharing a label, threshold 60 %): genre for 423
  notions, style for 353, artist for 57; **959 notions match no label**.
- **The label-less notions are mostly objects and motifs**, checked on contact sheets: rainbow, deer,
  butterfly, skull (from Cézanne to Pop Art), staircase, flag-decked streets (Childe Hassam),
  locomotive, skating, violin, lion, peacock… The Iconclass name is right on all eight checked by eye
  (z 7.5 to 8.6). WikiArt does not index these subjects; the model separates them on its own.
- **Two unexpected notions**:
  - no. 24 (17.6 % of works): **the famous masterpiece** (*The Starry Night*, *The Creation of Adam*,
    *Sunflowers*, *The Thinker*, *Vitruvian Man*). Neither a subject nor a style, but fame learned on
    the web: the model's "vector imaginary" (Impett and Offert, 2024);
  - no. 88 (2.9 %): **the painting photographed with its frame**, a fact of reproduction, not of the
    work. A lead for "To check".
- Broad notions (first 64) recover the large families: battle, sleeper, fruit still life, forest
  landscape, combat ukiyo-e…

**Limits.**
- **The Iconclass name is only reliable above z ≈ 5** (506 notions); below, vague notions get unrelated
  names ("Will", "hollow cheeks"). Names are proposed by the model, to be reviewed like group names.
- A notion describes what the model separates, not a historian's category; its boundaries are fuzzy.
- One regard (subject) and one seed; another seed would give similar but not identical notions.
- **In the Atlas (22/11/2026)**: "Notions" panel (key O): the 1,792 notions, filter, named (z ≥ 5) or
  not; a click lights up to 500 works on the map (activation index built on first use: 2.9 s on 81k,
  then ~10 ms). "Frames (no. 88)" tab in "To check" (2,321 works). No. 88 only holds for this run: a
  new training renumbers the notions. Without a reliable Iconclass name, a notion shows the catalogue
  label shared by at least 60 % of its 50 most marked works ("style: Impressionism (100 %)"): 577 of
  the 1,286 unnamed notions; 709 are left with nothing.

## 38. Confidence intervals for the pair benchmark (22/11/2026)

**Question.** The pair benchmark compares percentages computed on 10 to 37 pairs. Which gaps between
regards are reliable, and which come from the luck of the pair selection?

**Method.** `pixplot pairs ci` (`pairbench.bootstrap_report`), following Deepseek's reading
(`docs/handoff/deepseek-lectures.md`, Smucker, Allan and Carterette, CIKM 2007): bootstrap over
**pairs** (the two directions of a pair are not independent), 2,000 resamples, 95 % CI for R@10 and
median rank; for each pair of regards, a **paired** R@10 difference on pairs measured in both, with a
two-sided p. Reads the ranks of the latest `pixplot pairs bench` report: no recomputation, under one
second. No interval below 5 pairs. Annotated pairs only by default (`--all-origins` for the others).
Details in `bench/pairs_ci_*.json`.

**Results** (WikiArt 81k, 108 validated annotated pairs, report of 21/11/2026).

| Type | Pairs | Best regard (R@10, 95 % CI) | Reliable gaps |
|---|---|---|---|
| Same composition | 14 | Form 53.6 % [39–68] | Form > Subject (+32 pts), > Touch, > Colour, > Posture |
| Same palette | 27 | Colour 48.1 % [31–63] | Colour > Form, Subject, Touch |
| Same subject | 37 | Subject 37.8 % [28–49] | Subject > Touch, Colour, Posture; **not > Form (27.0 %)** |
| Lineage | 10 | Form = Subject 45.0 % [20–70] | Form, Subject > Colour, Posture; nothing else |
| Same facture | 17 | Touch 29.4 % [15–44] | Touch > Subject only |
| Same motif, same hand | 2, 1 | — | too few pairs |

**What it changes.**
- The two solid results of the benchmark hold: **Form for composition, Colour for palette**.
- **Subject does not reliably beat Form on "same subject"** (37.8 % vs 27.0 %, overlapping
  intervals), although the median rank (30 vs 506) clearly leans towards Subject.
- **Touch is only reliably ahead of Subject** on "same facture": not of Form or Colour.
- **Lineage**: Form and Subject tie, as Deepseek noted; with 10 pairs no regard can be declared best.
- Rule from now on: a new regard is "better" only if the paired-difference interval excludes zero.
  Pairs to add first: same subject, same facture, lineage, then same motif and same hand.

**Limits.** Percentile bootstrap on small samples: approximate intervals, rather narrow below 15
pairs. Several comparisons without correction (about ten per type): an isolated "reliable gap" at
p ≈ 0.03 still needs confirming. Pairs were reviewed by a single person (inter-rater agreement not
measured, see Krippendorff in Deepseek's note).

## 39. Does the "Why?" button really explain? Occlusion test (22/11/2026)

**Question.** In the comparator (§ 25, `pixplot/analysis/correspondences.py`), the "Pourquoi ?" ("Why?")
button highlights 4 pairs of 4 × 4 cells that match across two works in the form regard (DINOv3). Are these
zones genuinely **what drives the global similarity** computed by DINOv3, or merely a plausible post-hoc
picture (the perceptual bias noted by Wasielewski, 2023; protocol no. 1 in
`docs/handoff/deepseek-lectures.md`)? If they carry the similarity, masking them should drop the cosine
far more than masking other regions.

**Method.** `pixplot whytest` (`pixplot/analysis/whytest.py`), without altering the existing "Why?"
computation.
- **Pairs**: the **104 validated pairs** of `bench/wikiart81k_pairs.csv` (all types; **104/104** have at
  least 4 mutual matches) plus **104 random "nearest neighbour" control pairs** (exact 1st neighbour in
  form of a randomly drawn work, seed 0, disjoint from validated pairs; **103/104** have at least 4
  matches). Total: 207 pairs, 401 unique works.
- **Pre-check**: unoccluded re-encoding with DINOv3 ViT-B/16 using the exact same preprocessing (448-px
  letterbox, bands untouched) as reference run `features/dinov3_vitb16_20261116-102419`. Maximum cosine
  difference against `global.npy`: **0.00033** (mean 0.00006, minimum self-cosine 0.999999), well below
  the 0.01 gate.
- **Occlusion**: on both images (`both`) and on one image only (`one`, image A), across three conditions:
  **(a)** the top 4 "Why?" zones, **(b)** 4 cells drawn at random among valid artwork cells (excluding
  letterbox bands, mean over 10 draws), **(c)** the 4 central cells (5, 6, 9, 10). Two fill modes:
  artwork **mean colour** (`mean`, excluding bands) and **strong Gaussian blur** (`blur`, radius 32 px).
  Drop = original cosine − occluded cosine.
- **Statistics and pre-registered criterion**: paired bootstrap over pairs (2,000 resamples, 95 % CI,
  two-sided p as in `pixplot pairs ci`, § 38). **Pass if** the median drop of (a) exceeds (b) by a
  factor ≥ 3 and the 95 % CI of (a − b) excludes zero. Cost: **205 s** (3 min 25 s on RX 7900 GRE,
  10,311 images encoded; report `<data>/bench/whytest_report.json`, log `<data>/whytest.log`).

**Results: clear failure across all conditions.**

| Group & mode (`mean`) | n | med. cos₀ | (a) Why [95 % CI] | (b) Random | (c) Centre | Ratio a/b | med. (a − b) [95 % CI] · p | med. (a − c) · p | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| Validated · 2 images | 104 | 0.356 | −0.0006 [−0.0038; +0.0048] | −0.0089 | −0.0448 | — | +0.0148 [+0.0053; +0.0188] · 0.015 | +0.0474 · <0.001 | **Fail** |
| Validated · 1 image (A) | 104 | 0.356 | +0.0019 [−0.0011; +0.0044] | +0.0034 | +0.0124 | 0.55 | −0.0003 [−0.0059; +0.0032] · 0.602 | −0.0113 · 0.128 | **Fail** |
| Neighbours · 2 images | 103 | 0.724 | +0.0099 [+0.0059; +0.0123] | +0.0274 | +0.0214 | **0.36** | −0.0119 [−0.0174; −0.0055] · 0.008 | −0.0034 · 0.274 | **Fail** |
| Neighbours · 1 image (A) | 103 | 0.724 | +0.0059 [+0.0027; +0.0133] | +0.0181 | **+0.0945** | **0.33** | −0.0090 [−0.0134; −0.0031] · 0.002 | **−0.0785 · <0.001** | **Fail** |

**Strong-blur control (`blur`)** — nearly identical figures; the conclusion does not depend on fill mode:
- Validated: `both` (a) +0.0012, (b) −0.0062, (c) −0.0316 (`a − b` +0.0125, p = 0.015); `one` (a) +0.0023,
  (b) +0.0040, (c) +0.0195 (ratio 0.57, p = 0.598).
- Nearest neighbours: `both` (a) +0.0075, (b) +0.0259, (c) +0.0322 (ratio **0.29**, `a − b` −0.0117,
  p = 0.006); `one` (a) +0.0077, (b) +0.0191, (c) **+0.0857** (ratio **0.40**, `a − b` −0.0084, p = 0.010;
  `a − c` −0.0758, p < 0.001).

**By validated pair type** (types with ≥ 10 pairs; `mean`, `both` / `one`; `filiation` 9, `meme_motif` 2,
`meme_main` 1 omitted from breakdown):

| Type (n) | med. cos₀ | `both`: (a) / (b) / (c) | `both`: (a − b) · p | `one`: (a) / (b) / (c) | `one`: (a − b) · p |
|---|---|---|---|---|---|
| Same composition (14) | 0.544 | +0.0076 / +0.0169 / +0.0208 | −0.0042 · 0.749 | +0.0109 / +0.0179 / **+0.0769** | −0.0032 · 0.397 |
| Same subject (36) | 0.421 | +0.0088 / +0.0137 / +0.0070 | +0.0095 · 0.398 | +0.0035 / +0.0144 / **+0.0624** | −0.0086 · 0.017 |
| Same facture (16) | 0.284 | +0.0031 / −0.0269 / −0.1041 | +0.0271 · 0.072 | −0.0007 / −0.0009 / −0.0214 | +0.0060 · 0.248 |
| Same palette (26) | 0.097 | −0.0090 / −0.0275 / −0.1131 | +0.0172 · <0.001 | −0.0028 / −0.0099 / −0.0119 | +0.0045 · 0.099 |

**Why it fails: two mechanisms uncovered.**
1. **A severe corner bias in "Why?".** Tallying the chosen cells explains everything: on validated pairs
   (832 cells), **63.0 %** of selected zones fall in the **4 corners** (`{0, 3, 12, 15}`, vs 25 % uniform),
   **95.8 %** on the border and only **4.2 % in the centre** (nearest neighbours: **57.5 %** corners,
   **93.6 %** border, **6.4 %** centre); in **92.8–93.0 %** of matches, a cell is paired with the exact same
   grid slot (`cell_a == cell_b`). DINOv3's outer patches carry a strong positional and edge signature: two
   matching corners look very similar to each other while differing from the rest of the painting, which
   mechanically inflates the `lift` score in `correspondences.py` at the expense of the centre — precisely
   where DINOv3's global vector draws most of its similarity (+0.0945 when masking the centre of one
   neighbour, 16 times the drop of the "Why?" boxes). On nearest neighbours, masking the 4 "Why?" zones
   causes **roughly 3 times less** cosine drop than masking 4 random cells.
2. **A symmetric-masking artefact on dissimilar pairs.** On validated pairs with low initial cosine
   (`meme_palette` 0.097, `meme_facture` 0.284, mostly cross-regard disagreements), masking the centre of
   **both** images erases their distinct subjects and places a matching flat/blurred square in the middle,
   *raising* their cosine (negative drop: −0.113 for centre, −0.028 for random). The positive `(a − b) =
   +0.0148` on `validated (both)` comes solely from this artefact — (a) itself does not drop (−0.0006) —
   and vanishes as soon as only one image is masked (`one`).

**Visual inspection (6-pair contact sheet, `<data>/bench/whytest_planche.jpg`).**
- *Three large drops of (a)*:
  1. `#49819` (Realist illustration) ↔ `#67186` (Remington, *A Brush with the Redskins*, `meme_sujet`,
     Δ(a) = +0.105, Δ(b) = −0.003): the only pair on the sheet where the 4 boxes land on the figures
     (crouching riflemen at centre-right) rather than the corners.
  2. `#8965` (Kirchner, *Walking Woman with Dog*) ↔ `#66489` (Billy Apple, `meme_sujet`, Δ(a) = +0.100,
     Δ(b) = +0.092): all 4 boxes hug the top and bottom corners, dropping no more than chance.
  3. `#21020` (Makovsky) ↔ `#31498` (Konchalovsky, `meme_sujet`, Δ(a) = +0.090, Δ(b) = +0.054,
     Δ(c) = +0.087): all 4 boxes line up across the top strip (hair and background), no better than centre
     and nearly zero when masking one image (+0.002).
- *Three pairs where (a) drops no more than chance*:
  4. `#71348` (Expressionist smoking skull) ↔ `#75862` (Symbolist creature, `meme_facture`, Δ(a) = +0.012,
     Δ(b) = +0.179, Δ(c) = +0.224): the 4 boxes sit strictly on the 4 empty corners, missing both central
     subjects entirely.
  5. `#48392` (Flora-Karavia, *Marie Bonaparte*) ↔ `#76646` (Pogačnik, *Pop Object 3*, `meme_composition`,
     Δ(a) = −0.006, Δ(b) = +0.061, Δ(c) = +0.207): the 4 boxes cling to the 4 background corners, ignoring
     both the portrait bust and the white sack in the middle.
  6. `#79406` (Van Gogh, *Sower after Millet*) ↔ `#41274` (Millet, *The Sower*, `filiation`, cos 0.711,
     Δ(a) = −0.022, Δ(b) = +0.044, Δ(c) = +0.031; one image: Δ(c) = +0.107): on a faithful copy, the 4
     boxes frame only the sky and dark ground corners, leaving the entire sower figure outside.

**Limits.** On non-square artworks, outer cells are clipped by letterboxing: mean masked artwork area is
21.9–22.5 % for (a), 25.8–26.5 % for (b) and 33.9–34.4 % for (c). Normalising each drop to 25 % masked
area leaves the ranking unchanged (neighbours `one`, `mean`: (a) +0.0080 vs (b) +0.0177 and (c) +0.0669).
Testing one model (DINOv3 ViT-B/16) on a fixed 4 × 4 grid only evaluates the current "Why?" implementation.
Methodological reminder: a computed proximity — and even more so an automatic highlight — is a lead for
looking, never proof.

**Proposals for next steps (not applied; to be decided and re-tested with `pixplot whytest`).**
1. **Immediate UI warning**: clarify in the "Pourquoi ?" legend that current boxes are heavily biased
   toward corners and do not reflect what drives the global score, or hide the button until ranking is
   fixed.
2. **Fix zone ranking in `correspondences.py`** (no re-extraction needed): (i) **per-cell corpus
   centring** (subtract the mean vector $\mu_c$ of each grid slot `c ∈ 0..15` before computing cell cosines)
   to strip out positional corner signatures; (ii) **weight by alignment with each artwork's global vector**
   (`regions` vs `global.npy`), favouring zones that actually contribute to the global representation.
3. **Direct on-demand occlusion**: in the comparator (one pair at a time), measure leave-one-cell-out
   cosine drops directly (16 GPU passes, ~0.15 s) — faithful by construction, at the cost of loading the
   model on demand. Any candidate fix should pass `pixplot whytest` before adoption.

## 40. Fixing the "Why?" button: per-cell centring and global alignment (2026-11-23)

**Question.** § 39 showed that the original ranking in `correspondences.py` (`lift` on raw cosines) picked
mostly corners (58–63 %) and failed the occlusion test (`a / b` = 0.33–0.55). Can the ranking be fixed
**without GPU or re-extraction** (Option 1: per-position centring + global-vector alignment weighting), or
is an on-demand GPU occlusion map (Option 2) required?

**Strict tuning / verification split.** Parameters were selected exclusively on **104 tuning "close
neighbour" pairs** (exact top-1 shape neighbour, seed 1, strictly disjoint from both validated pairs and
seed 0 neighbours). Validated pairs and seed 0 neighbours were used **once only** for final verification
under the unchanged § 39 criterion (median drop `(a) ≥ 3 × (b)` and 95 % CI of `(a − b)` excluding zero).
Single-image masking (`one`) is reported first, as it avoids the shared flat-patch artefact identified in § 39.

**Option 1 tuning (seed 1 neighbours, `n = 100/104` with ≥ 4 matches, `mean`, `one` mode).**
For each slot $c \in \{0..15\}$ of the 4 × 4 grid, we compute its corpus mean $\mu_c$ from `regions.npy`
(L2-normalised valid cells, `OK` artworks only; computed once in **11.4 s** on CPU and cached in
`cell_means_4x4.npy`, 48 KB). Diagnostic: $\|\mu_c\|$ is **0.831–0.845** in the 4 corners vs **0.762–0.768**
at the centre (strong positional signature), while mean alignment with the global vector (`cell_raw · global`)
is **0.228–0.242** in corners vs **0.388–0.392** at the centre.

| Variant (seed 1 neighbours, `n = 100`, `one`) | Corners | Centre | Same cell | Median `(a)` drop | Ratio `a / b` | `(a − b)` 95 % CI · p | Criterion |
|---|---|---|---|---|---|---|---|
| Baseline (raw `lift`, § 39) | 52.8 % | 5.8 % | 96.4 % | +0.0091 | 0.40 | [−0.0170; −0.0030] · 0.003 | Fail |
| $\mu_c$ centring + `lift` | 19.0 % | 32.8 % | 65.2 % | +0.0453 | 1.97 | [+0.0107; +0.0310] · <0.001 | Fail |
| $\mu_c$ centring + `sim` | 15.0 % | 38.4 % | 63.7 % | +0.0544 | 2.36 | [+0.0200; +0.0472] · <0.001 | Fail |
| $\mu_c$ centring + `lift × align` | 7.1 % | 49.3 % | 61.8 % | +0.0810 | 3.51 | [+0.0299; +0.0672] · <0.001 | **Pass** |
| $\mu_c$ centring + `sim × align` | 4.1 % | 57.5 % | 61.3 % | +0.0872 | 3.78 | [+0.0466; +0.0840] · <0.001 | **Pass** |
| **$\mu_c$ centring + `sim × align_a × align_b`** | **3.9 %** | **59.0 %** | **61.1 %** | **+0.0963** | **4.18** | **[+0.0523; +0.0877] · <0.001** | **Pass** |

*(Shared controls: random `(b)` = +0.0231, centre `(c)` = +0.1121.)* Centring alone removes corner bias but
stays below 3×; combined with global alignment weighting
($\max(0, \text{sim}_{\text{centred}}) \cdot \max(0, c_a \cdot g_a) \cdot \max(0, c_b \cdot g_b)$), it
reaches **4.18× random** with zero GPU cost at query time. Option 2 (on-demand GPU occlusion) is therefore
unnecessary.

**Single final verification (`pixplot whytest`, WikiArt 81k, 128.4 s on RX 7900 GRE, 8,273 images encoded).**
Unoccluded check: max cosine difference **0.000663** (mean 0.000068, min self-cosine 0.999998) → OK. Out of
the current 108 validated pairs and 108 seed 0 neighbours, **73/108 validated** and **93/108 neighbours**
yield ≥ 4 mutual matches after centring (see Limits).

| Group & mode (`mean`) | n | med cos₀ | (a) Why [95 % CI] | (b) Random | (c) Centre | Ratio `a / b` | (a − b) med [95 % CI] · p | (a − c) med · p | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| **Validated · 1 image (`one`)** | 73 | 0.372 | **+0.0112** [+0.0041; +0.0220] | +0.0027 | +0.0129 | **4.20** | **+0.0138** [+0.0072; +0.0203] · <0.001 | +0.0001 · 0.706 | **Pass** |
| **Neighbours · 1 image (`one`)** | 93 | 0.724 | **+0.0710** [+0.0603; +0.0968] | +0.0186 | +0.0960 | **3.82** | **+0.0541** [+0.0465; +0.0682] · <0.001 | −0.0053 · 0.121 | **Pass** |
| Validated · 2 images (`both`) | 73 | 0.372 | +0.0045 [−0.0029; +0.0109] | −0.0116 | −0.0451 | — | +0.0136 [+0.0087; +0.0233] · 0.001 | +0.0541 · <0.001 | Fail *(artefact)* |
| Neighbours · 2 images (`both`) | 93 | 0.724 | **+0.0612** [+0.0511; +0.0767] | +0.0270 | +0.0182 | 2.26 | +0.0331 [+0.0229; +0.0439] · <0.001 | **+0.0310 · <0.001** | Fail *(2.26 < 3)* |

**Heavy blur control** (`blur`, radius 32 px) — even stronger in `one` mode:
- **Validated `one`**: (a) **+0.0184** vs (b) +0.0032 vs (c) +0.0182 → ratio **5.69**, `(a − b)` = +0.0141, p < 0.001 → **Pass**.
- **Neighbours `one`**: (a) **+0.0731** vs (b) +0.0197 vs (c) +0.0870 → ratio **3.71**, `(a − b)` = +0.0513, p < 0.001 → **Pass**.
- **Neighbours `both`**: (a) +0.0592 vs (b) +0.0259 vs (c) +0.0282 (ratio **2.29**, `(a − c)` = +0.0205, p < 0.001).

**Spatial distribution (before → after) and area-normalised drops:**

| Group | Corners (before → after) | Edges (before → after) | Centre (before → after) | Same cell `a == b` | `one` drop scaled to 25 % area: `(a) / (b) / (c)` |
|---|---|---|---|---|---|
| Validated | 63.0 % → **17.5 %** | 95.8 % → **63.7 %** | 4.2 % → **36.3 %** | 92.8 % → **46.2 %** | **+0.0112** / +0.0028 / +0.0112 *(areas: 27.5 / 25.3 / 33.9 %)* |
| Neighbours | 57.5 % → **4.8 %** | 93.6 % → **42.7 %** | 6.4 % → **57.3 %** | 93.0 % → **56.2 %** | **+0.0653** / +0.0180 / +0.0709 *(areas: 32.0 / 25.8 / 34.2 %)* |

**By validated pair type (`mean`, `one`, ≥ 10 pairs)**:
- `filiation` (n = 10, cos₀ 0.664): (a) **+0.0554** vs (b) +0.0097 vs (c) +0.0690 (ratio **5.72**, `a − b` +0.0371, p = 0.036).
- `meme_composition` (n = 10, cos₀ 0.590): (a) +0.0327 vs (b) +0.0227 vs (c) +0.0577 (ratio 1.44).
- `meme_sujet` (n = 22, cos₀ 0.374): (a) +0.0160 vs (b) +0.0144 vs (c) +0.0524 (`a − b` +0.0156, p = 0.009).
- `meme_facture` (n = 12, cos₀ 0.328): (a) +0.0154 vs (b) +0.0020 vs (c) −0.0214 (ratio 7.58, p = 0.154).
- `meme_palette` (n = 17, cos₀ 0.005): (a) −0.0057 vs (b) −0.0110 vs (c) −0.0212 (artworks with no shape similarity).

**Visual inspection (before / after contact sheet on 6 verification pairs, `<data>/bench/whytest_avant_apres.jpg`).**
1. `#79406` (Van Gogh, *Sower after Millet*) ↔ `#41274` (Millet, *The Sower*, `filiation`, cos 0.711): moves off the 4 sky/ground corners (`d(a)` −0.017) directly onto the sower's figure (`[5, 6, 10, 9]`, `d(a)` **+0.107**, 8× random).
2. `#32834` ↔ `#33077` (Rembrandt, two oval portraits of a young woman, `meme_sujet`, cos 0.855): moves off the 4 white corners outside the oval (`+0.001`) onto the face and bust (`+0.515`, 16× random).
3. `#4261` (Pissarro) ↔ `#15620` (Levitan, `meme_facture`, cos 0.716): moves off corners (`−0.004`) onto the horizontal river and bank band (`[10, 9, 11, 8]`, `+0.139`).
4. `#22485` (Chagall) ↔ `#66396` (foxes in snow, `meme_sujet`, cos 0.340): moves off the 4 empty margin corners (`−0.015`) onto the lower-centre animal figures (`+0.108`).
5. `#33547` (Rembrandt, castle) ↔ `#81005` (Turner, *Windsor Castle*, `meme_facture`, cos 0.510): edge case; boxes move onto the castle and reflection, yet masking them raises cosine (`−0.083`, like random `−0.025`), reflecting broad atmospheric rather than local similarity.
6. `#31416` (Konchalovsky, pig) ↔ `#35524` (Dürer, young steer, `meme_composition`, cos 0.530): boxes track the animal in both versions (drop `+0.036` vs random `+0.075`).

**Integration & UI.** Wired into `correspondences.py` (`load_or_compute_cell_means` + `match`), `Spaces.cell_means`
(`pixplot/api/spaces.py`), `/api/correspond`, and MCP `why_similar` (unchanged output fields). An explicit
disclaimer under the zones in `web/atlas-panneaux.js` states that they show "the zones that resemble each
other most" and are "a lead to look at, not an explanation". Verified live in the Atlas (port 8770, 0 console
errors, 0 network errors) on *The Sower*, the two Rembrandts, and Pissarro/Levitan.

**Limits.**
- **Fewer pairs reaching ≥ 4 mutual matches**: 73/108 validated and 93/108 neighbours (vs 104/104 and 103/104
  previously). Stripping positional corner signatures prevents shape-dissimilar pairs (`meme_palette`,
  `meme_facture`) from fabricating 4 spurious corner matches; the comparator simply shows the 1–3 remaining
  zones (or none).
- **Tied with fixed centre in `one` mode**: on neighbours, selected zones match the fixed centre (`a − c` =
  −0.0053, p = 0.121) without statistically exceeding it; however, they clearly beat the centre in `both` mode
  (`+0.0612` vs `+0.0182`, p < 0.001) and adapt to off-centre or horizontal compositions.
- **Scope**: the ranking measures weighted local similarity, never causal proof of influence or an internal
  explanation of the network.

**Addendum (2026-11-24): when fewer than 4 zones answer each other.** Correspondences are *mutual* (each cell
is the other's best). Counted on the CPU, without GPU, for all the validated pairs of the benchmark (1,278,
metadata pairs included) and as many close neighbours (seed 0): a median of **4** mutual correspondences
for the benchmark pairs, **7** for close neighbours; fewer than 4 for **31 %** of the benchmark pairs (402)
and **10 %** of the neighbours (133), while both works almost always have 16 valid cells. The shortfall
therefore comes from the resemblance itself, more diffuse between distant works, not from a cropping
defect. We do not fill in with non-mutual correspondences (they have not been put to the test); the
comparator now says, under the zones, that only 1 to 3 zones clearly answer each other and what this
means. These pairs remain outside the occlusion test.

## 41. The "posture" regard in the Atlas, on trial (2026-11-23)

**Decision.** § 35 had left posture in `NOT_KEPT`: it does not beat form on the validated pairs. Yet the
review of the "same gesture" pairs (25 validated, 7 rejected, 5 to review out of 37) shows that it finds
gestural formulas the other regards do not see. It is therefore offered as a **specialised regard, on
trial**: kept apart from the four main regards in the Atlas, marked "trial", with a card that states its
limits. Work by Gemini 4 Neon (`docs/handoff/gemini-posture-atlas.md`), reviewed and checked by Claude.

**What changes.**

- "Posture" neighbours go through `PostureIndex`: every figure of each work, compared directly and
  mirrored, **exact** search (no approximate index). Each neighbour states the two figures that answer
  each other and whether the match is mirrored. Works without a figure are excluded, and their card says so.
- Skeletons drawn (SVG, no library) on a work's card and in the comparator; routes `/api/posture/{id}` and
  `/api/posture/match?a=…&b=…`; `posture_matches` in `/api/compare`.
- `similar_artworks` (MCP) accepts `space="posture"`, with the "on trial" mention and the usual caution.
  Still 20 tools.
- `pixplot communities` and `pixplot disagreements` leave trial regards out by default (posture covers only
  48.4 % of the corpus); they can be named with `--spaces`.

**Measurements (WikiArt 81k, 39,043 works with a figure, 102,515 figures).**

| Measurement | Value |
|---|---|
| Opening the index (once) | 1,606 ms → 486 ms (vectorised, identical result) |
| Warm neighbours, `PostureIndex.similar`, k = 20 | 3 to 38 ms |
| Warm work card in the browser | 142 to 177 ms (first request: ~350 ms) |
| *The Sower*, Van Gogh 79406 | Millet 41274 at rank 1 (pose 0.979) |
| Titian 66184 ↔ Mantegna 56885 | pose 0.932, mirrored |

**Limits.** Detector and skeletons trained on photographs (COCO): they fail on Cubism and heavily distorted
figures, and find nothing in landscapes, still lifes and tightly cropped portraits. No 2D map of its own
(works without a figure would have no place on it). The drawings realign on hover after the window is
resized. A similar pose is a lead, not proof that one artist saw the other.

## 42. Notions of the "form" regard, named through SigLIP 2 (2026-11-24)

**Question.** § 37 opened the "subject" regard (SigLIP 2) into 1,792 notions. What does the same method give
on the "form" regard (DINOv3), and how can its notions be named when DINOv3 cannot read text?

**Computation.** `pixplot notions --space forme`: same autoencoder (TopK Matryoshka, 2,048 notions, 16 per
work, 30 epochs), on the 80,716 DINOv3 vectors; 50 min on the CPU (run `notions_forme_20261123-132834`).

**Naming through another regard.** Iconclass is a list of words: only SigLIP 2 can compare it with images.
For each form notion, we take its 50 strongest works (exact activations), average their **SigLIP 2**
vectors, and look for the most distinctive Iconclass notion (z-score over all notions), as for the names of
the form groups (§ 23). The name therefore says what these works **show** according to SigLIP 2, not what
DINOv3 saw in them; the Atlas and the MCP say so (`via: "sujet"`). `pixplot notions --nommer RUN` does it on
an existing run (3.7 s); a new computation on form does it by itself.

| | Subject (§ 37) | Form |
|---|---|---|
| Live notions | 1,792 of 2,048 | 2,048 of 2,048 |
| Explained variance (held-out works) | 73.7 % | 63.4 % |
| Reliable Iconclass name (z ≥ 5) | 506 | 489 (through SigLIP 2) |
| Dominant catalogue label (≥ 60 %), genre / style / artist | 423 / 353 / 57 | 572 / 143 / 18 |
| Neither | 709 | 1,315 |

**Reading by eye** (sheets of the 8 strongest works, outside the repository). Six named notions out of six
are right: pumpkins (no. 1439, z 8.0), ladders (no. 607, from Fra Angelico to Léger and Chagall), vertical
stripes (no. 1396), harvests and haystacks (no. 713), herds of horses (no. 262); one approximation:
"wax tablet" (no. 994) actually designates Chagall's Tables of the Law. Among the notions without a reliable
name, several are coherent to the eye and concern layout or gesture more than subject: people seated in a
circle in drawings (no. 1588), Twombly-like gestural writing (no. 572), arched polyptychs (no. 1604). Their
weak Iconclass names (z < 4) are wrong and stay hidden, as intended.

**Reading.** Form sums up into notions less well than subject (63 % against 74 % of the variance): DINOv3
mixes more things. Its notions are less tied to style (143 against 353) and more to genre, which fits a
regard on composition rather than manner. Notion numbers are specific to each regard and each computation.

**Interface.** The "Notions" panel (key O) offers both regards; `/api/notions?space=forme`,
`/api/notions/{n}?space=forme`; MCP tool `explore_notions(space="forme")`. List in 38 ms, first notion
opened in 1.7 s (index computation), then 4 ms. The "frame" notion (no. 88) applies to the "subject" regard
only.

**Limits.** A name given through SigLIP 2 inherits its biases (§ 26); the z ≥ 5 threshold was set on the
"subject" regard (§ 37) and is checked here on 6 notions only. A notion describes what the model separates,
not an art historian's category.
