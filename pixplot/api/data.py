"""Données servies par l'API : une analyse (carte, groupes, voisinages) + le catalogue.

Tout est chargé une fois au démarrage (quelques Mo pour 500 000 œuvres, hors vignettes).
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..catalog import db
from ..catalog.metadata import get_metadata
from ..analysis import communities, critique, disagreements, duplicates, order, sae
from ..analysis import iconclass
from ..analysis.naming import load_names
from ..analysis.spacemaps import available_maps, load_space_map
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
HDBSCAN_MAX_ISOLATED = 0.3  # au-delà, les familles HDBSCAN ne sont pas montrées
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
    iconclass: dict[int, dict] = field(default_factory=dict)
    row_of: dict[int, int] = field(default_factory=dict)
    suspect_of: dict[int, list] = field(default_factory=dict)
    _spaces: object = None
    _notions_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

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
            iconclass=iconclass.load_names(analysis),
            suspects=load_suspects(analysis),
            meta=meta,
        )
        data.row_of = {int(i): r for r, i in enumerate(ids)}
        if data.hdbscan is not None and (data.hdbscan < 0).mean() > HDBSCAN_MAX_ISOLATED:
            # HDBSCAN inexploitable sur ce corpus (cf. ARCHITECTURE.md § 11) : on ne l'affiche
            # pas, plutôt que de déclarer « à part » la moitié des œuvres.
            data.hdbscan = None
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
        from .. import __version__

        return {
            "version": __version__,
            "analysis": self.analysis.id,
            "features": self.features.id,
            "encoder": self.features.manifest["params"].get("encoder"),
            "input_size": self.features.manifest["params"].get("input_size"),
            "count": int(len(self.ids)),
            "clusters": len(self.cluster_summary),
            "hdbscan": self.hdbscan is not None,
            "metadata_keys": self.category_keys(),
            "named_groups": bool(self.names),
            "iconclass": bool(self.iconclass),
            "space_maps": available_maps(self.analysis),
            "communities": communities.available(self.analysis),
            "places": self.place_counts(),
            "disagreements": self.disagreement_counts(),
            "duplicates": (self._duplicates() or {}).get("counts", {}),
            "notions": self.notions_info(),
            "main_space": self.spaces.main,
            "suspects": (self.suspects or {}).get("counts", {}),
            "annotated_pairs": self.annotated_pair_counts(),
            "suspects_space": (self.suspects or {}).get("space"),
            "analysis_params": self.analysis.manifest.get("params", {}),
        }

    def places_payload(self) -> dict:
        """Lieux typés et datés (table ``places``), en colonnes ; ``row`` = rang de l'œuvre
        dans la carte. Les coordonnées des métadonnées (latitude/longitude) sans type
        apparaissent comme « lieu non précisé »."""
        from ..catalog.places import PLACE_TYPES, load_places

        conn = self._conn(self.settings)
        rows = [r for r in load_places(conn) if r["artwork_id"] in self.row_of]
        conn.close()
        cols = {k: [] for k in ("row", "type", "name", "lat", "lon", "year", "date", "source")}
        for r in rows:
            cols["row"].append(self.row_of[r["artwork_id"]])
            for k in ("type", "name", "lat", "lon", "year", "date", "source"):
                cols[k].append(r[k])
        coords = self.coordinates()
        if coords:
            for n, (la, lo) in enumerate(zip(*coords)):
                if la is not None and lo is not None:
                    for k, v in (("row", n), ("type", "non_precise"), ("name", ""), ("lat", la), ("lon", lo),
                                 ("year", None), ("date", ""), ("source", "métadonnées latitude/longitude")):
                        cols[k].append(v)
        counts: dict[str, int] = {}
        for t in cols["type"]:
            counts[t] = counts.get(t, 0) + 1
        return {"types": [{"key": t, "label": PLACE_TYPES[t][0], "about": PLACE_TYPES[t][1], "count": counts[t]}
                          for t in PLACE_TYPES if t in counts], **cols}

    def place_counts(self) -> dict[str, int]:
        if getattr(self, "_place_counts", None) is None:
            self._place_counts = {t["key"]: t["count"] for t in self.places_payload()["types"]}
        return self._place_counts

    def corpus_report(self) -> dict:
        """Bilan critique du corpus (voir ``analysis.critique``), mis en cache."""
        if getattr(self, "_report", None) is None:
            conn = self._conn(self.settings)
            sources: dict = {}
            for key, src, n in conn.execute("SELECT key, source, COUNT(*) FROM metadata GROUP BY key, source"):
                sources.setdefault(key, Counter())[src or ""] += n
            conn.close()
            pl = self.places_payload()
            places = len({r for r, la in zip(pl["row"], pl["lat"]) if la is not None})
            meta = {int(i): self.meta.get(int(i), {}) for i in self.ids}
            self._report = critique.corpus_report(meta, sources, self.years(), places)
        return self._report

    def annotated_pair_counts(self) -> dict[str, int]:
        from ..analysis.pairbench import load_pairs, pairs_path

        out: dict[str, int] = {}
        for p in load_pairs(pairs_path(self.settings)):
            if p.origin == "annotée":
                out[p.status] = out.get(p.status, 0) + 1
        return out

    def _disagreements(self) -> dict | None:
        if not hasattr(self, "_dis_cache"):
            self._dis_cache = disagreements.load(self.analysis)
        return self._dis_cache

    def disagreement_counts(self) -> dict[str, int]:
        d = self._disagreements()
        return {k: len(v) for k, v in d["pairs"].items()} if d else {}

    def disagreements_payload(self, near: str, far: str, offset: int = 0, limit: int = 40) -> dict | None:
        d = self._disagreements()
        if not d or f"{near}>{far}" not in d["pairs"]:
            return None
        items = d["pairs"][f"{near}>{far}"]
        page = [{**x, "label_a": self.label(x["a"]), "label_b": self.label(x["b"])}
                for x in items[offset:offset + limit]]
        return {"near": near, "far": far, "total": len(items), "offset": offset, "items": page,
                "rule": f"rang ≤ {d['max_rank']} selon « {near} », centile < {d['max_centile']} selon « {far} »",
                "combos": list(d["pairs"]), "n": d["n"]}

    def _duplicates(self) -> dict | None:
        if not hasattr(self, "_dup_cache"):
            self._dup_cache = duplicates.load(self.analysis)
        return self._dup_cache

    def _notions(self) -> tuple[Run, dict] | None:
        """Dernier run de notions apprises et son ``notions.json``, mis en cache."""
        if not hasattr(self, "_notions_cache"):
            run = sae.latest_notions_run(self.settings.runs_dir)
            meta = sae.load_notions(run) if run is not None else None
            self._notions_cache = (run, meta) if run is not None and meta is not None else None
        return self._notions_cache

    def _notions_index(self) -> dict | None:
        """Index inversé exact par notion, calculé une seule fois à la première consultation."""
        pair = self._notions()
        if pair is None:
            return None
        with self._notions_lock:
            if not hasattr(self, "_notions_idx"):
                run, _ = pair
                self._notions_idx = sae.encode_index(run, self.settings.runs_dir, allowed_ids=set(self.row_of))
        return self._notions_idx

    def _notion_count(self, feat: dict) -> int:
        idx = getattr(self, "_notions_idx", None)
        f = int(feat["feature"])
        if idx is not None and 0 <= f < idx["n_features"]:
            return int(idx["offsets"][f + 1] - idx["offsets"][f])
        return max(1, round(float(feat.get("frequency", 0.0)) * len(self.ids)))

    def notions_info(self) -> dict | None:
        pair = self._notions()
        if pair is None:
            return None
        run, meta = pair
        feats = meta.get("features", [])
        named = sum(1 for f in feats if sae.notion_label(f)[1])
        framed = None
        fid = sae.framed_feature(run, meta)
        if fid is not None:
            f88 = next((f for f in feats if int(f["feature"]) == fid), None)
            if f88 is not None:
                framed = {"feature": fid, "label": sae.FRAMED_LABEL,
                          "count": self._notion_count(f88)}
        return {"run": run.id, "space": meta.get("space", "sujet"), "count": len(feats),
                "named": named, "z_min": sae.ICONCLASS_Z_MIN, "framed": framed}

    def notions_payload(self) -> dict | None:
        """Liste des notions vivantes (numéro, étiquette Iconclass si z ≥ 5 sinon « sans nom »,
        nombre d'œuvres actives)."""
        pair = self._notions()
        if pair is None:
            return None
        run, meta = pair
        items = []
        named_count = 0
        for f in meta.get("features", []):
            label, is_named = sae.notion_label(f)
            if is_named:
                named_count += 1
            ic = f.get("iconclass")
            ic_out = ({"notation": ic["notation"], "fr": ic["fr"], "z": ic["z"],
                       "url": iconclass.link(ic["notation"])}
                      if is_named and ic else None)
            items.append({
                "feature": int(f["feature"]),
                "label": label,
                "named": is_named,
                "iconclass": ic_out,
                "meta": sae.meta_label(f),
                "count": self._notion_count(f),
                "frequency": f.get("frequency", 0.0),
                "labels": f.get("labels", {}),
                "top": [int(i) for i in f.get("top", []) if int(i) in self.row_of],
            })
        items.sort(key=lambda x: x["feature"])
        info = self.notions_info()
        return {"run": run.id, "space": meta.get("space", "sujet"), "z_min": sae.ICONCLASS_Z_MIN,
                "n": int(len(self.ids)), "total": len(items), "named": named_count,
                "dead": meta.get("dead", 0), "explained_variance": meta.get("explained_variance", {}),
                "framed": info["framed"] if info else None, "items": items}

    def notion_detail_payload(self, feature: int, offset: int = 0, limit: int = 40,
                              highlight_limit: int = 500) -> dict | None:
        """Œuvres actives d'une notion, triées par activation décroissante."""
        pair = self._notions()
        if pair is None:
            return None
        run, meta = pair
        feat = next((f for f in meta.get("features", []) if int(f["feature"]) == feature), None)
        if feat is None:
            return None
        label, is_named = sae.notion_label(feat)
        ic = feat.get("iconclass")
        ic_out = ({"notation": ic["notation"], "fr": ic["fr"], "z": ic["z"],
                   "url": iconclass.link(ic["notation"])}
                  if is_named and ic else None)
        idx = self._notions_index()
        exact = False
        if idx is not None and 0 <= feature < idx["n_features"]:
            lo, hi = int(idx["offsets"][feature]), int(idx["offsets"][feature + 1])
            all_ids = idx["ids"][lo:hi]
            all_scores = idx["scores"][lo:hi]
            total = int(hi - lo)
            page_ids = all_ids[offset:offset + limit].tolist()
            page_scores = [round(float(s), 3) for s in all_scores[offset:offset + limit]]
            hl_ids = all_ids[:highlight_limit].tolist()
            exact = True
        else:
            fallback = [int(i) for i in feat.get("top", []) if int(i) in self.row_of]
            total = len(fallback)
            page_ids = fallback[offset:offset + limit]
            page_scores = [None] * len(page_ids)
            hl_ids = fallback[:highlight_limit]
        items = [{**self.brief(int(i)), "score": sc} for i, sc in zip(page_ids, page_scores)]
        is_framed = feature == sae.framed_feature(run, meta)
        return {
            "feature": feature,
            "label": label,
            "named": is_named,
            "iconclass": ic_out,
            "editorial_label": sae.FRAMED_LABEL if is_framed else "",
            "meta": sae.meta_label(feat),
            "space": meta.get("space", "sujet"),
            "run": run.id,
            "labels": feat.get("labels", {}),
            "frequency": feat.get("frequency", 0.0),
            "total": total,
            "offset": offset,
            "limit": limit,
            "exact": exact,
            "highlight_ids": hl_ids,
            "items": items,
        }

    def duplicates_payload(self, level: str = "same", conflicts: bool = False, offset: int = 0,
                           limit: int = 40) -> dict | None:
        """Paires de doublons ou de variantes (SSCD), avec les étiquettes de chaque œuvre."""
        d = self._duplicates()
        if not d:
            return None
        items = [p for p in d["pairs"] if p["level"] == level and (p["conflicts"] or not conflicts)]
        page = [{**p, "label_a": self.label(p["a"]), "label_b": self.label(p["b"]),
                 "meta_a": {k: self.meta.get(p["a"], {}).get(k) for k in duplicates.KEYS},
                 "meta_b": {k: self.meta.get(p["b"], {}).get(k) for k in duplicates.KEYS}}
                for p in items[offset:offset + limit]]
        return {"level": level, "conflicts": conflicts, "total": len(items), "offset": offset, "items": page,
                "counts": d["counts"], "rule": f"SSCD centré : même image dès {d['same']}, variante dès {d['variant']}",
                "sscd": d["sscd"]}

    def communities_payload(self, space: str) -> dict | None:
        """Groupes et familles Leiden d'un regard, alignés sur ``ids`` (-1 : œuvre absente)."""
        c = communities.load(self.analysis, space)
        if c is None:
            return None
        pos = {int(i): n for n, i in enumerate(c["ids"])}
        rows = [pos.get(int(i), -1) for i in self.ids]
        group = [int(c["groups"][r]) if r >= 0 else -1 for r in rows]
        return {"space": space, "resolution": c.get("resolution"), "n_groups": int(c["groups"].max()) + 1,
                "n_families": int(c["families"].max()) + 1, "group": group,
                "family": [int(c["families"][g]) if g >= 0 else -1 for g in group]}

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
        hc = order.load(self.analysis)
        if hc is not None and len(hc) == len(self.ids):     # entropie et complexité (pixplot ordre)
            payload["entropy"] = [None if np.isnan(v) else round(float(v), 3) for v in hc[:, 0]]
            payload["complexity"] = [None if np.isnan(v) else round(float(v), 3) for v in hc[:, 1]]
        years = self.years()
        if sum(y is not None for y in years) >= max(2, len(years) // 20):
            payload["year"] = years
        coords = self.coordinates()
        if coords and sum(v is not None for v in coords[0]) >= 2:
            payload["lat"], payload["lon"] = coords
        return payload

    def space_map_payload(self, key: str) -> dict | None:
        """Positions des œuvres sur la carte d'un autre regard (None hors de cet espace)."""
        coords = load_space_map(self.analysis, key)
        if coords is None:
            return None
        xs = [None if np.isnan(v) else round(float(v), 5) for v in coords[:, 0]]
        ys = [None if np.isnan(v) else round(float(v), 5) for v in coords[:, 1]]
        return {"space": key, "x": xs, "y": ys}

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
                        "iconclass": iconclass.shown_terms(self.iconclass.get(entry["cluster"], {})),
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
            "metadata_source_notes": {k: n for k, s in sources.items() if (n := critique.source_note(s))},
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
