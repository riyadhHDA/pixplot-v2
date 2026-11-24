# Mistral Proposals — recent papers, ideas, skills / MCP / API

**English** · [Français](PROPOSITIONS-MISTRAL.fr.md)

*Last updated: 2026-11-24.*

This file collects the **proposals** discussed with Mistral Vibe: recent scientific papers, new
features, skills, MCP tools, API routes. It is not the roadmap — the [ROADMAP](../ROADMAP.md)
decides. This file keeps the memory of leads: a proposal that gets implemented leaves here
(CHANGELOG + ARCHITECTURE) and becomes "done"; a rejected proposal keeps its reasons and numbers.

## How to update this file

- Each entry has a **date**, a **source** (paper with arXiv/DOI, or discussion) and a
  **status**: `to test`, `in progress`, `done`, `rejected` (with the reason).
- Papers are grouped by theme, most recent first; those marked "read first" go on top.
- **Both languages are updated together** (`PROPOSITIONS-MISTRAL.fr.md` and
  `PROPOSITIONS-MISTRAL.md`), with the same section structure.
- New entries go on top of the tables; history is never rewritten.

Update format:

```text
- 2026-11-24 | emotion zones (APOLO masks × SigLIP 2 zones) | EmoSEM, arXiv 2504.14658 | to test
```

## Papers spotted (2025–2026)

| Paper (date) | Ref. | Why it matters for PixPlot | Status |
|---|---|---|---|
| M-ArtAgent + WikiArt Influence Benchmark WIB-100 (2026) | arXiv 2604.07468 | Ready-made "filiation" benchmark on WikiArt | read first |
| Sparse Autoencoders Learn Monosemantic Features in VLMs (Apr. 2025) | arXiv 2504.02821 | Tested on SigLIP SoViT-400m (our model); framework to score our SAE notions | read first |
| EmoSEM: segmenting the regions that trigger emotion (Apr. 2025); link with APOLO / ArtEmis unverified | arXiv 2504.14658 | Locate emotion inside the painting, crossed with our 1.6 M zones | read first |
| fruit-SALAD, Scientific Data (2025) | s41597-025-04529-4 | Human-perceived similarity projected into embeddings: judge the gazes | **reference not verified** (page unreachable on 2026-11-24) |
| Dare to Plagiarize? (June 2025) | arXiv 2506.23132 | Detection + retrieval of the authentic source (duplicates, filiation) | read first |
| SAM 3: Segment Anything with Concepts (Nov. 2025) | arXiv 2511.16719 | Segment a motif from a phrase ("halo"), already in the ROADMAP | read first |
| ArtSeek: late-interaction retrieval for art (July 2025) | arXiv 2507.21917 | Fine-grained text search (zones), PaintingForm benchmark | read first |
| Patch-to-region, ColPali family (Dec. 2025); about documents, not art | arXiv 2512.02660 | Multi-zone text + spatial queries on our zone grid | read first |
| AVAtt: eye-tracking on paintings (Oct. 2026) | arXiv 2610.30481 | Painting-specific saliency (16 movements, 5 centuries) | read first |
| Uncertainty-Aware Art-Historical Dating with VLMs (2026) | arXiv 2608.18984 | Visual dating with confidence intervals | read first |
| Relational Visual Similarity (Dec. 2025) | arXiv 2512.07833 | Analogies A:B::C:? between artworks (disagreements, paragone) | spotted |
| jina-clip-v2, multilingual CLIP (Dec. 2024) | arXiv 2412.08802 | Challenger SigLIP 2 for French text search (textbench) | spotted; weights under CC BY-NC 4.0 (non-commercial) |
| Art Beyond Semantics: sheaf + WikiArt+, HertzianaDP benchmarks (2026) | arXiv 2607.16321 | Multi-relational representations artwork/artist/school | spotted |
| Automating Iconclass: LLM + RAG (Oct. 2025) | arXiv 2510.19986 | Name groups and notions without SigLIP, 92 % without fine-tuning | spotted |
| VQArt-Bench: art and heritage VQA (Oct. 2025) | arXiv 2510.12750 | Quantitatively evaluate the MCP server's answers | spotted |
| GeoToken: image geolocalization, local-first (Nov. 2025) | arXiv 2511.01082 | Estimate the depicted place of a landscape (complements the places view) | spotted |
| Revisiting Wölfflin in the Age of AI, J. Imaging (2025) | doi 10.3390/jimaging11050128 | Compare with our linear/painterly axis (§ 43) | **reference not verified** (page unreachable on 2026-11-24) |
| Two-by-two ordinal patterns in art paintings (Mar. 2025) | arXiv 2503.09844 | Extension of permutation entropy (`pixplot ordre`) | spotted |
| Forensic Study of Paintings: canvas comparison (June 2025) | arXiv 2506.20272 | Material/workshop filiation (museum corpus, HD scans) | spotted |
| Curating art exhibitions using machine learning (2025) | arXiv 2506.19813 | Suggest a hang from the map (Research Pack) | spotted |
| DINOv3 (Meta, Aug. 2025) | arXiv 2508.10104 | Our "form" gaze; § 6.1.3 = part correspondences ("Why?") | spotted |
| SigLIP 2 (Feb. 2025) | arXiv 2502.14786 | Our "subject" gaze; NaFlex variant (native resolution, no letterbox) | spotted |

