# Passation — où en est le travail

À lire en début de session, à mettre à jour en fin de session (voir [AGENTS.md](../AGENTS.md)).
Ce fichier remplace la mémoire propre à chaque assistant : il doit suffire à reprendre le travail
avec n'importe quel modèle.

*Dernière mise à jour : 18/11/2026.*

## Version publiée

**0.13.5** (17/11/2026) : affichage des images de l'Atlas par lots, dans un ordre stable. Historique
complet dans le [CHANGELOG](../CHANGELOG.fr.md), étapes suivantes dans la [ROADMAP](../ROADMAP.fr.md).

## Travail en cours, non commité

**0.14 : nommer les groupes avec Iconclass.** Le code est écrit et testé, mais attend que
l'utilisateur juge les noms (critère de la feuille de route : « jugés plus justes que les actuels, sur
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

- **Import Paris Musées** (premier corpus français, images CC0 seulement) : le site et l'API
  répondaient « Service indisponible » (503) le 17/11/2026. À la reprise : vérifier que le site est
  revenu, ouvrir une notice pour trouver le lien du manifeste IIIF (environ 202 000 notices en ont un,
  selon le ministère) et le champ des droits ; l'importeur IIIF existant (`pixplot import-iiif`) devrait
  suffire. L'API GraphQL demande un compte et un jeton que l'utilisateur doit créer lui-même.
- **Affichage de l'Atlas** : étape suivante possible, une pyramide de tuiles précalculées (comme les
  cartes en ligne, `TileLayer` de deck.gl) pour la carte principale. Les mipmaps ont été essayés en
  0.13.5 et retirés (erreurs WebGL).
- **0.15, la composition** (STELLAR, PE-Spatial) : calcul GPU de plusieurs heures. Proposer d'abord
  une estimation avec location de GPU (WikiArt seulement : corpus libre). Repère : l'index de zones
  SigLIP 2 a pris 6 h 21 en local (71 zones/s) ; une H100 aurait fait le calcul en 30 à 45 min, mais
  le gain réel, envoi des images compris, est d'environ 2 à 3 h.

## Repères utiles

- Atlas 81k : `pixplot --data data/wikiart81k serve --port 8766`.
- Index de zones : `textzones_siglip2_so400m_20261117-155341` (1 614 320 zones, PCA 256, 818 Mo).
- Paires validées : `bench/wikiart81k_pairs.csv` (104 paires relues à la main par l'utilisateur).
- Search Console : le site est vérifié (`site/googlea3776ac9a4d427ef.html`) ; le plan du site est
  `https://riyadhhda.github.io/pixplot-v2/sitemap.xml` (pas à la racine du domaine).
