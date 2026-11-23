# Compte rendu — regard « posture » dans l'Atlas, l'API et le MCP (`gemini/posture-atlas`)

*Date : 23/11/2026 · Assistant : Gemini 4 Neon (Antigravity) · Branche : `gemini/posture-atlas`*

## 1. Ce qui a été fait

1. **Voisines exactes multi-figures + miroir (`pixplot/encoders/posture.py`, `pixplot/api/spaces.py`, `pixplot/api/data.py`)** :
   - `PostureIndex.__init__` a été vectorisé en NumPy pur (division par 3,3 du temps d'ouverture à froid sur 81k) et mémorise `_run_rows` pour indexer correctement `poses_kpts.npy` / `poses_boxes.npy` sur un sous-ensemble d'identifiants.
   - Ajout de `COCO_LIMBS`, `letterbox_to_image_kpts`, `letterbox_to_image_box`, `PostureIndex.figure_count`, `PostureIndex.figures` et `PostureIndex.match_pair`.
   - `Spaces.posture_index("posture")` charge `PostureIndex` une seule fois (paresseusement) et le met en cache.
   - `Spaces.neighbors("posture", ...)` et `Spaces.posture_neighbors(...)` passent désormais par `PostureIndex.similar` (toutes les figures, direct et miroir, exclusion des œuvres sans figure).
   - `AtlasData.neighbor_list` enrichit chaque voisine posture avec `fig_a`, `fig_b` et `mirrored`, et `AtlasData.artwork` ajoute `posture_figures` (nombre de figures détectées dans l'œuvre).
   - `Spaces.pairwise` utilise également `PostureIndex.match_pair` pour la colonne Posture du comparateur (`None` si l'une des œuvres n'a pas de figure).

2. **Regard spécialisé, en essai (`pixplot/api/spaces.py`, `pixplot/analysis/critique.py`, `web/`)** :
   - `"vitpose"` est sorti de `NOT_KEPT` et `"posture"` est déclaré dans `EXPERIMENTAL = frozenset({"posture"})`.
   - `Spaces.list()` expose `experimental: True` et `specialized: True`, et la fiche critique `CARDS["posture"]` (`pixplot/analysis/critique.py`) est mise à jour (`status: "spécialisé · en essai"`, couverture 48,4 %, échec sur le cubisme et les figures déformées, ne bat pas la forme sur les paires validées, 25 paires « même geste » validées sur 37 proposées).
   - Dans l'Atlas (`web/atlas-panneaux.js`, `web/atlas-base.js`, `web/atlas-revue.js`, `web/atlas.css`) :
     - le sélecteur de regards sépare visuellement les regards principaux des regards spécialisés (`.spaces-sep`, bordure pointillée `.space.essai` + mention `essai`) ;
     - la fiche du regard dans « Corpus » porte le badge `spécialisé · en essai` ;
     - une œuvre sans figure affiche un message explicite (« Aucune figure détectée dans cette œuvre… ») au lieu d'une liste vide.

3. **Squelettes visibles (`pixplot/api/app.py`, `web/atlas-panneaux.js`, `web/atlas.css`)** :
   - Ajout de `GET /api/posture/{artwork_id}` (squelettes COCO-17 ramenés du carré de letterbox aux coordonnées `[0, 1]` de l'image réelle) et `GET /api/posture/match?a=...&b=...` (squelettes des deux œuvres + paire `(fig_a, fig_b)` + `mirrored` + précaution).
   - `GET /api/compare` inclut `posture_matches` (`score`, `fig_a`, `fig_b`, `mirrored`) pour afficher immédiatement le badge `miroir` dans le tableau des similarités.
   - Dessin en SVG natif (sans bibliothèque, calé sur `imageRect(img)`), avec figure qui se répond en doré et figures secondaires en discret :
     - **Fiche d'une œuvre** : squelettes dessinés sur `.fiche .hero` quand le regard actif est `posture` ; au survol d'une voisine, la figure `fig_a` correspondante est mise en avant avec la mention `en miroir` le cas échéant ; badge `miroir` sur les vignettes des voisines.
     - **Comparateur** : bouton `Squelettes` par paire (activé automatiquement pour la paire `1 ↔ 2` lorsque le regard actif est `posture`), dessin des deux squelettes qui se répondent et bandeau indiquant score, numéros de figures, mention `en miroir` et précaution.

4. **Serveur MCP (`pixplot/mcp/server.py`)** :
   - Aucun nouvel outil (toujours 20 outils).
   - `similar_artworks` accepte `space="posture"` (avec `experimental: True`, `figures`, `note` mentionnant le statut « en essai » et « une pose semblable est une piste, pas la preuve qu'un artiste a vu l'autre », et `message` explicite si aucune figure n'est détectée).

5. **Tests (`tests/test_posture.py`)** :
   - Mise à jour du test d'enregistrement (`vitpose` hors `NOT_KEPT`, `posture` dans `EXPERIMENTAL`).
   - Ajout de `test_posture_api_skeletons_mirror_no_figure_and_mcp` sur le corpus synthétique (`conftest.py`) : voisines multi-figures avec miroir (`fig_a=1`, `fig_b=0`, `mirrored=True`), œuvre sans figure, conversion letterbox → image 90×120 dans `/api/posture/{id}`, `/api/posture/match`, `/api/compare`, et MCP `similar_artworks(..., space="posture")`.

---

## 2. Mesures (WikiArt 81k — 80 716 œuvres, 39 043 figurées, 102 515 figures)

### Temps mesurés côté Python (`PostureIndex`, exact sans approximation)

| Opération | Temps mesuré | Détails |
|---|---|---|
| `PostureIndex.open` (avant vectorisation) | 1 605,9 ms | Chargement initial (une seule fois) |
| `PostureIndex.open` (après vectorisation) | **485,8 ms** | 3,3× plus rapide, résultat strictement identique |
| `PostureIndex.similar(79406, k=20)` à chaud | **8,3 ms** | Top 1 : Millet `41274` (score `0,9791`, `fig_a=0`, `fig_b=0`, `mirrored=False`) |
| `PostureIndex.similar(66184, k=20)` à chaud | **38,0 ms** | Top 1 : `6813` (`0,9756`, `mirrored=True`) |
| `PostureIndex.similar(56885, k=20)` à chaud | **8,6 ms** | Top 1 : `71698` (`0,9829`, `fig_a=7`, `fig_b=2`, `mirrored=False`) |
| `PostureIndex.similar(24419, k=20)` à chaud | **4,1 ms** | Top 1 : `56788` (`0,9593`) |
| `PostureIndex.similar(12088, k=20)` à chaud | **3,2 ms** | Top 1 : `39811` (`0,9405`) |
| `PostureIndex.match_pair(66184, 56885)` | < 1 ms | Titien ↔ Mantegna : score `0,9320`, `fig_a=0`, `fig_b=0`, **`mirrored=True`** |

La cible `< 300 ms` à chaud est largement tenue (3 à 38 ms en Python, recherche **100 % exacte**, sans aucun index approché).

### Vérification dans l'Atlas 81k (port 8770, navigateur)

- **Temps HTTP à chaud** (`/api/artwork/79406?space=posture`, 3 requêtes consécutives mesurées côté navigateur, incluant SQLite + sérialisation JSON) : **177 ms**, **144 ms**, **142 ms** (toutes `< 300 ms`).
- **Le Semeur** (Van Gogh `79406`) : Millet `41274` sort bien au **rang 1** (`0.979`), squelette SVG aligné sur l'image (`288,7 × 382 px`).
- **Titien `66184` ↔ Mantegna `56885`** dans le comparateur : squelettes SVG alignés sur les deux œuvres (`478 × 302 px` et `478 × 374,8 px`), score `0.932`, mention **`en miroir`** affichée sur l'image, dans le bandeau et dans le tableau.
- **Œuvre sans figure** (`#oeuvre-3`) : 0 voisine, message clair `.empty-posture` (« Aucune figure détectée… »).
- **Panneau Corpus** : fiche « Posture » affichée avec le badge `spécialisé · en essai`.
- **Console et réseau** : **0 erreur console**, **0 erreur HTTP** (un bug CSS initial où la règle globale `svg { width: 18px; height: 18px; }` écrasait `.pose-svg` a été détecté lors de cette vérification et corrigé dans `web/atlas.css` et `web/atlas-panneaux.js`).

### Tests automatisés

- `pytest -q tests` : **127 passed** (dont 5 dans `tests/test_posture.py`).

---

## 3. Limites connues

- **Couverture partielle** : 48,4 % des œuvres de WikiArt 81k (39 043 / 80 716) ont au moins une figure corporelle détectée ; les paysages, natures mortes, abstractions et portraits très serrés sans épaules/corps n'ont pas de voisines en posture.
- **Figures déformées / cubisme** : détecteur et estimateur entraînés sur photographies modernes (MS COCO).
- **Redimensionnement de fenêtre** : les overlays SVG (`.pose-svg`) sont positionnés au chargement de l'image (comme `.why-box` pour « Pourquoi ? ») ; après un redimensionnement important de la fenêtre, un survol ou un reclic sur `Squelettes` recale le dessin.
- **Pas de carte 2D dédiée à la posture** : les œuvres sans figure n'y auraient pas de position ; le regard est exposé uniquement pour les voisines, le comparateur et le MCP.

---

## 4. À décider / pour l'intégrateur

1. **Fusion** : relire et fusionner `gemini/posture-atlas` dans `main` (`.\scripts\nouvelle-tache.ps1 posture-atlas -Agent gemini -Terminer`).
2. **Documentation** : ajouter la section datée correspondante dans `ARCHITECTURE.fr.md` / `ARCHITECTURE.md`, mettre à jour `docs/HANDOFF.md` et les CHANGELOG si publication.
3. **Évolution éventuelle (optionnelle)** : si l'utilisateur souhaite voir aussi le squelette directement sur les petites vignettes des voisines (ou comparer en un clic une œuvre et une voisine posture depuis la fiche), c'est faisable dans une tâche ultérieure très courte.
