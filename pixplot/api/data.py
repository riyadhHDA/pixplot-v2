"""Données servies par l'API : une analyse (carte, groupes, voisinages) + le catalogue.

Tout est chargé une fois au démarrage (quelques Mo pour 500 000 œuvres, hors vignettes).
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..catalog import db
from ..catalog.metadata import get_metadata
from ..config import Settings
from ..runs import Run, latest_run

LABEL_KEYS = ("artist", "date", "genre", "style")
MAX_CATEGORIES = 2000  # au-delà, une métadonnée n'est pas proposée pour colorer la carte


@dataclass
class AtlasData:
    settings: Settings
    analysis: Run
    features: Run
    ids: np.ndarray
    coords: np.ndarray
    clusters: np.ndarray
    atypicality: np.ndarray
    neighbors: np.ndarray
    neighbor_scores: np.ndarray
    hdbscan: np.ndarray | None
    cluster_summary: list[dict]
    meta: dict[int, dict[str, str]]
    row_of: dict[int, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ chargement
    @classmethod
    def load(cls, settings: Settings, analysis: Run | None = None) -> "AtlasData":
        analysis = analysis or latest_run("analysis", runs_dir=settings.runs_dir)
        if analysis is None:
            raise RuntimeError("Aucune analyse terminée : lancez d'abord `pixplot analyze`.")
        p = Path(analysis.path)
        parent = analysis.manifest["parent"]  # "features/<nom>"
        features = Run.load(settings.runs_dir / parent)
        ids = np.load(p / "ids.npy")
        conn = cls._conn(settings)
        meta = get_metadata(conn, ids.tolist())
        conn.close()
        h = p / "hdbscan.npy"
        data = cls(
            settings=settings, analysis=analysis, features=features, ids=ids,
            coords=np.load(p / "coords.npy"), clusters=np.load(p / "clusters.npy"),
            atypicality=np.load(p / "atypicality.npy"), neighbors=np.load(p / "neighbors.npy"),
            neighbor_scores=np.load(p / "neighbor_scores.npy"),
            hdbscan=np.load(h) if h.exists() else None,
            cluster_summary=json.loads((p / "clusters.json").read_text(encoding="utf-8")),
            meta=meta,
        )
        data.row_of = {int(i): r for r, i in enumerate(ids)}
        return data

    @staticmethod
    def _conn(settings: Settings) -> sqlite3.Connection:
        return db.connect(settings.catalog_path)

    # ------------------------------------------------------------------ helpers
    def label(self, artwork_id: int) -> str:
        m = self.meta.get(artwork_id, {})
        bits = [m[k] for k in LABEL_KEYS if m.get(k) and not m[k].lower().startswith("unknown")]
        return " · ".join(bits) if bits else f"Œuvre {artwork_id}"

    def category_keys(self) -> list[str]:
        counts = Counter(k for m in self.meta.values() for k in m)
        keys = [k for k, c in counts.most_common() if c >= max(2, len(self.ids) // 20)]
        out = []
        for k in keys:
            distinct = {m.get(k) for m in self.meta.values()}
            if len(distinct) <= MAX_CATEGORIES:
                out.append(k)
        return out

    # ------------------------------------------------------------------ réponses
    def info(self) -> dict:
        return {
            "analysis": self.analysis.id,
            "features": self.features.id,
            "encoder": self.features.manifest["params"].get("encoder"),
            "input_size": self.features.manifest["params"].get("input_size"),
            "count": int(len(self.ids)),
            "clusters": len(self.cluster_summary),
            "hdbscan": self.hdbscan is not None,
            "metadata_keys": self.category_keys(),
            "analysis_params": self.analysis.manifest.get("params", {}),
        }

    def map_payload(self) -> dict:
        """Colonnes compactes : une liste par attribut plutôt qu'un objet par œuvre."""
        cats = {}
        for key in self.category_keys():
            values = [self.meta[int(i)].get(key) or "" for i in self.ids]
            uniques = sorted(set(values), key=lambda v: (v == "" or v.lower().startswith("unknown"), v))
            index = {v: n for n, v in enumerate(uniques)}
            cats[key] = {"values": uniques, "codes": [index[v] for v in values]}
        conn = self._conn(self.settings)
        sizes = {r[0]: (r[1] or 1) / max(r[2] or 1, 1)
                 for r in conn.execute("SELECT id, width, height FROM artworks WHERE status = 'ok'")}
        conn.close()
        payload = {
            "ids": self.ids.tolist(),
            "aspect": [round(sizes.get(int(i), 1.0), 3) for i in self.ids],  # largeur / hauteur
            "x": np.round(self.coords[:, 0], 5).tolist(),
            "y": np.round(self.coords[:, 1], 5).tolist(),
            "cluster": self.clusters.tolist(),
            "atypicality": np.round(self.atypicality, 3).tolist(),
            "categories": cats,
        }
        if self.hdbscan is not None:
            payload["hdbscan"] = self.hdbscan.tolist()
        return payload

    def clusters_payload(self) -> list[dict]:
        out = []
        for entry in self.cluster_summary:
            members = self.ids[self.clusters == entry["cluster"]]
            rows = [self.row_of[int(i)] for i in members]
            dominant = {}
            for key in ("artist", "style", "genre", "date"):
                vals = [self.meta[int(i)].get(key) for i in members]
                vals = [v for v in vals if v and not v.lower().startswith("unknown")]
                if vals:
                    dominant[key] = [{"value": v, "share": round(c / len(members), 3)}
                                     for v, c in Counter(vals).most_common(3)]
            out.append({**entry, "number": entry["cluster"] + 1,
                        "center": np.median(self.coords[rows], axis=0).round(5).tolist(),
                        "dominant": dominant})
        return out

    def artwork(self, artwork_id: int, k: int = 20) -> dict | None:
        r = self.row_of.get(artwork_id)
        if r is None:
            return None
        conn = self._conn(self.settings)
        row = conn.execute("SELECT * FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        sources = {rr[0]: rr[1] for rr in conn.execute(
            "SELECT key, source FROM metadata WHERE artwork_id = ?", (artwork_id,))}
        conn.close()
        neigh = []
        for nid, score in zip(self.neighbors[r][:k], self.neighbor_scores[r][:k]):
            if nid < 0:
                continue
            neigh.append({"id": int(nid), "score": round(float(score), 4), "label": self.label(int(nid)),
                          "cluster": int(self.clusters[self.row_of[int(nid)]]) + 1
                          if int(nid) in self.row_of else None})
        return {
            "id": artwork_id,
            "label": self.label(artwork_id),
            "filename": Path(row["path"]).name,
            "width": row["width"], "height": row["height"], "format": row["format"],
            "metadata": self.meta.get(artwork_id, {}),
            "metadata_sources": sources,
            "cluster": int(self.clusters[r]) + 1,
            "hdbscan": int(self.hdbscan[r]) if self.hdbscan is not None else None,
            "atypicality": round(float(self.atypicality[r]), 3),
            "x": round(float(self.coords[r, 0]), 5), "y": round(float(self.coords[r, 1]), 5),
            "neighbors": neigh,
            "provenance": {"features": self.features.id, "analysis": self.analysis.id,
                           "encoder": self.features.manifest["params"].get("encoder")},
        }

    def search(self, q: str, limit: int = 5000) -> list[int]:
        """Œuvres dont une métadonnée ou le nom de fichier contient ``q`` (sans casse)."""
        q = q.strip().lower()
        if not q:
            return []
        if q.isdigit() and int(q) in self.row_of:
            return [int(q)]
        conn = self._conn(self.settings)
        names = {r["id"]: Path(r["path"]).name.lower() for r in conn.execute("SELECT id, path FROM artworks")}
        conn.close()
        hits = []
        for i in self.ids.tolist():
            m = self.meta.get(i, {})
            if q in names.get(i, "") or any(q in v.lower() for v in m.values() if v):
                hits.append(i)
                if len(hits) >= limit:
                    break
        return hits

    def original_path(self, artwork_id: int) -> Path | None:
        if artwork_id not in self.row_of:
            return None
        conn = self._conn(self.settings)
        row = conn.execute("SELECT path FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        conn.close()
        return Path(row["path"]) if row else None
