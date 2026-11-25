"""pixplot dater : dater une œuvre d'après ses voisines datées, avec une fourchette calibrée (ARCHITECTURE § 45)."""

import numpy as np

from pixplot.analysis import dating


def _corpus(n=400, seed=0):
    """Des vecteurs qui tournent avec l'année : deux œuvres proches dans le temps sont proches dans l'espace."""
    rng = np.random.default_rng(seed)
    years = rng.uniform(1400, 2000, n)
    a = (years - 1400) / 600 * np.pi / 2
    X = np.column_stack([np.cos(a), np.sin(a), rng.normal(0, 0.03, n)])
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X.astype(np.float32), years


def test_voisines_sans_elle_meme_ni_doublons_ni_artiste():
    X, y = _corpus(50)
    dated = np.ones(50, bool)
    X[1] = X[0]                                     # doublon exact de l'œuvre 0
    Y, W = dating.neighbor_years(X, y, dated, k=5, exclude={0: {1}, 1: {0}}, rows=np.array([0]))
    assert y[0] not in Y[0] and y[1] not in Y[0]    # ni elle-même, ni son doublon
    artists = np.array([0] * 25 + [1] * 25)
    Y, _ = dating.neighbor_years(X, y, dated, k=5, artists=artists, rows=np.array([3]))
    assert set(Y[0]).isdisjoint(set(y[:25]))        # artiste caché : aucune œuvre du même artiste
    Y, _ = dating.neighbor_years(X, y, dated, k=5, artists=artists, rows=np.array([3]), same_artist_only=True)
    assert set(Y[0]) <= set(y[:25]) - {y[3]}        # même artiste seulement


def test_quantiles_ponderes():
    Y = np.array([[1500.0, 1600.0, 1700.0, np.nan]])
    W = np.array([[1.0, 1.0, 10.0, 0.0]])
    q = dating.weighted_quantiles(Y, W, (0.1, 0.5, 0.9))
    # cumul des poids : 1/12 à 1500, 2/12 à 1600, 1 à 1700 → q10 = 1600, médiane = 1700 (le poids lourd la tire)
    assert q[0, 1] == 1700 and q[0, 0] == 1600
    assert np.isnan(dating.weighted_quantiles(np.full((1, 3), np.nan), np.zeros((1, 3)), (0.5,))).all()


def test_marge_conforme_tient_la_couverture():
    rng = np.random.default_rng(1)
    y = rng.normal(0, 10, 4000)
    lo, hi = np.full(4000, -5.0), np.full(4000, 5.0)  # fourchette trop étroite au départ
    m = dating.conformal_margin(lo[:2000], hi[:2000], y[:2000])
    cov = np.mean((y[2000:] >= lo[2000:] - m) & (y[2000:] <= hi[2000:] + m))
    assert m > 0 and abs(cov - 0.8) < 0.03


def test_datation_et_temoins():
    X, y = _corpus(600)
    dated = np.ones(600, bool)
    rng = np.random.default_rng(2)
    perm = rng.permutation(600)
    calib = np.zeros(600, bool); calib[perm[:150]] = True
    test = np.zeros(600, bool); test[perm[150:400]] = True
    Y, W = dating.neighbor_years(X, y, dated, k=10)
    r = dating.evaluate(dating.estimate(Y, W), y, calib, test)
    g = dating.baseline_global(y, dated, calib, test)
    assert r["erreur_mediane"] < g["erreur_mediane"] / 5       # bien mieux que la médiane du corpus
    assert abs(r["couverture"] - 0.8) < 0.08
    est = dating.estimate(Y, W)
    assert est.shape == (600, 4) and (est[:, 1] <= est[:, 0]).all() and (est[:, 0] <= est[:, 2]).all()


def test_fiche_et_api(atlas_env):
    """La fiche d'une œuvre sans date porte la date estimée ; une œuvre datée, non."""
    from pixplot.api.data import AtlasData

    s, _ = atlas_env
    data = AtlasData.load(s)
    ids = [int(i) for i in data.ids]
    years = data.years()
    undated = next(i for i, yv in zip(ids, years) if yv is None)
    dated_id = next(i for i, yv in zip(ids, years) if yv is not None)
    arr = np.tile([1550.0, 1520.0, 1580.0, 5.0, 1.0], (len(ids), 1))
    path = dating.save(data.analysis, arr, {"regard": "couleur", "couverture_visée": 0.8})
    try:
        data = AtlasData.load(s)
        e = data.artwork(undated)["date_estimate"]
        assert (e["year"], e["low"], e["high"], e["method"]) == (1550, 1520, 1580, "artiste")
        assert "date_estimate" not in data.artwork(dated_id)
        # carte de l'Atlas : l'année estimée seulement pour les œuvres sans date (vue chronologique)
        est = data.map_payload()["year_est"]
        rows = {i: r for r, i in enumerate(ids)}
        assert est[rows[undated]] == 1550 and est[rows[dated_id]] is None
    finally:
        path.unlink()
        path.with_suffix(".json").unlink()
