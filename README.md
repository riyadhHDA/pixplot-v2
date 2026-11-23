<p align="center">
  <img src="docs/images/banner.png" alt="PixPlot v2 — map of 80,716 WikiArt artworks, grouped by visual similarity" width="100%">
</p>

<p align="center">
  <b>English</b> · <a href="README.fr.md">Français</a> · <a href="https://riyadhhda.github.io/pixplot-v2/"><b>Project website</b></a>
</p>

<p align="center">
  <a href="LICENSE"><img alt="Licence: GPL-3.0" src="https://img.shields.io/badge/licence-GPL--3.0-e0b040"></a>
  <a href="https://github.com/riyadhHDA/pixplot-v2/releases"><img alt="Version" src="https://img.shields.io/github/v/release/riyadhHDA/pixplot-v2?label=version&color=e0b040"></a>
  <a href="https://doi.org/10.5281/zenodo.24363789"><img alt="DOI" src="https://zenodo.org/badge/DOI/10.5281/zenodo.24363789.svg"></a>
  <a href="https://github.com/riyadhHDA/pixplot-v2/actions/workflows/tests.yml"><img alt="Tests" src="https://github.com/riyadhHDA/pixplot-v2/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="Python 3.12" src="https://img.shields.io/badge/python-3.12-3776ab">
  <img alt="100% local" src="https://img.shields.io/badge/100%25-local-2c2c31">
  <img alt="GPU: AMD ROCm or CPU" src="https://img.shields.io/badge/GPU-AMD%20ROCm%20%7C%20CPU-9b978e">
  <img alt="MCP server" src="https://img.shields.io/badge/MCP-19%20tools-e0b040">
</p>

# PixPlot v2

PixPlot v2 is a local tool for exploring large art-history image collections by visual similarity. It rewrites the
idea behind the Yale DHLab's [PixPlot](https://github.com/YaleDHLab/pix-plot) (2018) from scratch around current
vision models (DINOv3, SigLIP 2) so the whole workflow runs on a single desktop PC.

Because the models only see pixels, a high similarity score never proves influence or attribution. The tool keeps
roles separate: PixPlot computes and indexes, an MCP assistant can help search and compare, and verification stays
with the historian.

## What you can do with your corpus

Start from a folder of images, a museum IIIF collection or a dataset such as WikiArt, with or without metadata.
PixPlot then answers art historians' questions. The examples come from WikiArt 81k; every result is a lead to
check, not a conclusion.

| Your question | What PixPlot does | Example on WikiArt |
|---|---|---|
| **Who copied, quoted or reworked whom?** | Nearest neighbours under four regards, a comparator and a "Pourquoi ?" button that shows the zones answering each other. | Van Gogh's *Sower* finds Millet's at rank 1; so does Rubens's copy of Titian's *Rape of Europa*. |
| **Where does this motif come back?** | Search for a **detail** drawn on an image, or for a **zone described** in words, across 1.6 million zones. | "A halo", "a skull", "a blessing hand": the exact zone is framed in every work found. |
| **Which works deal with this theme?** | **Free-text** search (French or English) and **conceptual axes**: the whole corpus placed between two words. | "Annunciation in a garden"; the corpus laid out between "sacred" and "profane". |
| **Is my catalogue reliable?** | A **To check** list of labels contradicted by all neighbours, and **duplicate** detection. | 4,884 labels to check; 839 works entered twice, 702 of them under two different styles (the same Corot as "Romantic" and "Realist"). |
| **What brings these two works together?** | The same pair seen through form, subject, colour and touch; **disagreements** between regards (same composition, different subject…). | A layout reused for another theme; one subject painted by two hands. |
| **What is my corpus made of?** | A map of named groups (art-history vocabulary and **Iconclass**), **combined filters**, timeline and geographic views, a report on what is missing. | "Baroque" + "portrait" = 980 works, lit up on the map in 14 ms. |
| **How do I keep track of my research?** | A **research notebook**, **Research Pack** export (.zip: images, sourced metadata, scores, method, corpus datasheet) and an assistant plugged in through **MCP** that searches and compares with you. | A file ready for a seminar, a thesis or a colleague's review. |
| **Which model sees what?** | Benchmarks on pairs validated by the historian; every model has a card (training data, biases). | Four models set aside after measurement (TIPSv2, PE-Spatial, SSCD, Depth Anything), figures published (ARCHITECTURE § 19, 24, 27, 28). |

