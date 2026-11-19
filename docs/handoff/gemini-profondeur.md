# Compte rendu — évaluation de Depth Anything V2 (`gemini/profondeur`)

*Date : 19/11/2026 · Assistant : Gemini 4 Neon (Antigravity) · Branche : `gemini/profondeur`*

## 1. Ce qui a été fait

1. **Vérification de la licence** : fiche Hugging Face de
   `depth-anything/Depth-Anything-V2-Small-hf` vérifiée avant téléchargement — **licence Apache
   2.0** (`license: apache-2.0`). Les variantes Base et Large (CC BY-NC 4.0) ont été écartées. Poids
   stockés uniquement dans le cache Hugging Face local, jamais dans git.
2. **Choix techniques retenus** :
   - **Résolution native 518 px** (37 × 14, multiple de 14 requis par le backbone DINOv2 ViT-S/14),
     avec le *letterbox* standard de PixPlot (normalisation ImageNet, sans recadrer ni déformer
     l'œuvre).
   - **Recadrage sur la seule zone de l'œuvre** : `extract.py` transmet les boîtes *letterbox*
     `(left, top, w, h)` aux encodeurs qui déclarent `needs_boxes = True` (ajout localisé de 4
     lignes, rétrocompatible). La carte de profondeur prédite est recadrée sur l'œuvre seule avant
     moyennage sur une **grille 8 × 8** (64 dimensions, `adaptive_avg_pool2d`), ignorant totalement
     les bandes du *letterbox* et alignant la grille sur l'œuvre (réponse à la limite relevée au
     § 24).
   - **Normalisation par z-score de longueur 1 par œuvre** (centrage en `float64` avec garde contre
     les cartes planes, puis normalisation L2) : option la plus simple, strictement invariante à
     toute transformation affine $a \cdot d + b$ ($a > 0$, cohérente avec la disparité relative du
     modèle), dont le cosinus vaut exactement la corrélation de Pearson entre deux grilles 8 × 8.
     Les variantes centrée sur le corpus et par rangs (Spearman) ont également été mesurées en
     mémoire.
3. **Code ajouté / adapté** :
   - `pixplot/encoders/depth.py` : `DepthAnythingEncoder` (`depth_anything_v2_small`) + fonction
     pure NumPy `depth_grid_descriptor` (testable sans PyTorch).
   - `pixplot/features/extract.py` : transmission de `boxes` à `encoder.encode(batch, boxes=boxes)`
     lorsque `getattr(encoder, "needs_boxes", False)` est vrai.
   - `pixplot/encoders/registry.py` : enregistrement de `depth_anything_v2_small` (repli sur 518 px
     quand `--input-size` vaut la valeur par défaut CLI 448).
   - `pixplot/api/spaces.py` : regard `"profondeur"` (`Profondeur (Depth Anything V2)`) ajouté dans
     `KINDS`, `ORDER` et placé dans `NOT_KEPT` (évalué, caché par défaut dans l'Atlas et le serveur
     MCP).
   - `pixplot/analysis/critique.py` : fiche critique `"profondeur"` ajoutée dans `CARDS` avec les
     mesures WikiArt 81k.
   - `pixplot/cli.py` : passage des arguments `embed` pour `depth_anything_*` ; restauration propre
     de `Spaces.include_not_kept` dans un `finally` et ajout de `"profondeur"` dans l'ordre
     d'affichage de `pixplot composition`.
   - `tests/test_depth.py` : 3 tests sur le petit corpus synthétique (dont 2 sans PyTorch :
     invariances / letterbox / cartes planes, et intégration `NOT_KEPT` + `pairs bench` +
     `composition`, plus 1 test PyTorch local sans réseau).
   - `ARCHITECTURE.fr.md` et `ARCHITECTURE.md` : nouvelle section **§ 28**.
4. **Extraction sur WikiArt 81k** (`features/depth_anything_v2_small_20261119-191351`, journalisée
   dans `data/wikiart81k/depth.log`) :
   - **80 716 œuvres**, **0 échec** (0 carte plate dégénérée), **14 min 3 s**, **95,7 images/s**,
     **3 082 MiB** VRAM (RX 7900 GRE, FP16, lots de 32, 6 threads de lecture ; 10 Mo sur disque).

## 2. Mesures (WikiArt 81k, 80 716 œuvres, 104 paires annotées validées)

Rapports complets : `data/wikiart81k/bench/composition_report_dinov3_vitb16_20261116-111508.json`
et `data/wikiart81k/bench/pairs_report_dinov3_vitb16_20261116-111508.json`.

### Catégorie cible : « Même composition, sujet différent » (14 paires, 28 recherches)

| Regard | R@10 | R@100 | Rang médian | Centile |
|---|---:|---:|---:|---:|
| **Forme (DINOv3), regard actuel** | **53,6 %** | **71,4 %** | **8** | **0,928** |
| Forme, 4 × 4 cases communes (§ 24) | 0,0 % | 32,1 % | 332 | 0,958 |
| PE-Spatial, 4 × 4 cases communes (§ 24) | 7,1 % | 28,6 % | 286 | 0,878 |
| Sujet (SigLIP 2) | 21,4 % | 28,6 % | 814 | 0,738 |
| Touche (DINOv3, couche 6) | 10,7 % | 32,1 % | 1 017 | 0,857 |
| **Profondeur (Depth Anything V2 Small, 8 × 8 brut)** | **3,6 %** | **7,1 %** | **13 754** | **0,677** |
| *Profondeur centrée sur le corpus (en mémoire)* | *3,6 %* | *7,1 %* | *6 874* | *0,682* |
| *Profondeur par rangs / Spearman (en mémoire)* | *3,6 %* | *3,6 %* | *13 424* | *0,640* |

