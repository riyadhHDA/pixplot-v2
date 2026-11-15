"""Index FAISS sur les vecteurs globaux d'un run ``features``.

Contenu d'un run ``index/global_<encodeur>_<horodatage>/`` :

    manifest.json   run parent (features), type d'index, nombre de vecteurs
    global.faiss    l'index
    ids.npy         (M,) int64 : ligne de l'index → identifiant catalogue

Type d'index :
- ``flat`` (défaut) : recherche exacte par produit scalaire. Jusqu'à ~500 000 œuvres
  c'est le bon choix : ~1,5 Go de RAM, quelques millisecondes par requête.
- ``hnsw`` : recherche approchée, plus rapide au-delà d'un million d'œuvres.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..features.extract import OK
from ..runs import Run, create_run, list_runs

INDEX_FILE = "global.faiss"


def _faiss():
    try:
        import faiss
    except ImportError as exc:
        raise ImportError("Installez FAISS : pip install -e \".[ml]\"") from exc
    return faiss


def build_global_index(features: Run, kind: str = "flat", runs_dir: Path | None = None,
                       block: int = 65536) -> Run:
    faiss = _faiss()
    p = Path(features.path)
    ids = np.load(p / "ids.npy")
    status = np.load(p / "status.npy")
    vectors = np.load(p / "global.npy", mmap_mode="r")
    rows = np.flatnonzero(status == OK)
    if not len(rows):
        raise RuntimeError(f"Aucun vecteur valide dans {features.id}")
    dim = vectors.shape[1]

    if kind == "flat":
        index = faiss.IndexFlatIP(dim)
    elif kind == "hnsw":
        index = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = 80
    else:
        raise ValueError(f"Type d'index inconnu : {kind} (flat ou hnsw)")

    run = create_run("index", f"global_{features.manifest['name']}",
                     {"kind": kind, "dim": dim}, parent=features, runs_dir=runs_dir)
    try:
        for s in range(0, len(rows), block):  # par blocs : jamais tout en float32 en RAM d'un coup
            chunk = np.ascontiguousarray(vectors[rows[s:s + block]], dtype=np.float32)
            index.add(chunk)
        faiss.write_index(index, str(run.path / INDEX_FILE))
        np.save(run.path / "ids.npy", ids[rows].astype(np.int64))
    except BaseException as exc:
        run.fail(exc)
        raise
    run.complete(count=int(index.ntotal))
    return run


def find_index_for(features: Run, runs_dir: Path | None = None) -> Run | None:
    """Le dernier index terminé construit à partir de ce run de vecteurs."""
    for run in reversed(list_runs("index", runs_dir=runs_dir)):
        if run.manifest.get("parent") == features.id:
            return run
    return None


@dataclass
class GlobalIndex:
    run: Run
    index: object
    ids: np.ndarray

    @classmethod
    def open(cls, run: Run) -> "GlobalIndex":
        faiss = _faiss()
        return cls(run=run, index=faiss.read_index(str(Path(run.path) / INDEX_FILE)),
                   ids=np.load(Path(run.path) / "ids.npy"))

    def search(self, queries: np.ndarray, k: int = 10) -> tuple[np.ndarray, np.ndarray]:
        """Requêtes (Q, D) → (identifiants (Q, k), scores (Q, k)). -1 si moins de k résultats."""
        q = np.ascontiguousarray(np.atleast_2d(queries), dtype=np.float32)
        scores, rows = self.index.search(q, k)
        out = np.where(rows >= 0, self.ids[np.clip(rows, 0, None)], -1)
        return out, scores
