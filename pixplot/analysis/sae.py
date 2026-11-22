"""Ouvrir les vecteurs : auto-encodeur parcimonieux (« notions » apprises par un regard).

Un vecteur de SigLIP 2 ou de DINOv3 mélange tout ce que le modèle a vu dans l'œuvre. Un
auto-encodeur parcimonieux apprend un dictionnaire de quelques milliers de directions, les
**notions**, tel que chaque œuvre se reconstruise avec une poignée d'entre elles seulement (ici 16).
On regarde ensuite, pour chaque notion, les œuvres qui l'allument le plus : c'est une façon de voir
ce que le modèle a réellement appris, notion par notion (Bricken et al., 2023 ; Gao et al., 2024).

Variante **Matryoshka** (Bussmann et al., ICML 2025) : la reconstruction est aussi demandée avec les
seules 64, 256 et 1 024 premières notions ; les premières sont donc les plus générales, les
suivantes affinent. Entraîné sur les vecteurs déjà calculés, sur processeur, en quelques minutes.

Lecture de chaque notion : ses œuvres les plus fortes, ce que leurs métadonnées ont en commun
(style, genre, artiste, siècle) comparé au hasard, et, pour un regard qui parle (SigLIP 2), la notion
Iconclass la plus proche (même méthode que les noms de groupes, § 23). Ce sont des pistes de lecture
du modèle, pas des catégories de l'histoire de l'art.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Callable

import numpy as np

PREFIXES = (64, 256, 1024)
SEED = 0
ICONCLASS_Z_MIN = 5.0          # en dessous, le nom Iconclass est trop bruité (ARCHITECTURE § 37)
FRAMED_FEATURE = 88            # n° 88 sur le regard « sujet » : tableau photographié avec son cadre
FRAMED_RUN = "notions_sujet_20261121-213443"   # numéro propre à ce calcul : un autre entraînement le change
FRAMED_LABEL = "tableau photographié avec son cadre"


def _prep(X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Centre les vecteurs (normés) et les met à une échelle où chaque dimension vaut ~1."""
    mean = X.mean(axis=0)
    Z = X - mean
    scale = float(np.sqrt((Z ** 2).sum(axis=1).mean()) / np.sqrt(X.shape[1]))
    return (Z / scale).astype(np.float32), mean.astype(np.float32), scale


