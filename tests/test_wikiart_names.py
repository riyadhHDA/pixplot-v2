"""Rattachement des noms de fichier WikiArt (MMArt) et des émotions (ArtEmis), sur données synthétiques."""
import csv
import io
import sqlite3

import numpy as np
from PIL import Image


def _png(seed: int, size=(120, 90)) -> bytes:
    rng = np.random.default_rng(seed)
    arr = (rng.random((size[1] // 10, size[0] // 10, 3)) * 255).astype(np.uint8)
    im = Image.fromarray(arr).resize(size, Image.Resampling.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _catalog(images: dict[int, tuple[bytes, str, str]]):
    from pixplot.catalog.ingest import dhash

    conn = sqlite3.connect(":memory:")
    conn.executescript("""CREATE TABLE artworks (id INTEGER PRIMARY KEY, path TEXT, status TEXT, dhash TEXT,
                          width INTEGER, height INTEGER);
                          CREATE TABLE metadata (artwork_id INTEGER, key TEXT, value TEXT, source TEXT,
                          PRIMARY KEY (artwork_id, key));""")
    for aid, (data, style, artist) in images.items():
        with Image.open(io.BytesIO(data)) as im:
            conn.execute("INSERT INTO artworks VALUES (?, ?, 'ok', ?, ?, ?)",
                         (aid, f"{aid}.png", dhash(im.convert("RGB")), im.width, im.height))
        conn.executemany("INSERT INTO metadata VALUES (?, ?, ?, 'test')",
                         [(aid, "style", style), (aid, "artist", artist)])
    return conn


def test_match_and_import(tmp_path):
    from pixplot.catalog import wikiart_names as W

    imgs = {1: (_png(1), "Realism", "camille-corot"), 2: (_png(2), "Realism", "camille-corot"),
            3: (_png(3), "Baroque", "Unknown Artist")}
    conn = _catalog(imgs)
    ours = W.load_ours(conn)
    rows = [("Realism/camille-corot_le-pont-1860.jpg", *W.image_hash(imgs[2][0])),
            ("Baroque/rembrandt_la-ronde-1642.jpg", *W.image_hash(imgs[3][0])),   # artiste inconnu chez nous
            ("Realism/camille-corot_autre.jpg", *W.image_hash(_png(99)))]          # absente : pas devinée
    matches = W.match_rows(ours, rows, say=lambda m: None)
    assert [(m["id"], m["wikiart_file"]) for m in matches] == [
        (2, "Realism/camille-corot_le-pont-1860"), (3, "Baroque/rembrandt_la-ronde-1642")]

    import pyarrow as pa
    import pyarrow.parquet as pq
    pq.write_table(pa.table({"image_id": ["Realism/camille-corot_le-pont-1860.jpg", "Baroque/rembrandt_la-ronde-1642.jpg"],
                             "artist": ["camille-corot", "rembrandt"], "date": [1860.0, None]}), tmp_path / "t.parquet")
    r = W.import_mmart(conn, matches, tmp_path / "t.parquet")
    assert r == {"artworks": 2, "dated": 1}
    got = dict(conn.execute("SELECT key, value FROM metadata WHERE artwork_id = 2 AND key IN ('title', 'date')").fetchall())
    assert got == {"title": "Le pont", "date": "1860"}

    with (tmp_path / "artemis.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["art_style", "painting", "emotion", "utterance", "repetition"])
        for e in ["awe", "awe", "awe", "sadness"]:
            w.writerow(["Realism", "camille-corot_le-pont-1860", e, "texte", 4])
        for e in ["fear", "anger", "awe", "sadness", "disgust"]:                 # pas de dominante nette
            w.writerow(["Baroque", "rembrandt_la-ronde-1642", e, "texte", 5])
    r = W.import_artemis(conn, tmp_path, W.artemis_by_file(tmp_path / "artemis.csv"))
    assert r == {"artworks": 2, "labelled": 1}
    assert conn.execute("SELECT value FROM metadata WHERE artwork_id = 2 AND key = 'emotion'").fetchone()[0] == "émerveillement"
    assert (tmp_path / "artemis.json").exists()


def test_import_artists_only_fills_unknown():
    from pixplot.catalog import wikiart_names as W

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (artwork_id INTEGER, key TEXT, value TEXT, source TEXT, PRIMARY KEY (artwork_id, key))")
    conn.executemany("INSERT INTO metadata VALUES (?, ?, ?, 'test')", [
        (1, "artist", "Unknown Artist"), (1, "wikiart_file", "Baroque/francisco-de-zurbaran_st-lawrence-1639"),
        (2, "artist", "claude-monet"), (2, "wikiart_file", "Impressionism/claude-monet_water-lilies"),
        (3, "artist", "rembrandt"), (3, "wikiart_file", "Baroque/jan-lievens_portrait")])
    assert W.import_artists(conn) == {"filled": 1, "disagree": 1}
    got = dict(conn.execute("SELECT artwork_id, value FROM metadata WHERE key = 'artist'").fetchall())
    assert got == {1: "francisco-de-zurbaran", 2: "claude-monet", 3: "rembrandt"}   # jamais remplacée si connue
