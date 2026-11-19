# Compte rendu — évaluation de SSCD (`gemini/sscd`)

*Date : 19/11/2026 · Assistant : Gemini 4 Neon (Antigravity) · Branche : `gemini/sscd`*

## 1. Ce qui a été fait

1. **Vérification de la licence** : dépôt officiel `facebookresearch/sscd-copy-detection` (Pizzi et
   al., Meta, CVPR 2022) vérifié sur GitHub (`LICENSE` et `README.md`) — **licence MIT** pour le
   code et les poids préentraînés TorchScript (`dl.fbaipublicfiles.com/sscd-copy-detection/`), sans
   demande d'accès ni restriction d'usage.
2. **Choix techniques retenus** :
   - Variante **`sscd_disc_large`** (ResNeXt-101 32×4d, 1 024 dimensions, meilleure variante du
     dépôt ; `sscd_disc_mixup` est aussi supporté dans le registre) afin qu'un résultat négatif ne
     puisse pas être imputé à un modèle trop petit.
   - Format **TorchScript autonome** (`.torchscript.pt`) téléchargé dans
     `data/wikiart81k/models/sscd_disc_large.torchscript.pt` (hors git), sans dépendance externe
     (`classy_vision` / `augly`).
   - Résolution **320 px** (taille carrée recommandée par le dépôt SSCD pour les lots GPU), avec le
     **letterbox** standard de PixPlot (normalisation ImageNet, sans recadrer ni déformer l'œuvre).
   - Vecteurs bruts normalisés L2 enregistrés sur disque ; effet du centrage (recommandé par le
     README SSCD) mesuré en plus en mémoire pour vérification.
3. **Code ajouté / adapté** :
   - `pixplot/encoders/sscd.py` : `SSCDEncoder` (`sscd_disc_mixup`, `sscd_disc_large`),
     téléchargement atomique dans `<données>/models/`.
   - `pixplot/encoders/registry.py` : enregistrement de `sscd_disc_mixup` et `sscd_disc_large`.
   - `pixplot/api/spaces.py` : regard `"copie"` (`Copie (SSCD)`) ajouté dans `KINDS` et placé dans
     `NOT_KEPT` (évalué, non proposé par défaut dans l'Atlas ni le serveur MCP).
   - `pixplot/analysis/critique.py` : fiche critique `"copie"` ajoutée dans `CARDS`.
   - `pixplot/cli.py` : passage de `--weights` / `cache_dir` / `--input-size` à `embed` pour
     `sscd_*`, et activation temporaire de `Spaces.include_not_kept` dans `pairs bench` quand
     `--spaces` est fourni (restaurée dans un `finally`).
   - `tests/test_sscd.py` : deux tests sur le petit corpus synthétique (`atlas_env`), dont un sans
     PyTorch (CI GitHub) et un avec un vrai module TorchScript local.
   - `ARCHITECTURE.fr.md` et `ARCHITECTURE.md` : nouvelle section **§ 27**.
4. **Extraction sur WikiArt 81k** (`features/sscd_disc_large_20261119-184816`, journalisée dans
   `data/wikiart81k/sscd.log`) :
   - **80 716 œuvres**, **0 échec**, **4 min 41 s**, **274,9 images/s**, **926 MiB** VRAM (RX 7900
     GRE, FP16, lots de 64, 6 threads de lecture).

## 2. Mesures (`pixplot pairs bench`, 104 paires validées, 80 716 œuvres)

Rapport complet : `data/wikiart81k/bench/pairs_report_dinov3_vitb16_20261116-111508.json`.

### Catégorie cible : « Filiation attestée (copie, citation, modèle) » (9 paires, 18 recherches)

| Regard | R@10 | R@100 | Rang médian | Centile |
|---|---:|---:|---:|---:|
| **Sujet (SigLIP 2)** | **38,9 %** | **66,7 %** | **25** | **0,997** |
| **Forme (DINOv3)** | **38,9 %** | **66,7 %** | **26** | **0,993** |
| Copie (SSCD brut) | 33,3 % | 44,4 % | 216 | 0,902 |
| *Copie (SSCD centré, essai en mémoire)* | *33,3 %* | *50,0 %* | *108* | *0,904* |
| Touche (DINOv3 couche 6) | 16,7 % | 27,8 % | 578 | 0,902 |
| Couleur (CIELAB) | 0,0 % | 0,0 % | 17 656 | 0,557 |

### Détail des 9 paires `filiation` validées (rangs A→B, B→A)

- **Van Gogh / Millet (*Le Semeur*)** : SSCD **(1, 1)** · Forme (2, 1) · Sujet (1, 1)
- **Raphaël / Pérugin (*Mariage de la Vierge*)** : SSCD **(1, 1)** · Forme (2, 1) · Sujet (1, 1)
- **Manet / Titien (*Olympia* ← *Vénus d'Urbin*)** : SSCD **(6, 3)** [centré **(1, 3)**] · Forme (4, 23) · Sujet (4, 58)
- **Minimalisme (`63250 ↔ 64985`)** : SSCD (15, 58) · Forme (17, 29) · Touche (4, 3)
- **Manet / Goya (*Exécution de Maximilien* ← *Tres de mayo*)** : SSCD (110, 983) · Forme (2, 68) · Sujet (2, 12)
- **Manet / Giorgione-Titien (*Déjeuner sur l'herbe*)** : SSCD (323, 461) · Forme (8, 796) · Sujet (155, 130)
- **Monet / Manet (*Déjeuner sur l'herbe*)** : SSCD (803, 732) · Sujet (22, 3) · Forme (84, 435)
- **Picasso / El Greco (*Demoiselles d'Avignon*)** : SSCD (13 406, 21 382) · Sujet (671, 96) · Forme (418, 2 144)
- **Van Gogh / eau-forte de Rembrandt (*Résurrection de Lazare*)** : SSCD (60 102, 44 044) · Sujet (591, 1 814) · Forme (1 856, 3 645)

*(Hors banc : sur la paire proposée Rubens / Titien `64269 ↔ 67405`, SSCD donne (1, 1) comme Forme et Sujet.)*

### Autres catégories annotées validées (104 paires au total)

| Catégorie (n recherches) | SSCD R@10 | SSCD rang méd. | Meilleur regard actuel (R@10 · rang méd.) |
|---|---:|---:|---|
| Même sujet, composition différente (72) | 4,2 % | 27 374 | Sujet (37,5 % · 30) |
| Même composition, sujet différent (28) | 7,1 % | 13 736 | Forme (53,6 % · 8) |
| Artistes différents, facture comparable (32) | 0,0 % | 6 952 | Touche (31,2 % · 136) |
| Même palette, traditions différentes (52) | 0,0 % | 32 982 | Couleur (50,0 % · 10) |
| Même motif, époque différente (4) | 0,0 % | 5 612 | Sujet (50,0 % · 26) |
| Même artiste, facture différente (2) | 0,0 % | 53 312 | Couleur (100,0 % · 2) |

### Observation annexe (dédoublonnage perceptuel)

Sur un sondage aléatoire de 2 000 œuvres de WikiArt 81k, **52 œuvres (2,6 %)** ont une autre œuvre
à cosinus SSCD ≥ 0,75 (dont des quasi-doublons JPEG réencodés sous deux étiquettes différentes,
non détectés par le hachage SHA-256 d'`ingest`).

## 3. Tests

- Suite complète exécutée : `68 passed` (les 66 tests existants + 2 nouveaux tests dans
  `tests/test_sscd.py`).

## 4. Reste à faire (pour l'intégrateur)

- Relire et fusionner `gemini/sscd` dans `main` (via `nouvelle-tache.ps1 sscd -Agent gemini -Terminer`).
- Mettre à jour `docs/HANDOFF.md` et, si publication, le numéro de version et les CHANGELOG (hors
  périmètre de cette branche).

## 5. Décision pour l'utilisateur

**Recommandation : ne pas ajouter SSCD comme cinquième regard « copie » dans l'Atlas.**

- Sur les 9 paires `filiation` validées, SSCD est derrière Forme (DINOv3) et Sujet (SigLIP 2) en
  R@10 (33,3 % contre 38,9 %), en R@100 (44,4 % contre 66,7 %) et en rang médian (216 — ou 108
  centré — contre 26 et 25).
- Il ne fait mieux que sur une seule paire (*Olympia* ← *Vénus d'Urbin*, rangs 6 et 3 vs 4 et 23),
  tandis que Forme et Sujet retrouvent déjà les autres copies fidèles au rang 1–2 et gèrent bien
  mieux les réinterprétations libres, gravures ou fragments.
- Deux options s'offrent à vous :
  1. **(Recommandée) Garder l'état actuel** : SSCD reste dans `NOT_KEPT` (hors Atlas/MCP), code et
     vecteurs conservés pour de futurs bancs d'essai (par exemple si le corpus s'enrichit de gravures
     de reproduction fidèles) ou comme base d'une future commande de **dédoublonnage perceptuel**.
  2. **Exposer quand même le regard « copie » dans l'Atlas** : il suffit de retirer `"sscd"` de
     `NOT_KEPT` dans `pixplot/api/spaces.py`, puis de calculer son index FAISS (`pixplot index
     --encoder sscd_disc_large`).
