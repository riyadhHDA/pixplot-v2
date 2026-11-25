# Compte rendu — Évaluation de Depth Pro 2 (Apple) et OpenVisionBanana

- **Tâche** : `modeles-essai` · **Branche** : `gemini/modeles-essai` · **Date** : 24/11/2026
- **Corpus** : WikiArt 81k (80 716 œuvres, `analysis/dinov3_vitb16_20261116-111508`)
- **Matériel** : Windows 11 natif, AMD RX 7900 GRE (16 Go), PyTorch 2.14.0+rocm10.1.0 (HIP 7.16), `timm` 1.0.31.
- **Décisions** :
  - **OpenVisionBanana** : écarté dès l’étude préalable (aucun téléchargement, aucun calcul GPU).
  - **Depth Pro 2 (`depth_pro2_base`)** : implémenté, extrait sur les 80 716 œuvres, évalué par `pairs bench`, `pairs ci`, `composition` et examen visuel ; **non retenu** (laissé dans `NOT_KEPT`, hors Atlas et MCP).

---

## 1. Sources lues et licences vérifiées

### Depth Pro 2 (Apple, nov. 2026)
- **Sources** : page officielle (`https://apple-aiml-research.github.io/ml-depth-pro-2/`), dépôt GitHub (`apple-aiml-research/ml-depth-pro-2` : `pyproject.toml`, `src/depth_pro_2/model.py`, `network/encoder.py`, `network/decoder.py`), prépublication (`arXiv:2611.26603`), fiche Hugging Face `apple/DepthPro2-B` (`config.json`, `model.safetensors`, 386 Mo).
- **Architecture** : transformateur multi-vues initialisé sur **DINOv3** (`vit_base_patch16_dinov3` pour `B`, 97 M de paramètres, patchs 16 × 16, RoPE 2D normalisée par le grand côté, blocs `cross_frame` `[5, 7, 9, 11]`, pyramide sur les blocs `[2, 5, 8, 11]`) + décodeur DPT (128 canaux) + tête de profondeur inverse (disparité normalisée par la focale, valeurs positives plus grandes au premier plan). Estimateur de focale séparé `apple/DepthPro2-focal` (23,5 M, 94 Mo), non requis pour un descripteur normalisé par z-score.
- **Données d’entraînement** : mélange d’images uniques, de vidéos et de séquences multi-vues (1 à 32 images) issues des pipelines d’Apple ; le code d’entraînement et le détail complet des jeux ne sont pas publiés. Aucune spécialisation pour la peinture ou l’art non perspectif.
- **Licences et accès** :
  - Code : *Apple Sample Code License* (permissive avec attribution).
  - Poids : **Apple Machine Learning Research Model License (`apple-amlr`)** — **usage de recherche non commercial uniquement** (autorise l’évaluation académique locale, interdit l’usage commercial).
  - Accès Hugging Face (`apple/DepthPro2-B`) : **public**, sans compte ni formulaire (`gated: False`).
- **Tailles** : `S` 24 M (97 Mo), `B` 97 M (386 Mo), `L` 334 M (1,3 Go), `H+` 872 M (3,5 Go).

### OpenVisionBanana (FunAILab)
- **Sources** : dépôt GitHub (`https://github.com/OpenVisionBanana/OpenVisionBanana`), fiches Hugging Face `FunAILab/Open-Vision-Banana` et `black-forest-labs/FLUX.2-klein-base-4B`.
- **Ce qu’il fait** : modèle **génératif par diffusion / flux rectifié** (construit sur FLUX.2 [klein] Base, 4B et 9B) reformulant des tâches de perception (segmentation, profondeur relative, normales) ainsi que l’édition et la génération comme de la **génération d’image conditionnée par une invite texte** (sortie = image RGB générée en plusieurs pas de débruitage, et non un vecteur d’indexation).
- **Données d’entraînement** : 2,1 à 3,8 M de paires issues de jeux publics de vision par ordinateur.
- **Licences et accès** : code **Apache 2.0** ; poids sous **FLUX Non-Commercial License** (Black Forest Labs : non commercial uniquement, règles de revue/filtrage sur les médias générés).
- **Taille, compatibilité ROCm et coût estimé** : ~13 Go en BF16 pour la variante 4B (limite sur 16 Go de VRAM avec activations, imposant souvent un déchargement CPU très lent), > 20 Go pour la 9B. À raison de 1 à 15 s par image pour plusieurs pas de débruitage d’un modèle 4B, **80 716 œuvres demanderaient entre ~22 heures et plus de 10 jours de GPU en continu** pour une seule tâche, sans produire de descripteur vectoriel.
- **Décision** : **écarté sans téléchargement ni calcul GPU**. Ce n’est pas un encodeur adapté à la cartographie ou la recherche sur un grand corpus.

