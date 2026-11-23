# Roadmap

**English** · [Français](ROADMAP.fr.md) · Updated: 2026-11-23 · Current version: **0.21.0**

Completed work is listed in [CHANGELOG.md](CHANGELOG.md). This file tracks upcoming steps,
dropped experiments and leads worth testing.

## Principle: benchmark before keeping

We avoid piling up models without evidence. A new method only stays if it beats the baseline
on a benchmark (annotated pairs, labels, RichArt…) while adding a signal the existing spaces
miss. Failed attempts are documented with their numbers and dropped. Since 22/11/2026, "beats"
means that the 95 % confidence interval of the paired difference excludes zero (`pixplot pairs ci`,
ARCHITECTURE § 38).

## Next steps

### 0.11 — Leiden groups, nested, per way of seeing · *done*

> **Result** (ARCHITECTURE § 15): criterion met for form, subject and touch (more stable, as good
> or better on labels), not for colour. Names, the groups panel and labels-to-check still have to
> be ported to Leiden before it becomes the Atlas's main grouping.

- **Why**: the number of groups comes from an arbitrary rule (k = √N / 2, i.e. 142 groups
  for 80,716 works) and HDBSCAN fails on a continuum without gaps.
- **What**: Leiden communities on the neighbour graph already computed; granularity
  becomes a setting; nested groups (groups, then sub-groups when zooming in the Atlas);
  groups for every way of seeing, not only form.
- **Success if**: stable from one run to the next (adjusted Rand index), and at least as
  good as e-means on labels and pairs. Otherwise e-means stays.

### 0.12 — Disagreements between ways of seeing, and pair review · *tools done*

> The "Disagreements" panel, the "Reference pairs" tab and the Anki-style quick review (key R,
> 0.12.1) are in the Atlas (ARCHITECTURE § 16 and 17). **104 validated pairs** (§ 18): criterion
> met in number; "same hand" (1) and "same motif" (2) still need more.
> The criterion remains: the art historian's review of the pairs.

- **Why**: the most telling result for an art historian is often that one way of seeing
  brings two works together while another pulls them apart. And the benchmark needs
  validated pairs.
- **What**: in the Atlas, a "Disagreements" panel (close in form but far in subject,
  etc.) and a "Pairs to review" panel to validate or reject proposed pairs.
- **Success if**: the 11 proposed pairs are reviewed, and about 100 validated pairs cover
  the eight types, including "same composition" and "same palette".
  *This part is the art historian's work.*

### 0.13 — Searching a region with words (TIPSv2) · *measured, TIPSv2 not adopted*

> **Result** (ARCHITECTURE § 19, `pixplot zonebench`): on RichArt, SigLIP 2 on cropped regions beats
> TIPSv2 (sentence: 28% vs 20% at rank 1); TIPSv2's pointing barely beats "always the centre" (51%).
> **SigLIP 2 region index done in 0.13.3**: 1.6 million regions, "Zone décrite" search in the Atlas (ARCHITECTURE § 22).

- **Why**: today we compare a region with a region (DINOv3) or a sentence with a whole
  image (SigLIP 2). Nothing compares a sentence with a region: "halo", "blessing hand",
  "skull".
