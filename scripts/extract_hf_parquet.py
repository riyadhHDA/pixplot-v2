"""Extrait les images et les étiquettes d'un jeu de données Hugging Face au format Parquet.

Usage :
    python scripts/extract_hf_parquet.py data/corpus/wikiart/raw data/corpus/wikiart

Produit :
    <sortie>/images/<artiste>/<n>.<ext>   les images, octets d'origine (pas de recompression)
    <sortie>/metadata.csv                 path, artist, genre, style, source, ...

Les colonnes ClassLabel (entiers) sont traduites en noms grâce au schéma Hugging Face
enregistré dans les métadonnées du fichier Parquet, ou, s'il est absent, grâce à un
fichier ``<sortie>/labels.json`` ({"colonne": ["nom0", "nom1", ...]}).
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
from pathlib import Path

import pyarrow.parquet as pq
from PIL import Image


def label_names(schema) -> dict[str, list[str]]:
    meta = (schema.metadata or {}).get(b"huggingface")
    if not meta:
        return {}
    features = json.loads(meta).get("info", {}).get("features", {})
    return {k: v["names"] for k, v in features.items() if isinstance(v, dict) and "names" in v}


def safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name, flags=re.UNICODE).strip("_") or "inconnu"


def guess_ext(data: bytes, path: str | None) -> str:
    if path and Path(path).suffix:
        return Path(path).suffix.lower()
    with Image.open(io.BytesIO(data)) as im:
        return "." + (im.format or "jpg").lower().replace("jpeg", "jpg")


def main(src: Path, out: Path) -> None:
    files = sorted(src.glob("*.parquet"))
    if not files:
        sys.exit(f"Aucun fichier .parquet dans {src}")
    (out / "images").mkdir(parents=True, exist_ok=True)
    rows, n = [], 0
    labels_file = out / "labels.json"
    fallback = json.loads(labels_file.read_text(encoding="utf-8")) if labels_file.exists() else {}

    for f in files:
        pf = pq.ParquetFile(f)
        names = label_names(pf.schema_arrow) or fallback
        for batch in pf.iter_batches(batch_size=64):
            for rec in batch.to_pylist():
                img = rec.pop("image")
                data = img["bytes"] if isinstance(img, dict) else img
                labels = {k: (names[k][v] if k in names and isinstance(v, int) else v) for k, v in rec.items()}
                folder = out / "images" / safe(str(labels.get("artist", "lot")))
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"{n:06d}{guess_ext(data, img.get('path') if isinstance(img, dict) else None)}"
                target.write_bytes(data)
                rows.append({"path": target.relative_to(out).as_posix(), **labels, "source": f"{f.name}"})
                n += 1
        print(f"{f.name} : {n} images au total")

    keys = ["path"] + sorted({k for r in rows for k in r} - {"path"})
    with open(out / "metadata.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"{n} images -> {out / 'images'}\nMétadonnées -> {out / 'metadata.csv'}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
