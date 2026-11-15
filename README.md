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

PyTorch s'installe à part (roues ROCm d'AMD sous WSL2), puis `pip install -e ".[ml]"`.

## Où en est-on

- [x] Architecture, structure du projet, runs versionnés, prétraitement letterbox,
      vecteurs régionaux, encodeur DINOv3 (écrit, pas encore testé sur GPU)
- [ ] Étape 1 : ingestion + extraction sur 1 000 images

## Licence et origine

PixPlot v2 est distribué sous licence **GPL-3.0** (voir [LICENSE](LICENSE)).

Il s'inspire de [PixPlot](https://github.com/YaleDHLab/pix-plot) (Yale DHLab, licence MIT),
réécrit de zéro. Le code original n'est pas inclus dans ce dépôt.
