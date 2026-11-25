"""Banc d'essai « influence entre artistes » sur Wikidata (CC0), inspiré de WIB-100.

Principe (d'après le protocole équilibré de WIB-100, Liu et al., arXiv:2604.07468, non publié) :
on rattache les artistes du corpus à Wikidata (d'abord par identifiant WikiArt ``P6002``,
sinon par nom + cohérence de dates ; les cas ambigus sont laissés de côté), puis on collecte
séparément deux relations dirigées :

- ``P737`` (« influencé par » : si B a ``P737 = A``, alors ``A → B``) ;
- ``P1066`` (« élève de » : si B a ``P1066 = A``, alors maître ``A → B`` élève).

Chaque lien conserve les identifiants Wikidata, la propriété et les références citées sur
Wikidata. Les données de Wikidata sont des affirmations à sourcer, jamais des consignes.

Témoins (paires d'artistes sans lien ``P737``/``P1066`` connu entre eux, ≥ ``min_works`` œuvres) :
- ``difficiles`` : même époque (≤ 30 ans d'écart de naissance) et même style dominant ;
- ``moyens`` : même époque et autre style dominant ;
- ``faciles`` : époque différente (source ≥ 80 ans plus ancienne) et autre style dominant ;
- ``impossibles`` : source née après la mort de la cible (mis à part, hors mesure principale).

Mesure par artistes dans chaque regard (forme, sujet, couleur, touche, posture) : pour une
paire ``A → B``, on calcule, pour chaque œuvre ``b`` de B, le rang médian des œuvres de A parmi
les voisines de ``b`` (hors œuvres de B et hors doublons exacts de ``doublons.json``), puis la
médiane sur les œuvres de B (convertie en centile, invariant au nombre d'œuvres de A). On mesure
ensuite l'AUC « liens réels contre témoins » avec intervalles de confiance à 95 % et écarts
appariés entre regards par bootstrap sur les paires (2 000 tirages).
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "PixPlot-v2-research/0.1 (https://riyadhhda.github.io/pixplot-v2/)"
WIKIDATA_LICENSE = "CC0 1.0"
MIN_WORKS = 5
MIN_POSTURE_WORKS = 3
REVIEW_SAMPLE_SIZE = 30
REVIEW_FIELDS = [
    "source", "target", "source_qid", "target_qid", "property",
    "source_dates", "target_dates", "source_style", "target_style",
    "references", "verdict", "note",
]
CONTROL_TIERS = ("difficiles", "moyens", "faciles", "impossibles")


def influence_dir(settings) -> Path:
    d = Path(settings.data_dir) / "bench" / "influence"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ normalisation & dates
def _known(v: str | None) -> bool:
    return bool(v) and not v.strip().lower().startswith("unknown")


def _parse_year(raw: str | None) -> int | None:
    if not raw:
        return None
    m = re.search(r"(-?\d{4})", str(raw))
    if not m:
        return None
    y = int(m.group(1))
    return y if 1000 <= y <= 2026 else None


def _norm_text(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    return s


def slug_to_name(slug: str) -> str:
    """Convertit un slug WikiArt ('vincent-van-gogh') en nom probable ('Vincent van Gogh')."""
    particles = {"van", "von", "de", "del", "della", "da", "di", "du", "la", "le", "des", "el", "al"}
    parts = [p for p in re.split(r"[-_]+", slug.strip()) if p]
    out = []
    for i, p in enumerate(parts):
        out.append(p.lower() if (i > 0 and p.lower() in particles) else p.capitalize())
    return " ".join(out)


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _wd_year(val: str | None) -> int | None:
    if not val:
        return None
    m = re.match(r"^[+]?(-?\d{4})-", val)
    if not m:
        return None
    y = int(m.group(1))
    return y if 500 <= y <= 2026 else None


# ------------------------------------------------------------------ catalogue local
@dataclass
class CatalogArtist:
    slug: str
    n_artworks: int
    dominant_style: str
    median_year: int | None
    year_min: int | None
    year_max: int | None


def load_catalog_artists(catalog_path: Path) -> tuple[dict[str, CatalogArtist], dict[str, list[int]]]:
    """Lit les artistes connus (status = 'ok') dans ``catalog.sqlite``."""
    with sqlite3.connect(catalog_path) as db:
        rows = db.execute("""
            SELECT a.id, m_art.value, m_st.value, m_dt.value
            FROM artworks a
            JOIN metadata m_art ON m_art.artwork_id = a.id AND m_art.key = 'artist'
            LEFT JOIN metadata m_st ON m_st.artwork_id = a.id AND m_st.key = 'style'
            LEFT JOIN metadata m_dt ON m_dt.artwork_id = a.id AND m_dt.key = 'date'
            WHERE a.status = 'ok' AND m_art.value NOT LIKE 'Unknown%'
        """).fetchall()
    works: dict[str, list[int]] = defaultdict(list)
    styles: dict[str, Counter] = defaultdict(Counter)
    years: dict[str, list[int]] = defaultdict(list)
    for aid, artist, style, date in rows:
        if not _known(artist):
            continue
        works[artist].append(int(aid))
        if _known(style):
            styles[artist][style] += 1
        y = _parse_year(date)
        if y is not None:
            years[artist].append(y)
    artists: dict[str, CatalogArtist] = {}
    for slug, aids in sorted(works.items()):
        st = styles[slug].most_common(1)[0][0] if styles[slug] else ""
        ys = sorted(years[slug])
        artists[slug] = CatalogArtist(
            slug=slug,
            n_artworks=len(aids),
            dominant_style=st,
            median_year=int(np.median(ys)) if ys else None,
            year_min=ys[0] if ys else None,
            year_max=ys[-1] if ys else None,
        )
    return artists, dict(works)


# ------------------------------------------------------------------ Wikidata SPARQL
def sparql_query(query: str, *, timeout: float = 60.0, retries: int = 4, delay: float = 1.5) -> dict:
    """Exécute une requête SPARQL sur Wikidata avec User-Agent générique et gestion des limites."""
    import httpx

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/sparql-results+json",
    }
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            r = httpx.post(
                SPARQL_ENDPOINT,
                data={"query": query, "format": "json"},
                headers=headers,
                timeout=timeout,
            )
            if r.status_code in (429, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", delay * (2 ** attempt)))
                time.sleep(min(wait, 30.0))
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(delay * (2 ** attempt))
    raise RuntimeError(f"Échec de la requête SPARQL Wikidata après {retries} tentatives : {last_err}")


def _save_raw(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def fetch_p6002_table(out_dir: Path, *, say=print) -> tuple[list[dict], Path]:
    """Récupère tous les éléments Wikidata portant un identifiant WikiArt (P6002)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    q = """
    SELECT ?item ?itemLabel ?slug (MIN(?b) AS ?birth) (MIN(?d) AS ?death) WHERE {
      ?item wdt:P6002 ?slug .
      OPTIONAL { ?item wdt:P569 ?b . }
      OPTIONAL { ?item wdt:P570 ?d . }
      SERVICE wikibase:label { bd:serviceParam wikibase:language "fr,en". }
    } GROUP BY ?item ?itemLabel ?slug
    """
    say("Wikidata SPARQL : récupération des identifiants WikiArt (P6002)…")
    raw = sparql_query(q, timeout=90.0)
    bindings = raw["results"]["bindings"]
    raw_path = _save_raw(out_dir / f"raw_p6002_{stamp}.json", {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": SPARQL_ENDPOINT,
        "user_agent": USER_AGENT,
        "license": WIKIDATA_LICENSE,
        "query": q.strip(),
        "count": len(bindings),
        "bindings": bindings,
    })
    rows = []
    for b in bindings:
        rows.append({
            "qid": _qid(b["item"]["value"]),
            "label": b.get("itemLabel", {}).get("value", ""),
            "slug": b["slug"]["value"].strip().lower(),
            "birth_year": _wd_year(b.get("birth", {}).get("value")),
            "death_year": _wd_year(b.get("death", {}).get("value")),
        })
    return rows, raw_path


