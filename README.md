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

## Utilisation (étape 1)

```bash
pixplot doctor                          # Python, PyTorch, GPU
pixplot ingest "D:/MesImages"           # catalogue, vignettes, doublons
pixplot embed --limit 1000              # vecteurs DINOv3 (GPU) — reprenable
pixplot embed --encoder dinov2_vitb14_reg --limit 1000   # DINOv2, sans demande d'accès
pixplot embed --encoder colorhist       # même pipeline sans GPU, pour tester
pixplot similar 42 --html planche.html  # œuvres les plus proches
pixplot status
```

Installation du GPU (Windows natif, WSL2 en secours) et des modèles : [docs/INSTALL_GPU.md](docs/INSTALL_GPU.md).

## Où en est-on

- [x] Architecture, runs versionnés, prétraitement letterbox, vecteurs régionaux
- [x] Étape 1 : ingestion (catalogue SQLite, SHA-256, dHash, doublons, vignettes WebP),
      extraction par lots reprenable, recherche d'images similaires, planche HTML
- [ ] Étape 1 : validation DINOv3 sur la RX 7900 GRE (1 000 images, images/s, VRAM)
- [ ] Étape 2 : index FAISS + banc d'essai sur paires connues

## Licence et origine

PixPlot v2 est distribué sous licence **GPL-3.0** (voir [LICENSE](LICENSE)).

Il s'inspire de [PixPlot](https://github.com/YaleDHLab/pix-plot) (Yale DHLab, licence MIT),
réécrit de zéro. Le code original n'est pas inclus dans ce dépôt.
