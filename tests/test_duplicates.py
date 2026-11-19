"""Doublons et variantes (vecteurs SSCD) : seuils, étiquettes contradictoires, sans GPU."""
import numpy as np


def test_label_check():
    from pixplot.analysis.duplicates import label_check

    conflicts, one_side = label_check({"style": "Realism", "artist": "Unknown Artist", "genre": "landscape"},
                                      {"style": "Romanticism", "artist": "camille-corot", "genre": "Landscape"})
    assert conflicts == ["style"]                       # « landscape » = « Landscape »
    assert one_side == ["artist"]                       # « Unknown Artist » ne compte pas


def test_compute_levels(tmp_path):
    from pixplot.analysis.duplicates import compute, find_sscd_run, load, save
    from pixplot.features.extract import OK
    from pixplot.runs import create_run

    rng = np.random.default_rng(0)
    X = rng.normal(size=(40, 32)).astype(np.float32)
    X[1] = X[0] + 0.01 * rng.normal(size=32)            # même image
    X[3] = X[2] + 0.6 * rng.normal(size=32)             # variante
    run = create_run("features", "sscd_disc_large", {"encoder": "sscd_disc_large"}, runs_dir=tmp_path)
    ids = np.arange(100, 140)
    np.save(run.path / "ids.npy", ids)
    np.save(run.path / "status.npy", np.full(40, OK, dtype=np.uint8))
    np.save(run.path / "global.npy", X.astype(np.float16))
    run.complete()
    assert find_sscd_run(tmp_path).path == run.path
    meta = {100: {"style": "Realism"}, 101: {"style": "Romanticism"}}
    res = compute(ids, run, meta, k=3, same=0.85, variant=0.5, say=lambda m: None)
    first = res["pairs"][0]
    assert (first["a"], first["b"], first["level"], first["conflicts"]) == (100, 101, "same", ["style"])
    assert all(p["cos"] >= 0.5 for p in res["pairs"])

    class A:  # un run d'analyse réduit à son dossier
        path = tmp_path
    save(A, res)
    assert load(A)["counts"] == res["counts"]
