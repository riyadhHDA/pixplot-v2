"""Nommer les groupes avec Iconclass, la classification iconographique des musées.

Iconclass (H. van de Waal, 1972-1985 ; édition en ligne E. Posthumus et J. P. J. Brandhorst)
range les sujets de l'art en environ 40 000 notions codées : « 73A5 l'Annonciation »,
« 11H(JEROME) Jérôme, moine et ermite… », « 25H paysage ». Données sous licence CC0
(https://github.com/iconclass/data), téléchargées par ``pixplot iconclass --fetch``.

Méthode (comme ``naming.py``, mais avec Iconclass à la place de notre lexique) : chaque
notion est décrite au modèle par son libellé anglais nettoyé (« a painting of the
announcement of Christ's birth ») ; le centre de chaque groupe dans l'espace SigLIP 2 est
comparé à toutes les notions ; on garde celles qui distinguent le plus ce groupe des autres
(écart à la moyenne des groupes, en écarts-types), parmi les plus proches en valeur absolue.

Le code Iconclass est la **source vérifiable** du nom : on peut le chercher sur
iconclass.org, et un musée qui indexe en Iconclass parle la même langue. Ce sont toujours
des propositions, à relire.
"""

from __future__ import annotations

import glob
import json
import re
import urllib.request
from pathlib import Path

import numpy as np

BASE = "https://raw.githubusercontent.com/iconclass/data/main"
FILES = ["notations.txt", "LICENSE"] + [f"txt/{lang}/txt_{lang}_{part}.txt" for lang in ("en", "fr")
                                        for part in ("0_1", "2_3", "4", "5_6_7_8", "9")]
TOP_RAW = 10          # parmi les 10 notions les plus proches du groupe…
KEEP = 3              # … on garde les 3 plus distinctives
FILE = "names_iconclass.json"
SURE, POSSIBLE = 4.0, 3.0  # z : relu sur WikiArt 81k, au-dessus de 4 le nom est presque toujours juste,
                           # entre 3 et 4 plausible, en dessous Iconclass n'a rien de convaincant
                           # (portraits, abstractions : la classification n'a pas de mot pour ça)


def confidence(z: float) -> str:
    return "sûr" if z >= SURE else "possible" if z >= POSSIBLE else "faible"


def link(notation: str) -> str:
    from urllib.parse import quote
    return "https://iconclass.org/" + quote(notation, safe="")


def icon_dir(settings) -> Path:
    return Path(settings.data_dir).parent / "iconclass" if (Path(settings.data_dir).parent / "iconclass").exists() \
        else Path(settings.data_dir) / "iconclass"


def fetch(dest: Path, say=print) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        target = dest / Path(f).name
        if not target.exists():
            say(f"  téléchargement {f}")
            urllib.request.urlretrieve(f"{BASE}/{f}", target)
    return dest


