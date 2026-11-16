"""Lieux typés et datés des œuvres, d'après le programme ARTL@S (B. Joyeux-Prunel, 2012).

Un « lieu » d'œuvre n'est jamais un seul lieu : l'atelier où elle a été faite, la salle où
elle a été exposée, le musée qui la conserve, le paysage qu'elle représente, les villes où a
vécu l'artiste posent des questions différentes. Et chaque lieu a une date : sans elle, on
ne voit pas les circulations. D'où une table à part, une œuvre pouvant avoir plusieurs lieux :

    places(artwork_id, type, name, lat, lon, date, year, source)

Les lieux viennent d'un fichier (``pixplot import-places``, colonnes ``path`` ou ``id``,
``type``, ``place``, ``lat``, ``lon``, ``date``, ``source``) ou sont **déduits des
métadonnées** déjà importées (``pixplot places --derive``) : dépôt d'un musée → lieu de
conservation, « born in Munich » → naissance de l'artiste, etc. Les coordonnées manquantes
sont cherchées dans un petit répertoire embarqué (``gazetteer``) ; un lieu inconnu reste
sans coordonnées plutôt que d'être deviné.

Une carte de lieux montre des répartitions et des circulations, pas des styles : ne pas
expliquer une manière par un lieu (contre le déterminisme hérité de Taine).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from . import gazetteer

# clé → (libellé, ce que la carte de ce type montre)
PLACE_TYPES: dict[str, tuple[str, str]] = {
    "creation": ("Lieu de création", "où l'œuvre a été faite"),
    "exposition": ("Lieu d'exposition", "où l'œuvre a été montrée, à une date donnée"),
    "conservation": ("Lieu de conservation", "où l'œuvre est conservée (aujourd'hui, sauf date contraire)"),
    "represente": ("Lieu représenté", "le lieu que l'œuvre figure"),
    "naissance_artiste": ("Naissance de l'artiste", "où l'artiste est né"),
    "residence_artiste": ("Résidence de l'artiste", "où l'artiste a vécu ou travaillé"),
    "deces_artiste": ("Mort de l'artiste", "où l'artiste est mort"),
    "non_precise": ("Lieu non précisé", "coordonnées sans type de lieu (métadonnées anciennes)"),
}
TYPE_ALIASES = {
    "création": "creation", "creation": "creation", "atelier": "creation", "made": "creation",
    "exposition": "exposition", "exhibition": "exposition", "exhibited": "exposition", "salon": "exposition",
    "conservation": "conservation", "collection": "conservation", "repository": "conservation", "musée": "conservation",
    "représenté": "represente", "represente": "represente", "depicted": "represente", "sujet": "represente",
    "naissance": "naissance_artiste", "birth": "naissance_artiste", "résidence": "residence_artiste",
    "residence": "residence_artiste", "active": "residence_artiste", "mort": "deces_artiste", "death": "deces_artiste",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS places (
    artwork_id  INTEGER NOT NULL REFERENCES artworks(id),
    type        TEXT NOT NULL,
    name        TEXT,
    lat         REAL,
    lon         REAL,
    date        TEXT,
    year        INTEGER,
    source      TEXT
);
CREATE INDEX IF NOT EXISTS places_artwork ON places(artwork_id);
"""


def ensure(conn) -> None:
    conn.executescript(SCHEMA)


def norm_type(t: str | None) -> str:
    t = (t or "").strip().lower()
    if t in PLACE_TYPES:
        return t
    if t in TYPE_ALIASES:
        return TYPE_ALIASES[t]
    raise ValueError(f"Type de lieu inconnu : « {t} » (types : {', '.join(PLACE_TYPES)})")


def _year(date: str | None) -> int | None:
    m = re.search(r"\b(1[0-9]{3}|20[0-9]{2}|[5-9][0-9]{2})\b", date or "")
    return int(m.group(1)) if m else None


def _float(v) -> float | None:
    try:
        f = float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return f