def fetch_candidates_by_name(slugs: list[str], out_dir: Path, *, batch_size: int = 35,
                             pause: float = 1.2, say=print) -> tuple[dict[str, list[dict]], Path]:
    """Recherche sur Wikidata par libellé exact (en/fr) pour les artistes sans P6002."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    all_batches: list[dict] = []
    by_norm: dict[str, list[dict]] = defaultdict(list)

    # Préparer les variantes de nom pour chaque slug
    names_to_query: list[str] = []
    seen_names: set[str] = set()
    for s in slugs:
        for cand in (slug_to_name(s), " ".join(p.capitalize() for p in re.split(r"[-_]+", s) if p)):
            if cand and cand not in seen_names:
                seen_names.add(cand)
                names_to_query.append(cand)

    say(f"Wikidata SPARQL : recherche par nom pour {len(slugs)} artistes sans P6002 ({len(names_to_query)} formes)…")
    for start in range(0, len(names_to_query), batch_size):
        chunk = names_to_query[start:start + batch_size]
        vals = " ".join(f'"{n.replace(chr(34), "")}"@en "{n.replace(chr(34), "")}"@fr' for n in chunk)
        q = f"""
        SELECT ?item ?itemLabel ?lbl (MIN(?b) AS ?birth) (MIN(?d) AS ?death) WHERE {{
          VALUES ?lbl {{ {vals} }}
          ?item rdfs:label ?lbl .
          ?item wdt:P31 wd:Q5 .
          ?item wdt:P106 ?occ .
          VALUES ?occ {{ wd:Q1028181 wd:Q483501 wd:Q1281618 wd:Q15296811 wd:Q11569986 wd:Q644687 wd:Q33231 wd:Q3391743 }}
          OPTIONAL {{ ?item wdt:P569 ?b . }}
          OPTIONAL {{ ?item wdt:P570 ?d . }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
        }} GROUP BY ?item ?itemLabel ?lbl
        """
        raw = sparql_query(q, timeout=60.0)
        bindings = raw["results"]["bindings"]
        all_batches.append({"offset": start, "count": len(bindings), "bindings": bindings})
        for b in bindings:
            rec = {
                "qid": _qid(b["item"]["value"]),
                "label": b.get("itemLabel", {}).get("value", ""),
                "matched_label": b.get("lbl", {}).get("value", ""),
                "birth_year": _wd_year(b.get("birth", {}).get("value")),
                "death_year": _wd_year(b.get("death", {}).get("value")),
            }
            by_norm[_norm_text(rec["matched_label"])].append(rec)
        if start + batch_size < len(names_to_query):
            time.sleep(pause)

    raw_path = _save_raw(out_dir / f"raw_names_{stamp}.json", {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": SPARQL_ENDPOINT,
        "user_agent": USER_AGENT,
        "license": WIKIDATA_LICENSE,
        "n_slugs": len(slugs),
        "batches": all_batches,
    })
    return dict(by_norm), raw_path


def _dates_compatible(artist: CatalogArtist, birth: int | None, death: int | None) -> bool:
    """Vérifie si des dates de vie Wikidata sont compatibles avec les œuvres datées du catalogue."""
    if birth is None and death is None:
        return False
    if artist.median_year is None:
        return True  # aucune date d'œuvre locale : on ne peut pas filtrer par date
    if birth is not None:
        # Un artiste ne peint pas avant 10 ans, ni plus de 110 ans après sa naissance
        if artist.year_min is not None and birth > artist.year_min - 8:
            return False
        if artist.median_year - birth > 110:
            return False
    if death is not None:
        # Tolérance de 15 ans (estampes / éditions posthumes ou date approximative WikiArt)
        if artist.median_year > death + 15:
            return False
        if artist.year_min is not None and death < artist.year_min:
            return False
    return True


def match_artists(catalog_artists: dict[str, CatalogArtist], p6002_rows: list[dict],
                  name_candidates: dict[str, list[dict]]) -> dict:
    """Rattache chaque artiste du catalogue à Wikidata : P6002 d'abord, puis nom + dates.

    Les cas ambigus (plusieurs QID candidats) sont laissés de côté (``match_status = 'ambigu'``).
    """
    by_slug: dict[str, list[dict]] = defaultdict(list)
    for r in p6002_rows:
        by_slug[r["slug"]].append(r)

    matched: dict[str, dict] = {}
    counts = Counter()

    for slug, art in sorted(catalog_artists.items()):
        base = asdict(art)
        # 1. Identifiant WikiArt exact (P6002)
        cands = {r["qid"]: r for r in by_slug.get(slug.lower(), [])}
        if len(cands) == 1:
            r = next(iter(cands.values()))
            matched[slug] = {**base, "match_status": "p6002", "qid": r["qid"], "label": r["label"],
                             "birth_year": r["birth_year"], "death_year": r["death_year"]}
            counts["p6002"] += 1
            continue
        if len(cands) > 1:
            matched[slug] = {**base, "match_status": "ambigu", "qid": None, "label": "",
                             "birth_year": None, "death_year": None,
                             "candidates": sorted(cands)}
            counts["ambigu"] += 1
            continue

        # 2. Repli : nom + cohérence de dates
        norm = _norm_text(slug_to_name(slug))
        raw_cands = {r["qid"]: r for r in name_candidates.get(norm, [])}
        if not raw_cands:
            matched[slug] = {**base, "match_status": "absent", "qid": None, "label": "",
                             "birth_year": None, "death_year": None}
            counts["absent"] += 1
            continue
        compat = [r for r in raw_cands.values() if _dates_compatible(art, r["birth_year"], r["death_year"])]
        if len(compat) == 1:
            r = compat[0]
            matched[slug] = {**base, "match_status": "nom_dates", "qid": r["qid"], "label": r["label"],
                             "birth_year": r["birth_year"], "death_year": r["death_year"]}
            counts["nom_dates"] += 1
        elif len(compat) > 1 or len(raw_cands) > 1:
            matched[slug] = {**base, "match_status": "ambigu", "qid": None, "label": "",
                             "birth_year": None, "death_year": None,
                             "candidates": sorted(r["qid"] for r in (compat or raw_cands.values()))}
            counts["ambigu"] += 1
        else:
            matched[slug] = {**base, "match_status": "absent", "qid": None, "label": "",
                             "birth_year": None, "death_year": None}
            counts["absent"] += 1

    # Vérifier les collisions : deux slugs différents rattachés au même QID -> garder aucun si ambigu
    by_qid: dict[str, list[str]] = defaultdict(list)
    for slug, info in matched.items():
        if info["qid"]:
            by_qid[info["qid"]].append(slug)
    for qid, slugs in by_qid.items():
        if len(slugs) > 1:
            # Si un seul vient de P6002 et les autres de nom_dates, on garde le P6002 et passe les autres en ambigu
            p6 = [s for s in slugs if matched[s]["match_status"] == "p6002"]
            to_drop = [s for s in slugs if s not in p6] if len(p6) == 1 else slugs
            for s in to_drop:
                counts[matched[s]["match_status"]] -= 1
                counts["ambigu"] += 1
                matched[s]["match_status"] = "ambigu"
                matched[s]["candidates"] = [qid]
                matched[s]["qid"] = None

    counts["surs"] = counts["p6002"] + counts["nom_dates"]
    counts["total"] = len(catalog_artists)
    return {"counts": dict(counts), "artists": matched}


def _chronology_status(src: dict, tgt: dict) -> str:
    """Classe une paire dirigée source → cible comme chronologiquement possible ou impossible.

    Une influence ``A → B`` est impossible si A est né après la mort de B (marge de 10 ans :
    A doit avoir eu au moins ~10 ans avant la mort de B) ou si A est né plus de 35 ans après B.
    """
    sb, tb, td = src.get("birth_year"), tgt.get("birth_year"), tgt.get("death_year")
    if sb is not None and td is not None and sb > td - 10:
        return "impossible"
    if sb is not None and tb is not None and sb > tb + 35:
        return "impossible"
    return "possible"


def fetch_wikidata_links(artists_data: dict, out_dir: Path, *, min_works: int = MIN_WORKS,
                         batch_size: int = 100, pause: float = 1.2, say=print) -> tuple[list[dict], Path]:
    """Récupère les liens P737 (influencé par) et P1066 (élève de) avec références Wikidata."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    eligible = {
        info["qid"]: slug
        for slug, info in artists_data["artists"].items()
        if info.get("qid") and info["n_artworks"] >= min_works
    }
    qids = sorted(eligible)
    say(f"Wikidata SPARQL : récupération des liens P737 et P1066 pour {len(qids)} artistes (≥ {min_works} œuvres)…")

    all_batches: list[dict] = []
    # (source_qid, target_qid, prop) -> set of (ref_prop, ref_val)
    link_refs: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    seen_pairs: set[tuple[str, str, str]] = set()

    for start in range(0, len(qids), batch_size):
        chunk = qids[start:start + batch_size]
        vals = " ".join(f"wd:{q}" for q in chunk)
        q = f"""
        SELECT ?target ?prop ?source ?refProp ?refVal ?refValLabel WHERE {{
          VALUES ?target {{ {vals} }}
          {{
            ?target p:P737 ?stmt . ?stmt ps:P737 ?source . BIND("P737" AS ?prop)
          }} UNION {{
            ?target p:P1066 ?stmt . ?stmt ps:P1066 ?source . BIND("P1066" AS ?prop)
          }}
          OPTIONAL {{
            ?stmt prov:wasDerivedFrom ?ref .
            ?ref ?refProp ?refVal .
            FILTER(?refProp IN (pr:P248, pr:P854, pr:P4656, pr:P143, pr:P813))
          }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "fr,en". }}
        }}
        """
        raw = sparql_query(q, timeout=60.0)
        bindings = raw["results"]["bindings"]
        all_batches.append({"offset": start, "count": len(bindings), "bindings": bindings})
        for b in bindings:
            tq = _qid(b["target"]["value"])
            sq = _qid(b["source"]["value"])
            prop = b["prop"]["value"]
            if sq not in eligible or tq not in eligible or sq == tq:
                continue
            key = (sq, tq, prop)
            seen_pairs.add(key)
            if "refProp" in b and "refVal" in b:
                rp = _qid(b["refProp"]["value"])
                rv = b["refVal"]["value"]
                rl = b.get("refValLabel", {}).get("value", rv)
                entry = {"prop": rp, "value": rv, "label": rl}
                if entry not in link_refs[key]:
                    link_refs[key].append(entry)
        if start + batch_size < len(qids):
            time.sleep(pause)

    raw_path = _save_raw(out_dir / f"raw_links_{stamp}.json", {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "endpoint": SPARQL_ENDPOINT,
        "user_agent": USER_AGENT,
        "license": WIKIDATA_LICENSE,
        "n_qids": len(qids),
        "batches": all_batches,
    })

    links: list[dict] = []
    for sq, tq, prop in sorted(seen_pairs):
        s_slug, t_slug = eligible[sq], eligible[tq]
        s_info, t_info = artists_data["artists"][s_slug], artists_data["artists"][t_slug]
        links.append({
            "source": s_slug,
            "target": t_slug,
            "source_qid": sq,
            "target_qid": tq,
            "property": prop,
            "chronology": _chronology_status(s_info, t_info),
            "references": link_refs.get((sq, tq, prop), []),
        })
    return links, raw_path


