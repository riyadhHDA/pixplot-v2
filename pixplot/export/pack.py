"""Research Pack : un dossier de recherche compact, traçable, lisible par un LLM.

Un LLM ne sait rien faire de vecteurs bruts. Ce qu'il exploite : des **images** (il les
voit), des **relations explicites** chiffrées et des **métadonnées sourcées**. Le pack
contient donc :

    manifest.json     titre, question, date, modèles et runs utilisés, paramètres,
                      provenance de la sélection, mises en garde
    summary.md        le dossier rédigé pour un LLM (et lisible par l'historien) : question,
                      méthode, composition, œuvres, relations les plus fortes, atypiques,
                      consignes d'interprétation
    artworks.csv      une ligne par œuvre : métadonnées, groupe, famille, atypicité, image
    relations.csv     paires d'œuvres du pack et leur similarité (DINOv3, et SigLIP si dispo)
    evidence/         une vignette (512 px) par œuvre + les détails recadrés s'il y en a
    vectors.npy       (option « expert ») vecteurs globaux, pour reproduire les calculs

Tout est en CSV / JSON / Markdown / JPEG : aucun outil particulier n'est nécessaire.
Quelques Mo pour 50 œuvres.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from .. import __version__
from ..catalog.ingest import thumb_path

CAVEATS = [
    "Une proximité visuelle calculée est une piste à examiner, pas une preuve d'influence, "
    "de filiation ou d'attribution.",
    "Les scores sont des similarités entre vecteurs (cosinus, de -1 à 1), pas des probabilités.",
    "Les métadonnées viennent de leur source (colonne « source ») et peuvent être erronées ou "
    "incomplètes ; les valeurs « Unknown » signifient « non renseigné ».",
    "Les images restent soumises aux droits de leurs détenteurs : ce pack est un document de "
    "travail, pas une publication.",
]

PROMPT = """Tu es un assistant de recherche en histoire de l'art. Ce dossier a été produit par
PixPlot v2 : des modèles de vision ont rapproché des œuvres ; les images sont dans evidence/.

Question de recherche : {question}

1. Regarde les images. Décris ce qui rapproche réellement ces œuvres (composition, motifs,
   gestes, technique, iconographie) et ce qui les distingue.
2. Propose plusieurs hypothèses historiques ou iconographiques, classées par plausibilité.
3. Pour chacune : œuvres qui la soutiennent, contre-exemples dans le dossier, et ce qu'il
   faudrait vérifier (sources, catalogues, dates, provenances).
4. Distingue toujours : observation (ce qui se voit), donnée (métadonnée sourcée),
   calcul (score PixPlot) et interprétation (ta proposition).
5. Indique les limites du dossier et les recherches complémentaires à lancer dans PixPlot
   (œuvres à chercher, détails à comparer).
