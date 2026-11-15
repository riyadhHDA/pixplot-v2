"""Audit à l'aveugle : où les regroupements de la machine contredisent-ils les étiquettes ?

Les modèles ne voient jamais les métadonnées (ils ne lisent que les pixels). On compare
ensuite leurs voisinages et leurs groupes aux étiquettes connues (artiste, style…) pour
repérer précisément les échecs :

- **groupes vs étiquettes** : pureté, NMI et ARI (0 = aucun lien, 1 = identique) ;
- **par valeur d'étiquette** : quels styles / artistes sont bien retrouvés, lesquels non ;
- **confusions** : quand une œuvre de style A a pour voisines des œuvres de style B,
  quelles paires A → B reviennent le plus (au-delà de ce que leur fréquence expliquerait) ;
- **œuvres en échec** : aucune de leurs voisines ne partage leur étiquette.

Ce sont des pistes de diagnostic, pas un verdict : une « confusion » peut être une vraie
parenté visuelle (deux styles proches), ou une étiquette discutable dans la source.
"""

from __future__ import annotations

import base64
import html
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..catalog.ingest import thumb_path
from ..catalog.metadata import get_metadata
from ..runs import Run


def _valid(v: str | None) -> bool:
    return bool(v) and not v.lower().startswith("unknown")


@dataclass
class KeyAudit:
    key: str
    n: int
    values: int
    purity: float | None
    nmi: float | None
    ari: float | None
    per_value: list[dict] = field(default_factory=list)      # value, n, p_at_k, top_confusions
    confusions: list[dict] = field(default_factory=list)     # a, b, share, lift
    failures: list[dict] = field(default_factory=list)       # id, label, neighbor labels


def audit(analysis: Run, conn, keys: list[str], k: int = 10, min_count: int = 10,
          max_failures: int = 30) -> list[KeyAudit]:
    p = Path(analysis.path)
    ids = np.load(p / "ids.npy")
    clusters = np.load(p / "clusters.npy")
    neighbors = np.load(p / "neighbors.npy")[:, :k]
    nscores = np.load(p / "neighbor_scores.npy")[:, :k]
    row_of = {int(i): r for r, i in enumerate(ids)}
    meta = get_metadata(conn, ids.tolist())
    out = []

    for key in keys:
        labels = np.array([meta[int(i)].get(key) or "" for i in ids], dtype=object)
        valid = np.array([_valid(v) for v in labels])
        if valid.sum() < 2:
            continue
        counts = Counter(labels[valid])
        n_valid = int(valid.sum())
        freq = {v: c / n_valid for v, c in counts.items()}

        # --- groupes vs étiquettes
        purity = nmi = ari = None
        try:
            from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
            nmi = float(normalized_mutual_info_score(labels[valid], clusters[valid]))
            ari = float(adjusted_rand_score(labels[valid], clusters[valid]))
        except ImportError:  # pragma: no cover
            pass
        major = 0
        for c in np.unique(clusters[valid]):
            major += Counter(labels[valid & (clusters == c)]).most_common(1)[0][1]
        purity = major / n_valid

        # --- par valeur, confusions, échecs
        hits = defaultdict(list)
        conf = defaultdict(Counter)
        neigh_total = Counter()  # nombre de voisines étiquetées observées, par valeur
        failures = []
        for r in np.flatnonzero(valid):
            mine = labels[r]
            neigh = [row_of.get(int(j)) for j in neighbors[r] if j >= 0]
            neigh_labels = [labels[j] for j in neigh if j is not None and valid[j]]
            if not neigh_labels:
                continue
            same = [v == mine for v in neigh_labels]
            hits[mine].append(float(np.mean(same)))
            neigh_total[mine] += len(neigh_labels)
            for v in neigh_labels:
                if v != mine:
                    conf[mine][v] += 1
            if not any(same) and counts[mine] >= min_count:
                failures.append({"id": int(ids[r]), "label": mine,
                                 "neighbors": [int(j) for j in neighbors[r][:5] if j >= 0],
                                 "neighbor_labels": Counter(neigh_labels).most_common(3),
                                 "best_score": float(nscores[r][0])})

        per_value = []
        for v, c in counts.most_common():
            if c < min_count or not hits[v]:
                continue
            total_conf = sum(conf[v].values())
            per_value.append({
                "value": v, "n": c, "p_at_k": float(np.mean(hits[v])), "chance": freq[v],
                "top_confusions": [(b, m / max(total_conf, 1)) for b, m in conf[v].most_common(3)],
            })
        per_value.sort(key=lambda d: d["p_at_k"])

        # Confusions « anormales » : B apparaît chez A bien plus que sa fréquence ne l'explique.
        confusions = []
        for a, cb in conf.items():
            if counts[a] < min_count:
                continue
            total = neigh_total[a]
            for b, m in cb.items():
                if counts[b] < min_count:
                    continue
                share = m / max(total, 1)
                lift = share / max(freq[b], 1e-9)
                if m >= 5:
                    confusions.append({"a": a, "b": b, "count": m, "share": share, "lift": lift})
        confusions.sort(key=lambda d: (-d["share"] * min(d["lift"], 10)))

        failures.sort(key=lambda d: -counts[d["label"]])
        out.append(KeyAudit(key, n_valid, len(counts), purity, nmi, ari,
                            per_value, confusions[:20], failures[:max_failures]))
    return out