# ------------------------------------------------------------------ témoins (comme WIB-100)
def _effective_birth(info: dict) -> int | None:
    if info.get("birth_year") is not None:
        return int(info["birth_year"])
    if info.get("median_year") is not None:
        return int(info["median_year"]) - 35
    return None


def build_controls(artists_data: dict, links: list[dict], *, min_works: int = MIN_WORKS,
                   max_per_tier: int = 500, seed: int = 0) -> dict[str, list[dict]]:
    """Construit les 4 groupes témoins sans lien P737/P1066 connu entre les deux artistes."""
    known_undirected = {frozenset((l["source"], l["target"])) for l in links}
    pool = []
    for slug, info in sorted(artists_data["artists"].items()):
        if not info.get("qid") or info["n_artworks"] < min_works:
            continue
        b = _effective_birth(info)
        if b is None or not info.get("dominant_style"):
            continue
        pool.append((slug, info["qid"], b, info.get("death_year"), info["dominant_style"]))

    buckets: dict[str, list[dict]] = {t: [] for t in CONTROL_TIERS}
    for s_slug, s_qid, sb, sd, s_st in pool:
        for t_slug, t_qid, tb, td, t_st in pool:
            if s_slug == t_slug or frozenset((s_slug, t_slug)) in known_undirected:
                continue
            pair = {"source": s_slug, "target": t_slug, "source_qid": s_qid, "target_qid": t_qid}
            # Chronologiquement impossible (mis à part, hors mesure principale)
            if td is not None and sb >= td:
                buckets["impossibles"].append(pair)
                continue
            # Chronologiquement possible pour les témoins principaux
            if sb > tb + 15 or (td is not None and sb > td - 10):
                continue
            diff = abs(sb - tb)
            if diff <= 30:
                if s_st == t_st:
                    buckets["difficiles"].append(pair)
                else:
                    buckets["moyens"].append(pair)
            elif tb - sb >= 80 and s_st != t_st:
                buckets["faciles"].append(pair)

    rng = np.random.default_rng(seed)
    out: dict[str, list[dict]] = {}
    for tier in CONTROL_TIERS:
        cand = buckets[tier]
        if len(cand) > max_per_tier:
            idx = rng.choice(len(cand), size=max_per_tier, replace=False)
            out[tier] = [cand[int(i)] for i in sorted(idx)]
        else:
            out[tier] = cand
    return out


