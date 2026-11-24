"""Fabrique les démonstrations animées du site à partir de vraies réponses de PixPlot sur WikiArt 81k.

Pour chaque cas d'usage, on interroge l'Atlas qui tourne (``pixplot --data data/wikiart81k serve --port 8766``) :
voisines, zones qui se répondent, recherche de zone et de phrase, squelettes, étiquettes à vérifier, doublons,
désaccords, notion apprise ; l'axe de Wölfflin est calculé avec SigLIP 2. On écrit :

- ``site/assets/scenes.json`` : œuvres, zones, liens et déroulé de chaque scène ;
- ``site/assets/oeuvres/<id>.webp`` (et ``<id>-l.webp`` pour les grandes) : vignettes réduites.

Seules des œuvres du domaine public sont reproduites (artistes morts avant 1956) : la liste est fixée ici,
à la main, et vérifiée œuvre par œuvre.

Usage : .venv/Scripts/python scripts/site_scenes.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "wikiart81k"
OUT = ROOT / "site" / "assets"
IMG = OUT / "oeuvres"
API = "http://127.0.0.1:8766"

# Œuvres retenues (toutes d'artistes morts avant 1956 : domaine public).
REPRISE = 79294                       # Van Gogh, Le Semeur d'après Millet, 1889
MILLET = 41274                        # Millet, Le Semeur, 1850
MOTIF_Q = "a skull"
MOTIF = [8723, 28410, 38609, 35525, 70211, 36503]   # El Greco, Cézanne, Zurbarán, Dürer, Mabuse, Ribera
THEME_Q = "Annonciation dans un jardin"
GESTE = (66184, 56885)                # Titien, Vénus (1565) ↔ Mantegna, Christ au jardin des Oliviers (1455)
SUSPECT = 1225                        # Sisley, 1894 : ses voisines étiquetées sont des Monet
DOUBLON = (3733, 3948)                # Corot, 1873 : la même image, « romantique » et « réaliste »
DESACCORD = (32914, 67091)            # d'après Rembrandt (gravure Bowyer) ↔ Bryullov, 1831
NOTION = 607                          # regard « forme » : échelle (Iconclass 41A343)
NOTION_PD = [10582, 17746, 70404, 45762, 71573, 32934, 33315, 35161]
DEAD_BEFORE_1956 = {                  # artistes acceptés pour les résultats pris automatiquement
    "leonardo-da-vinci", "benozzo-gozzoli", "gustave-dore", "rembrandt", "vittore-carpaccio", "albrecht-durer",
    "sandro-botticelli", "pietro-perugino", "fra-angelico", "jean-fouquet", "claude-monet", "alfred-sisley",
    "vincent-van-gogh", "jean-francois-millet", "titian", "raphael", "tintoretto", "paolo-veronese",
    "lorenzo-lotto", "giorgione", "correggio", "parmigianino", "jacopo-pontormo", "agnolo-bronzino",
    "hans-holbein-the-younger", "lucas-cranach-the-elder", "hans-memling", "rogier-van-der-weyden",
    "jan-van-eyck", "hieronymus-bosch", "pieter-bruegel-the-elder", "andrea-mantegna", "giovanni-bellini",
    "piero-della-francesca", "filippo-lippi", "domenico-ghirlandaio", "michelangelo", "el-greco",
    "caravaggio", "peter-paul-rubens", "anthony-van-dyck", "jacopo-bassano", "albrecht-altdorfer",
    "hans-baldung", "mabuse", "jan-van-hemessen", "maerten-van-heemskerck", "giorgio-vasari",
    "rosso-fiorentino", "joos-van-cleve", "quentin-matsys", "bernard-van-orley", "jacopo-tintoretto",
    "francesco-salviati", "sebastiano-del-piombo", "andrea-del-sarto", "dosso-dossi", "moretto-da-brescia",
    "giovanni-battista-moroni", "federico-barocci", "annibale-carracci", "agostino-carracci", "guido-reni",
}

LANG = ("fr", "en")


def get(path: str, **q) -> dict:
    """Appel à l'API de l'Atlas local."""
    url = API + path + ("?" + urllib.parse.urlencode(q) if q else "")
    with urllib.request.urlopen(url, timeout=900) as r:
        return json.loads(r.read())


ART: dict[int, dict] = {}


def art(i: int, large: bool = False) -> int:
    """Enregistre une œuvre (métadonnées courtes) et écrit sa vignette réduite."""
    i = int(i)
    if i not in ART:
        a = get(f"/api/artwork/{i}")
        m = a.get("metadata", {})
        ART[i] = {"w": a["width"], "h": a["height"], "artist": m.get("artist"), "title": m.get("title"),
                  "date": m.get("date"), "style": m.get("style"), "genre": m.get("genre")}
    src = DATA / "thumbs" / "1024" / f"{i // 1000:04d}" / f"{i}.webp"
    IMG.mkdir(parents=True, exist_ok=True)
    for suffix, side, q in (("", 360, 74), ("-l", 900, 72)) if large else (("", 360, 74),):
        dst = IMG / f"{i}{suffix}.webp"
        if not dst.exists():
            im = Image.open(src).convert("RGB")
            im.thumbnail((side, side), Image.LANCZOS)
            im.save(dst, "WEBP", quality=q, method=6)
    if large:
        ART[i]["large"] = True
    return i


def who(i: int) -> str:
    a = ART[i]
    name = (a["artist"] or "").replace("-", " ").title()
    return f"{name}{', ' + a['date'] if a.get('date') else ''}"


def wolfflin() -> dict:
    """Œuvres réelles 1500–1549 et 1550–1599 placées sur l'axe linéaire / pictural (ARCHITECTURE § 43)."""
    sys.path.insert(0, str(ROOT))
    from pixplot.api.data import AtlasData
    from pixplot.api.search import SearchEngines
    from pixplot.config import get_settings

    lin = ("a painting with clear outlines | contours drawn with a firm line, forms modelled with crisp edges"
           " | smooth even paint with sharply defined shapes")
    pic = ("a painting made of loose patches of colour | brushwork instead of outlines, soft blurred edges merging"
           " into the background | paint applied in visible, broken touches")
    from pixplot.api.search import concept_phrases, pole_vectors
    data = AtlasData.load(get_settings(DATA))
    eng = SearchEngines(data)
    eng._load_text()
    tv = pole_vectors(eng._text_encoder, [concept_phrases(lin), concept_phrases(pic)])
    store = eng._text_store
    row = {int(a): r for r, a in enumerate(store.ids)}
    n = len(data.ids)
    sl, sp = np.full(n, np.nan), np.full(n, np.nan)
    for r, aid in enumerate(data.ids):
        q = row.get(int(aid))
        if q is not None:
            v = store.global_vectors[q].astype(np.float32)
            sl[r], sp[r] = v @ tv[0], v @ tv[1]
    ok = np.isfinite(sl)
    zd = (sp - sp[ok].mean()) / sp[ok].std() - (sl - sl[ok].mean()) / sl[ok].std()
    years = np.array([y if y is not None else np.nan for y in data.years()], dtype=float)
    out = {}
    for name, lo, hi in (("a", 1500, 1550), ("b", 1550, 1600)):
        m = ok & (years >= lo) & (years < hi)
        idx = np.flatnonzero(m)
        med = float(np.median(zd[idx]))
        picks = []
        for qt in (0.1, 0.3, 0.5, 0.7, 0.9):
            target = np.quantile(zd[idx], qt)
            for r in idx[np.argsort(np.abs(zd[idx] - target))]:
                meta = data.meta.get(int(data.ids[r]), {})
                if meta.get("artist") in DEAD_BEFORE_1956 and meta.get("genre") not in ("sketch_and_study",) \
                        and int(data.ids[r]) not in picks:
                    picks.append(int(data.ids[r]))
                    break
        out[name] = {"median": round(med, 2), "n": int(m.sum()),
                     "works": [{"id": art(i), "z": round(float(zd[data.row_of[i]]), 2)} for i in picks]}
    return out, data