def _load(dest: Path, lang: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(glob.glob(str(dest / f"txt_{lang}_*.txt"))):
        for line in open(f, encoding="utf-8"):
            if "|" in line:
                n, t = line.rstrip("\n").split("|", 1)
                out[n] = t
    return out


def clean(label: str) -> str:
    """Libellé → description pour le modèle : sans références bibliques ni citations."""
    s = re.sub(r"\([^)]*\d+:\d+[^)]*\)", "", label)          # (Luc 1:26-38)
    s = re.sub(r"'[^']*' \(Ripa\)", "", s)
    s = s.replace(" ~ ", ", ").replace("~", ", ")
    s = re.sub(r"\s+", " ", s).strip(" ;,.")
    s = re.sub(r" ([,;])", r"\1", s)
    return s


MAX_DEPTH = 7          # « 41A6711 fleurs dans un vase » oui ; au-delà, des épisodes trop précis
NAMED_OK = ("11", "25")  # noms entre parenthèses gardés : saints (11H, 11HH) et espèces (25F, 25G)
NARRATIVE_DEPTH = 4    # Bible (7) et mythologie (9) : « 73A5 l'Annonciation » oui, épisodes de détail non
EXCLUDED = ("81", "82", "83")  # littérature : œuvres, personnages : trop précis, souvent trompeurs


def usable(notation: str) -> bool:
    """Notions bonnes à nommer un groupe : pas de variante de « clé » (lettres doublées,
    « 31AA » = version féminine…), profondeur limitée, noms propres seulement pour les
    saints et les espèces, pas de personnages ni d'œuvres littéraires."""
    base = notation.split("(")[0]
    if re.search(r"([A-Z])\1", base) or "+" in notation or notation.startswith(EXCLUDED):
        return False
    if "(" in notation and not notation.startswith(NAMED_OK):
        return False
    if base[:1] in "79" and len(base) > NARRATIVE_DEPTH:
        return False
    return len(base) <= MAX_DEPTH


def load_vocabulary(dest: Path) -> list[dict]:
    """Notions utilisables : libellé anglais et français, sans gabarit « (...) » vide."""
    en, fr = _load(dest, "en"), _load(dest, "fr")
    vocab = []
    for n, t in en.items():
        if "(...)" in n or n not in fr or not t.strip() or not usable(n) or "(Ripa)" in t or "NOM" in fr[n]:
            continue
        vocab.append({"notation": n, "en": t, "fr": fr[n], "prompt": "a painting of " + clean(t)[:200]})
    return vocab


def encode_vocabulary(vocab: list[dict], encoder, dest: Path, say=print, batch: int = 256) -> np.ndarray:
    cache = dest / f"vectors_{encoder.name}.npy"
    keys = dest / f"vectors_{encoder.name}.json"
    notations = [v["notation"] for v in vocab]
    if cache.exists() and keys.exists() and json.loads(keys.read_text(encoding="utf-8")) == notations:
        return np.load(cache)
    out = []
    for s in range(0, len(vocab), batch):
        out.append(encoder.encode_text([v["prompt"] for v in vocab[s:s + batch]]))
        if (s // batch) % 20 == 0:
            say(f"  {s + len(out[-1])}/{len(vocab)} notions encodées")
    V = np.concatenate(out).astype(np.float32)
    np.save(cache, V)
    keys.write_text(json.dumps(notations), encoding="utf-8")
    return V


def pick(centroids: np.ndarray, V: np.ndarray, top_raw: int = TOP_RAW, keep: int = KEEP) -> list[list[tuple[int, float, float]]]:
    """Pour chaque groupe : [(indice de notion, z, similarité)] — les plus distinctives
    parmi les ``top_raw`` plus proches."""
    S = centroids @ V.T                                         # (groupes, notions)
    Z = (S - S.mean(axis=0)) / np.maximum(S.std(axis=0), 1e-6)
    out = []
    for g in range(len(S)):
        near = np.argpartition(-S[g], top_raw)[:top_raw]
        best = near[np.argsort(-Z[g, near])][:keep]
        out.append([(int(i), float(Z[g, i]), float(S[g, i])) for i in best])
    return out


def name_groups(analysis, settings, encoder=None, say=print) -> Path:
    from ..features.extract import OK
    from ..features.store import FeatureStore
    from ..runs import list_runs

    dest = icon_dir(settings)
    if not (dest / "notations.txt").exists():
        raise SystemExit(f"Données Iconclass absentes ({dest}) : lancez `pixplot iconclass --fetch`.")
    vocab = load_vocabulary(dest)
    say(f"Iconclass : {len(vocab)} notions")
    runs = [r for r in list_runs("features", runs_dir=settings.runs_dir)
            if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")]
    if not runs:
        raise SystemExit("Pas de vecteurs SigLIP 2 : lancez `pixplot embed --encoder siglip2_so400m`.")
    store = FeatureStore.open(runs[-1])
    p = Path(analysis.path)
    ids, clusters = np.load(p / "ids.npy"), np.load(p / "clusters.npy")
    k = int(clusters.max()) + 1
    row = {int(i): r for r, i in enumerate(store.ids) if store.status[r] == OK}
    C = np.zeros((k, store.global_vectors.shape[1]), dtype=np.float32)
    for c in range(k):
        rows = sorted(row[int(i)] for i in ids[clusters == c] if int(i) in row)
        if rows:
            v = np.asarray(store.global_vectors[rows], dtype=np.float32).mean(axis=0)
            C[c] = v / max(float(np.linalg.norm(v)), 1e-12)
    if encoder is None:
        from ..encoders.registry import get_encoder
        say("Chargement de SigLIP 2…")
        params = runs[-1].manifest["params"]
        encoder = get_encoder(params["encoder"], hf_model=params.get("weights"), input_size=params.get("input_size"))
    V = encode_vocabulary(vocab, encoder, dest, say=say)
    picks = pick(C, V)
    groups = [{"cluster": c, "terms": [{"notation": vocab[i]["notation"], "fr": vocab[i]["fr"], "en": vocab[i]["en"],
                                        "z": round(z, 2), "sim": round(s, 4), "confidence": confidence(z)}
                                       for i, z, s in picks[c]]}
              for c in range(k)]
    out = p / FILE
    out.write_text(json.dumps({"source": runs[-1].id, "vocabulary": "Iconclass (CC0), iconclass.org",
                               "method": f"SigLIP 2 ; parmi les {TOP_RAW} notions les plus proches, les {KEEP} plus distinctives (z)",
                               "groups": groups}, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def shown_terms(group: dict, limit: int = 2) -> list[dict]:
    """Ce qu'on montre : les notions « sûr » ou « possible », avec leur lien iconclass.org."""
    return [{**t, "url": link(t["notation"])} for t in group.get("terms", [])
            if t["z"] >= POSSIBLE][:limit]


def load_names(analysis) -> dict[int, dict]:
    p = Path(analysis.path) / FILE
    if not p.exists():
        return {}
    return {g["cluster"]: g for g in json.loads(p.read_text(encoding="utf-8"))["groups"]}