# ------------------------------------------------------------------ export relecture 30 liens
def export_review_sample(links: list[dict], artists_data: dict, out_csv: Path, *,
                         n: int = REVIEW_SAMPLE_SIZE, seed: int = 0) -> list[dict]:
    """Tire au hasard ``n`` liens P737 et les écrit dans un CSV pour relecture par l'historien."""
    p737 = [l for l in links if l["property"] == "P737" and l.get("chronology", "possible") == "possible"]
    rng = np.random.default_rng(seed)
    if len(p737) > n:
        idx = sorted(rng.choice(len(p737), size=n, replace=False).tolist())
        sample = [p737[i] for i in idx]
    else:
        sample = list(p737)

    def _dates(info: dict) -> str:
        b, d = info.get("birth_year"), info.get("death_year")
        return f"{b or '?'}–{d or '?'}"

    def _fmt_refs(refs: list[dict]) -> str:
        parts = []
        for r in refs:
            if r["prop"] in ("P854", "P4656"):
                parts.append(r["value"])
            elif r["prop"] in ("P248", "P143"):
                parts.append(r["label"])
        return " ; ".join(dict.fromkeys(parts))

    rows = []
    for l in sample:
        si = artists_data["artists"][l["source"]]
        ti = artists_data["artists"][l["target"]]
        rows.append({
            "source": l["source"],
            "target": l["target"],
            "source_qid": l["source_qid"],
            "target_qid": l["target_qid"],
            "property": l["property"],
            "source_dates": _dates(si),
            "target_dates": _dates(ti),
            "source_style": si.get("dominant_style", ""),
            "target_style": ti.get("dominant_style", ""),
            "references": _fmt_refs(l.get("references", [])),
            "verdict": "",
            "note": "",
        })
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


