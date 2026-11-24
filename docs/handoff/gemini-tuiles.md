# Passation — `gemini/tuiles` (pyramide de tuiles précalculées pour l'Atlas)

Branche : `gemini/tuiles` · Dossier de travail : `C:\Users\Riyadh\Documents\pixplot-tuiles` · Date : 24/11/2026.

## 1. Ce qui a été fait

- **Rappel mipmaps (0.13.5)** : dans `web/atlas-carte.js`, les mipmaps WebGL sur textures dynamiques provoquaient des erreurs WebGL et ralentissaient le chargement. Les tuiles précalculées utilisent des textures statiques 512 × 512 px sans mipmaps (`minFilter: "linear", magFilter: "linear", clamp-to-edge`) ; la réduction d'échelle est faite hors ligne en Lanczos 2 × 2 lors de la génération de la pyramide.
- **Calcul CPU reprenable (`pixplot/analysis/tiles.py`, commande `pixplot tiles`)** :
  - Rend le niveau le plus fin (`max_level = 4`, soit 16 × 16 tuiles de 512 px sur l'emprise `[-1024, 1024]`, ~25,3 px par œuvre sur WikiArt 81k) dans l'ordre exact des lignes de l'analyse (identique à `IconLayer`), depuis les planches déjà assemblées quand leur résolution suffit (sinon `thumbs/64` ou `thumbs/256`).
  - Réduit ensuite 2 × 2 en Lanczos du niveau `max_level - 1` jusqu'au niveau `0`.
  - Écrit chaque tuile de façon atomique (`.tmp` + `os.replace`) dans un run daté `runs/tiles/<analyse>_<AAAAMMJJ-HHMMSS>/` (`manifest.json` + `tiles.json` + `<niveau>/<x>/<y>.webp`), tient un journal (`<données>/tiles.log`), et reprend automatiquement un run interrompu (`--no-resume` pour repartir de zéro).
- **API (`pixplot/api/data.py`, `pixplot/api/app.py`)** :
  - `/api/info` expose `"tiles": true|false`.
  - `/api/tiles` renvoie `tiles.json` ; `/api/tiles/{level}/{x}/{y}.{ext}` sert les tuiles avec cache HTTP.
- **Interface web (`web/atlas-base.js`, `web/atlas-carte.js`, `web/atlas-ui.js`, `web/index.html`)** :
  - Affiche la pyramide avec `TileLayer` + `BitmapLayer` de deck.gl 9.4 (embarqué dans `web/vendor/`, 100 % hors ligne) aux zooms éloignés (`onScreenSize() < 24 px`) sur la carte principale sans filtre ni surbrillance.
  - **Chargement différé des planches** : à l'ouverture, si une pyramide existe, les 5 planches de 4096 px (35,7 Mo) ne sont pas téléchargées ; elles ne le sont qu'au premier zoom proche (`≥ 24 px`), à l'activation d'un filtre/d'une surbrillance, au changement de carte ou si l'utilisateur décoche « Tuiles précalculées » dans le menu « Vue ».
  - **Sélection, infobulle, couleurs et filtres** :
    - Clic et survol sur les tuiles retrouvent l'œuvre sous le pointeur en parcourant les positions en ordre inverse (identique à l'empilement WebGL).
    - Dès qu'une couleur (mode « Points colorés »), un filtre combiné, une recherche, une notion, une surbrillance de groupe ou une autre carte est active, les tuiles s'effacent automatiquement au profit des vignettes ou points afin de ne jamais afficher une carte fausse.
- **Tests et documentation** :
  - `tests/test_tiles.py` sur le corpus synthétique (`tests/conftest.py`) : génération CPU, reprise après interruption, journal, CLI `pixplot tiles`, API (`/api/info`, `/api/tiles`, `/api/tiles/...`, 404).
  - `docs/COMMANDS.fr.md` + `docs/COMMANDS.md` et `docs/FORMATS.fr.md` + `docs/FORMATS.md` mis à jour dans les deux langues.

## 2. Mesures

### Génération de la pyramide sur WikiArt 81k (80 716 œuvres, CPU uniquement)

Run créé : `tiles/dinov3_vitb16_20261116-111508_20261124-171819` (dans `data/wikiart81k/runs/tiles/`, hors git).

| Grandeur | Valeur |
|---|---|
| Niveaux | 0 à 4 (tuiles 512 × 512 px, WebP qualité 85) |
| Tuiles non vides | **210** (sur 341 possibles ; les coins vides ne sont ni écrits ni demandés) |
| Source utilisée | Planches `sprites/` (32 px) |
| Temps de calcul (CPU) | **13,12 s** |
| Espace disque | **10,68 Mio** (à comparer aux 34,84 Mio des 5 planches JPEG) |

### Chronométrage dans Chrome (1440 × 900, cache vidé, RX 7900 GRE, écran 144 Hz, port 8770)

Protocole identique avant et après (Chrome via CDP, `Network.setCacheDisabled(true)`, 0 erreur console / WebGL) :

