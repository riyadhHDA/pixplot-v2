# Passation — où en est le travail

À lire en début de session, à mettre à jour en fin de session (voir [AGENTS.md](../AGENTS.md)).
Ce fichier remplace la mémoire propre à chaque assistant : il doit suffire à reprendre le travail
avec n'importe quel modèle.

*Dernière mise à jour : 24/11/2026 (Wölfflin, tuiles de Neon fusionnées).*

## Version publiée

**0.22.0** (24/11/2026) : regard « posture » en essai dans l'Atlas et le MCP (§ 41), notions du regard « forme » nommées à travers SigLIP 2 (§ 42), « Pourquoi ? » qui dit quand moins de 4 zones se répondent (§ 40, complément), référence des commandes, site à jour. Détail dans « En cours » plus bas (« Après la 0.21.0 », publié).
**0.21.0** (23/11/2026) : regard « posture » évalué (§ 35), banc d'essai texte (§ 36), notions apprises et leur panneau (§ 37), intervalles de confiance (§ 38), « Pourquoi ? » mis à l'épreuve puis réparé (§§ 39–40), fiche de données, formats et parité FR / EN vérifiés par des tests, outil MCP `explore_notions` (20 outils). Détail dans « En cours » plus bas (publié).
**0.20.0** (19/11/2026) : titres, dates, artistes (MMArt) et émotions (ArtEmis) pour WikiArt, vue
chronologique ; ordre de la matière ; PE-Core et CSD évalués, non retenus (ARCHITECTURE §§ 30 à 34).
Détail dans « Fait depuis 0.19.0 » plus bas.
**0.19.0** (19/11/2026) : filtres combinés, doublons (SSCD, 19 outils MCP), fin de l'audit d'Argon,
SSCD / Depth Anything V2 / LocalMAP évalués et non retenus (ARCHITECTURE §§ 27 à 29). Détail dans
« Fait depuis 0.18.0 » plus bas.
**0.18.0** (19/11/2026) : noms Iconclass (étape 0.14), relus par l'utilisateur sur 83 groupes :
Iconclass plus juste 39 fois, nom actuel 24 fois (ARCHITECTURE § 23, `bench/wikiart81k_iconclass_review.csv`).
**0.17.0** : travail de Gemini 4 Neon, relu par Claude (65 tests, Atlas vérifié ;
axes conceptuels : 42 s au premier appel, le temps de charger SigLIP 2, puis ~1,2 s dans le navigateur) —
intégration de trois lectures (`C:\Users\Riyadh\Downloads\Livre`, restées hors dépôt) — voir
`ARCHITECTURE.fr.md` § 26 :
- **Axes conceptuels 2D** (L. Impett & F. Offert, *Visual Resources*, 2024) : `/api/layout/concepts`,
  vue « Axes conceptuels (2 mots) » dans l'Atlas (`web/atlas-dispositions.js`, `web/index.html`),
  outil MCP `probe_concepts` ; mesuré à 582–592 ms à chaud sur WikiArt 81k.
- **Mesures visuelles sans GPU** (D. G. Stork, *Pixels & Paintings*, Wiley, 2024) :
  `pixplot/analysis/connoisseur.py`, `/api/artwork/{id}/measures`, bloc pliable « Mesures visuelles »
  dans la fiche d'œuvre (`web/atlas-panneaux.js`), outil MCP `measure_artwork` (18 outils au total) ;
  mesuré à 14,5 ms/œuvre sur 100 vignettes 256 px (grille fixe 4 × 4 × 4, H de 0,07 à 3,52 bits).
- **Couche critique enrichie** (J.-L. Giavitto & P. Saint-Germier dir., *L'art au temps de l'IA*,
  Centre Pompidou, 2025) : `critique.PRINCIPLES`, panneau Corpus, consignes MCP, README / ROADMAP /
  MCP / Guide de l'historien (FR + EN). 65 tests passent.
- **Réécriture éditoriale** : `README.fr.md` / `README.md`, `ROADMAP.fr.md` /
  `ROADMAP.md`, `docs/MCP.fr.md` / `docs/MCP.md` et les 4 pages du site (`site/index.html`,
  `site/fr/index.html`, `site/guide/index.html`, `site/fr/guide/index.html`) réécrites sur un ton
  plus direct et naturel, et synchronisées avec l'état réel (18 outils MCP, § 26).