## Full WikiArt on one PC

![The Atlas: 80,716 works, a Claude Monet record and its nearest neighbours](docs/images/atlas-artwork.jpg)

All of WikiArt (**80,716 artworks**, 81,444 images, 33.7 GB) runs end to end in **≈ 1 h 21** on a Windows 11 PC
with an AMD Radeon RX 7900 GRE and 16 GB of RAM: ingestion, DINOv3 and SigLIP 2 embeddings, an index of
1.58 million image regions, clustering, map layout, blind audit and benchmark. The Atlas opens in roughly 3 seconds
with all thumbnails rendered, and a text or detail query returns in 0.25 s.

<details>
<summary>The full map: 142 coloured groups</summary>

![Overview of the 80,716 artworks coloured by group](docs/images/atlas-overview.jpg)
</details>

## Main features

| | |
|---|---|
| **Four separate spaces** | **Form** (DINOv3: silhouettes, layout), **subject** (SigLIP 2: theme, genre, school), **colour** (CIELAB palette) and **touch** (brushwork and grain from DINOv3 layer 6). Comparing spaces helps see why two works match or diverge. |
| **Search** | By metadata, by **free text** in French or English (SigLIP 2), by **described zone** ("a halo", "a skull" across 1.6M regions) or by **detail** by drawing a box directly on a painting. |
| **Groups** | Spherical clustering (e-means) and nested Leiden communities, with tentative names proposed from an art-history vocabulary. |
| **Web Atlas** | Interactive offline deck.gl map, records with sourced metadata and neural-free **visual measures** (balance, symmetry, chromatic entropy, after Stork), a **comparator** (up to six works with a "Pourquoi ?" zone matcher), **combined filters** (artist, style, genre, group…), a **research notebook**, one map per space, **2D conceptual axes** on two words (after *2D CLIP*), plus **timeline** and **geographic** views (typed/dated places, offline world map). |
| **Catalogue audit** | Blind audit (pixels only), a **To check** list of works whose label is contradicted by all their neighbours (either a cataloguing error or an unusual work) and **duplicates**: works entered twice and their variants (`pixplot doublons`). |
| **IIIF museum imports** | `pixplot import-iiif` ingests IIIF v2/v3 manifests and collections with normalised metadata and rights fields. |
| **MCP server (20 tools)** | Connects Claude or any compatible assistant to search, inspect images and crops, compare works, run visual measures, probe conceptual axes and add notes to the notebook. |
| **Traceability** | Every computation is saved in a dated *run* (`manifest.json` with model, parameters and parent run). Exporting a *Research Pack* (.zip) bundles images, sourced metadata and scores. |

## Some measurements on WikiArt

