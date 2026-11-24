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

## Non publié

- **`pixplot sauvegarde`** : met à l'abri le travail fait à la main, qui ne se recalcule pas. Copie les paires
  relues dans `bench/` du dépôt (`<corpus>_pairs_travail.csv`, à commiter), le carnet sur demande (`--carnet`),
  et avec `--vers` le dossier de données vers un autre disque (l'essentiel, ou `--tout`) ; n'efface jamais rien
  et refuse de remplacer une copie plus longue que l'original.
- **Site redessiné** : une planche par cas d'usage (dix questions d'historien), chacune animée avec de vraies
  réponses de PixPlot sur WikiArt 81k (œuvres du domaine public, zones, squelettes et liens réels, caméra qui
  passe de l'une à l'autre), jouée une fois et désactivée si l'on a demandé moins de mouvement ; à l'ouverture,
  un échantillon de la vraie carte ; thèmes clair et sombre ; chiffres « artiste » mis à jour.
  `scripts/site_scenes.py` refait les données des démonstrations.
- **Pyramide de tuiles** (Gemini 4 Neon) : `pixplot tiles` (13 s sur processeur pour 81k) ; l'Atlas montre la vue d'ensemble en tuiles et ne charge les planches qu'au zoom : transfert à l'ouverture −91 %, mémoire de la carte graphique ÷ 42. Nouveau format de fichiers : `runs/tiles/` (FORMATS). (ARCHITECTURE § 44)
- **Wölfflin, linéaire / pictural** : préréglage mesuré dans la vue « Axes conceptuels », avec sa mise en garde (seul des cinq couples à séparer Renaissance et Baroque, AUC 0,74 ; avant 1800, l'axe suit le temps). Un axe peut réunir plusieurs phrases séparées par « | », aussi dans l'outil MCP `probe_concepts`. (ARCHITECTURE § 43)

## 0.22.0 — 24/11/2026 · Posture dans l'Atlas, notions du regard « forme », référence des commandes

- **« Pourquoi ? »** : quand moins de 4 zones se répondent, le comparateur le dit et explique pourquoi (ressemblance plus diffuse ; 31 % des paires du banc d'essai, 10 % des voisines proches). (ARCHITECTURE § 40, complément)
- **Site** : posture (avec la planche), notions apprises, doublons et filtres combinés ; feuille de route remise à jour jusqu'à la 1.0.
- **Notions du regard « forme »** : 2 048 notions apprises sur DINOv3, nommées avec Iconclass à travers SigLIP 2 (ce que montrent leurs œuvres) ; le panneau « Notions » de l'Atlas propose les deux regards, `explore_notions` prend `space`, `pixplot notions --nommer RUN`. (ARCHITECTURE § 42)
- **Regard « posture » dans l'Atlas, en essai** (Gemini 4 Neon, relu par Claude) : voisines exactes sur toutes les figures, avec le miroir ; squelettes dessinés dans la fiche et le comparateur ; `similar_artworks` accepte `space="posture"`. Séparé des quatre regards principaux et marqué « essai ». `communities` et `disagreements` le laissent de côté par défaut. (ARCHITECTURE § 41)
- **Référence des commandes** (`docs/COMMANDS.fr.md` / `.md`) : les 41 commandes de `pixplot`, rangées par étape de travail ; un test refuse une commande non décrite ou une description sans commande (condition de la 1.0).

## 0.21.0 — 23/11/2026 · Posture, notions apprises, « Pourquoi ? » mis à l'épreuve et réparé, fiche de données

- **Regard « posture »** (Gemini 4 Neon) : squelettes des figures (RT-DETRv2 + ViTPose, Apache 2.0),
  comparés avec leur image en miroir, figures trouvées dans 48 % des œuvres. Ne fait pas mieux que la
  forme sur les paires validées, mais retrouve des gestes repris d'un artiste à l'autre (*Le Semeur*
  de Millet et de Van Gogh). Pas encore proposé dans l'Atlas : **37 paires « même geste » à relire**
  (touche R ; « même geste » = touche 7, « filiation » passe à la touche 8). ARCHITECTURE § 35.
- **Notions apprises** : `pixplot notions` décompose les vecteurs du regard « sujet » en 1 792
  notions ; 959 ne correspondent à aucune étiquette et sont surtout des objets et des motifs
  (arc-en-ciel, crâne, escalier…). Deux surprises : le « chef-d'œuvre célèbre » et le « tableau
  photographié avec son cadre ». Dans l'Atlas : panneau « Notions » (touche O) et onglet
  « Cadres (n° 88) » dans « À vérifier ». ARCHITECTURE § 37.
- **Recherche par phrase mesurée** avec les descriptions de MMArt (`pixplot textbench`) : on retrouve
  une œuvre par ce qu'elle montre (rang médian 13), presque jamais par la façon dont elle est peinte
  (661) ni par son contexte historique. ARCHITECTURE § 36.
- **Intervalles de confiance du banc par paires** (`pixplot pairs ci`) : seuls deux résultats sont
  sûrs (la forme pour la composition, la couleur pour la palette) ; un regard n'est dit « meilleur »
  que si l'écart reste net malgré le hasard du tirage des paires. ARCHITECTURE § 38.
- **Émotion à genre égal** : environ deux tiers de l'effet survivent au contrôle du genre
  (ARCHITECTURE § 34).
- **Outil MCP `explore_notions`** (20 outils) : un assistant peut chercher les notions par nom et voir leurs œuvres.
- Correctif : les fiches des regards (panneau Corpus, MCP) disaient que le sujet bat la forme sur « même composition » ; d'après le § 38 c'est l'inverse, et la note sur les artistes manquants tient compte de MMArt (7 % restent inconnus).
- **Le bouton « Pourquoi ? » mis à l'épreuve** (Gemini 4 Neon, `pixplot whytest`) : cacher les zones qu'il montre ne fait pas plus baisser la ressemblance que cacher des zones au hasard ; il choisit surtout des coins (63 %). ARCHITECTURE § 39.
- **« Pourquoi ? » réparé** (Gemini 4 Neon) : chaque zone est comparée après avoir retiré sa « signature de position », et les zones sont classées par leur poids dans la ressemblance globale. Il passe désormais le test du § 39 (4,2 fois le hasard) ; sur *Le Semeur*, il montre le semeur au lieu des coins du ciel. Une phrase sous les zones rappelle que c'est une piste, pas une explication. ARCHITECTURE § 40.
- **Fiche de données du corpus** (d'après Gebru et al., *Datasheets for Datasets*, 2021) : provenance des images et des étiquettes, droits connus, ce qui manque, ce que PixPlot a repéré (doublons, étiquettes douteuses, cadres), usages à éviter. Calculée, jamais écrite à la main ; jointe à chaque Research Pack (`datasheet.md`) et par `pixplot corpus --datasheet`.
- **Formats de fichiers documentés** (`docs/FORMATS.fr.md` / `.md`) : catalogue, vignettes, runs, paires, carnet, Research Pack ; un test vérifie que le code écrit bien ce qui est décrit (condition de la 1.0).
- **Documentation au même niveau dans les deux langues** : tableaux des §§ 14, 17 et 19 rétablis en anglais, installation GPU française mise à jour, arborescence d'ARCHITECTURE refaite ; un test vérifie désormais que chaque section a, dans les deux langues, autant de blocs de code et de tableaux (condition de la 1.0).
- Correctif : un calcul de notions ne fait plus planter `pixplot serve`.

## 0.20.0 — 19/11/2026 · Titres, dates, artistes et émotions pour WikiArt ; ordre de la matière

- **WikiArt retrouve ses titres, ses dates et ses artistes** : `pixplot wikiart-noms` rattache nos
  œuvres à leur nom de fichier d'origine en comparant les images de **MMArt** (CC BY 4.0) à nos
  empreintes. 70 902 œuvres rattachées (vérifiées à l'œil, aucun désaccord avec les étiquettes
  existantes) : titres, **dates pour 56 794 œuvres (1401–2012) : la vue chronologique s'allume**, et
  l'artiste de 35 185 œuvres « Unknown Artist » (129 → 1 090 artistes). ARCHITECTURE § 34.
- **Émotions d'ArtEmis** (usage de recherche non commercial, gardé en local) : émotion dominante de
  55 120 œuvres, dans la fiche, les couleurs et les filtres. Les regards captent un peu l'émotion
  (1,7 fois le hasard), surtout par le sujet, à peine par la couleur.
- **Ordre et désordre de la matière** (Sigaki, Perc et Ribeiro, PNAS 2018) : `pixplot ordre`,
  couleurs « Désordre » et « Complexité » de la carte, ligne dans les mesures visuelles. Du
  Minimalism (le plus ordonné) au Pointillism (le plus désordonné) ; dans le temps, surfaces lisses
  vers 1600–1850, désordre maximal vers 1900, retour à l'ordre après 1940. ARCHITECTURE § 33.
- **Deux modèles évalués et non retenus**, par Gemini 4 Neon : PE-Core contre SigLIP 2 (moins bon en
  recherche par phrase en français, 81/100 contre 97/100) et CSD contre la touche (meilleur sur le
  style, mais entraîné sur des données qui contiennent probablement WikiArt). ARCHITECTURE §§ 31–32.
- **Recalculs** après l'ajout des artistes : étiquettes d'artiste à vérifier (506 → 1 206), mentions
  « métadonnées » des groupes (noms relus inchangés), banc d'essai « artiste » sur 1 090 artistes.
- Documentation : cas d'usage en tête du README, règle de P@1 écrite (§ 30), feuille de route à jour.

## 0.19.0 — 19/11/2026 · Filtres combinés, doublons, trois modèles mis à l'épreuve

- **Filtres combinés** dans l'Atlas (bouton « Filtrer », touche F), d'après *Collection Space
  Navigator* (Ohm et al., 2023) : artiste, style, genre, groupe, atypicité (et dates si le corpus en
  a). Chaque valeur affiche le nombre d'œuvres qu'elle donnerait avec les autres critères ; la
  sélection part au carnet ou dans un Research Pack.
- **Doublons et variantes** : `pixplot doublons`, onglet « Doublons » dans « À vérifier », outil MCP
  `find_duplicates` (19 outils). Sur WikiArt 81k : 839 paires « même image », dont 702 rangées sous
  deux styles différents, et 785 variantes (répliques, séries, états, copies). ARCHITECTURE § 29.
- **Trois modèles évalués et non retenus**, résultats publiés quand même :
  - SSCD, détection de copies (§ 27, par Gemini 4 Neon) : derrière Forme et Sujet sur les filiations,
    mais il sert à trouver les doublons ;
  - Depth Anything V2, composition par la profondeur (§ 28, par Gemini 4 Neon) : rang médian 13 754
    contre 8 pour Forme ;
  - LocalMAP contre UMAP (§ 29) : +1,5 point sur les étiquettes des voisines, mais une carte coupée en
    îlots et plus entassée. Proposée comme carte d'essai (`pixplot maps --localmap`, « pas mieux »).
- **Fin de l'audit de Gemini 4 Argon** : réponses en retard ignorées dans les panneaux, erreurs
  lisibles, notes du carnet non enregistrées signalées, relecture rapide et vignettes HD plus sûres ;
  reprise de `pixplot zones`, petits groupes Leiden rattachés entiers, cadres des zones alignés sur
  les patchs, vecteurs float16 renormalisés, mémoire bornée au-delà de 100 000 œuvres. Groupes Leiden
  publiés inchangés (mesuré). Reste à décider : le calcul de P@1 dans `pixplot bench`.

## 0.18.0 — 19/11/2026 · Nommer les groupes avec Iconclass

Étape 0.14 de la feuille de route.

- Chaque groupe reçoit aussi des notions d'**Iconclass**, la classification iconographique des musées
  (CC0), avec leur code (« 47D31 moulin à vent ») en lien vers iconclass.org et un degré de confiance
  (sûr / possible). Commande `pixplot iconclass [--fetch]`, panneau Groupes de l'Atlas, champ `iconclass`
  de l'API, outils MCP `corpus_overview` et `get_group`.
- **Relu par l'historien** sur 83 groupes : Iconclass jugé plus juste 39 fois, le nom actuel 24 fois
  (17 équivalents, 3 tous deux faux). Les deux noms restent affichés ensemble. ARCHITECTURE § 23 ; la
  relecture est versionnée dans `bench/wikiart81k_iconclass_review.csv`.

## 0.17.0 — 19/11/2026 · Axes conceptuels, mesures visuelles, principes de lecture

Travail de Gemini 4 Neon (Antigravity), relu et vérifié par Claude ; trois lectures intégrées
(ARCHITECTURE § 26).

- **Axes conceptuels** (L. Impett et F. Offert, *Visual Resources*, 2024) : nouvelle vue de la carte,
  chaque œuvre placée selon sa proximité avec deux mots (« sacré » / « profane », « mer » / « montagne »…) ;
  les œuvres qui s'écartent de la diagonale en ressortent. API `/api/layout/concepts`, outil MCP
  `probe_concepts`.
- **Mesures visuelles sans modèle** (D. G. Stork, *Pixels & Paintings*, 2024) : barycentre de la
  lumière et de la saturation, symétrie gauche-droite, dynamique tonale, entropie chromatique et
  première coupe de la composition, dans la fiche d'œuvre. API `/api/artwork/{id}/measures`, outil MCP
  `measure_artwork` (18 outils).
- **Principes de lecture** (J.-L. Giavitto et P. Saint-Germier dir., *L'art au temps de l'IA*,
  Centre Pompidou, 2025) dans le panneau Corpus et les consignes du serveur MCP.
- README, feuille de route, documentation MCP et pages du site réécrits sur un ton plus direct.

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