# ------------------------------------------------------------------ doublons
def load_duplicate_map(analysis_dir: Path | None) -> dict[int, set[int]]:
    """Charge les doublons exacts (``level == 'same'``) de ``doublons.json``."""
    if analysis_dir is None:
        return {}
    p = Path(analysis_dir) / "doublons.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    excl: dict[int, set[int]] = defaultdict(set)
    for pair in data.get("pairs", []):
        if pair.get("level") == "same":
            a, b = int(pair["a"]), int(pair["b"])
            excl[a].add(b)
            excl[b].add(a)
    return dict(excl)


# ------------------------------------------------------------------ mesure par artistes
def score_pairs_matrix(
    pairs: list[tuple[str, str]],
    artist_works: dict[str, list[int]],
    X: np.ndarray,
    row_of: dict[int, int],
    exclude: dict[int, set[int]] | None = None,
    *,
    min_works: int = MIN_WORKS,
    block: int = 256,
) -> dict[tuple[str, str], dict]:
    """Mesure la proximité ``A → B`` pour chaque paire dirigée dans un regard vectoriel.

    Pour chaque œuvre ``b`` de B, on classe tout le corpus hors œuvres de B et hors doublons
    de ``b``, puis on relève le rang médian des œuvres de A parmi les voisines de ``b``.
    Le score de la paire ``A → B`` est la médiane sur ``b ∈ B`` de ce rang médian, convertie
    en centile ``1 - (rang - 1) / (N' - 1)`` (0,5 = hasard, 1 = tout en tête). On conserve
    aussi le rang médian de la plus proche œuvre de A (``best_rank``) et le couple d'œuvres
    le plus proche ``(a_id, b_id, rank, sim)`` pour l'examen visuel.
    """
    N = len(X)
    if N < 2:
        return {}
    id_of_row = np.full(N, -1, dtype=np.int64)
    for aid, r in row_of.items():
        id_of_row[r] = aid

    # Lignes présentes par artiste
    a_rows: dict[str, np.ndarray] = {}
    for slug, aids in artist_works.items():
        rs = np.array([row_of[i] for i in aids if i in row_of], dtype=np.int64)
        if len(rs) >= min_works:
            a_rows[slug] = rs

    # Grouper les paires par artiste cible B
    by_target: dict[str, list[str]] = defaultdict(list)
    for src, tgt in pairs:
        if src in a_rows and tgt in a_rows and src != tgt:
            by_target[tgt].append(src)

    excl = exclude or {}
    out: dict[tuple[str, str], dict] = {}

    for tgt, srcs in by_target.items():
        srcs_unique = sorted(set(srcs))
        r_tgt = a_rows[tgt]
        n_tgt = len(r_tgt)
        # Accumulateurs par source
        med_ranks: dict[str, list[float]] = {s: [] for s in srcs_unique}
        min_ranks: dict[str, list[float]] = {s: [] for s in srcs_unique}
        best_pair: dict[str, tuple[float, int, int, int]] = {}  # (sim, a_id, b_id, rank)

        for start in range(0, n_tgt, block):
            qb = r_tgt[start:start + block]
            Sim = X[qb] @ X.T  # (m, N)
            for bi, row_b in enumerate(qb):
                b_id = int(id_of_row[row_b])
                s_vec = Sim[bi]
                s_vec[r_tgt] = -np.inf
                dup_rows = [row_of[d] for d in excl.get(b_id, ()) if d in row_of]
                if dup_rows:
                    s_vec[dup_rows] = -np.inf
                valid = s_vec[np.isfinite(s_vec)]
                n_valid = len(valid)
                if n_valid == 0:
                    continue
                valid_sorted = np.sort(valid)  # croissant

                for src in srcs_unique:
                    rs = a_rows[src]
                    vals = s_vec[rs]
                    ok = np.isfinite(vals)
                    if not ok.any():
                        continue
                    v_ok = vals[ok]
                    r_ok = rs[ok]
                    # Rang 1 = la plus proche : nombre de scores strictement supérieurs + 1
                    pos = np.searchsorted(valid_sorted, v_ok, side="right")
                    ranks = (n_valid - pos) + 1
                    med_ranks[src].append(float(np.median(ranks)))
                    best_idx = int(np.argmax(v_ok))
                    best_r = int(ranks[best_idx])
                    best_s = float(v_ok[best_idx])
                    min_ranks[src].append(float(best_r))
                    prev = best_pair.get(src)
                    if prev is None or best_s > prev[0]:
                        best_pair[src] = (best_s, int(id_of_row[r_ok[best_idx]]), b_id, best_r)

        n_denom = max(N - n_tgt - 1, 1)
        for src in srcs_unique:
            if not med_ranks[src]:
                continue
            mr = float(np.median(med_ranks[src]))
            br = float(np.median(min_ranks[src]))
            bp = best_pair[src]
            out[(src, tgt)] = {
                "median_rank": mr,
                "centile": float(1.0 - (mr - 1.0) / n_denom),
                "best_rank": br,
                "best_centile": float(1.0 - (br - 1.0) / n_denom),
                "n_source_works": int(len(a_rows[src])),
                "n_target_works": int(n_tgt),
                "top_work_pair": {"a": bp[1], "b": bp[2], "rank": bp[3], "sim": round(bp[0], 4)},
            }
    return out


