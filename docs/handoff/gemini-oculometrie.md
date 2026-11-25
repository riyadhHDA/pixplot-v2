# Compte rendu — Oculométrie : les zones de PixPlot face au regard humain (AVAtt)

**Branche :** `gemini/oculometrie` · **Date :** 25/11/2026 · **Assistant :** Gemini 4 Neon

## Question posée

Les zones que PixPlot met en avant pour l'historien — les cases 4 × 4 du bouton **« Pourquoi ? »**
(`pixplot/analysis/correspondences.py`, ARCHITECTURE §§ 39–40) et les zones trouvées par une
phrase (**`search_zones`**, index SigLIP 2 de 1,6 million de zones) — coïncident-elles avec les
zones réellement regardées par des observateurs humains ?

## 1. Source, contenu et licences d'AVAtt

- **Publication :** M. A. Kerkouri, M. Tliba, A. Chetouani, A. Bruno, *AVAtt: A Free-Viewing
  Eye-Tracking Dataset and Benchmark for Visual Attention on Paintings*, arXiv:2610.30481 (2026).
- **Accès :** ouvert, sans compte ni formulaire (*non gated*) sur
  [Hugging Face (`Amine-CV/AVAtt`)](https://huggingface.co/datasets/Amine-CV/AVAtt) ; code sur
  [GitHub (`kmamine/AVAtt---Art-Visual-Attention`)](https://github.com/kmamine/AVAtt---Art-Visual-Attention).
- **Téléchargement autorisé par l'utilisateur :** enregistré hors git dans
  `data/avatt/` (1 148 fichiers, ~312 Mo sans les vidéos `temporal_saliency_maps/`).
- **Contenu :**
  - **283 lignes** dans `metadata.csv`, soit **282 peintures uniques** (`avatt_0219` est un doublon
    signalé de `avatt_0218`, *Las Meninas*, exclu par défaut), couvrant **34 mouvements** (regroupés
    en 16 familles sur 5 siècles).
  - **152 volontaires** en observation libre (*free-viewing* : regarder et apprécier librement),
    présentation de 15 s (182 peintures) ou 5,5 s (101 peintures), oculomètre Tobii X2-30 (30 Hz,
    filtre I-VT), stimuli centrés sur fond gris 1600 × 900 avec coordonnées exactes de la peinture
    (`painting_x0..y1`).
  - **121 002 fixations** sur les 282 peintures uniques, dont **120 785 (99,82 %)** tombent dans le
    rectangle de la peinture (minimum : 148 fixations par peinture).
- **Licences :**
  - Données oculométriques, cartes et annotations : **CC0 1.0**.
  - Code d'AVAtt : **MIT**.
  - Images des peintures : 248 *public domain*, 25 *in copyright*, 10 *unknown* (fournies pour la
    recherche scientifique non commerciale). **Strictement gardées en local dans `data/avatt/`**,
    jamais dans git.

## 2. Rattachement à WikiArt 81k (dHash)

Rattachement par empreinte perceptuelle 64 bits (`pixplot.catalog.ingest.dhash`), après recadrage
exact sur `(painting_x0, painting_y0, painting_x1, painting_y1)` et réduction à 1024 px max (même
calcul que `pixplot ingest`), comparé aux 80 716 œuvres `ok` de `catalog.sqlite`. Règle stricte
identique à `wikiart_names.py` (ARCHITECTURE § 34) : distance ≤ 8 bits et marge ≥ 4 bits avec la
deuxième candidate.

- **Rattachées sûrement :** **108 / 282** peintures uniques (38,3 %), toutes présentes dans DINOv3
  (`regions.npy`) et dans l'index `textzones` (108/108).
- **Absentes / non rattachées :** **174 / 282**, dont **12 rejetées par manque de marge** (parmi
  lesquelles 2 vrais doublons présents en double exemplaire dans WikiArt 81k : `avatt_0153` Renoir
  et `avatt_0261` Bellini/Titien, volontairement laissés hors échantillon pour garder une règle sans
  exception). Les autres viennent de Wikimedia Commons / musées ou sont hors de `huggan/wikiart`.
- **Contrôle :** tous les rattachements à 6–8 bits ont été vérifiés sur artiste et titre (aucun faux
  positif) ; écart maximal de rapport hauteur/largeur entre le recadrage AVAtt et WikiArt : 6,0 %.
- Aucun calcul GPU long n'a été lancé (les 108 peintures disposent déjà de leurs vecteurs DINOv3 et
  SigLIP 2 ; seul l'encodage texte des 20 requêtes + 58 titres a chargé SigLIP 2 quelques secondes).

## 3. Mesures (IC 95 % par bootstrap sur les peintures, 2 000 tirages)

Pour chaque peinture, on mesure sur les coordonnées normalisées `[0, 1]²` des fixations :
- **`fix`** : part des fixations humaines tombant dans la ou les cases montrées ;
- **`surf`** : part de surface de la peinture couverte (les cases de bord du carré letterbox peuvent
  être rognées) ;
- **`enr`** : enrichissement (`fix / surf`, vaut 1,0 si les fixations étaient uniformes) ;
- **`NSS`** : *Normalized Scanpath Saliency* du masque binaire des cases montrées,
  `(fix − surf) / sqrt(surf · (1 − surf))` (0 au hasard uniforme, positif si la zone est plus
  regardée que le reste de la peinture).

Deux **témoins naïfs sans apprentissage** sont évalués sur **exactement la même grille** (top-*k*
cases) et en NSS continu :
- **Biais central (`center`)** : gaussienne isotrope centrée en `(0,5 ; 0,5)` ($\sigma = 0{,}25$).
- **Contraste local (`contrast`)** : contraste couleur centre-périphérie + gradient de Sobel lissé.

### (a) & (c) Zones du bouton « Pourquoi ? » (grille 4 × 4, DINOv3)

Mesuré sur les 108 peintures rattachées, d'abord avec la 1ʳᵉ voisine **au sein d'AVAtt** (cosinus
médian 0,609 ; 93/108 peintures à 4 correspondances), puis avec la 1ʳᵉ voisine **dans tout WikiArt
81k** (cosinus médian 0,763 ; 104/108 à 4 correspondances). L'ancien classement d'avant le § 40
(`why_old`, biais de coins) est inclus en repère.

| Condition (AVAtt ↔ AVAtt, *n* = 108) | Part fixations [IC 95 %] | Surface | Enrich. [IC 95 %] | NSS [IC 95 %] | Δ NSS vs « Pourquoi ? » [IC 95 %] · *p* |
|---|---:|---:|---:|---:|---|
| **« Pourquoi ? » (§ 40, actuel)** | **36,2 %** [33,5 ; 38,7] | 28,0 % | **1,28×** [1,20 ; 1,36] | **+0,181** [+0,133 ; +0,229] | — |
| Témoin hasard (50 tirages, même *k*) | 24,0 % [23,4 ; 24,5] | 24,0 % | 0,97× [0,96 ; 0,98] | −0,006 [−0,012 ; +0,001] | **+0,187** [+0,137 ; +0,234] · <0,0001 |
| Témoin naïf : biais central (top-*k*) | **57,4 %** [54,9 ; 59,7] | 32,4 % | **1,79×** [1,72 ; 1,86] | **+0,538** [+0,494 ; +0,580] | **−0,357** [−0,420 ; −0,297] · <0,0001 |
| Témoin naïf : contraste local (top-*k*) | 41,8 % [38,2 ; 45,3] | 25,9 % | 1,57× [1,46 ; 1,68] | +0,354 [+0,291 ; +0,417] | **−0,173** [−0,247 ; −0,104] · <0,0001 |
| Ancien « Pourquoi ? » (avant § 40) | 10,1 % [8,4 ; 11,9] | 19,8 % | 0,47× [0,41 ; 0,55] | −0,250 [−0,279 ; −0,216] | **+0,430** [+0,371 ; +0,485] · <0,0001 |

| Condition (AVAtt ↔ WikiArt 81k, *n* = 108) | Part fixations [IC 95 %] | Surface | Enrich. [IC 95 %] | NSS [IC 95 %] | Δ NSS vs « Pourquoi ? » [IC 95 %] · *p* |
|---|---:|---:|---:|---:|---|
| **« Pourquoi ? » (§ 40, actuel)** | **43,2 %** [40,2 ; 45,9] | 31,1 % | **1,39×** [1,30 ; 1,46] | **+0,260** [+0,205 ; +0,312] | — |
| Témoin hasard (50 tirages, même *k*) | 24,6 % [23,9 ; 25,2] | 24,5 % | 0,97× [0,96 ; 0,99] | −0,003 [−0,009 ; +0,003] | **+0,263** [+0,207 ; +0,315] · <0,0001 |
| Témoin naïf : biais central (top-*k*) | **58,7 %** [56,4 ; 61,0] | 33,1 % | **1,79×** [1,73 ; 1,86] | **+0,548** [+0,505 ; +0,589] | **−0,288** [−0,353 ; −0,224] · <0,0001 |
| Témoin naïf : contraste local (top-*k*) | 42,1 % [38,5 ; 45,7] | 26,5 % | 1,53× [1,43 ; 1,63] | +0,344 [+0,281 ; +0,407] | **−0,083** [−0,162 ; −0,002] · 0,043 |
| Ancien « Pourquoi ? » (avant § 40) | 11,0 % [9,1 ; 12,9] | 19,9 % | 0,51× [0,44 ; 0,58] | −0,229 [−0,263 ; −0,192] | **+0,489** [+0,422 ; +0,554] · <0,0001 |

*(Repère en NSS continu sur les 108 peintures : biais central = **+0,733** [+0,687 ; +0,780] ;
contraste local = **+0,558** [+0,498 ; +0,619].)*

### (b) & (c) Zones trouvées par une phrase (`search_zones`, SigLIP 2)

Deux protocoles, comparés aux autres cases de la **même grille** (2 × 2 ou 4 × 4) de la même
peinture (bootstrap sur les peintures, moyenne par peinture quand une œuvre répond à plusieurs
requêtes) :
1. **20 requêtes iconographiques fixes en français** (15 meilleures peintures AVAtt par requête →
   300 zones sur 100 peintures distinctes ; 287 en 4 × 4, 13 en 2 × 2).
2. **Titres des œuvres** (58 peintures rattachées ayant un titre dans AVAtt ; 30 en 2 × 2, 28 en 4 × 4).

| Protocole / Condition | Part fix. [IC 95 %] | Enrich. [IC 95 %] | NSS [IC 95 %] | Rang humain [IC 95 %] | Δ NSS vs `search_zones` · *p* |
|---|---:|---:|---:|---:|---|
| **20 requêtes FR (*n* = 100 peint.) — `search_zones`** | **9,7 %** [8,6 ; 10,8] | **1,43×** [1,26 ; 1,60] | **+0,105** [+0,061 ; +0,149] | **58,7 %** [54,1 ; 63,2] | — |
| — Hasard (même grille) | 7,4 % [6,8 ; 8,2] | 1,00× | 0,000 | 50,0 % | **+0,105** [+0,061 ; +0,149] · <0,0001 |
| — Biais central (même grille) | 12,4 % [10,8 ; 14,0] | 1,83× [1,61 ; 2,08] | +0,212 [+0,150 ; +0,277] | 74,9 % [70,6 ; 79,0] | −0,107 [−0,190 ; −0,029] · 0,008 |
| — Contraste local (même grille) | 14,6 % [12,5 ; 16,7] | 2,09× [1,79 ; 2,39] | +0,289 [+0,210 ; +0,365] | 74,8 % [69,6 ; 79,7] | −0,183 [−0,270 ; −0,094] · <0,0001 |
| **Titres d'œuvres (*n* = 58 peint.) — `search_zones`** | **22,2 %** [19,3 ; 25,2] | **1,75×** [1,45 ; 2,10] | **+0,220** [+0,140 ; +0,310] | **70,9 %** [64,0 ; 77,9] | — |
| — Hasard (même grille) | 16,0 % [13,7 ; 18,5] | 1,00× | 0,000 | 50,0 % | **+0,220** [+0,140 ; +0,310] · <0,0001 |
| — Biais central (même grille) | 20,8 % [18,0 ; 23,9] | 1,62× [1,38 ; 1,90] | +0,177 [+0,103 ; +0,255] | 72,1 % [63,8 ; 80,2] | +0,043 [−0,056 ; +0,145] · 0,402 |
| — Contraste local (même grille) | 19,8 % [16,6 ; 23,0] | 1,50× [1,21 ; 1,82] | +0,141 [+0,050 ; +0,234] | 62,0 % [53,2 ; 70,4] | +0,079 [−0,017 ; +0,184] · 0,116 |

**Détail décisif par requête (`search_zones`) :** la moyenne globale (+0,105) masque un contraste
complet selon la nature du motif demandé :
- **Motifs focaux (humains, bâti)** : `enfant` (+0,370, 2,40×, rang 77 %), `visage` (+0,359, 2,34×,
  rang 82 %), `maison` (+0,302, 2,17×, rang 78 %), `portrait d'une femme` (+0,257, 2,01×, rang 75 %),
  `pont` (+0,217), `groupe de personnages` (+0,216), `église ou clocher` (+0,187), `mains` (+0,172).
- **Motifs de fond / décor** : `fleurs` (−0,086), `fenêtre` (−0,091), `table` (−0,099), `montagne`
  (−0,136, 0,54×, rang 35 %), `ciel et nuages` (**−0,241**, 0,19×, rang **10 %**).

## 4. Examen à l'œil (planches visuelles)

Deux planches contact superposant la carte de chaleur humaine (AVAtt) aux cadres PixPlot ont été
générées et examinées (`data/wikiart81k/bench/oculometrie/planche_pourquoi.jpg` et
`planche_search_zones.jpg`, hors git) :

- **« Pourquoi ? » — réussites :**
  - `avatt_0107` (Sisley, *The Road from Hampton Court*, fix 78 %, NSS +1,03, cos 0,76) : les cadres
    1–3 couvrent exactement la bande du pont, des maisons et des barques qui concentre le regard.
  - `avatt_0239` (Rembrandt, *Les Syndics*, fix 63 %, NSS +0,68, cos 0,59) : les cadres 2, 3 et 1
    encadrent les visages et le buste des drapiers.
  - `avatt_0244` (Manet, *Marine à Arcachon*, fix 53 %, NSS +0,66, cos 0,57) : les cadres 1–2 tombent
    sur les voiliers et le personnage sur la plage (les cadres 3–4 restent de fines bandes en haut).
- **« Pourquoi ? » — échecs oculométriques :**
  - `avatt_0259` (Boldini, *La Conversation*, fix 9 %, NSS −0,38, cos 0,52) : le regard fixe les deux
    visages au centre-gauche, mais les correspondances avec la voisine AVAtt portent sur le fauteuil
    et le mur à droite.
  - `avatt_0098` (Sisley, fix 12 %, NSS −0,42, cos 0,73) : l'œil regarde la maison claire au centre,
    tandis que « Pourquoi ? » cadre le ciel bleu et la masse d'arbres — zones **pertinentes pour la
    comparaison formelle** entre deux paysages, bien que peu fixées.
  - `avatt_0248` (*Soup Bowl Covers*, fix 5 %, NSS −0,47, cos 0,39) : sans vraie voisine proche dans
    AVAtt, les correspondances tombent sur le fond brun et le bord.
- **`search_zones` — réussites et faux échecs :**
  - Réussites : `« visage »` sur Hals (`avatt_0026`, fix 41 % sur 6 % de surface, NSS +1,45, rang
    100 %) et sur un portrait Renaissance (`avatt_0028`, fix 34 %, NSS +1,15) ; `« groupe de
    personnages »` sur Gauguin (`avatt_0138`, minuscule figure dans la forêt, fix 33 %, NSS +1,09).
  - Faux échecs : `« ciel et nuages »` sur deux Sisley (`avatt_0053`, `avatt_0084`, NSS −0,44 / −0,40)
    et `« montagne »` sur Seghers (`avatt_0180`, NSS −0,43). Dans les trois cas, **PixPlot a trouvé
    exactement ce qu'on lui demandait** ; les humains regardaient simplement les maisons, le chemin ou
    la rivière en dessous.

## 5. Ce que l'historien doit en retenir

1. **La réparation du « Pourquoi ? » (§ 40) est confirmée par le regard humain.** L'ancien classement
   (coins, § 39) évitait littéralement les zones regardées (NSS −0,250, deux fois moins que le hasard).
   Le classement actuel tombe nettement au-dessus du hasard (+0,181 dans AVAtt, +0,260 sur les vraies
   voisines du corpus).
2. **Mais « Pourquoi ? » n'est pas une carte d'attention humaine.** Le simple biais vers le centre
   capture 57–59 % des fixations (NSS +0,54) et le contraste local 42 % (NSS +0,35), tous deux
   devant « Pourquoi ? » (36–43 %, NSS +0,18 à +0,26). Une partie de l'amélioration du § 40 vient
   d'avoir quitté les coins pour se rapprocher du centre ; le modèle reste guidé par l'homologie
   formelle entre deux toiles, pas par la saillance cognitive.
3. **Une zone peu regardée reste souvent pertinente pour la comparaison.** Un ciel de Sisley, un
   encadrement architectural ou un fond de nature morte attire peu de fixations lors d'une vision
   libre de 5 à 15 s, mais peut légitimement rapprocher deux compositions ou deux manières.
4. **`search_zones` suit la requête, pas la saillance.** Sur des requêtes de figures/visages ou sur
   le titre même de l'œuvre, il pointe des zones très regardées (jusqu'à 2,4× le hasard, au niveau du
   biais central sur les titres). Sur des éléments de décor (`ciel`, `montagne`), il localise
   correctement des zones délaissées par le regard libre.

## 6. Limites

- **Couverture d'AVAtt :** 108/282 peintures rattachées à WikiArt 81k (les 174 absentes n'ont pas été
  encodées sur GPU pour éviter tout calcul GPU non demandé ; elles couvrent notamment davantage
  d'œuvres muséales hors WikiArt).
- **Observation libre ≠ regard d'historien :** AVAtt enregistre des volontaires non spécialistes en
  vision libre de 5,5 s ou 15 s ; l'œil d'un historien qui cherche une attribution ou un repentir ne
  suit pas nécessairement les mêmes fixations.
- **Grille fixe :** les mesures reflètent la granularité actuelle de PixPlot (4 × 4 letterbox pour
  « Pourquoi ? », 2 × 2 et 4 × 4 pour `search_zones`).

## 7. Code ajouté et vérifications

- `pixplot/analysis/gaze.py` : chargement AVAtt, rattachement dHash, métriques (`fix_share`, `area`,
  `enrichment`, `nss`), témoins naïfs (`center_bias_map`, `local_contrast_map`), bootstrap sur les
  peintures, planches visuelles.
- `pixplot/cli.py` : commande `pixplot oculometrie` (documentée dans `docs/COMMANDS.fr.md` et
  `docs/COMMANDS.md`).
- `tests/test_gaze.py` : 4 tests unitaires et bout-en-bout sur le petit corpus (`tests/conftest.py`).
- Tous les tests passent (suite complète `pytest -q tests`).

## 8. Décisions attendues de l'utilisateur

1. **Intégration dans `ARCHITECTURE.fr.md` / `ARCHITECTURE.md` :** ces résultats sont prêts à être
   résumés en une nouvelle section datée lors de la fusion dans `main`.
2. **Encodage éventuel des 174 peintures AVAtt absentes de WikiArt 81k :** souhaites-tu les encoder
   à part (~10 s de GPU) pour porter l'échantillon de 108 à 282 peintures, ou l'échantillon de 108
   peintures (déjà très net statistiquement, tous les IC 95 % étant étroits) suffit-il ?
3. **Suite interface :** aucune modification de l'Atlas n'est nécessaire (la mise en garde du § 40
   sous les zones du « Pourquoi ? » est déjà cohérente avec ces résultats : « zones qui se
   ressemblent le plus — une piste à regarder, pas une explication »).
