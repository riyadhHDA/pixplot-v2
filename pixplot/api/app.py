"""API FastAPI de PixPlot v2 + service de l'interface web (dossier ``web/``).

Local d'abord : le serveur n'écoute que sur 127.0.0.1 par défaut, et ne sert que les
images du catalogue, par identifiant (jamais un chemin fourni par le navigateur).
"""

from __future__ import annotations

import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..catalog.ingest import THUMB_SIZES, thumb_path
from .data import AtlasData
from .search import SearchEngines, SearchUnavailable

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
CACHE = {"Cache-Control": "public, max-age=86400"}


class PackQuery(BaseModel):
    ids: list[int] = Field(..., min_length=1, max_length=500)
    title: str = Field("Research Pack", max_length=200)
    question: str = Field("", max_length=2000)
    selection: dict[str, str] = Field(default_factory=dict)
    scores: dict[int, float] = Field(default_factory=dict)
    details: dict[int, list[float]] = Field(default_factory=dict)


class NoteIn(BaseModel):
    title: str = Field("", max_length=300)
    kind: str = Field("note", max_length=20)
    note: str = Field("", max_length=20000)
    artwork_ids: list[int] = Field(default_factory=list, max_length=5000)
    context: dict = Field(default_factory=dict)


class PairIn(BaseModel):
    a: int
    b: int
    type: str = Field(..., max_length=40)
    status: str = Field("validée", max_length=20)
    source: str = Field("", max_length=500)
    note: str = Field("", max_length=5000)


class NotePatch(BaseModel):
    title: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=20000)
    artwork_ids: list[int] | None = Field(None, max_length=5000)


class RegionQuery(BaseModel):
    id: int
    box: list[float] = Field(..., min_length=4, max_length=4, description="[x0, y0, x1, y1] en fractions de l'image")
    k: int = Field(30, ge=1, le=200)


