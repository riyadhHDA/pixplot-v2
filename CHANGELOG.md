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