def score_pairs_posture(
    pairs: list[tuple[str, str]],
    artist_works: dict[str, list[int]],
    posture_index,
    exclude: dict[int, set[int]] | None = None,
    *,
    min_works: int = MIN_POSTURE_WORKS,
) -> dict[tuple[str, str], dict]:
    """Même mesure pour le regard « posture » (PostureIndex multi-figures + miroir)."""
    if posture_index is None or posture_index.n_with_figures < 2:
        return {}
    # Sous-ensemble des œuvres figurées (counts > 0)
    fig_mask = posture_index.counts > 0
    fig_rows = np.flatnonzero(fig_mask)
    fig_ids = posture_index.ids[fig_rows]
    # Map artwork_id -> position dans fig_ids (0..M-1)
    fig_pos = {int(aid): pos for pos, aid in enumerate(fig_ids)}
    M = len(fig_ids)

    a_pos: dict[str, np.ndarray] = {}
    for slug, aids in artist_works.items():
        ps = np.array([fig_pos[i] for i in aids if i in fig_pos], dtype=np.int64)
        if len(ps) >= min_works:
            a_pos[slug] = ps

    by_target: dict[str, list[str]] = defaultdict(list)
    for src, tgt in pairs:
        if src in a_pos and tgt in a_pos and src != tgt:
            by_target[tgt].append(src)

    excl = exclude or {}
    out: dict[tuple[str, str], dict] = {}

    for tgt, srcs in by_target.items():
        srcs_unique = sorted(set(srcs))
        p_tgt = a_pos[tgt]
        n_tgt = len(p_tgt)
        med_ranks: dict[str, list[float]] = {s: [] for s in srcs_unique}
        min_ranks: dict[str, list[float]] = {s: [] for s in srcs_unique}
        best_pair: dict[str, tuple[float, int, int, int]] = {}

        for pos_b in p_tgt:
            b_id = int(fig_ids[pos_b])
            scores_full = posture_index.similarities_from(int(fig_rows[pos_b]), allow_mirror=True)
            s_vec = scores_full[fig_rows].astype(np.float32, copy=True)
            s_vec[p_tgt] = -np.inf
            dup_pos = [fig_pos[d] for d in excl.get(b_id, ()) if d in fig_pos]
            if dup_pos:
                s_vec[dup_pos] = -np.inf
            valid = s_vec[np.isfinite(s_vec)]
            n_valid = len(valid)
            if n_valid == 0:
                continue
            valid_sorted = np.sort(valid)

            for src in srcs_unique:
                ps = a_pos[src]
                vals = s_vec[ps]
                ok = np.isfinite(vals)
                if not ok.any():
                    continue
                v_ok = vals[ok]
                p_ok = ps[ok]
                pos = np.searchsorted(valid_sorted, v_ok, side="right")
                ranks = (n_valid - pos) + 1
                med_ranks[src].append(float(np.median(ranks)))
                best_idx = int(np.argmax(v_ok))
                best_r = int(ranks[best_idx])
                best_s = float(v_ok[best_idx])
                min_ranks[src].append(float(best_r))
                prev = best_pair.get(src)
                if prev is None or best_s > prev[0]:
                    best_pair[src] = (best_s, int(fig_ids[p_ok[best_idx]]), b_id, best_r)

        n_denom = max(M - n_tgt - 1, 1)
        for src in srcs_unique:
            if not med_ranks[src]:
                continue
            mr = float(np.median(med_ranks[src]))
            br = float(np.median(min_ranks[src]))
            bp = best_pair[src]
            out[(src, tgt)] = {
                "median_rank": mr,
                "centile": float(1.0 - (mr - 1.0) / n_denom),
                "best_rank": br,
                "best_centile": float(1.0 - (br - 1.0) / n_denom),
                "n_source_works": int(len(a_pos[src])),
                "n_target_works": int(n_tgt),
                "top_work_pair": {"a": bp[1], "b": bp[2], "rank": bp[3], "sim": round(bp[0], 4)},
            }
    return out


