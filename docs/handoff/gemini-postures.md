# Compte rendu — regard « posture » / Pathosformeln (`gemini/postures`)

*Date : 21/11/2026 · Assistant : Gemini 4 Neon (Antigravity) · Branche : `gemini/postures`*

## 1. Ce qui a été fait

1. **Vérification des licences (code ET poids) avant téléchargement** :
   - Écartés : YOLO-pose d'Ultralytics (AGPL) et poids affinés sur *Human-Art* (jeu sous licence non
     commerciale CC BY-NC).
   - Retenus (**100 % Apache 2.0**, code et poids sur Hugging Face, directement pris en charge par
     `transformers` sans nouvelle dépendance) :
     - détecteur de personnes : **RT-DETRv2-R50** (`PekingU/rtdetr_v2_r50vd`, 172 Mo, COCO) ;
     - estimateur de squelettes 17 points : **ViTPose Base Simple** (`usyd-community/vitpose-base-simple`,
       344 Mo, COCO).
   - Poids stockés uniquement dans le cache Hugging Face local, jamais dans git.
2. **Pilote visuel sur 100 œuvres variées** (peinture d'histoire/religieuse, portraits/nus, gravures/dessins/Ukiyo-e,
   art moderne figuratif et 15 témoins sans figure : paysages, natures mortes, abstraction), inspecté
   visuellement planche par planche :
   - **R50 vs R18** : `rtdetr_v2_r50vd` devance nettement `rtdetr_v2_r18vd` sur les gravures/dessins/Ukiyo-e
     (**13/20 = 65 %** contre 4/20 = 20 %) et la peinture d'histoire/religieuse (**19/20 = 95 %** contre
     15/20 = 75 %). R50 à 640 px a donc été retenu.
   - Qualité des squelettes concluante sur la peinture figurative occidentale, les gravures (Doré, Dürer,
     Rembrandt), les dessins au trait et l'Ukiyo-e (*Olympia* ↔ *Vénus d'Urbin* : rang 1/100, cos 0,951 ;
     *Le Semeur* Van Gogh ↔ Millet : rang 1/100, cos 0,981). Zéro faux positif sur l'abstraction et les
     natures mortes ; échec attendu sur le cubisme (*Les Demoiselles d'Avignon*) et les figures modernes
     très déformées.
3. **Choix techniques retenus (`pixplot/encoders/posture.py`)** :
   - **Filtrage** : détection personne $\ge 0{,}40$, NMS (IoU 0,65), taille minimale ($\ge 8\,\%$ du grand
     côté et $\ge 0{,}6\,\%$ de l'aire de l'œuvre pour écarter le staffage minuscule), au moins **4 points
     corporels** (épaules à chevilles, confiance $\ge 0{,}30$, moyenne $\ge 0{,}40$) pour ignorer les
     visages serrés sans posture corporelle. Jusqu'à **8 figures** conservées par œuvre.
   - **Descripteur 50-D normalisé L2 par figure** : 13 articulations normalisées (26 dim. : 1 centre de tête
     moyennant les 5 points du visage + 12 articulations du corps, centrées sur le torse et ramenées au
     rayon quadratique moyen) + 12 vecteurs unitaires de membres (24 dim. : cou, épaules, colonne, bassin,
     bras, avant-bras, cuisses, jambes), robustes aux proportions peintes (maniérisme, Botero) et aux
     cadrages à mi-corps.
   - **Miroir gauche-droite exact + multi-figures** : `mirror_pose_vector` applique une involution
     orthogonale exacte $F$ ($x \mapsto -x$ et échange gauche/droite, vérifiée à $< 10^{-6}$).
     `PostureIndex` calcule la similarité exacte multi-figures + miroir
     $\max_{i \in A,\, j \in B} \max(v_i \cdot v_j, v_i \cdot F(v_j))$ sur toutes les figures stockées dans
     `poses_*.npy`. `global.npy` stocke la figure principale canonisée en orientation (pour compatibilité
     `FeatureStore` / `Spaces` / `pairs bench`).
   - **Exclusion propre des œuvres sans figure dans `Spaces._open`** : les œuvres sans figure (`poses_count
     == 0`) ne sont pas indexées dans `Spaces._rows["posture"]`, ce qui évite les faux rangs 1 par ex
     aequo sur vecteurs nuls (vérifié : `Témoin` = centile 0,498, exactement le hasard).
   - **Contournement ROCm Windows** : `torch.backends.cudnn.enabled = False` sur HIP évite un blocage du
     solveur MIOpen sur RT-DETRv2 sous ROCm Windows tout en atteignant 25,0 img/s via rocBLAS.
4. **Extraction sur WikiArt 81k** (`features/vitpose_base_20261121-182701`, journal
   `data/wikiart81k/posture.log`) :
   - **80 716 œuvres**, **0 échec**, **53 min 55 s**, **25,0 images/s**, **7 375 MiB** VRAM (RX 7900 GRE,
     FP16, lots de 64, 6 threads ; **139 Mo** sur disque).
   - **Couverture** : **39 043 œuvres (48,4 %)** avec au moins une figure corporelle valide, **102 515
     figures** au total (2,63 figures / œuvre figurée).
     - Genres : `religious_painting` **87,4 %**, `genre_painting` **83,2 %**, `portrait` **76,5 %**,
       `nude_painting` **64,9 %**, `illustration` **63,8 %**, `sketch_and_study` **50,7 %**, `cityscape`
       **30,9 %**, `landscape` **10,9 %**, `still_life` **2,9 %**, `abstract_painting` **2,7 %**.
     - Styles : Maniérisme **88,5 %**, Première Renaissance **83,6 %**, Haute Renaissance **82,8 %**,
       Baroque **82,3 %**, Rococo **81,5 %**, Renaissance du Nord **80,9 %**, Ukiyo-e **49,4 %**,
       Cubisme **14,1 %**, Expressionnisme abstrait **4,4 %**, Minimalisme **1,4 %**.
5. **Type `meme_geste` et 37 paires proposées pour relecture** :
   - Type `meme_geste` (« Même geste ou posture, sujet ou style différents », regard attendu : `posture`)
     ajouté dans `pixplot/analysis/pairbench.py` et `pixplot/analysis/review.py`.
   - **37 paires candidates** ajoutées dans `data/wikiart81k/bench/pairs.csv` au statut `proposée`
     (aucune validée), toutes **regardées visuellement** sur planches contact avec squelettes superposés :
     7 archétypes gestuels (allongé, penché/agenouillé, deux bras levés, un bras levé, torsion/fente,
     assis, bras tendu), XVᵉ–XXᵉ s., fresques, huiles, gravures, dessins, ukiyo-e et affiches, dont
     30 en miroir et 7 directes.
6. **Fichiers ajoutés / modifiés** :
   - `pixplot/encoders/posture.py` : descripteur 50-D NumPy pur, miroir, `PostureIndex`, `ViTPoseEncoder`.
   - `pixplot/encoders/base.py`, `pixplot/features/extract.py` : support générique optionnel `extra_arrays`
     (memmap reprenable pour `poses_count`, `poses_vecs`, `poses_kpts`, `poses_boxes`).
   - `pixplot/encoders/registry.py` : enregistrement de `vitpose_base` et `vitpose_r18`.
   - `pixplot/api/spaces.py` : regard `"posture"` ajouté dans `KINDS`, `ORDER` et placé dans `NOT_KEPT` ;
     filtrage des œuvres sans figure dans `_open` si `poses_count.npy` existe.
   - `pixplot/analysis/pairbench.py`, `pixplot/analysis/review.py` : ajout du type `meme_geste`.
   - `pixplot/analysis/critique.py` : fiche critique `"posture"`.
   - `pixplot/cli.py` : ajouts localisés (`embed` pour `vitpose_*`, variante `posture_multi` dans
     `pixplot composition`).
   - `tests/test_posture.py` (4 tests, dont 3 sans PyTorch) + mise à jour de `len(q["types"]) == 8` dans
     `tests/test_research.py`.
   - `ARCHITECTURE.fr.md` et `ARCHITECTURE.md` : nouvelle section **§ 35**.

---

## 2. Mesures (WikiArt 81k, 80 716 œuvres dont 39 043 figurées)

Rapports : `data/wikiart81k/bench/pairs_report_dinov3_vitb16_20261116-111508.json` et
`data/wikiart81k/bench/composition_report_dinov3_vitb16_20261116-111508.json`.

### Paires validées existantes (sous-ensemble figuré / total)

| Catégorie (n figurées / total) | Forme (DINOv3) | Sujet (SigLIP 2) | Touche (L6) | Posture (fig. princ.) | **Posture multi+miroir** |
|---|---|---|---|---|---|
| **Filiation attestée** (18 / 20) | **50,0 % / 66,7 % · méd. 16** (0,993) | **50,0 % / 72,2 % · méd. 8** (0,998) | 16,7 % / 27,8 % · 578 (0,902) | 11,1 % / 22,2 % · 4 366 (0,639) | **22,2 % / 27,8 % · 1 754** (0,790) |
| **Même composition, sujet diff.** (12 / 28) | **66,7 % / 83,3 % · méd. 2** (0,998) | 33,3 % / 50,0 % · 77 (0,995) | 0,0 % / 25,0 % · 494 (0,988) | **8,3 % / 25,0 % · 346** (0,910) | 0,0 % / 8,3 % · 1 276 (**0,967**) |
| **Même sujet, comp. diff.** (26 / 74) | 27,0 % / 39,2 % · 506 *(tous)* | **37,8 % / 54,1 % · 30** *(tous)* | 5,4 % / 13,5 % · 24 922 *(tous)* | 0,0 % / 7,7 % · 9 472 (0,631) | 0,0 % / 3,8 % · 10 934 (0,620) |
| **Métadonnées : Témoin** (128 / 600) | 0,0 % / 0,2 % · 45 138 (0,456) | 0,0 % / 0,0 % · 45 837 (0,450) | 0,0 % / 0,0 % · 45 880 (0,447) | 0,0 % / 0,8 % · 19 648 (**0,498**) | — |

- Succès notables en `posture_multi` : *Le Semeur* Van Gogh ↔ Millet **rang [1, 1]** (cos 0,979),
  *L'Enlèvement d'Europe* Rubens ↔ Titien **rang [1, 1]** (0,946), *Olympia* → *Vénus d'Urbin* **rang 13**
  (898 en retour, 0,951), *Lazare* Van Gogh → Rembrandt **rang 1 152** (vs Forme 1 856).
- **Forme + posture (validation croisée hors échantillon, 200 tirages 50/50)** :
  - `meme_composition` : $\alpha = 0$ retenu dans **90,5 %** des tirages, centile moyen **0,9201** contre
    **0,9275** pour Forme seule (aucun gain).
  - `filiation` : $\alpha \approx 0{,}10$ améliore légèrement la médiane sur découpages fixes (20 → 16,
    centile 0,9941 → 0,9944), mais sur 200 tirages R@10 passe de 45,0 % à 43,7 % pour un centile stable
    (0,9942 vs 0,9941).
- **Sur les 37 paires `meme_geste` proposées** *(à titre indicatif : biais de sélection car extraites via
  posture, non encore relues)* : Forme (R@10 0,0 %, R@100 2,7 %, méd. 9 600), Sujet (0,0 %, méd. 16 076)
  et Touche (0,0 %, méd. 15 108) les ratent presque toutes ; l'activation du **miroir** fait passer
  `posture_multi` de méd. **8 914** (centile 0,714) à méd. **38** (centile **0,972**).

---

## 3. Tests

- Suite complète exécutée : **95 passed** (91 existants + 4 nouveaux dans `tests/test_posture.py`,
  dont 3 sans PyTorch).

---

## 4. Reste à faire (pour l'intégrateur)

- Relire et fusionner `gemini/postures` dans `main` (`.\scripts\nouvelle-tache.ps1 postures -Agent gemini -Terminer`).
- **Petit ajustement `web/` hors périmètre de cette branche** : dans `web/atlas-revue.js` ligne 195
  (`/^[1-7]$/`), passer à `/^[1-8]$/` (ou `Number(k) <= rv.types.length`) et mettre à jour le message
  « touches 1 à 7 » ligne 152 afin que le raccourci clavier `8` fonctionne aussi pour le 8ᵉ type
  `meme_geste` (le clic et la touche `Entrée` marchent déjà).
- Mettre à jour `docs/HANDOFF.md` (et CHANGELOG / version si publication).

---

## 5. Décision pour l'utilisateur

1. **Relire les 37 paires `meme_geste` proposées** dans l'Atlas (touche `R`, relecture rapide : elles
   apparaissent en tête de file) afin de constituer un premier jeu validé de *Pathosformeln*.
2. **Garder ou non le regard « posture »** :
   - **(Recommandée à ce stade) Garder `"vitpose"` dans `NOT_KEPT` jusqu'à la relecture des 37 paires** :
     il ne couvre que 48,4 % de WikiArt 81k et n'améliore pas Forme sur `meme_composition` / `filiation`.
   - **Si la relecture confirme l'intérêt des paires `meme_geste`** : envisager d'exposer « Posture » comme
     regard spécialisé (en branchant `PostureIndex` multi-figures + miroir dans `Spaces.neighbors`, car la
     version multi-figures + miroir surpasse largement le vecteur global unique : centile 0,790 vs 0,639 sur
     `filiation`, et 0,972 vs 0,809 sur les candidates `meme_geste`), avec une mention claire qu'il ne
     s'applique qu'aux œuvres figuratives.
