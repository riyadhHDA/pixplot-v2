"""Retrouver le nom de fichier WikiArt d'origine de nos œuvres, puis leurs titres, dates et émotions.

Notre WikiArt 81k vient du jeu Hugging Face ``huggan/wikiart`` : il garde l'artiste, le style et
le genre, mais ni le titre ni le nom de fichier, et l'ordre des œuvres y est mélangé. Or deux jeux
d'annotations désignent chaque œuvre par ce nom de fichier (« Style/artiste_titre-date.jpg ») :

- **MMArt** (Wang et al., 2026, CC BY 4.0) : titre, date, quatre descriptions écrites par un modèle
  de langage (jamais une source, seulement un banc d'essai) ;
- **ArtEmis** (Achlioptas et al., CVPR 2021, recherche non commerciale, gardé en local) : 454 684
  réactions de spectateurs (9 émotions et une phrase).

On rattache donc les images une à une : MMArt contient les images, on calcule pour chacune la même
empreinte que ``pixplot ingest`` (dHash 64 bits) et l'on cherche, parmi nos œuvres du même style et
du même artiste, celle qui a les mêmes dimensions et l'empreinte la plus proche. Un rattachement
douteux (empreintes trop éloignées, ou deux candidates aussi proches) est écarté, jamais deviné.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

MAX_BITS = 8          # au-delà, deux empreintes de 64 bits ne désignent plus la même image
MIN_MARGIN = 4        # écart minimal avec la deuxième candidate
SOURCE_MMART = "MMArt (Wang et al. 2026, CC BY 4.0), rattaché par empreinte d'image"


@dataclass
class Ours:
    """Nos œuvres, rangées pour la recherche : (style, artiste) → lignes."""
    ids: np.ndarray
    hashes: np.ndarray          # uint64
    sizes: np.ndarray           # (N, 2) largeur, hauteur
    by_key: dict[tuple[str, str], list[int]]
    by_style: dict[str, list[int]]
    by_artist: dict[str, list[int]]


def split_image_id(image_id: str) -> tuple[str, str, str]:
    """« Style/artiste_titre.jpg » → (style, artiste, nom sans extension)."""
    style, _, name = image_id.replace("\\", "/").partition("/")
    stem = re.sub(r"\.\w+$", "", name)
    return style, stem.split("_", 1)[0], stem


def load_ours(conn) -> Ours:
    """Empreintes, dimensions, styles et artistes de toutes les œuvres du catalogue."""
    rows = conn.execute("SELECT id, dhash, width, height FROM artworks WHERE status = 'ok' AND dhash IS NOT NULL").fetchall()
    meta: dict[int, dict[str, str]] = {}
    for aid, k, v in conn.execute("SELECT artwork_id, key, value FROM metadata WHERE key IN ('style', 'artist')"):
        meta.setdefault(aid, {})[k] = v or ""
    ids = np.array([r[0] for r in rows], dtype=np.int64)
    hashes = np.array([int(r[1], 16) for r in rows], dtype=np.uint64)
    sizes = np.array([(r[2] or 0, r[3] or 0) for r in rows], dtype=np.int64)
    by_key, by_style, by_artist = {}, {}, {}
    for i, aid in enumerate(ids.tolist()):
        m = meta.get(aid, {})
        style, artist = m.get("style", ""), m.get("artist", "")
        by_key.setdefault((style, artist), []).append(i)
        by_style.setdefault(style, []).append(i)
        by_artist.setdefault(artist, []).append(i)
    return Ours(ids, hashes, sizes, by_key, by_style, by_artist)


def _popcount(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.uint64)
    b = np.unpackbits(x.view(np.uint8).reshape(-1, 8), axis=1)
    return b.sum(axis=1)


def match_one(ours: Ours, style: str, artist: str, h: int, size: tuple[int, int]) -> tuple[int | None, int, str]:
    """(notre id ou None, distance en bits, comment). Cherche d'abord même style et même artiste,
    puis même style et artiste inconnu chez nous, puis même artiste dans tous les styles."""
    for how, cand in (("style+artiste", ours.by_key.get((style, artist), [])),
                      ("style, artiste inconnu", ours.by_key.get((style, "Unknown Artist"), [])),
                      ("artiste", ours.by_artist.get(artist, []))):
        if not cand:
            continue
        idx = np.asarray(cand)
        d = _popcount(ours.hashes[idx] ^ np.uint64(h))
        same = (ours.sizes[idx, 0] == size[0]) & (ours.sizes[idx, 1] == size[1])
        d = np.where(same, d, d + 3)             # mêmes dimensions : indice fort qu'il s'agit du même fichier
        order = np.argsort(d)
        best = int(d[order[0]])
        second = int(d[order[1]]) if len(order) > 1 else 99
        if best <= MAX_BITS and second - best >= MIN_MARGIN:
            return int(ours.ids[idx[order[0]]]), best, how
    return None, -1, "aucune"


def match_rows(ours: Ours, rows: Iterable[tuple[str, int, tuple[int, int]]],
               say: Callable[[str], None] = print) -> list[dict]:
    """``rows`` : (image_id, dhash entier, (largeur, hauteur)). Un même id de chez nous n'est
    gardé que pour la ligne la plus proche (les doublons de WikiArt sont rangés sous deux styles)."""
    best: dict[int, dict] = {}
    unmatched = 0
    for image_id, h, size in rows:
        style, artist, stem = split_image_id(image_id)
        aid, dist, how = match_one(ours, style, artist, h, size)
        if aid is None:
            unmatched += 1
            continue
        if aid not in best or dist < best[aid]["bits"]:
            best[aid] = {"id": aid, "wikiart_file": f"{style}/{stem}", "bits": dist, "how": how}
    say(f"  rattachées : {len(best)} · sans rattachement sûr : {unmatched}")
    return sorted(best.values(), key=lambda r: r["id"])


def image_hash(data: bytes) -> tuple[int, tuple[int, int]]:
    """Empreinte et dimensions d'une image donnée en octets (même calcul que ``pixplot ingest``)."""
    from PIL import Image, ImageOps

    from ..imageio import oriented_size, to_rgb
    from .ingest import THUMB_SIZES, dhash

    with Image.open(io.BytesIO(data)) as probe:
        size = oriented_size(probe)
    with Image.open(io.BytesIO(data)) as im:              # comme imageio.open_image
        target = max(THUMB_SIZES)
        im.draft("RGB", (target, target))
        im = to_rgb(ImageOps.exif_transpose(im))
    return int(dhash(im), 16), size


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)


