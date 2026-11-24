# PixPlot commands

**English** · [Français](COMMANDS.fr.md)

Every command is written `pixplot [--data FOLDER] <command> [options]`. This document groups them
by stage of work; `pixplot <command> -h` details each option (help texts are in French). A test
(`tests/test_commands_doc.py`) checks that no command is missing here and that no command
described here has disappeared.

## Before you start

`--data` names the corpus folder (otherwise the `PIXPLOT_DATA` variable, otherwise `./data`). Every
command writes its results into that folder, never elsewhere.

```bash
pixplot doctor                                   # the installation and the graphics card
pixplot --data data/wikiart81k status            # what the corpus holds, and its computations
pixplot --data data/wikiart81k serve --open      # the Atlas in the browser
```

| Command | What it does | Useful options |
|---|---|---|
| `pixplot doctor` | checks the installation: Python, graphics card, libraries | — |
| `pixplot status` | state of the catalogue and list of computations (*runs*) | — |
| `pixplot runs` | same as `status` | — |
| `pixplot sauvegarde` | keeps hand-made work safe: copies the reviewed pairs into the repository's `bench/` (to commit) and, with `--vers`, the data folder to another disk; never deletes anything | `--vers`, `--tout`, `--carnet`, `--force` |
| `pixplot --version` | version number | — |

## Bringing works in

| Command | What it does | Useful options |
|---|---|---|
| `pixplot ingest` | catalogues one or more image folders and makes the thumbnails | `--workers`, `--limit` |
| `pixplot import-metadata` | imports artist, date, style… from a CSV (`path` column) | `--source` |
| `pixplot import-iiif` | downloads a museum collection through its IIIF manifests | `--out`, `--max-size`, `--all-canvases`, `--delay` |
| `pixplot wikiart-noms` | titles and dates (MMArt), emotions (ArtEmis), missing artists, by image fingerprint | `--mmart`, `--artemis`, `--artistes` |
| `pixplot import-places` | typed, dated places from a CSV | `--source` |
| `pixplot places` | summary of places; `--derive` infers them from the metadata | `--derive` |

## Computing the regards

Long computations resume where they stopped and write a log in the corpus folder.

| Command | What it does | Useful options |
|---|---|---|
| `pixplot embed` | computes the vectors of a regard (one encoder = one regard) | `--encoder`, `--batch-size`, `--no-resume` |
| `pixplot index` | builds the FAISS index of a vector run | `--kind flat\|hnsw`, `--regions` |
| `pixplot zones` | 20 zones per work seen by SigLIP 2, then their index (find a detail with words) | `--batch`, `--index-only` |

## Analysing

| Command | What it does | Useful options |
|---|---|---|
| `pixplot analyze` | groups (e-means), UMAP map, neighbourhoods, atypical works: creates an analysis run | `--clusters`, `--no-map` |
| `pixplot maps` | one map per regard; `--localmap` adds the LocalMAP trial map | `--spaces`, `--force`, `--localmap` |
| `pixplot tiles` | precomputed tile pyramid for the main Atlas map (CPU, resumable) | `--max-level`, `--tile-size`, `--format`, `--no-resume` |
| `pixplot communities` | nested Leiden groups (families ⊃ groups), one set per regard | `--spaces`, `--groups`, `--families` |
| `pixplot name-groups` | proposes a name for each group (SigLIP 2 and vocabulary) | `--show` |
| `pixplot iconclass` | proposes group names drawn from Iconclass | `--fetch` |
| `pixplot disagreements` | pairs that one regard brings together and another separates | `--spaces`, `--rank`, `--centile` |
| `pixplot suspects` | labels that are probably wrong (all the neighbours say something else) | `--keys`, `--space` |
| `pixplot doublons` | works entered twice, replicas and variants (SSCD) | `--same`, `--variant` |
| `pixplot ordre` | order and disorder of the paint surface (entropy, complexity), no GPU | `--workers` |
| `pixplot notions` | notions learned by a regard (sparse autoencoder); `--nommer` names an existing run through SigLIP 2 | `--space sujet\|forme`, `--nommer` |
| `pixplot corpus` | critical summary of the corpus; `--datasheet` writes its datasheet | `--datasheet` |

## Searching and exporting

| Command | What it does | Useful options |
|---|---|---|
| `pixplot similar` | works closest to a work (number or image path) | `-k`, `--html` |
| `pixplot search-text` | works that match a description, in French or English | `-k`, `--encoder` |
| `pixplot pack` | Research Pack (.zip): works, metadata, datasheet, for an LLM or a colleague | `--ids`, `--cluster`, `--similar`, `--text`, `--detail` |

## Opening the Atlas and the servers

| Command | What it does | Useful options |
|---|---|---|
| `pixplot serve` | the Atlas, an interactive map, reachable only from this PC by default | `--port`, `--open`, `--analysis` |
| `pixplot mcp` | MCP server: gives Claude or another LLM access to the corpus (see [MCP](MCP.md)) | `--analysis` |
| `pixplot antigravity-mcp` | MCP server: a second opinion from Antigravity, read-only | — |

## Benchmarks

Each benchmark writes a dated report in `<data>/bench/`. A computed proximity is a lead, not a
proof: the benchmarks measure what each regard finds, not what is true.

| Command | What it does | Useful options |
|---|---|---|
| `pixplot bench` | compares runs on labels (artist, style, genre) and known pairs | `-k`, `--keys` |
| `pixplot pairs types` | the kinds of resemblance (same composition, filiation, same gesture…) | — |
| `pixplot pairs add` | adds a pair of works validated by hand | `--type`, `--source`, `--note` |
| `pixplot pairs list` | the recorded pairs | `--status` |
| `pixplot pairs generate` | proposes pairs to review, by type | `-n`, `--seed` |
| `pixplot pairs bench` | which regard finds which resemblance, on the validated pairs | `--spaces`, `--proposed` |
| `pixplot pairs ci` | confidence intervals of the last `pairs bench` (bootstrap) | `--boot`, `--all-origins` |
| `pixplot composition` | "composition" benchmark: regards, PE-Spatial, 4 × 4 layouts | — |
| `pixplot zonebench` | find a zone with words: RichArt benchmark | `--encoders` |
| `pixplot textbench` | sentence search, on the MMArt descriptions | `-n`, `--encoders` |
| `pixplot whytest` | puts the "Why?" button to the test by occlusion | `-k`, `--random` |
| `pixplot audit` | blind audit: where the groups contradict the labels | `--keys`, `--min-count` |

## Stability

Before 1.0, a command or an option may still change; each change is recorded in the
[CHANGELOG](../CHANGELOG.md). From 1.0 on, the commands in this document and the formats in
[FORMATS](FORMATS.md) will not change without a new major version.