Across all 80,716 works ([ARCHITECTURE.md § 11–12](ARCHITECTURE.md#11-scaling-up-the-full-wikiart-corpus-16112026)),
share of the 10 nearest neighbours carrying the same label as the query work:

| Space | artist | style | genre | Pointillism | Fauvism |
|---|---|---|---|---|---|
| form (DINOv3) | 33.9% | 52.4% | 76.8% | 21% | 20% |
| subject (SigLIP 2) | **42.9%** | **62.0%** | **79.5%** | 44% | 26% |
| touch | 35.0% | 49.6% | 62.8% | **62%** | **30%** |

"Artist" column recomputed on 2026-11-19 over 1,090 artists, after recovering the artist of 35,185
"Unknown Artist" works through MMArt ([§ 34](ARCHITECTURE.md)): the task is harder than with 129
artists (before: 50.8 / 61.6 / 53.0%); the ranking of the regards does not change.

- For a purely visual model, subject tends to dominate manner; SigLIP 2 recovers standard art-history categories best.
- **Touch** catches styles defined by brushwork (Pointillism jumps from 21% to 62%) and recognises the artist's hand better than global form.
- WikiArt labels are noisy: the audit surfaces real cataloguing errors (such as religious scenes filed under genre painting).
- HDBSCAN breaks down on such a dense continuum; the atypicality score is a much more reliable signal for outliers.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate                 # Linux / macOS: source .venv/bin/activate
pip install -e ".[dev,ml]"             # install PyTorch first (AMD ROCm wheels): docs/INSTALL_GPU.md
pytest

pixplot ingest "D:/MyImages"           # catalogue, thumbnails, duplicates
pixplot import-metadata meta.csv       # artist, date, style… ("path" column required)
pixplot embed                          # DINOv3 vectors (GPU), resumable
pixplot analyze                        # groups, UMAP map, neighbourhoods
pixplot serve --open                   # opens the Atlas at http://127.0.0.1:8765
```

To run the whole pipeline at once with a timed log: `bash scripts/full_pipeline.sh data/my_corpus "My source"`.

<details>
<summary>All commands</summary>

```bash
pixplot doctor                          # Python, PyTorch, GPU
pixplot import-iiif URL --out D:/Museum # museum collection (IIIF v2/v3 manifest or collection)
pixplot embed --encoder siglip2_so400m  # text↔image space ("subject")
pixplot embed --encoder dinov3_vitb16_texture   # "touch" space
pixplot embed --encoder color_lab       # "colour" space (no GPU)
pixplot embed --encoder colorhist       # whole pipeline without GPU, for testing
pixplot index [--encoder NAME]          # FAISS index of the latest run
pixplot index --regions                 # region index → "Search a detail" in the Atlas
pixplot maps                            # one UMAP map per space (subject, colour, touch)
pixplot communities                     # nested Leiden communities (families ⊃ groups) per space
pixplot disagreements                   # pairs close in one space and far in another
pixplot zonebench                       # searching a region with words: RichArt benchmark
pixplot zones                           # region index (20 per work, SigLIP 2): "a halo", "a skull"
pixplot corpus                          # corpus report: missing metadata, model bias cards
pixplot places --derive                 # typed and dated places derived from metadata
pixplot import-places places.csv        # typed and dated places from CSV
pixplot name-groups                     # name groups (SigLIP 2 + art-history vocabulary)
pixplot suspects                        # labels contradicted by all neighbours
pixplot search-text "Annunciation in a garden"
pixplot similar 42 --html sheet.html    # nearest neighbours as an HTML sheet
pixplot audit                           # blind audit against labels
pixplot bench                           # compare runs (labels, known pairs)
pixplot pairs generate | bench          # pair benchmark: which space finds which kind of kinship
pixplot pack --text "Annunciation" -k 20 --question "…"   # Research Pack (.zip)
pixplot corpus --datasheet                                  # corpus datasheet (provenance, rights, gaps; in French)
pixplot mcp                             # MCP server: see docs/MCP.md
pixplot status
```
</details>

## Documentation

- [**Practical guide**](https://riyadhhda.github.io/pixplot-v2/guide/): reading scores, three workflows (filiation, label, motif), working with an assistant, citing ([Français](https://riyadhhda.github.io/pixplot-v2/fr/guide/))
- [ARCHITECTURE.md](ARCHITECTURE.md): design, benchmarks and detailed measurements ([Français](ARCHITECTURE.fr.md))
- [docs/INSTALL_GPU.md](docs/INSTALL_GPU.md): GPU setup on Windows 11 (AMD ROCm), WSL2 fallback, model weights ([Français](docs/INSTALL_GPU.fr.md))
- [docs/MCP.md](docs/MCP.md): connecting Claude or another assistant ([Français](docs/MCP.fr.md))
- [ROADMAP.md](ROADMAP.md): planned work, success criteria and dropped experiments ([Français](ROADMAP.fr.md))
- [CHANGELOG.md](CHANGELOG.md): release history ([Français](CHANGELOG.fr.md))

Code comments and the Atlas UI are in French; documentation is maintained in both French and English.

## Design choices

- **Local first:** no image leaves the computer and there is no telemetry.
- **Whole images:** no centre-cropping before encoding (letterboxing preserves aspect ratio and composition).
- **Traceable runs:** every output stores its model, version and parameters.
- **Benchmark before keeping:** models that fail to beat the baseline (TIPSv2, PE-Spatial) are documented and dropped.

## Author

**Riyadh HADJBA**, art history student at the [University of Strasbourg](https://www.unistra.fr).
Conceived and directed by Riyadh HADJBA, built with the help of coding assistants (Claude and Gemini).

## Citing PixPlot v2

> Riyadh HADJBA, *PixPlot v2 : un laboratoire d'exploration visuelle pour l'histoire de l'art*,
> software, Université de Strasbourg, 2026. DOI: [10.5281/zenodo.24363789](https://doi.org/10.5281/zenodo.24363789).

This DOI covers all versions; each release also gets its own DOI on
[Zenodo](https://doi.org/10.5281/zenodo.24363789). APA and BibTeX formats are available from GitHub's "Cite this
repository" button ([`CITATION.cff`](CITATION.cff)).

## Licence and credits

Released under the **GPL-3.0** licence ([LICENSE](LICENSE)).

- Inspired by [PixPlot](https://github.com/YaleDHLab/pix-plot) (Yale DHLab, MIT), rewritten from scratch with no code reused.
- Models: [DINOv3](https://github.com/facebookresearch/dinov3) (Meta, DINOv3 licence, weights never redistributed here), [SigLIP 2](https://huggingface.co/google/siglip2-so400m-patch16-384) (Google, Apache 2.0).
- Libraries: FAISS and e-means (Meta, MIT), UMAP, scikit-learn, deck.gl, FastAPI, MCP Python SDK. World base map: [world-atlas](https://github.com/topojson/world-atlas) (ISC), from [Natural Earth](https://www.naturalearthdata.com) (public domain).
- Group-naming vocabulary extended from the glossary of H. Honour and J. Fleming, *The Visual Arts: A History* (revised 7th ed., 2023) — only the terms are used.
- Readings that shaped the design: A. Wasielewski, *Computational Formalism* (MIT Press, 2023); B. Joyeux-Prunel, "ARTL@S" (*Artl@s Bulletin*, 2012); T. Arnold and L. Tilton, *Distant Viewing* (MIT Press, 2023); H. Honour and J. Fleming, *The Visual Arts: A History* (2023); L. Impett and F. Offert, "There Is a Digital Art History" (*Visual Resources*, 2024); D. G. Stork, *Pixels & Paintings: Foundations of Computer-assisted Connoisseurship* (Wiley, 2024); J.-L. Giavitto and P. Saint-Germier (eds.), *L'art au temps de l'IA* (Centre Pompidou, 2025).
- Region benchmark: [RichArt](https://huggingface.co/datasets/MihaiBogdanBindila/RichArt) (ICMR 2026, CC BY-NC 4.0, local use only); [TIPSv2](https://huggingface.co/google/tipsv2-b14) (Google DeepMind, Apache 2.0), tested and dropped.
- Test corpora: [WikiArt via huggan/wikiart](https://huggingface.co/datasets/huggan/wikiart) and the [Yale Center for British Art](https://britishart.yale.edu/) (public domain, IIIF). No corpus images are stored in this repository.
