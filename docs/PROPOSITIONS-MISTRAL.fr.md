# Propositions Mistral — papiers récents, idées, skills / MCP / API

[English](PROPOSITIONS-MISTRAL.md) · **Français**

*Dernière mise à jour : 24/11/2026.*

Ce fichier recueille les **propositions** discutées avec Mistral Vibe : papiers scientifiques
récents, nouvelles fonctionnalités, skills, outils MCP, routes API. Ce n'est pas la feuille de
route — la [ROADMAP](../ROADMAP.fr.md) décide. Ce fichier garde la mémoire des pistes : une
proposition qui se fait sort d'ici (CHANGELOG + ARCHITECTURE) et passe en « fait » ; une
proposition écartée garde ses raisons et ses chiffres.

## Comment mettre à jour ce fichier

- Chaque entrée a une **date**, une **source** (papier avec arXiv/DOI, ou discussion) et un
  **statut** : `à tester`, `en cours`, `fait`, `écarté` (avec la raison).
- Les papiers sont rangés par thème, les plus récents d'abord ; ceux marqués « à lire en
  priorité » passent devant.
- On met à jour **les deux langues ensemble** (`PROPOSITIONS-MISTRAL.fr.md` et
  `PROPOSITIONS-MISTRAL.md`), avec la même structure de sections.
- On ajoute les nouvelles entrées en haut des tableaux ; on ne réécrit pas l'historique.

Format d'une mise à jour :

```text
- 2026-11-24 | zones émotionnelles (masques APOLO × zones SigLIP 2) | EmoSEM, arXiv 2504.14658 | à tester
```

## Papiers repérés (2025–2026)

| Papier (date) | Réf. | Pourquoi pour PixPlot | Statut |
|---|---|---|---|
| M-ArtAgent + WikiArt Influence Benchmark WIB-100 (2026) | arXiv 2604.07468 | Banc « filiation » équilibré, prêt à l'emploi sur WikiArt | à lire en priorité |
| Sparse Autoencoders Learn Monosemantic Features in VLMs (avr. 2025) | arXiv 2504.02821 | Testé sur SigLIP SoViT-400m (notre modèle) ; cadre pour noter nos notions SAE | à lire en priorité |
| EmoSEM : segmenter les zones qui suscitent l'émotion (avr. 2025) ; lien avec APOLO / ArtEmis non vérifié | arXiv 2504.14658 | Localiser l'émotion dans le tableau, croisé avec nos 1,6 M zones | à lire en priorité |
| fruit-SALAD, Scientific Data (2025) | s41597-025-04529-4 | Similarité perçue par des humains, projetée dans les embeddings : juger les regards | **référence non vérifiée** (page inaccessible au 24/11/2026) |
| Dare to Plagiarize? (juin 2025) | arXiv 2506.23132 | Détection + retrieval de la source authentique (doublons, filiation) | à lire en priorité |
| SAM 3 : Segment Anything with Concepts (nov. 2025) | arXiv 2511.16719 | Découper un motif par une phrase (« auréole »), déjà dans la ROADMAP | à lire en priorité |
| ArtSeek : retrieval late-interaction pour l'art (juil. 2025) | arXiv 2507.21917 | Recherche par texte fine (zones), benchmark PaintingForm | à lire en priorité |
| Patch-to-region, famille ColPali (déc. 2025) ; porte sur des documents, pas sur l'art | arXiv 2512.02660 | Requête multi-zones texte + spatial sur notre grille de zones | à lire en priorité |
| AVAtt : eye-tracking sur peintures (oct. 2026) | arXiv 2610.30481 | Saillance spécifique peintures (16 mouvements, 5 siècles) | à lire en priorité |
| Uncertainty-Aware Art-Historical Dating with VLMs (2026) | arXiv 2608.18984 | Datation visuelle avec intervalle de confiance | à lire en priorité |
| Relational Visual Similarity (déc. 2025) | arXiv 2512.07833 | Analogies A:B::C:? entre œuvres (désaccords, parangone) | repéré |
| jina-clip-v2, CLIP multilingue (déc. 2024) | arXiv 2412.08802 | Challenger SigLIP 2 pour la recherche en français (textbench) | repéré ; poids sous CC BY-NC 4.0 (non commercial) |
| Art Beyond Semantics : sheaf + benchmarks WikiArt+, HertzianaDP (2026) | arXiv 2607.16321 | Représentations multi-relationnelles œuvre/artiste/école | repéré |
| Automating Iconclass : LLM + RAG (oct. 2025) | arXiv 2510.19986 | Nommer groupes et notions sans SigLIP, 92 % sans fine-tuning | repéré |
| VQArt-Bench : VQA art et patrimoine (oct. 2025) | arXiv 2510.12750 | Évaluer quantitativement les réponses du serveur MCP | repéré |
| GeoToken : géolocalisation d'images, local-first (nov. 2025) | arXiv 2511.01082 | Estimer le lieu peint d'un paysage (complète la vue lieux) | repéré |
| Revisiting Wölfflin in the Age of AI, J. Imaging (2025) | doi 10.3390/jimaging11050128 | Comparer à notre axe linéaire/pictural (§ 43) | **référence non vérifiée** (page inaccessible au 24/11/2026) |
| Two-by-two ordinal patterns in art paintings (mars 2025) | arXiv 2503.09844 | Extension de l'entropie de permutation (`pixplot ordre`) | **mesuré, non retenu** (ARCHITECTURE § 47) |
| Forensic Study of Paintings : comparaison de toiles (juin 2025) | arXiv 2506.20272 | Filiation matérielle/atelier (corpus musée, scans HD) | repéré |
| Curating art exhibitions using machine learning (2025) | arXiv 2506.19813 | Proposer un accrochage depuis la carte (Research Pack) | repéré |
| DINOv3 (Meta, août 2025) | arXiv 2508.10104 | Notre regard « forme » ; § 6.1.3 = correspondances de parties (« Pourquoi ? ») | repéré |
| SigLIP 2 (févr. 2025) | arXiv 2502.14786 | Notre regard « sujet » ; variante NaFlex (résolution native, sans letterbox) | repéré |