# ------------------------------------------------------------------ AUC & bootstrap apparié
def roc_auc(pos: np.ndarray, neg: np.ndarray) -> float:
    """ROC-AUC exact (statistique U de Mann-Whitney, ex aequo par rang moyen)."""
    n_pos, n_neg = len(pos), len(neg)
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    scores = np.concatenate([pos, neg])
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=np.float64)
    sorted_s = scores[order]
    i = 0
    while i < len(scores):
        j = i + 1
        while j < len(scores) and sorted_s[j] == sorted_s[i]:
            j += 1
        avg_rank = 0.5 * (i + j - 1) + 1.0
        ranks[order[i:j]] = avg_rank
        i = j
    u = ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2.0
    return float(u / (n_pos * n_neg))


def bootstrap_auc(pos: np.ndarray, neg: np.ndarray, *, n_boot: int = 2000,
                  seed: int = 0, level: float = 0.95) -> dict:
    """AUC et intervalle de confiance par bootstrap sur les paires (positifs et témoins)."""
    pos = np.asarray(pos, dtype=np.float64)
    neg = np.asarray(neg, dtype=np.float64)
    point = roc_auc(pos, neg)
    if len(pos) < 5 or len(neg) < 5:
        return {"auc": point, "ci": None, "n_pos": int(len(pos)), "n_neg": int(len(neg))}
    rng = np.random.default_rng(seed)
    lo_q, hi_q = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    vals = np.empty(n_boot, dtype=np.float64)
    ip = rng.integers(len(pos), size=(n_boot, len(pos)))
    ine = rng.integers(len(neg), size=(n_boot, len(neg)))
    for b in range(n_boot):
        vals[b] = roc_auc(pos[ip[b]], neg[ine[b]])
    return {
        "auc": point,
        "ci": [float(np.percentile(vals, lo_q)), float(np.percentile(vals, hi_q))],
        "n_pos": int(len(pos)),
        "n_neg": int(len(neg)),
    }


