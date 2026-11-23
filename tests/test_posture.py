"""Tests du regard « posture » (RT-DETRv2 + ViTPose, descripteur 50-D, miroir, multi-figures)."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

from pixplot.analysis import review
from pixplot.analysis.pairbench import TYPES, Pair, add_pair, pairs_path
from pixplot.api.data import AtlasData
from pixplot.api.spaces import EXPERIMENTAL, NOT_KEPT, Spaces, describe_encoder
from pixplot.cli import main as cli_main
from pixplot.config import get_settings
from pixplot.encoders.base import EncodedBatch, Encoder
from pixplot.encoders.posture import (
    DIM,
    MAX_FIGURES,
    PostureIndex,
    canonicalize_pose_vector,
    mirror_keypoints,
    mirror_pose_vector,
    nms_boxes,
    pose_descriptor,
)
from pixplot.encoders.registry import ENCODERS, get_encoder
from pixplot.features.extract import extract
from pixplot.features.store import FeatureStore


def _make_skeleton(pose: str = "striding") -> np.ndarray:
    """Squelette COCO (17, 3) synthétique réaliste en coordonnées [0, 1]."""
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[:, 2] = 0.90
    if pose == "striding":
        # Semeur en marche, bras droit tendu en avant
        pts = [
            (0.52, 0.15), (0.50, 0.14), (0.54, 0.14), (0.48, 0.15), (0.55, 0.15),
            (0.45, 0.28), (0.57, 0.27),  # épaules
            (0.40, 0.42), (0.68, 0.34),  # coudes
            (0.38, 0.54), (0.80, 0.30),  # poignets
            (0.47, 0.55), (0.55, 0.55),  # hanches
            (0.38, 0.74), (0.63, 0.72),  # genoux
            (0.30, 0.92), (0.70, 0.90),  # chevilles
        ]
    elif pose == "reclining":
        # Figure allongée (type Vénus / Olympia)
        pts = [
            (0.20, 0.38), (0.19, 0.36), (0.21, 0.36), (0.18, 0.38), (0.22, 0.38),
            (0.28, 0.42), (0.26, 0.50),  # épaules
            (0.22, 0.56), (0.36, 0.55),  # coudes
            (0.28, 0.60), (0.48, 0.56),  # poignets
            (0.50, 0.50), (0.50, 0.58),  # hanches
            (0.68, 0.54), (0.67, 0.62),  # genoux
            (0.86, 0.60), (0.85, 0.66),  # chevilles
        ]
    else:
        # Bras levés (type Pathosformel / orant)
        pts = [
            (0.50, 0.22), (0.48, 0.20), (0.52, 0.20), (0.46, 0.22), (0.54, 0.22),
            (0.42, 0.34), (0.58, 0.34),
            (0.30, 0.24), (0.70, 0.22),
            (0.22, 0.10), (0.78, 0.08),
            (0.44, 0.60), (0.56, 0.60),
            (0.44, 0.78), (0.56, 0.78),
            (0.44, 0.94), (0.56, 0.94),
        ]
    kp[:, :2] = np.asarray(pts, dtype=np.float32)
    return kp


def test_pose_descriptor_invariances_and_mirror_no_torch():
    """Le descripteur 50-D est invariant en translation, échelle, exact au miroir et sans PyTorch."""
    kp = _make_skeleton("striding")
    v = pose_descriptor(kp)
    assert v.shape == (DIM,)
    assert np.isclose(np.linalg.norm(v), 1.0, atol=1e-5)

    # Invariance en translation et échelle
    kp_shift = kp.copy()
    kp_shift[:, 0] = kp_shift[:, 0] * 3.7 + 120.0
    kp_shift[:, 1] = kp_shift[:, 1] * 3.7 - 45.0
    assert np.allclose(v, pose_descriptor(kp_shift), atol=1e-5)

    # Équivariance exacte au miroir gauche-droite + involution
    kp_mir = mirror_keypoints(kp, width=1.0)
    v_mir = pose_descriptor(kp_mir)
    assert np.allclose(mirror_pose_vector(v), v_mir, atol=1e-6)
    assert np.allclose(mirror_pose_vector(mirror_pose_vector(v)), v, atol=1e-6)

    # Canonisation strictement invariante au miroir
    assert np.allclose(canonicalize_pose_vector(v), canonicalize_pose_vector(v_mir), atol=1e-6)

    # Deux postures très différentes restent bien séparées même avec miroir
    v_rec = pose_descriptor(_make_skeleton("reclining"))
    assert max(float(v @ v_rec), float(v @ mirror_pose_vector(v_rec))) < 0.5

    # Portrait à mi-corps (jambes absentes) : vecteur valide
    half = kp.copy()
    half[11:, 2] = 0.05
    v_half = pose_descriptor(half)
    assert np.isclose(np.linalg.norm(v_half), 1.0, atol=1e-5)

    # Visage seul sans articulations corporelles : vecteur nul, pas de NaN
    face_only = kp.copy()
    face_only[5:, 2] = 0.05
    v_face = pose_descriptor(face_only)
    assert np.all(v_face == 0.0) and np.all(np.isfinite(v_face))

    # NMS supprime les boîtes doublons
    boxes = np.array([[0.1, 0.1, 0.5, 0.8], [0.11, 0.11, 0.49, 0.79], [0.6, 0.2, 0.9, 0.8]], dtype=np.float32)
    scores = np.array([0.9, 0.7, 0.85], dtype=np.float32)
    assert nms_boxes(boxes, scores, iou_thr=0.65) == [0, 2]


def test_posture_index_multi_figure_and_mirror_no_torch():
    """PostureIndex retrouve une figure secondaire même retournée en miroir et écarte les œuvres vides."""
    v_stride = pose_descriptor(_make_skeleton("striding"))
    v_recline = pose_descriptor(_make_skeleton("reclining"))
    v_recline_mir = mirror_pose_vector(v_recline)
    v_orant = pose_descriptor(_make_skeleton("orant"))

    ids = np.array([10, 20, 30, 40], dtype=np.int64)
    counts = np.array([2, 1, 1, 0], dtype=np.int8)
    vecs = np.zeros((4, MAX_FIGURES, DIM), dtype=np.float16)
    vecs[0, 0] = v_stride
    vecs[0, 1] = v_recline      # figure secondaire allongée dans l'œuvre 10
    vecs[1, 0] = v_recline_mir  # figure unique allongée en miroir dans l'œuvre 20
    vecs[2, 0] = v_orant        # bras levés dans l'œuvre 30
    # œuvre 40 : 0 figure (paysage)

    idx = PostureIndex(ids, counts, vecs)
    assert idx.n_artworks == 4 and idx.n_with_figures == 3

    # Avec miroir : l'œuvre 10 retrouve l'œuvre 20 au rang 1 (figure 1 ↔ figure 0, miroir=True)
    res = idx.similar(10, k=5, allow_mirror=True)
    assert res[0]["id"] == 20
    assert res[0]["score"] > 0.99
    assert res[0]["fig_a"] == 1 and res[0]["fig_b"] == 0 and res[0]["mirrored"] is True
    assert all(r["id"] != 40 for r in res)

    # Œuvre sans figure : aucune voisine
    assert idx.similar(40, k=5) == []


class _FakePosture(Encoder):
    """Encodeur posture léger sans PyTorch pour tester extract, NOT_KEPT, pairs bench et composition."""

    name = "vitpose_base"
    dim = DIM
    input_size = 128
    patch_size = None
    needs_boxes = True
    extra_arrays = {
        "poses_count": ((), "int8"),
        "poses_vecs": ((MAX_FIGURES, DIM), "float16"),
        "poses_kpts": ((MAX_FIGURES, 17, 3), "float16"),
        "poses_boxes": ((MAX_FIGURES, 5), "float16"),
    }

    def encode(self, batch: np.ndarray, boxes=None) -> EncodedBatch:
        assert boxes is not None and len(boxes) == len(batch)
        n = len(batch)
        g = np.zeros((n, DIM), dtype=np.float32)
        cnt = np.zeros((n,), dtype=np.int8)
        pv = np.zeros((n, MAX_FIGURES, DIM), dtype=np.float16)
        pk = np.zeros((n, MAX_FIGURES, 17, 3), dtype=np.float16)
        pb = np.zeros((n, MAX_FIGURES, 5), dtype=np.float16)

        skels = [_make_skeleton("striding"), _make_skeleton("reclining"), _make_skeleton("orant")]
        for i in range(n):
            # Associe une posture déterministe au canal dominant (Rouge / Vert / Bleu du corpus synthétique)
            dom = int(np.argmax(batch[i].mean(axis=(1, 2))))
            kp = skels[dom]
            if i % 2 == 1:
                kp = mirror_keypoints(kp)
            v = pose_descriptor(kp)
            cnt[i] = 1
            pv[i, 0] = v.astype(np.float16)
            pk[i, 0] = kp.astype(np.float16)
            pb[i, 0] = np.array([0.1, 0.1, 0.9, 0.9, 0.9], dtype=np.float16)
            g[i] = canonicalize_pose_vector(v)
        return EncodedBatch(
            global_vectors=g,
            extras={"poses_count": cnt, "poses_vecs": pv, "poses_kpts": pk, "poses_boxes": pb},
        )


def test_posture_registered_experimental_meme_geste_and_bench(atlas_env, tmp_path):
    """Posture est un regard spécialisé en essai (hors NOT_KEPT), meme_geste est enregistré, et pairs bench fonctionne."""
    assert "vitpose_base" in ENCODERS and "vitpose_r18" in ENCODERS
    assert "vitpose" not in NOT_KEPT and "posture" in EXPERIMENTAL
    key, label, _ = describe_encoder("vitpose_base")
    assert key == "posture" and "ViTPose" in label

    assert "meme_geste" in TYPES and TYPES["meme_geste"][1] == "posture"
    assert "meme_geste" in review.REVIEW_TYPES
    assert review.SUGGESTED["posture"] == "meme_geste"

    src_settings, n = atlas_env
    data_copy = tmp_path / "data"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    fake = _FakePosture()
    run = extract(fake, s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete" and run.manifest["outputs"]["ok"] == n
    assert (run.path / "poses_count.npy").exists() and (run.path / "poses_vecs.npy").exists()

    # Exposé par défaut comme regard spécialisé en essai (avec drapeau dans list() et dans la fiche critique)
    data = AtlasData.load(s)
    assert "posture" in data.spaces.runs
    sp_posture = next(sp for sp in data.spaces.list() if sp["key"] == "posture")
    assert sp_posture["experimental"] is True and sp_posture["specialized"] is True
    assert sp_posture["card"]["experimental"] is True

    # Ajout de paires meme_geste (validée + proposée)
    reds = [i for i, m in data.meta.items() if m.get("artist") == "Rouge"]
    blues = [i for i, m in data.meta.items() if m.get("artist") == "Bleu"]
    add_pair(pairs_path(s), Pair(reds[0], reds[1], "meme_geste", "annotée", "validée", "synthétique"))
    add_pair(pairs_path(s), Pair(blues[0], blues[1], "meme_geste", "annotée", "proposée", "synthétique"))

    rc = cli_main(["--data", str(s.data_dir), "pairs", "bench", "--spaces", "couleur,posture"])
    assert rc == 0 and Spaces.include_not_kept is False

    reports = list((s.data_dir / "bench").glob("pairs_report_*.json"))
    rep = json.loads(reports[0].read_text(encoding="utf-8"))
    assert rep["spaces"] == ["couleur", "posture"]
    assert any(r["space"] == "posture" and r["type"] == "meme_geste" for r in rep["results"])

    rc_comp = cli_main(["--data", str(s.data_dir), "composition"])
    assert (rc_comp is None or rc_comp == 0) and Spaces.include_not_kept is False
    comp = json.loads(list((s.data_dir / "bench").glob("composition_report_*.json"))[0].read_text(encoding="utf-8"))
    spaces_measured = {r["space"] for r in comp["results"] if r["type"] == "meme_geste"}
    assert "posture" in spaces_measured and "posture_multi" in spaces_measured

    # Une œuvre sans figure (poses_count == 0) est exclue de Spaces._rows["posture"] et renvoie []
    cnt_path = run.path / "poses_count.npy"
    cnt_arr = np.load(cnt_path)
    cnt_arr[0] = 0
    np.save(cnt_path, cnt_arr)
    d2 = AtlasData.load(s)
    d2.spaces._open("posture")
    first_id = int(np.load(run.path / "ids.npy")[0])
    assert first_id not in d2.spaces._rows["posture"]
    assert d2.spaces.neighbors("posture", first_id) == []


def test_posture_api_skeletons_mirror_no_figure_and_mcp(atlas_env, tmp_path):
    """API /api/artwork?space=posture, /api/posture/{id}, /api/posture/match, /api/compare et MCP."""
    pytest.importorskip("fastapi")
    import asyncio
    from fastapi.testclient import TestClient
    from pixplot.api.app import create_app
    from pixplot.encoders.posture import letterbox_to_image_kpts

    src_settings, _ = atlas_env
    data_copy = tmp_path / "data_api"
    shutil.copytree(src_settings.data_dir, data_copy)
    s = get_settings(data_copy)

    run = extract(_FakePosture(), s.catalog_path, s.runs_dir, batch_size=6, workers=1)
    run_ids = np.load(run.path / "ids.npy")
    cnt = np.load(run.path / "poses_count.npy")
    vecs = np.load(run.path / "poses_vecs.npy")
    kpts = np.load(run.path / "poses_kpts.npy")

    # On fabrique 3 cas précis sur les 3 premières œuvres :
    # - r=0 (id0) : 2 figures (fig 0 = striding, fig 1 = reclining)
    # - r=1 (id1) : 1 figure (fig 0 = reclining EN MIROIR) → doit répondre à id0 (fig_a=1, fig_b=0, mirrored=True)
    # - r=2 (id2) : 0 figure → aucune voisine, posture_figures=0, match=False
    # Les autres œuvres reçoivent "orant" (éloigné de reclining/striding)
    kp_stride = _make_skeleton("striding")
    kp_rec = _make_skeleton("reclining")
    kp_rec_mir = mirror_keypoints(kp_rec)
    kp_orant = _make_skeleton("orant")
    v_stride = pose_descriptor(kp_stride).astype(np.float16)
    v_rec = pose_descriptor(kp_rec).astype(np.float16)
    v_rec_mir = pose_descriptor(kp_rec_mir).astype(np.float16)
    v_orant = pose_descriptor(kp_orant).astype(np.float16)

    cnt[:] = 1
    vecs[:] = 0
    kpts[:] = 0
    for r in range(len(run_ids)):
        vecs[r, 0] = v_orant
        kpts[r, 0] = kp_orant.astype(np.float16)

    cnt[0] = 2
    vecs[0, 0], vecs[0, 1] = v_stride, v_rec
    kpts[0, 0], kpts[0, 1] = kp_stride.astype(np.float16), kp_rec.astype(np.float16)

    cnt[1] = 1
    vecs[1, 0] = v_rec_mir
    kpts[1, 0] = kp_rec_mir.astype(np.float16)

    cnt[2] = 0
    vecs[2, 0] = 0
    kpts[2, 0] = 0

    np.save(run.path / "poses_count.npy", cnt)
    np.save(run.path / "poses_vecs.npy", vecs)
    np.save(run.path / "poses_kpts.npy", kpts)

    id0, id1, id2 = int(run_ids[0]), int(run_ids[1]), int(run_ids[2])
    data = AtlasData.load(s)
    client = TestClient(create_app(data))

    # 1. /api/spaces expose posture comme regard spécialisé en essai
    sp = next(x for x in client.get("/api/spaces").json()["spaces"] if x["key"] == "posture")
    assert sp["experimental"] is True and sp["specialized"] is True

    # 2. /api/artwork/{id0}?space=posture retrouve id1 en tête (figure secondaire 1 ↔ 0, en miroir)
    a0 = client.get(f"/api/artwork/{id0}", params={"space": "posture", "k": 5}).json()
    assert a0["space"] == "posture" and a0["posture_figures"] == 2
    assert a0["neighbors"][0]["id"] == id1
    assert a0["neighbors"][0]["fig_a"] == 1 and a0["neighbors"][0]["fig_b"] == 0
    assert a0["neighbors"][0]["mirrored"] is True
    assert all(n["id"] != id2 for n in a0["neighbors"])

    # 3. Œuvre sans figure : posture_figures == 0, neighbors == []
    a2 = client.get(f"/api/artwork/{id2}", params={"space": "posture", "k": 5}).json()
    assert a2["posture_figures"] == 0 and a2["neighbors"] == []

    # 4. Route des squelettes /api/posture/{id} (avec conversion letterbox → image 90x120)
    p0 = client.get(f"/api/posture/{id0}")
    assert p0.status_code == 200
    p0j = p0.json()
    assert p0j["count"] == 2 and p0j["experimental"] is True and len(p0j["limbs"]) == 14
    expected_kp0 = letterbox_to_image_kpts(kp_stride.astype(np.float16), 90, 120)
    got_kp0 = np.array(p0j["figures"][0]["kpts"], dtype=np.float32)
    assert np.allclose(got_kp0[:, :2], expected_kp0[:, :2], atol=1e-3)
    assert client.get(f"/api/posture/{id2}").json()["count"] == 0
    assert client.get("/api/posture/999999").status_code == 404

    # 5. Route /api/posture/match et /api/compare
    pm = client.get("/api/posture/match", params={"a": id0, "b": id1}).json()
    assert pm["matched"] is True and pm["fig_a"] == 1 and pm["fig_b"] == 0 and pm["mirrored"] is True
    assert pm["score"] > 0.99 and "pas la preuve" in pm["note"]
    pm_empty = client.get("/api/posture/match", params={"a": id0, "b": id2}).json()
    assert pm_empty["matched"] is False and pm_empty["score"] is None

    cmp = client.get("/api/compare", params={"ids": f"{id0},{id1},{id2}"}).json()
    assert cmp["similarity"]["posture"][0][1] > 0.99
    assert cmp["similarity"]["posture"][0][2] is None
    assert cmp["posture_matches"]["0,1"]["mirrored"] is True

    # 6. MCP similar_artworks accepte « posture » avec mention essai + précaution, sans nouvel outil
    pytest.importorskip("mcp")
    from pixplot.mcp.server import create_server

    srv = create_server(data)

    async def check_mcp():
        tools = {t.name for t in await srv.list_tools()}
        assert len(tools) == 20
        r0 = json.loads((await srv.call_tool("similar_artworks", {"artwork_id": id0, "k": 5, "space": "posture"})).content[0].text)
        assert r0["space"] == "posture" and r0["experimental"] is True and r0["figures"] == 2
        assert "essai" in r0["note"] and "pas la preuve" in r0["note"]
        assert r0["neighbors"][0]["id"] == id1 and r0["neighbors"][0]["mirrored"] is True
        r2 = json.loads((await srv.call_tool("similar_artworks", {"artwork_id": id2, "k": 5, "space": "posture"})).content[0].text)
        assert r2["figures"] == 0 and r2["neighbors"] == [] and "Aucune figure" in r2["message"]

    asyncio.run(check_mcp())


def test_vitpose_encoder_torch_on_synthetic_corpus(atlas_env, tmp_path):
    """ViTPoseEncoder avec deux modules PyTorch locaux fonctionne sans réseau ni téléchargement."""
    torch = pytest.importorskip("torch")

    class _DetOut:
        def __init__(self, logits, pred_boxes):
            self.logits = logits
            self.pred_boxes = pred_boxes

    class _PoseOut:
        def __init__(self, heatmaps):
            self.heatmaps = heatmaps

    class TinyDet(torch.nn.Module):
        def forward(self, pixel_values):
            b = pixel_values.shape[0]
            # 2 requêtes : 1 personne fiable au centre (classe 0) et 1 fond ignoré
            logits = torch.full((b, 2, 80), -5.0, device=pixel_values.device)
            logits[:, 0, 0] = 4.0  # sigmoid(4.0) ≈ 0.98
            boxes = torch.zeros((b, 2, 4), device=pixel_values.device)
            boxes[:, 0] = torch.tensor([0.5, 0.5, 0.45, 0.70], device=pixel_values.device)
            return _DetOut(logits, boxes)

    class TinyPose(torch.nn.Module):
        def forward(self, pixel_values):
            k = pixel_values.shape[0]
            hm = torch.zeros((k, 17, 64, 48), device=pixel_values.device)
            sk = _make_skeleton("striding")
            for j in range(17):
                px = int(np.clip(round(sk[j, 0] * 47), 1, 46))
                py = int(np.clip(round(sk[j, 1] * 63), 1, 62))
                hm[:, j, py, px] = 0.92
            return _PoseOut(hm)

    # input_size=448 (défaut CLI DINOv3) doit retomber sur 640 px
    enc = get_encoder(
        "vitpose_base", det_module=TinyDet(), pose_module=TinyPose(), device="cpu", input_size=448,
    )
    assert enc.name == "vitpose_base" and enc.dim == DIM and enc.input_size == 640
    assert enc.needs_boxes is True and enc.patch_size is None
    desc = enc.describe()
    assert desc["source"] == "huggingface" and desc["descriptor"] == "pose_50d_coords_bones_mirror"

    src_settings, n = atlas_env
    runs_dir = tmp_path / "runs"
    run = extract(enc, src_settings.catalog_path, runs_dir, batch_size=6, workers=1)
    assert run.manifest["status"] == "complete"
    assert run.manifest["outputs"]["ok"] == n and run.manifest["outputs"]["failed"] == 0

    store = FeatureStore.open(run)
    vecs = np.asarray(store.global_vectors, dtype=np.float32)
    assert vecs.shape == (n, DIM)
    assert np.allclose(np.linalg.norm(vecs, axis=1), 1.0, atol=1e-2)

    idx = PostureIndex.open(run.path)
    assert idx.n_artworks == n and idx.n_with_figures == n
    assert len(idx.similar(int(idx.ids[0]), k=3)) == 3


def test_regards_en_essai_hors_des_calculs_par_defaut():
    """`communities` et `disagreements` laissent la posture de côté sauf si on la nomme."""
    from types import SimpleNamespace

    from pixplot.cli import _default_spaces

    data = SimpleNamespace(spaces=SimpleNamespace(runs={"forme": 1, "sujet": 2, "posture": 3}))
    assert _default_spaces(None, data) == ["forme", "sujet"]
    assert _default_spaces("forme,posture", data) == ["forme", "posture"]
