"""Importateur IIIF : charger une collection de musée ou de bibliothèque dans PixPlot.

IIIF (International Image Interoperability Framework) est le standard ouvert des musées
et bibliothèques (Getty, Rijksmuseum, BnF Gallica, Bodleian, Harvard, Yale…). On lui donne
l'adresse d'un **manifeste** (une œuvre ou un document) ou d'une **collection** (une liste de
manifestes, éventuellement imbriquée), en version 2 ou 3 de l'API Présentation.

Pour chaque manifeste : l'image de la première vue (ou de toutes avec ``all_canvases``),
téléchargée à la taille demandée par l'API Image quand elle existe, et ses métadonnées
(titre, auteur, date, lieu, droits…) dans ``metadata.csv``. Ensuite, le pipeline habituel :
``pixplot ingest`` puis ``pixplot import-metadata``.

Politesse envers les serveurs : une requête à la fois, une pause entre deux, un User-Agent
explicite, reprise possible (les images déjà téléchargées sont sautées). Respectez les
conditions d'utilisation de chaque institution (colonne ``rights``).
"""

from __future__ import annotations

import csv
import html
import json
import re
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator

USER_AGENT = "PixPlot-v2 IIIF importer (+https://github.com/riyadhHDA/pixplot-v2)"
# Libellés de métadonnées des institutions → clés PixPlot (les autres sont gardées telles quelles).
KEY_ALIASES = {
    "artist": "artist", "artiste": "artist", "creator": "artist", "créateur": "artist", "maker": "artist",
    "author": "artist", "auteur": "artist", "painter": "artist", "peintre": "artist", "attribution": "attribution",
    "date": "date", "dated": "date", "datation": "date", "date de création": "date", "creation date": "date",
    "period": "period", "période": "period", "title": "title", "titre": "title",
    "place": "place", "lieu": "place", "location": "place", "place of creation": "place",
    "object type": "object_type", "type": "object_type", "technique": "technique", "medium": "technique",
    "materials": "technique", "matériaux": "technique", "dimensions": "dimensions",
    "rights": "rights", "license": "rights", "licence": "rights", "droits": "rights",
    "identifier": "identifier", "object number": "identifier", "inventory number": "identifier", "cote": "identifier",
    "call number": "identifier", "accession number": "identifier",
    "latitude": "latitude", "longitude": "longitude", "repository": "repository", "institution": "repository",
}


@dataclass
class ImportReport:
    manifests: int = 0
    images: int = 0
    skipped: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    csv_path: Path | None = None


def fetch_json(url: str, timeout: int = 30) -> dict:
    if url.startswith(("file:", "/")) or re.match(r"^[A-Za-z]:[\\/]", url):
        path = Path(url.removeprefix("file://").removeprefix("file:"))
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/ld+json, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL fournie par l'utilisateur)
        return json.loads(r.read().decode("utf-8"))


def download(url: str, dest: Path, timeout: int = 60) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as fh:  # noqa: S310
        while chunk := r.read(1 << 16):
            fh.write(chunk)
    tmp.replace(dest)


# ---------------------------------------------------------------------- valeurs IIIF
def text_of(value) -> str:
    """Valeur IIIF (chaîne, liste, {"@value"}, carte de langues v3) → texte simple, sans HTML."""
    if value is None:
        return ""
    if isinstance(value, str):
        out = value
    elif isinstance(value, list):
        out = " ; ".join(t for t in (text_of(v) for v in value) if t)
    elif isinstance(value, dict):
        if "@value" in value:
            out = str(value["@value"])
        else:  # carte de langues v3 : {"fr": [...], "en": [...], "none": [...]}
            for lang in ("fr", "en", "none", *value.keys()):
                if lang in value:
                    out = text_of(value[lang])
                    break
            else:
                out = ""
    else:
        out = str(value)
    out = re.sub(r"<[^>]+>", " ", out)
    return re.sub(r"\s+", " ", html.unescape(out)).strip()


def _id(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return obj.get("id") or obj.get("@id") or ""
    return ""


def _type(obj: dict) -> str:
    t = obj.get("type") or obj.get("@type") or ""
    return (t[0] if isinstance(t, list) else t).split(":")[-1]


def iter_manifests(url: str, fetch: Callable[[str], dict] = fetch_json, limit: int | None = None,
                   _seen: set | None = None) -> Iterator[tuple[str, dict]]:
    """(adresse, manifeste) pour un manifeste ou une collection (récursif, sans doublons)."""
    seen = _seen if _seen is not None else set()
    if url in seen:
        return
    seen.add(url)
    doc = fetch(url)
    kind = _type(doc)
    if kind == "Manifest":
        yield url, doc
        return
    if kind != "Collection":
        raise ValueError(f"{url} : ni manifeste ni collection IIIF (type « {kind or '?'} »)")
    children = (doc.get("manifests") or []) + (doc.get("collections") or []) + (doc.get("members") or []) \
        + (doc.get("items") or [])
    count = 0
    for child in children:
        cid = _id(child)
        if not cid:
            continue
        ckind = _type(child) if isinstance(child, dict) else ""
        if ckind == "Manifest" and "items" not in child and "sequences" not in child:
            child = None  # référence seule : il faut aller le chercher
        if ckind == "Manifest" and child is not None:
            pairs = [(cid, child)]
        else:
            pairs = iter_manifests(cid, fetch, None if limit is None else limit - count, seen)
        for pair in pairs:
            yield pair
            count += 1
            if limit is not None and count >= limit:
                return
    # pages de collection (v2 « next », v3 « first »/« next »)
    nxt = _id(doc.get("next")) or _id(doc.get("first"))
    if nxt and (limit is None or count < limit):
        yield from iter_manifests(nxt, fetch, None if limit is None else limit - count, seen)


def canvases(manifest: dict) -> list[dict]:
    if "sequences" in manifest:  # v2
        seqs = manifest.get("sequences") or [{}]
        return seqs[0].get("canvases") or []
    return [c for c in manifest.get("items") or [] if _type(c) == "Canvas"]  # v3


def image_url(canvas: dict, max_size: int) -> str | None:
    """Adresse d'une image de la vue, réduite à ``max_size`` px par l'API Image si possible."""
    if "images" in canvas:  # v2
        anns = canvas.get("images") or []
        body = anns[0].get("resource") if anns else None
    else:  # v3 : Canvas → AnnotationPage → Annotation → body
        pages = canvas.get("items") or []
        anns = pages[0].get("items") if pages else []
        body = anns[0].get("body") if anns else None
        if isinstance(body, list):
            body = body[0] if body else None
    if not isinstance(body, dict):
        return None
    if body.get("type") == "Choice" or body.get("@type") == "oa:Choice":
        body = (body.get("items") or [body.get("default")] or [None])[0] or {}
    services = body.get("service") or []
    if isinstance(services, dict):
        services = [services]
    for s in services:
        sid = _id(s).rstrip("/")
        profile = json.dumps(s.get("profile", "")) + str(s.get("type", s.get("@type", "")))
        if sid and ("image" in profile.lower() or "level" in profile.lower()):
            return f"{sid}/full/!{max_size},{max_size}/0/default.jpg"
    return _id(body) or None


YEAR_IN_LABEL = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-4][0-9])(?!\d)")


