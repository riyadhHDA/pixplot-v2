# Passation — où en est le travail

À lire en début de session, à mettre à jour en fin de session (voir [AGENTS.md](../AGENTS.md)).
Ce fichier remplace la mémoire propre à chaque assistant : il doit suffire à reprendre le travail
avec n'importe quel modèle.

*Dernière mise à jour : 19/11/2026.*

## Version publiée

**0.16.1** (19/11/2026) : outil MCP `why_similar` (16 outils) et guide de l'historien de l'art sur
le site. **0.16.0** : « Pourquoi ces deux œuvres se ressemblent ? » dans le comparateur (ARCHITECTURE § 25). Avant : **0.15.1**, tests sur GitHub (Linux et Windows), Atlas découpé en 8 scripts, projet
citable (CITATION.cff, DOI Zenodo à chaque release). Avant : 0.15.0, la composition (ARCHITECTURE § 24). Historique
complet dans le [CHANGELOG](../CHANGELOG.fr.md), étapes suivantes dans la [ROADMAP](../ROADMAP.fr.md).

## Fait, commité dans main, pas encore publié

- Antigravity sous Windows : `pixplot antigravity-mcp` (outil `ask_antigravity`, second avis en lecture
  seule : `--mode plan --sandbox`), testé le 19/11/2026 avec agy 1.5.12 installé par winget (relecture
  réelle en 65 s, aucun fichier modifié). PixPlot déclaré pour Antigravity dans `.agents/mcp_config.json`
  (local). Compétence d'accessibilité dans `.agents/skills/`.
- « Pourquoi ? » corrigé d'après la relecture d'Antigravity : ressemblance moyenne sans la paire
  elle-même, plus d'avertissement Python pour les œuvres non carrées.

## Travail en cours, sur une branche

**0.14 : nommer les groupes avec Iconclass** — branche `claude/iconclass` (commit `598b83c`, non
fusionnée). Le code est écrit et testé, mais attend que l'utilisateur juge les noms (critère de la feuille de route : « jugés plus justes que les actuels, sur
un échantillon relu »).

- Fichiers : `pixplot/analysis/iconclass.py` (nouveau), commande `pixplot iconclass [--fetch]` dans
  `pixplot/cli.py`, champ `iconclass` des groupes (`pixplot/api/data.py`), MCP (`corpus_overview`,
  `get_group`), affichage dans le panneau Groupes (`web/atlas.js` sur la branche : à reporter dans
  `web/atlas-panneaux.js`, fonction `renderGroups`, depuis le découpage du 19/11/2026 ; `web/atlas.css`), tests
  (`tests/test_research.py::test_iconclass_vocabulary_and_pick`), ARCHITECTURE § 23 (FR et EN).
- Données : `data/iconclass/` (CC0, non versionné) ; résultat dans
  `data/wikiart81k/runs/analysis/dinov3_vitb16_20261116-111508/names_iconclass.json`.
- Résultat sur WikiArt 81k : 37 groupes « sûr », 47 « possible », 58 sans notion affichée.
- Reste à faire quand l'utilisateur aura relu : rebaser la branche sur `main`, entrée de CHANGELOG
  (FR + EN), version 0.15.1 ou 0.16.0 (la 0.15.0 est sortie avant ; à voir avec l'utilisateur)
  (voir la liste des fichiers dans AGENTS.md), commit, étiquette, release.

## En attente de l'utilisateur

- **Relire les noms Iconclass** dans l'Atlas (panneau Groupes ; bordure pleine = sûr, pointillée =
  possible).
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
