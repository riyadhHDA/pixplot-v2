"""Runs versionnés : chaque étape du pipeline écrit dans son propre dossier.

    data/runs/<étape>/<nom>_<horodatage>/manifest.json

Le manifest enregistre les paramètres, le run parent, les versions et le statut
(``running`` → ``complete`` ou ``failed``). Un run n'est jamais écrasé : c'est ce qui
rend chaque résultat traçable et reproductible.
"""

from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import get_settings

MANIFEST = "manifest.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # écriture atomique


@dataclass
class Run:
    path: Path
    manifest: dict[str, Any]

    @property
    def id(self) -> str:
        return f"{self.manifest['stage']}/{self.path.name}"

    def save(self) -> None:
        _write_json(self.path / MANIFEST, self.manifest)

    def complete(self, **outputs: Any) -> None:
        self.manifest.update(status="complete", finished=_now())
        self.manifest.setdefault("outputs", {}).update(outputs)
        self.save()

    def fail(self, error: BaseException | str) -> None:
        self.manifest.update(status="failed", finished=_now(), error=str(error))
        self.save()

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Run":
        path = Path(path)
        manifest = json.loads((path / MANIFEST).read_text(encoding="utf-8"))
        return cls(path=path, manifest=manifest)


def _stage_dir(stage: str, runs_dir: Path | None) -> Path:
    return (runs_dir or get_settings().runs_dir) / stage


def create_run(
    stage: str,
    name: str,
    params: dict[str, Any] | None = None,
    parent: Run | str | None = None,
    runs_dir: Path | None = None,
) -> Run:
    """Crée un nouveau dossier de run avec un manifest au statut ``running``."""
    base = _stage_dir(stage, runs_dir)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / f"{name}_{stamp}"
    n = 1
    while path.exists():
        n += 1
        path = base / f"{name}_{stamp}-{n}"
    path.mkdir()

    manifest = {
        "stage": stage,
        "name": name,
        "status": "running",
        "created": _now(),
        "params": params or {},
        "parent": parent.id if isinstance(parent, Run) else parent,
        "env": {
            "pixplot": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }
    run = Run(path=path, manifest=manifest)
    run.save()
    return run


def list_runs(
    stage: str,
    name: str | None = None,
    status: str | None = "complete",
    runs_dir: Path | None = None,
) -> list[Run]:
    """Runs d'une étape, du plus ancien au plus récent."""
    base = _stage_dir(stage, runs_dir)
    if not base.exists():
        return []
    runs = [Run.load(p) for p in base.iterdir() if (p / MANIFEST).exists()]
    runs = [
        r for r in runs
        if (name is None or r.manifest["name"] == name)
        and (status is None or r.manifest["status"] == status)
    ]
    return sorted(runs, key=lambda r: (r.manifest["created"], r.path.name))


def latest_run(stage: str, name: str | None = None, runs_dir: Path | None = None) -> Run | None:
    runs = list_runs(stage, name=name, runs_dir=runs_dir)
    return runs[-1] if runs else None