def add_place(conn, artwork_id: int, type: str, name: str | None, lat=None, lon=None,
              date: str | None = None, source: str = "", institution: bool = False) -> dict:
    """Ajoute un lieu ; complète les coordonnées par le répertoire si besoin."""
    t = norm_type(type)
    lat, lon = _float(lat), _float(lon)
    if lat is None or lon is None:
        city = gazetteer.find_institution_city(name) if institution else gazetteer.find_city(name)
        c = gazetteer.coords(city)
        if c:
            lat, lon = c
    row = {"artwork_id": int(artwork_id), "type": t, "name": (name or "").strip(), "lat": lat, "lon": lon,
           "date": (date or "").strip(), "year": _year(date), "source": source}
    conn.execute("INSERT INTO places VALUES (:artwork_id, :type, :name, :lat, :lon, :date, :year, :source)", row)
    return row


def import_places_csv(conn, path: Path, source: str = "") -> dict:
    """Importe un fichier de lieux. Renvoie {"added", "unmatched", "no_coords"}."""
    ensure(conn)
    by_path = {Path(p).resolve().as_posix(): i for i, p in conn.execute("SELECT id, path FROM artworks")}
    by_name = {Path(p).name: i for i, p in conn.execute("SELECT id, path FROM artworks")}
    added = unmatched = no_coords = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            aid = None
            if r.get("id", "").strip().isdigit():
                aid = int(r["id"])
            elif r.get("path"):
                aid = by_path.get(Path(r["path"]).resolve().as_posix()) or by_name.get(Path(r["path"]).name)
            if aid is None:
                unmatched += 1
                continue
            row = add_place(conn, aid, r.get("type", ""), r.get("place") or r.get("name"), r.get("lat"), r.get("lon"),
                            r.get("date"), r.get("source") or source, institution=norm_type(r.get("type")) == "conservation")
            added += 1
            no_coords += row["lat"] is None
    conn.commit()
    return {"added": added, "unmatched": unmatched, "no_coords": no_coords}


_BORN = re.compile(r"\bborn (?:in|at) ([^;,]+(?:, [A-Z][a-z]+)?)", re.I)
_DIED = re.compile(r"\bdied (?:in|at) ([^;,]+(?:, [A-Z][a-z]+)?)", re.I)
_NE = re.compile(r"\bn[ée]e? (?:à|a) ([^;,()]+)", re.I)
_MORT = re.compile(r"\bmort(?:e)? (?:à|a) ([^;,()]+)", re.I)


def derive_from_metadata(conn, meta: dict[int, dict[str, str]], sources: dict[tuple[int, str], str] | None = None) -> dict:
    """Déduit des lieux des métadonnées : dépôt / institution → conservation ; « born in X »,
    « died in X » (ou « né à », « mort à ») dans la notice de l'artiste → naissance / mort ;
    ``place`` ou ``lieu`` → lieu non précisé. Remplace les lieux déjà déduits (source
    commençant par « déduit »), garde ceux importés d'un fichier."""
    ensure(conn)
    conn.execute("DELETE FROM places WHERE source LIKE 'déduit%'")
    counts: dict[str, int] = {}
    for aid, m in meta.items():
        def put(t, name, date=None, inst=False, why=""):
            add_place(conn, aid, t, name, date=date, source=f"déduit : {why}", institution=inst)
            counts[t] = counts.get(t, 0) + 1
        for key in ("repository", "institution", "holding_institution", "musee", "museum"):
            if m.get(key):
                put("conservation", m[key], inst=True, why=f"métadonnée « {key} »")
                break
        artist = m.get("artist") or ""
        for rx, t, word in ((_BORN, "naissance_artiste", "born"), (_NE, "naissance_artiste", "né"),
                            (_DIED, "deces_artiste", "died"), (_MORT, "deces_artiste", "mort")):
            if (hit := rx.search(artist)) and gazetteer.find_city(hit.group(1)):
                y = re.search(r"\b(1[0-9]{3})\b", artist[hit.end(): hit.end() + 12])
                put(t, hit.group(1).strip(), date=y.group(1) if y else None, why=f"notice de l'artiste (« {word} »)")
        for key in ("place", "lieu"):
            if m.get(key):
                put("non_precise", m[key], why=f"métadonnée « {key} »")
                break
    conn.commit()
    return counts


def load_places(conn) -> list[dict]:
    ensure(conn)
    cols = ["artwork_id", "type", "name", "lat", "lon", "date", "year", "source"]
    return [dict(zip(cols, r)) for r in conn.execute(f"SELECT {', '.join(cols)} FROM places")]