### Combinaison Forme + profondeur (validation croisée sans triche, 14 paires)

Somme pondérée $S = (1 - \alpha)\, S_{\text{forme}} + \alpha\, S_{\text{profondeur}}$, $\alpha$
choisi sur une moitié des paires et évalué sur l'autre moitié :

| Variante | R@10 | R@100 | Rang médian | Centile |
|---|---:|---:|---:|---:|
| **Forme seule ($\alpha = 0$)** | **53,6 %** | **71,4 %** | **8** | **0,9275** |
| CV 2 moitiés alternées (cosinus brut, $\alpha = 0{,}05 / 0{,}10$) | 42,9 % | 75,0 % | 26 | 0,9314 |
| CV 2 moitiés consécutives (cosinus brut, $\alpha = 0{,}10 / 0{,}10$) | 42,9 % | 71,4 % | 26 | 0,9334 |
| CV 2 moitiés alternées (z-score sim, prof. centrée, $\alpha = 0{,}05 / 0{,}40$) | 50,0 % | 64,3 % | 15 | 0,9283 |
| CV 200 tirages 7/7 (cosinus brut, opt. centile, $\alpha$ méd. 0,10) | 42,1 % | — | 691 (moy.) | 0,9037 |
| CV 200 tirages 7/7 (opt. R@10 / médiane) | — | — | — | $\alpha = 0$ dans **74 %** des tirages |

### Autres catégories annotées validées et paires de métadonnées

| Catégorie (n recherches) | Profondeur R@10 | Profondeur rang méd. (centré) | Meilleur regard actuel (R@10 · rang méd.) |
|---|---:|---:|---|
| Filiation attestée (18) | 11,1 % | 14 889 (11 784) | Sujet (38,9 % · 25) / Forme (38,9 % · 26) |
| Même sujet, composition différente (72) | 2,8 % | 32 444 (32 471) | Sujet (37,5 % · 30) |
| Artistes différents, facture comparable (32) | 0,0 % | 28 682 (28 509) | Touche (31,2 % · 136) |
| Même palette, traditions différentes (52) | 0,0 % | 51 211 (43 698) | Couleur (50,0 % · 10) |
| Même motif, époque différente (4) | 0,0 % | 41 282 (—) | Sujet (50,0 % · 26) |
| Même artiste, facture différente (2) | 0,0 % | 30 958 (—) | Couleur (100,0 % · 2) |
| Métadonnées : sujet / main / facture / témoin | 0,0 % | 34 098 – 42 868 | Centiles 0,544 / 0,548 / 0,552 / 0,479 |

### Lecture qualitative (pourquoi ça échoue)

- **Gradient vertical universel** : sur les 80 716 œuvres, la grille moyenne 8 × 8 croît strictement
  du haut (−0,108) vers le bas (+0,181), d'où un cosinus moyen de **0,539** entre deux œuvres prises
  au hasard (0,016 après centrage).
- **Vérification positive** : le descripteur fonctionne bien sur les scènes figuratives à plans nets
  — Van Gogh / Millet (*Le Semeur* : rangs **3 et 1**, cosinus 0,948), paire proposée Rubens /
  Titien (*L'Enlèvement d'Europe* : rangs **1 et 1**, cosinus 0,987), Pérugin (*Remise des clés* ↔
  *Mariage de la Vierge* : rangs 1 285 et **85**), Michel-Ange / Haute Renaissance (`24374 ↔ 54823`
  : rang **7** dans un sens).
- **Effondrement sur l'art non perspectif et les écarts de format** : Pop Art (`65822 ↔ 71779` :
  68 987 et 80 552), Chagall / Expressionnisme (`22435 ↔ 60995` : 79 814 et 79 803), Expressionnisme
  / Pop Art (`48392 ↔ 76646` : 75 807 et 64 679), et même Raphaël / Pérugin (`32148 ↔ 30987` :
  2 256 et 25 374 contre 3 et 7 pour Forme, à cause du décalage vertical d'horizon entre un retable
  haut et une fresque large).

## 3. Tests

- Suite complète exécutée : **76 passed** (les 73 tests existants + 3 nouveaux tests dans
  `tests/test_depth.py`, dont 2 sans PyTorch).

## 4. Reste à faire (pour l'intégrateur)

- Relire et fusionner `gemini/profondeur` dans `main` (via
  `.\scripts\nouvelle-tache.ps1 profondeur -Agent gemini -Terminer`).
- Mettre à jour `docs/HANDOFF.md` (et, si publication, numéro de version et CHANGELOG — hors
  périmètre de cette branche).

## 5. Décision pour l'utilisateur

**Recommandation : ne pas retenir Depth Anything V2, ni comme regard à part entière ni combiné à Forme.**

- Seul, le descripteur de profondeur 8 × 8 est très loin derrière Forme (DINOv3) sur « même
  composition, sujet différent » (R@10 3,6 % contre 53,6 %, rang médian 13 754 — ou 6 874 centré —
  contre 8).
- Combiné à Forme, il dégrade le haut du classement (R@10 et rang médian) et n'améliore pas le
  centile moyen en validation croisée hors échantillon (0,9037 contre 0,9275 sur 200 tirages 7/7).
- Deux options :
  1. **(Recommandée) Garder l'état actuel** : `"depth_anything"` reste dans `NOT_KEPT` (hors Atlas
     et MCP), code et vecteurs (10 Mo) conservés pour de futurs bancs d'essai ou un corpus
     spécifiquement figuratif / perspectif (paysages, peinture d'histoire).
  2. **Exposer quand même le regard « profondeur » dans l'Atlas** : retirer `"depth_anything"` de
     `NOT_KEPT` dans `pixplot/api/spaces.py`, puis indexer (`pixplot index --encoder
     depth_anything_v2_small`).
