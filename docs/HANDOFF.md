# Passation — où en est le travail

À lire en début de session, à mettre à jour en fin de session (voir [AGENTS.md](../AGENTS.md)).
Ce fichier remplace la mémoire propre à chaque assistant : il doit suffire à reprendre le travail
avec n'importe quel modèle.

*Dernière mise à jour : 18/11/2026, après-midi.*

## Version publiée

**0.13.5** (17/11/2026) : affichage des images de l'Atlas par lots, dans un ordre stable. Historique
complet dans le [CHANGELOG](../CHANGELOG.fr.md), étapes suivantes dans la [ROADMAP](../ROADMAP.fr.md).

## Fusionné dans main, pas encore publié (pas de version, pas de push)

**Étape 0.15, la composition : PE-Spatial évalué, non retenu** (ARCHITECTURE § 24, compte rendu
`docs/handoff/claude-composition.md`). Sur les 14 paires « même composition », DINOv3 reste le meilleur
(rang médian 8 ; PE-Spatial 286 au mieux). Code relu par Codex (plugin), qui a proposé deux variantes,
mesurées, sans changement de verdict. Vecteurs PE-Spatial sur le disque, masqués dans l'Atlas
(`NOT_KEPT`). À décider avec l'utilisateur : publier en 0.15.0 (résultat négatif documenté, comme la
0.13.0) ou attendre.

## Travail en cours, sur une branche

**0.14 : nommer les groupes avec Iconclass** — branche `claude/iconclass` (commit `598b83c`, non
fusionnée). Le code est écrit et testé, mais attend que l'utilisateur juge les noms (critère de la feuille de route : « jugés plus justes que les actuels, sur
un échantillon relu »).

- Fichiers : `pixplot/analysis/iconclass.py` (nouveau), commande `pixplot iconclass [--fetch]` dans
  `pixplot/cli.py`, champ `iconclass` des groupes (`pixplot/api/data.py`), MCP (`corpus_overview`,
  `get_group`), affichage dans le panneau Groupes (`web/atlas.js`, `web/atlas.css`), tests
  (`tests/test_research.py::test_iconclass_vocabulary_and_pick`), ARCHITECTURE § 23 (FR et EN).
- Données : `data/iconclass/` (CC0, non versionné) ; résultat dans
  `data/wikiart81k/runs/analysis/dinov3_vitb16_20261116-111508/names_iconclass.json`.
- Résultat sur WikiArt 81k : 37 groupes « sûr », 47 « possible », 58 sans notion affichée.
- Reste à faire quand l'utilisateur aura relu : entrée de CHANGELOG (FR + EN), version 0.14.0
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
  champ des droits figure sur la notice (« CC0 Paris Musées / … »). Copie de travail de Codex :
  `..\pixplot-paris-musees` (branche `codex/paris-musees`, son compte rendu non commité dans
  `docs/handoff/`), bloqué par son bac à sable.
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
- Search Console : le site est vérifié (`site/googlea3776ac9a4d427ef.html`) ; le plan du site est
  `https://riyadhhda.github.io/pixplot-v2/sitemap.xml` (pas à la racine du domaine).
