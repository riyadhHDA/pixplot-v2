# Compte rendu — évaluation de PE-Core L/14 et CSD ViT-L/14 (`gemini/pecore-csd`)

*Date : 19/11/2026 · Assistant : Gemini 4 Neon (Antigravity) · Branche : `gemini/pecore-csd`*

## 1. Ce qui a été fait

### A. PE-Core L/14 (Meta, 2025) contre SigLIP 2 So400m (« sujet »)

1. **Vérification de la licence** : fiches Hugging Face `facebook/PE-Core-L14-336` et
   `timm/PE-Core-L-14-336` vérifiées avant téléchargement — **licence Apache 2.0**, accès libre.
2. **Choix techniques retenus** :
   - Variante **`pe_core_l14`** (`timm/PE-Core-L-14-336`, 0,32 Md visuel + 0,31 Md texte, 1 024 d,
     336 px, 2,68 Go ; `pe_core_b16` et `pe_core_g14` aussi enregistrées). `G/14 @448` (1,88 Md
     visuel, 9,68 Go, 1 024 patchs contre 576) aurait pris ~3 h sur 81k.
   - Chargement autonome sans dépendance `open_clip` : tour visuelle via `timm`
     (`vit_pe_core_large_patch14_336`, 310 tenseurs chargés en `strict=True`) et tour texte causale
     en PyTorch fidèle à `facebookresearch/perception_models` (GELU, `pad_id=0`, pooling `argmax` sur
     EOT, 293 tenseurs chargés en `strict=True`). Prétraitement *letterbox* sans recadrage,
     normalisation `(x − 0,5) / 0,5`.
   - Recherche par phrase branchée dans `pixplot/api/search.py` et `pixplot search-text --encoder
     pe_core_l14` (SigLIP 2 reste la valeur par défaut sans aucun changement pour l'Atlas ni MCP).
3. **Extraction sur WikiArt 81k** (`features/pe_core_l14_20261119-225940`, journal
   `data/wikiart81k/pe_core.log`) : **80 716 œuvres**, **0 échec**, **20 min 18 s**,
   **65,5 images/s**, **3 806 MiB** VRAM (RX 7900 GRE, FP16, lots de 64).

### B. CSD ViT-L/14 (Somepalli et al., ECCV 2024) contre Touche (DINOv3, couche 6)

1. **Vérification des licences (code ET poids)** :
   - Code officiel (`learn2phoenix/CSD`) : **licence MIT** (`LICENSE` vérifié sur GitHub).
   - Poids préentraînés sur Hugging Face (`tomg-group-umd/CSD-ViT-L/pytorch_model.bin`, 2,44 Go) :
     **licence CC BY 4.0**, accès libre — autorisés pour un usage de recherche local.
2. **Choix techniques retenus** :
   - Implémentation autonome en PyTorch (`pixplot/encoders/csd.py`) sans dépendance au paquet
     `openai/clip` : backbone CLIP ViT-L/14 (QuickGELU, normalisation CLIP, *letterbox* sans recadrage
     à 224 px) + tête style `last_layer_style` normalisée L2 (768 d, 296 tenseurs chargés en
     `strict=True`).
   - Observation importante sur le fichier `pytorch_model.bin` : les métadonnées internes indiquent
     `iter: 15000` (`iters=40000`, `lambda_c=0.0`, entraîné sur `improved_aesthetics_6plus` /
     `laion_style_subset`), ce qui explique l'avertissement du README officiel sur un écart avec les
     chiffres de l'article (80 000 itérations).
3. **Extraction sur WikiArt 81k** (`features/csd_vitl14_20261119-232036`, journal
   `data/wikiart81k/csd.log`) : **80 716 œuvres**, **0 échec**, **8 min 38 s**, **149,8 images/s**,
   **1 985 MiB** VRAM (RX 7900 GRE, FP16, lots de 64).

### Code ajouté / modifié

- `pixplot/encoders/pe_core.py`, `pixplot/encoders/csd.py` : nouveaux encodeurs autonomes.
- `pixplot/encoders/registry.py` : enregistrement de `pe_core_b16`, `pe_core_l14`, `pe_core_g14`,
  `csd_vitl14` (avec repli sur leur résolution native quand `--input-size` vaut 448).
- `pixplot/api/spaces.py` : regards `"sujet_pe"` et `"touche_csd"` ajoutés dans `KINDS`, `ORDER` et
  placés dans `NOT_KEPT` (hors Atlas et MCP par défaut).
- `pixplot/api/search.py` et `pixplot/cli.py` : ajouts localisés (`embed` pour `pe_core_*` et `csd_*`,
  option `--encoder` sur `search-text`).
- `pixplot/analysis/critique.py` : fiches critiques `"sujet_pe"` et `"touche_csd"`.
- `tests/test_pe_core.py` (3 tests, dont 2 sans PyTorch) et `tests/test_csd.py` (3 tests, dont 2 sans
  PyTorch).
- `ARCHITECTURE.fr.md` et `ARCHITECTURE.md` : nouvelles sections **§ 31** (PE-Core) et **§ 32** (CSD).

*(Note : pendant la session, le catalogue partagé `catalog.sqlite` a été enrichi de 35 185 artistes
retrouvés par MMArt ; `pixplot bench` a donc été mesuré sur les deux bases `n = 39 499` et
`n = 74 684` pour SigLIP 2 et PE-Core afin de garder une comparaison strictement homogène.)*

---

## 2. Synthèse des mesures (WikiArt 81k, 80 716 œuvres)

### A. PE-Core L/14 @336 contre SigLIP 2 So400m @384

- **`pixplot bench` (k = 10, P@1 = première voisine étiquetée, § 30)** :
  - Artiste (`huggan/wikiart` seul, n = 39 499) : PE-Core **74,5 % / 62,6 %** vs SigLIP 2 73,0 % / 61,6 %
  - Artiste (catalogue enrichi MMArt, n = 74 684) : PE-Core **61,5 % / 44,3 %** vs SigLIP 2 59,3 % / 42,9 %
  - Style (n = 80 716) : PE-Core **72,0 % / 62,3 %** vs SigLIP 2 71,4 % / 62,0 %
  - Genre (n = 64 929) : PE-Core **83,6 % / 79,7 %** vs SigLIP 2 83,4 % / 79,5 %
- **`pixplot pairs bench`** :
  - **Filiation attestée** (10 paires, n = 20) : jeu égal — R@10 **45,0 %**, R@100 **70,0 %**, rang
    médian **18** (PE-Core) vs **17** (SigLIP 2), centile 0,996 vs 0,998.
  - **Même sujet, composition différente** (37 paires, n = 74) : SigLIP 2 R@10 37,8 % / méd. 30 vs
    PE-Core 28,4 % / méd. 174 (centile 0,929 pour PE-Core vs 0,919) ; mais sur les **16 paires sans
    biais de sélection `désaccord sujet > …`**, PE-Core passe devant (R@10 **21,9 %** vs 12,5 %, méd.
    **573** vs 1 152, centile **0,867** vs 0,838).
- **Recherche par phrase (10 requêtes d'historien, 100 résultats inspectés visuellement par langue)** :
  - **En français** : **SigLIP 2 : 97 / 100** contre **PE-Core : 81 / 100** (−16 pts). PE-Core décroche
    sur « Annonciation » (**4/10** contre 10/10), « femme lisant une lettre » (**5/10** contre 9/10)
    et « paysage d'hiver avec patineurs » (**6/10** contre 9/10), et souffre d'un biais OCR sur le
    texte imprimé dans les reproductions.
  - **En anglais** : **SigLIP 2 : 96 / 100** contre **PE-Core : 92 / 100** (PE-Core remonte à 10/10
    sur *Annunciation* et *winter landscape with ice skaters*, mais reste à 5/10 sur *woman reading a
    letter* contre 8/10 pour SigLIP 2).

### B. CSD ViT-L/14 @224 contre Touche (DINOv3, couche 6 @448)

- **`pixplot bench` (k = 10, P@1 selon § 30)** :
  - Style (n = 80 716) : CSD **67,0 % / 57,7 %** vs Touche 61,3 % / 49,6 % (repère SigLIP 2 : 71,4 % / 62,0 %)
  - Artiste (n = 74 684) : CSD **54,8 % / 40,0 %** vs Touche 51,9 % / 35,0 %
  - Genre (n = 64 929) : CSD **75,4 % / 69,8 %** vs Touche 69,4 % / 62,8 %
  - **Détail par style (P@10)** : quasi égalité sur la facture pure (`Analytical_Cubism` **58,1 %**
    Touche vs 56,0 % CSD ; `Pointillism` 61,8 % vs 63,0 % ; `Fauvism` 29,8 % vs 31,8 %), mais bond
    massif de CSD sur les écoles et médiums nommés dans le web (`Ukiyo_e` 96,3 % vs 80,3 %, `Baroque`
    67,4 % vs 51,9 %, `High_Renaissance` 45,5 % vs 33,7 %).
- **`pixplot pairs bench`** :
  - **Métadonnées « artistes différents, facture comparable »** (n = 500, sans biais de sélection) :
    CSD R@10 **1,8 %**, R@100 **10,4 %**, rang médian **2 157**, centile **0,854** vs Touche 1,6 %,
    7,0 %, méd. 7 750, centile 0,803.
  - **Métadonnées « même artiste, styles différents »** (n = 600) : CSD méd. **14 910**, centile
    **0,746** vs Touche 22 217, centile 0,660.
  - **Métadonnées « même sujet, styles différents »** (n = 600) : CSD centile **0,591** (méd. 31 368)
    vs Touche 0,622 (méd. 28 160).
  - **Annotées « artistes différents, facture comparable »** (17 paires, n = 34) : Touche R@10 29,4 %,
    méd. 202, centile 0,710 vs CSD R@10 0,0 %, méd. 7 666, centile **0,836** (avec fort biais de
    sélection : 9 paires viennent de `désaccord touche > …` et 4 de `… > touche`).
- **Alerte méthodologique majeure (contamination WikiArt / LAION-Styles)** : CSD est initialisé sur
  CLIP ViT-L/14 et affiné sur **LAION-Styles** (511 921 images tirées de LAION-Aesthetics 6+, jamais
  purgées de WikiArt, avec 3 840 étiquettes d'artistes, médiums et mouvements). Les scores WikiArt de
  CSD sont donc **potentiellement gonflés** et reflètent autant le style nommé dans les légendes web
  (`csd ∩ sujet` = 16,2 % de voisines communes contre 12,0 % pour Touche) que la facture matérielle.

---

## 3. Tests

- Suite complète exécutée : **86 passed** (80 tests existants + 3 tests dans `tests/test_pe_core.py` +
  3 tests dans `tests/test_csd.py`, dont 4 tests sans PyTorch).

## 4. Reste à faire (pour l'intégrateur)

- Relire et fusionner `gemini/pecore-csd` dans `main` (via
  `.\scripts\nouvelle-tache.ps1 pecore-csd -Agent gemini -Terminer`).
- Mettre à jour `docs/HANDOFF.md` (et, si publication, numéro de version et CHANGELOG — hors périmètre
  de cette branche).

## 5. Décision pour l'utilisateur

### A. PE-Core L/14 vs SigLIP 2 So400m (« sujet »)

**Recommandation : garder l'état actuel (SigLIP 2 So400m comme regard « sujet », PE-Core dans `NOT_KEPT`).**

- PE-Core L/14 gagne +0,2 à +2,2 pt sur les étiquettes image → image, mais perd **16 points en recherche
  par phrase en français** (81/100 contre 97/100, effondrement sur « Annonciation » à 4/10) et reste
  même derrière en anglais (92/100 vs 96/100). Remplacer SigLIP 2 obligerait aussi à recalculer l'index
  de zones (6 h 21), les noms Iconclass et les axes conceptuels 2D pour un résultat moins bon en
  français.
- Options :
  1. **(Recommandée) Garder l'état actuel** : SigLIP 2 reste le regard « sujet », PE-Core reste dans
     `NOT_KEPT` (interrogeable en CLI via `pixplot search-text --encoder pe_core_l14` et `pairs bench`).
  2. **Ajouter PE-Core comme regard séparé** : retirer `"pe_core"` de `NOT_KEPT` dans
     `pixplot/api/spaces.py` et indexer (`pixplot index --encoder pe_core_l14`), mais il ferait
     doublon avec SigLIP 2.
  3. **Remplacer SigLIP 2** : déconseillé tant que PixPlot s'utilise en français.

### B. CSD ViT-L/14 vs Touche (DINOv3, couche 6)

**Recommandation : garder l'état actuel (« touche » inchangé, CSD dans `NOT_KEPT`), et réévaluer CSD
plus tard sur un corpus muséal hors WikiArt/LAION.**

- Ne pas remplacer « touche » : DINOv3 couche 6 est strictement auto-supervisé (zéro fuite WikiArt,
  zéro étiquette de style apprise), tourne à 448 px, fait jeu égal ou mieux sur les styles de facture
  pure (`Analytical_Cubism`, `Pointillism`) et reste le regard le plus indépendant de Forme et Sujet.
- Les bons scores de CSD sur WikiArt (style P@10 57,7 % vs 49,6 %, métadonnées `meme_facture` méd.
  2 157 vs 7 750) sont difficiles à démêler de la contamination LAION-Styles / WikiArt et de sa
  supervision par noms d'écoles (`Ukiyo_e`, `Baroque`, `High_Renaissance`), et reposent sur un
  checkpoint public arrêté à l'itération 15 000.
- Options :
  1. **(Recommandée) Garder l'état actuel** : « touche » reste DINOv3 couche 6, CSD reste dans
     `NOT_KEPT` (vecteurs gardés sur disque pour un futur test sur corpus IIIF / Paris Musées non
     présent dans LAION).
  2. **Ajouter CSD comme regard « Style (CSD) »** : retirer `"csd"` de `NOT_KEPT` dans
     `pixplot/api/spaces.py` et indexer (`pixplot index --encoder csd_vitl14`), en affichant sa fiche
     critique (risque de contamination WikiArt).
  3. **Remplacer « touche » par CSD** : déconseillé pour les raisons méthodologiques ci-dessus.