# ------------------------------------------------------------------ lecture de MMArt
def _hash_row(item: tuple[str, bytes]) -> tuple[str, int, tuple[int, int]] | None:
    image_id, data = item
    try:
        h, size = image_hash(data)
    except Exception:  # image illisible : pas de rattachement
        return None
    return image_id, h, size


def mmart_hashes(parquet_dir: Path, workers: int = 6, say: Callable[[str], None] = print):
    """Empreintes de toutes les images de MMArt (fichiers ``train-*.parquet``), fichier par fichier."""
    from concurrent.futures import ProcessPoolExecutor

    import pyarrow.parquet as pq

    files = sorted(Path(parquet_dir).glob("train-*.parquet"))
    with ProcessPoolExecutor(workers) as pool:
        for k, f in enumerate(files, 1):
            pf = pq.ParquetFile(f)
            n = 0
            for batch in pf.iter_batches(batch_size=256, columns=["image_id", "image"]):
                ids = batch.column("image_id").to_pylist()
                imgs = batch.column("image").to_pylist()
                items = [(i, (im or {}).get("bytes") or b"") for i, im in zip(ids, imgs)]
                for out in pool.map(_hash_row, items, chunksize=16):
                    if out is not None:
                        n += 1
                        yield out
            say(f"  {f.name} : {n} images ({k}/{len(files)})")


def readable_title(stem: str, artist: str) -> str:
    """« aaron-siskind_acolman-1-1955 » → « Acolman 1 » (l'artiste et l'année finale retirés)."""
    t = stem.split("_", 1)[1] if "_" in stem else stem
    t = re.sub(r"-(1[0-9]{3}|20[0-2][0-9])$", "", t)
    t = t.replace("-", " ").strip()
    return t[:1].upper() + t[1:] if t else ""


