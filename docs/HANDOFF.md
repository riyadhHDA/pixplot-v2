# Passation — où en est le travail

À lire en début de session, à mettre à jour en fin de session (voir [AGENTS.md](../AGENTS.md)).
Ce fichier remplace la mémoire propre à chaque assistant : il doit suffire à reprendre le travail
avec n'importe quel modèle.

*Dernière mise à jour : 19/11/2026 (audit : points d'interface corrigés ; SSCD confié à Gemini).*

## Version publiée

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
- **Pas encore corrigé** (à faire ou à décider) :
  - interface : **corrigé le 19/11/2026, non commité** (I-2, I-4, M-1, M-2, M-3, M-5 : numéro par
    chargement du panneau et des vues, `httpError`/`sendJSON` dans `atlas-base.js`, carnet qui signale
    une note non enregistrée, file de relecture rechargée une seule fois, lots HD relancés 2 fois) ;
  - calculs : **corrigé le 19/11/2026, non commité** (4, 7, 12, 13, 14 ; tests dans
    `tests/test_audit_calc.py`) : reprise de `pixplot zones` (dernier run inachevé compatible, images
    illisibles laissées hors de l'index et retentées) ; `merge_small` rattache chaque petite communauté
    entière, dichotomie de Leiden qui reconnaît un graphe émietté ; cadres alignés sur le découpage
    réel des patchs, recherche de détail sur k × 20 zones filtrée sur l'analyse ; renormalisation
    après float16 (index FAISS, `FeatureStore.search`, `bench`) ; voisines par blocs de 4 096, UMAP
    qui garde la place apprise de l'échantillon. Les groupes Leiden publiés ne sont pas recalculés.
    Mesuré sur WikiArt 81k : Leiden redonne exactement les mêmes groupes (forme 142, sujet 141,
    NMI 1,000 : aucune petite communauté à γ ≈ 7–8) ; la renormalisation change la 1ʳᵉ voisine de
    0,033 % des œuvres (forme) et 0,21 % (sujet), la liste des 10 de 0,23 % et 1,5 %.
  - reste : normalisation de la variante « cases communes » (8, méthode non retenue) ; **P@1 de
    `pixplot bench` mesuré sur la première voisine étiquetée** (9 : changerait les chiffres publiés,
    à décider avec l'utilisateur).

## Fait depuis 0.18.0 (sur `main`, non publié)

- Corrections de l'audit d'Argon (commit `4d7998a`, voir plus bas).
- **Filtres combinés** (Collection Space Navigator) : bouton « Filtrer » / touche F, `web/atlas-filtres.js`.
  Comptes croisés (ce que donnerait chaque valeur avec les autres critères), 14 ms par changement sur
  81k, sélection vers le carnet (5 000 au plus) ou un Research Pack (500 plus typiques). « Vue
  d'ensemble » efface aussi les filtres. Vérifié dans l'Atlas 81k (Baroque + portrait = 980, compté
  à part).
- **LocalMAP** : l'installation de `pacmap` 0.9.1 a été refusée par le garde-fou d'auto mode ;
  l'utilisateur doit la lancer lui-même (`.venv\Scripts\python -m pip install pacmap==0.9.1`).

## En attente de l'utilisateur

- **SSCD confié à Gemini** (19/11/2026) : copie de travail `..\pixplot-sscd`, branche `gemini/sscd`,
  consigne dans `PROMPT-gemini-sscd.md` (non versionné). À relire puis fusionner avec
  `.\scripts\nouvelle-tache.ps1 sscd -Agent gemini -Terminer`.

- **Une paire proposée** à valider ou rejeter dans la relecture rapide (touche R) : copie de Rubens
  d'après l'*Enlèvement d'Europe* de Titien (n° 64269 ↔ 67405, Honour et Fleming p. 573).
- **Profil GitHub** : la page de présentation (dépôt `riyadhHDA/riyadhHDA`) est en ligne ; le nom, la
  bio, le lien et les dépôts épinglés sont à régler par l'utilisateur (le jeton `gh` n'a pas le droit
  `user`).

## Bloqué ou plus tard

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
