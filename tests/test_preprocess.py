import numpy as np
from PIL import Image

from pixplot.encoders.base import PAD_RGB, letterbox, letterbox_box, to_normalized_array
from pixplot.features.regions import letterbox_mask, pool_regions, region_count


def test_letterbox_keeps_whole_image():
    img = Image.new("RGB", (800, 400), (255, 0, 0))  # œuvre en format paysage
    out = letterbox(img, 448)
    assert out.size == (448, 448)
    left, top, w, h = letterbox_box(800, 400, 448)
    assert (w, h) == (448, 224) and top == 112
    assert out.getpixel((224, 224)) == (255, 0, 0)     # l'œuvre est au centre, entière
    assert out.getpixel((224, 10)) == PAD_RGB          # bande en haut, pas de recadrage


def test_normalized_padding_is_near_zero():
    arr = to_normalized_array(Image.new("RGB", (16, 16), PAD_RGB))
    assert arr.shape == (3, 16, 16)
    assert np.abs(arr).max() < 0.02


def test_pool_regions_shape_and_mask():
    rng = np.random.default_rng(0)
    grid = rng.normal(size=(2, 28, 28, 8)).astype(np.float32)
    regions = pool_regions(grid)
    assert regions.shape == (2, region_count(), 8) == (2, 21, 8)
    assert np.allclose(np.linalg.norm(regions, axis=-1), 1, atol=1e-5)

    # Les bandes ne doivent pas influencer les régions
    mask = letterbox_mask(letterbox_box(800, 400, 448), 448, 16)
    assert mask.shape == (28, 28) and mask[0].sum() == 0 and mask[14].all()
    noisy = grid.copy()
    noisy[:, ~mask] = 1000.0
    m = np.broadcast_to(mask, (2, 28, 28))
    assert np.allclose(pool_regions(grid, mask=m)[:, 0], pool_regions(noisy, mask=m)[:, 0], atol=1e-5)


def test_split_tokens_drops_registers():
    from pixplot.encoders.dinov3 import split_tokens

    n, regs, g, d = 2, 4, 3, 5
    hidden = np.arange(n * (1 + regs + g * g) * d, dtype=np.float32).reshape(n, 1 + regs + g * g, d)
    cls, patches = split_tokens(hidden, regs, g)
    assert cls.shape == (n, d) and patches.shape == (n, g, g, d)
    assert np.array_equal(cls, hidden[:, 0])
    assert np.array_equal(patches[:, 0, 0], hidden[:, 1 + regs])      # premier patch après les registres
    assert np.array_equal(patches[:, 2, 2], hidden[:, -1])