**0.16.3** : corrections d'après trois audits de Gemini 4 Argon (voir plus bas).
**0.16.2** : Antigravity sous Windows (`pixplot antigravity-mcp`, second avis en
lecture seule ; PixPlot dans Antigravity par `.agents/mcp_config.json`), compétence d'accessibilité,
« Pourquoi ? » corrigé. **0.16.1** : outil MCP `why_similar` (16 outils) et guide de l'historien de l'art sur
le site. **0.16.0** : « Pourquoi ces deux œuvres se ressemblent ? » dans le comparateur (ARCHITECTURE § 25). Avant : **0.15.1**, tests sur GitHub (Linux et Windows), Atlas découpé en 8 scripts, projet
citable (CITATION.cff, DOI Zenodo à chaque release). Avant : 0.15.0, la composition (ARCHITECTURE § 24). Historique
complet dans le [CHANGELOG](../CHANGELOG.fr.md), étapes suivantes dans la [ROADMAP](../ROADMAP.fr.md).

## Audits de Gemini 4 Argon (19/11/2026, publiés en 0.16.3)

Trois audits par Antigravity (modèle Gemini 4 Argon High, en lecture seule) ; textes complets dans
`data/audit_argon_{1,2,3}.md` (non versionnés). Chaque point a été vérifié dans le code avant d'être
corrigé ; 63 tests passent, Atlas vérifié.

- **Corrigé, interface** : chronologie au-delà de ~65 000 dates (Math.min(...)), couleurs recalculées
  à chaque dessin, trois niveaux HD chargés à la fois (768 Mo), clés HTML non échappées, **Ctrl+R en
  relecture rapide qui rejetait la paire**, réponses de recherche périmées, « Pourquoi ? » superposé,
  ImageBitmap non fermés, cadre de détail tracé avant le chargement, petites fautes.
- **Corrigé, sécurité** : l'API refuse les noms d'hôte autres que cette machine (DNS rebinding) et les
  écritures venues d'autres sites ; le relais Antigravity n'envoie que des fichiers du projet (pas
  `data/`), plus d'`agy.cmd` ; le relais accepte jusqu'à 15 min et renvoie ses erreurs en clair.
