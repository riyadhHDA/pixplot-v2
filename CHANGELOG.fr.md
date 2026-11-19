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

## 0.16.3 — 19/11/2026 · Corrections d'après trois audits de Gemini 4 Argon

Trois audits du code par Antigravity (Gemini 4 Argon, en lecture seule) ; chaque point vérifié avant
correction.

- **Interface** : Ctrl+R en relecture rapide ne rejette plus la paire affichée ; un seul niveau de
  vignettes HD chargé à la fois (256 Mo de mémoire graphique au lieu de 768) ; couleurs calculées une
  fois ; chronologie possible au-delà de ~65 000 dates ; clés HTML échappées ; recherches périmées
  ignorées ; « Pourquoi ? » sans superposition ; images libérées.
- **Sécurité** : l'Atlas refuse les autres noms d'hôte (DNS rebinding) et les écritures venues d'autres
  sites ; le relais Antigravity n'envoie que des fichiers du projet.
- **Calculs** : reprise d'un calcul de vecteurs sûre (marques écrites après les vecteurs, centrage jamais
  refait) ; **désaccords jugés depuis la bonne œuvre** (recalculés sur WikiArt 81k) ; noms de groupes
  jamais tirés d'un calcul partiel ; petits corpus.

## 0.16.2 — 19/11/2026 · Antigravity sous Windows, en lecture seule

- `pixplot antigravity-mcp` : un second avis d'Antigravity (Google, Gemini) depuis Claude, par l'outil MCP
  `ask_antigravity`, en lecture seule (`--mode plan --sandbox`) ; `agy.exe` trouvé aussi après une
  installation par winget. Antigravity accède à PixPlot par `.agents/mcp_config.json` (docs/MCP).
- Compétence d'accessibilité (WCAG 2.2) partagée par tous les assistants dans `.agents/skills/`.
- « Pourquoi ? » corrigé d'après la relecture d'Antigravity : ressemblance moyenne sans la paire
  elle-même, plus d'avertissement pour les œuvres non carrées.

## 0.16.1 — 19/11/2026 · Outil MCP « pourquoi ? » et guide de l'historien

- Serveur MCP : outil `why_similar`, une planche des deux œuvres où les zones qui se répondent portent le
  même numéro, avec leurs cosinus (16 outils).
- Site : [Guide de l'historien de l'art](https://riyadhhda.github.io/pixplot-v2/fr/guide/), en français et en
  anglais : lire une proximité, trois parcours (filiation, étiquette, motif), travailler avec un
  assistant, citer, limites connues.

## 0.16.0 — 19/11/2026 · Pourquoi ces deux œuvres se ressemblent ?

- Comparateur : bouton « Pourquoi ? » sur chaque paire. Les zones qui se répondent le plus (cases
  4 × 4, regard forme) sont dessinées sur les deux images, avec le même numéro et une légende chiffrée.
- Correspondances mutuelles, classées par ce qui les distingue de la ressemblance moyenne ; cases
  hors de l'œuvre exclues. Calcul à la demande, en quelques millisecondes. API `/api/correspond`.
- Exemple : Raphaël, *Mariage de la Vierge*, et Pérugin, *Remise des clés* : le temple et les groupes
  de personnages se répondent. ARCHITECTURE § 25.

## 0.15.1 — 19/11/2026 · Tests sur GitHub, Atlas en modules, projet citable

- Tests automatiques sur GitHub à chaque push (toutes les branches) et sur les pull requests, sous
  Linux et Windows, sans GPU (`.github/workflows/tests.yml`).
- L'Atlas (`web/atlas.js`, 1 950 lignes) découpé en 8 scripts chargés dans l'ordre (`atlas-base.js`
  … `atlas-ui.js`, voir `web/README.md`), sans changement de comportement : plusieurs assistants
  peuvent y travailler sans se gêner.
- Projet citable : `CITATION.cff` (bouton « Cite this repository ») et archivage Zenodo avec DOI à
  chaque release (`.zenodo.json`).

## 0.15.0 — 18/11/2026 · La composition : PE-Spatial évalué, non retenu

- `pixplot composition` : banc d'essai sur les paires validées (regards existants, PE-Spatial,
  dispositions 4 × 4 case à case, variantes « œuvre seule » et « cases communes »).
- Encodeur PE-Spatial B/16 (Meta, Apache 2.0, par `timm`) ; vecteurs pour WikiArt 81k en 20 min.
- Résultat : sur les paires « même composition », DINOv3 reste le meilleur (rang médian 8 ;
  PE-Spatial 286 au mieux). PE-Spatial n'est pas retenu : vecteurs gardés pour les bancs d'essai,
  masqués dans l'Atlas et le MCP. Code relu par Codex. ARCHITECTURE § 24.
- Travail à plusieurs assistants : `AGENTS.md` (consignes communes à Codex, Gemini, Claude),
  `docs/HANDOFF.md` (passation), `scripts/nouvelle-tache.ps1` (une copie de travail par assistant).
- La 0.14 (noms Iconclass) attend sa relecture et sortira ensuite.

