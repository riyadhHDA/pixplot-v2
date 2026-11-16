# Historique des versions

[English](CHANGELOG.md) · **Français**

**PixPlot v2** est le nom du projet : la deuxième génération de PixPlot, après celui du
Yale DHLab (2018). Ce n'est pas un numéro de version. Les versions du logiciel suivent le
[versionnage sémantique](https://semver.org/lang/fr/) : `0.MINEUR.CORRECTIF`.

- **0.x** : logiciel de recherche en construction ; une version mineure peut changer les
  commandes ou les formats de fichiers. La 1.0 viendra quand ils seront stables.
- **MINEUR** (0.9 → 0.10) : chaque nouvelle fonctionnalité.
- **CORRECTIF** (0.7.0 → 0.7.1) : corrections et documentation seules.

Chaque version est une étiquette git `vX.Y.Z` et une *release* GitHub. Le numéro est dans
`pyproject.toml` et `pixplot/__init__.py`, et s'affiche avec `pixplot --version`.

## 0.12.1 — 16/11/2026 · Relecture rapide des paires

- Relecture façon Anki (touche R dans l'Atlas) : une paire à la fois, en grand ; Entrée ou 1 à 7
  pour valider avec une sorte de ressemblance, R pour écarter, Espace pour passer, Z pour annuler.
- La file enchaîne les paires proposées puis des candidates tirées des désaccords entre regards ;
  les candidates écartées sont notées dans `bench/review_log.csv` et ne reviennent plus.
- API `/api/review/queue`, `/api/review`, `/api/review/undo`.

## 0.12.0 — 16/11/2026 · Désaccords entre regards, relecture des paires

- `pixplot disagreements` : pour chaque couple de regards, les paires très proches selon l'un et
  lointaines selon l'autre ; dans l'Atlas, bouton « Désaccords » (touche D).
- « À vérifier » : onglet « Paires de référence » pour valider ou rejeter les paires proposées.
- API `/api/disagreements` ; `/api/pairs` donne aussi les libellés des œuvres.

## 0.11.0 — 16/11/2026 · Groupes Leiden

- `pixplot communities` : groupes Leiden emboîtés (familles ⊃ groupes) pour chaque regard, sur le
  graphe des voisines ; nombre de groupes réglable (`--groups`, `--families`).
- Atlas : couleur par « Familles Leiden » ou « Groupes Leiden » de chaque regard ; API `/api/communities/{regard}`.
- Comparaison avec e-means sur WikiArt 81k (ARCHITECTURE § 15) : plus stable pour la forme, le sujet
  et la touche, meilleur accord avec les artistes pour la touche ; pas pour la couleur. Les groupes
  nommés restent ceux d'e-means pour l'instant.

## 0.10.2 — 16/11/2026 · Site du projet

- Site de présentation en anglais et en français (https://riyadhhda.github.io/pixplot-v2/), publié sur GitHub Pages par une
  GitHub Action à chaque modification de `site/` ; aperçu local : `bash scripts/build_site.sh`.

## 0.10.1 — 16/11/2026 · Feuille de route

- `ROADMAP.fr.md` / `ROADMAP.md` : les étapes 0.11 à 0.15 (groupes Leiden, désaccords entre regards,
  recherche d'une zone par des mots avec TIPSv2, noms Iconclass, composition), la condition de
  réussite de chacune, ce qui est écarté et les conditions de la 1.0.

## 0.10.0 — 16/11/2026 · Banc d'essai par paires

- `pixplot pairs` : mesure quel regard retrouve quelle *sorte* de ressemblance (même sujet,
  même composition, même main, même facture, même motif, même palette, filiation, témoin),
  par rang exact parmi tout le corpus (R@10, R@100, rang médian, centile).
- Paires annotées par l'historien (avec source et statut validée / proposée / rejetée) et
  paires tirées des métadonnées, toujours séparées.
- Atlas : bouton « Annoter » dans le comparateur, colonne « référence ».
- 11 premières paires proposées d'après Honour et Fleming et des filiations connues.
- `pixplot --version` ; version dans `/api/info` et le serveur MCP.

## 0.9.0 — 16/11/2026 · Vocabulaire des noms de groupes

- 21 sujets et 23 manières tirés du glossaire de Honour et Fleming, *The Visual Arts: A
  History* (Annonciations, Retables, clair-obscur, sfumato, grisaille, plein air…).

## 0.8.0 — 16/11/2026 · Une carte par regard, interface repensée

- `pixplot maps` : une carte UMAP par regard (sujet, couleur, touche).
- Vue géographique sur un fond de carte du monde embarqué.
- En-tête allégé, panneaux adaptés à l'écran, écran d'accueil, aide, raccourcis clavier.

## 0.7.1 — 16/11/2026 · Page du projet

- Bannière, captures, documentation en anglais et en français, crédits.

## 0.7.0 — 16/11/2026 · Quatre regards

- Espaces sujet (SigLIP 2), couleur (CIELAB) et touche (couches intermédiaires de DINOv3).
- Comparateur, carnet de recherche, chronologie et géographie, noms de groupes,
  étiquettes à vérifier, import IIIF (validé sur le Yale Center for British Art).

## 0.6.0 — 16/11/2026 · Audit et passage à l'échelle

- Audit à l'aveugle face aux étiquettes ; toutes les vignettes affichées sans scintillement.
- WikiArt complet : 80 716 œuvres en ≈ 1 h 21 sur un seul PC.

## 0.5.0 — 15/11/2026 · Serveur MCP et Research Pack

## 0.4.0 — 15/11/2026 · Recherche par détail et par texte (SigLIP 2)

## 0.3.0 — 15/11/2026 · API FastAPI et Atlas interactif (deck.gl)

## 0.2.0 — 15/11/2026 · Groupes e-means, HDBSCAN, carte UMAP

## 0.1.0 — 15/11/2026 · Ingestion, vecteurs, index FAISS, banc d'essai par étiquettes
