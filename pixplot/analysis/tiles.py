"""Pyramide de tuiles précalculées pour la carte principale de l'Atlas (CPU seulement).

Au lieu de charger toutes les planches de vignettes sur le GPU dès l'ouverture, la carte UMAP
est découpée en tuiles carrées (512 × 512 px) à plusieurs niveaux de zoom, comme une carte
géographique en ligne, servies au ``TileLayer`` de deck.gl.

Structure d'un run ``runs/tiles/<analyse>_<AAAAMMJJ-HHMMSS>/`` :
    manifest.json        métadonnées standard du run (``stage: "tiles"``, ``parent: "analysis/..."``)
    tiles.json           paramètres géométriques et liste des tuiles non vides par niveau
    <niveau>/<x>/<y>.webp   tuiles (``x`` de gauche à droite, ``y`` de haut en bas)

Le niveau le plus fin (``max_level``) est rendu tuile par tuile dans l'ordre exact des lignes
de l'analyse (identique aux planches WebGL), puis chaque niveau supérieur est réduit 2 × 2 en
Lanczos à partir de ses quatre tuiles filles. Chaque fichier est écrit de façon atomique
(``.tmp`` puis ``os.replace``) : une interruption permet de reprendre sans recalculer les tuiles
déjà produites.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from ..catalog.ingest import thumb_path
from ..runs import Run, create_run, list_runs

WORLD = 1000.0
DEFAULT_EXTENT = 1024.0
DEFAULT_TILE_SIZE = 512
DEFAULT_MAX_LEVEL = 4
DEFAULT_FORMAT = "webp"
DEFAULT_QUALITY = 85
BACKGROUND = (15, 15, 16)  # #0f0f10, fond --bg de web/atlas.css
SUPPORTED_FORMATS = ("webp", "jpg", "png")


def icon_size_for(n: int) -> float:
    """Taille d'une vignette en unités monde — même formule que ``web/atlas-base.js``."""
    return max(2.0, min(40.0, (2.0 * WORLD / math.sqrt(max(n, 1))) * 0.9))


def tile_path(run_dir: Path, level: int, tx: int, ty: int, fmt: str = DEFAULT_FORMAT) -> Path:
    return run_dir / str(level) / str(tx) / f"{ty}.{fmt}"


def find_tiles_run(analysis: Run, runs_dir: Path) -> Run | None:
    """Dernier run ``tiles`` terminé correspondant à cette analyse."""
    matches = [
        r for r in list_runs("tiles", status="complete", runs_dir=runs_dir)
        if r.manifest.get("parent") == analysis.id and (r.path / "tiles.json").exists()
    ]
    return matches[-1] if matches else None


def _find_resumable(analysis: Run, runs_dir: Path, params: dict) -> Run | None:
    candidates = [
        r for r in list_runs("tiles", status=None, runs_dir=runs_dir)
        if r.manifest.get("parent") == analysis.id
        and r.manifest.get("status") in ("running", "failed")
        and r.manifest.get("params") == params
    ]
    return candidates[-1] if candidates else None


def _save_atomic(im: Image.Image, path: Path, fmt: str, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    if fmt == "webp":
        im.save(tmp, format="WEBP", quality=quality, method=4)
    elif fmt == "jpg":
        im.save(tmp, format="JPEG", quality=quality, optimize=True)
    elif fmt == "png":
        im.save(tmp, format="PNG", optimize=True)
    else:
        raise ValueError(f"Format de tuile inconnu : {fmt}")
    os.replace(tmp, path)


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _log(log_path: Path | None, msg: str) -> None:
    if log_path is None:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"[{stamp}] {msg}\n")


class _ThumbSource:
    """Fournit la vignette d'une œuvre (rang ``r``) depuis les planches déjà assemblées si leur
    résolution suffit, sinon depuis ``thumbs/<64|256>/``."""

    def __init__(self, analysis_dir: Path, ids: np.ndarray, thumbs_dir: Path, target_px: float):
        self.ids = ids
        self.thumbs_dir = thumbs_dir
        self.src_size = 64 if target_px <= 64 else 256
        self.sprites_meta = None
        self.sheets: list[Image.Image] = []
        meta_path = analysis_dir / "sprites" / "sprites.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("count") == len(ids) and target_px <= meta.get("cell", 0) + 4:
                sheets_ok = True
                loaded: list[Image.Image] = []
                for s in range(meta["sheets"]):
                    sp = analysis_dir / "sprites" / f"sheet-{s}.jpg"
                    if not sp.exists():
                        sheets_ok = False
                        break
                    im = Image.open(sp)
                    im.load()
                    loaded.append(im)
                if sheets_ok:
                    self.sprites_meta = meta
                    self.sheets = loaded
                else:
                    for im in loaded:
                        im.close()

    @property
    def kind(self) -> str:
        return "sprites" if self.sprites_meta is not None else f"thumbs/{self.src_size}"

    def aspect(self, r: int) -> float:
        if self.sprites_meta is not None:
            w = self.sprites_meta["w"][r]
            h = self.sprites_meta["h"][r]
            return w / max(h, 1)
        return 1.0

    def get(self, r: int) -> Image.Image | None:
        if self.sprites_meta is not None:
            m = self.sprites_meta
            s = m["atlas"][r]
            x, y, w, h = m["x"][r], m["y"][r], m["w"][r], m["h"][r]
            if w <= 0 or h <= 0:
                return None
            return self.sheets[s].crop((x, y, x + w, y + h))
        p = thumb_path(self.thumbs_dir, int(self.ids[r]), self.src_size)
        if not p.exists():
            return None
        try:
            with Image.open(p) as im:
                return im.convert("RGB")
        except OSError:
            return None

    def close(self) -> None:
        for im in self.sheets:
            im.close()
        self.sheets.clear()