"""


def _slug(s: str) -> str:
    return re.sub(r"[^\w-]+", "-", s.lower(), flags=re.UNICODE).strip("-")[:60] or "pack"


def _jpeg(src: Path, max_side: int) -> bytes:
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _crop_jpeg(src: Path, box, max_side: int = 512) -> bytes:
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        x0, y0, x1, y1 = box
        crop = im.crop((int(x0 * w), int(y0 * h), max(int(x1 * w), int(x0 * w) + 1), max(int(y1 * h), int(y0 * h) + 1)))
        crop.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        crop.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def _distribution(meta: dict[int, dict], ids: list[int], key: str, top: int = 8) -> list[tuple[str, int]]:
    vals = [meta[i].get(key) for i in ids]
    vals = [v for v in vals if v and not v.lower().startswith("unknown")]
    return Counter(vals).most_common(top)


def build_pack(
    data,
    artwork_ids: list[int],
    out_dir: Path,
    title: str,
    question: str = "",
    selection: dict | None = None,
    details: dict[int, list[float]] | None = None,
    scores: dict[int, float] | None = None,
    include_vectors: bool = False,
    image_side: int = 512,
) -> Path:
    """Construit ``<out_dir>/<date>_<titre>.zip`` et renvoie son chemin.

    data       : AtlasData (analyse + catalogue)
    selection  : comment la sélection a été faite (requête, outil, paramètres) — consigné
    details    : {œuvre: [x0, y0, x1, y1]} zones à recadrer (recherche par détail)
    scores     : {œuvre: score} score de la recherche qui a produit la sélection
    """
    ids = [int(i) for i in dict.fromkeys(artwork_ids) if int(i) in data.row_of]
    if not ids:
        raise ValueError("Aucune œuvre de la sélection n'est dans l'analyse")
    details = details or {}
    scores = scores or {}
    rows = [data.row_of[i] for i in ids]
    meta = data.meta
    feats_p = data.features.manifest["params"]
    question = question.strip() or "Qu'est-ce qui rapproche ces œuvres, et comment l'expliquer ?"
    now = datetime.now(timezone.utc)

    # --- similarités entre œuvres du pack (vecteurs de l'analyse, normalisés)
    fp = Path(data.features.path)
    all_ids = np.load(fp / "ids.npy")
    pos = {int(i): r for r, i in enumerate(all_ids)}
    V = np.load(fp / "global.npy", mmap_mode="r")
    X = np.asarray(V[[pos[i] for i in ids]], dtype=np.float32)
    X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
    S = X @ X.T
    text_S = None
    try:
        text_run = data_text_run(data)
        if text_run is not None:
            tp = Path(text_run.path)
            tpos = {int(i): r for r, i in enumerate(np.load(tp / "ids.npy"))}
            if all(i in tpos for i in ids):
                T = np.asarray(np.load(tp / "global.npy", mmap_mode="r")[[tpos[i] for i in ids]], dtype=np.float32)
                T /= np.maximum(np.linalg.norm(T, axis=1, keepdims=True), 1e-12)
                text_S = T @ T.T
    except Exception:
        text_S = None

    pairs = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            pairs.append((float(S[a, b]), a, b))
    pairs.sort(reverse=True)

    # --- fichiers
    def evidence_name(i: int) -> str:
        return f"evidence/{i}.jpg"

    artworks_csv = io.StringIO()
    meta_keys = sorted({k for i in ids for k in meta.get(i, {})})
    fields = ["id", "image", "label", *meta_keys, "group", "family_hdbscan", "atypicality", "search_score",
              "detail_image", "width", "height", "filename"]
    w = csv.DictWriter(artworks_csv, fieldnames=fields)
    w.writeheader()
    sizes = data.sizes(ids)
    conn = data._conn(data.settings)
    names = {r[0]: Path(r[1]).name for r in conn.execute(
        f"SELECT id, path FROM artworks WHERE id IN ({','.join('?' * len(ids))})", ids)}
    conn.close()
    for i, r in zip(ids, rows):
        w.writerow({
            "id": i, "image": evidence_name(i), "label": data.label(i),
            **{k: meta.get(i, {}).get(k, "") for k in meta_keys},
            "group": int(data.clusters[r]) + 1,
            "family_hdbscan": "" if data.hdbscan is None else ("à part" if data.hdbscan[r] < 0 else int(data.hdbscan[r]) + 1),
            "atypicality": round(float(data.atypicality[r]), 3),
            "search_score": scores.get(i, ""),
            "detail_image": f"evidence/detail_{i}.jpg" if i in details else "",
            "width": sizes.get(i, ("", ""))[0], "height": sizes.get(i, ("", ""))[1],
            "filename": names.get(i, ""),
        })

    relations_csv = io.StringIO()
    w = csv.writer(relations_csv)
    w.writerow(["a", "b", "similarite_visuelle_dinov3", "similarite_semantique_siglip", "meme_groupe"])
    for s, a, b in pairs:
        w.writerow([ids[a], ids[b], round(s, 4),
                    "" if text_S is None else round(float(text_S[a, b]), 4),
                    int(data.clusters[rows[a]] == data.clusters[rows[b]])])

    # --- summary.md
    lines = [f"# {title}", "", f"*Research Pack PixPlot v2 — {now:%d/%m/%Y %H:%M} UTC — {len(ids)} œuvres*", "",
             "## Question de recherche", "", question, ""]
    if selection:
        lines += ["## Comment cette sélection a été faite", ""]
        lines += [f"- **{k}** : {v}" for k, v in selection.items()]
        lines += [""]
    lines += ["## Méthode", "",
              f"- Ressemblance visuelle : **{feats_p.get('encoder')}** ({feats_p.get('weights', '')}), "
              f"image entière sans recadrage, {feats_p.get('input_size')} px. Run `{data.features.id}`.",
              f"- Groupes : e-means sur ces vecteurs ; carte UMAP ; analyse `{data.analysis.id}`.",
              "- Atypicité : 0 = œuvre très entourée de voisines semblables, 1 = très isolée (rang centile)."]
    if text_S is not None:
        lines += ["- Similarité sémantique : SigLIP 2 (relations.csv, colonne siglip)."]
    lines += [""]
    lines += ["## Composition du dossier", ""]
    for key in ("artist", "style", "genre", "date"):
        dist = _distribution(meta, ids, key)
        if dist:
            lines.append(f"- **{key}** : " + ", ".join(f"{v} ({c})" for v, c in dist))
    groups = Counter(int(data.clusters[r]) + 1 for r in rows)
    lines += [f"- **groupes PixPlot** : " + ", ".join(f"groupe {g} ({c})" for g, c in groups.most_common()), ""]

    lines += ["## Œuvres", "", "| n° | image | description | groupe | atypicité | score |", "|---|---|---|---|---|---|"]
    for i, r in zip(ids, rows):
        det = f" + [détail](evidence/detail_{i}.jpg)" if i in details else ""
        lines.append(f"| {i} | [{i}.jpg]({evidence_name(i)}){det} | {data.label(i)} | {int(data.clusters[r]) + 1} | "
                     f"{float(data.atypicality[r]):.2f} | {scores.get(i, '')} |")
    lines += ["", "## Relations les plus fortes (ressemblance visuelle)", ""]
    for s, a, b in pairs[:15]:
        lines.append(f"- {ids[a]} ↔ {ids[b]} : {s:.3f}  ({data.label(ids[a])} / {data.label(ids[b])})")
    atyp = sorted(zip(ids, rows), key=lambda t: -float(data.atypicality[t[1]]))[:5]
    lines += ["", "## Œuvres les plus atypiques du dossier", ""]
    lines += [f"- {i} : atypicité {float(data.atypicality[r]):.2f} — {data.label(i)}" for i, r in atyp]
    lines += ["", "## Mises en garde", ""] + [f"- {c}" for c in CAVEATS]
    lines += ["", "## Consigne proposée pour un LLM", "", "```", PROMPT.format(question=question).strip(), "```", ""]
    summary = "\n".join(lines)

    manifest = {
        "format": "pixplot-research-pack", "format_version": 1, "pixplot": __version__,
        "title": title, "question": question, "created": now.isoformat(timespec="seconds"),
        "count": len(ids), "artwork_ids": ids, "selection": selection or {},
        "models": {"visual": {k: feats_p.get(k) for k in ("encoder", "weights", "input_size", "source")}},
        "runs": {"features": data.features.id, "analysis": data.analysis.id,
                 "analysis_params": data.analysis.manifest.get("params", {})},
        "files": ["summary.md", "artworks.csv", "relations.csv", "evidence/"] + (["vectors.npy"] if include_vectors else []),
        "caveats": CAVEATS,
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    zpath = out_dir / f"{now:%Y%m%d-%H%M%S}_{_slug(title)}.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("summary.md", summary)
        z.writestr("artworks.csv", artworks_csv.getvalue())
        z.writestr("relations.csv", relations_csv.getvalue())
        for i in ids:
            t = thumb_path(data.settings.thumbs_dir, i, 1024)
            if t.exists():
                z.writestr(evidence_name(i), _jpeg(t, image_side))
            if i in details:
                src = data.original_path(i)
                if src is not None and src.exists():
                    z.writestr(f"evidence/detail_{i}.jpg", _crop_jpeg(src, details[i]))
        if include_vectors:
            buf = io.BytesIO()
            np.save(buf, X)
            z.writestr("vectors.npy", buf.getvalue())
    return zpath


def data_text_run(data):
    """Run SigLIP 2 le plus récent couvrant ce catalogue, s'il existe."""
    from ..runs import list_runs
    runs = [r for r in list_runs("features", runs_dir=data.settings.runs_dir)
            if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")]
    return runs[-1] if runs else None