---

## 2. Implémentation et extraction de Depth Pro 2 Base (`depth_pro2_base`)

- **Code ajouté** :
  - `pixplot/encoders/depth_pro2.py` (`DepthPro2Encoder`, variantes `depth_pro2_small`, `depth_pro2_base`, `depth_pro2_large`). Implémentation PyTorch autonome appuyée sur `timm` (`vit_base_patch16_dinov3`) et `safetensors`, sans dépendance vidéo (`av`, `pillow-heif`). En mode image unique par lots (`(B, 3, 512, 512)`), les blocs `cross_frame` traitent chaque image indépendamment tout en conservant les jetons préfixes inchangés, ce qui reproduit exactement le passage image unique du dépôt officiel. Précision : `bfloat16` pour l’encodeur et le décodeur, `float32` pour la tête.
  - Prétraitement et descripteur identiques à `depth.py` (§ 28) pour une comparaison à armes égales : *letterbox* à 512 px (multiple de 32, proche des 518 px de Depth Anything V2), normalisation ImageNet, recadrage sur la zone utile de l’œuvre, moyenne sur grille **8 × 8**, centrage et normalisation L2 par œuvre (z-score de norme 1, 64 dimensions).
  - Déclaré dans `pixplot/encoders/registry.py`, rangé dans `NOT_KEPT` (`profondeur_dp2`) dans `pixplot/api/spaces.py`, fiche critique dans `pixplot/analysis/critique.py`, ordre d’affichage dans `pixplot/cli.py` (`cmd_composition`).
  - Tests unitaires : `tests/test_depth_pro2.py` (enregistrement `NOT_KEPT`, `pairs bench`, `composition`, cohérence numérique PyTorch/NumPy, extraction sur le corpus synthétique).
- **Extraction sur WikiArt 81k** (avec accord de l’utilisateur) :
  - Run : `features/depth_pro2_base_20261124-190441` (journal `data/wikiart81k/depth_pro2.log`)
  - **80 716 œuvres**, **0 échec**, **30 min 59 s** (1 859,3 s), **43,4 images/s**, **5 153 MiB** de VRAM (RX 7900 GRE, `bfloat16`, lots de 32).

---

## 3. Mesures (WikiArt 81k, paires validées)

### A. « Même composition, sujet différent » (14 paires, 28 recherches — `pixplot composition` et `pairs ci`)

| Regard | R@10 [IC 95 %] | R@100 | Rang médian [IC 95 %] | Centile |
|---|---:|---:|---:|---:|
| **Forme (DINOv3), regard actuel** | **53,6 %** [35,7–67,9] | **71,4 %** | **8** [4–76] | **0,928** |
| Sujet (SigLIP 2) | 21,4 % [3,6–42,9] | 28,6 % | 814 [21–29 909] | 0,738 |
| Touche (DINOv3 couche 6) | 10,7 % [0,0–21,4] | 32,1 % | 1 017 [71–3 886] | 0,857 |
| Profondeur (Depth Anything V2 Small, § 28) | 3,6 % [0,0–10,7] | 7,1 % | 13 754 [3 045–41 312] | 0,677 |
| **Profondeur (Depth Pro 2 Base, brut)** | **0,0 %** [0,0–0,0] | **7,1 %** | **4 836** [1 462–18 130] | **0,851** |
| *Profondeur (Depth Pro 2 Base, centré en mémoire)* | *0,0 %* | *7,1 %* | *4 266* | *0,851* |

- **Intervalles de confiance appariés (`pixplot pairs ci`, 2 000 tirages bootstrap sur les paires)** :
  - `forme − profondeur_dp2` = **+53,6 %** `[+39,3 % ; +67,9 %]`, **p = 0,000** (écart sûr en faveur de Forme).
  - `sujet − profondeur_dp2` = **+21,4 %** `[+3,6 % ; +42,9 %]`, **p = 0,019** (écart sûr en faveur de Sujet).
  - `profondeur_dp2` vs `profondeur` (Depth Anything V2) : aucun écart sûr de R@10 (`0,0 %` vs `3,6 %`).

### B. Autres catégories annotées validées (`pixplot pairs bench` et `pairs ci`)

