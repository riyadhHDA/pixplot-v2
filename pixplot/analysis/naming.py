"""Noms automatiques des groupes : « Paysages · tons sombres » plutôt que « Groupe 124 ».

Méthode (fonctionne sans aucune métadonnée) : le centre de chaque groupe dans l'espace
SigLIP 2 est comparé à un vocabulaire d'histoire de l'art (sujets d'un côté, techniques
et manières de l'autre). On ne garde pas le terme le plus proche dans l'absolu (« un
tableau » l'emporterait partout) mais celui qui distingue le plus ce groupe des autres :
écart à la moyenne des groupes, en écarts-types (z).

C'est une **proposition de nom**, à relire : les termes viennent d'un modèle et non d'un
catalogue. Les métadonnées dominantes (artistes, styles), quand elles existent, sont
données à part, avec leur proportion.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

# (nom français, description anglaise donnée au modèle)
SUBJECTS = [
    ("Paysages", "a landscape painting"),
    ("Marines", "a seascape with boats and waves"),
    ("Vues urbaines", "a city street with buildings"),
    ("Portraits", "a portrait of a person"),
    ("Portraits de groupe", "a group portrait of several people"),
    ("Natures mortes", "a still life with objects on a table"),
    ("Fleurs", "flowers in a vase"),
    ("Scènes religieuses", "a religious scene with saints and angels"),
    ("Vierge à l'Enfant", "the Virgin Mary holding the Christ child"),
    ("Crucifixions", "the crucifixion of Christ"),
    ("Mythologie", "a mythological scene with gods and nymphs"),
    ("Nus", "a nude figure"),
    ("Scènes de genre", "people in an everyday life scene"),
    ("Intérieurs", "a domestic interior"),
    ("Batailles", "a battle with soldiers and horses"),
    ("Animaux", "animals"),
    ("Chevaux", "horses"),
    ("Forêts", "trees in a forest"),
    ("Montagnes", "mountains"),
    ("Architecture", "a building facade, architecture"),
    ("Abstraction géométrique", "a geometric abstract composition"),
    ("Abstraction gestuelle", "an abstract painting with gestural brushstrokes"),
    ("Aplats de couleur", "large flat fields of color"),
    ("Figures féminines", "a woman"),
    ("Enfants", "children"),
    ("Danse et spectacle", "dancers on a stage"),
    ("Scènes nocturnes", "a night scene"),
    ("Hiver", "a winter landscape with snow"),
    ("Jardins", "a garden"),
    ("Rivières et ponts", "a river with a bridge"),
    ("Plages", "people on a beach"),
    ("Visages", "a close-up of a face"),
    ("Têtes d'étude", "a study of a head"),
    ("Mers et ciels", "the sea and the sky at sunset"),
]
MANNERS = [
    ("gravure", "an engraving, black and white print"),
    ("dessin", "a pencil or charcoal drawing"),
    ("esquisse", "a rough sketch"),
    ("aquarelle", "a watercolor"),
    ("estampe japonaise", "a Japanese woodblock print"),
    ("affiche", "a poster with text"),
    ("fresque", "a fresco on a wall"),
    ("icône", "a byzantine icon with gold background"),
    ("enluminure", "an illuminated manuscript page"),
    ("sculpture", "a photograph of a sculpture"),
    ("collage", "a collage"),
    ("empâtements", "thick visible brushstrokes, impasto"),
    ("points de couleur", "a painting made of small dots of color"),
    ("couleurs vives", "vivid saturated colors"),
    ("tons sombres", "dark tones, chiaroscuro"),
    ("tons clairs", "light pale colors"),
    ("monochrome", "a monochrome image"),
    ("formes géométriques", "hard-edged geometric shapes"),
    ("formes fragmentées", "cubist fragmented forms"),
    ("style naïf", "naive art"),
    ("style bande dessinée", "pop art comic style"),
    ("fond d'or", "gold background"),
    ("cerne noir", "bold black outlines and flat colors"),
]
NAMES_FILE = "names.json"
MANNER_MIN_Z = 1.0


def _pick(S: np.ndarray, top_raw: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Pour chaque groupe (ligne), le terme le plus distinctif parmi ses ``top_raw`` plus
    proches en valeur absolue. Renvoie (indices, z)."""
    Z = (S - S.mean(axis=0)) / np.maximum(S.std(axis=0), 1e-6)
    allowed = np.zeros_like(S, dtype=bool)
    near = np.argsort(-S, axis=1)[:, :top_raw]
    np.put_along_axis(allowed, near, True, axis=1)
    Zm = np.where(allowed, Z, -np.inf)
    best = Zm.argmax(axis=1)
    return best, Z[np.arange(len(S)), best]


