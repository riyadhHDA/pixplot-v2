"""API FastAPI de PixPlot v2 + service de l'interface web (dossier ``web/``).

Local d'abord : le serveur n'écoute que sur 127.0.0.1 par défaut, et ne sert que les
images du catalogue, par identifiant (jamais un chemin fourni par le navigateur).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..catalog.ingest import THUMB_SIZES, thumb_path
from .data import AtlasData

WEB_DIR = Path(__file__).resolve().parents[2] / "web"
CACHE = {"Cache-Control": "public, max-age=86400"}


def create_app(data: AtlasData, web_dir: Path = WEB_DIR) -> FastAPI:
    app = FastAPI(title="PixPlot v2", docs_url="/api/docs", redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    map_cache: dict = {}

    @app.get("/api/info")
    def info():
        return data.info()

    @app.get("/api/map")
    def map_():
        if "map" not in map_cache:
            map_cache["map"] = data.map_payload()
        return JSONResponse(map_cache["map"])

    @app.get("/api/clusters")
    def clusters():
        return data.clusters_payload()

    @app.get("/api/artwork/{artwork_id}")
    def artwork(artwork_id: int, k: int = Query(20, ge=1, le=100)):
        out = data.artwork(artwork_id, k=k)
        if out is None:
            raise HTTPException(404, "Œuvre absente de cette analyse")
        return out

    @app.get("/api/search")
    def search(q: str = Query(..., min_length=1, max_length=200)):
        hits = data.search(q)
        return {"query": q, "count": len(hits), "ids": hits}

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
