# Compte rendu — Le bouton « Pourquoi ? » explique-t-il vraiment ?

*Date : 22/11/2026 · Assistant : Gemini 4 Neon · Branche : `gemini/pourquoi`*

## Ce qui est fait

- **Module et commande CLI** :
  - `pixplot/analysis/whytest.py` : banc d'occultation complet, reprenable par paire (`<données>/bench/whytest_progress.jsonl`), vérifiant d'abord que le réencodage sans occultation reproduit le run DINOv3 de référence (`< 0,01`), mesurant les trois conditions `(a)` 4 premières zones du « Pourquoi ? », `(b)` 4 cases valides au hasard (10 tirages), `(c)` 4 cases centrales (5, 6, 9, 10), sur les deux images (`both`) puis une seule (`one`, A), pour les deux remplissages (`mean` couleur moyenne de l'œuvre hors bandes et `blur` flou gaussien rayon 32 px), avec bootstrap apparié sur les paires (2 000 tirages, IC 95 %, p bilatéral) et génération automatique d'une planche visuelle de 6 paires (`<données>/bench/whytest_planche.jpg`).
  - `pixplot/cli.py` : ajout localisé de `pixplot whytest` (journal dans `<données>/whytest.log`, rapport dans `<données>/bench/whytest_report.json`).
  - `tests/test_whytest.py` : 4 tests unitaires sans GPU (conservation du letterbox et de la couleur moyenne, exécution complète + reprise + planche sur corpus synthétique, arrêt net si la vérification sans occultation échoue, utilitaires et parseur CLI).
  - Le calcul existant du « Pourquoi ? » (`pixplot/analysis/correspondences.py`) n'a **pas** été modifié.
- **Documentation** : section **§ 39** ajoutée dans `ARCHITECTURE.fr.md` et `ARCHITECTURE.md`.
- **Fichiers générés hors git** (dans `C:\Users\Riyadh\Documents\Pixplot V2\data\wikiart81k\`) :
  - `bench/whytest_report.json`, `bench/whytest_progress.jsonl`, `bench/whytest_planche.jpg`, `whytest.log`.

## Chiffres clés (WikiArt 81k, run `features/dinov3_vitb16_20261116-102419`)

- **Paires** : 104 paires validées de `bench/wikiart81k_pairs.csv` (**104/104** avec ≥ 4 correspondances mutuelles) + 104 paires témoins « voisines proches » (1ʳᵉ voisine exacte en forme, graine 0, disjointes ; **103/104** avec ≥ 4 correspondances). Total : 207 paires, 401 œuvres uniques.
- **Vérification sans occultation** (22,2 s) : écart max de cosinus **0,00033** (moyenne 0,00006), auto-cosinus minimal **0,999999** → **OK** (très sous le seuil 0,01).
- **Temps de calcul** : **205,4 s (3 min 25 s)** sur RX 7900 GRE pour **10 311 images encodées** (`mean` : 75,2 s ; `blur` : 86,4 s). Reprise vérifiée sur disque (0 image d'occultation réencodée, 49 s au total dont 24 s de vérification).
- **Verdict : ÉCHEC dans toutes les conditions** (critère fixé d'avance : chute médiane `(a)/(b) ≥ 3` et IC 95 % de `(a − b)` excluant zéro).

| Groupe et mode (`mean`) | n | cos₀ méd. | (a) Pourquoi [IC 95 %] | (b) Hasard | (c) Centre | Ratio a/b | (a − b) méd. [IC 95 %] · p | (a − c) méd. · p |
|---|---|---|---|---|---|---|---|---|
| Validées · 2 images | 104 | 0,356 | −0,0006 [−0,0038 ; +0,0048] | −0,0089 | −0,0448 | — | +0,0148 [+0,0053 ; +0,0188] · 0,015 | +0,0474 · <0,001 |
| Validées · 1 image (A) | 104 | 0,356 | +0,0019 [−0,0011 ; +0,0044] | +0,0034 | +0,0124 | 0,55 | −0,0003 [−0,0059 ; +0,0032] · 0,602 | −0,0113 · 0,128 |
| Voisines · 2 images | 103 | 0,724 | +0,0099 [+0,0059 ; +0,0123] | +0,0274 | +0,0214 | **0,36** | −0,0119 [−0,0174 ; −0,0055] · 0,008 | −0,0034 · 0,274 |
| Voisines · 1 image (A) | 103 | 0,724 | +0,0059 [+0,0027 ; +0,0133] | +0,0181 | **+0,0945** | **0,33** | −0,0090 [−0,0134 ; −0,0031] · 0,002 | **−0,0785 · <0,001** |

- **Contrôle `blur` (flou gaussien rayon 32 px)** : conclusions identiques — voisines `both` : (a) +0,0075 vs (b) +0,0259 vs (c) +0,0322 (ratio **0,29**, p = 0,006) ; voisines `one` : (a) +0,0077 vs (b) +0,0191 vs (c) **+0,0857** (ratio **0,40**, p = 0,010 ; `a − c` −0,0758, p < 0,001).
- **Par type (≥ 10 paires, `mean`, `both` / `one`)** :
  - `meme_composition` (14, cos₀ 0,544) : `both` +0,0076 / +0,0169 / +0,0208 ; `one` +0,0109 / +0,0179 / **+0,0769**.
  - `meme_sujet` (36, cos₀ 0,421) : `both` +0,0088 / +0,0137 / +0,0070 ; `one` +0,0035 / +0,0144 / **+0,0624** (`a − b` −0,0086, p = 0,017).
  - `meme_facture` (16, cos₀ 0,284) : `both` +0,0031 / −0,0269 / −0,1041 ; `one` −0,0007 / −0,0009 / −0,0214.
  - `meme_palette` (26, cos₀ 0,097) : `both` −0,0090 / −0,0275 / −0,1131 ; `one` −0,0028 / −0,0099 / −0,0119.
- **Cause trouvée (diagnostic spatial)** :
  - **63,0 %** des cases retenues sur les validées (et **57,5 %** sur les voisines) tombent dans les **4 coins** (`{0, 3, 12, 15}`, hasard 25 %), **95,8 % / 93,6 %** sur les bords, et seulement **4,2 % / 6,4 %** au centre ; **92,8–93,0 %** apparient une case à la même case exacte (`cell_a == cell_b`). Le score `lift` récompense la signature positionnelle de coin de DINOv3 plutôt que le sujet central.
  - Même en normalisant les chutes par la surface occultée (ramenée à 25 % de l'œuvre : 22 % pour (a), 26 % pour (b), 34 % pour (c)), l'ordre reste inchangé (`voisines one` : +0,0080 vs +0,0177 vs +0,0669).
  - Sur la planche de 6 paires (`bench/whytest_planche.jpg`), le cas le plus parlant est Van Gogh / Millet (*Le Semeur*, cos 0,711) : les 4 cadres n'encadrent que les coins de ciel et de terre sombre, laissant toute la silhouette du semeur dehors (occulter ces 4 coins fait remonter le cosinus de +0,022).

## Ce qui reste / Ce que l'utilisateur doit décider

1. **Interface à court terme** : faut-il ajouter une mise en garde explicite sur le bouton « Pourquoi ? » de l'Atlas (indiquant le biais de coins), ou le masquer par défaut tant que le classement n'est pas réparé ?
2. **Correction du classement (à choisir puis re-mesurer avec `pixplot whytest`)** :
   - **Option 1 (rapide, sans GPU ni réextraction)** : soustraire dans `correspondences.py` la moyenne par case du corpus $\mu_c$ (`c ∈ 0..15`) avant le cosinus entre cases, et/ou pondérer les paires de cases par leur alignement avec le vecteur global (`global.npy`).
   - **Option 2 (fidèle par construction, GPU à la demande)** : remplacer les correspondances de grille par une carte d'occultation case par case dans le comparateur (~0,15 s par paire sur RX 7900 GRE).
3. **Intégration** : fusionner la branche `gemini/pourquoi` dans `main`, puis mettre à jour `docs/HANDOFF.md` et le CHANGELOG.