| Catégorie (n recherches) | Depth Pro 2 Base (R@10 · R@100 · méd. · cent.) | Depth Anything V2 (R@10 · méd. · cent.) | Meilleur regard actuel (R@10 · méd.) |
|---|---|---|---|
| **Filiation attestée** (20) | 0,0 % · 5,0 % · 5 298 · 0,831 *(centré : 4 916 · 0,836)* | 20,0 % · 12 436 · 0,773 | Forme (45,0 % · 20) / Sujet (45,0 % · 17) |
| Même sujet, composition diff. (74) | 0,0 % · 0,0 % · 39 150 · 0,568 | 2,7 % · 32 444 · 0,559 | Sujet (37,8 % · 30) |
| Artistes diff., facture comp. (34) | 0,0 % · 0,0 % · 40 141 · 0,526 | 0,0 % · 30 244 · 0,608 | Touche (29,4 % · 202) |
| Même palette, trad. diff. (54) | 0,0 % · 0,0 % · 32 844 · 0,565 | 0,0 % · 51 211 · 0,428 | Couleur (48,1 % · 13) |
| Même geste / posture (40) | 0,0 % · 0,0 % · 19 874 · 0,619 | 0,0 % · 26 897 · 0,678 | Posture (50,0 % · 10) / Posture multi (32,5 % · 104) |
| Même motif, époque diff. (4) | 0,0 % · 0,0 % · 16 768 · 0,787 | 0,0 % · 41 282 · 0,492 | Sujet (50,0 % · 26) |
| Même artiste, facture diff. (2) | 0,0 % · 0,0 % · 34 862 · 0,568 | 0,0 % · 30 958 · 0,616 | Couleur (100,0 % · 2) |

Sur `filiation`, Forme (`+45,0 %`, `[+20,0 % ; +70,1 %]`, p = 0,000) et Sujet (`+45,0 %`, `[+20,0 % ; +70,0 %]`, p = 0,001) battent Depth Pro 2 de façon sûre. Sur les paires de métadonnées, Depth Pro 2 reste proche du hasard (centile 0,494 à 0,576, témoin 0,472).

### C. Effet du gradient vertical et combinaison avec Forme

- **Ce que Depth Pro 2 corrige réellement par rapport à Depth Anything V2 (§ 28)** : le biais de gradient vertical moyen (haut → bas sur les 8 lignes) disparaît presque complètement (`[-0,027 … +0,027]` contre `[-0,099 … +0,178]` chez Depth Anything V2). Le cosinus moyen entre deux œuvres prises au hasard chute de **0,536** (DA2) à **0,051** (DP2 brut, et **0,008** centré). C’est ce qui divise par presque trois le rang médian sur « même composition » (`13 754 → 4 836`) et sur « filiation » (`12 436 → 5 298`), et fait monter le centile de `0,677` à `0,851`.
- **Mais le haut du classement ne décolle pas** : R@10 reste à **0,0 %** partout (aucune paire retrouvée dans les 10 premières, ni sur « même composition », ni sur « filiation »).
- **Combinaison linéaire `Forme + α · DP2` sur « même composition » (14 paires)** :
  - `α = 0,00` (Forme seule) : R@10 **53,6 %**, R@100 71,4 %, rang médian 8, centile 0,9275.
  - `α = 0,05` (DP2 brut / centré) : R@10 53,6 %, R@100 75,0 % / 78,6 %, rang médian 6, centile 0,9373 / 0,9375.
  - `α = 0,10` : R@10 recule à 50,0 %, rang médian 12 ; `α = 0,20` : R@10 chute à 46,4 % / 42,9 %.
  - Le léger gain de R@100 à `α = 0,05` porte sur 1 à 2 paires seulement (sur 14) et n’est pas statistiquement significatif ; dès `α ≥ 0,10`, la profondeur dégrade le haut du classement, comme au § 28.

---

## 4. Examen à l’œil (planche de 6 paires)

Six paires ont été inspectées visuellement avec leurs cartes de profondeur inverse Depth Pro 2 (3 meilleures / gains nets et 3 échecs) :