- **What**: a [TIPSv2](https://gdm-tipsv2.github.io/) pilot (Google DeepMind, B/14) on
  1,000 works, evaluated on [RichArt](https://huggingface.co/datasets/MihaiBogdanBindila/RichArt)
  (20,882 described regions, local use only), then a full region index if it convinces.
- **Success if**: it finds RichArt regions clearly better than SigLIP 2 applied to cropped
  regions. Licence checked before any download.

### 0.14 — Naming groups with Iconclass

- **Why**: the current lexicon (101 hand-written terms, extended from Honour and Fleming)
  is small. [Iconclass](https://github.com/iconclass/data) is the museums' reference
  iconographic classification, with French labels, under CC0.
- **What**: group names proposed from Iconclass concepts, with their notation (e.g.
  "73A5 Annunciation") as a verifiable source; then a benchmark of 100 to 200 French
  queries.
- **Success if**: the names are judged more accurate than the current ones, on a reviewed
  sample.

> **Done on 2026-11-19: criterion met.** Over 83 reviewed groups, Iconclass is judged more accurate 39
> times, the current name 24 times (17 equivalent, 3 both wrong): ARCHITECTURE § 23.

### 0.15 — Composition: STELLAR and PE-Spatial

- **Why**: the benchmark shows that no way of seeing follows a filiation once the artist
  transforms the model (Picasso after El Greco or Delacroix).
- **What**: [STELLAR](https://huggingface.co/microsoft/STELLAR) (what is depicted *and*
  where) as a "composition" way of seeing; [PE-Spatial](https://huggingface.co/facebook/PE-Spatial-B16-512)
  as a candidate for detail search.
- **Success if**: it wins on the "same composition" and "filiation" pairs validated in
  step 0.12. Otherwise it is documented and dropped.

> **Done on 2026-11-18: not adopted.** PE-Spatial and the 4×4 layout stay far behind DINOv3 on
> "same composition" pairs (median rank 286 at best, vs 8): ARCHITECTURE § 24.

## Later, or to watch

- **Entropy and complexity** (Sigaki, Perc and Ribeiro, PNAS 2018) *(done in 0.20.0: `pixplot ordre`, map colour and artwork record)*: an "order and complexity" way
  of seeing computed without a GPU, and a possible axis for the timeline.
- **ArtEmis** (CVPR 2021) *(done in 0.20.0, ARCHITECTURE § 34: the regards capture a little emotion, mostly through subject)*: 455,000 emotion annotations on WikiArt works; do the ways of seeing
  capture the felt effect or only the subject?
- **"Why do these two works look alike?"** *(done in 0.16.0, ARCHITECTURE § 25)*: show, in the
  comparator, which regions of one answer which regions of the other (an answer to the perceptual
  bias described by Wasielewski).
- **2D conceptual axes (Impett & Offert, 2024) and visual measures (Stork, 2024)** *(done,
  ARCHITECTURE § 26)*: 2D projection on two SigLIP 2 concepts, neural-free visual balance and
  chromatic entropy.
- **Leads from recent readings** (to benchmark locally on this PC):
  - **LocalMAP** (AAAI 2025, `pacmap`, 100 % CPU) *(evaluated in 0.19.0, ARCHITECTURE § 29)*: barely better than
    UMAP on neighbours' labels (+1.5 points), but the map splits into islands and is more crowded. Not
    kept for the main map; offered as a trial map (`pixplot maps --localmap`).
  - **SSCD** (CVPR 2022) for copies *(evaluated in 0.19.0, § 27: not kept as a regard, but used to
    find duplicates)* and **Depth Anything V2** (NeurIPS 2024) for composition through depth
    *(evaluated in 0.19.0, § 28: not kept)*.
  - **CSD** (ECCV 2024) for pure style vs "touch", and **PE-Core** vs SigLIP 2 for "subject"
    *(evaluated, not kept: ARCHITECTURE §§ 31–32)*.
  - **Poses and gaze** (Stork § 8.3 & § 9.3.1; *Human-Art* CVPR 2023; Madhu et al.) *(evaluated in
    0.21.0, § 35: "posture" regard, not yet offered; 37 "same gesture" pairs to review)*: skeleton
    detection for *Pathosformeln* and figure symmetry.
  - **Sparse autoencoders** (*PatchSAE* ICLR 2025, *Matryoshka SAE* ICML 2025) *(done in 0.21.0, § 37:
    1,792 notions of the "subject" regard, "Notions" panel in the Atlas)* on already-computed
    vectors, and enriched Iconclass hierarchy (*Visual Narratives*, WACV 2024).
- **Collection Space Navigator** (Ohm et al., 2023) *(done in 0.19.0)*: combined filters in
  the Atlas (labels, groups, atypicality, dates) with cross counts, selection sent to the notebook or a
  Research Pack (`web/atlas-filtres.js`, key F).

- **SAM 3**: precise segmentation of a motif, on demand on a selection. Meta licence to be
  accepted by the user; ROCm compatibility to check.
- **MMArt** *(done in 0.20.0, § 34: titles, dates and artists for 70,902 works)*: would bring titles and dates to our WikiArt (matching images by perceptual
  hash). Its descriptions are generated by a language model: a benchmark for text search,
  never a source of names.
- **Non-European corpora** via IIIF (Asia, Islam, Africa), and corpora with places for the
  geographic view.
- **PE-Core**: only as a challenger to SigLIP 2 for the "subject" way of seeing.

## Ruled out

- **Merging the rankings of the ways of seeing**: against the principle of separate ways
  of seeing.
- **V-JEPA 2.1, AIMv2**: built for video, or no expected gain on still works.
- **HDBSCAN** at scale: documented as unsuitable (ARCHITECTURE § 11).

## Towards 1.0

1.0 will come when: commands and file formats are stable (described in
[docs/COMMANDS.md](docs/COMMANDS.md) and [docs/FORMATS.md](docs/FORMATS.md), checked by tests); the benchmark has at least 100
validated pairs; installation has been tested on a fresh machine; and the documentation is
complete in both languages.