## Propositions de fonctionnalités

| Priorité | Proposition | S'appuie sur | Banc de réussite | Effort | Statut |
|---|---|---|---|---|---|
| P1 | Zones émotionnelles : où dans le tableau se situe l'émotion | APOLO × index de zones | zone prédite dans le masque annoté (vs hasard) | ~1 j | à tester |
| P1 | Banc « perception humaine » : ~200 paires notées par des humains | fruit-SALAD | classement des regards sur jugements humains, avec IC (`pairs ci`) | 2–3 j | à tester |
| P1 | Datation prédictive + IC pour les œuvres sans date | arXiv 2608.18984 | erreur médiane en années + IC calibrés sur les 56 794 datées | 1–2 j | **fait** : `pixplot dater`, ARCHITECTURE § 45 |
| P1 | Recherche en français challengée (jina-clip-v2, SigLIP 2 NaFlex) | arXiv 2412.08802 | `textbench` FR/EN, IC compris | 1 j | à tester |
| — | Les 4 autres paires de Wölfflin en axes conceptuels | J. Imaging 2025 | même banc que § 43 (AUC + Spearman dates) | — | **écarté** : déjà mesuré (§ 43, banc de DeepSeek) ; ces quatre couples ne tiennent pas, le résultat s'inverse selon la phrase ou le genre |
| P2 | Graphe d'influence « qui reprend qui » en vue node-link | WIB-100, arXiv 2604.07468 | R@10 sur WIB-100 + 9 paires filiation | 1–2 sem. | à tester |
| P2 | Saillance prédite : « où regarde-t-on » (fiche + couche carte) | AVAtt, SPGen | NSS/AUC vs fixations humaines | 3–5 j | à tester |
| P2 | Analogies visuelles A est à B comme C est à ? | arXiv 2512.07833 | paires « même composition » / « filiation » | 3–5 j | à tester |
| P2 | Motifs découpés par phrase (SAM 3), recherchés dans tout le corpus | arXiv 2511.16719 | RichArt + cross-corpus | 1–2 sem. | à tester (licence Meta) |
| P2 | Requête multi-zones : « main qui bénit en haut à droite + crâne en bas » | arXiv 2512.02660, ArtSeek | 50 requêtes composées, rang de l'œuvre visée | 1–2 sem. | à tester |
| P2 | Nommer les notions SAE par LLM + RAG Iconclass | arXiv 2510.19986 | relecture des 489 notions nommées (cf. § 23) | 2–3 j | à tester |
| P3 | Graphe de connaissances Wikidata (artistes, mouvements, lieux) | source à trouver (arXiv 2602.19133 est un jeu de données d'entités nommées, FRAME, pas « ArtContext ») | requêtes vérifiables sur Wikidata | 1–2 sem. | à tester |
| P3 | Banc VQA pour évaluer le serveur MCP | VQArt-Bench | score du MCP sur questions d'art | 3–5 j | à tester |
| P3 | Géo-localisation des paysages peints | GeoToken | lieux estimés vs métadonnées `places` | 3–5 j | à tester |
| P3 | Proposition d'accrochage depuis la carte | arXiv 2506.19813 | parcours jugé par l'utilisateur | 1 sem. | à tester |
| P3 | Détection d'œuvres générées par IA dans « À vérifier » | source à trouver (arXiv 2511.22471 porte sur la détection d'images falsifiées avec DINOv3, pas sur l'art ; « ArtUnmasked » introuvable) | corpus étiqueté IA/humain | 3–5 j | à tester |
| P3 | Toile / atelier (filiation matérielle) | arXiv 2506.20272 | corpus musée avec scans HD (Paris Musées) | ? | écarté pour WikiArt (pas de scans HD) |

## Skills, MCP et API

| Surface | Proposition | Critère d'acceptation | Statut |
|---|---|---|---|
| skill | `pixplot-bench` : créer/étendre un banc, IC 95 %, § ARCHITECTURE datée | un assistant lance un banc de bout en bout | à tester |
| skill | `pixplot-encoder` : évaluer un nouvel encodeur (licence, registry, NOT_KEPT, bancs) | procédure suivie pour un encodeur | à tester |
| skill | `pixplot-release` : semver + 7 fichiers + tag + release bilingue | `pytest` passe après bump | à tester |
| skill | `pixplot-doc` : parité FR/EN, COMMANDS/FORMATS, HANDOFF en fin de session | tests de parité passent | à tester |
| skill | `pixplot-audit` : relecture façon Argon (vérifier avant corriger) | rapport numéroté actionnable | à tester |
| skill | `pixplot-papers` : veille littérature (arXiv/HAL), fiche de lecture, proposition ROADMAP | une fiche par papier, lien chantier | à tester |
| skill | `pixplot-licences` : checklist licence avant téléchargement, data/ hors git | aucun téléchargement sans case cochée | à tester |
| skill | `pixplot-mcp` : ajouter un outil MCP en 6 étapes (code → doc FR/EN → README → site → test) | un outil ajouté de bout en bout | à tester |
| MCP | `estimate_date(id)` : datation visuelle + IC | IC calibrés sur œuvres datées | à tester |
| MCP | `emotion_zones(id)` / `saliency(id)` | masque APOLO / fixations AVAtt | à tester |
| MCP | `find_influence(id, k)` : sources et dérivées | WIB-100 + paires filiation | à tester |
| MCP | `segment_motif(id, phrase)` : SAM 3 + recherche cross-corpus | RichArt | à tester (licence) |
| MCP | `search_composed([{text, region}…])` : requête multi-zones | 50 requêtes composées | à tester |
| MCP | `analogy(a, b, c)` : A:B::C:? | paires composition/filiation | à tester |
| MCP | `bench_results()` / `run_bench(name)` : bancs depuis le LLM | VQArt-Bench pour auto-évaluation | à tester |
| MCP | `list_runs()` / `run_status(name)` : piloter les calculs longs | run suivi sans terminal | à tester |
| MCP | `save_pairs()` / `export_bench()` : copier pairs.csv, notebook, noms vers `bench/` | chantier « sauvegarde data/ » | **fait autrement** : commande `pixplot sauvegarde` (24/11/2026) |
| API | `GET /api/runs` + `/api/runs/{id}/progress` (SSE) | progression visible dans l'Atlas | à tester |
| API | `/api/artwork/{id}/emotion-zones`, `/saliency`, `/date-estimate` | panneaux dans la fiche | à tester |
| API | `GET /api/analogy`, `POST /api/search/regions`, `POST /api/segment` | comparateur + recherche avancée | à tester |
| API | `GET /api/influence/graph` : vue node-link du graphe de filiation | graphe dessiné dans l'Atlas | à tester |
| API | `GET /api/export/iiif` : Research Pack en collection IIIF Présentation 3 | pack rechargeable par `import-iiif` | à tester |
| API | `GET /api/bench` : résultats des bancs (IC) pour un panneau « Mesures » | IC à 95 % affichés | à tester |
| API | `GET /api/health` + pagination sur `/api/map`, `/api/search` | test machine vierge (condition 1.0) | à tester |

## Historique des mises à jour

- 2026-11-24 — Création du fichier : analyse de la codebase en lecture seule, revue de
  littérature 2025–2026, propositions de fonctionnalités et de skills / MCP / API.
- 2026-11-24 — Relecture par Claude : les 24 références vérifiées à la source (arXiv, éditeurs). 19 justes ;
  3 fausses corrigées (SigLIP 2 = 2502.14786 ; 2602.19133 et 2511.22471 ne correspondent pas à « ArtContext » et
  « ArtUnmasked ») ; 2 non vérifiables (fruit-SALAD, J. Imaging) ; EmoSEM sans lien établi avec APOLO / ArtEmis.
  Wölfflin (4 autres paires) écarté car déjà mesuré (§ 43) ; sauvegarde faite (`pixplot sauvegarde`).
