"""Regard « posture » (Pathosformeln de Warburg) : détection de figures et squelettes.

Chaîne 100 % libre (licence Apache 2.0 pour le code ET les poids) :
- détection de personnes : RT-DETRv2 (``PekingU/rtdetr_v2_r50vd`` ou ``rtdetr_v2_r18vd``) ;
- estimation de squelette (17 points COCO) : ViTPose (``usyd-community/vitpose-base-simple``).

Descripteur d'une figure (50 dimensions, normalisé L2) :
- 13 articulations normalisées (26 dim.) : centre de la tête (moyenne pondérée des 5 points
  du visage, pour éviter que le visage ne pèse autant que le corps entier) + 12 articulations
  du corps (épaules, coudes, poignets, hanches, genoux, chevilles), centrées sur le torse et
  ramenées à une taille commune (distance quadratique moyenne des points du corps visibles) ;
- 12 vecteurs unitaires de membres (24 dim.) : cou, ligne d'épaules, colonne, bassin, bras,
  avant-bras, cuisses, jambes — robustes aux proportions allongées ou trapues en peinture
  (maniérisme, gothique, art moderne) et aux cadrages à mi-corps.

Miroir gauche-droite (gravure d'après un tableau, citation inversée) :
- ``mirror_pose_vector`` applique exactement le retournement horizontal ($x \\mapsto -x$ et
  échange gauche/droite) sur le vecteur 50-D ;
- pour l'œuvre entière (jusqu'à 8 figures conservées dans ``poses_*.npy``), la similarité
  exacte ``PostureIndex`` prend la meilleure correspondance entre toutes les paires de figures
  des deux œuvres, en direct et en miroir :
  $$\\operatorname{sim}(A, B) = \\max_{i \\in A,\\, j \\in B} \\max(v_i \\cdot v_j,\\; v_i \\cdot F(v_j))$$
- ``global.npy`` stocke la figure principale canonisée en orientation (pour compatibilité avec
  ``FeatureStore``, ``Spaces`` et ``pixplot pairs bench``). Les œuvres sans figure valide
  (paysages, natures mortes, abstraction, portraits serrés sans corps) reçoivent un vecteur nul.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from .base import PAD_RGB, EncodedBatch, Encoder, letterbox, letterbox_box

# (id détecteur HF, id pose HF, résolution détecteur) — tous sous licence Apache 2.0
MODELS: dict[str, tuple[str, str, int]] = {
    "vitpose_base": ("PekingU/rtdetr_v2_r50vd", "usyd-community/vitpose-base-simple", 640),
    "vitpose_r18": ("PekingU/rtdetr_v2_r18vd", "usyd-community/vitpose-base-simple", 640),
}

DIM = 50
MAX_FIGURES = 8
DET_THRESHOLD = 0.40
NMS_IOU = 0.65
MIN_BOX_SIDE = 0.08     # côté minimal relatif au grand côté de l'œuvre (écarte le staffage 10 px)
MIN_BOX_AREA = 0.006    # aire minimale relative à l'aire de l'œuvre
KPT_THRESHOLD = 0.30    # confiance minimale par articulation
MIN_BODY_KPTS = 4       # au moins 4 articulations du corps (5..16) : écarte les visages seuls
MIN_BODY_CONF = 0.40    # confiance moyenne minimale des articulations du corps visibles

# Échange gauche/droite des 17 points COCO
COCO_LR_SWAP = np.array([0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15], dtype=np.int64)

# Permutation et signes exacts du miroir horizontal sur le vecteur 50-D :
# - 0..25  : 13 articulations (tête, épaules L/R, coudes L/R, poignets L/R, hanches L/R, genoux L/R, chevilles L/R)
# - 26..33 : 4 axes centraux (cou, épaules L→R, colonne, hanches L→R)
# - 34..49 : 8 membres latéraux (bras, avant-bras, cuisses, jambes — paires L/R)
_MIRROR_PERM = np.array([
    # Coordonnées (0..25)
    0, 1,
    4, 5, 2, 3,
    8, 9, 6, 7,
    12, 13, 10, 11,
    16, 17, 14, 15,
    20, 21, 18, 19,
    24, 25, 22, 23,
    # Os centraux (26..33)
    26, 27,  # cou
    28, 29,  # épaules (L→R devient R'→L' : dx inchangé, dy inversé)
    30, 31,  # colonne
    32, 33,  # hanches (L→R : dx inchangé, dy inversé)
    # Membres latéraux (34..49)
    36, 37, 34, 35,  # bras
    40, 41, 38, 39,  # avant-bras
    44, 45, 42, 43,  # cuisses
    48, 49, 46, 47,  # jambes
], dtype=np.int64)

_MIRROR_SIGN = np.array([
    # Coordonnées : x inversé, y conservé
    -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    # Os centraux
    -1, 1,   # cou
    1, -1,   # épaules L→R
    -1, 1,   # colonne
    1, -1,   # hanches L→R
    # Membres latéraux : x inversé, y conservé
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
    -1, 1, -1, 1,
], dtype=np.float32)

# Direction déterministe pour choisir l'orientation canonique de global.npy (sur la composante antisymétrique)
_CANON_WEIGHTS = np.zeros(DIM, dtype=np.float64)
_CANON_WEIGHTS[0] = 2.0    # inclinaison horizontale de la tête
_CANON_WEIGHTS[26] = 1.5   # vecteur cou (dx)
_CANON_WEIGHTS[30] = 2.5   # inclinaison de la colonne (dx)
_CANON_WEIGHTS[10] = 1.0   # poignet gauche (dx)
_CANON_WEIGHTS[12] = 1.0   # poignet droit (dx)
_CANON_WEIGHTS[22] = 0.8   # cheville gauche (dx)
_CANON_WEIGHTS[24] = 0.8   # cheville droite (dx)


def mirror_keypoints(keypoints: np.ndarray, width: float = 1.0) -> np.ndarray:
    """Retourne un squelette COCO (17, 3) horizontalement (miroir gauche-droite)."""
    kp = np.asarray(keypoints, dtype=np.float32)
    if kp.shape != (17, 3):
        raise ValueError(f"Attendu (17, 3), reçu {kp.shape}")
    out = kp[COCO_LR_SWAP].copy()
    out[:, 0] = width - out[:, 0]
    return out


def mirror_pose_vector(vec: np.ndarray) -> np.ndarray:
    """Applique le miroir horizontal exact sur un vecteur (50,) ou un tableau (..., 50)."""
    v = np.asarray(vec, dtype=np.float32)
    return v[..., _MIRROR_PERM] * _MIRROR_SIGN


def canonicalize_pose_vector(vec: np.ndarray) -> np.ndarray:
    """Choisit de façon déterministe entre ``vec`` et son miroir pour obtenir un vecteur
    unique invariant au retournement gauche-droite (pour ``global.npy``)."""
    v = np.asarray(vec, dtype=np.float32)
    if float(np.linalg.norm(v)) < 1e-8:
        return np.zeros(DIM, dtype=np.float32)
    vm = mirror_pose_vector(v)
    asym = (v.astype(np.float64) - vm.astype(np.float64)) * 0.5
    s = float(np.dot(_CANON_WEIGHTS, asym))
    if abs(s) < 1e-7:
        # Départage lexicographique sur la première composante antisymétrique non nulle
        nz = np.flatnonzero(np.abs(asym) > 1e-7)
        if len(nz):
            s = float(asym[nz[0]])
    return v.copy() if s >= 0.0 else vm


def pose_descriptor(
    keypoints: np.ndarray,
    kpt_threshold: float = KPT_THRESHOLD,
    min_body_kpts: int = MIN_BODY_KPTS,
    min_body_conf: float = MIN_BODY_CONF,
) -> np.ndarray:
    """Squelette COCO (17, 3) en coordonnées isotropes → descripteur 50-D normalisé L2.

    Renvoie le vecteur nul si la figure n'a pas assez d'articulations corporelles fiables.
    """
    kp = np.asarray(keypoints, dtype=np.float64)
    if kp.shape != (17, 3):
        raise ValueError(f"keypoints doit être de forme (17, 3), reçu {kp.shape}")

    xy = kp[:, :2]
    conf = np.clip(kp[:, 2], 0.0, 1.0)

    body_vis = conf[5:] >= kpt_threshold
    if int(body_vis.sum()) < min_body_kpts:
        return np.zeros(DIM, dtype=np.float32)
    if float(conf[5:][body_vis].mean()) < min_body_conf:
        return np.zeros(DIM, dtype=np.float32)

    # 13 articulations : 0 = centre de la tête (0..4), 1..12 = corps (5..16)
    joints = np.zeros((13, 2), dtype=np.float64)
    weights = np.zeros(13, dtype=np.float64)

    face_vis = conf[:5] >= kpt_threshold
    if face_vis.any():
        fw = conf[:5][face_vis]
        joints[0] = (xy[:5][face_vis] * fw[:, None]).sum(axis=0) / fw.sum()
        weights[0] = float(fw.max())

    joints[1:] = xy[5:]
    weights[1:] = np.where(body_vis, conf[5:], 0.0)

    # Centre du repère corporel : milieu du torse si complet, sinon milieu des épaules, sinon barycentre du corps
    sh_ok = weights[1] > 0 and weights[2] > 0
    hip_ok = weights[7] > 0 and weights[8] > 0
    if sh_ok and hip_ok:
        center = 0.25 * (joints[1] + joints[2] + joints[7] + joints[8])
    elif sh_ok:
        center = 0.5 * (joints[1] + joints[2])
    else:
        bw = weights[1:]
        center = (joints[1:] * bw[:, None]).sum(axis=0) / bw.sum()

    # Échelle : distance quadratique moyenne des articulations du corps visibles
    bw = weights[1:]
    rel_body = joints[1:] - center
    scale = float(np.sqrt((bw * (rel_body ** 2).sum(axis=1)).sum() / bw.sum()))
    if scale <= 1e-6:
        w_all = weights
        rel_all = joints - center
        scale = float(np.sqrt((w_all * (rel_all ** 2).sum(axis=1)).sum() / max(w_all.sum(), 1e-12)))
    if scale <= 1e-6:
        return np.zeros(DIM, dtype=np.float32)

    # 26 coordonnées normalisées pondérées par confiance
    coords = ((joints - center) / scale) * weights[:, None]
    coords[weights <= 0] = 0.0

    # 12 vecteurs unitaires de membres (24 dimensions)
    bones = np.zeros((12, 2), dtype=np.float64)

    def _unit(p_a: np.ndarray, p_b: np.ndarray, w: float) -> np.ndarray:
        if w <= 0.0:
            return np.zeros(2, dtype=np.float64)
        d = p_b - p_a
        n = float(np.linalg.norm(d))
        if n <= 1e-6:
            return np.zeros(2, dtype=np.float64)
        return (d / n) * w

    mid_sh = 0.5 * (joints[1] + joints[2])
    mid_hip = 0.5 * (joints[7] + joints[8])
    w_sh = min(weights[1], weights[2])
    w_hip = min(weights[7], weights[8])

    bones[0] = _unit(mid_sh, joints[0], min(w_sh, weights[0]))   # cou
    bones[1] = _unit(joints[1], joints[2], w_sh)                  # épaules L→R
    bones[2] = _unit(mid_hip, mid_sh, min(w_sh, w_hip))           # colonne
    bones[3] = _unit(joints[7], joints[8], w_hip)                 # hanches L→R
    bones[4] = _unit(joints[1], joints[3], min(weights[1], weights[3]))    # bras gauche
    bones[5] = _unit(joints[2], joints[4], min(weights[2], weights[4]))    # bras droit
    bones[6] = _unit(joints[3], joints[5], min(weights[3], weights[5]))    # avant-bras gauche
    bones[7] = _unit(joints[4], joints[6], min(weights[4], weights[6]))    # avant-bras droit
    bones[8] = _unit(joints[7], joints[9], min(weights[7], weights[9]))    # cuisse gauche
    bones[9] = _unit(joints[8], joints[10], min(weights[8], weights[10]))  # cuisse droite
    bones[10] = _unit(joints[9], joints[11], min(weights[9], weights[11]))   # jambe gauche
    bones[11] = _unit(joints[10], joints[12], min(weights[10], weights[12])) # jambe droite

    vec = np.concatenate([coords.reshape(-1), bones.reshape(-1)])
    norm = float(np.linalg.norm(vec))
    if norm <= 1e-6:
        return np.zeros(DIM, dtype=np.float32)
    return (vec / norm).astype(np.float32)


def nms_boxes(boxes: np.ndarray, scores: np.ndarray, iou_thr: float = NMS_IOU) -> list[int]:
    """Suppression des boîtes doublons (Non-Maximum Suppression) en NumPy pur."""
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = np.argsort(-scores)
    keep: list[int] = []
    while len(order) > 0:
        i = int(order[0])
        keep.append(i)
        if len(order) == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / np.maximum(areas[i] + areas[rest] - inter, 1e-6)
        order = rest[iou <= iou_thr]
    return keep


# ------------------------------------------------------------------ recherche multi-figures + miroir
class PostureIndex:
    """Recherche exacte par posture sur toutes les figures d'un corpus, avec miroir gauche-droite.

    Pour deux œuvres A et B :
    ``sim(A, B) = max_{i in A, j in B} max(v_i · v_j, v_i · mirror(v_j))``.
    Les œuvres sans figure valide reçoivent la similarité ``-1.0``.
    """

    def __init__(
        self,
        ids: np.ndarray,
        counts: np.ndarray,
        vecs: np.ndarray,
        kpts: np.ndarray | None = None,
        boxes: np.ndarray | None = None,
    ):
        self.ids = np.asarray(ids, dtype=np.int64)
        self.row_of = {int(i): r for r, i in enumerate(self.ids)}
        self.counts = np.asarray(counts, dtype=np.int32)
        self.n_artworks = len(self.ids)
        self.n_with_figures = int((self.counts > 0).sum())

        # Aplatissement en tableau contigu de toutes les figures valides (K, 50)
        flat_vecs: list[np.ndarray] = []
        flat_art: list[np.ndarray] = []
        flat_slot: list[np.ndarray] = []
        offsets = np.zeros(self.n_artworks + 1, dtype=np.int32)
        cur = 0
        for r in range(self.n_artworks):
            c = int(self.counts[r])
            if c > 0:
                v = np.asarray(vecs[r, :c], dtype=np.float32)
                norms = np.linalg.norm(v, axis=1, keepdims=True)
                good = (norms[:, 0] > 1e-5)
                if good.any():
                    v = v[good] / norms[good]
                    k = len(v)
                    flat_vecs.append(v)
                    flat_art.append(np.full(k, r, dtype=np.int32))
                    flat_slot.append(np.flatnonzero(good).astype(np.int8))
                    cur += k
            offsets[r + 1] = cur

        self.offsets = offsets
        if flat_vecs:
            self.vecs = np.ascontiguousarray(np.concatenate(flat_vecs, axis=0), dtype=np.float32)
            self.art_of = np.concatenate(flat_art, axis=0)
            self.slot_of = np.concatenate(flat_slot, axis=0)
        else:
            self.vecs = np.zeros((0, DIM), dtype=np.float32)
            self.art_of = np.zeros((0,), dtype=np.int32)
            self.slot_of = np.zeros((0,), dtype=np.int8)
        self.kpts = kpts
        self.boxes = boxes

    @classmethod
    def open(cls, run_path: Path, ids: Sequence[int] | None = None) -> "PostureIndex":
        from ..features.extract import OK

        p = Path(run_path)
        run_ids = np.load(p / "ids.npy")
        status = np.load(p / "status.npy", mmap_mode="r")
        counts = np.load(p / "poses_count.npy", mmap_mode="r")
        vecs = np.load(p / "poses_vecs.npy", mmap_mode="r")
        kpts = np.load(p / "poses_kpts.npy", mmap_mode="r") if (p / "poses_kpts.npy").exists() else None
        boxes = np.load(p / "poses_boxes.npy", mmap_mode="r") if (p / "poses_boxes.npy").exists() else None

        where = {int(i): r for r, i in enumerate(run_ids) if status[r] == OK}
        if ids is None:
            present = [int(i) for r, i in enumerate(run_ids) if status[r] == OK]
        else:
            present = [int(i) for i in ids if int(i) in where]
        rows = np.array([where[i] for i in present], dtype=np.int64)
        return cls(
            ids=np.asarray(present, dtype=np.int64),
            counts=np.asarray(counts[rows], dtype=np.int32),
            vecs=np.asarray(vecs[rows], dtype=np.float32),
            kpts=kpts,
            boxes=boxes,
        )

    def similarities_from(self, row: int, allow_mirror: bool = True) -> np.ndarray:
        """Similarité exacte (N,) entre l'œuvre ``row`` et tout le corpus (-1.0 si sans figure)."""
        s0, s1 = int(self.offsets[row]), int(self.offsets[row + 1])
        scores = np.full(self.n_artworks, -1.0, dtype=np.float32)
        if s0 == s1 or len(self.vecs) == 0:
            return scores
        q = self.vecs[s0:s1]  # (m, 50)
        sim_fig = (q @ self.vecs.T).max(axis=0)  # (K,)
        if allow_mirror:
            qm = mirror_pose_vector(q)
            sim_fig = np.maximum(sim_fig, (qm @ self.vecs.T).max(axis=0))
        np.maximum.at(scores, self.art_of, sim_fig)
        return scores

    def similar(
        self,
        artwork_id: int,
        k: int = 20,
        allow_mirror: bool = True,
    ) -> list[dict]:
        """Les ``k`` œuvres les plus proches par posture, avec détail figure A ↔ figure B et miroir."""
        if artwork_id not in self.row_of:
            return []
        row = self.row_of[artwork_id]
        s0, s1 = int(self.offsets[row]), int(self.offsets[row + 1])
        if s0 == s1 or len(self.vecs) == 0:
            return []
        scores = self.similarities_from(row, allow_mirror=allow_mirror)
        scores[row] = -np.inf
        valid = np.flatnonzero(scores > -1.0)
        if not len(valid):
            return []
        k = min(k, len(valid))
        top_sub = np.argpartition(-scores[valid], k - 1)[:k]
        top_rows = valid[top_sub[np.argsort(-scores[valid[top_sub]])]]

        q = self.vecs[s0:s1]
        qm = mirror_pose_vector(q) if allow_mirror else None
        out = []
        for tr in top_rows:
            t0, t1 = int(self.offsets[tr]), int(self.offsets[tr + 1])
            tv = self.vecs[t0:t1]
            d_dir = q @ tv.T
            best_dir = float(d_dir.max())
            fa, fb = np.unravel_index(int(d_dir.argmax()), d_dir.shape)
            mirrored = False
            best = best_dir
            if qm is not None:
                d_mir = qm @ tv.T
                best_mir = float(d_mir.max())
                if best_mir > best_dir:
                    best = best_mir
                    fa, fb = np.unravel_index(int(d_mir.argmax()), d_mir.shape)
                    mirrored = True
            out.append({
                "id": int(self.ids[tr]),
                "score": round(best, 4),
                "fig_a": int(self.slot_of[s0 + fa]),
                "fig_b": int(self.slot_of[t0 + fb]),
                "mirrored": mirrored,
            })
        return out

    def ranks_for_pairs(
        self,
        pairs,
        allow_mirror: bool = True,
        only_with_figures: bool = False,
    ) -> tuple[list, np.ndarray, int]:
        """Calcule les rangs exacts (2 requêtes par paire) pour une liste de ``Pair``."""
        usable = []
        for p in pairs:
            if p.a not in self.row_of or p.b not in self.row_of:
                continue
            ra, rb = self.row_of[p.a], self.row_of[p.b]
            if only_with_figures and (self.offsets[ra] == self.offsets[ra + 1] or self.offsets[rb] == self.offsets[rb + 1]):
                continue
            usable.append(p)
        if not usable:
            return [], np.zeros(0, dtype=np.int64), (self.n_with_figures if only_with_figures else self.n_artworks)

        n_corpus = self.n_with_figures if only_with_figures else self.n_artworks
        has_fig = (self.offsets[1:] > self.offsets[:-1])
        qa = [self.row_of[p.a] for p in usable] + [self.row_of[p.b] for p in usable]
        qb = [self.row_of[p.b] for p in usable] + [self.row_of[p.a] for p in usable]
        ranks = np.empty(len(qa), dtype=np.int64)
        cache: dict[int, np.ndarray] = {}
        for i, (ra, rb) in enumerate(zip(qa, qb)):
            sim = cache.get(ra)
            if sim is None:
                sim = self.similarities_from(ra, allow_mirror=allow_mirror)
                if only_with_figures:
                    sim = np.where(has_fig, sim, -np.inf)
                cache[ra] = sim
            target = sim[rb]
            if not has_fig[ra] or not has_fig[rb]:
                # Sans figure détectée d'un côté ou de l'autre : aucun appariement possible (dernier rang)
                ranks[i] = max(n_corpus - 1, 1)
                continue
            # La requête elle-même est exclue ; ex aequo comptés au meilleur rang (comme pairbench)
            gt = int((sim > target).sum()) - (1 if sim[ra] > target else 0)
            ranks[i] = gt + 1
        return usable, ranks, n_corpus


