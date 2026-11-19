# Changelog

**English** · [Français](CHANGELOG.fr.md)

**PixPlot v2** is the project's name: the second generation of PixPlot, after the Yale
DHLab's (2018). It is not a version number. Software versions follow
[semantic versioning](https://semver.org/): `0.MINOR.PATCH`.

- **0.x**: research software under construction; a minor release may change commands or
  file formats. 1.0 will come once they are stable.
- **MINOR** (0.9 → 0.10): every new feature.
- **PATCH** (0.7.0 → 0.7.1): fixes and documentation only.

Each version is a git tag `vX.Y.Z` and a GitHub release. The number lives in
`pyproject.toml` and `pixplot/__init__.py`, and `pixplot --version` prints it.

## 0.17.0 — 2026-11-19 · Concept axes, visual measures, reading principles

Work by Gemini 4 Neon (Antigravity), reviewed and checked by Claude; three readings integrated
(ARCHITECTURE § 26).

- **Concept axes** (L. Impett and F. Offert, *Visual Resources*, 2024): a new map view placing each work
  by its closeness to two words ("sacred" / "profane", "sea" / "mountain"…); works far from the diagonal
  stand out. API `/api/layout/concepts`, MCP tool `probe_concepts`.
- **Visual measures without a model** (D. G. Stork, *Pixels & Paintings*, 2024): barycentre of
  lightness and saturation, left-right symmetry, tonal range, chromatic entropy and the first cut of the
  composition, in the artwork record. API `/api/artwork/{id}/measures`, MCP tool `measure_artwork`
  (18 tools).
- **Reading principles** (J.-L. Giavitto and P. Saint-Germier eds, *L'art au temps de l'IA*, Centre
  Pompidou, 2025) in the Corpus panel and the MCP server instructions.
- README, roadmap, MCP docs and site pages rewritten in a more direct tone.

## 0.16.3 — 2026-11-19 · Fixes after three Gemini 4 Argon audits

Three code audits by Antigravity (Gemini 4 Argon, read-only); each point checked before fixing.

- **Interface**: Ctrl+R in quick review no longer rejects the displayed pair; one HD thumbnail level
  loaded at a time (256 MB of GPU memory instead of 768); colours computed once; timeline works beyond
  ~65,000 dates; HTML keys escaped; stale searches ignored; "why?" no longer overlaps; images released.
- **Security**: the Atlas rejects other host names (DNS rebinding) and writes coming from other sites;
  the Antigravity relay only sends project files.
- **Computations**: safe resume of a vector computation (marks written after vectors, centring never
  redone); **disagreements judged from the right work** (recomputed on WikiArt 81k); group names never
  taken from a partial run; small corpora.

## 0.16.2 — 2026-11-19 · Antigravity on Windows, read-only

- `pixplot antigravity-mcp`: a second opinion from Antigravity (Google, Gemini) from Claude, through the
  `ask_antigravity` MCP tool, read-only (`--mode plan --sandbox`); `agy.exe` also found after a winget
  install. Antigravity reaches PixPlot through `.agents/mcp_config.json` (docs/MCP).
- Accessibility skill (WCAG 2.2) shared by all assistants in `.agents/skills/`.
- "Why?" fixed after Antigravity's review: mean similarity excludes the pair itself, no more warning for
  non-square works.

## 0.16.1 — 2026-11-19 · "Why?" MCP tool and the art historian's guide

- MCP server: `why_similar` tool, a plate of the two works where the zones that answer each other carry
  the same number, with their cosines (16 tools).
- Site: [The art historian's guide](https://riyadhhda.github.io/pixplot-v2/guide/), in French and English:
  reading a proximity, three paths (filiation, label, motif), working with an assistant, citing, known
  limits.

## 0.16.0 — 2026-11-19 · Why do these two works look alike?

- Comparator: a "Pourquoi ?" button on each pair. The zones that answer each other most (4×4 cells,
  form regard) are drawn on both images, with the same number and a legend with figures.
- Mutual matches, ranked by what sets them apart from the mean similarity; cells outside the work
  excluded. Computed on demand in a few milliseconds. API `/api/correspond`.
- Example: Raphael, *Marriage of the Virgin*, and Perugino, *Delivery of the Keys*: the temple and the
  groups of figures answer each other. ARCHITECTURE § 25.

## 0.15.1 — 2026-11-19 · GitHub tests, modular Atlas, citable project

- Automatic tests on GitHub at every push (all branches) and on pull requests, on Linux and Windows,
  without GPU (`.github/workflows/tests.yml`).
- The Atlas (`web/atlas.js`, 1,950 lines) split into 8 scripts loaded in order (`atlas-base.js` …
  `atlas-ui.js`, see `web/README.md`), with no change in behaviour: several assistants can work on it
  without getting in each other's way.
- Citable project: `CITATION.cff` ("Cite this repository" button) and Zenodo archiving with a DOI at
  every release (`.zenodo.json`).

## 0.15.0 — 2026-11-18 · Composition: PE-Spatial evaluated, not adopted

- `pixplot composition`: benchmark on validated pairs (existing regards, PE-Spatial, cell-by-cell
  4×4 layouts, "work only" and "common cells" variants).
- PE-Spatial B/16 encoder (Meta, Apache 2.0, via `timm`); vectors for WikiArt 81k in 20 min.
- Result: on "same composition" pairs, DINOv3 stays best (median rank 8; PE-Spatial 286 at best).
  PE-Spatial is not adopted: vectors kept for benchmarks, hidden in the Atlas and MCP. Code reviewed
  by Codex. ARCHITECTURE § 24.
- Multi-assistant work: `AGENTS.md` (shared instructions for Codex, Gemini, Claude),
  `docs/HANDOFF.md` (handoff), `scripts/nouvelle-tache.ps1` (one worktree per assistant).
- 0.14 (Iconclass names) awaits review and will follow.

## 0.13.5 — 2026-11-17 · Images: stable order and batched loading

- Fix: depending on zoom, overlapping thumbnails swapped places (high definition only covered the centre
  of the screen). Each level now covers every visible thumbnail (8,192 px textures when the GPU allows),
  in the same order as the sprite sheets.
- Batched thumbnails: `/api/thumbs/{size}?ids=…` returns up to 48 in one request (browsers open only 6
  connections at a time); two workers decode them and size them to their cell off the main thread.
- WikiArt 81k, six zooms: 3,053 thumbnails in 1.2 s instead of 6.7 s; in never-visited areas, about 925
  thumbnails per second instead of 450; no frame over 10 ms.

## 0.13.4 — 2026-11-17 · Faster image display

- Atlas: high-definition thumbnails now go through three fixed-size textures (4,096 px) managed by the
  Atlas, instead of one texture that grew without limit as you moved around (black squares, slowdowns
  getting worse over time).
- Loading from the centre of the screen outwards, 8 images at a time; images no longer on screen are not
  downloaded; the small thumbnail stays visible until the large one arrives.
- High definition from 34 px on screen (instead of 72): no more blurry stage. On WikiArt 81k, medium
  zoom: 489 thumbnails in about 2 s; up close, under half a second.

## 0.13.3 — 2026-11-17 · Searching a region with words

- `pixplot zones`: each work cut into 20 regions (2×2 and 4×4 grids) run through SigLIP 2, resumable
  extraction, then a compressed index with exact re-ranking.
- Atlas: "Zone décrite" search mode ("a halo", "a skull"); `/api/search/zones` API; `search_zones`
  MCP tool (15 tools).
- WikiArt 81k: 1,614,320 regions in 6 h 21; a search in 0.5 s (ARCHITECTURE § 22).
- Fix: region runs are no longer mistaken for whole-work vectors.

## 0.13.2 — 2026-11-17 · Typed, dated places

- Several places per work, each with a type (creation, exhibition, holding, depicted place, artist's
  birth / residence / death), a date and a source: `pixplot import-places`, `pixplot places --derive`
  (inferred from metadata), bundled gazetteer of cities and institutions.
- Geography view: choice of place type, circulations between a work's places, time slider, critical
  note. `/api/places` API.
- After B. Joyeux-Prunel, "ARTL@S" (2012): ARCHITECTURE § 21.

## 0.13.1 — 2026-11-17 · Critical layer

- A card per way of seeing (model, training data, what it sees and does not see, biases, results) in
  the Atlas ("Corpus" button, key I), the API and the MCP server.
- `pixplot corpus` and `/api/corpus`: corpus report (label coverage and source, artist concentration,
  non-Western styles, dates, places).
- WikiArt labels flagged as volunteer-made, to be checked; MCP security rule (metadata is data,
  never instructions).
- After A. Wasielewski, *Computational Formalism*, and T. Arnold and L. Tilton, *Distant Viewing*
  (ARCHITECTURE § 20).

## 0.13.0 — 2026-11-16 · Searching a region with words: TIPSv2 evaluated

- `pixplot zonebench`: benchmark on RichArt (709 paintings, 1,243 objects described by museum
  catalogues) — finding the region in the corpus and pointing at it in its painting.
- `tipsv2_b14` and `tipsv2_so400m14` encoders (Google DeepMind, Apache 2.0), kept for reproducibility.
- Result (ARCHITECTURE § 19): SigLIP 2 on cropped regions beats TIPSv2 (28% vs 20% at rank 1);
  TIPSv2 is not integrated into the Atlas. Next: a SigLIP 2 region index.

## 0.12.2 — 2026-11-16 · First benchmark on 104 validated pairs

- 104 pairs validated by the art historian, versioned in `bench/wikiart81k_pairs.csv` (with the
  works' labels) and the review log.
- Results (ARCHITECTURE § 18), measuring only the ways of seeing not used to choose each pair:
  each wins on the resemblance it should see, except composition (subject wins); Leiden keeps
  more pairs in one group than e-means (form 24 → 33%).

## 0.12.1 — 2026-11-16 · Quick pair review

- Anki-style review (key R in the Atlas): one pair at a time, large; Enter or 1 to 7 to validate
  with a kind of resemblance, R to dismiss, Space to skip, Z to undo.
- The queue chains proposed pairs, then candidates drawn from disagreements between ways of
  seeing; dismissed candidates are logged in `bench/review_log.csv` and never come back.
- `/api/review/queue`, `/api/review`, `/api/review/undo` API.

## 0.12.0 — 2026-11-16 · Disagreements between ways of seeing, pair review

- `pixplot disagreements`: for each couple of ways of seeing, pairs very close in one and far in
  the other; in the Atlas, "Désaccords" button (key D).
- "À vérifier": "Paires de référence" tab to validate or reject proposed pairs.
- `/api/disagreements` API; `/api/pairs` also returns the works' labels.

## 0.11.0 — 2026-11-16 · Leiden groups

- `pixplot communities`: nested Leiden groups (families ⊃ groups) for each way of seeing, on the
  neighbour graph; adjustable number of groups (`--groups`, `--families`).
- Atlas: colour by "Familles Leiden" or "Groupes Leiden" of each way of seeing; `/api/communities/{space}` API.
- Comparison with e-means on WikiArt 81k (ARCHITECTURE § 15): more stable for form, subject and touch,
  better agreement with artists for touch; not for colour. Named groups stay e-means for now.

## 0.10.2 — 2026-11-16 · Project website

- Presentation website in English and French (https://riyadhhda.github.io/pixplot-v2/), published on GitHub Pages by a GitHub
  Action whenever `site/` changes; local preview: `bash scripts/build_site.sh`.

## 0.10.1 — 2026-11-16 · Roadmap

- `ROADMAP.md` / `ROADMAP.fr.md`: steps 0.11 to 0.15 (Leiden groups, disagreements between ways of
  seeing, searching a region with words with TIPSv2, Iconclass names, composition), the success
  condition of each, what is ruled out and the conditions for 1.0.

## 0.10.0 — 2026-11-16 · Pair benchmark

- `pixplot pairs`: measures which way of seeing finds which *kind* of resemblance (same
  subject, same composition, same hand, same handling, same motif, same palette,
  filiation, control), by exact rank among the whole corpus (R@10, R@100, median rank,
  percentile).
- Pairs annotated by the art historian (with source and validated / proposed / rejected
  status) and pairs drawn from metadata, always reported separately.
- Atlas: "Annoter" button in the comparator, "référence" column.
- First 11 proposed pairs, from Honour and Fleming and well-known filiations.
- `pixplot --version`; version in `/api/info` and the MCP server.

## 0.9.0 — 2026-11-16 · Group-naming vocabulary

- 21 subjects and 23 manners from the glossary of Honour and Fleming, *The Visual Arts: A
  History* (Annunciations, altarpieces, chiaroscuro, sfumato, grisaille, plein air…).

## 0.8.0 — 2026-11-16 · One map per way of seeing, redesigned interface

- `pixplot maps`: one UMAP map per way of seeing (subject, colour, touch).
- Geographic view on a bundled world base map.
- Lighter header, screen-adaptive panels, welcome screen, help, keyboard shortcuts.

## 0.7.1 — 2026-11-16 · Project page

- Banner, screenshots, English and French documentation, credits.

## 0.7.0 — 2026-11-16 · Four ways of seeing

- Subject (SigLIP 2), colour (CIELAB) and touch (DINOv3 intermediate layers) spaces.
- Comparator, research notebook, timeline and geography, group names, labels to check,
  IIIF import (validated on the Yale Center for British Art).

## 0.6.0 — 2026-11-16 · Audit and scale

- Blind audit against the labels; every thumbnail shown without flicker.
- Full WikiArt: 80,716 works in ≈ 1 h 21 on a single PC.

## 0.5.0 — 2026-11-15 · MCP server and Research Packs

## 0.4.0 — 2026-11-15 · Detail search and free-text search (SigLIP 2)

## 0.3.0 — 2026-11-15 · FastAPI and the interactive Atlas (deck.gl)

## 0.2.0 — 2026-11-15 · E-means groups, HDBSCAN, UMAP map

## 0.1.0 — 2026-11-15 · Ingestion, vectors, FAISS index, label benchmark