- **Corrigé, calculs** : marques « fait » écrites après les vecteurs ; centrage (couleur, touche) jamais
  refait à une reprise ; **désaccords jugés depuis la bonne œuvre** (le centile n'est pas symétrique) ;
  noms de groupes jamais tirés d'un calcul SigLIP 2 partiel ; voisines -1 de FAISS sur petit corpus ;
  UMAP sur petit corpus ; `-k` < `--rank` ; échantillon de la PCA des zones ; `parent` à None.
- **Désaccords recalculés** sur WikiArt 81k après la correction de sens : « proche en forme, loin en
  sujet » passe de 287 à 77 paires, « proche en sujet, loin en forme » de 85 à 39 (beaucoup d'anciennes
  paires étaient jugées depuis la mauvaise œuvre) ; les autres couples gardent 300 paires, dont 41 à
  77 % en commun avec l'ancien calcul.
- **Points restants, traités ensuite** :
  - interface : **corrigé le 19/11/2026, publié en 0.19.0** (I-2, I-4, M-1, M-2, M-3, M-5 : numéro par
    chargement du panneau et des vues, `httpError`/`sendJSON` dans `atlas-base.js`, carnet qui signale
    une note non enregistrée, file de relecture rechargée une seule fois, lots HD relancés 2 fois) ;
  - calculs : **corrigé le 19/11/2026, publié en 0.19.0** (4, 7, 12, 13, 14 ; tests dans
    `tests/test_audit_calc.py`) : reprise de `pixplot zones` (dernier run inachevé compatible, images
    illisibles laissées hors de l'index et retentées) ; `merge_small` rattache chaque petite communauté
    entière, dichotomie de Leiden qui reconnaît un graphe émietté ; cadres alignés sur le découpage
    réel des patchs, recherche de détail sur k × 20 zones filtrée sur l'analyse ; renormalisation
    après float16 (index FAISS, `FeatureStore.search`, `bench`) ; voisines par blocs de 4 096, UMAP
    qui garde la place apprise de l'échantillon. Les groupes Leiden publiés ne sont pas recalculés.
    Mesuré sur WikiArt 81k : Leiden redonne exactement les mêmes groupes (forme 142, sujet 141,
    NMI 1,000 : aucune petite communauté à γ ≈ 7–8) ; la renormalisation change la 1ʳᵉ voisine de
    0,033 % des œuvres (forme) et 0,21 % (sujet), la liste des 10 de 0,23 % et 1,5 %.
  - reste : normalisation de la variante « cases communes » (8, méthode non retenue). Point 9 (P@1)
    **décidé le 19/11/2026** : règle gardée (première voisine étiquetée) et écrite, écarts mesurés
    dans ARCHITECTURE § 30, aucune conclusion ne change.

## Fait depuis 0.18.0 (publié en 0.19.0)

- Corrections de l'audit d'Argon (commit `4d7998a`, voir plus bas).
- **SSCD évalué par Gemini 4 Neon, non retenu** (fusionné, ARCHITECTURE § 27,
  `docs/handoff/gemini-sscd.md`) : licence MIT, 80 716 œuvres en 4 min 41 s. Sur les 9 paires
  « filiation », R@10 33 % et rang médian 216, derrière Forme et Sujet (39 %, 26 et 25). Il retrouve
  les copies fidèles au rang 1 et repère 2,6 % de quasi-doublons (piste : dédoublonnage). Reste dans
  `NOT_KEPT`.
- **Depth Anything V2 Small évalué par Gemini 4 Neon, non retenu** (fusionné, ARCHITECTURE § 28,
  `docs/handoff/gemini-profondeur.md`) : Apache 2.0, grille de profondeur 8 × 8 sur l'œuvre seule,
  80 716 œuvres en 14 min. Sur « même composition, sujet différent », R@10 3,6 % et rang médian
  13 754 contre 53,6 % et 8 pour Forme ; combinée à Forme, elle dégrade le haut du classement.
  Bonne sur les scènes à plans nets (*Le Semeur*, Rubens / Titien), perdue sur l'art non perspectif.
  Reste dans `NOT_KEPT`. `extract.py` passe désormais les cadres du letterbox aux encodeurs qui
  déclarent `needs_boxes`.
- **Filtres combinés** (Collection Space Navigator) : bouton « Filtrer » / touche F, `web/atlas-filtres.js`.
  Comptes croisés (ce que donnerait chaque valeur avec les autres critères), 14 ms par changement sur
  81k, sélection vers le carnet (5 000 au plus) ou un Research Pack (500 plus typiques). « Vue
  d'ensemble » efface aussi les filtres. Vérifié dans l'Atlas 81k (Baroque + portrait = 980, compté
  à part).
- **LocalMAP évalué (19/11/2026), non retenu pour la carte principale** (`pacmap` 0.9.1, Apache 2.0,
  installé avec l'accord de l'utilisateur). Regard forme, PCA 64 comme la carte actuelle, 28 s sur
  CPU. Contre UMAP : voisines gardées 7,8 % contre 7,4 % ; voisines de même style 47,3 % contre
  45,8 %, même artiste 33,5 % contre 32,0 %, même genre 75,5 % contre 75,9 % ; mais la carte se
  coupe en ~6 îlots : surface occupée 20 % contre 41 %, vignettes superposées 95 % contre 83 %, et
  les paires validées plus loin (rang médian 8 879 contre 6 994). Avec 20 voisines : moins bien
  partout. Résultats dans ARCHITECTURE § 29.
  À la demande de l'utilisateur, proposée comme **carte d'essai** dans le menu de l'Atlas (« Forme ·
  LocalMAP (essai, pas mieux) », avec une note qui dit qu'elle n'est pas meilleure) :
  `pixplot maps --localmap`, dépendance facultative `pip install -e .[localmap]`. Calculée pour 81k.
- **Doublons et variantes** (`pixplot doublons`, `pixplot/analysis/duplicates.py`, onglet « Doublons »
  dans « À vérifier ») : vecteurs SSCD centrés, 5 voisines par œuvre. Seuils choisis en regardant des
  paires par tranche de cosinus : ≥ 0,85 même image, 0,65–0,85 répliques, séries, états de gravure,
  copies. WikiArt 81k : 839 paires « même image » (702 avec deux styles différents : la même
  reproduction rangée dans deux styles), 785 variantes (68 en désaccord). Résultats dans
  ARCHITECTURE § 29.
  Outil MCP `find_duplicates` (19 outils ; README, MCP et site FR + EN mis à jour).

## En cours

- **Test du « Pourquoi ? » (Gemini 4 Neon), fusionné le 23/11/2026, non publié** (ARCHITECTURE § 39,
  `handoff/gemini-pourquoi.md`, `pixplot whytest`, 3 min 25 s sur GPU) : **échec net**. Cacher les
  4 zones montrées ne fait pas plus chuter la ressemblance que 4 cases au hasard (voisines proches :
  3 fois moins). Cause : biais de coins (63 % des zones dans les 4 coins, 4 % au centre), car les cases
  de bord de DINOv3 portent une signature de position. Le bouton reste en place pour l'instant.
  **Réparé par Neon, fusionné le 23/11/2026, non publié** (ARCHITECTURE § 40,
  `handoff/gemini-pourquoi-v2.md`) : chaque case est centrée par sa moyenne sur le corpus
  (`cell_means_4x4.npy` dans le run de vecteurs, 11 s une fois), puis les correspondances sont
  classées par leur alignement avec le vecteur global. Réglé sur des voisines de graine 1, vérifié
  une fois sur les paires validées : **réussi** (une image : 4,2 fois le hasard ; voisines 3,8 ;
  flou 5,7 et 3,7). Coins 63 % → 17 %, centre 4 % → 36 %. Réserve : 35 paires validées sur 108
  n'ont plus 4 correspondances (1 à 3 zones affichées) et sortent du test. Vérifié dans l'Atlas 81k
  par Claude : *Le Semeur* sur le semeur, mise en garde sous les zones, 0 erreur console.
- **Posture (Gemini 4 Neon), fusionnée dans main le 21/11/2026, non publiée** (ARCHITECTURE § 35,
  `docs/handoff/gemini-postures.md`) : RT-DETRv2-R50 + ViTPose Base (Apache 2.0, licences vérifiées
  sur Hugging Face), squelette 50 d par figure, comparaison multi-figures avec miroir gauche-droite.
  81k en 54 min ; figures dans 48,4 % des œuvres. Ne bat pas Forme sur les paires validées ; réussites
  ponctuelles (*Le Semeur* Van Gogh ↔ Millet, *Europe* Rubens ↔ Titien au rang 1). Reste dans
  `NOT_KEPT`. **37 paires `meme_geste` : 25 validées, 7 rejetées, 5 à relire** (état du 23/11/2026 ;
  exemples choisis pour illustrer le projet : `handoff/exemples-posture.md`) (touche R, en tête de
  file ; « même geste » = touche 7, « filiation » passe à la touche 8). Selon la relecture : exposer
  ou non « Posture » comme regard spécialisé (brancher `PostureIndex` dans `Spaces.neighbors`).
- **Claude, fait le 21/11/2026, commité (`c63b5e7`), non publié** (processeur seul) :
  - **Recherche par phrase avec les descriptions MMArt** (`pixplot textbench`, § 36), 300 œuvres :
    la description narrative retrouve l'œuvre (rang médian 13 avec SigLIP 2, 6 avec PE-Core), la
    formelle presque jamais (661 / 807), l'historique pas du tout. Textes coupés à 64 / 77 jetons.
  - **Notions apprises** (`pixplot notions --space sujet`, § 37, run `notions_sujet_20261121-213443`,
    3 h 28) : 1 792 notions vivantes, 73,7 % de variance ; 959 sans étiquette, surtout des objets et
    motifs bien nommés par Iconclass (z ≥ 5 fiable). Notions inattendues : n° 24 « chef-d'œuvre
    célèbre », n° 88 « tableau photographié avec son cadre ». Planches de lecture faites avec un
    script hors dépôt. Suite possible : liste de notions dans l'Atlas ; n° 88 dans « À vérifier ».
  - **Émotion à genre égal** (§ 34) : rapport au hasard 1,37 (forme, sujet), 1,27 (touche), 1,12
    (couleur) ; environ deux tiers de l'effet survivent au contrôle du genre.
  - Raccourci clavier de la relecture passé de 1–7 à 1–8 (`web/atlas-revue.js`).
- **Travail en équipe du 22/11/2026, relu et commité par Claude, non publié** (Claude coordonne et
  intègre ; personne d'autre ne commite) :
  - Claude : **intervalles de confiance du banc par paires** (`pixplot pairs ci`, § 38, 98 tests).
    Sûrs : Forme pour la composition, Couleur pour la palette ; pas sûrs : Sujet > Forme sur « même
    sujet », Touche > Forme sur « même facture » ; filiation à égalité. Règle : un regard n'est
    « meilleur » que si l'IC de l'écart apparié exclut zéro.
  - Gemini Neon : panneau « Notions » dans l'Atlas (touche O) et onglet « Cadres (n° 88) » dans
    « À vérifier » ; correctif `runs.py` (les runs `notions_*` faisaient planter `pixplot serve`).
    Relu : calcul des activations conforme à l'entraînement ; corrigé, le n° 88 n'est « cadre » que
    pour le run `notions_sujet_20261121-213443` (`sae.FRAMED_RUN`). 100 tests, vérifié dans l'Atlas 81k.
  - Deepseek : banc Wölfflin mesuré, seul linéaire/pictural robuste (AUC 0,74 ; témoins jusqu'à
    ±0,08, ±0,24 à genre égal). Note écrite par Claude : `handoff/deepseek-wolfflin.md` ; script et
    résultats dans `data/wikiart81k/bench/wolfflin/` (hors git). **Décidé le 24/11/2026** : axe
    d'essai préréglé, fait (voir « Après la 0.22.0 »).
  - CHANGELOG FR + EN : section « Non publié » écrite par Claude (Mistral arrêté avant).
  - Claude : outil MCP `explore_notions` (20 outils) : chercher les notions par nom, voir leurs
    œuvres ; essayé sur 81k (liste 15–40 ms, première notion ouverte 2,7 s). README, MCP, site, AGENTS à jour.
  - **Détail, fichiers et suite dans [`handoff/session-2026-11-22.md`](handoff/session-2026-11-22.md).**
- **Claude, 23/11/2026, non publié** : fiche de données du corpus (`pixplot/analysis/datasheet.py`,
  `pixplot corpus --datasheet`, `datasheet.md` dans chaque Research Pack) ; fiches des regards et
  note sur les artistes corrigées d'après le § 38 et MMArt. Notions du regard forme : calcul coupé à
  l'époque 16/30 par la fin de session, à relancer (processeur, 1–2 h) quand Neon n'en a plus besoin.
  Formats de fichiers décrits dans `docs/FORMATS.fr.md` / `.md`, vérifiés par `tests/test_formats.py`
  (condition de la 1.0 : un format qui change se note au CHANGELOG et dans ce document).
  Parité FR / EN de la doc vérifiée par `tests/test_doc_parity.py` (mêmes titres ; par section, autant de
  blocs de code et de tableaux) : écarts corrigés dans ARCHITECTURE §§ 4, 14, 17, 19 et INSTALL_GPU.

- **Après la 0.21.0 (23/11/2026)** : planche « posture » dans le README FR + EN (poussée). Claude :
  référence des commandes `docs/COMMANDS.fr.md` / `.md` (41 commandes, `tests/test_commands_doc.py`,
  condition de la 1.0), non publiée. Notions du regard forme **calculées** (run `notions_forme_20261123-132834`, 50 min,
  2 048 notions vivantes, 63,4 % de variance contre 73,7 % pour le sujet). **Lues et montrées le
  24/11/2026, non publié** (ARCHITECTURE § 42) : nommées avec Iconclass à travers SigLIP 2 (489 sûres,
  `pixplot notions --nommer`, copie avant noms : `notions.avant-noms.json`) ; panneau « Notions » à deux
  regards, `/api/notions?space=forme`, `explore_notions(space=…)`.
  **Posture dans l'Atlas, en essai (Neon), fusionné le 23/11/2026, non publié** (ARCHITECTURE § 41,
  `handoff/gemini-posture-atlas.md`) : `vitpose` sorti de `NOT_KEPT`, `posture` dans
  `spaces.EXPERIMENTAL` ; voisines exactes `PostureIndex` (toutes figures, miroir), squelettes dans la
  fiche et le comparateur, `/api/posture/…`, MCP `similar_artworks(space="posture")`. Vérifié par
  Claude dans l'Atlas 81k (*Le Semeur* → Millet rang 1, Titien ↔ Mantegna en miroir, 0 erreur).
  Ajout de Claude : `communities` / `disagreements` excluent les regards en essai par défaut
  (`cli._default_spaces`). Copie de travail supprimée.

- **Après la 0.22.0 (24/11/2026), non publié** :
  - Claude : **Wölfflin, linéaire / pictural** dans la vue « Axes conceptuels » (ARCHITECTURE § 43).
    Un axe peut réunir plusieurs phrases séparées par « | » (moyennées ; aussi `probe_concepts`) ; le
    préréglage reprend les 3 phrases par pôle du banc de DeepSeek et affiche sa mise en garde (remplace
    l'ancien « linéaire / pictural » à deux mots). Mesuré tel que l'Atlas le calcule : AUC 0,743
    (identique au banc), 0,757 avec l'écart à la diagonale ; avec les dates, Spearman 0,49 avant 1800
    (bascule vers 1550), nul ensuite. Vérifié dans l'Atlas 81k (1 s par appel, 17 s au premier, 0 erreur).
  - **Gemini 4 Neon : pyramide de tuiles**, fusionnée le 24/11/2026 (ARCHITECTURE § 44,
    `handoff/gemini-tuiles.md`) : `pixplot tiles`, run `tiles/dinov3_vitb16_20261116-111508_20261124-171819`
    calculé pour 81k. Ouverture : 210 Ko au lieu de 35 Mo, mémoire graphique ÷ 42 ; fluidité inchangée
    (déjà au plafond). Vérifié par Claude dans l'Atlas 81k ; ajout `onTileUnload`. Copie supprimée.
    À décider plus tard : lancer `tiles` depuis `analyze` ou non (aujourd'hui à part).
  - Claude : **site redessiné** (non poussé au moment de l'écriture). Recueil de planches, une par cas
    d'usage (10), chacune avec une démonstration animée faite de **vraies réponses de PixPlot** sur WikiArt 81k
    (à la demande de l'utilisateur, pas de personnages dessinés) : vraies œuvres, caméra qui glisse et zoome,
    zones, squelettes et liens réels qui s'allument (`site/assets/scenes.js`, données `site/assets/scenes.json`
    et vignettes `site/assets/oeuvres/`, 61 images, 1,6 Mo, chargées à l'approche ; fabriquées par
    `scripts/site_scenes.py` avec l'Atlas 81k lancé sur le port 8766). **Seulement des œuvres du domaine public**
    (artistes morts avant 1956, liste fixée dans le script). Jouée une fois à l'entrée dans l'écran, bouton
    « Rejouer », état final direct si mouvement réduit. Exemples : Van Gogh d'après Millet (1ʳᵉ voisine sa copie
    de 1881, 2ᵉ l'original), « a skull » (El Greco, Cézanne…), Titien ↔ Mantegna en miroir, Sisley entouré de
    Monet, Corot en double, notion « échelle » = Descentes de croix, axe de Wölfflin. « une auréole » ne donne
    rien de bon en recherche de zone (abstractions) : le site ne la cite plus ; « a golden halo around the
    head of a saint » marche bien (second exemple, 10 œuvres). Chaque démonstration s'agrandit (clic ou bouton,
    boîte de dialogue modale). Titre : PixPlot est un outil, WikiArt un cas pratique. Crédits : Claude et Gemini
    (code), DeepSeek (lectures, banc Wölfflin), Mistral (contrôles qualité) ;
    ouverture : un échantillon réel de la carte 81k (`site/assets/carte.json`, 6 000 positions UMAP et
    10 noms de groupes, 68 Ko) qui se range à sa place. Thème clair (carton de montage) et sombre, polices
    système (Palatino), pas de police externe. Guide aux mêmes styles. Colonne « artiste » du tableau mise à
    jour (1 090 artistes). Vérifié dans le navigateur : bureau, téléphone (pas de défilement horizontal),
    clair et sombre, 0 erreur console.

- **Test d'installation sur machine vierge** (condition de la 1.0) : **décision de l'utilisateur du
  19/11/2026, à faire tout à la fin**, juste avant la 1.0. Ne pas le proposer avant.

## Fait depuis 0.19.0 (publié en 0.20.0)

- **Titres, dates et émotions pour WikiArt** (Claude, 19/11/2026, publié en 0.20.0) : notre WikiArt 81k (`huggan/wikiart`)
  n'a ni titres ni noms de fichier, et son ordre est mélangé. On rattache chaque œuvre à son nom de
  fichier d'origine en comparant les images de **MMArt** (CC BY 4.0, `Shuaimyself/MMArt`, 25,3 Go
  téléchargés avec l'accord de l'utilisateur dans `data/sources/mmart/`, hors git) à nos empreintes
  dHash (même style, même artiste, mêmes dimensions). Puis import des titres et dates (MMArt) et de
  l'émotion dominante (**ArtEmis**, obtenu par l'utilisateur via le formulaire des auteurs, usage
  non commercial, dans `data/sources/artemis/`, hors git ; détail des réactions dans
  `<données>/artemis.json`). Commande `pixplot wikiart-noms --mmart … --artemis …`,
  `pixplot/catalog/wikiart_names.py`, test `tests/test_wikiart_names.py`.
  **Fait** : MMArt téléchargé en 14 min ; rattachement en 3 min 38 s : **70 902 œuvres** retrouvent
  leur nom de fichier (3 281 images de MMArt laissées de côté faute de rattachement sûr ; 32 paires
  vérifiées à l'œil, cas limites compris, toutes justes ; dimensions inutiles car notre copie est
  redimensionnée). Titres pour 70 902 œuvres, **dates pour 56 794** (1401–2012) : la vue chronologique
  s'allume. ArtEmis : réactions pour 70 324 œuvres, émotion dominante (≥ 40 % des réactions, hors
  « autre chose ») pour 55 120. Copie du catalogue avant import : `catalog.avant-wikiart-noms.sqlite`.
  Mesures : (1) ordre de la matière dans le temps, Spearman année/H −0,03 mais une courbe : H médian
  0,941 (1400–1599), 0,912 (1750–1849), 0,948 (1880–1909), 0,895 (1970–2012) ; (2) l'émotion
  dominante, P@1 (première voisine étiquetée) : forme 41,8 %, sujet 41,7 %, touche 37,5 %, couleur
  30,1 %, hasard 24,7 % (genre, pour comparer : 80,9 / 83,4 / 69,4 / 33,1 % contre 14,6 %). Les
  regards captent un peu l'émotion, surtout par le sujet ; la couleur presque pas. Résultats dans ARCHITECTURE
  § 34. **Artistes** (accord de l'utilisateur) :
  `pixplot wikiart-noms --artistes` complète les « Unknown Artist » par l'artiste du nom de fichier :
  35 185 œuvres complétées, il en reste 6 729 inconnues ; 129 → 1 090 artistes distincts. Sur les
  35 717 œuvres rattachées qui avaient déjà un artiste, **0** désaccord avec le nom de fichier.
  Conséquence : les bancs d'essai par artiste, `suspects` et les noms de groupes calculés avant
  portent sur les anciennes étiquettes ; à recalculer avant la prochaine publication de chiffres.
- **PE-Core L/14 et CSD ViT-L/14 évalués par Gemini 4 Neon, non retenus** (fusionné, ARCHITECTURE
  §§ 31–32, `docs/handoff/gemini-pecore-csd.md`). PE-Core (Apache 2.0) contre SigLIP 2 : un peu
  devant sur les étiquettes (style P@1 72,0 % contre 71,4 %), mais recherche par phrase en français
  97/100 pour SigLIP 2 contre 81/100 (anglais 96 contre 92) : SigLIP 2 reste le regard « sujet ».
  CSD (code MIT, poids CC BY 4.0) contre la touche : devant sur le style (P@1 67,0 % contre 61,3 %),
  surtout sur les écoles nommées, mais entraîné sur LAION-Styles qui contient probablement WikiArt
  (scores sans doute gonflés) : la touche reste DINOv3 couche 6. Recherche par phrase possible avec un
  autre encodeur (`pixplot search-text --encoder pe_core_l14`).
- Docs remises à jour (feuille de route, AGENTS, passation) ; README : cas d'usage ; P@1 écrit (§ 30).
- **Ordre et désordre de la matière** (Sigaki, Perc et Ribeiro, PNAS 2018) : entropie de permutation H
  et complexité C sur la luminance des vignettes 256 px (fenêtres 2 × 2, 24 ordres possibles).
  `connoisseur.entropy_complexity`, `pixplot/analysis/order.py`, commande `pixplot ordre` (quelques
  minutes sur 81k, processeur seul) → `ordre.npy` dans l'analyse ; ligne « Ordre de la matière » dans
  les mesures visuelles (fiche et outil MCP `measure_artwork`) ; couleurs « Désordre » et
  « Complexité » de la carte (par rang dans le corpus, les valeurs brutes se tassant entre 0,90 et
  0,98). Médianes par style sur WikiArt 81k : du plus ordonné, Minimalism (H 0,622, C 0,229) et
  Color Field (0,712, 0,221), au plus désordonné, Post-Impressionism (0,956, 0,057) et Pointillism
  (0,978, 0,028) ; par genre, abstract_painting (0,835) à illustration (0,950). Résultats dans ARCHITECTURE
  § 33.

## À faire avant la prochaine version

- **Fait le 19/11/2026** : recalculs après l'ajout de 35 185 artistes. `pixplot suspects` : étiquettes
  d'artiste à vérifier 506 → 1 206 (style 2 771 et genre 1 607 inchangés ; ancien fichier gardé en
  `suspects.avant-artistes.json`). Mentions « métadonnées » des groupes mises à jour pour 27 groupes
  sur 142, **aucun nom relu par l'utilisateur modifié** (ancien fichier `names.avant-artistes.json`).
  `pixplot bench`, artiste P@10 sur 1 090 artistes : forme 33,9 %, sujet 42,9 %, touche 35,0 %,
  couleur 7,3 % (avant, 129 artistes : 50,8 / 61,6 / 53,0 %) ; même classement ; README FR + EN à jour.

## En attente de l'utilisateur

- **Sauvegarde du travail fait à la main (constaté le 24/11/2026)** : le code est sur GitHub, mais
  `data/` ne l'est pas, et aucune sauvegarde (OneDrive, disque externe) n'a été trouvée. Le plus
  précieux, car irremplaçable : `data/wikiart81k/bench/pairs.csv` (1 296 lignes, relectures comprises ;
  la copie versionnée `bench/wikiart81k_pairs.csv` n'a que 105 lignes et date du 16/11), le carnet
  `notebook.sqlite`, les noms de groupes relus. Proposé : une commande qui recopie ces fichiers dans
  `bench/` (versionné), plus une copie de `data/` sur un disque externe. Le reste se recalcule.

- **Profil GitHub** : la page de présentation (dépôt `riyadhHDA/riyadhHDA`) est en ligne ; le nom, la
  bio, le lien et les dépôts épinglés sont à régler par l'utilisateur (le jeton `gh` n'a pas le droit
  `user`).

## Bloqué ou plus tard

- **Pistes signalées par l'utilisateur le 24/11/2026, à regarder plus tard** (rien de lu ni d'évalué) :
  Depth Pro 2 d'Apple (https://apple-aiml-research.github.io/ml-depth-pro-2/), à comparer à Depth
  Anything V2, déjà évalué et écarté pour la composition (ARCHITECTURE § 28) ; OpenVisionBanana
  (https://github.com/OpenVisionBanana/OpenVisionBanana). Pour chacun : licence des poids, ce qu'il
  apporterait à un regard existant, banc d'essai avant toute adoption.

- **Phrases des spectateurs d'ArtEmis** (idée du 19/11/2026, « plus tard » selon l'utilisateur) : les
  afficher dans la fiche de l'œuvre et pouvoir chercher dedans (~2 h). Aujourd'hui seules l'émotion
  dominante et 3 phrases par œuvre sont gardées (`<données>/artemis.json`) ; le fichier complet est
  dans `data/sources/artemis/` (usage non commercial, local).