def date_from_label(label: str) -> str | None:
    """Beaucoup d'institutions (Yale…) ne mettent la date que dans le libellé :
    « Turner, 1775–1851, Dort, 1818 ». On prend le dernier segment qui contient une année,
    sauf s'il ressemble aux dates de vie de l'artiste (« 1775–1851 » juste après le nom)."""
    parts = [p.strip() for p in label.split(",")]
    for k in range(len(parts) - 1, 0, -1):
        if YEAR_IN_LABEL.search(parts[k]):
            return parts[k] if k >= 2 else None
    return None


def metadata_of(manifest: dict, url: str) -> dict[str, str]:
    out: dict[str, str] = {}
    label = text_of(manifest.get("label"))
    if label:
        out["label"] = label
    for pair in manifest.get("metadata") or []:
        name, value = text_of(pair.get("label")), text_of(pair.get("value"))
        if not name or not value:
            continue
        key = KEY_ALIASES.get(name.lower().strip(" :"), re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:40])
        out.setdefault(key, value)
    out.setdefault("title", label)
    if (nav := manifest.get("navDate")) and "date" not in out:
        out["date"] = str(nav)[:10]
        out["date_source"] = "navDate IIIF"
    if "date" not in out and label and (d := date_from_label(label)):
        out["date"] = d
        out["date_source"] = "déduite du libellé du manifeste"
    for key in ("requiredStatement", "attribution"):
        if v := manifest.get(key):
            out.setdefault("attribution", text_of(v.get("value") if isinstance(v, dict) and "value" in v else v))
    for key in ("rights", "license"):
        if v := manifest.get(key):
            out.setdefault("rights", text_of(v))
    out["iiif_manifest"] = url
    return out


def import_iiif(sources: list[str], out_dir: Path, max_size: int = 1600, limit: int | None = None,
                all_canvases: bool = False, delay: float = 0.3, fetch: Callable[[str], dict] = fetch_json,
                get: Callable[[str, Path], None] = download, progress: Callable[[str], None] | None = None) -> ImportReport:
    out_dir = Path(out_dir)
    images = out_dir / "images"
    images.mkdir(parents=True, exist_ok=True)
    report = ImportReport(csv_path=out_dir / "metadata.csv")
    rows: list[dict[str, str]] = []
    if report.csv_path.exists():  # reprise : on garde les lignes déjà écrites
        with open(report.csv_path, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    done = {r["iiif_manifest"] + "#" + r.get("iiif_canvas", "") for r in rows}
    n = len(rows)

    for source in sources:
        try:
            manifests = list(iter_manifests(source, fetch, limit))
        except Exception as exc:  # noqa: BLE001
            report.failed.append((source, f"{type(exc).__name__}: {exc}"))
            continue
        for url, manifest in manifests:
            report.manifests += 1
            meta = metadata_of(manifest, url)
            views = canvases(manifest)
            for k, canvas in enumerate(views if all_canvases else views[:1]):
                key = f"{url}#{_id(canvas)}"
                if key in done:
                    report.skipped += 1
                    continue
                img = image_url(canvas, max_size)
                if not img:
                    report.failed.append((url, "aucune image trouvée dans la vue"))
                    continue
                n += 1
                dest = images / f"{n:06d}.jpg"
                try:
                    if not dest.exists():
                        get(img, dest)
                        time.sleep(delay)
                except Exception as exc:  # noqa: BLE001
                    report.failed.append((img, f"{type(exc).__name__}: {exc}"))
                    n -= 1
                    continue
                row = {"path": f"images/{dest.name}", **meta, "iiif_canvas": _id(canvas), "iiif_image": img}
                if all_canvases and len(views) > 1:
                    row["view"] = f"{k + 1}/{len(views)}"
                rows.append(row)
                done.add(key)
                report.images += 1
                if progress:
                    progress(f"{report.images} images · {meta.get('title', url)[:70]}")
            _write_csv(report.csv_path, rows)
    _write_csv(report.csv_path, rows)
    return report


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    keys: list[str] = ["path"]
    for r in rows:
        keys += [k for k in r if k not in keys]
    tmp = path.with_suffix(".csv.part")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)
