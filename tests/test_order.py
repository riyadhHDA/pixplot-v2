"""Ordre et désordre de la matière (Sigaki, Perc et Ribeiro, PNAS 2018) : cas extrêmes connus."""
import numpy as np


def test_entropy_complexity_extremes():
    from pixplot.analysis.connoisseur import entropy_complexity

    h, c = entropy_complexity(np.random.default_rng(0).random((128, 128)))
    assert h > 0.99 and c < 0.01                       # bruit : désordre maximal, complexité nulle
    x = np.linspace(0, 1, 128)
    h, c = entropy_complexity(np.add.outer(x, x))
    assert h < 0.2                                     # dégradé régulier : très ordonné
    assert entropy_complexity(np.ones((16, 16))) == (0.0, 0.0)
    assert entropy_complexity(np.ones((1, 16))) == (0.0, 0.0)


def test_by_label_orders_from_flat_to_noisy():
    from pixplot.analysis.order import by_label

    hc = np.array([[0.6, 0.2]] * 3 + [[0.97, 0.03]] * 3 + [[np.nan, np.nan]], dtype=np.float32)
    rows = by_label(["Minimalism"] * 3 + ["Pointillism"] * 3 + ["Pointillism"], hc, min_count=2)
    assert [r["value"] for r in rows] == ["Minimalism", "Pointillism"]
    assert rows[1]["n"] == 3                           # l'œuvre sans mesure ne compte pas


def test_measure_image_has_order():
    from PIL import Image

    from pixplot.analysis.connoisseur import measure_image

    im = Image.fromarray((np.random.default_rng(1).random((64, 64, 3)) * 255).astype(np.uint8))
    m = measure_image(im)
    assert set(m["order"]) == {"permutation_entropy", "complexity"}