def import_mmart(conn, matches: list[dict], text_parquet: Path) -> dict:
    """Écrit titre, date et nom de fichier WikiArt dans le catalogue (source MMArt)."""
    import pyarrow.parquet as pq

    t = pq.read_table(text_parquet, columns=["image_id", "artist", "date"]).to_pylist()
    info = {split_image_id(r["image_id"])[0] + "/" + split_image_id(r["image_id"])[2]: r for r in t}
    rows, dated = [], 0
    for m in matches:
        r = info.get(m["wikiart_file"])
        if r is None:
            continue
        stem = m["wikiart_file"].split("/", 1)[1]
        rows.append((m["id"], "wikiart_file", m["wikiart_file"], SOURCE_MMART))
        title = readable_title(stem, r["artist"])
        if title:
            rows.append((m["id"], "title", title, SOURCE_MMART))
        d = r.get("date")
        if d is not None and d == d and 1000 <= d <= 2030:
            rows.append((m["id"], "date", str(int(d)), SOURCE_MMART))
            dated += 1
    conn.executemany("INSERT OR REPLACE INTO metadata(artwork_id, key, value, source) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    return {"artworks": len(matches), "dated": dated}


# ------------------------------------------------------------------ ArtEmis
EMOTIONS_FR = {"amusement": "amusement", "awe": "émerveillement", "contentment": "contentement",
               "excitement": "excitation", "anger": "colère", "disgust": "dégoût", "fear": "peur",
               "sadness": "tristesse", "something else": "autre chose"}
SOURCE_ARTEMIS = "ArtEmis (Achlioptas et al. 2021, recherche non commerciale), émotion la plus citée"


def artemis_by_file(csv_path: Path) -> dict[str, dict]:
    """Par œuvre (« Style/nom »), le nombre de réactions par émotion et trois phrases d'exemple."""
    out: dict[str, dict] = {}
    with Path(csv_path).open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = f"{r['art_style']}/{r['painting']}"
            e = out.setdefault(key, {"counts": {}, "examples": []})
            e["counts"][r["emotion"]] = e["counts"].get(r["emotion"], 0) + 1
            if len(e["examples"]) < 3:
                e["examples"].append({"emotion": r["emotion"], "text": r["utterance"]})
    return out


def import_artemis(conn, data_dir: Path, by_file: dict[str, dict]) -> dict:
    """Émotion la plus citée de chaque œuvre rattachée (clé ``emotion``), et le détail des
    réactions dans ``<données>/artemis.json`` (reste en local : licence non commerciale)."""
    import json

    files = dict(conn.execute("SELECT value, artwork_id FROM metadata WHERE key = 'wikiart_file'").fetchall())
    rows, detail = [], {}
    for key, e in by_file.items():
        aid = files.get(key)
        if aid is None:
            continue
        counts = e["counts"]
        n = sum(counts.values())
        top, c = max(counts.items(), key=lambda kv: kv[1])
        if c / n < 0.4 or top == "something else":        # pas d'émotion dominante nette : pas d'étiquette
            label = ""
        else:
            label = EMOTIONS_FR.get(top, top)
        if label:
            rows.append((aid, "emotion", label, SOURCE_ARTEMIS))
        detail[aid] = {"n": n, "counts": counts, "examples": e["examples"]}
    conn.executemany("INSERT OR REPLACE INTO metadata(artwork_id, key, value, source) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    (Path(data_dir) / "artemis.json").write_text(json.dumps(detail, ensure_ascii=False), encoding="utf-8")
    return {"artworks": len(detail), "labelled": len(rows)}


# ------------------------------------------------------------------ artistes retrouvés
SOURCE_ARTIST = ("nom de fichier WikiArt (retrouvé par MMArt) ; l'étiquette d'origine de huggan/wikiart "
                 "était « Unknown Artist »")


def import_artists(conn) -> dict:
    """Pour les œuvres étiquetées « Unknown Artist », l'artiste lu dans le nom de fichier WikiArt
    retrouvé (« Style/artiste_titre »). Les étiquettes déjà connues ne sont jamais remplacées ; un
    désaccord entre une étiquette connue et le nom de fichier est seulement compté."""
    files = dict(conn.execute("SELECT artwork_id, value FROM metadata WHERE key = 'wikiart_file'").fetchall())
    artist = dict(conn.execute("SELECT artwork_id, value FROM metadata WHERE key = 'artist'").fetchall())
    rows, disagree = [], 0
    for aid, f in files.items():
        slug = split_image_id(f + ".jpg")[1]
        cur = artist.get(aid) or ""
        if not cur or cur.lower().startswith("unknown"):
            rows.append((aid, "artist", slug, SOURCE_ARTIST))
        elif cur != slug:
            disagree += 1
    conn.executemany("INSERT OR REPLACE INTO metadata(artwork_id, key, value, source) VALUES (?, ?, ?, ?)", rows)
    conn.commit()
    return {"filled": len(rows), "disagree": disagree}
