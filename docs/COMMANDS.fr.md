# Les commandes de PixPlot

[English](COMMANDS.md) · **Français**

Toutes les commandes s'écrivent `pixplot [--data DOSSIER] <commande> [options]`. Ce document les
range par étape de travail ; `pixplot <commande> -h` donne le détail de chaque option. Un test
(`tests/test_commands_doc.py`) vérifie qu'aucune commande ne manque ici et qu'aucune commande
décrite ici n'a disparu.

## Avant de commencer

`--data` désigne le dossier du corpus (sinon la variable `PIXPLOT_DATA`, sinon `./data`). Toutes
les commandes écrivent leurs résultats dans ce dossier, jamais ailleurs.

```bash
pixplot doctor                                   # l'installation et la carte graphique
pixplot --data data/wikiart81k status            # ce que contient le corpus, et ses calculs
pixplot --data data/wikiart81k serve --open      # l'Atlas dans le navigateur
```

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot doctor` | vérifie l'installation : Python, carte graphique, bibliothèques | — |
| `pixplot status` | état du catalogue et liste des calculs (*runs*) | — |
| `pixplot runs` | même chose que `status` | — |
| `pixplot sauvegarde` | met à l'abri le travail fait à la main : copie les paires relues dans `bench/` du dépôt (à commiter) et, avec `--vers`, le dossier de données vers un autre disque ; n'efface jamais rien | `--vers`, `--tout`, `--carnet`, `--force` |
| `pixplot --version` | numéro de version | — |

## Faire entrer des œuvres

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot ingest` | catalogue un ou plusieurs dossiers d'images et fait les vignettes | `--workers`, `--limit` |
| `pixplot import-metadata` | importe artiste, date, style… depuis un CSV (colonne `path`) | `--source` |
| `pixplot import-iiif` | télécharge une collection de musée par ses manifestes IIIF | `--out`, `--max-size`, `--all-canvases`, `--delay` |
| `pixplot wikiart-noms` | titres et dates (MMArt), émotions (ArtEmis), artistes manquants, par empreinte d'image | `--mmart`, `--artemis`, `--artistes` |
| `pixplot import-places` | lieux typés et datés depuis un CSV | `--source` |
| `pixplot places` | bilan des lieux ; `--derive` les déduit des métadonnées | `--derive` |

## Calculer les regards

Les calculs longs reprennent là où ils se sont arrêtés et écrivent un journal dans le dossier du
corpus.

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot embed` | calcule les vecteurs d'un regard (un encodeur = un regard) | `--encoder`, `--batch-size`, `--no-resume` |
| `pixplot index` | construit l'index FAISS d'un run de vecteurs | `--kind flat\|hnsw`, `--regions` |
| `pixplot zones` | 20 zones par œuvre vues par SigLIP 2, puis leur index (chercher un détail avec des mots) | `--batch`, `--index-only` |

## Analyser

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot analyze` | groupes (e-means), carte UMAP, voisinages, œuvres atypiques : crée un run d'analyse | `--clusters`, `--no-map` |
| `pixplot maps` | une carte par regard ; `--localmap` ajoute la carte d'essai LocalMAP | `--spaces`, `--force`, `--localmap` |
| `pixplot tiles` | pyramide de tuiles précalculées pour la carte principale de l'Atlas (CPU, reprenable) | `--max-level`, `--tile-size`, `--format`, `--no-resume` |
| `pixplot communities` | groupes Leiden emboîtés (familles ⊃ groupes), un jeu par regard | `--spaces`, `--groups`, `--families` |
| `pixplot name-groups` | propose un nom à chaque groupe (SigLIP 2 et vocabulaire) | `--show` |
| `pixplot iconclass` | propose des noms de groupes tirés d'Iconclass | `--fetch` |
| `pixplot disagreements` | paires qu'un regard rapproche et qu'un autre sépare | `--spaces`, `--rank`, `--centile` |
| `pixplot suspects` | étiquettes probablement erronées (toutes les voisines disent autre chose) | `--keys`, `--space` |
| `pixplot doublons` | œuvres entrées deux fois, répliques et variantes (SSCD) | `--same`, `--variant` |
| `pixplot ordre` | ordre et désordre de la matière (entropie, complexité), sans GPU | `--workers` |
| `pixplot dater` | date chaque œuvre d'après ses voisines datées (celles de son artiste s'il en a assez), avec une fourchette à 80 % calibrée ; mesure chaque regard face à deux témoins ; sans GPU | `--space`, `--spaces`, `-k` |
| `pixplot notions` | notions apprises par un regard (auto-encodeur parcimonieux) ; `--nommer` nomme un run existant à travers SigLIP 2 | `--space sujet\|forme`, `--nommer` |
| `pixplot corpus` | bilan critique du corpus ; `--datasheet` écrit sa fiche de données | `--datasheet` |

