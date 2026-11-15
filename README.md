# PixPlot v2

Exploration visuelle de grands corpus d'œuvres pour l'histoire de l'art.
L'architecture est décrite dans [ARCHITECTURE.md](ARCHITECTURE.md).

## Installation (développement)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -e ".[dev]"
pytest
```

PyTorch s'installe à part (roues ROCm d'AMD pour Windows), puis `pip install -e ".[ml]"`.

## Utilisation

```bash
pixplot doctor                          # Python, PyTorch, GPU
pixplot ingest "D:/MesImages"           # catalogue, vignettes, doublons
pixplot embed --limit 1000              # vecteurs DINOv3 (GPU) — reprenable
pixplot embed --encoder dinov2_vitb14_reg --limit 1000   # DINOv2, sans demande d'accès
pixplot embed --encoder colorhist       # même pipeline sans GPU, pour tester
pixplot import-metadata meta.csv       # artiste, date, style... (colonne path)
pixplot index                          # index FAISS du dernier run
pixplot similar 42 --html planche.html  # œuvres les plus proches
pixplot bench                          # comparer les runs (étiquettes, paires connues)
pixplot analyze --hdbscan              # groupes, carte UMAP, voisinages → data/maps/*.jpg
pixplot index --regions                # index des zones → « Chercher un détail » dans l'Atlas
pixplot embed --encoder siglip2_so400m # vecteurs texte↔image (puis pixplot index --encoder siglip2_so400m)
pixplot search-text "Annonciation dans un jardin"   # recherche en texte libre
pixplot serve --open                   # l'Atlas : carte interactive sur http://127.0.0.1:8765
pixplot pack --text "Annonciation" -k 20 --question "…"   # Research Pack (.zip) pour un LLM
pixplot mcp                            # serveur MCP : brancher Claude, voir docs/MCP.md
pixplot status
```

Installation du GPU (Windows natif, WSL2 en secours) et des modèles : [docs/INSTALL_GPU.md](docs/INSTALL_GPU.md).

## Où en est-on

- [x] Architecture, runs versionnés, prétraitement letterbox, vecteurs régionaux
- [x] Étape 1 : ingestion (catalogue SQLite, SHA-256, dHash, doublons, vignettes WebP),
      extraction par lots reprenable, recherche d'images similaires, planche HTML
- [x] Étape 1 validée sur la RX 7900 GRE (Windows natif) : DINOv3 B/16, 48 à 60 img/s
- [x] Étape 2 : index FAISS + banc d'essai (`pixplot bench`) — résultats dans ARCHITECTURE.md § 9
- [x] Étape 3 : e-means + HDBSCAN + UMAP → première carte (`pixplot analyze`)
- [x] Étape 4 : API + Atlas interactif (`pixplot serve --open`)
- [x] Étape 5 : recherche par détail (cadre tracé) + recherche en texte libre multilingue (SigLIP 2)
- [x] Étape 6 : serveur MCP (11 outils, images comprises) + Research Pack
- [ ] Étape 7 : comparateur, carnet de recherche, chronologie et géographie

## Licence et origine

PixPlot v2 est distribué sous licence **GPL-3.0** (voir [LICENSE](LICENSE)).

Il s'inspire de [PixPlot](https://github.com/YaleDHLab/pix-plot) (Yale DHLab, licence MIT),
réécrit de zéro. Le code original n'est pas inclus dans ce dépôt.