def create_app(data: AtlasData, web_dir: Path = WEB_DIR, engines: SearchEngines | None = None) -> FastAPI:
    app = FastAPI(title="PixPlot v2", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    map_cache: dict = {}

    @app.middleware("http")
    async def no_stale_interface(request, call_next):
        # L'interface (HTML/JS/CSS) est toujours revalidée : après une mise à jour, le
        # navigateur ne mélange jamais une ancienne page et un nouveau script.
        response = await call_next(request)
        if not request.url.path.startswith("/api/") and not request.url.path.startswith("/vendor/"):
            response.headers["Cache-Control"] = "no-cache"
        return response
    engines = engines or SearchEngines(data)

    @app.post("/api/pack")
    def pack(q: PackQuery):
        from ..export.pack import build_pack

        try:
            path = build_pack(data, q.ids, data.settings.data_dir / "packs", q.title or "Research Pack",
                              question=q.question, selection=q.selection or {"méthode": "sélection dans l'Atlas"},
                              details={int(k): v for k, v in q.details.items() if len(v) == 4},
                              scores={int(k): v for k, v in q.scores.items()})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return FileResponse(path, media_type="application/zip", filename=path.name)

    @app.get("/api/search/status")
    def search_status():
        return engines.status()

    @app.post("/api/search/region")
    def search_region(q: RegionQuery):
        try:
            return engines.region(q.id, q.box, k=q.k)
        except SearchUnavailable as exc:
            raise HTTPException(503, str(exc))
        except KeyError:
            raise HTTPException(404, "Œuvre ou image originale introuvable")
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.get("/api/search/text")
    def search_text(q: str = Query(..., min_length=2, max_length=300), k: int = Query(60, ge=1, le=500)):
        try:
            return engines.text(q, k=k)
        except SearchUnavailable as exc:
            raise HTTPException(503, str(exc))

    @app.get("/api/info")
    def info():
        return data.info()

    @app.get("/api/map")
    def map_():
        if "map" not in map_cache:
            map_cache["map"] = data.map_payload()
        return JSONResponse(map_cache["map"])

    @app.get("/api/disagreements")
    def disagreements_list(near: str, far: str, offset: int = Query(0, ge=0), limit: int = Query(40, ge=1, le=200)):
        out = data.disagreements_payload(near, far, offset, limit)
        if out is None:
            raise HTTPException(404, "Pas de désaccords pour ces regards : lancez `pixplot disagreements`.")
        return out

    @app.get("/api/communities/{space}")
    def space_communities(space: str):
        key = f"communities:{space}"
        if key not in map_cache:
            out = data.communities_payload(space)
            if out is None:
                raise HTTPException(404, f"Pas de groupes Leiden pour « {space} » : lancez `pixplot communities`.")
            map_cache[key] = out
        return JSONResponse(map_cache[key])

    @app.get("/api/layout/{space}")
    def space_layout(space: str):
        if space not in map_cache:
            out = data.space_map_payload(space)
            if out is None:
                raise HTTPException(404, f"Pas de carte pour « {space} » : lancez `pixplot maps`.")
            map_cache[space] = out
        return JSONResponse(map_cache[space])

    @app.get("/api/clusters")
    def clusters():
        return data.clusters_payload()

    @app.get("/api/artwork/{artwork_id}")
    def artwork(artwork_id: int, k: int = Query(20, ge=1, le=100), space: str | None = None):
        if space and space not in data.spaces.runs:
            raise HTTPException(400, f"Espace inconnu : {space}")
        out = data.artwork(artwork_id, k=k, space=space)
        if out is None:
            raise HTTPException(404, "Œuvre absente de cette analyse")
        return out

    # ------------------------------------------------------------- carnet de recherche
    from ..notebook import Notebook
    notebook = Notebook(data.settings.data_dir / "notebook.sqlite")

    @app.get("/api/notebook")
    def notebook_list(q: str = ""):
        return {"entries": notebook.list(q)}

    @app.post("/api/notebook")
    def notebook_add(entry: NoteIn):
        try:
            return notebook.add(entry.title, entry.kind, entry.note, entry.artwork_ids, entry.context)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @app.patch("/api/notebook/{entry_id}")
    def notebook_update(entry_id: int, patch: NotePatch):
        out = notebook.update(entry_id, patch.title, patch.note, patch.artwork_ids)
        if out is None:
            raise HTTPException(404, "Entrée introuvable")
        return out

    @app.delete("/api/notebook/{entry_id}")
    def notebook_delete(entry_id: int):
        if not notebook.delete(entry_id):
            raise HTTPException(404, "Entrée introuvable")
        return {"deleted": entry_id}

    @app.get("/api/notebook/export.md")
    def notebook_export():
        from fastapi.responses import Response
        md = notebook.to_markdown(lambda i: data.label(i) if i in data.row_of else f"Œuvre {i}")
        return Response(md, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="carnet-pixplot.md"'})

    # ------------------------------------------------------------- paires du banc d'essai
    from ..analysis import pairbench

    pairs_file = pairbench.pairs_path(data.settings)

    @app.get("/api/pairs")
    def pairs_list(ids: str = ""):
        wanted = {int(x) for x in ids.split(",") if x.strip().isdigit()}
        pairs = [p for p in pairbench.load_pairs(pairs_file) if p.origin == "annotée"
                 and (not wanted or (p.a in wanted and p.b in wanted))]
        label = lambda i: data.label(i) if i in data.row_of else f"Œuvre {i} (hors analyse)"
        return {"types": [{"key": k, "label": v[0], "expected": v[1], "question": v[2]}
                          for k, v in pairbench.TYPES.items() if k != "temoin"],
                "statuses": list(pairbench.STATUSES),
                "pairs": [{**p.__dict__, "label_a": label(p.a), "label_b": label(p.b)} for p in pairs]}

    @app.post("/api/pairs")
    def pairs_add(pair: PairIn):
        if pair.a not in data.row_of or pair.b not in data.row_of:
            raise HTTPException(404, "Œuvre absente de cette analyse")
        try:
            p = pairbench.add_pair(pairs_file, pairbench.Pair(pair.a, pair.b, pair.type, "annotée",
                                                              pair.status, pair.source, pair.note))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return p.__dict__

    # ------------------------------------------------------------- étiquettes à vérifier
    @app.get("/api/suspects")
    def suspects(key: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(60, ge=1, le=500)):
        if not data.suspects:
            raise HTTPException(404, "Pas encore calculé : lancez `pixplot suspects`.")
        groups = data.suspects["suspects"]
        key = key or next(iter(groups), None)
        if key not in groups:
            raise HTTPException(400, f"Étiquette inconnue : {key} (disponibles : {', '.join(groups)})")
        items = [d for d in groups[key] if d["id"] in data.row_of]
        page = [{**d, **data.brief(d["id"])} for d in items[offset:offset + limit]]
        return {"key": key, "keys": list(groups), "total": len(items), "space": data.suspects["space"],
                "rule": data.suspects["rule"], "items": page}

    @app.get("/api/spaces")
    def spaces():
        return {"main": data.spaces.main, "spaces": data.spaces.list()}

    @app.get("/api/compare")
    def compare(ids: str = Query(..., description="identifiants séparés par des virgules")):
        try:
            wanted = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(400, "Identifiants invalides")
        if not 2 <= len(wanted) <= 6:
            raise HTTPException(400, "Comparer de 2 à 6 œuvres")
        missing = [i for i in wanted if i not in data.row_of]
        if missing:
            raise HTTPException(404, f"Œuvres absentes de cette analyse : {missing}")
        return {"ids": wanted, "artworks": [data.artwork(i, k=0) for i in wanted],
                "spaces": data.spaces.list(), "similarity": data.spaces.pairwise(wanted)}

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1, max_length=200)):
        hits = data.search(q)
        return {"query": q, "count": len(hits), "ids": hits}

    sprite_lock = threading.Lock()

    def sprites_meta() -> Path:
        from ..analysis.sprites import build_sprites
        with sprite_lock:  # construites une seule fois, à la première demande si besoin
            return build_sprites(data.analysis, data.settings.thumbs_dir)

    @app.get("/api/sprites")
    def sprites():
        return FileResponse(sprites_meta(), media_type="application/json", headers=CACHE)

    @app.get("/api/sprites/{n}.jpg")
    def sprite_sheet(n: int):
        p = sprites_meta().parent / f"sheet-{n}.jpg"
        if not p.exists():
            raise HTTPException(404, "Planche inexistante")
        return FileResponse(p, media_type="image/jpeg", headers=CACHE)

    @app.get("/api/thumb/{size}/{artwork_id}")
    def thumb(size: int, artwork_id: int):
        if size not in THUMB_SIZES:
            raise HTTPException(400, f"Tailles disponibles : {THUMB_SIZES}")
        if artwork_id not in data.row_of:
            raise HTTPException(404, "Œuvre inconnue")
        p = thumb_path(data.settings.thumbs_dir, artwork_id, size)
        if not p.exists():
            raise HTTPException(404, "Vignette absente")
        return FileResponse(p, media_type="image/webp", headers=CACHE)

    @app.get("/api/image/{artwork_id}")
    def image(artwork_id: int):
        p = data.original_path(artwork_id)
        if p is None or not p.exists():
            raise HTTPException(404, "Image originale introuvable")
        return FileResponse(p, headers=CACHE)

    if web_dir.exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app