## Chercher et exporter

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot similar` | œuvres les plus proches d'une œuvre (numéro ou chemin d'image) | `-k`, `--html` |
| `pixplot search-text` | œuvres qui répondent à une description, en français ou en anglais | `-k`, `--encoder` |
| `pixplot pack` | Research Pack (.zip) : œuvres, métadonnées, fiche de données, pour un LLM ou un collègue | `--ids`, `--cluster`, `--similar`, `--text`, `--detail` |

## Ouvrir l'Atlas et les serveurs

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot serve` | l'Atlas, carte interactive, seulement depuis ce PC par défaut | `--port`, `--open`, `--analysis` |
| `pixplot mcp` | serveur MCP : donne accès au corpus à Claude ou à un autre LLM (voir [MCP](MCP.fr.md)) | `--analysis` |
| `pixplot antigravity-mcp` | serveur MCP : second avis d'Antigravity, en lecture seule | — |

## Bancs d'essai

Chaque banc écrit un rapport daté dans `<données>/bench/`. Une proximité calculée est une piste,
pas une preuve : les bancs mesurent ce que chaque regard retrouve, pas ce qui est vrai.

| Commande | Ce qu'elle fait | Options utiles |
|---|---|---|
| `pixplot bench` | compare des runs sur les étiquettes (artiste, style, genre) et les paires connues | `-k`, `--keys` |
| `pixplot pairs types` | les types de ressemblance (même composition, filiation, même geste…) | — |
| `pixplot pairs add` | ajoute une paire d'œuvres validée à la main | `--type`, `--source`, `--note` |
| `pixplot pairs list` | les paires enregistrées | `--status` |
| `pixplot pairs generate` | propose des paires à relire, par type | `-n`, `--seed` |
| `pixplot pairs bench` | quel regard retrouve quelle ressemblance, sur les paires validées | `--spaces`, `--proposed` |
| `pixplot pairs ci` | intervalles de confiance du dernier `pairs bench` (bootstrap) | `--boot`, `--all-origins` |
| `pixplot composition` | banc « composition » : regards, PE-Spatial, dispositions 4 × 4 | — |
| `pixplot zonebench` | chercher une zone avec des mots : banc RichArt | `--encoders` |
| `pixplot textbench` | recherche par phrase, sur les descriptions MMArt | `-n`, `--encoders` |
| `pixplot whytest` | met à l'épreuve le bouton « Pourquoi ? » par occultation | `-k`, `--random` |
| `pixplot audit` | audit à l'aveugle : où les groupes contredisent les étiquettes | `--keys`, `--min-count` |

## Stabilité

Avant la 1.0, une commande ou une option peut encore changer ; chaque changement est noté dans le
[CHANGELOG](../CHANGELOG.fr.md). À partir de la 1.0, les commandes de ce document et les formats de
[FORMATS](FORMATS.fr.md) ne changeront plus sans une nouvelle version majeure.
