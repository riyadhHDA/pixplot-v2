# Atlas (interface web)

Carte interactive du corpus, servie par `pixplot serve` sur http://127.0.0.1:8765.

- `index.html`, `atlas.css` et les scripts `atlas-*.js` : l'interface, en JavaScript simple, sans
  compilation. Les scripts sont des scripts classiques chargés **dans cet ordre** par `index.html` ;
  ils partagent leurs constantes et fonctions (même portée globale, pas de modules) :

  | Fichier | Contenu |
  |---|---|
  | `atlas-base.js` | constantes, état commun (`state`), utilitaires (`$`, `esc`), chargement (`init`) |
  | `atlas-couleurs.js` | couleurs des points et légende |
  | `atlas-carte.js` | deck.gl, vignettes (planches et haute définition), dessin des couches |
  | `atlas-dispositions.js` | carte, chronologie, géographie et lieux typés |
  | `atlas-panneaux.js` | infobulle, groupes, surbrillance, fiche d'une œuvre, comparateur, carnet |
  | `atlas-revue.js` | à vérifier : étiquettes, bilan du corpus, relecture rapide, paires, désaccords |
  | `atlas-recherche.js` | recherche par détail et par zone décrite, résultats, Research Pack |
  | `atlas-filtres.js` | filtres combinés (étiquettes, groupes, atypicité, dates), sélection vers le carnet ou un Research Pack |
  | `atlas-notions.js` | notions apprises (liste filtrable, surbrillance, carnet) et onglet « Cadres (n° 88) » dans « À vérifier » |
  | `atlas-ui.js` | branchement de l'interface (boutons, raccourcis), puis `init()` — toujours en dernier |

  Les appels entre fichiers se résolvent au moment où ils ont lieu (après le chargement de tous les
  scripts) ; seul le code exécuté au chargement doit respecter l'ordre. Un nouveau fichier s'ajoute
  dans `index.html`, avant `atlas-ui.js`.
- `hd-worker.js` : décodage des vignettes hors du fil principal (Web Worker).
- `vendor/deck.gl-9.4.1.min.js` : deck.gl (licence MIT), rangé ici pour fonctionner hors ligne.

L'interface ne lit que l'API (`/api/...`, voir `pixplot/api/app.py`) ; elle n'accède jamais
directement aux fichiers. Pour la modifier : éditer les fichiers puis recharger la page.
