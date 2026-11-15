"""Serveur MCP de PixPlot v2 : donne à Claude (ou à un autre LLM) un accès direct au corpus.

PixPlot calcule, observe et organise ; le LLM questionne et propose ; l'historien vérifie.

Le LLM peut chercher (texte, voisines, détail), consulter des fiches, **voir** les œuvres,
les détails et des planches de comparaison, explorer les groupes et les œuvres atypiques,
puis exporter un Research Pack. Transport : stdio (lancé par le client MCP).
Les sorties standard sont réservées au protocole : aucun ``print`` ici.
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image as PILImage, ImageDraw, ImageFont

from ..api.data import AtlasData
from ..api.search import SearchEngines, SearchUnavailable
from ..catalog.ingest import thumb_path
from ..config import Settings
from ..export import selection as sel
from ..export.pack import build_pack
from ..runs import Run

INSTRUCTIONS = """Tu as accès à PixPlot v2, un corpus d'œuvres d'art analysé par des modèles de vision
(DINOv3 pour la ressemblance visuelle, SigLIP 2 pour la recherche par description).

Méthode conseillée :
1. corpus_overview pour connaître le corpus, ses groupes et ce qui est disponible.
2. Chercher : search_by_text (description, en français ou en anglais), similar_artworks,
   search_detail (un cadre sur une œuvre : main, drapé, objet…), get_group, find_atypical.
3. Regarder : view_artwork, view_detail, compare_artworks (planche numérotée). Ne conclus
   jamais sur une œuvre sans l'avoir regardée.
4. Documenter : export_research_pack pour un dossier traçable.