def score_posture_run(
    space_name: str,
    run_path: Path,
    pairs,
    ids: Sequence[int],
    allow_mirror: bool = True,
    only_with_figures: bool = True,
):
    """Évalue un run ``vitpose_*`` avec similarité exacte multi-figures + miroir (format ``PairResult``)."""
    from ..analysis.composition import aggregate

    idx = PostureIndex.open(run_path, ids=ids)
    valid_pairs = [p for p in pairs if p.status == "validée"]
    usable, ranks, n_corpus = idx.ranks_for_pairs(
        valid_pairs, allow_mirror=allow_mirror, only_with_figures=only_with_figures,
    )
    if not usable:
        return []
    return aggregate(space_name, usable, ranks, n_corpus)


# ------------------------------------------------------------------ encodeur PyTorch (RT-DETRv2 + ViTPose)
def _decode_heatmaps_gpu(heatmaps):
    """Décodage rapide sur GPU : argmax + décalage d'un quart de pixel (standard ViTPose)."""
    import torch

    k, j, h, w = heatmaps.shape
    flat = heatmaps.view(k, j, h * w)
    maxvals, idx = flat.max(dim=-1)
    y = (idx // w).float()
    x = (idx % w).float()

    xm = (x.long() - 1).clamp(0, w - 1)
    xp = (x.long() + 1).clamp(0, w - 1)
    ym = (y.long() - 1).clamp(0, h - 1)
    yp = (y.long() + 1).clamp(0, h - 1)
    bi = torch.arange(k, device=heatmaps.device).view(k, 1).expand(k, j)
    ji = torch.arange(j, device=heatmaps.device).view(1, j).expand(k, j)
    dx = torch.sign(heatmaps[bi, ji, y.long(), xp] - heatmaps[bi, ji, y.long(), xm]) * 0.25
    dy = torch.sign(heatmaps[bi, ji, yp, x.long()] - heatmaps[bi, ji, ym, x.long()]) * 0.25
    x = (x + dx + 0.5) / w
    y = (y + dy + 0.5) / h
    return torch.stack([x, y], dim=-1), maxvals


class ViTPoseEncoder(Encoder):
    """Détecteur RT-DETRv2 + estimateur de squelettes ViTPose (Apache 2.0)."""

    patch_size = None
    needs_boxes = True
    extra_arrays = {
        "poses_count": ((), "int8"),
        "poses_vecs": ((MAX_FIGURES, DIM), "float16"),
        "poses_kpts": ((MAX_FIGURES, 17, 3), "float16"),
        "poses_boxes": ((MAX_FIGURES, 5), "float16"),
    }

    def __init__(
        self,
        arch: str = "vitpose_base",
        hf_model: str | None = None,
        detector_model: str | None = None,
        input_size: int | None = None,
        det_threshold: float = DET_THRESHOLD,
        max_figures: int = MAX_FIGURES,
        device: str | None = None,
        fp16: bool = True,
        det_module=None,
        pose_module=None,
    ):
        import torch

        if arch not in MODELS:
            raise ValueError(f"Architecture inconnue : {arch} (choix : {', '.join(MODELS)})")
        default_det, default_pose, default_size = MODELS[arch]
        self.name = arch
        self.dim = DIM
        self.input_size = input_size or default_size
        self.det_weights = detector_model or default_det
        self.pose_weights = hf_model or default_pose
        self.det_threshold = det_threshold
        self.max_figures = max_figures
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.fp16 = fp16 and self.device != "cpu"
        self._torch = torch
        self._figures_total = 0
        self._artworks_with_figures = 0
        self._artworks_total = 0

        # Sous ROCm Windows, MIOpen peut bloquer sur le choix de solveur de convolution pour
        # RT-DETRv2 ; le repli GEMM rocBLAS (cudnn=False) évite ce blocage sans perte de précision.
        if self.device != "cpu" and getattr(torch.version, "hip", None):
            torch.backends.cudnn.enabled = False

        if det_module is None:
            from transformers import RTDetrV2ForObjectDetection
            self.det_model = RTDetrV2ForObjectDetection.from_pretrained(self.det_weights).eval().to(self.device)
        else:
            self.det_model = det_module.eval().to(self.device)

        if pose_module is None:
            from transformers import VitPoseForPoseEstimation
            self.pose_model = VitPoseForPoseEstimation.from_pretrained(self.pose_weights).eval().to(self.device)
        else:
            self.pose_model = pose_module.eval().to(self.device)

        self._mean = torch.tensor([0.485, 0.456, 0.406], device=self.device).view(1, 3, 1, 1)
        self._std = torch.tensor([0.229, 0.224, 0.225], device=self.device).view(1, 3, 1, 1)
        if self.device != "cpu":
            torch.cuda.reset_peak_memory_stats()

    def preprocess(self, image: Image.Image) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        """Letterbox carré en [0, 1] float32 (format natif de RT-DETRv2 ; ViTPose normalise sur GPU)."""
        box = letterbox_box(*image.size, self.input_size)
        canvas = letterbox(image, self.input_size, fill=PAD_RGB)
        arr = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1) / 255.0
        return arr, box

    def _crop_persons(self, imgs_01, batch_indices: list[int], boxes_xyxy: np.ndarray,
                      out_h: int = 256, out_w: int = 192, pad: float = 1.25):
        torch = self._torch
        F = torch.nn.functional
        k = len(batch_indices)
        aspect = out_w / out_h

        cx = 0.5 * (boxes_xyxy[:, 0] + boxes_xyxy[:, 2])
        cy = 0.5 * (boxes_xyxy[:, 1] + boxes_xyxy[:, 3])
        bw = np.maximum(boxes_xyxy[:, 2] - boxes_xyxy[:, 0], 1e-4) * pad
        bh = np.maximum(boxes_xyxy[:, 3] - boxes_xyxy[:, 1], 1e-4) * pad
        bw = np.maximum(bw, bh * aspect)
        bh = np.maximum(bh, bw / aspect)

        x0, y0 = cx - 0.5 * bw, cy - 0.5 * bh
        x1, y1 = cx + 0.5 * bw, cy + 0.5 * bh
        crop_rects = np.stack([x0, y0, x1, y1], axis=1).astype(np.float32)

        theta = torch.zeros((k, 2, 3), device=self.device, dtype=torch.float32)
        rx0 = torch.from_numpy(x0).to(self.device).float() * 2.0 - 1.0
        ry0 = torch.from_numpy(y0).to(self.device).float() * 2.0 - 1.0
        rx1 = torch.from_numpy(x1).to(self.device).float() * 2.0 - 1.0
        ry1 = torch.from_numpy(y1).to(self.device).float() * 2.0 - 1.0
        theta[:, 0, 0] = 0.5 * (rx1 - rx0)
        theta[:, 0, 2] = 0.5 * (rx1 + rx0)
        theta[:, 1, 1] = 0.5 * (ry1 - ry0)
        theta[:, 1, 2] = 0.5 * (ry1 + ry0)

        grid = F.affine_grid(theta, size=(k, 3, out_h, out_w), align_corners=False)
        src = imgs_01[torch.tensor(batch_indices, device=self.device, dtype=torch.long)]
        crops = F.grid_sample(src, grid, mode="bilinear", padding_mode="zeros", align_corners=False)
        return (crops - self._mean) / self._std, crop_rects

    def encode(
        self,
        batch: np.ndarray,
        boxes: Sequence[tuple[int, int, int, int]] | None = None,
    ) -> EncodedBatch:
        torch = self._torch
        n = len(batch)
        size = self.input_size
        x = torch.from_numpy(np.ascontiguousarray(batch)).to(self.device, non_blocking=True)

        with torch.inference_mode(), torch.autocast(
            device_type="cuda" if self.device != "cpu" else "cpu",
            dtype=torch.float16,
            enabled=self.fp16,
        ):
            det_out = self.det_model(pixel_values=x)

        logits = det_out.logits.float()
        pred_boxes = det_out.pred_boxes.float()
        person_scores = logits[:, :, 0].sigmoid().cpu().numpy()
        pred_boxes_np = pred_boxes.cpu().numpy()

        batch_idx: list[int] = []
        cand_boxes: list[np.ndarray] = []
        cand_scores: list[float] = []
        cand_prom: list[float] = []

        for b in range(n):
            ox, oy, nw, nh = boxes[b] if boxes is not None else (0, 0, size, size)
            x_min, y_min = ox / size, oy / size
            x_max, y_max = (ox + nw) / size, (oy + nh) / size
            art_area = max((nw * nh) / (size * size), 1e-6)
            art_max = max(nw, nh) / size

            sc = person_scores[b]
            mask = sc >= self.det_threshold
            if not mask.any():
                continue
            bx = pred_boxes_np[b, mask]
            bs = sc[mask]
            xyxy = np.empty_like(bx)
            xyxy[:, 0] = np.clip(bx[:, 0] - 0.5 * bx[:, 2], x_min, x_max)
            xyxy[:, 1] = np.clip(bx[:, 1] - 0.5 * bx[:, 3], y_min, y_max)
            xyxy[:, 2] = np.clip(bx[:, 0] + 0.5 * bx[:, 2], x_min, x_max)
            xyxy[:, 3] = np.clip(bx[:, 1] + 0.5 * bx[:, 3], y_min, y_max)

            bw = xyxy[:, 2] - xyxy[:, 0]
            bh = xyxy[:, 3] - xyxy[:, 1]
            size_ok = (np.maximum(bw, bh) >= MIN_BOX_SIDE * art_max) & ((bw * bh) >= MIN_BOX_AREA * art_area)
            xyxy, bs = xyxy[size_ok], bs[size_ok]
            if not len(xyxy):
                continue
            keep = nms_boxes(xyxy, bs, iou_thr=NMS_IOU)
            xyxy, bs = xyxy[keep], bs[keep]
            areas = np.maximum((xyxy[:, 2] - xyxy[:, 0]) * (xyxy[:, 3] - xyxy[:, 1]), 1e-6)
            prom = bs * np.sqrt(areas / art_area)
            order = np.argsort(-prom)[:self.max_figures]
            for j in order:
                batch_idx.append(b)
                cand_boxes.append(xyxy[j])
                cand_scores.append(float(bs[j]))
                cand_prom.append(float(prom[j]))

        g_vecs = np.zeros((n, self.dim), dtype=np.float32)
        p_count = np.zeros((n,), dtype=np.int8)
        p_vecs = np.zeros((n, self.max_figures, self.dim), dtype=np.float16)
        p_kpts = np.zeros((n, self.max_figures, 17, 3), dtype=np.float16)
        p_boxes = np.zeros((n, self.max_figures, 5), dtype=np.float16)

        if batch_idx:
            cand_arr = np.asarray(cand_boxes, dtype=np.float32)
            crops, crop_rects = self._crop_persons(x, batch_idx, cand_arr)
            kpts_parts, ksc_parts = [], []
            for ps in range(0, len(crops), 64):
                with torch.inference_mode(), torch.autocast(
                    device_type="cuda" if self.device != "cpu" else "cpu",
                    dtype=torch.float16,
                    enabled=self.fp16,
                ):
                    p_out = self.pose_model(pixel_values=crops[ps:ps + 64])
                kc, ks = _decode_heatmaps_gpu(p_out.heatmaps.float())
                kpts_parts.append(kc.cpu().numpy())
                ksc_parts.append(ks.cpu().numpy())
            kpts_rel = np.concatenate(kpts_parts, axis=0)
            ksc = np.concatenate(ksc_parts, axis=0)

            per_img: list[list[tuple[float, np.ndarray, np.ndarray, np.ndarray]]] = [[] for _ in range(n)]
            for k_i, b in enumerate(batch_idx):
                rx0, ry0, rx1, ry1 = crop_rects[k_i]
                kp = np.empty((17, 3), dtype=np.float32)
                kp[:, 0] = rx0 + kpts_rel[k_i, :, 0] * (rx1 - rx0)
                kp[:, 1] = ry0 + kpts_rel[k_i, :, 1] * (ry1 - ry0)
                kp[:, 2] = ksc[k_i]
                vec = pose_descriptor(kp)
                if float(np.linalg.norm(vec)) < 1e-6:
                    continue
                body_c = float(kp[5:, 2][kp[5:, 2] >= KPT_THRESHOLD].mean())
                rank_score = cand_prom[k_i] * body_c
                box5 = np.array([*cand_arr[k_i], cand_scores[k_i]], dtype=np.float32)
                per_img[b].append((rank_score, vec, kp, box5))

            for b in range(n):
                figs = sorted(per_img[b], key=lambda t: -t[0])[:self.max_figures]
                if not figs:
                    continue
                p_count[b] = len(figs)
                g_vecs[b] = canonicalize_pose_vector(figs[0][1])
                for slot, (_, vec, kp, box5) in enumerate(figs):
                    p_vecs[b, slot] = vec.astype(np.float16)
                    p_kpts[b, slot] = kp.astype(np.float16)
                    p_boxes[b, slot] = box5.astype(np.float16)

        self._artworks_total += n
        self._artworks_with_figures += int((p_count > 0).sum())
        self._figures_total += int(p_count.sum())
        return EncodedBatch(
            global_vectors=g_vecs,
            extras={
                "poses_count": p_count,
                "poses_vecs": p_vecs,
                "poses_kpts": p_kpts,
                "poses_boxes": p_boxes,
            },
        )

    def runtime_stats(self) -> dict:
        stats: dict = {
            "artworks_with_figures_session": self._artworks_with_figures,
            "figures_total_session": self._figures_total,
            "figure_rate_session": round(self._artworks_with_figures / max(self._artworks_total, 1), 4),
        }
        if self.device == "cpu":
            stats["device"] = "cpu"
            return stats
        torch = self._torch
        stats["device"] = torch.cuda.get_device_name(0)
        stats["vram_peak_mib"] = round(torch.cuda.max_memory_allocated() / 2**20)
        return stats

    def describe(self) -> dict:
        return {
            **super().describe(),
            "source": "huggingface",
            "detector": self.det_weights,
            "weights": self.pose_weights,
            "max_figures": self.max_figures,
            "det_threshold": self.det_threshold,
            "descriptor": "pose_50d_coords_bones_mirror",
            "device": self.device,
            "fp16": self.fp16,
        }