## Feature proposals

| Priority | Proposal | Based on | Acceptance benchmark | Effort | Status |
|---|---|---|---|---|---|
| P1 | Emotion zones: where in the painting the emotion sits | APOLO × zone index | predicted zone inside the annotated mask (vs chance) | ~1 d | to test |
| P1 | "Human perception" benchmark: ~200 pairs rated by humans | fruit-SALAD | gaze ranking on human ratings, with CIs (`pairs ci`) | 2–3 d | to test |
| P1 | Predictive dating + CI for undated works | arXiv 2608.18984 | median error in years + calibrated CIs on the 56,794 dated works | 1–2 d | **done**: `pixplot dater`, ARCHITECTURE § 45 |
| P1 | French text search challenged (jina-clip-v2, SigLIP 2 NaFlex) | arXiv 2412.08802 | `textbench` FR/EN, CIs included | 1 d | to test |
| — | The 4 other Wölfflin pairs as concept axes | J. Imaging 2025 | same bench as § 43 (AUC + Spearman with dates) | — | **rejected**: already measured (§ 43, DeepSeek's benchmark); these four pairs do not hold, the result flips with the wording or the genre |
| P2 | Influence graph "who copies whom" as a node-link view | WIB-100, arXiv 2604.07468 | R@10 on WIB-100 + 9 filiation pairs | 1–2 wk | to test |
| P2 | Predicted saliency: "where do we look" (sheet + map layer) | AVAtt, SPGen | NSS/AUC vs human fixations | 3–5 d | to test |
| P2 | Visual analogies A is to B as C is to ? | arXiv 2512.07833 | "same composition" / "filiation" pairs | 3–5 d | to test |
| P2 | Motifs segmented by phrase (SAM 3), searched corpus-wide | arXiv 2511.16719 | RichArt + cross-corpus | 1–2 wk | to test (Meta licence) |
| P2 | Multi-zone query: "a blessing hand top right + a skull at the bottom" | arXiv 2512.02660, ArtSeek | 50 composed queries, rank of target work | 1–2 wk | to test |
| P2 | Name SAE notions with LLM + Iconclass RAG | arXiv 2510.19986 | review of the 489 named notions (cf. § 23) | 2–3 d | to test |
| P3 | Wikidata knowledge graph (artists, movements, places) | source to find (arXiv 2602.19133 is a named-entity dataset, FRAME, not "ArtContext") | queries checkable on Wikidata | 1–2 wk | to test |
| P3 | VQA benchmark to evaluate the MCP server | VQArt-Bench | MCP score on art questions | 3–5 d | to test |
| P3 | Geolocalization of painted landscapes | GeoToken | estimated places vs `places` metadata | 3–5 d | to test |
| P3 | Exhibition hang proposal from the map | arXiv 2506.19813 | hang judged by the user | 1 wk | to test |
| P3 | AI-generated artwork detection in "To check" | source to find (arXiv 2511.22471 is about forgery detection with DINOv3, not art; "ArtUnmasked" not found) | labelled AI/human corpus | 3–5 d | to test |
| P3 | Canvas / workshop (material filiation) | arXiv 2506.20272 | museum corpus with HD scans (Paris Musées) | ? | rejected for WikiArt (no HD scans) |

## Skills, MCP and API

| Surface | Proposal | Acceptance criterion | Status |
|---|---|---|---|
| skill | `pixplot-bench`: create/extend a benchmark, 95 % CI, dated ARCHITECTURE § | an assistant runs a benchmark end to end | to test |
| skill | `pixplot-encoder`: evaluate a new encoder (licence, registry, NOT_KEPT, benches) | procedure followed for one encoder | to test |
| skill | `pixplot-release`: semver + 7 files + tag + bilingual release | `pytest` passes after bump | to test |
| skill | `pixplot-doc`: FR/EN parity, COMMANDS/FORMATS, HANDOFF at session end | parity tests pass | to test |
| skill | `pixplot-audit`: Argon-style review (verify before fixing) | numbered actionable report | to test |
| skill | `pixplot-papers`: literature watch (arXiv/HAL), reading note, ROADMAP proposal | one note per paper, link to a workstream | to test |
| skill | `pixplot-licences`: licence checklist before any download, data/ out of git | no download without a ticked box | to test |
| skill | `pixplot-mcp`: add an MCP tool in 6 steps (code → FR/EN doc → README → site → test) | one tool added end to end | to test |
| MCP | `estimate_date(id)`: visual dating + CI | calibrated CIs on dated works | to test |
| MCP | `emotion_zones(id)` / `saliency(id)` | APOLO masks / AVAtt fixations | to test |
| MCP | `find_influence(id, k)`: sources and derivatives | WIB-100 + filiation pairs | to test |
| MCP | `segment_motif(id, phrase)`: SAM 3 + cross-corpus search | RichArt | to test (licence) |
| MCP | `search_composed([{text, region}…])`: multi-zone query | 50 composed queries | to test |
| MCP | `analogy(a, b, c)`: A:B::C:? | composition/filiation pairs | to test |
| MCP | `bench_results()` / `run_bench(name)`: benchmarks from the LLM | VQArt-Bench for self-evaluation | to test |
| MCP | `list_runs()` / `run_status(name)`: drive long computations | run tracked without a terminal | to test |
| MCP | `save_pairs()` / `export_bench()`: copy pairs.csv, notebook, names to `bench/` | "save data/" workstream | **done differently**: `pixplot sauvegarde` command (2026-11-24) |
| API | `GET /api/runs` + `/api/runs/{id}/progress` (SSE) | progress visible in the Atlas | to test |
| API | `/api/artwork/{id}/emotion-zones`, `/saliency`, `/date-estimate` | panels in the artwork sheet | to test |
| API | `GET /api/analogy`, `POST /api/search/regions`, `POST /api/segment` | comparator + advanced search | to test |
| API | `GET /api/influence/graph`: node-link view of the influence graph | graph drawn in the Atlas | to test |
| API | `GET /api/export/iiif`: Research Pack as an IIIF Presentation 3 collection | pack reloadable via `import-iiif` | to test |
| API | `GET /api/bench`: benchmark results (CIs) for a "Metrics" panel | 95 % CIs displayed | to test |
| API | `GET /api/health` + pagination on `/api/map`, `/api/search` | fresh-machine test (1.0 condition) | to test |

## Update history

- 2026-11-24 — File created: read-only codebase analysis, 2025–2026 literature review, feature
  and skills / MCP / API proposals.
- 2026-11-24 — Reviewed by Claude: all 24 references checked at the source (arXiv, publishers). 19 correct;
  3 wrong ones fixed (SigLIP 2 = 2502.14786; 2602.19133 and 2511.22471 do not match "ArtContext" and
  "ArtUnmasked"); 2 unverifiable (fruit-SALAD, J. Imaging); EmoSEM with no established link to APOLO / ArtEmis.
  Wölfflin (4 other pairs) rejected as already measured (§ 43); backup done (`pixplot sauvegarde`).