1. **Réussite nette — Pérugin, *La Remise des clés* (`#30987`) ↔ *Le Mariage de la Vierge* (`#30969`)** (`meme_composition`, Forme `(2, 2)`, DA2 `(1 285, 85)`, **DP2 `(18, 14)`**) : les silhouettes des figures au premier plan sont découpées avec une grande netteté devant le ciel et le temple en bleu profond. L’absence de biais vertical permet de rapprocher la fresque large et le retable haut dans les 20 premières œuvres.
2. **Gain trompeur sur art graphique plat — Ed Ruscha (*Actual Size*, `#65822`) ↔ Peter Max (`#71779`)** (`meme_composition`, Forme `(9, 5)`, DA2 `(68 987, 80 552)`, DP2 `(424, 432)`) : sur deux affiches Pop Art sans espace 3D, Depth Pro 2 place artificiellement le haut (lettrage « SPAM » / arc coloré) au premier plan, ce qui les rapproche par coïncidence mais ne reflète aucune profondeur réelle.
3. **Recul sur une copie fidèle — Rubens (`#64269`) ↔ Titien (*L’Enlèvement d’Europe*, `#67405`)** (`filiation`, Forme `(1, 1)`, DA2 `(1, 1)`, **DP2 `(1 061, 34)`**) : les cartes sont visuellement remarquables (diagonale d’Europe et du taureau très nette), mais la finesse même des contours fait ressortir les deux *putti* en haut à gauche chez Rubens et non chez Titien, ce qui pénalise la corrélation sur grille 8 × 8. Même recul sur Van Gogh / Millet (*Le Semeur* : DA2 `(3, 1)` → DP2 `(1 341, 2 540)`).
4. **Échec sur la lecture 3D d’une forme identique — Michel-Ange (`#24374`) ↔ Mantegna (`#54823`)** (`meme_composition`, Forme `(39, 2)`, DA2 `(7, 6 183)`, **DP2 `(23 583, 39 954)`**) : deux lunettes ; Depth Pro 2 lit celle de Michel-Ange comme une niche creusée avec figures latérales, mais celle de Mantegna comme un demi-disque doré uniformément plat au premier plan.
5. **Échec complet sur le cubisme — Picasso, *Le Peintre et son modèle* (`#27729` ↔ `#28025`)** (`meme_composition`, Forme `(4, 39)`, DA2 `(5 555, 23 429)`, **DP2 `(54 434, 48 061)`**) : profondeur inventée de manière incohérente entre les deux toiles cubistes planes.
6. **Échec attendu sur une filiation transformée — Picasso (*Les Demoiselles d’Avignon*, `#27813`) ↔ El Greco (*La Vision de saint Jean*, `#8685`)** (`filiation`, Forme `(418, 2 144)`, DA2 `(52 346, 27 418)`, **DP2 `(60 410, 55 537)`**) : saint Jean est bien détaché chez El Greco, mais l’espace fracturé des *Demoiselles* ne produit aucun plan cohérent.

---

## 5. Limites

- Échantillons de paires validées encore modestes (`meme_composition` : 14 paires, `filiation` : 10 paires) et en partie issus des désaccords où Forme était déjà en tête.
- Seule la variante `DepthPro2-B` (97 M) et la grille 8 × 8 z-score ont été mesurées (pas `L` ni `H+`, ni un autre descripteur de carte de profondeur).
- Le corpus WikiArt mêle art perspectif, gravures, aplats et art moderne : un estimateur de profondeur reste par nature inadapté aux œuvres non perspectives.
- Rappel de méthode : une proximité calculée est une piste pour regarder, jamais une preuve historique.

---

## 6. Recommandation et décisions pour l’utilisateur

- **Recommandation** : **ne retenir ni OpenVisionBanana ni Depth Pro 2** comme regard dans l’Atlas ou le serveur MCP.
  - Depth Pro 2 Base corrige nettement le biais de gradient vertical de Depth Anything V2 (centile `0,677 → 0,851`, rang médian `13 754 → 4 836`), mais reste à **0,0 % de R@10** sur « même composition » et « filiation », largement battu par **Forme (DINOv3)** (`53,6 %`, écart sûr `+53,6 pts`, p < 0,001), et ses poids sont sous licence non commerciale (`apple-amlr`).
  - L’encodeur `depth_pro2_base` reste dans `pixplot/encoders/depth_pro2.py` et dans `NOT_KEPT` (et ses vecteurs dans `data/wikiart81k/runs/features/depth_pro2_base_20261124-190441`, 10 Mo) pour la reproductibilité des bancs d’essai, exactement comme SSCD, Depth Anything V2, PE-Core et CSD.
- **Ce que l’utilisateur doit décider** :
  1. Confirmer la fusion de `gemini/modeles-essai` dans `main` (code de l’encodeur en `NOT_KEPT` + tests) et l’ajout d’une section datée dans `ARCHITECTURE.fr.md` / `ARCHITECTURE.md` par l’intégrateur.
  2. Décider s’il souhaite conserver les 10 Mo de vecteurs `features/depth_pro2_base_20261124-190441` et le cache Hugging Face (386 Mo) pour d’éventuels essais ultérieurs (par ex. sur un corpus strictement figuratif/perspectif), ou les supprimer.