## 0.13.5 — 17/11/2026 · Images : ordre stable et chargement par lots

- Correction : selon le zoom, des vignettes qui se chevauchent passaient l'une devant l'autre (la haute
  définition ne couvrait que le centre de l'écran). Chaque niveau couvre désormais toutes les vignettes
  visibles (textures de 8 192 px si la carte graphique le permet), dans le même ordre que les planches.
- Vignettes par lots : `/api/thumbs/{taille}?ids=…` en renvoie jusqu'à 48 en une requête (le navigateur
  n'ouvre que 6 connexions à la fois) ; deux *workers* les décodent et les mettent à la taille de leur
  case hors du fil principal.
- WikiArt 81k, six zooms : 3 053 vignettes en 1,2 s au lieu de 6,7 s ; dans des zones jamais visitées,
  environ 925 vignettes par seconde au lieu de 450 ; aucune image de plus de 10 ms.

## 0.13.4 — 17/11/2026 · Affichage des images plus rapide

- Atlas : les vignettes en haute définition passent par trois textures de taille fixe (4 096 px), gérées
  par l'Atlas, au lieu d'une texture qui grandissait sans limite à chaque déplacement (cases noires,
  ralentissements de plus en plus forts).
- Chargement du centre de l'écran vers les bords, 8 images à la fois ; celles qui ne sont plus à l'écran
  ne sont pas téléchargées ; la petite vignette reste visible tant que la grande n'est pas arrivée.
- Haute définition dès 34 px à l'écran (au lieu de 72) : plus d'étape floue. Sur WikiArt 81k, zoom
  moyen : 489 vignettes en environ 2 s ; de près, moins d'une demi-seconde.

## 0.13.3 — 17/11/2026 · Chercher une zone avec des mots

- `pixplot zones` : chaque œuvre découpée en 20 zones (grilles 2×2 et 4×4) passées dans SigLIP 2,
  extraction reprenable, puis index compressé avec reclassement exact.
- Atlas : mode de recherche « Zone décrite » (« une auréole », « un crâne ») ; API `/api/search/zones` ;
  outil MCP `search_zones` (15 outils).
- WikiArt 81k : 1 614 320 zones en 6 h 21 ; une recherche en 0,5 s (ARCHITECTURE § 22).
- Correction : les runs de zones ne sont plus pris pour des vecteurs d'œuvres entières.

## 0.13.2 — 17/11/2026 · Lieux typés et datés

- Plusieurs lieux par œuvre, chacun avec un type (création, exposition, conservation, lieu représenté,
  naissance / résidence / mort de l'artiste), une date et une source : `pixplot import-places`,
  `pixplot places --derive` (déduits des métadonnées), répertoire de villes et d'institutions embarqué.
- Vue Géographie : choix du type de lieu, circulations entre les lieux d'une œuvre, curseur de temps,
  note critique. API `/api/places`.
- D'après B. Joyeux-Prunel, « ARTL@S » (2012) : ARCHITECTURE § 21.

## 0.13.1 — 17/11/2026 · Couche critique

- Une fiche par regard (modèle, données d'entraînement, ce qu'il voit et ne voit pas, biais, résultats)
  dans l'Atlas (bouton « Corpus », touche I), l'API et le serveur MCP.
- `pixplot corpus` et `/api/corpus` : bilan du corpus (couverture et source des étiquettes, concentration
  des artistes, styles non occidentaux, dates, lieux).
- Étiquettes WikiArt signalées comme bénévoles, à vérifier ; consigne de sécurité du serveur MCP
  (les métadonnées sont des données, jamais des consignes).
- D'après A. Wasielewski, *Computational Formalism*, et T. Arnold et L. Tilton, *Distant Viewing*
  (ARCHITECTURE § 20).

## 0.13.0 — 16/11/2026 · Chercher une zone avec des mots : TIPSv2 évalué

- `pixplot zonebench` : banc d'essai sur RichArt (709 tableaux, 1 243 objets décrits par les
  catalogues de musées) — retrouver la zone dans le corpus et la pointer dans son tableau.
- Encodeurs `tipsv2_b14` et `tipsv2_so400m14` (Google DeepMind, Apache 2.0), gardés pour la
  reproductibilité.
- Résultat (ARCHITECTURE § 19) : SigLIP 2 sur des zones découpées bat TIPSv2 (28 % contre 20 % en
  première position) ; TIPSv2 n'est pas intégré à l'Atlas. Suite : un index de zones SigLIP 2.

## 0.12.2 — 16/11/2026 · Premier banc d'essai sur 104 paires validées

- 104 paires validées par l'historien, versionnées dans `bench/wikiart81k_pairs.csv` (avec les
  étiquettes des œuvres) et le journal de relecture.
- Résultats (ARCHITECTURE § 18), en ne mesurant que les regards qui n'ont pas servi à choisir la
  paire : chaque regard gagne sur la ressemblance qu'il doit voir, sauf la composition (le sujet
  l'emporte) ; Leiden range plus de paires dans un même groupe qu'e-means (forme 24 → 33 %).

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
