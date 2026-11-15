"""Ligne de commande : ``pixplot <commande>``.

    pixplot doctor                         vérifier Python, PyTorch, GPU
    pixplot ingest DOSSIER [DOSSIER...]    cataloguer les images, vignettes, doublons
    pixplot embed --limit 1000             calculer les vecteurs (DINOv3 par défaut)
    pixplot similar ID_OU_CHEMIN --html    voir les œuvres les plus proches
    pixplot status                         état du catalogue et des runs
"""

from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

from .config import get_settings
from .runs import Run, latest_run, list_runs

STAGES = ("features", "index", "analysis", "export")

TODO = {
    "index": "Étape 2 — index FAISS",
    "analyze": "Étape 3 — e-means + UMAP",
    "serve": "Étape 4 — API + interface",
}


def _progress(label: str):
    try:
        from tqdm import tqdm
    except ImportError:  # pragma: no cover
        return None
    bar = {"t": None}

    def update(done: int, total: int) -> None:
        if bar["t"] is None:
            bar["t"] = tqdm(total=total, desc=label, unit="img", initial=0)
        bar["t"].n = done
        bar["t"].refresh()
        if done >= total:
            bar["t"].close()

    return update


# --------------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    import platform

    import numpy
    import PIL

    print(f"Python      {platform.python_version()} ({platform.system()} {platform.release()})")
    print(f"NumPy       {numpy.__version__}")
    print(f"Pillow      {PIL.__version__}")
    try:
        import torch
    except ImportError:
        print("PyTorch     non installé → voir docs/INSTALL_GPU.md")
        return 1
    print(f"PyTorch     {torch.__version__}  (ROCm/HIP : {torch.version.hip or 'non'})")
    if not torch.cuda.is_available():
        print("GPU         NON DISPONIBLE pour PyTorch")
        return 1
    print(f"GPU         {torch.cuda.get_device_name(0)}")
    x = torch.randn(2048, 2048, device="cuda")
    print(f"Calcul GPU  ok ({float((x @ x).mean()):.4f})")
    try:
        import faiss
        print(f"FAISS       {faiss.__version__}")
    except ImportError:
        print("FAISS       non installé (nécessaire à l'étape 2)")
    return 0


# --------------------------------------------------------------------------- ingest
def cmd_ingest(args) -> int:
    from .catalog import db
    from .catalog.ingest import ingest

    s = get_settings(args.data)
    report = ingest(args.paths, s.catalog_path, s.thumbs_dir, workers=args.workers,
                    limit=args.limit, progress=_progress("Ingestion"))
    print(f"\nImages trouvées : {report.discovered}  ·  nouvelles : {report.new}  ·  traitées : {report.processed}")
    print(f"  ok : {report.ok}  ·  doublons exacts : {report.duplicates}  ·  erreurs : {len(report.errors)}")
    for path, err in report.errors[:10]:
        print(f"  ! {path} — {err}")
    if len(report.errors) > 10:
        print(f"  ... et {len(report.errors) - 10} autres (statut 'error' dans le catalogue)")
    with db.connect(s.catalog_path) as conn:
        print(f"Catalogue : {db.counts(conn)}  →  {s.catalog_path}")
    return 0


# --------------------------------------------------------------------------- embed
def cmd_embed(args) -> int:
    from .encoders.registry import get_encoder
    from .features.extract import extract

    s = get_settings(args.data)
    kwargs = {}
    if args.encoder.startswith("dinov3_"):
        kwargs = {"weights": args.weights, "repo": args.repo, "hf_model": args.hf_model,
                  "input_size": args.input_size}
    encoder = get_encoder(args.encoder, **kwargs)
    print(f"Encodeur : {encoder.describe()}")
    run = extract(encoder, s.catalog_path, s.runs_dir, limit=args.limit, batch_size=args.batch_size,
                  workers=args.workers, resume=not args.no_resume, progress=_progress("Extraction"))
    out = run.manifest.get("outputs", {})
    print(f"\nRun : {run.id}")
    for key in ("count", "ok", "failed", "images_per_second", "device", "vram_peak_mib"):
        if key in out:
            print(f"  {key:<18} {out[key]}")
    return 0


# --------------------------------------------------------------------------- similar
def _resolve_run(s, run_name: str | None, encoder: str | None) -> Run:
    if run_name:
        return Run.load(s.runs_dir / "features" / run_name)
    run = latest_run("features", name=encoder, runs_dir=s.runs_dir)
    if run is None:
        raise SystemExit("Aucun run de vecteurs terminé : lancez d'abord `pixplot embed`.")
    return run