def train(X: np.ndarray, n_features: int = 2048, k: int = 16, epochs: int = 30, batch: int = 1024,
          lr: float = 4e-4, prefixes: tuple[int, ...] = PREFIXES, say: Callable[[str], None] = print) -> dict:
    """Auto-encodeur TopK Matryoshka. Renvoie les poids (numpy) et les mesures de reconstruction
    sur 10 % des œuvres mises de côté."""
    import torch

    torch.manual_seed(SEED)
    rng = np.random.default_rng(SEED)
    Z, mean, scale = _prep(X)
    order = rng.permutation(len(Z))
    held = order[: len(Z) // 10]
    fit = order[len(Z) // 10:]
    d = Z.shape[1]
    W_dec = torch.randn(n_features, d)
    W_dec /= W_dec.norm(dim=1, keepdim=True)
    W_dec = torch.nn.Parameter(W_dec)
    W_enc = torch.nn.Parameter(W_dec.detach().T.clone())
    b_enc = torch.nn.Parameter(torch.zeros(n_features))
    b_dec = torch.nn.Parameter(torch.zeros(d))
    opt = torch.optim.Adam([W_enc, b_enc, W_dec, b_dec], lr=lr)
    sizes = [p for p in prefixes if p < n_features] + [n_features]

    def encode(x):
        pre = torch.relu((x - b_dec) @ W_enc + b_enc)
        val, idx = pre.topk(k, dim=1)
        return torch.zeros_like(pre).scatter_(1, idx, val)

    Zt = torch.from_numpy(Z)
    for ep in range(epochs):
        perm = torch.from_numpy(rng.permutation(fit))
        total = 0.0
        for s in range(0, len(perm), batch):
            x = Zt[perm[s:s + batch]]
            z = encode(x)
            loss = 0.0
            for m in sizes:                          # Matryoshka : chaque préfixe doit reconstruire seul
                loss = loss + ((z[:, :m] @ W_dec[:m] + b_dec - x) ** 2).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            with torch.no_grad():
                W_dec /= W_dec.norm(dim=1, keepdim=True)
            total += float(loss.detach()) * len(x)
        if ep in (0, epochs // 2, epochs - 1):
            say(f"  époque {ep + 1}/{epochs} · perte {total / len(fit):.4f}")
    with torch.no_grad():
        xh = Zt[torch.from_numpy(held)]
        z = encode(xh)
        var = float(((xh - xh.mean(0)) ** 2).sum())
        fve = {m: round(1 - float(((z[:, :m] @ W_dec[:m] + b_dec - xh) ** 2).sum()) / var, 4) for m in sizes}
        acts = torch.cat([encode(Zt[s:s + 4096]) for s in range(0, len(Zt), 4096)]).numpy()
    freq = (acts > 0).mean(axis=0)
    return {"W_enc": W_enc.detach().numpy(), "b_enc": b_enc.detach().numpy(), "W_dec": W_dec.detach().numpy(),
            "b_dec": b_dec.detach().numpy(), "mean": mean, "scale": scale, "k": k,
            "explained_variance": fve, "freq": freq, "acts": acts, "dead": int((freq == 0).sum())}


def describe(model: dict, ids: np.ndarray, X: np.ndarray, meta: dict[int, dict], top: int = 50,
             notion_vecs: np.ndarray | None = None, notions: list[dict] | None = None) -> list[dict]:
    """Pour chaque notion vivante : fréquence, œuvres les plus fortes, ce que leurs métadonnées ont en
    commun (comparé à 50 œuvres prises au hasard), et la notion Iconclass la plus proche."""
    acts = model["acts"]
    rng = np.random.default_rng(SEED)
    keys = ("style", "genre", "artist", "century")

    def labels(rows):
        out = {}
        for key in keys:
            vals = []
            for r in rows:
                m = meta.get(int(ids[r]), {})
                v = m.get("date", "") if key == "century" else m.get(key, "")
                if key == "century" and v[:4].isdigit():
                    v = f"{int(v[:4]) // 100 + 1}e siècle"
                if v and not str(v).lower().startswith("unknown"):
                    vals.append(v)
            if vals:
                val, c = Counter(vals).most_common(1)[0]
                out[key] = {"value": val, "share": round(c / len(rows), 3)}
        return out

    base = {key: [] for key in keys}
    for _ in range(50):
        lab = labels(rng.choice(len(ids), top, replace=False))
        for key in keys:
            base[key].append(lab.get(key, {}).get("share", 0.0))
    baseline = {key: round(float(np.mean(v)), 3) for key, v in base.items()}

    feats, centroids = [], []
    for f in range(acts.shape[1]):
        col = acts[:, f]
        n_on = int((col > 0).sum())
        if n_on == 0:
            continue
        rows = np.argsort(-col)[:min(top, n_on)]
        c = X[rows].mean(axis=0)
        centroids.append(c / max(np.linalg.norm(c), 1e-12))
        feats.append({"feature": f, "frequency": round(n_on / len(ids), 5), "top": [int(ids[r]) for r in rows[:12]],
                      "labels": labels(rows)})
    if notion_vecs is not None and notions:
        C = np.stack(centroids)
        S = C @ notion_vecs.T                                  # (notions apprises, notions Iconclass)
        Zs = (S - S.mean(axis=0)) / (S.std(axis=0) + 1e-6)     # z-score : ce qui distingue cette notion
        for i, f in enumerate(feats):
            j = int(np.argmax(Zs[i]))
            f["iconclass"] = {"notation": notions[j]["notation"], "fr": notions[j]["fr"], "z": round(float(Zs[i, j]), 2)}
    return feats, baseline


def save(run_path: Path, model: dict, feats: list[dict], baseline: dict, info: dict) -> None:
    np.savez_compressed(run_path / "sae.npz", **{k: model[k] for k in ("W_enc", "b_enc", "W_dec", "b_dec", "mean")},
                        scale=np.float32(model["scale"]), k=np.int32(model["k"]))
    (run_path / "notions.json").write_text(json.dumps({**info, "baseline": baseline, "features": feats},
                                                      ensure_ascii=False), encoding="utf-8")


def latest_notions_run(runs_dir: Path, space: str | None = None):
    """Dernier run terminé de notions apprises (``analysis/notions_*``), en privilégiant ``sujet``."""
    from ..runs import list_runs

    runs = [
        r for r in list_runs("analysis", include_notions=True, runs_dir=runs_dir)
        if r.manifest["name"].startswith("notions_") and (Path(r.path) / "notions.json").exists()
    ]
    if space:
        runs = [r for r in runs if r.manifest["name"] == f"notions_{space}"]
    elif any(r.manifest["name"] == "notions_sujet" for r in runs):
        runs = [r for r in runs if r.manifest["name"] == "notions_sujet"]
    return runs[-1] if runs else None


def load_notions(run) -> dict | None:
    """Lit ``notions.json`` d'un run de notions."""
    p = Path(run.path) / "notions.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def framed_feature(run, meta: dict) -> int | None:
    """Numéro de la notion « tableau photographié avec son cadre », s'il est connu pour ce run
    (relu à l'œil sur ce calcul seulement ; les numéros changent à chaque entraînement)."""
    if meta.get("space") == "sujet" and Path(run.path).name == FRAMED_RUN:
        return FRAMED_FEATURE
    return None


def notion_label(feat: dict, z_min: float = ICONCLASS_Z_MIN) -> tuple[str, bool]:
    """Étiquette Iconclass si ``z >= z_min``, sinon « sans nom »."""
    ic = feat.get("iconclass")
    if ic and float(ic.get("z", 0.0)) >= z_min and ic.get("fr"):
        return str(ic["fr"]), True
    return "sans nom", False


def encode_index(run, runs_dir: Path, allowed_ids: set[int] | None = None, batch: int = 4096) -> dict | None:
    """Recalcule en NumPy les activations TopK exactes depuis ``sae.npz`` et construit un index
    inversé par notion (œuvres triées par activation décroissante). Renvoie ``None`` si ``sae.npz``
    ou les vecteurs parents sont absents."""
    from ..runs import Run
    from .layout import load_valid

    npz_path = Path(run.path) / "sae.npz"
    parent = run.manifest.get("parent")
    if not npz_path.exists() or not parent:
        return None
    feat_path = runs_dir / parent
    if not (feat_path / "manifest.json").exists():
        return None
    ids, X = load_valid(Run.load(feat_path))
    if allowed_ids is not None:
        keep = np.fromiter((int(i) in allowed_ids for i in ids), dtype=bool, count=len(ids))
        ids, X = ids[keep], X[keep]
    n = len(ids)
    with np.load(npz_path) as npz:
        W_enc = npz["W_enc"].astype(np.float32)
        b_enc = npz["b_enc"].astype(np.float32)
        b_dec = npz["b_dec"].astype(np.float32)
        mean = npz["mean"].astype(np.float32)
        scale = float(npz["scale"])
        k = int(npz["k"])
    n_features = W_enc.shape[1]
    k = max(1, min(k, n_features))
    if n == 0:
        return {"n_features": n_features, "n_artworks": 0, "offsets": np.zeros(n_features + 1, dtype=np.int64),
                "ids": np.empty(0, dtype=np.int64), "scores": np.empty(0, dtype=np.float32)}
    W_eff = W_enc / max(scale, 1e-12)
    b_eff = b_enc - (mean / max(scale, 1e-12) + b_dec) @ W_enc
    top_idx = np.empty((n, k), dtype=np.int32)
    top_val = np.empty((n, k), dtype=np.float32)
    for s in range(0, n, batch):
        xb = X[s:s + batch].astype(np.float32, copy=False)
        pre = xb @ W_eff + b_eff
        if k < n_features:
            idx = np.argpartition(pre, -k, axis=1)[:, -k:]
            val = np.take_along_axis(pre, idx, axis=1)
        else:
            idx = np.broadcast_to(np.arange(n_features, dtype=np.int32), pre.shape)
            val = pre
        np.maximum(val, 0.0, out=val)
        e = s + len(xb)
        top_idx[s:e] = idx
        top_val[s:e] = val
    pos = top_val > 0
    art_rows, _ = np.nonzero(pos)
    feat_flat = top_idx[pos]
    val_flat = top_val[pos]
    art_flat = ids[art_rows].astype(np.int64)
    order = np.lexsort((-val_flat, feat_flat))
    counts = np.bincount(feat_flat, minlength=n_features)
    offsets = np.zeros(n_features + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    return {"n_features": n_features, "n_artworks": n, "offsets": offsets,
            "ids": art_flat[order], "scores": val_flat[order]}
