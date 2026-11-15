"""Chemins et réglages globaux.

Le dossier de données vient de la variable d'environnement ``PIXPLOT_DATA``,
sinon ``./data`` dans le dossier courant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog.sqlite"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"


def get_settings(data_dir: str | os.PathLike | None = None) -> Settings:
    if data_dir is None:
        data_dir = os.environ.get("PIXPLOT_DATA") or Path.cwd() / "data"
    return Settings(data_dir=Path(data_dir).expanduser().resolve())