Règles : une proximité calculée est une piste, pas une preuve d'influence ni d'attribution.
Les scores sont des similarités cosinus, pas des probabilités. Distingue toujours ce qui se
voit, ce que disent les métadonnées (avec leur source), ce que calcule PixPlot, et ton
interprétation. Cherche activement les contre-exemples."""

MAX_COMPARE = 12


def _jpeg(im: PILImage.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _font(size: int):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_server(data: AtlasData, engines: SearchEngines | None = None):
    from mcp.server.mcpserver import Image, MCPServer

    engines = engines or SearchEngines(data)
    server = MCPServer(name="pixplot", title="PixPlot v2", instructions=INSTRUCTIONS,
                       version="0.1.0", log_level="WARNING")

    def check(artwork_id: int) -> int:
        artwork_id = int(artwork_id)
        if artwork_id not in data.row_of:
            raise ValueError(f"Œuvre {artwork_id} inconnue dans cette analyse")
        return artwork_id

    # ------------------------------------------------------------------ vue d'ensemble
    @server.tool()
    def corpus_overview() -> dict:
        """Le corpus : taille, modèles, groupes (avec artiste/style/genre dominants), recherches disponibles."""
        groups = [{"group": g["number"], "size": g["size"], "representative": g["representative"],
                   "dominant": {k: [f"{v['value']} ({round(v['share'] * 100)} %)" for v in vs]
                                for k, vs in g["dominant"].items()}}
                  for g in data.clusters_payload()]
        return {**data.info(), "search": engines.status(), "groups": groups}

    # ------------------------------------------------------------------ recherches
    @server.tool()
    def search_by_text(query: str, k: int = 20) -> dict:
        """Œuvres correspondant à une description en langage naturel (SigLIP 2, multilingue).
        Ex. « Annonciation dans un jardin », « saint Sébastien attaché à un arbre »."""
        try:
            return engines.text(query, k=min(max(k, 1), 100))
        except SearchUnavailable as exc:
            return {"error": str(exc)}

    @server.tool()
    def similar_artworks(artwork_id: int, k: int = 20) -> dict:
        """Les œuvres visuellement les plus proches d'une œuvre (DINOv3), avec leur score."""
        a = data.artwork(check(artwork_id), k=min(max(k, 1), 100))
        return {"artwork": {"id": a["id"], "label": a["label"], "group": a["cluster"]},
                "neighbors": a["neighbors"]}

    @server.tool()
    def search_detail(artwork_id: int, x0: float, y0: float, x1: float, y1: float, k: int = 20) -> dict:
        """Cherche dans tout le corpus les zones semblables à un détail d'une œuvre.
        Le cadre est en fractions de l'image (0 = gauche/haut, 1 = droite/bas).
        Chaque résultat donne la zone trouvée (box) : à regarder avec view_detail."""
        try:
            return engines.region(check(artwork_id), [x0, y0, x1, y1], k=min(max(k, 1), 100))
        except SearchUnavailable as exc:
            return {"error": str(exc)}

    # ------------------------------------------------------------------ fiches et images
    @server.tool()
    def get_artwork(artwork_id: int) -> dict:
        """Fiche d'une œuvre : métadonnées (et leur source), groupe, famille HDBSCAN,
        atypicité, 10 plus proches voisines, provenance du calcul."""
        return data.artwork(check(artwork_id), k=10)

    @server.tool()
    def view_artwork(artwork_id: int, size: int = 768):
        """Montre l'image d'une œuvre (côté max 256 à 1024 px)."""
        artwork_id = check(artwork_id)
        t = thumb_path(data.settings.thumbs_dir, artwork_id, 1024)
        with PILImage.open(t) as im:
            im = im.convert("RGB")
            side = min(max(int(size), 256), 1024)
            im.thumbnail((side, side))
            return [f"Œuvre {artwork_id} — {data.label(artwork_id)}", Image(data=_jpeg(im), format="jpeg")]

    @server.tool()
    def view_detail(artwork_id: int, x0: float, y0: float, x1: float, y1: float):
        """Montre un détail recadré d'une œuvre, depuis l'image originale (fractions 0-1)."""
        artwork_id = check(artwork_id)
        src = data.original_path(artwork_id)
        if src is None or not src.exists():
            raise ValueError("Image originale introuvable")
        from ..imageio import open_image
        im = open_image(src, target=4096)
        w, h = im.size
        box = [min(max(float(v), 0.0), 1.0) for v in (x0, y0, x1, y1)]
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Cadre vide : il faut x0 < x1 et y0 < y1")
        crop = im.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
        crop.thumbnail((1024, 1024))
        return [f"Détail de l'œuvre {artwork_id} ({data.label(artwork_id)}), cadre {box}",
                Image(data=_jpeg(crop, 90), format="jpeg")]

    @server.tool()
    def compare_artworks(artwork_ids: list[int]):
        """Planche numérotée de 2 à 12 œuvres côte à côte + matrice de similarité visuelle."""
        ids = [check(i) for i in dict.fromkeys(artwork_ids)][:MAX_COMPARE]
        if len(ids) < 2:
            raise ValueError("Il faut au moins 2 œuvres")
        cols = 4 if len(ids) > 6 else 3 if len(ids) > 4 else len(ids)
        cell, pad, head = 300, 8, 30
        rows_n = (len(ids) + cols - 1) // cols
        sheet = PILImage.new("RGB", (cols * cell, rows_n * (cell + head)), (20, 20, 20))
        draw, font = ImageDraw.Draw(sheet), _font(18)
        for n, i in enumerate(ids):
            with PILImage.open(thumb_path(data.settings.thumbs_dir, i, 1024)) as im:
                im = im.convert("RGB")
                im.thumbnail((cell - 2 * pad, cell - 2 * pad))
                x, y = (n % cols) * cell, (n // cols) * (cell + head)
                sheet.paste(im, (x + (cell - im.width) // 2, y + head + (cell - im.height) // 2))
                draw.text((x + pad, y + 5), f"{n + 1}. n° {i}", fill=(224, 176, 64), font=font)
        fp = Path(data.features.path)
        pos = {int(v): r for r, v in enumerate(np.load(fp / "ids.npy"))}
        X = np.asarray(np.load(fp / "global.npy", mmap_mode="r")[[pos[i] for i in ids]], dtype=np.float32)
        X /= np.maximum(np.linalg.norm(X, axis=1, keepdims=True), 1e-12)
        S = X @ X.T
        legend = "\n".join(f"{n + 1}. n° {i} — {data.label(i)} (groupe {int(data.clusters[data.row_of[i]]) + 1})"
                           for n, i in enumerate(ids))
        matrix = "    " + " ".join(f"{n + 1:>5}" for n in range(len(ids))) + "\n" + "\n".join(
            f"{a + 1:>3} " + " ".join(f"{S[a, b]:>5.2f}" for b in range(len(ids))) for a in range(len(ids)))
        return [legend, Image(data=_jpeg(sheet), format="jpeg"),
                "Similarité visuelle DINOv3 (cosinus) :\n" + matrix]

    # ------------------------------------------------------------------ groupes, atypiques
    @server.tool()
    def get_group(group_number: int, k: int = 20) -> dict:
        """Un groupe de la carte : taille, métadonnées dominantes, œuvres les plus centrales d'abord."""
        info = next((g for g in data.clusters_payload() if g["number"] == int(group_number)), None)
        if info is None:
            raise ValueError(f"Groupe {group_number} inexistant")
        chosen = sel.by_cluster(data, int(group_number), k=min(max(k, 1), 200))
        return {"group": info["number"], "size": info["size"], "dominant": info["dominant"],
                "representative": info["representative"],
                "artworks": [data.brief(i) | {"atypicality": round(float(data.atypicality[data.row_of[i]]), 3)}
                             for i in chosen.ids]}

    @server.tool()
    def find_atypical(k: int = 20, group_number: int | None = None) -> dict:
        """Les œuvres les plus isolées (peu de voisines semblables), dans tout le corpus ou un groupe.
        Utile pour repérer des exceptions, des erreurs de catalogue ou des œuvres singulières."""
        rows = np.arange(len(data.ids))
        if group_number is not None:
            rows = rows[data.clusters == int(group_number) - 1]
        rows = rows[np.argsort(-data.atypicality[rows])][:min(max(k, 1), 200)]
        out = []
        for r in rows:
            i = int(data.ids[r])
            out.append(data.brief(i) | {"atypicality": round(float(data.atypicality[r]), 3),
                                        "hdbscan_isolated": bool(data.hdbscan is not None and data.hdbscan[r] < 0)})
        return {"artworks": out}

    # ------------------------------------------------------------------ export
    @server.tool()
    def export_research_pack(artwork_ids: list[int], title: str, question: str = "") -> dict:
        """Exporte un Research Pack (.zip : images, métadonnées sourcées, relations chiffrées,
        résumé, provenance des calculs) pour documenter une piste de recherche."""
        chosen = sel.by_ids(data, artwork_ids)
        chosen.how["méthode"] = "sélection faite par un assistant (serveur MCP PixPlot)"
        path = build_pack(data, chosen.ids, data.settings.data_dir / "packs", title,
                          question=question, selection=chosen.how)
        return {"path": str(path), "artworks": len(chosen.ids), "size_mb": round(path.stat().st_size / 2**20, 2)}

    return server


def run(settings: Settings, analysis_name: str | None = None) -> None:
    analysis = Run.load(settings.runs_dir / "analysis" / analysis_name) if analysis_name else None
    data = AtlasData.load(settings, analysis)
    create_server(data).run("stdio")
