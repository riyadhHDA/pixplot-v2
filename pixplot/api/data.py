"""Données servies par l'API : une analyse (carte, groupes, voisinages) + le catalogue.

Tout est chargé une fois au démarrage (quelques Mo pour 500 000 œuvres, hors vignettes).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..catalog import db
from ..catalog.metadata import get_metadata
from ..analysis.naming import load_names
from ..analysis.suspects import load_suspects
from ..config import Settings
from ..runs import Run, latest_run

LABEL_KEYS = ("artist", "date", "genre", "style")
DATE_KEYS = ("date", "year", "annee", "année", "datation", "created", "date_creation", "dated")
LAT_KEYS = ("latitude", "lat")
LON_KEYS = ("longitude", "lon", "lng")
YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-4][0-9]|[5-9][0-9]{2})(?!\d)")


def parse_year(value: str | None) -> int | None:
    """Première année lisible : « vers 1650 », « 1650-1655 », « c. 1890 » → 1650, 1650, 1890."""
    if not value:
        return None
    m = YEAR_RE.search(str(value))
    return int(m.group(1)) if m else None


def parse_coord(value: str | None, limit: float) -> float | None:
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v if -limit <= v <= limit else None
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
    names: dict[int, dict]
    suspects: dict | None
    meta: dict[int, dict[str, str]]
    row_of: dict[int, int] = field(default_factory=dict)
    suspect_of: dict[int, list] = field(default_factory=dict)
    _spaces: object = None

    @property
    def spaces(self):
        """Espaces de ressemblance disponibles (voir ``spaces.py``), ouverts à la demande."""
        if self._spaces is None:
            from .spaces import Spaces
            self._spaces = Spaces(self)
        return self._spaces

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
            names=load_names(analysis),
            suspects=load_suspects(analysis),
            meta=meta,
        )
        data.row_of = {int(i): r for r, i in enumerate(ids)}
        data.suspect_of = {}
        for key, items in (data.suspects or {}).get("suspects", {}).items():
            for d in items:
                data.suspect_of.setdefault(d["id"], []).append({"key": key, **{k: v for k, v in d.items() if k != "id"}})
        return data

    # ------------------------------------------------------------------ dates et lieux
    def years(self) -> list[int | None]:
        keys = [k for k in DATE_KEYS if any(k in m for m in self.meta.values())]
        out = []
        for i in self.ids:
            m = self.meta.get(int(i), {})
            out.append(next((y for k in keys if (y := parse_year(m.get(k))) is not None), None))
        return out

    def coordinates(self) -> tuple[list[float | None], list[float | None]] | None:
        keys = {k for m in self.meta.values() for k in m}
        lat_key = next((k for k in LAT_KEYS if k in keys), None)
        lon_key = next((k for k in LON_KEYS if k in keys), None)
        if not lat_key or not lon_key:
            return None
        lat = [parse_coord(self.meta.get(int(i), {}).get(lat_key), 90) for i in self.ids]
        lon = [parse_coord(self.meta.get(int(i), {}).get(lon_key), 180) for i in self.ids]
        return lat, lon

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
            "named_groups": bool(self.names),
            "suspects": (self.suspects or {}).get("counts", {}),
            "suspects_space": (self.suspects or {}).get("space"),
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
        years = self.years()
        if sum(y is not None for y in years) >= max(2, len(years) // 20):
            payload["year"] = years
        coords = self.coordinates()
        if coords and sum(v is not None for v in coords[0]) >= 2:
            payload["lat"], payload["lon"] = coords
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
            named = self.names.get(entry["cluster"], {})
            out.append({**entry, "number": entry["cluster"] + 1,
                        "name": named.get("name") or "", "terms": named.get("terms", []),
                        "metadata_name": named.get("metadata_name", ""),
                        "center": np.median(self.coords[rows], axis=0).round(5).tolist(),
                        "dominant": dominant})
        return out

    def neighbor_list(self, artwork_id: int, k: int = 20, space: str | None = None) -> list[dict]:
        """Voisines dans l'espace de l'analyse (précalculées) ou dans un autre espace."""
        r = self.row_of[artwork_id]
        if space and space != self.spaces.main:
            pairs = self.spaces.neighbors(space, artwork_id, k)
        else:
            pairs = [(int(n), float(s)) for n, s in zip(self.neighbors[r][:k], self.neighbor_scores[r][:k]) if n >= 0]
        return [{"id": nid, "score": round(score, 4), "label": self.label(nid),
                 "cluster": int(self.clusters[self.row_of[nid]]) + 1 if nid in self.row_of else None}
                for nid, score in pairs]

    def artwork(self, artwork_id: int, k: int = 20, space: str | None = None) -> dict | None:
        r = self.row_of.get(artwork_id)
        if r is None:
            return None
        conn = self._conn(self.settings)
        row = conn.execute("SELECT * FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        sources = {rr[0]: rr[1] for rr in conn.execute(
            "SELECT key, source FROM metadata WHERE artwork_id = ?", (artwork_id,))}
        conn.close()
        neigh = self.neighbor_list(artwork_id, k, space)
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
            "space": space or self.spaces.main,
            "label_checks": self.suspect_of.get(artwork_id, []),
            "label_checks_space": (self.suspects or {}).get("space"),
            "group_name": self.names.get(int(self.clusters[r]), {}).get("name", ""),
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

    def brief(self, artwork_id: int) -> dict:
        """Résumé d'une œuvre pour une liste de résultats."""
        r = self.row_of[artwork_id]
        return {"id": artwork_id, "label": self.label(artwork_id), "cluster": int(self.clusters[r]) + 1}

    def sizes(self, artwork_ids: list[int]) -> dict[int, tuple[int, int]]:
        if not artwork_ids:
            return {}
        conn = self._conn(self.settings)
        q = f"SELECT id, width, height FROM artworks WHERE id IN ({','.join('?' * len(artwork_ids))})"
        out = {r[0]: (r[1] or 1, r[2] or 1) for r in conn.execute(q, artwork_ids)}
        conn.close()
        return out

    def original_path(self, artwork_id: int) -> Path | None:
        if artwork_id not in self.row_of:
            return None
        conn = self._conn(self.settings)
        row = conn.execute("SELECT path FROM artworks WHERE id = ?", (artwork_id,)).fetchone()
        conn.close()
        return Path(row["path"]) if row else None