| Mesure | Avant (planches) | Après (tuiles actives) | Écart |
|---|---|---|---|
| **Transfert réseau à l'ouverture** | 38 907 Ko (38,0 Mio) | **3 441 Ko** (3,36 Mio) | **−91 %** (−35,5 Mio) |
| dont planches / tuiles | 35 678 Ko (6 req.) | **210 Ko** (5 req.) | **−99,4 %** |
| **Temps avant 1re image complète** | 4 925 ms *(points colorés seuls en vue d'ensemble)* | **4 488 ms** *(mosaïque complète des 80 716 œuvres dès la vue d'ensemble)* | **−437 ms** (−9 %) |
| **Mémoire GPU à l'ouverture** (`luma.gl`) | **434,9 Mio** (424,6 Mio textures) | **10,3 Mio** (9,3 Mio textures) | **−97,6 % (÷ 42)** |
| **Mémoire JS** (`usedJSHeapSize`) | 61,5 Mo | **22,6 Mo** | **−63 %** |
| **FPS — déplacement vue d'ensemble** | 143,9 fps (méd. 6,9 ms, max 7,2 ms) | **143,9 fps** (méd. 6,9 ms, max 7,1 ms) | identique (plafond 144 Hz) |
| **FPS — déplacement zoom moyen** (`fit + 1,5`) | 143,9 fps (méd. 6,9 ms, max 7,1 ms) | **143,9 fps** (méd. 6,9 ms, max 7,2 ms) | identique (plafond 144 Hz) |
| **FPS — premier grand zoom avant/arrière** (`fit → fit + 3,5 → fit`) | 143,9 fps (méd. 6,9 ms, max 7,2 ms) | **114,7 fps** (méd. 7,0 ms, p95 7,1 ms, **pic 208,4 ms**) | **pic unique de 208 ms** au 1er franchissement du seuil |
| **Mémoire GPU après grand zoom** | 434,9 Mio | **475,0 Mio** | +40,1 Mio (cache tuiles + planches) |
| **Erreurs console / WebGL** | 0 | **0** | 0 |

### Vérification visuelle dans le navigateur (port 8770)

Vérifié interactivement :
1. Vue d'ensemble : mosaïque d'œuvres orientée et alignée avec les numéros de groupes (îlots 39, 38, 13/66/76, 28/53/131).
2. Clic sur une œuvre sur les tuiles : fiche ouverte (`Œuvre n° 78724`, Vasnetsov), vignette, métadonnées et voisines conformes.
3. Couleurs (« Style ») : bascule automatique en points colorés, pas de fausse carte tuilée ; retour aux tuiles en repassant sur « Vignettes ».
4. Filtre combiné (`Artiste : inconnu`) : bascule hors tuiles avec surbrillance correcte ; retour aux tuiles après « Tout effacer ».
5. Zoom sur un groupe (`Groupe 124 · Forêts`) : transition vers les vignettes puis la HD sans erreur.

## 3. Limites connues

- **Premier grand zoom** : parce que les 5 planches de 4096 px ne sont plus chargées à l'ouverture, le tout premier zoom qui franchit le seuil `24 px/œuvre` déclenche leur chargement et la création des 5 `IconLayer` (un pic unique de ~208 ms, puis 143,9 fps ensuite).
- **Mémoire GPU après grand zoom** : une fois les planches chargées en plus du cache de tuiles, la mémoire GPU atteint 475 Mio (+40 Mio par rapport aux 435 Mio initiaux).
- **Portée** : les tuiles ne couvrent que la carte principale (`layout === "map"`) sans filtre ni surbrillance. Les cartes des autres regards (`map:sujet`, etc.), la chronologie, la géographie et les axes conceptuels continuent d'utiliser les vignettes / points.
- **Sur corpus de 81k sur RX 7900 GRE**, la fluidité brute en déplacement était déjà au plafond de l'écran (144 fps) ; le gain réel des tuiles porte surtout sur la **mémoire GPU à l'ouverture (−97,6 %)**, le **transfert réseau (−91 %)**, la **mémoire JS (−63 %)** et la **qualité visuelle dès la vue d'ensemble** (vraie mosaïque anti-crénelée au lieu de points colorés) — des gains qui compteront encore davantage sur un corpus de 200k–500k œuvres ou sur un PC portable sans grosse carte graphique.

## 4. Décisions pour l'utilisateur / intégrateur

1. **Activation par défaut** : la fonction est laissée **activée par défaut** quand une pyramide existe (`pixplot tiles` lancé), avec une case « Tuiles précalculées (zooms éloignés) » dans le menu « Vue » pour la désactiver à volonté. Si l'utilisateur préfère éviter le pic de 208 ms au premier grand zoom sur son PC fixe (16 Go VRAM), il suffit de passer `tilesEnabled: false` par défaut dans `web/atlas-base.js`.
2. **Intégration dans `pixplot analyze` ?** Aujourd'hui `pixplot tiles` est une commande séparée (13 s CPU sur 81k). À décider si `pixplot analyze` doit aussi la proposer ou si elle reste optionnelle.
3. **Section `ARCHITECTURE.fr.md` / `.md` et version** : non modifiées sur cette branche (règle des copies de travail parallèles) ; à intégrer lors de la fusion dans `main`.
