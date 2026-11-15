"""Moteurs de recherche de l'Atlas, chargés à la première utilisation :

- **par détail** : le modèle de l'analyse (DINOv3) + l'index des zones ;
- **par texte** : SigLIP 2 + ses vecteurs d'images (run ``features/siglip2_*``).

Un verrou protège le GPU : une seule requête de modèle à la fois.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from ..encoders.registry import get_encoder
from ..features.store import FeatureStore
from ..index.regions import RegionIndex, encode_box, find_region_index, square_to_image
from ..runs import list_runs


class SearchUnavailable(RuntimeError):
    """La recherche demandée n'est pas prête (index ou vecteurs manquants)."""


class SearchEngines:
    def __init__(self, data):
        self.data = data
        self._lock = threading.Lock()
        self._region_encoder = None
        self._region_index = None
        self._text_encoder = None
        self._text_store = None
        self._text_index = None

    # ------------------------------------------------------------------ disponibilité
    def text_run(self):
        runs = [r for r in list_runs("features", runs_dir=self.data.settings.runs_dir)
                if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")]
        return runs[-1] if runs else None

    def status(self) -> dict:
        regions = find_region_index(self.data.features, runs_dir=self.data.settings.runs_dir)
        text = self.text_run()
        return {
            "region": regions is not None,
            "region_index": regions.id if regions else None,
            "text": text is not None,
            "text_features": text.id if text else None,
        }

    # ------------------------------------------------------------------ détail
    def _load_region(self):
        if self._region_index is None:
            run = find_region_index(self.data.features, runs_dir=self.data.settings.runs_dir)
            if run is None:
                raise SearchUnavailable("Index des zones absent : lancez `pixplot index --regions`.")
            self._region_index = RegionIndex.open(run)
        if self._region_encoder is None:
            p = self.data.features.manifest["params"]
            kwargs = {"input_size": p.get("input_size")}
            if p.get("source") == "meta":
                kwargs["weights"] = str(Path("weights") / p["weights"])
            elif p.get("source") == "huggingface":
                kwargs["hf_model"] = p.get("weights")
            self._region_encoder = get_encoder(p["encoder"], **kwargs)

    def region(self, artwork_id: int, box, k: int = 30) -> dict:
        path = self.data.original_path(artwork_id)
        if path is None or not path.exists():
            raise KeyError(artwork_id)
        with self._lock:
            self._load_region()
            vec = encode_box(self._region_encoder, path, box)
        hits = self._region_index.search(vec, k=k, exclude=artwork_id)
        sizes = self.data.sizes([h["id"] for h in hits])
        results = []
        for h in hits:
            if h["id"] not in self.data.row_of:
                continue
            w, hgt = sizes.get(h["id"], (1, 1))
            results.append({**self.data.brief(h["id"]), "score": h["score"],
                            "box": square_to_image(h["square_box"], w, hgt), "grid": h["grid"]})
        return {"query": {"id": artwork_id, "box": [round(float(v), 4) for v in box]},
                "index": self._region_index.run.id, "results": results}

    # ------------------------------------------------------------------ texte
    def _load_text(self):
        if self._text_store is None:
            run = self.text_run()
            if run is None:
                raise SearchUnavailable("Vecteurs SigLIP 2 absents : lancez `pixplot embed --encoder siglip2_so400m`.")
            self._text_store = FeatureStore.open(run)
            try:
                from ..index.faiss_index import GlobalIndex, find_index_for
                idx = find_index_for(run, runs_dir=self.data.settings.runs_dir)
                self._text_index = GlobalIndex.open(idx) if idx else None
            except ImportError:
                self._text_index = None
        if self._text_encoder is None:
            p = self._text_store.run.manifest["params"]
            self._text_encoder = get_encoder(p["encoder"], hf_model=p.get("weights"),
                                             input_size=p.get("input_size"))

    def text(self, query: str, k: int = 60) -> dict:
        with self._lock:
            self._load_text()
            vec = self._text_encoder.encode_text([query])[0]
        if self._text_index is not None:
            found, scores = self._text_index.search(vec, k=k * 2)
            pairs = [(int(i), float(s)) for i, s in zip(found[0], scores[0]) if i >= 0]
        else:
            pairs = self._text_store.search(vec, k=k * 2)
        results = [{**self.data.brief(i), "score": round(s, 4)} for i, s in pairs if i in self.data.row_of][:k]
        return {"query": query, "features": self._text_store.run.id, "results": results}