def build_tiles(
    analysis: Run,
    thumbs_dir: Path,
    runs_dir: Path,
    *,
    max_level: int = DEFAULT_MAX_LEVEL,
    tile_size: int = DEFAULT_TILE_SIZE,
    extent: float = DEFAULT_EXTENT,
    fmt: str = DEFAULT_FORMAT,
    quality: int = DEFAULT_QUALITY,
    resume: bool = True,
    log_path: Path | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Run:
    """Construit la pyramide de tuiles de la carte principale (CPU seulement, reprenable)."""
    if fmt not in SUPPORTED_FORMATS:
        raise ValueError(f"Format non pris en charge : {fmt} (attendu : {', '.join(SUPPORTED_FORMATS)})")
    if max_level < 0 or max_level > 7:
        raise ValueError(f"max_level hors bornes (0..7) : {max_level}")
    if tile_size < 64 or tile_size > 2048:
        raise ValueError(f"tile_size hors bornes (64..2048) : {tile_size}")

    analysis_dir = Path(analysis.path)
    ids = np.load(analysis_dir / "ids.npy")
    coords = np.load(analysis_dir / "coords.npy")
    n = len(ids)
    icon_sz = icon_size_for(n)

    params = {
        "tile_size": int(tile_size),
        "max_level": int(max_level),
        "extent": float(extent),
        "world": float(WORLD),
        "format": fmt,
        "quality": int(quality),
        "background": list(BACKGROUND),
    }

    resumed = False
    run = _find_resumable(analysis, runs_dir, params) if resume else None
    if run is not None:
        resumed = True
        run.manifest["status"] = "running"
        run.manifest.pop("error", None)
        run.save()
    else:
        run = create_run("tiles", name=analysis_dir.name, params=params, parent=analysis, runs_dir=runs_dir)

    t0 = time.perf_counter()
    grid_max = 1 << max_level
    canvas_px = grid_max * tile_size
    px_per_world = canvas_px / (2.0 * extent)
    icon_px = icon_sz * px_per_world

    _log(log_path, f"{'Reprise' if resumed else 'Début'} {run.id} · parent={analysis.id} · "
         f"n={n} · niveaux=0..{max_level} · tuile={tile_size}px · {fmt}(q={quality})")

    source = _ThumbSource(analysis_dir, ids, thumbs_dir, icon_px)
    _log(log_path, f"Source vignettes : {source.kind} (taille cible au niveau {max_level} : {icon_px:.1f} px)")

    try:
        # 1. Assigner chaque œuvre aux tuiles qu'elle recouvre au niveau le plus fin.
        # On utilise le demi-côté maximal (icon_px / 2) pour ne jamais tronquer une œuvre à cheval sur un bord.
        half_max = max(1.0, icon_px * 0.5)
        cx_all = (coords[:, 0].astype(np.float64) * WORLD + extent) * px_per_world
        cy_all = (extent - coords[:, 1].astype(np.float64) * WORLD) * px_per_world

        buckets: dict[tuple[int, int], list[int]] = defaultdict(list)
        for r in range(n):
            cx, cy = cx_all[r], cy_all[r]
            tx0 = max(0, int(math.floor((cx - half_max) / tile_size)))
            tx1 = min(grid_max - 1, int(math.floor((cx + half_max) / tile_size)))
            ty0 = max(0, int(math.floor((cy - half_max) / tile_size)))
            ty1 = min(grid_max - 1, int(math.floor((cy + half_max) / tile_size)))
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    buckets[(tx, ty)].append(r)

        # Prévoir les tuiles non vides à chaque niveau (pour la barre de progression).
        level_keys: dict[int, set[tuple[int, int]]] = {max_level: set(buckets.keys())}
        for lv in range(max_level - 1, -1, -1):
            level_keys[lv] = {(tx // 2, ty // 2) for (tx, ty) in level_keys[lv + 1]}
        total_tiles = sum(len(s) for s in level_keys.values())
        done_tiles = 0
        skipped_tiles = 0

        # 2. Rendu du niveau le plus fin (max_level).
        t_lv = time.perf_counter()
        resample = Image.Resampling.BILINEAR if icon_px <= 36 else Image.Resampling.LANCZOS
        for (tx, ty) in sorted(level_keys[max_level]):
            out_path = tile_path(run.path, max_level, tx, ty, fmt)
            if resumed and out_path.exists():
                skipped_tiles += 1
                done_tiles += 1
                if progress:
                    progress(done_tiles, total_tiles)
                continue
            tile = Image.new("RGB", (tile_size, tile_size), BACKGROUND)
            ox_tile = tx * tile_size
            oy_tile = ty * tile_size
            # Ordre croissant des lignes r : exactement le même empilement que IconLayer.
            for r in buckets[(tx, ty)]:
                im = source.get(r)
                if im is None:
                    continue
                iw, ih = im.size
                if iw <= 0 or ih <= 0:
                    continue
                scale = icon_px / max(iw, ih)
                tw = max(1, int(round(iw * scale)))
                th = max(1, int(round(ih * scale)))
                if tw != iw or th != ih:
                    im = im.resize((tw, th), resample)
                px = int(round(cx_all[r] - ox_tile - tw * 0.5))
                py = int(round(cy_all[r] - oy_tile - th * 0.5))
                tile.paste(im, (px, py))
            _save_atomic(tile, out_path, fmt, quality)
            done_tiles += 1
            if progress:
                progress(done_tiles, total_tiles)

        _log(log_path, f"Niveau {max_level} ({len(level_keys[max_level])} tuiles) : "
             f"{time.perf_counter() - t_lv:.2f} s")

        # 3. Réduction 2 × 2 de niveau en niveau (max_level - 1 → 0).
        for lv in range(max_level - 1, -1, -1):
            t_lv = time.perf_counter()
            for (tx, ty) in sorted(level_keys[lv]):
                out_path = tile_path(run.path, lv, tx, ty, fmt)
                if resumed and out_path.exists():
                    skipped_tiles += 1
                    done_tiles += 1
                    if progress:
                        progress(done_tiles, total_tiles)
                    continue
                mosaic = Image.new("RGB", (tile_size * 2, tile_size * 2), BACKGROUND)
                for dx in (0, 1):
                    for dy in (0, 1):
                        child = tile_path(run.path, lv + 1, tx * 2 + dx, ty * 2 + dy, fmt)
                        if child.exists():
                            with Image.open(child) as cim:
                                mosaic.paste(cim, (dx * tile_size, dy * tile_size))
                reduced = mosaic.resize((tile_size, tile_size), Image.Resampling.LANCZOS)
                _save_atomic(reduced, out_path, fmt, quality)
                done_tiles += 1
                if progress:
                    progress(done_tiles, total_tiles)
            _log(log_path, f"Niveau {lv} ({len(level_keys[lv])} tuiles) : "
                 f"{time.perf_counter() - t_lv:.2f} s")

        # 4. Métadonnées tiles.json + finalisation du run.
        total_bytes = 0
        levels_meta: dict[str, list[str]] = {}
        for lv in range(max_level + 1):
            entries = []
            for (tx, ty) in sorted(level_keys[lv]):
                p = tile_path(run.path, lv, tx, ty, fmt)
                if p.exists():
                    total_bytes += p.stat().st_size
                    entries.append(f"{tx}/{ty}")
            levels_meta[str(lv)] = entries

        meta = {
            "format": fmt,
            "tile_size": int(tile_size),
            "extent": float(extent),
            "world": float(WORLD),
            "min_level": 0,
            "max_level": int(max_level),
            "background": list(BACKGROUND),
            "icon_size": round(icon_sz, 4),
            "count": int(n),
            "analysis": analysis.id,
            "levels": levels_meta,
        }
        _write_json_atomic(run.path / "tiles.json", meta)

        duration = round(time.perf_counter() - t0, 2)
        run.complete(
            tiles=total_tiles,
            skipped_tiles=skipped_tiles,
            resumed=resumed,
            levels=max_level + 1,
            source=source.kind,
            bytes=total_bytes,
            duration_s=duration,
        )
        _log(log_path, f"Terminé {run.id} · {total_tiles} tuiles ({skipped_tiles} reprises) · "
             f"{total_bytes / (1024 * 1024):.2f} Mio · {duration:.2f} s")
        return run
    except BaseException as exc:
        run.fail(exc)
        _log(log_path, f"Échec {run.id} : {exc}")
        raise
    finally:
        source.close()