def cmd_similar(args) -> int:
    from .catalog import db
    from .catalog.ingest import thumb_path
    from .features.store import FeatureStore

    s = get_settings(args.data)
    conn = db.connect(s.catalog_path)
    if args.query.isdigit():
        artwork_id = int(args.query)
    else:
        row = db.find_by_path(conn, args.query)
        if row is None:
            raise SystemExit(f"Image absente du catalogue : {args.query}")
        artwork_id = row["id"]

    store = FeatureStore.open(_resolve_run(s, args.run, args.encoder))
    results = store.similar(artwork_id, k=args.k)
    rows = db.get_artworks(conn, [artwork_id] + [i for i, _ in results])

    print(f"Run : {store.run.id}")
    print(f"Requête  #{artwork_id}  {rows[artwork_id]['path']}")
    for rank, (i, score) in enumerate(results, 1):
        print(f"{rank:>3}. #{i:<8} {score:.4f}  {rows[i]['path']}")

    if args.html:
        def card(i, label):
            src = thumb_path(s.thumbs_dir, i, 256).resolve().as_uri()
            return (f'<figure><img src="{src}" loading="lazy"><figcaption>{html.escape(label)}<br>'
                    f'<small>{html.escape(Path(rows[i]["path"]).name)}</small></figcaption></figure>')

        cards = [card(artwork_id, f"Requête #{artwork_id}")]
        cards += [card(i, f"{r}. #{i} — {sc:.3f}") for r, (i, sc) in enumerate(results, 1)]
        page = f"""<!doctype html><meta charset="utf-8"><title>PixPlot — #{artwork_id}</title>
<style>
body{{font:14px system-ui,sans-serif;background:#111;color:#ddd;margin:16px}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}}
figure{{margin:0;background:#1c1c1c;padding:8px;border-radius:6px}}
figure:first-child{{outline:2px solid #e0b040}}
img{{width:100%;height:200px;object-fit:contain;background:#000}}
small{{color:#888;word-break:break-all}}
</style>
<h1>Œuvres proches de #{artwork_id}</h1><p>Run : {html.escape(store.run.id)}</p>
<main>{''.join(cards)}</main>"""
        out = Path(args.html)
        out.write_text(page, encoding="utf-8")
        print(f"\nPlanche : {out.resolve()}")
    return 0


# --------------------------------------------------------------------------- status
def cmd_status(args) -> int:
    from .catalog import db

    s = get_settings(args.data)
    print(f"Données : {s.data_dir}")
    if s.catalog_path.exists():
        with db.connect(s.catalog_path) as conn:
            print(f"Catalogue : {db.counts(conn)}")
    else:
        print("Catalogue : vide (lancez `pixplot ingest`)")
    found = False
    for stage in STAGES:
        for run in list_runs(stage, status=None, runs_dir=s.runs_dir):
            found = True
            m = run.manifest
            print(f"  {run.id:<55} {m['status']:<9} {m['created']}")
    if not found:
        print("Aucun run.")
    return 0


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pixplot", description="PixPlot v2")
    parser.add_argument("--data", help="dossier de données (sinon PIXPLOT_DATA ou ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="vérifier l'installation et le GPU").set_defaults(func=cmd_doctor)

    p = sub.add_parser("ingest", help="cataloguer des dossiers d'images")
    p.add_argument("paths", nargs="+")
    p.add_argument("--workers", type=int, default=None, help="processus parallèles (défaut : CPU - 1)")
    p.add_argument("--limit", type=int, default=None, help="ne traiter que N images en attente")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("embed", help="calculer les vecteurs des œuvres")
    p.add_argument("--encoder", default="dinov3_vitb16",
                   help="dinov3_vitb16 (défaut), dinov3_vitl16, dinov3_vits16, colorhist (test sans GPU)")
    p.add_argument("--hf-model", default=None,
                   help="modèle Hugging Face (défaut : facebook/dinov3-…-pretrain-lvd1689m)")
    p.add_argument("--weights", default=None,
                   help="secours : fichier .pth au format Meta (avec --repo) au lieu de Hugging Face")
    p.add_argument("--repo", default="vendor/dinov3", help="dépôt DINOv3 cloné (avec --weights)")
    p.add_argument("--input-size", type=int, default=448, help="résolution (multiple de 16)")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--batch-size", type=int, default=16)
    p.add_argument("--workers", type=int, default=4, help="threads de chargement des images")
    p.add_argument("--no-resume", action="store_true", help="ne pas reprendre un run interrompu")
    p.set_defaults(func=cmd_embed)

    p = sub.add_parser("similar", help="œuvres les plus proches d'une œuvre")
    p.add_argument("query", help="identifiant catalogue ou chemin de l'image")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--run", help="nom du dossier de run (défaut : le plus récent)")
    p.add_argument("--encoder", help="restreindre au dernier run de cet encodeur")
    p.add_argument("--html", help="écrire une planche HTML de comparaison")
    p.set_defaults(func=cmd_similar)

    sub.add_parser("status", help="état du catalogue et des runs").set_defaults(func=cmd_status)
    sub.add_parser("runs", help="alias de status").set_defaults(func=cmd_status)

    for name, desc in TODO.items():
        sub.add_parser(name, help=f"(à venir) {desc}").set_defaults(func=None, todo=desc)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # accents corrects dans toutes les consoles
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    if args.func is None:
        print(f"Pas encore implémenté : {args.todo}", file=sys.stderr)
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