def name_from_vectors(centroids: np.ndarray, subject_vecs: np.ndarray, manner_vecs: np.ndarray) -> list[dict]:
    """Centres de groupes et vocabulaire, tous normalisés dans le même espace."""
    S1, S2 = centroids @ subject_vecs.T, centroids @ manner_vecs.T
    subj, z1 = _pick(S1)
    man, z2 = _pick(S2)
    out = []
    for c in range(len(centroids)):
        terms = [{"term": SUBJECTS[subj[c]][0], "kind": "sujet", "z": round(float(z1[c]), 2)}]
        name = SUBJECTS[subj[c]][0]
        if z2[c] >= MANNER_MIN_Z:
            terms.append({"term": MANNERS[man[c]][0], "kind": "manière", "z": round(float(z2[c]), 2)})
            name += f" · {MANNERS[man[c]][0]}"
        out.append({"name": name, "terms": terms})
    return out


def metadata_name(meta: list[dict[str, str]]) -> str:
    """« Corot, Chichkine · Réalisme » : ce que disent les métadonnées, si c'est net."""
    def top(key: str, min_share: float, n: int) -> list[str]:
        vals = [m.get(key) for m in meta]
        vals = [v for v in vals if v and not v.lower().startswith("unknown")]
        if not vals:
            return []
        return [v for v, c in Counter(vals).most_common(n) if c / len(meta) >= min_share]

    def pretty(v: str) -> str:
        return v.replace("_", " ").replace("-", " ").title() if v.islower() or "_" in v else v

    bits = []
    artists = top("artist", 0.08, 2)
    if artists:
        bits.append(", ".join(pretty(a).split()[-1] for a in artists))
    for key, share in (("style", 0.35), ("genre", 0.5)):
        vals = top(key, share, 1)
        if vals:
            bits.append(pretty(vals[0]))
    return " · ".join(bits)


def name_groups(analysis, settings, encoder=None, say=print) -> Path:
    """Écrit ``names.json`` dans le run d'analyse. ``encoder`` : un SigLIP2Encoder déjà
    chargé (sinon chargé ici) ; sans vecteurs SigLIP, seuls les noms « métadonnées »."""
    from ..catalog import db
    from ..catalog.metadata import get_metadata
    from ..features.extract import OK
    from ..features.store import FeatureStore
    from ..runs import list_runs

    p = Path(analysis.path)
    ids = np.load(p / "ids.npy")
    clusters = np.load(p / "clusters.npy")
    k = int(clusters.max()) + 1
    conn = db.connect(settings.catalog_path)
    meta = get_metadata(conn, ids.tolist())
    conn.close()

    runs = [r for r in list_runs("features", runs_dir=settings.runs_dir)
            if str(r.manifest["params"].get("encoder", "")).startswith("siglip2")
            and r.manifest.get("status") == "complete"]
    named: list[dict] | None = None
    source = None
    if runs:
        store = FeatureStore.open(runs[-1])
        row = {int(i): r for r, i in enumerate(store.ids) if store.status[r] == OK}
        centroids = np.zeros((k, store.global_vectors.shape[1]), dtype=np.float32)
        for c in range(k):
            rows = [row[int(i)] for i in ids[clusters == c] if int(i) in row]
            if rows:
                v = np.asarray(store.global_vectors[sorted(rows)], dtype=np.float32).mean(axis=0)
                centroids[c] = v / max(float(np.linalg.norm(v)), 1e-12)
        if encoder is None:
            from ..encoders.registry import get_encoder
            say("Chargement de SigLIP 2 pour le vocabulaire…")
            encoder = get_encoder(runs[-1].manifest["params"]["encoder"])
        subject_vecs = encoder.encode_text([e for _, e in SUBJECTS])
        manner_vecs = encoder.encode_text([e for _, e in MANNERS])
        named = name_from_vectors(centroids, subject_vecs, manner_vecs)
        source = runs[-1].id

    out = []
    for c in range(k):
        members = [meta.get(int(i), {}) for i in ids[clusters == c]]
        entry = {"cluster": c, "metadata_name": metadata_name(members) if members else ""}
        if named:
            entry.update(named[c])
        else:
            entry["name"] = entry["metadata_name"]
            entry["terms"] = []
        out.append(entry)
    path = p / NAMES_FILE
    path.write_text(json.dumps({"source": source, "method": "SigLIP 2, vocabulaire d'histoire de l'art, "
                                "terme le plus distinctif (z)" if source else "métadonnées dominantes",
                                "groups": out}, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def load_names(analysis) -> dict[int, dict]:
    path = Path(analysis.path) / NAMES_FILE
    if not path.exists():
        return {}
    return {g["cluster"]: g for g in json.loads(path.read_text(encoding="utf-8"))["groups"]}