def paired_bootstrap_auc(
    pos_a: np.ndarray, pos_b: np.ndarray,
    neg_a: np.ndarray, neg_b: np.ndarray,
    *, n_boot: int = 2000, seed: int = 0, level: float = 0.95,
) -> dict:
    """Écart d'AUC apparié (regard A − regard B) par tirage simultané des mêmes paires."""
    pos_a, pos_b = np.asarray(pos_a, dtype=np.float64), np.asarray(pos_b, dtype=np.float64)
    neg_a, neg_b = np.asarray(neg_a, dtype=np.float64), np.asarray(neg_b, dtype=np.float64)
    auc_a, auc_b = roc_auc(pos_a, neg_a), roc_auc(pos_b, neg_b)
    diff = float(auc_a - auc_b)
    if len(pos_a) < 5 or len(neg_a) < 5:
        return {"diff_auc": diff, "ci": None, "p": None, "significant": False,
                "n_pos": int(len(pos_a)), "n_neg": int(len(neg_a))}
    rng = np.random.default_rng(seed)
    lo_q, hi_q = (1.0 - level) / 2.0 * 100.0, (1.0 + level) / 2.0 * 100.0
    diffs = np.empty(n_boot, dtype=np.float64)
    ip = rng.integers(len(pos_a), size=(n_boot, len(pos_a)))
    ine = rng.integers(len(neg_a), size=(n_boot, len(neg_a)))
    for b in range(n_boot):
        diffs[b] = roc_auc(pos_a[ip[b]], neg_a[ine[b]]) - roc_auc(pos_b[ip[b]], neg_b[ine[b]])
    lo, hi = float(np.percentile(diffs, lo_q)), float(np.percentile(diffs, hi_q))
    p_two = float(min(1.0, 2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean())))
    return {
        "diff_auc": diff,
        "ci": [lo, hi],
        "p": p_two,
        "significant": bool(lo > 0.0 or hi < 0.0),
        "n_pos": int(len(pos_a)),
        "n_neg": int(len(neg_a)),
    }


def evaluate_scores(
    scores_by_space: dict[str, dict[tuple[str, str], dict]],
    positives: dict[str, list[tuple[str, str]]],
    controls: dict[str, list[tuple[str, str]]],
    *,
    metric: str = "centile",
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict:
    """Calcule les AUC, IC 95 % et écarts appariés pour chaque relation × groupe témoin."""
    spaces = list(scores_by_space)
    report: dict = {"metric": metric, "n_boot": n_boot, "level": level, "comparisons": {}}

    for rel, pos_pairs in positives.items():
        for tier, neg_pairs in controls.items():
            key = f"{rel}_vs_{tier}"
            sp_stats = {}
            for sp in spaces:
                sc = scores_by_space[sp]
                pv = np.array([sc[p][metric] for p in pos_pairs if p in sc], dtype=np.float64)
                nv = np.array([sc[p][metric] for p in neg_pairs if p in sc], dtype=np.float64)
                st = bootstrap_auc(pv, nv, n_boot=n_boot, seed=seed, level=level)
                st["pos_median"] = float(np.median(pv)) if len(pv) else None
                st["neg_median"] = float(np.median(nv)) if len(nv) else None
                sp_stats[sp] = st

            paired = []
            for i, s1 in enumerate(spaces):
                for s2 in spaces[i + 1:]:
                    sc1, sc2 = scores_by_space[s1], scores_by_space[s2]
                    common_pos = [p for p in pos_pairs if p in sc1 and p in sc2]
                    common_neg = [p for p in neg_pairs if p in sc1 and p in sc2]
                    pa = np.array([sc1[p][metric] for p in common_pos], dtype=np.float64)
                    pb = np.array([sc2[p][metric] for p in common_pos], dtype=np.float64)
                    na = np.array([sc1[p][metric] for p in common_neg], dtype=np.float64)
                    nb = np.array([sc2[p][metric] for p in common_neg], dtype=np.float64)
                    res = paired_bootstrap_auc(pa, pb, na, nb, n_boot=n_boot, seed=seed, level=level)
                    paired.append({"a": s1, "b": s2, **res})
            report["comparisons"][key] = {"relation": rel, "control": tier,
                                          "spaces": sp_stats, "paired": paired}
    return report
