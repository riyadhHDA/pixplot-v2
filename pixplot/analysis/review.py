"""Relecture rapide des paires, à la manière d'Anki : une paire à la fois, une touche par
décision.

La file mêle deux sources, toujours dans cet ordre :

1. les paires **proposées** (annotées mais pas encore relues) ;
2. des **candidates** tirées des désaccords entre regards (``pixplot disagreements``), en
   alternant les couples de regards pour varier les sortes de ressemblance.

Une candidate validée devient une paire annotée du type choisi ; une candidate écartée
(« pas de lien ») est notée dans ``bench/review_log.csv`` pour ne plus revenir. Rien n'est
jamais effacé sans trace : le journal garde la date de chaque décision.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from . import disagreements, pairbench

LOG_FILE = "review_log.csv"
LOG_FIELDS = ["a", "b", "decision", "origin", "time"]
# regard qui rapproche → sorte de ressemblance proposée par défaut
SUGGESTED = {"forme": "meme_composition", "sujet": "meme_sujet", "touche": "meme_facture",
             "couleur": "meme_palette"}
REVIEW_TYPES = [k for k in pairbench.TYPES if k != "temoin"]   # touches 1 à 7


def log_path(settings) -> Path:
    return Path(settings.data_dir) / "bench" / LOG_FILE


def _pair_key(a: int, b: int) -> tuple[int, int]:
    return (min(a, b), max(a, b))


def load_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def log_decision(path: Path, a: int, b: int, decision: str, origin: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"a": a, "b": b, "decision": decision, "origin": origin,
                    "time": time.strftime("%Y-%m-%d %H:%M:%S")})


def unlog(path: Path, a: int, b: int) -> None:
    """Retire la dernière décision sur cette paire (annulation)."""
    rows = load_log(path)
    for n in range(len(rows) - 1, -1, -1):
        if _pair_key(int(rows[n]["a"]), int(rows[n]["b"])) == _pair_key(a, b):
            del rows[n]
            break
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(rows)


def build_queue(analysis, settings, known_ids: set[int], limit: int = 30, exclude: set | None = None) -> list[dict]:
    pairs = pairbench.load_pairs(pairbench.pairs_path(settings))
    annotated = {_pair_key(p.a, p.b) for p in pairs if p.origin == "annotée" and p.status != "proposée"}
    logged = {_pair_key(int(r["a"]), int(r["b"])) for r in load_log(log_path(settings))}
    skip = annotated | logged | {tuple(x) for x in (exclude or set())}
    out: list[dict] = []
    for p in pairs:
        if p.origin == "annotée" and p.status == "proposée" and _pair_key(p.a, p.b) not in skip \
                and p.a in known_ids and p.b in known_ids:
            out.append({"a": p.a, "b": p.b, "origin": "proposée", "type": p.type, "source": p.source,
                        "note": p.note, "why": "paire proposée, à confirmer"})
            skip.add(_pair_key(p.a, p.b))
    d = disagreements.load(analysis)
    if d:
        lists = {k: iter(v) for k, v in d["pairs"].items()}
        while len(out) < limit and lists:
            for combo in list(lists):
                item = next(lists[combo], None)
                if item is None:
                    del lists[combo]
                    continue
                key = _pair_key(item["a"], item["b"])
                if key in skip:
                    continue
                skip.add(key)
                near, far = combo.split(">")
                out.append({"a": item["a"], "b": item["b"], "origin": "désaccord",
                            "type": SUGGESTED.get(near, "filiation"), "source": f"désaccord {near} > {far}",
                            "note": "", "near": near, "far": far, "rank": item["rank"], "centile": item["centile"],
                            "why": f"proche selon « {near} », loin selon « {far} »"})
                if len(out) >= limit:
                    break
    return out[:limit]