- **Import Paris Musées** (premier corpus français, images CC0 seulement) : le site est revenu le
  18/11/2026, mais son `robots.txt` interdit explicitement les robots d'IA (`anthropic-ai`,
  `ClaudeBot`, `Google-Extended`, `CCBot`…) et ses pages de recherche aux robots : **ne pas parcourir
  les notices**. Voie correcte : l'API GraphQL officielle, avec un jeton que l'utilisateur crée
  lui-même. Les manifestes IIIF sont au format Présentation 2 (lisible par `pixplot import-iiif`) ; le
  champ des droits figure sur la notice (« CC0 Paris Musées / … »). Un premier essai avec
  Codex (18/11/2026) a été bloqué par son bac à sable (pas de réseau) ; sa copie de travail est
  supprimée. L'utilisateur a quitté ChatGPT le 19/11/2026 : assistants actuels, Claude et Gemini.
- **Affichage de l'Atlas** : étape suivante possible, une pyramide de tuiles précalculées (comme les
  cartes en ligne, `TileLayer` de deck.gl) pour la carte principale. Les mipmaps ont été essayés en
  0.13.5 et retirés (erreurs WebGL).
- **Location de GPU** : à proposer avant un calcul de plusieurs heures (WikiArt seulement : corpus
  libre). Repère : l'index de zones SigLIP 2 a pris 6 h 21 en local (71 zones/s) ; une H100 aurait fait
  le calcul en 30 à 45 min, mais le gain réel, envoi des images compris, est d'environ 2 à 3 h.
  PE-Spatial B/16 sur 81k : environ 20 min en local (68 images/s).

## Repères utiles

- Atlas 81k : `pixplot --data data/wikiart81k serve --port 8766`.
- Index de zones : `textzones_siglip2_so400m_20261117-155341` (1 614 320 zones, PCA 256, 818 Mo).
- Banc d'essai composition : `pixplot composition` ; rapport dans
  `data/wikiart81k/bench/composition_report_*.json`.
- Paires validées : `bench/wikiart81k_pairs.csv` (104 paires relues à la main par l'utilisateur).
- DOI Zenodo (toutes versions) : `10.5281/zenodo.24363789` ; chaque release GitHub est archivée
  automatiquement par Zenodo, avec son propre DOI (0.15.1 : `10.5281/zenodo.24363790`).
- Search Console : le site est vérifié (`site/googlea3776ac9a4d427ef.html`) ; le plan du site est
  `https://riyadhhda.github.io/pixplot-v2/sitemap.xml` (pas à la racine du domaine).