# ---------------------------------------------------------------------- rapport
def _thumb_b64(thumbs_dir: Path, artwork_id: int) -> str:
    t = thumb_path(thumbs_dir, artwork_id, 256)
    return "data:image/webp;base64," + base64.b64encode(t.read_bytes()).decode() if t.exists() else ""


def write_report(results: list[KeyAudit], analysis: Run, conn, thumbs_dir: Path, out_dir: Path,
                 k: int = 10) -> tuple[Path, Path]:
    """Écrit ``audit.md`` (chiffres) et ``audit.html`` (exemples d'échecs, avec vignettes)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    feats = analysis.manifest.get("parent", "")
    md = [f"# Audit à l'aveugle — {analysis.id}", "",
          f"Vecteurs : `{feats}`. Les modèles n'ont vu que les pixels ; les étiquettes ne servent "
          f"qu'à évaluer. Voisinage : {k} plus proches voisines.", "",
          "| étiquette | œuvres | valeurs | pureté des groupes | NMI | ARI |", "|---|---|---|---|---|---|"]
    for r in results:
        md.append(f"| {r.key} | {r.n} | {r.values} | {r.purity:.1%} | {r.nmi:.3f} | {r.ari:.3f} |")
    md += ["", "*Pureté : part des œuvres dont l'étiquette est majoritaire dans leur groupe. "
           "NMI / ARI : accord entre groupes et étiquettes (0 = aucun, 1 = parfait).*", ""]

    all_ids = {f["id"] for r in results for f in r.failures} | {n for r in results for f in r.failures for n in f["neighbors"]}
    meta = get_metadata(conn, sorted(all_ids)) if all_ids else {}

    cards_html = []
    for r in results:
        md += [f"## {r.key}", "", "### Le moins bien retrouvé", "",
               f"| {r.key} | œuvres | P@{k} | hasard | confondu surtout avec |", "|---|---|---|---|---|"]
        for d in r.per_value[:12]:
            conf = ", ".join(f"{b} ({s:.0%})" for b, s in d["top_confusions"])
            md.append(f"| {d['value']} | {d['n']} | {d['p_at_k']:.1%} | {d['chance']:.1%} | {conf} |")
        md += ["", "### Le mieux retrouvé", "", f"| {r.key} | œuvres | P@{k} | hasard |", "|---|---|---|---|"]
        for d in sorted(r.per_value, key=lambda d: -d["p_at_k"])[:8]:
            md.append(f"| {d['value']} | {d['n']} | {d['p_at_k']:.1%} | {d['chance']:.1%} |")
        md += ["", "### Confusions les plus fréquentes", "",
               "| œuvres de… | ont pour voisines des… | part des voisines | × la fréquence attendue |", "|---|---|---|---|"]
        for c in r.confusions[:12]:
            md.append(f"| {c['a']} | {c['b']} | {c['share']:.1%} | ×{c['lift']:.1f} |")
        md += ["", f"### Œuvres en échec ({len(r.failures)} montrées dans audit.html)", "",
               "Aucune de leurs voisines ne partage leur étiquette.", ""]

        cards_html.append(f"<h2>{html.escape(r.key)} — œuvres en échec</h2>")
        for f in r.failures:
            row = [f'<figure class="q"><img src="{_thumb_b64(thumbs_dir, f["id"])}"><figcaption>n° {f["id"]}<br>'
                   f'<b>{html.escape(f["label"])}</b></figcaption></figure>']
            for n in f["neighbors"]:
                lab = meta.get(n, {}).get(r.key, "")
                row.append(f'<figure><img src="{_thumb_b64(thumbs_dir, n)}"><figcaption>n° {n}<br>'
                           f'{html.escape(lab or "—")}</figcaption></figure>')
            cards_html.append(f'<div class="row">{"".join(row)}</div>')

    md += ["## Comment lire", "",
           "- Une **confusion** peut révéler une limite du modèle (il rapproche la technique, "
           "la palette ou le format plutôt que le style), une **vraie parenté** (deux styles "
           "voisins), ou une **étiquette discutable** dans la source. Regarder les exemples.",
           "- Les étiquettes « Unknown » sont exclues."]
    md_path = out_dir / "audit.md"
    md_path.write_text("\n".join(md), encoding="utf-8")

    page = f"""<!doctype html><meta charset="utf-8"><title>Audit — échecs</title>
<style>
body{{font:14px system-ui,sans-serif;background:#111;color:#ddd;margin:16px}}
h2{{font-family:Georgia,serif;margin-top:28px}}
.row{{display:flex;gap:8px;margin:10px 0;padding:8px;background:#1a1a1a;border-radius:6px;overflow-x:auto}}
figure{{margin:0;width:150px;flex:none}}
figure img{{width:150px;height:120px;object-fit:contain;background:#000;border-radius:4px}}
figcaption{{font-size:11px;color:#999;margin-top:3px}}
figure.q{{outline:2px solid #e0b040;border-radius:4px}}
</style>
<h1>Audit à l'aveugle — exemples d'échecs</h1>
<p>Encadrée en or : l'œuvre ; à droite, ses 5 plus proches voisines selon le modèle, avec leur étiquette.
Analyse : {html.escape(analysis.id)}</p>
{''.join(cards_html)}"""
    html_path = out_dir / "audit.html"
    html_path.write_text(page, encoding="utf-8")
    return md_path, html_path
