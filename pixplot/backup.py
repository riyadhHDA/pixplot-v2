"""Sauvegarder ce qui ne se recalcule pas.

Presque tout ce qu'il y a dans ``<données>/`` se refait avec les commandes de PixPlot (vecteurs, index, cartes,
groupes). Le travail de l'historien, non : les paires relues à la main (``bench/pairs.csv``), les candidates
écartées (``bench/review_log.csv``) et le carnet de recherche (``notebook.sqlite``). Deux usages :

- :func:`to_repo` recopie ce travail dans le dossier ``bench/`` du dépôt (versionné par git), sous le nom du
  corpus (``<corpus>_pairs_travail.csv``, ``<corpus>_review_log.csv``, ``<corpus>_notebook.json``) ; on ne remplace jamais une copie qui contient plus de lignes que l'original, sauf demande expresse ;
- :func:`mirror` copie le dossier de données vers un autre disque : ajoute et met à jour, n'efface jamais rien ;
  les bases SQLite sont copiées par l'API de sauvegarde de SQLite (copie cohérente même si l'Atlas est ouvert).
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Travail fait à la main : (chemin dans <données>, suffixe du fichier dans bench/ du dépôt). La copie de travail
# des paires garde son propre nom : ``<corpus>_pairs.csv`` est un export relu, aux colonnes différentes.
HAND_MADE = (("bench/pairs.csv", "pairs_travail.csv"), ("bench/review_log.csv", "review_log.csv"))
NOTEBOOK = "notebook.sqlite"
# Ce qu'une copie « essentielle » emporte en plus du travail fait à la main : le catalogue (métadonnées,
# imports), les sources importées et les comptes rendus. Le reste se recalcule.
ESSENTIAL_FILES = ("catalog.sqlite", NOTEBOOK, "artemis.json", "wikiart_files.csv", "fiche_de_donnees.md")
ESSENTIAL_DIRS = ("bench",)


def _rows(path: Path) -> int:
    """Nombre de lignes de données d'un CSV (sans l'en-tête) ; 0 si absent."""
    if not path.exists():
        return 0
    with open(path, encoding="utf-8", newline="") as f:
        return max(0, sum(1 for _ in csv.reader(f)) - 1)


def _notebook_json(path: Path) -> str:
    """Le carnet en JSON lisible (une entrée par objet), trié par numéro : un fichier que git sait comparer."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM entries ORDER BY id").fetchall()
    finally:
        conn.close()
    entries = []
    for r in rows:
        e = dict(r)
        for k in ("artwork_ids", "context"):
            try:
                e[k] = json.loads(e[k])
            except (TypeError, ValueError):
                pass
        entries.append(e)
    return json.dumps(entries, ensure_ascii=False, indent=1) + "\n"


def to_repo(data_dir: Path, repo_bench: Path, corpus: str, notebook: bool = False, force: bool = False) -> list[dict]:
    """Recopie le travail fait à la main dans ``repo_bench`` (``<corpus>_pairs.csv`` …).

    Renvoie une ligne de compte rendu par fichier : copié, identique, absent, ou refusé (la copie du dépôt a plus
    de lignes que l'original : données perdues ou dossier de données neuf ? on ne l'écrase pas sans ``force``).
    """
    repo_bench.mkdir(parents=True, exist_ok=True)
    report: list[dict] = []
    for rel, suffix in HAND_MADE:
        src, dst = data_dir / rel, repo_bench / f"{corpus}_{suffix}"
        entry = {"source": str(src), "cible": str(dst), "lignes_source": _rows(src), "lignes_cible": _rows(dst)}
        if not src.exists():
            entry["état"] = "absent"
        elif dst.exists() and src.read_bytes() == dst.read_bytes():
            entry["état"] = "identique"
        elif entry["lignes_cible"] > entry["lignes_source"] and not force:
            entry["état"] = "refusé : la copie du dépôt a plus de lignes (--force pour remplacer)"
        else:
            shutil.copyfile(src, dst)
            entry["état"] = "copié"
        report.append(entry)
    if notebook:
        src, dst = data_dir / NOTEBOOK, repo_bench / f"{corpus}_notebook.json"
        entry = {"source": str(src), "cible": str(dst)}
        if not src.exists():
            entry["état"] = "absent"
        else:
            text = _notebook_json(src)
            n = len(json.loads(text))
            old = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else []
            entry.update({"lignes_source": n, "lignes_cible": len(old)})
            if dst.exists() and dst.read_text(encoding="utf-8") == text:
                entry["état"] = "identique"
            elif len(old) > n and not force:
                entry["état"] = "refusé : la copie du dépôt a plus d'entrées (--force pour remplacer)"
            else:
                dst.write_text(text, encoding="utf-8")
                entry["état"] = "copié"
        report.append(entry)
    return report


def _copy_sqlite(src: Path, dst: Path) -> None:
    """Copie cohérente d'une base SQLite, même ouverte par un autre programme."""
    tmp = dst.with_name(dst.name + ".tmp")
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(tmp)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    tmp.replace(dst)


def _wanted(data_dir: Path, everything: bool):
    """Les fichiers à copier : tout le dossier, ou l'essentiel (travail fait à la main, catalogue, sources)."""
    if everything:
        yield from (p for p in data_dir.rglob("*") if p.is_file())
        return
    for name in ESSENTIAL_FILES:
        if (data_dir / name).is_file():
            yield data_dir / name
    for d in ESSENTIAL_DIRS:
        if (data_dir / d).is_dir():
            yield from (p for p in (data_dir / d).rglob("*") if p.is_file())


def mirror(data_dir: Path, target: Path, everything: bool = False, progress=None) -> dict:
    """Copie ``data_dir`` vers ``target`` : ajoute et met à jour (taille ou date différente), n'efface jamais.

    Écrit ``target/sauvegarde.json`` (date, nombre de fichiers copiés et inchangés, octets). Refuse une cible
    située dans le dossier de données lui-même.
    """
    data_dir, target = data_dir.resolve(), target.resolve()
    if target == data_dir or data_dir in target.parents:
        raise ValueError("La copie doit aller hors du dossier de données (un autre disque, de préférence).")
    files = list(_wanted(data_dir, everything))
    copied = same = nbytes = 0
    for k, src in enumerate(files):
        rel = src.relative_to(data_dir)
        dst = target / rel
        st = src.stat()
        if dst.exists():
            dt = dst.stat()
            if dt.st_size == st.st_size and int(dt.st_mtime) >= int(st.st_mtime):
                same += 1
                if progress:
                    progress(k + 1, len(files))
                continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.suffix == ".sqlite":
            _copy_sqlite(src, dst)
        else:
            shutil.copy2(src, dst)
        copied += 1
        nbytes += st.st_size
        if progress:
            progress(k + 1, len(files))
    summary = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": str(data_dir),
               "mode": "tout" if everything else "essentiel", "fichiers": len(files), "copiés": copied,
               "inchangés": same, "octets_copiés": nbytes}
    (target / "sauvegarde.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    return summary
