"""Ligne de commande : ``pixplot <commande>``."""

from __future__ import annotations

import argparse
import sys

from .config import get_settings
from .runs import list_runs

STAGES = ("features", "index", "analysis", "export")

TODO = {
    "ingest": "Étape 1 — ingestion du corpus (catalogue, vignettes)",
    "embed": "Étape 1 — extraction DINOv3",
    "index": "Étape 2 — index FAISS",
    "analyze": "Étape 3 — e-means + UMAP",
    "serve": "Étape 4 — API + interface",
}


def cmd_runs(args: argparse.Namespace) -> int:
    settings = get_settings(args.data)
    stages = [args.stage] if args.stage else STAGES
    found = False
    for stage in stages:
        for run in list_runs(stage, status=None, runs_dir=settings.runs_dir):
            found = True
            m = run.manifest
            print(f"{run.id:<55} {m['status']:<9} {m['created']}")
    if not found:
        print(f"Aucun run dans {settings.runs_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pixplot", description="PixPlot v2")
    parser.add_argument("--data", help="dossier de données (sinon PIXPLOT_DATA ou ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("runs", help="lister les runs")
    p.add_argument("stage", nargs="?", choices=STAGES)
    p.set_defaults(func=cmd_runs)

    for name, desc in TODO.items():
        sub.add_parser(name, help=f"(à venir) {desc}").set_defaults(func=None, todo=desc)

    args = parser.parse_args(argv)
    if args.func is None:
        print(f"Pas encore implémenté : {args.todo}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