def main() -> int:
    scenes: dict[str, dict] = {}

    # 1. Qui a repris qui ? Voisines réelles et zones qui se répondent.
    a = get(f"/api/artwork/{REPRISE}", k=4)
    neigh = [{"id": art(n["id"]), "score": round(n["score"], 3)} for n in a["neighbors"][:4]]
    corr = get("/api/correspond", a=REPRISE, b=MILLET, k=4)["pairs"]
    scenes["reprise"] = {"base": art(REPRISE, True), "match": art(MILLET, True), "neighbors": neigh,
                         "space": a.get("space"),
                         "pairs": [{"a": p["box_a"], "b": p["box_b"], "sim": round(p["sim"], 3)} for p in corr]}

    # 2. Où revient ce motif ? Zones décrites par des mots.
    z = {h["id"]: h for h in get("/api/search/zones", q=MOTIF_Q)["results"]}
    scenes["motif"] = {"query": MOTIF_Q, "hits": [{"id": art(i, True), "box": z[i]["box"],
                                                    "rank": list(z).index(i) + 1} for i in MOTIF if i in z]}

    # 3. Quelles œuvres traitent ce thème ? Les six premiers résultats, tels quels.
    t = get("/api/search/text", q=THEME_Q, k=12)["results"]
    hits = []
    for rank, h in enumerate(t, 1):
        meta = get(f"/api/artwork/{h['id']}").get("metadata", {})
        if meta.get("artist") in DEAD_BEFORE_1956:
            hits.append({"id": art(h["id"]), "rank": rank, "score": round(h["score"], 3)})
        if len(hits) == 6:
            break
    scenes["theme"] = {"query": THEME_Q, "hits": hits}

    # 4. Le même geste ? Squelettes détectés et figures appariées.
    pm = get("/api/posture/match", a=GESTE[0], b=GESTE[1])
    pick = lambda figs, k: next((f for f in figs if f.get("fig") == k), figs[min(k, len(figs) - 1)])  # noqa: E731
    fa, fb = pick(pm["figures_a"], pm["fig_a"]), pick(pm["figures_b"], pm["fig_b"])
    scenes["geste"] = {"a": art(GESTE[0], True), "b": art(GESTE[1], True), "score": round(pm["score"], 3),
                       "mirrored": pm["mirrored"], "limbs": pm["limbs"], "thr": pm["kpt_threshold"],
                       "kpts_a": fa.get("kpts") or fa.get("keypoints"), "kpts_b": fb.get("kpts") or fb.get("keypoints"),
                       "raw_a": {k: v for k, v in fa.items() if k not in ("kpts", "keypoints")},
                       "raw_b": {k: v for k, v in fb.items() if k not in ("kpts", "keypoints")}}

    # 5. Mon catalogue est-il fiable ? Une étiquette contredite, un doublon.
    sus, off = None, 0
    while sus is None:
        page = get("/api/suspects", key="artist", offset=off, limit=500)
        sus = next((s for s in page["items"] if s["id"] == SUSPECT), None)
        off += 500
        if off >= page["total"]:
            break
    dup = next((d for d in get("/api/duplicates", level="same", limit=200)["items"]
                if {d["a"], d["b"]} == set(DOUBLON)), None)
    scenes["catalogue"] = {"suspect": art(SUSPECT, True), "value": sus["value"], "suggested": sus["suggested"],
                           "majority": sus["majority"], "neighbors": [art(i) for i in sus["neighbors"][:6]],
                           "dup": [art(DOUBLON[0]), art(DOUBLON[1])],
                           "dup_styles": [dup["meta_a"]["style"], dup["meta_b"]["style"]] if dup else None,
                           "dup_cos": dup["cos"] if dup else None}

    # 6. Qu'est-ce qui rapproche ces deux œuvres ? Centiles réels des quatre regards.
    c = get("/api/compare", ids=f"{DESACCORD[0]},{DESACCORD[1]}")
    dis = next(d for d in get("/api/disagreements", near="forme", far="sujet", limit=200)["items"]
               if (d["a"], d["b"]) == DESACCORD)
    zc = get("/api/correspond", a=DESACCORD[0], b=DESACCORD[1], k=4)["pairs"]
    scenes["regards"] = {"a": art(DESACCORD[0], True), "b": art(DESACCORD[1], True),
                         "rank_forme": dis["rank"], "centile_sujet": dis["centile"],
                         "pairs": [{"a": p["box_a"], "b": p["box_b"]} for p in zc],
                         "similarity": {k: round(v[0][1], 3) for k, v in c["similarity"].items()}}

    # 8. Notion apprise : la même notion dans des œuvres très différentes.
    n = get(f"/api/notions/{NOTION}", space="forme", limit=60)
    rank = {it["id"]: k + 1 for k, it in enumerate(n["items"])}
    scenes["notions"] = {"feature": NOTION, "label": n["label"], "iconclass": n["iconclass"], "total": n["total"],
                         "works": [{"id": art(i), "rank": rank.get(i)} for i in NOTION_PD]}

    # 9. Axe de Wölfflin : œuvres réelles à leur place.
    scenes["axes"], data = wolfflin()

    # 7. Filtres : dans l'échantillon de la carte d'ouverture (même tirage), les œuvres Baroque + portrait.
    carte = json.loads((OUT / "carte.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(7)
    idx = np.sort(rng.choice(len(data.ids), 6000, replace=False))
    flags = [k for k, r in enumerate(idx) if data.meta.get(int(data.ids[r]), {}).get("style") == "Baroque"
             and data.meta.get(int(data.ids[r]), {}).get("genre") == "portrait"]
    total = sum(1 for i in data.ids if data.meta.get(int(i), {}).get("style") == "Baroque"
                and data.meta.get(int(i), {}).get("genre") == "portrait")
    assert len(carte["pts"]) == 3 * len(idx)
    scenes["filtres"] = {"sample": flags, "total": total}

    out = {"source": "PixPlot v2 sur WikiArt 81k (réponses réelles de l'Atlas, 24/11/2026)", "art": ART, "scenes": scenes}
    (OUT / "scenes.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size = sum(p.stat().st_size for p in IMG.glob("*.webp"))
    print(f"scenes.json écrit ; {len(ART)} œuvres, {len(list(IMG.glob('*.webp')))} images, {size / 1024:.0f} Ko")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
