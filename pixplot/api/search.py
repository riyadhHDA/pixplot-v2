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
from ..features.extract import OK as FEAT_OK
from ..features.store import FeatureStore
from ..index.regions import RegionIndex, encode_box, find_region_index, square_to_image
from ..index.textzones import ZoneIndex, find_zone_index
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
        self._zone_index = None

    # ------------------------------------------------------------------ disponibilité
    def text_run(self):
        runs = [r for r in list_runs("features", runs_dir=self.data.settings.runs_dir)
                if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")]
        return runs[-1] if runs else None

    def status(self) -> dict:
        regions = find_region_index(self.data.features, runs_dir=self.data.settings.runs_dir)
        text = self.text_run()
        zones = find_zone_index(self.data.settings.runs_dir)
        return {
            "zones": zones is not None,
            "zone_index": zones.id if zones else None,
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
        hits = self._region_index.search(vec, k=k, exclude=artwork_id, allowed=self.data.row_of)
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

    # ------------------------------------------------------------------ zone décrite par des mots
    def zones(self, query: str, k: int = 60) -> dict:
        """Les œuvres dont une zone (grilles 2×2 et 4×4) répond le mieux à la description."""
        if self._zone_index is None:
            run = find_zone_index(self.data.settings.runs_dir)
            if run is None:
                raise SearchUnavailable("Index des zones absent : lancez `pixplot zones`.")
            self._zone_index = ZoneIndex(run)
        with self._lock:
            self._load_text()
            vec = self._text_encoder.encode_text([query])[0]
        hits = self._zone_index.search(vec, k=k, allowed=self.data.row_of)
        results = [{**self.data.brief(h["id"]), "score": h["score"], "box": h["box"], "grid": h["grid"]} for h in hits]
        return {"query": query, "index": self._zone_index.run.id, "results": results}

    # ------------------------------------------------------------------ axes conceptuels (2D SigLIP, Impett & Offert 2024)
    def concept_axes(self, x_query: str, y_query: str, k: int = 8, include_coords: bool = True) -> dict:
        """Place le corpus selon deux concepts textuels (d'après *2D CLIP*, Impett & Offert, 2024).

        Chaque œuvre reçoit ses similarités cosinus avec ``x_query`` et ``y_query`` dans SigLIP 2,
        normalisées par centiles (p1–p99) pour l'affichage en nuage 2D, ainsi que les œuvres qui
        s'écartent le plus de la diagonale (plus proches d'un concept que de l'autre).
        """
        with self._lock:
            self._load_text()
            tvecs = np.asarray(self._text_encoder.encode_text([x_query, y_query]), dtype=np.float32)
            store = self._text_store
            n_store = len(store.ids)
            raw = np.empty((n_store, 2), dtype=np.float32)
            block = 65536
            for s in range(0, n_store, block):
                raw[s:s + block] = store.global_vectors[s:s + block].astype(np.float32) @ tvecs.T
            bad = store.status != FEAT_OK
            raw[bad] = np.nan
            id_to_srow = {int(i): r for r, i in enumerate(store.ids) if not bad[r]}

        n = len(self.data.ids)
        sx = np.full(n, np.nan, dtype=np.float32)
        sy = np.full(n, np.nan, dtype=np.float32)
        for r, aid in enumerate(self.data.ids):
            sr = id_to_srow.get(int(aid))
            if sr is not None:
                sx[r], sy[r] = raw[sr, 0], raw[sr, 1]

        valid = np.isfinite(sx) & np.isfinite(sy)
        vx, vy = sx[valid].astype(np.float64), sy[valid].astype(np.float64)
        n_valid = int(valid.sum())
        if n_valid == 0:
            raise SearchUnavailable("Aucune œuvre de cette analyse n'a de vecteur SigLIP 2.")

        def norm_axis(arr: np.ndarray, vals: np.ndarray) -> tuple[list[float | None], dict]:
            lo, med, hi = np.percentile(vals, [1, 50, 99]) if len(vals) >= 2 else (vals[0], vals[0], vals[0])
            span = float(hi - lo)
            coords: list[float | None] = []
            if include_coords:
                if span > 1e-6:
                    scaled = np.clip(2.0 * (arr - lo) / span - 1.0, -1.08, 1.08)
                else:
                    scaled = np.zeros_like(arr)
                coords = [round(float(v), 4) if np.isfinite(v) else None for v in scaled]
            return coords, {
                "min": round(float(vals.min()), 4),
                "median": round(float(med), 4),
                "max": round(float(vals.max()), 4),
            }

        cx, x_stats = norm_axis(sx, vx)
        cy, y_stats = norm_axis(sy, vy)

        std_x, std_y = float(vx.std()), float(vy.std())
        if n_valid >= 2 and std_x > 1e-9 and std_y > 1e-9:
            corr = float(np.mean((vx - vx.mean()) * (vy - vy.mean())) / (std_x * std_y))
            zx = (sx - vx.mean()) / std_x
            zy = (sy - vy.mean()) / std_y
        else:
            corr = 0.0
            zx = sx - float(vx.mean())
            zy = sy - float(vy.mean())
        diff = zx - zy  # > 0 : plus X que Y (sous la diagonale) ; < 0 : plus Y que X (au-dessus)

        def pick(metric: np.ndarray, take: int) -> list[dict]:
            ok_idx = np.flatnonzero(valid)
            if not len(ok_idx):
                return []
            take = min(take, len(ok_idx))
            vals = metric[ok_idx]
            order = ok_idx[np.argsort(-vals)[:take]]
            return [
                {
                    **self.data.brief(int(self.data.ids[r])),
                    "score_x": round(float(sx[r]), 4),
                    "score_y": round(float(sy[r]), 4),
                    "gap_z": round(float(diff[r]), 3),
                }
                for r in order
            ]

        out = {
            "x_query": x_query,
            "y_query": y_query,
            "features": store.run.id,
            "count": n_valid,
            "correlation": round(corr, 4),
            "x_stats": x_stats,
            "y_stats": y_stats,
            "extremes": {
                "top_x": pick(sx, k),
                "top_y": pick(sy, k),
                "more_x": pick(diff, k),
                "more_y": pick(-diff, k),
            },
            "note": (
                "Chaque œuvre est placée selon sa proximité avec les deux mots dans SigLIP 2. "
                "Ce qui s'écarte de la diagonale éclaire à la fois le corpus et l'imaginaire "
                "vectoriel du modèle (L. Impett et F. Offert, Visual Resources, 2024)."
            ),
        }
        if include_coords:
            out["x"] = cx
            out["y"] = cy
        return out
