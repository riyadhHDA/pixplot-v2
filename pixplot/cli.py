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

TODO: dict[str, str] = {}


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
    if args.encoder.startswith(("dinov3_", "dinov2_", "siglip2_", "depth_anything_", "pe_core_", "csd_", "vitpose_")):
        kwargs = {"weights": args.weights, "repo": args.repo, "hf_model": args.hf_model,
                  "input_size": args.input_size}
    elif args.encoder.startswith("sscd_"):
        kwargs = {"weights": args.weights, "cache_dir": s.data_dir / "models",
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

    from .catalog.metadata import get_metadata

    store = FeatureStore.open(_resolve_run(s, args.run, args.encoder))
    index = None
    try:
        from .index.faiss_index import GlobalIndex, find_index_for
        index_run = find_index_for(store.run, runs_dir=s.runs_dir)
        index = GlobalIndex.open(index_run) if index_run else None
    except ImportError:
        pass  # sans FAISS : recherche exacte directe sur les vecteurs
    results = store.similar(artwork_id, k=args.k, index=index)
    all_ids = [artwork_id] + [i for i, _ in results]
    rows = db.get_artworks(conn, all_ids)
    meta = get_metadata(conn, all_ids)

    def describe(i: int) -> str:
        m = meta.get(i) or {}
        bits = [m[k] for k in ("artist", "date", "genre", "style") if m.get(k)]
        return " · ".join(bits) if bits else Path(rows[i]["path"]).name

    print(f"Run : {store.run.id}")
    print(f"Requête  #{artwork_id}  {describe(artwork_id)}")
    for rank, (i, score) in enumerate(results, 1):
        print(f"{rank:>3}. #{i:<8} {score:.4f}  {describe(i)}")

    if args.html:
        import base64

        def card(i, label):
            # Vignette intégrée dans la page : la planche est autonome (aucun lien vers le disque).
            thumb = thumb_path(s.thumbs_dir, i, 256)
            src = "data:image/webp;base64," + base64.b64encode(thumb.read_bytes()).decode() if thumb.exists() else ""
            return (f'<figure><img src="{src}" loading="lazy"><figcaption>{html.escape(label)}<br>'
                    f'<small>{html.escape(describe(i))}</small></figcaption></figure>')

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


# --------------------------------------------------------------------------- metadata
def cmd_import_metadata(args) -> int:
    from .catalog.metadata import import_csv

    s = get_settings(args.data)
    rep = import_csv(Path(args.csv), s.catalog_path, source=args.source)
    print(f"Lignes : {rep.rows}  ·  œuvres trouvées : {rep.matched}  ·  absentes du catalogue : {rep.unmatched}")
    print(f"Valeurs enregistrées : {rep.values}")
    return 0


def cmd_import_iiif(args) -> int:
    from .importers.iiif import import_iiif

    out = Path(args.out)
    print(f"Import IIIF vers {out} (images de {args.max_size} px au plus, une requête à la fois)…")
    rep = import_iiif(args.urls, out, max_size=args.max_size, limit=args.limit, all_canvases=args.all_canvases,
                      delay=args.delay, progress=lambda m: print(f"  {m}", flush=True))
    print(f"\nManifestes lus : {rep.manifests}  ·  images : {rep.images}  ·  déjà présentes : {rep.skipped}"
          f"  ·  échecs : {len(rep.failed)}")
    for what, err in rep.failed[:10]:
        print(f"  échec : {what} — {err}")
    print(f"Métadonnées : {rep.csv_path}")
    print("\nÉtapes suivantes :")
    print(f"  pixplot --data {args.data or 'data'} ingest \"{out / 'images'}\"")
    print(f"  pixplot --data {args.data or 'data'} import-metadata \"{rep.csv_path}\" --source \"IIIF\"")
    print("Vérifiez les droits de réutilisation de chaque institution (colonne « rights »).")
    return 0 if rep.images or rep.skipped else 1


# --------------------------------------------------------------------------- index
def cmd_index(args) -> int:
    from .index.faiss_index import build_global_index

    s = get_settings(args.data)
    features = _resolve_run(s, args.run, args.encoder)
    if args.regions:
        from .index.regions import build_region_index

        run = build_region_index(features, runs_dir=s.runs_dir)
        out = run.manifest["outputs"]
        print(f"Index des zones : {run.id}  ({out['count']} zones de {out['artworks']} œuvres, "
              f"{run.manifest['params']['kind']}, PCA {run.manifest['params']['pca_dim']} d)")
    else:
        run = build_global_index(features, kind=args.kind, runs_dir=s.runs_dir)
        print(f"Index : {run.id}  ({run.manifest['outputs']['count']} œuvres, {args.kind})")
    print(f"Construit depuis : {features.id}")
    return 0


# --------------------------------------------------------------------------- search-text
def cmd_search_text(args) -> int:
    from .api.data import AtlasData
    from .api.search import SearchEngines

    s = get_settings(args.data)
    engines = SearchEngines(AtlasData.load(s))
    res = engines.text(args.query, k=args.k, encoder=args.encoder)
    print(f"« {args.query} »  —  {res['features']}")
    for rank, r in enumerate(res["results"], 1):
        print(f"{rank:>3}. #{r['id']:<7} {r['score']:.4f}  groupe {r['cluster']:<3} {r['label']}")
    return 0


# --------------------------------------------------------------------------- analyze
def cmd_analyze(args) -> int:
    import json
    from collections import Counter

    import numpy as np

    from .analysis.layout import analyze
    from .analysis.mapimage import render_map
    from .catalog import db
    from .catalog.metadata import get_metadata

    s = get_settings(args.data)
    features = _resolve_run(s, args.run, args.encoder)
    print(f"Vecteurs : {features.id}")
    run = analyze(features, runs_dir=s.runs_dir, n_clusters=args.clusters, use_hdbscan=args.hdbscan,
                  progress=lambda m: print(f"  {m}", flush=True))
    out = run.manifest["outputs"]
    print(f"\nAnalyse : {run.id}  ({out['count']} œuvres, {out['clusters']} groupes)")
    if args.hdbscan:
        print(f"HDBSCAN : {out['hdbscan_clusters']} groupes, {out['hdbscan_isolated']} œuvres « à part »")
        if out["hdbscan_isolated"] > 0.3 * out["count"]:
            print("  Attention : plus de 30 % d'œuvres « à part » — HDBSCAN n'est pas fiable sur un "
                  "corpus aussi dense ; préférez le score d'atypicité (find_atypical, fiche de l'Atlas).")

    # Résumé des groupes avec les métadonnées dominantes : de quoi juger s'ils ont un sens.
    ids = np.load(run.path / "ids.npy")
    labels = np.load(run.path / "clusters.npy")
    with db.connect(s.catalog_path) as conn:
        meta = get_metadata(conn, ids.tolist())
    summary = json.loads((run.path / "clusters.json").read_text(encoding="utf-8"))
    keys = [k for k in ("artist", "style", "genre", "date") if any(k in m for m in meta.values())]
    print(f"\n{'groupe':>6} {'taille':>6}  " + "  ".join(f"{k} dominant" for k in keys))
    for entry in summary[:args.show]:
        members = ids[labels == entry["cluster"]]
        cells = []
        for key in keys:
            values = [meta[int(i)].get(key) for i in members]
            values = [v for v in values if v and not v.lower().startswith("unknown")]
            if values:
                v, c = Counter(values).most_common(1)[0]
                cells.append(f"{v} ({c / len(members):.0%})")
            else:
                cells.append("—")
        print(f"{entry['cluster'] + 1:>6} {entry['size']:>6}  " + "  ".join(cells))
    if len(summary) > args.show:
        print(f"   … {len(summary) - args.show} autres groupes (--show N pour tout voir)")

    if not args.no_map:
        path = render_map(run, s.thumbs_dir, s.data_dir / "maps" / f"{run.path.name}.jpg", size=args.map_size)
        print(f"\nCarte : {path}")
    from .analysis.sprites import build_sprites
    meta = json.loads(build_sprites(run, s.thumbs_dir).read_text(encoding="utf-8"))
    print(f"Planches de vignettes pour l'Atlas : {meta['sheets']} × {meta['sheet']} px, cases de {meta['cell']} px")
    return 0


# --------------------------------------------------------------------------- pack
def cmd_pack(args) -> int:
    from .api.data import AtlasData
    from .api.search import SearchEngines
    from .export import selection as sel
    from .export.pack import build_pack

    s = get_settings(args.data)
    data = AtlasData.load(s)
    engines = SearchEngines(data)
    if args.ids:
        chosen = sel.by_ids(data, [int(x) for x in args.ids.split(",") if x.strip()])
    elif args.cluster:
        chosen = sel.by_cluster(data, args.cluster, k=args.k)
    elif args.similar:
        chosen = sel.by_similar(data, args.similar, k=args.k)
    elif args.text:
        chosen = sel.by_text(engines, args.text, k=args.k)
    elif args.detail:
        if not args.box:
            raise SystemExit("--detail demande --box x0,y0,x1,y1 (fractions de l'image)")
        chosen = sel.by_detail(engines, args.detail, [float(v) for v in args.box.split(",")], k=args.k)
    else:
        raise SystemExit("Choisissez une sélection : --ids, --cluster, --similar, --text ou --detail")
    title = args.title or chosen.how.get("méthode", "Research Pack")
    path = build_pack(data, chosen.ids, Path(args.out) if args.out else s.data_dir / "packs", title,
                      question=args.question or "", selection=chosen.how, details=chosen.details,
                      scores=chosen.scores, include_vectors=args.vectors)
    size = path.stat().st_size / 2**20
    print(f"Research Pack : {path}  ({len(chosen.ids)} œuvres, {size:.1f} Mo)")
    return 0


# --------------------------------------------------------------------------- mcp
def cmd_mcp(args) -> int:
    from .mcp.server import run

    run(get_settings(args.data), analysis_name=args.analysis)
    return 0


def cmd_antigravity_mcp(args) -> int:
    from .mcp.antigravity import run

    run()
    return 0


# --------------------------------------------------------------------------- serve
def cmd_serve(args) -> int:
    import webbrowser

    import uvicorn

    from .api.app import create_app
    from .api.data import AtlasData

    s = get_settings(args.data)
    analysis = Run.load(s.runs_dir / "analysis" / args.analysis) if args.analysis else None
    data = AtlasData.load(s, analysis)
    url = f"http://{args.host}:{args.port}/"
    print(f"Analyse : {data.analysis.id}  ({len(data.ids)} œuvres)")
    print(f"Atlas   : {url}   (Ctrl+C pour arrêter)")
    if args.host not in ("127.0.0.1", "localhost"):
        print("Attention : le serveur est accessible depuis le réseau, images comprises.")
    if args.open:
        webbrowser.open(url)
    local = args.host in ("127.0.0.1", "localhost", "::1")
    uvicorn.run(create_app(data, local_only=local), host=args.host, port=args.port, log_level="warning")
    return 0


# --------------------------------------------------------------------------- noms
def _analysis_arg(s, name: str | None) -> Run:
    if name:
        return Run.load(s.runs_dir / "analysis" / name)
    run = latest_run("analysis", runs_dir=s.runs_dir)
    if run is None:
        raise SystemExit("Aucune analyse : lancez d'abord `pixplot analyze`.")
    return run


def cmd_maps(args) -> int:
    from .analysis.spacemaps import compute_space_maps

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    if args.localmap:
        from .analysis.spacemaps import compute_localmap

        print(f"Analyse : {analysis.id} — carte d'essai LocalMAP (regard de l'analyse)")
        print(f"Carte : {compute_localmap(analysis, s, force=args.force, say=lambda m: print(m, flush=True))}")
        return 0
    print(f"Analyse : {analysis.id} — une carte UMAP par regard")
    done = compute_space_maps(analysis, s, spaces=args.spaces.split(",") if args.spaces else None,
                              force=args.force, say=lambda m: print(m, flush=True))
    print(f"Cartes : {', '.join(done) or 'aucune (calculez d’abord d’autres espaces avec pixplot embed)'}")
    return 0


def cmd_communities(args) -> int:
    import numpy as np

    from .analysis import communities as C
    from .analysis.pairbench import load_space_matrix
    from .api.data import AtlasData

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    data = AtlasData.load(s, analysis)
    ids = [int(i) for i in data.ids]
    n_groups = args.groups or int(data.clusters.max()) + 1
    n_families = args.families or max(4, round(n_groups / 6))
    keys = args.spaces.split(",") if args.spaces else list(data.spaces.runs)
    print(f"Analyse : {analysis.id} — groupes Leiden (≈ {n_groups} groupes, ≈ {n_families} familles)")
    for key in keys:
        if key in C.available(analysis) and not args.force:
            print(f"« {key} » : déjà calculé (--force pour recalculer)")
            continue
        print(f"Regard « {key} »", flush=True)
        X, row = load_space_matrix(data.spaces, key, ids)
        present = np.array([i for i in ids if i in row], dtype=np.int64)
        c = C.compute(key, present, X, n_groups, n_families, k=args.k, seed=args.seed,
                      say=lambda m: print(m, flush=True))
        print(f"  → {C.save(analysis, c)}")
        del X
    return 0


def cmd_disagreements(args) -> int:
    from .analysis import disagreements as D
    from .analysis.pairbench import load_space_matrix
    from .api.data import AtlasData

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    data = AtlasData.load(s, analysis)
    ids = [int(i) for i in data.ids]
    keys = args.spaces.split(",") if args.spaces else list(data.spaces.runs)
    if len(keys) < 2:
        raise SystemExit("Il faut au moins deux regards : calculez-en d'autres avec `pixplot embed --encoder …`.")
    print(f"Analyse : {analysis.id} — désaccords entre {', '.join(keys)}", flush=True)
    vectors = {k: load_space_matrix(data.spaces, k, ids) for k in keys}
    res = D.compute(vectors, ids, k=args.k, max_rank=args.rank, max_centile=args.centile,
                    keep=args.keep, say=lambda m: print(m, flush=True))
    print(f"Désaccords : {D.save(analysis, res)}")
    return 0


def cmd_doublons(args) -> int:
    from .analysis import duplicates as DU
    from .api.data import AtlasData

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    run = DU.find_sscd_run(s.runs_dir)
    if run is None:
        raise SystemExit("Pas de vecteurs SSCD : lancez d'abord `pixplot embed --encoder sscd_disc_large`.")
    data = AtlasData.load(s, analysis)
    print(f"Analyse : {analysis.id} — doublons et variantes selon {run.id}", flush=True)
    res = DU.compute(data.ids, run, data.meta, k=args.k, same=args.same, variant=args.variant,
                     say=lambda m: print(m, flush=True))
    print(f"Doublons : {DU.save(analysis, res)}")
    return 0


def cmd_ordre(args) -> int:
    from .analysis import order as O
    from .api.data import AtlasData

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    print(f"Analyse : {analysis.id} — ordre et désordre (entropie et complexité, Sigaki et al. 2018)", flush=True)
    path = O.compute(analysis, s, workers=args.workers, say=lambda m: print(m, flush=True))
    hc = O.load(analysis)
    data = AtlasData.load(s, analysis)
    for key in ("style", "genre"):
        if key not in data.category_keys():
            continue
        rows = O.by_label([data.meta.get(int(i), {}).get(key) or "" for i in data.ids], hc)
        print(f"\n{key} (médianes, du plus ordonné au plus désordonné) :")
        for r in rows:
            print(f"  {r['value'][:30]:<30} H {r['H']:.3f}  C {r['C']:.3f}  ({r['n']} œuvres)")
    print(f"\nOrdre : {path}")
    return 0


def cmd_wikiart_noms(args) -> int:
    """Rattache nos œuvres WikiArt à leur nom de fichier d'origine (images de MMArt), puis importe
    titres, dates (MMArt) et émotions (ArtEmis)."""
    import time

    from .catalog import db
    from .catalog import wikiart_names as W

    s = get_settings(args.data)
    conn = db.connect(s.catalog_path)
    out_csv = s.data_dir / "wikiart_files.csv"
    if args.mmart and (args.force or not out_csv.exists()):
        t = time.time()
        ours = W.load_ours(conn)
        print(f"Nos œuvres : {len(ours.ids)} empreintes. Lecture des images de MMArt…", flush=True)
        matches = W.match_rows(ours, W.mmart_hashes(Path(args.mmart) / "data", workers=args.workers,
                                                    say=lambda m: print(m, flush=True)),
                               say=lambda m: print(m, flush=True))
        W.write_csv(matches, out_csv)
        print(f"Correspondances : {out_csv} ({time.time() - t:.0f} s)")
    if args.mmart and out_csv.exists():
        import csv

        matches = [{**r, "id": int(r["id"])} for r in csv.DictReader(out_csv.open(encoding="utf-8"))]
        r = W.import_mmart(conn, matches, Path(args.mmart) / "data" / "data.parquet")
        print(f"MMArt : titres et noms de fichier pour {r['artworks']} œuvres, dates pour {r['dated']}")
    if args.artistes:
        r = W.import_artists(conn)
        print(f"Artistes : {r['filled']} œuvres « Unknown Artist » complétées par le nom de fichier ; "
              f"{r['disagree']} étiquettes connues différentes du nom de fichier (laissées telles quelles)")
    if args.artemis:
        r = W.import_artemis(conn, s.data_dir, W.artemis_by_file(Path(args.artemis)))
        print(f"ArtEmis : réactions pour {r['artworks']} œuvres, émotion dominante nette pour {r['labelled']}")
    conn.close()
    return 0


def cmd_import_places(args) -> int:
    from .catalog import db
    from .catalog.places import import_places_csv

    s = get_settings(args.data)
    conn = db.connect(s.catalog_path)
    r = import_places_csv(conn, Path(args.file), source=args.source or Path(args.file).name)
    conn.close()
    print(f"{r['added']} lieux importés ; {r['unmatched']} lignes sans œuvre correspondante ; "
          f"{r['no_coords']} lieux sans coordonnées (ajoutez lat/lon ou un nom de ville connu).")
    return 0


def cmd_places(args) -> int:
    from collections import Counter

    from .catalog import db
    from .catalog.metadata import get_metadata
    from .catalog.places import PLACE_TYPES, derive_from_metadata, load_places

    s = get_settings(args.data)
    conn = db.connect(s.catalog_path)
    if args.derive:
        ids = [r[0] for r in conn.execute("SELECT id FROM artworks WHERE status = 'ok'")]
        counts = derive_from_metadata(conn, get_metadata(conn, ids))
        print("Lieux déduits des métadonnées : " + (", ".join(f"{PLACE_TYPES[t][0].lower()} {n}" for t, n in counts.items()) or "aucun"))
    rows = load_places(conn)
    conn.close()
    by_type = Counter(r["type"] for r in rows)
    print(f"{len(rows)} lieux pour {len({r['artwork_id'] for r in rows})} œuvres")
    for t, n in by_type.most_common():
        located = sum(1 for r in rows if r["type"] == t and r["lat"] is not None)
        dated = sum(1 for r in rows if r["type"] == t and r["year"] is not None)
        print(f"  {PLACE_TYPES[t][0]:<26} {n:>6}   situés {located:>6}   datés {dated:>6}")
    return 0


def cmd_zones(args) -> int:
    from .encoders.registry import get_encoder
    from .index.textzones import build_zone_index, extract_zones, find_zone_run

    import time

    s = get_settings(args.data)
    log = Path(s.data_dir) / "zones.log"

    def say(m):
        print(m, flush=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {m}\n")

    if not args.index_only:
        runs = [r for r in list_runs("features", runs_dir=s.runs_dir)
                if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")
                and r.manifest.get("status") == "complete" and not r.manifest["params"].get("limit")]
        if not runs:
            raise SystemExit("Pas de vecteurs SigLIP 2 : lancez d'abord `pixplot embed --encoder siglip2_so400m`.")
        text_run = runs[-1]
        p = text_run.manifest["params"]
        say(f"Zones SigLIP 2 d'après {text_run.id} (grilles 2×2 et 4×4 : 20 zones par œuvre)")
        enc = get_encoder(p["encoder"], hf_model=p.get("weights"), input_size=p.get("input_size"))
        zone_run = extract_zones(s, text_run, enc, batch_images=args.batch, workers=args.workers,
                                 limit=args.limit, say=say)
        del enc
    else:
        zone_run = find_zone_run(s.runs_dir, complete_only=True)
        if zone_run is None:
            raise SystemExit("Aucune extraction de zones terminée.")
    build_zone_index(zone_run, runs_dir=s.runs_dir, say=say)
    say("Terminé : la recherche « zone par des mots » est disponible dans l'Atlas (mode Description → Zones).")
    return 0


def cmd_corpus(args) -> int:
    from .api.data import AtlasData

    s = get_settings(args.data)
    data = AtlasData.load(s, _analysis_arg(s, args.analysis))
    r = data.corpus_report()
    print(f"Corpus : {r['n']} œuvres ({data.analysis.id})\n")
    print("Ce qui manque ou déséquilibre le corpus :")
    for n in r["notes"]:
        print(f"  - {n}")
    print("\nÉtiquettes : couverture et source")
    for k, c in r["coverage"].items():
        src = c["sources"][0]["source"] if c["sources"] else "?"
        print(f"  {k:<10} {c['share']:>6.0%}  {c['distinct']:>6} valeurs  source : {src}")
        if c["sources"] and c["sources"][0]["note"]:
            print(f"             {c['sources'][0]['note']}")
    print("\nRegards : ce que chacun voit, et ses biais")
    for sp in data.spaces.list():
        cd = sp["card"]
        print(f"\n  {sp['label']} — {cd['model']}")
        print(f"    entraîné sur : {cd['trained_on']}")
        print(f"    voit : {cd['sees']} · ne voit pas : {cd['blind_to']}")
        for b in cd["biases"]:
            print(f"    biais : {b}")
        print(f"    mesuré : {cd['measured']}")
    return 0


def cmd_zonebench(args) -> int:
    import json

    from .analysis import zonebench as Z
    from .encoders.registry import get_encoder

    root = Path(args.richart)
    if not (root / "annotations" / "test.json").exists():
        raise SystemExit(f"RichArt introuvable dans {root} (annotations/test.json et data/test/). "
                         "Voir docs : jeu de données MihaiBogdanBindila/RichArt, CC BY-NC 4.0, usage local.")
    results = {}
    for name in args.encoders.split(","):
        print(f"Encodeur {name}…", flush=True)
        enc = get_encoder(name)
        is_text_image = name.startswith("siglip2")
        res = Z.run(root, siglip=enc if is_text_image else None, tips=None if is_text_image else enc,
                    dense_size=args.size, say=lambda m: print(m, flush=True))
        for k, v in res["methods"].items():
            results[k if is_text_image else k.replace("tipsv2", name)] = v
        del enc
    print(f"\n{'méthode':<26} {'requête':<7} {'R@1':>6} {'R@5':>6} {'R@10':>6} {'rang méd.':>9} {'pointage':>9} {'hasard':>7}")
    for m, d in results.items():
        for q, v in d.items():
            pt = v.get("pointing")
            print(f"{m:<26} {q:<7} {v['R@1']:>6.1%} {v['R@5']:>6.1%} {v['R@10']:>6.1%} {v['median_rank']:>9.0f}"
                  + (f" {pt['hit']:>9.1%} {pt['chance']:>7.1%}" if pt else ""))
    out = root / "zonebench.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nRésultats : {out}")
    return 0


def cmd_name_groups(args) -> int:
    import json

    from .analysis.naming import name_groups

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    path = name_groups(analysis, s)
    data = json.loads(path.read_text(encoding="utf-8"))
    print(f"Analyse : {analysis.id}")
    print(f"Méthode : {data['method']}\n")
    for g in data["groups"][:args.show]:
        meta = f"   [{g['metadata_name']}]" if g.get("metadata_name") else ""
        print(f"  {g['cluster'] + 1:>4}  {g['name']}{meta}")
    if len(data["groups"]) > args.show:
        print(f"  … {len(data['groups']) - args.show} autres (--show N)")
    print(f"\nNoms : {path}")
    return 0


def cmd_composition(args) -> int:
    """Banc d'essai « composition » (étape 0.15) : regards existants, PE-Spatial, dispositions 4 × 4."""
    import json
    from pathlib import Path

    from .analysis.composition import score_layout
    from .analysis.pairbench import TYPES, load_pairs, load_space_matrix, pairs_path, score_pairs
    from .api.data import AtlasData

    s = get_settings(args.data)
    pairs = [p for p in load_pairs(pairs_path(s)) if p.origin == "annotée"]
    if not pairs:
        raise SystemExit("Aucune paire annotée : voir `pixplot pairs`.")
    from .api.spaces import Spaces

    prev_not_kept = Spaces.include_not_kept
    Spaces.include_not_kept = True        # le banc d'essai mesure aussi les modèles non retenus
    try:
        data = AtlasData.load(s, _analysis_arg(s, args.analysis))
        _ = data.spaces
    finally:
        Spaces.include_not_kept = prev_not_kept
    ids = [int(i) for i in data.ids]
    results = []
    for key in data.spaces.runs:
        print(f"Regard « {key} »…", flush=True)
        X, row = load_space_matrix(data.spaces, key, ids)
        results += score_pairs(pairs, {key: (X, row)})[0]
        del X
    for key, run in data.spaces.runs.items():
        if (Path(run.path) / "regions.npy").exists() and key in ("forme", "composition"):
            for kind, name in (("layout", f"{key}_4x4"), ("layout_communes", f"{key}_4x4c"),
                               ("global_masque", f"{key}_masq")):
                print(f"Variante « {name} »…", flush=True)
                results += score_layout(name, Path(run.path), pairs, ids, kind)
        if (Path(run.path) / "poses_vecs.npy").exists() and key == "posture":
            from .encoders.posture import score_posture_run
            print("Variante « posture_multi »…", flush=True)
            results += score_posture_run("posture_multi", Path(run.path), pairs, ids, allow_mirror=True)
    order = ["forme", "forme_masq", "forme_4x4", "forme_4x4c", "composition", "composition_masq",
             "composition_4x4", "composition_4x4c", "profondeur", "posture", "posture_multi",
             "sujet", "couleur", "touche", "copie"]
    print(f"\nBanc d'essai « composition » · {len(ids)} œuvres · paires validées par l'utilisateur")
    print("centile : part du corpus plus éloignée que l'œuvre jumelle (0,5 = hasard, 1 = la plus proche)")
    print(f"{'type':<44} {'regard':<16} {'n':>4} {'R@10':>6} {'R@100':>6} {'rang méd.':>9} {'centile':>8}")
    for t in TYPES:
        rows = sorted((r for r in results if r.type == t),
                      key=lambda r: order.index(r.space) if r.space in order else 99)
        if not rows:
            continue
        best = max(rows, key=lambda r: r.centile).space
        for r in rows:
            print(f"{TYPES[t][0][:44]:<44} {r.space:<16} {r.n:>4} {r.r10:>6.1%} {r.r100:>6.1%} "
                  f"{r.median_rank:>9.0f} {r.centile:>8.3f}{' ◀' if r.space == best else ''}")
    out = pairs_path(s).parent / f"composition_report_{Path(data.analysis.path).name}.json"
    out.write_text(json.dumps({"analysis": data.analysis.id, "n_artworks": len(ids),
                               "results": [r.__dict__ for r in results]}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"\nRapport : {out}")

def cmd_iconclass(args) -> int:
    import json

    from .analysis import iconclass

    s = get_settings(args.data)
    if args.fetch:
        d = iconclass.fetch(iconclass.icon_dir(s))
        print(f"Iconclass (CC0) dans {d}")
    if args.fetch_only:
        return 0
    analysis = _analysis_arg(s, args.analysis)
    path = iconclass.name_groups(analysis, s)
    data = json.loads(path.read_text(encoding="utf-8"))
    names = {}
    try:
        from .analysis.naming import load_names
        names = load_names(analysis)
    except Exception:
        pass
    print(f"Analyse : {analysis.id}")
    print(f"Méthode : {data['method']}")
    print()
    for g in data["groups"][:args.show]:
        cur = names.get(g["cluster"], {}).get("name", "")
        terms = " · ".join(f"{t['notation']} {t['fr'][:40]}" for t in g["terms"])
        print(f"  {g['cluster'] + 1:>4}  {terms}")
        if cur:
            print(f"        [actuel : {cur}]")
    print()
    print(f"Noms Iconclass : {path}  ·  à vérifier sur https://iconclass.org")
    return 0


def cmd_suspects(args) -> int:
    from .analysis.suspects import load_suspects, write_suspects

    s = get_settings(args.data)
    analysis = _analysis_arg(s, args.analysis)
    write_suspects(analysis, s, args.keys.split(","), space=args.space, k=args.k)
    data = load_suspects(analysis)
    print(f"Analyse : {analysis.id}  ·  espace : {data['space']} ({data['features']})")
    print(f"Règle : {data['rule']}")
    for key, items in data["suspects"].items():
        print(f"\n{key} : {len(items)} œuvres à vérifier")
        for d in items[:args.show]:
            print(f"  n° {d['id']:>6}  « {d['value']} »  → voisines : {d['suggested']} ({d['majority']:.0%})")
    print("\nÀ regarder dans l'Atlas : menu « À vérifier ». Ce sont des pistes, pas des corrections.")
    return 0


# --------------------------------------------------------------------------- audit
def cmd_audit(args) -> int:
    from .analysis.audit import audit, write_report
    from .catalog import db

    s = get_settings(args.data)
    if args.analysis:
        analysis = Run.load(s.runs_dir / "analysis" / args.analysis)
    else:
        analysis = latest_run("analysis", runs_dir=s.runs_dir)
        if analysis is None:
            raise SystemExit("Aucune analyse : lancez d'abord `pixplot analyze`.")
    conn = db.connect(s.catalog_path)
    results = audit(analysis, conn, args.keys.split(","), k=args.k, min_count=args.min_count)
    if not results:
        raise SystemExit(f"Aucune des étiquettes {args.keys} n'est renseignée dans le catalogue.")
    out = s.data_dir / "audits" / analysis.path.name
    md, page = write_report(results, analysis, conn, s.thumbs_dir, out, k=args.k)
    print(f"Analyse : {analysis.id}\n")
    print(f"{'étiquette':<10} {'œuvres':>7} {'valeurs':>8} {'pureté':>8} {'NMI':>6} {'ARI':>6}")
    for r in results:
        print(f"{r.key:<10} {r.n:>7} {r.values:>8} {r.purity:>8.1%} {r.nmi:>6.3f} {r.ari:>6.3f}")
    for r in results:
        print(f"\n{r.key} — le moins bien retrouvé (P@{args.k}) :")
        for d in r.per_value[:5]:
            conf = ", ".join(f"{b} {s_:.0%}" for b, s_ in d["top_confusions"][:2])
            print(f"  {d['p_at_k']:>6.1%}  {d['value']:<30} (n={d['n']})  → confondu avec {conf}")
    print(f"\nRapport : {md}\nExemples d'échecs : {page}")
    return 0


# --------------------------------------------------------------------------- bench
def cmd_bench(args) -> int:
    from .analysis.bench import run_bench
    from .catalog import db

    s = get_settings(args.data)
    conn = db.connect(s.catalog_path)
    keys = args.keys.split(",")
    names = args.runs or [r.path.name for r in list_runs("features", runs_dir=s.runs_dir)]
    label_rows, pair_rows = [], []
    for name in names:
        run = Run.load(s.runs_dir / "features" / name)
        out = run.manifest.get("outputs", {})
        p = run.manifest["params"]
        tag = f"{p.get('encoder')} @{p.get('input_size')}"
        labels, pairs = run_bench(run, conn, keys, k=args.k)
        speed = out.get("images_per_second")
        label_rows += [(tag, sc, speed) for sc in labels]
        pair_rows += [(tag, sc) for sc in pairs]

    k = args.k
    print(f"\nÉtiquettes (k={k}) — P@1 : même étiquette que la première voisine étiquetée (ARCHITECTURE § 30)")
    print(f"{'configuration':<28} {'étiquette':<8} {'P@1':>6} {f'P@{k}':>6} {'hasard':>7} {'n':>6} {'img/s':>6}")
    for tag, sc, speed in label_rows:
        print(f"{tag:<28} {sc.key:<8} {sc.p1:>6.1%} {sc.pk:>6.1%} {sc.chance:>7.1%} {sc.n:>6} {speed or '':>6}")
    if pair_rows:
        print(f"\nPaires connues : l'original est-il retrouvé ?")
        print(f"{'configuration':<28} {'variante':<16} {'R@1':>6} {f'R@{k}':>6} {'n':>5}")
        for tag, sc in pair_rows:
            print(f"{tag:<28} {sc.variant_type:<16} {sc.r1:>6.1%} {sc.rk:>6.1%} {sc.n:>5}")
    return 0


# --------------------------------------------------------------------------- paires
def cmd_pairs(args) -> int:
    import json
    from pathlib import Path

    from .analysis.pairbench import (TYPES, Pair, add_pair, load_pairs, load_space_matrix,
                                     metadata_pairs, pairs_path, save_pairs, score_pairs)

    s = get_settings(args.data)
    path = pairs_path(s)
    if args.action == "types":
        for key, (label, expected, question) in TYPES.items():
            print(f"{key:<17} {label}  (regard attendu : {expected or '—'})\n{'':<17} {question}")
        return 0
    if args.action == "add":
        if len(args.ids) != 2 or not args.type:
            raise SystemExit("Usage : pixplot pairs add A B --type TYPE [--source …] [--note …]")
        p = add_pair(path, Pair(args.ids[0], args.ids[1], args.type, "annotée", args.status,
                                args.source or "", args.note or ""))
        print(f"Paire enregistrée : {p.a} ↔ {p.b} ({TYPES[p.type][0]}, {p.status}) → {path}")
        return 0
    if args.action == "list":
        pairs = load_pairs(path)
        counts: dict = {}
        for p in pairs:
            counts[(p.type, p.origin, p.status)] = counts.get((p.type, p.origin, p.status), 0) + 1
        for (t, o, st), n in sorted(counts.items()):
            print(f"{TYPES.get(t, (t,))[0]:<48} {o:<12} {st:<9} {n:>5}")
        print(f"{len(pairs)} paires · {path}")
        return 0

    from .api.data import AtlasData
    from .api.spaces import Spaces

    data = AtlasData.load(s, _analysis_arg(s, args.analysis))
    if args.action == "bench" and args.spaces:
        prev_not_kept = Spaces.include_not_kept
        Spaces.include_not_kept = True
        try:
            _ = data.spaces
        finally:
            Spaces.include_not_kept = prev_not_kept
    ids = [int(i) for i in data.ids]
    if args.action == "generate":
        from .catalog import db
        from .catalog.metadata import get_metadata

        conn = db.connect(s.catalog_path)
        meta = get_metadata(conn, ids)
        conn.close()
        kept = [p for p in load_pairs(path) if p.origin != "métadonnées"]
        new = metadata_pairs(meta, n=args.n, seed=args.seed)
        save_pairs(path, kept + new)
        print(f"{len(new)} paires tirées des métadonnées (graine {args.seed}) ; "
              f"{len(kept)} paires annotées conservées → {path}")
        return 0

    # bench
    pairs = load_pairs(path)
    if not pairs:
        raise SystemExit("Aucune paire : `pixplot pairs generate` ou `pixplot pairs add`.")
    keys = args.spaces.split(",") if args.spaces else list(data.spaces.runs)
    results, detail = [], {}
    for key in keys:
        print(f"Regard « {key} » : chargement des vecteurs…", flush=True)
        X, row = load_space_matrix(data.spaces, key, ids)
        res, det = score_pairs(pairs, {key: (X, row)}, include_proposed=args.proposed)
        results += res
        for k, v in det.items():
            detail.setdefault(k, {}).update(v)
        del X
    order = {k: n for n, k in enumerate(keys)}
    print(f"\nBanc d'essai par paires · {data.analysis.id} · {len(ids)} œuvres")
    print("centile : part du corpus plus éloignée que l'œuvre jumelle (0,5 = hasard, 1 = la plus proche)")
    for origin in ("annotée", "métadonnées"):
        rows = [r for r in results if r.origin == origin]
        if not rows:
            continue
        print(f"\nPaires {'annotées' if origin == 'annotée' else 'tirées des métadonnées'}")
        print(f"{'type':<44} {'regard':<9} {'n':>5} {'R@10':>6} {'R@100':>6} {'rang méd.':>9} {'centile':>8}")
        for t in TYPES:
            sub_rows = sorted((r for r in rows if r.type == t), key=lambda r: order.get(r.space, 99))
            if not sub_rows:
                continue
            best = max(sub_rows, key=lambda r: r.centile).space
            for r in sub_rows:
                mark = " ◀" if r.space == best else ""
                print(f"{TYPES[t][0][:44]:<44} {r.space:<9} {r.n:>5} {r.r10:>6.1%} {r.r100:>6.1%} "
                      f"{r.median_rank:>9.0f} {r.centile:>8.3f}{mark}")
    out = path.parent / f"pairs_report_{Path(data.analysis.path).name}.json"
    out.write_text(json.dumps({
        "analysis": data.analysis.id, "n_artworks": len(ids), "spaces": keys,
        "results": [r.__dict__ for r in results],
        "pairs": [{"a": a, "b": b, "type": t, "ranks": v} for (a, b, t), v in detail.items()],
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nRapport : {out}")
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
    from . import __version__

    parser = argparse.ArgumentParser(prog="pixplot", description="PixPlot v2")
    parser.add_argument("--version", action="version", version=f"PixPlot v2 {__version__}")
    parser.add_argument("--data", help="dossier de données (sinon PIXPLOT_DATA ou ./data)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("doctor", help="vérifier l'installation et le GPU").set_defaults(func=cmd_doctor)

    p = sub.add_parser("ingest", help="cataloguer des dossiers d'images")
    p.add_argument("paths", nargs="+")
    p.add_argument("--workers", type=int, default=None, help="processus parallèles (défaut : CPU - 1)")
    p.add_argument("--limit", type=int, default=None, help="ne traiter que N images en attente")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("import-metadata", help="importer artiste, date, style... depuis un CSV (colonne path)")
    p.add_argument("csv")
    p.add_argument("--source", help="provenance à enregistrer (défaut : nom du fichier)")
    p.set_defaults(func=cmd_import_metadata)

    p = sub.add_parser("import-iiif", help="télécharger une collection de musée (manifeste ou collection IIIF)")
    p.add_argument("urls", nargs="+", help="adresse(s) de manifeste ou de collection IIIF (v2 ou v3)")
    p.add_argument("--out", required=True, help="dossier où écrire images/ et metadata.csv")
    p.add_argument("--max-size", type=int, default=1600, help="plus grand côté des images (px)")
    p.add_argument("--limit", type=int, help="nombre maximal de manifestes par source")
    p.add_argument("--all-canvases", action="store_true", help="toutes les vues de chaque manifeste (défaut : la première)")
    p.add_argument("--delay", type=float, default=0.3, help="pause entre deux téléchargements (s)")
    p.set_defaults(func=cmd_import_iiif)

    p = sub.add_parser("embed", help="calculer les vecteurs des œuvres")
    p.add_argument("--encoder", default="dinov3_vitb16",
                   help="dinov3_vitb16 (défaut), dinov3_vitl16, dinov2_vitb14_reg (sans demande d accès), colorhist (test sans GPU)")
    p.add_argument("--hf-model", default=None,
                   help="modèle Hugging Face (défaut : facebook/dinov3-…-pretrain-lvd1689m)")
    p.add_argument("--weights", default=None,
                   help="secours : fichier .pth au format Meta (avec --repo) au lieu de Hugging Face")
    p.add_argument("--repo", default="vendor/dinov3", help="dépôt DINOv3 cloné (avec --weights)")
    p.add_argument("--input-size", type=int, default=448, help="résolution : multiple de 16 (DINOv3) et de 14 (DINOv2) ; 448 convient aux deux")
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

    p = sub.add_parser("index", help="construire l'index FAISS d'un run de vecteurs")
    p.add_argument("--run", help="run de vecteurs (défaut : le plus récent)")
    p.add_argument("--encoder", help="restreindre au dernier run de cet encodeur")
    p.add_argument("--kind", default="flat", choices=("flat", "hnsw"),
                   help="flat = exact (défaut, jusqu'à ~500k) ; hnsw = approché, au-delà")
    p.add_argument("--regions", action="store_true", help="index des zones, pour la recherche par détail")
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("search-text", help="chercher des œuvres par une description (SigLIP 2 ou PE-Core)")
    p.add_argument("query", help="ex. « Annonciation dans un jardin »")
    p.add_argument("-k", type=int, default=15)
    p.add_argument("--encoder", default=None, help="préfixe d'encodeur texte-image (défaut : siglip2)")
    p.set_defaults(func=cmd_search_text)

    p = sub.add_parser("analyze", help="groupes (e-means), carte (UMAP), voisinages, œuvres atypiques")
    p.add_argument("--run", help="run de vecteurs (défaut : le plus récent)")
    p.add_argument("--encoder", help="restreindre au dernier run de cet encodeur")
    p.add_argument("--clusters", type=int, default=None, help="nombre de groupes (défaut : ≈ √N / 2)")
    p.add_argument("--hdbscan", action="store_true", help="ajouter HDBSCAN pour repérer les œuvres « à part »")
    p.add_argument("--show", type=int, default=15, help="nombre de groupes résumés à l'écran")
    p.add_argument("--no-map", action="store_true", help="ne pas dessiner la carte")
    p.add_argument("--map-size", type=int, default=4000, help="taille de la carte en pixels")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("pack", help="exporter un Research Pack (.zip) pour un LLM ou un collègue")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--ids", help="liste d'œuvres : 12,45,78")
    g.add_argument("--cluster", type=int, help="numéro de groupe (comme dans l'Atlas)")
    g.add_argument("--similar", type=int, help="une œuvre et ses voisines")
    g.add_argument("--text", help="une description (SigLIP 2)")
    g.add_argument("--detail", type=int, help="une œuvre + --box : recherche par détail")
    p.add_argument("--box", help="cadre x0,y0,x1,y1 en fractions de l'image (avec --detail)")
    p.add_argument("-k", type=int, default=30, help="nombre d'œuvres retenues")
    p.add_argument("--title")
    p.add_argument("--question", help="la question de recherche, reprise dans le dossier")
    p.add_argument("--vectors", action="store_true", help="ajouter les vecteurs (option experte)")
    p.add_argument("--out", help="dossier de sortie (défaut : data/packs)")
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser("mcp", help="serveur MCP (stdio) : donne accès au corpus à Claude ou un autre LLM")
    p.add_argument("--analysis", help="dossier d'analyse (défaut : la plus récente)")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("antigravity-mcp", help="serveur MCP : second avis d'Antigravity (Google), en lecture seule")
    p.set_defaults(func=cmd_antigravity_mcp)

    p = sub.add_parser("serve", help="ouvrir l'Atlas (carte interactive) dans le navigateur")
    p.add_argument("--analysis", help="dossier d'analyse (défaut : la plus récente)")
    p.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = accessible seulement depuis ce PC")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="ouvrir le navigateur automatiquement")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("maps", help="une carte UMAP par regard (sujet, couleur, touche)")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--spaces", help="espaces à calculer, séparés par des virgules (défaut : tous)")
    p.add_argument("--force", action="store_true", help="recalculer les cartes existantes")
    p.add_argument("--localmap", action="store_true",
                   help="carte d'essai LocalMAP du regard principal (paquet pacmap ; pas mieux qu'UMAP, ARCHITECTURE)")
    p.set_defaults(func=cmd_maps)

    p = sub.add_parser("wikiart-noms", help="titres, dates (MMArt) et émotions (ArtEmis) pour WikiArt, par empreinte d'image")
    p.add_argument("--mmart", help="dossier du jeu MMArt téléchargé (huggingface.co/datasets/Shuaimyself/MMArt)")
    p.add_argument("--artemis", help="fichier artemis_dataset_release_v0.csv")
    p.add_argument("--artistes", action="store_true",
                   help="compléter les « Unknown Artist » par l'artiste lu dans le nom de fichier retrouvé")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--force", action="store_true", help="refaire le rattachement des images")
    p.set_defaults(func=cmd_wikiart_noms)

    p = sub.add_parser("ordre", help="entropie et complexité de la matière (Sigaki et al., PNAS 2018), sans GPU")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--workers", type=int, default=8, help="fils de lecture des vignettes")
    p.set_defaults(func=cmd_ordre)

    p = sub.add_parser("doublons", help="œuvres entrées deux fois, répliques et variantes (vecteurs SSCD)")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("-k", type=int, default=5, help="voisines examinées par œuvre")
    p.add_argument("--same", type=float, default=0.85, help="cosinus à partir duquel c'est la même image")
    p.add_argument("--variant", type=float, default=0.65, help="cosinus à partir duquel c'est une variante")
    p.set_defaults(func=cmd_doublons)

    p = sub.add_parser("communities", help="groupes Leiden emboîtés (familles ⊃ groupes), un jeu par regard")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--spaces", help="regards à calculer, séparés par des virgules (défaut : tous)")
    p.add_argument("--groups", type=int, help="nombre de groupes visé (défaut : celui d'e-means)")
    p.add_argument("--families", type=int, help="nombre de familles visé (défaut : groupes / 6)")
    p.add_argument("-k", type=int, default=15, help="voisines par œuvre dans le graphe")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--force", action="store_true", help="recalculer")
    p.set_defaults(func=cmd_communities)

    p = sub.add_parser("disagreements", help="paires qu'un regard rapproche et qu'un autre sépare")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--spaces", help="regards à confronter, séparés par des virgules (défaut : tous)")
    p.add_argument("-k", type=int, default=10, help="voisines calculées par œuvre")
    p.add_argument("--rank", type=int, default=5, help="rang maximal dans le regard qui rapproche")
    p.add_argument("--centile", type=float, default=0.35, help="centile maximal dans le regard qui sépare")
    p.add_argument("--keep", type=int, default=300, help="paires gardées par couple de regards")
    p.set_defaults(func=cmd_disagreements)

    p = sub.add_parser("zones", help="chercher une zone avec des mots : 20 zones par œuvre vues par SigLIP 2, puis index")
    p.add_argument("--limit", type=int, help="seulement les N premières œuvres (essai)")
    p.add_argument("--batch", type=int, default=4, help="œuvres par lot GPU (× 20 zones)")
    p.add_argument("--workers", type=int, default=4, help="fils de lecture et découpage des images")
    p.add_argument("--index-only", action="store_true", help="reconstruire seulement l'index")
    p.set_defaults(func=cmd_zones)

    p = sub.add_parser("import-places", help="lieux typés et datés d'un fichier CSV (path|id, type, place, lat, lon, date, source)")
    p.add_argument("file")
    p.add_argument("--source", help="source à noter pour chaque lieu (défaut : nom du fichier)")
    p.set_defaults(func=cmd_import_places)

    p = sub.add_parser("places", help="bilan des lieux ; --derive les déduit des métadonnées (musée, naissance…)")
    p.add_argument("--derive", action="store_true", help="déduire les lieux des métadonnées déjà importées")
    p.set_defaults(func=cmd_places)

    p = sub.add_parser("corpus", help="bilan critique : ce qui manque au corpus, d'où viennent les étiquettes, ce que voit chaque regard")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser("zonebench", help="chercher une zone avec des mots : banc d'essai RichArt")
    p.add_argument("--richart", default="data/richart", help="dossier RichArt (annotations/, data/test/)")
    p.add_argument("--encoders", default="siglip2_so400m,tipsv2_b14", help="encodeurs comparés")
    p.add_argument("--size", type=int, default=672, help="taille du carré pour les vecteurs de zones (multiple de 14)")
    p.set_defaults(func=cmd_zonebench)

    p = sub.add_parser("iconclass", help="nommer les groupes avec Iconclass (classification iconographique, CC0)")
    p.add_argument("--analysis", default=None)
    p.add_argument("--fetch", action="store_true", help="télécharger les données Iconclass d'abord")
    p.add_argument("--fetch-only", action="store_true", help="seulement télécharger")
    p.add_argument("--show", type=int, default=40)
    p.set_defaults(func=cmd_iconclass)

    p = sub.add_parser("name-groups", help="proposer un nom à chaque groupe (SigLIP 2 + vocabulaire)")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--show", type=int, default=30)
    p.set_defaults(func=cmd_name_groups)

    p = sub.add_parser("suspects", help="étiquettes probablement erronées (toutes les voisines disent autre chose)")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--keys", default="artist,style,genre")
    p.add_argument("--space", help="espace de voisinage (défaut : sujet = SigLIP 2 s'il existe)")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--show", type=int, default=8)
    p.set_defaults(func=cmd_suspects)

    p = sub.add_parser("audit", help="audit à l'aveugle : où les regroupements contredisent les étiquettes")
    p.add_argument("--analysis", help="dossier d'analyse (défaut : la plus récente)")
    p.add_argument("--keys", default="artist,style,genre")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--min-count", type=int, default=10, help="ignorer les valeurs plus rares")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("bench", help="comparer des runs : étiquettes (artiste, style...) et paires connues")
    p.add_argument("runs", nargs="*", help="noms des runs de vecteurs (défaut : tous)")
    p.add_argument("-k", type=int, default=10)
    p.add_argument("--keys", default="artist,style,genre")
    p.set_defaults(func=cmd_bench)

    p = sub.add_parser("composition", help="banc d'essai « composition » : regards, PE-Spatial, dispositions 4 × 4")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.set_defaults(func=cmd_composition)

    p = sub.add_parser("pairs", help="banc d'essai par paires : quel regard retrouve quelle ressemblance")
    p.add_argument("action", choices=["types", "add", "list", "generate", "bench"])
    p.add_argument("ids", nargs="*", type=int, help="pour add : les deux numéros d'œuvre")
    p.add_argument("--type", help="type de ressemblance (voir `pixplot pairs types`)")
    p.add_argument("--status", default="validée", choices=["validée", "proposée", "rejetée"])
    p.add_argument("--source", help="référence (ex. « Honour et Fleming, p. 670 »)")
    p.add_argument("--note")
    p.add_argument("--analysis", help="nom du run d'analyse (défaut : le dernier)")
    p.add_argument("--spaces", help="regards à mesurer, séparés par des virgules (défaut : tous)")
    p.add_argument("--proposed", action="store_true", help="compter aussi les paires proposées")
    p.add_argument("-n", type=int, default=300, help="pour generate : paires par type")
    p.add_argument("--seed", type=int, default=0)
    p.set_defaults(func=cmd_pairs)

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
