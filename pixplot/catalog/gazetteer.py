"""Petit répertoire de lieux, embarqué : villes d'art et institutions courantes.

Sert à placer sur la carte un lieu donné par son nom (« Yale Center for British Art »,
« born in Munich ») sans appeler de service de géocodage en ligne. Coordonnées arrondies au
centre-ville (deux ou trois décimales) : assez pour une carte d'histoire de l'art, pas pour
une adresse. Un lieu absent d'ici reste sans coordonnées : on ne devine pas.
"""

from __future__ import annotations

import re
import unicodedata

# nom canonique → (latitude, longitude)
CITIES: dict[str, tuple[float, float]] = {
    "Paris": (48.857, 2.352), "London": (51.507, -0.128), "New Haven": (41.308, -72.928),
    "New York": (40.713, -74.006), "Munich": (48.137, 11.576), "Bathampton": (51.394, -2.322),
    "Amsterdam": (52.370, 4.895), "Rome": (41.903, 12.496), "Florence": (43.770, 11.256),
    "Venice": (45.441, 12.316), "Madrid": (40.417, -3.704), "Berlin": (52.520, 13.405),
    "Vienna": (48.208, 16.374), "Brussels": (50.850, 4.352), "Antwerp": (51.219, 4.402),
    "Strasbourg": (48.573, 7.752), "Lyon": (45.764, 4.836), "Marseille": (43.296, 5.370),
    "Bruges": (51.209, 3.225), "Ghent": (51.054, 3.717), "Haarlem": (52.387, 4.646),
    "Delft": (52.012, 4.357), "The Hague": (52.070, 4.300), "Utrecht": (52.091, 5.122),
    "Leiden": (52.160, 4.497), "Milan": (45.464, 9.190), "Naples": (40.852, 14.268),
    "Siena": (43.319, 11.331), "Bologna": (44.494, 11.343), "Seville": (37.389, -5.984),
    "Toledo": (39.863, -4.027), "Barcelona": (41.385, 2.173), "Lisbon": (38.722, -9.139),
    "Dresden": (51.050, 13.737), "Nuremberg": (49.454, 11.077), "Cologne": (50.938, 6.960),
    "Basel": (47.560, 7.589), "Zurich": (47.377, 8.541), "Geneva": (46.204, 6.143),
    "Prague": (50.076, 14.438), "Saint Petersburg": (59.934, 30.336), "Moscow": (55.756, 37.617),
    "Oslo": (59.914, 10.752), "Stockholm": (59.329, 18.069), "Copenhagen": (55.676, 12.568),
    "Edinburgh": (55.953, -3.188), "Dublin": (53.350, -6.260), "Bath": (51.381, -2.360),
    "Norwich": (52.630, 1.297), "Liverpool": (53.408, -2.991), "Manchester": (53.480, -2.242),
    "Bristol": (51.454, -2.588), "York": (53.960, -1.082), "Oxford": (51.752, -1.258),
    "Cambridge": (52.205, 0.119), "Boston": (42.360, -71.059), "Philadelphia": (39.953, -75.164),
    "Washington": (38.907, -77.037), "Chicago": (41.878, -87.630), "Tokyo": (35.676, 139.650),
    "Kyoto": (35.012, 135.768), "Rouen": (49.443, 1.100), "Giverny": (49.075, 1.534),
    "Arles": (43.677, 4.631), "Pont-Aven": (47.855, -3.747), "Aix-en-Provence": (43.530, 5.447),
    "Nice": (43.710, 7.262), "Colmar": (48.079, 7.358), "Bordeaux": (44.838, -0.579),
    "Toulouse": (43.605, 1.444), "Lille": (50.629, 3.057), "Montpellier": (43.611, 3.877),
    "Nantes": (47.218, -1.554), "Rennes": (48.117, -1.678), "Versailles": (48.805, 2.120),
    "Barbizon": (48.445, 2.602), "Chantilly": (49.194, 2.471), "Ajaccio": (41.919, 8.738),
}

# autres graphies → nom canonique
ALIASES: dict[str, str] = {
    "londres": "London", "munchen": "Munich", "venise": "Venice", "venezia": "Venice",
    "firenze": "Florence", "roma": "Rome", "vienne": "Vienna", "wien": "Vienna", "bruxelles": "Brussels",
    "anvers": "Antwerp", "antwerpen": "Antwerp", "brugge": "Bruges", "gand": "Ghent", "gent": "Ghent",
    "la haye": "The Hague", "den haag": "The Hague", "milano": "Milan", "napoli": "Naples",
    "sevilla": "Seville", "seville": "Seville", "tolede": "Toledo", "lisbonne": "Lisbon", "lisboa": "Lisbon",
    "koln": "Cologne", "bale": "Basel", "geneve": "Geneva", "praha": "Prague", "saint-petersbourg": "Saint Petersburg",
    "st petersburg": "Saint Petersburg", "moscou": "Moscow", "copenhague": "Copenhagen", "edimbourg": "Edinburgh",
    "philadelphie": "Philadelphia", "washington dc": "Washington", "washington, d.c.": "Washington",
    "edo": "Tokyo", "new york city": "New York", "nuremberg": "Nuremberg", "nurnberg": "Nuremberg",
}

# institution (fragment de nom, en minuscules) → ville
INSTITUTIONS: dict[str, str] = {
    "yale center for british art": "New Haven", "yale university art gallery": "New Haven",
    "musee du louvre": "Paris", "louvre": "Paris", "musee d'orsay": "Paris", "petit palais": "Paris",
    "carnavalet": "Paris", "paris musees": "Paris", "centre pompidou": "Paris", "musee rodin": "Paris",
    "metropolitan museum": "New York", "museum of modern art": "New York", "national gallery of art": "Washington",
    "national gallery": "London", "tate": "London", "british museum": "London", "victoria and albert": "London",
    "rijksmuseum": "Amsterdam", "van gogh museum": "Amsterdam", "mauritshuis": "The Hague",
    "museo del prado": "Madrid", "prado": "Madrid", "uffizi": "Florence", "galleria degli uffizi": "Florence",
    "art institute of chicago": "Chicago", "museum of fine arts, boston": "Boston", "hermitage": "Saint Petersburg",
    "kunsthistorisches museum": "Vienna", "alte pinakothek": "Munich", "gemaldegalerie": "Berlin",
    "musees de strasbourg": "Strasbourg", "musee unterlinden": "Colmar",
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().strip()
    return re.sub(r"\s+", " ", s)


_CANON = {_norm(k): k for k in CITIES}


def find_city(name: str | None) -> str | None:
    """« Munich, Germany » → « Munich » ; « Londres » → « London » ; inconnu → None."""
    if not name:
        return None
    for part in [name] + [p for p in re.split(r"[,;(]", name)]:
        key = _norm(part).strip(" .")
        if key in _CANON:
            return _CANON[key]
        if key in ALIASES:
            return ALIASES[key]
    # « Salon de Paris », « Royal Academy, London » : un nom de ville entier dans le texte ;
    # le plus long l'emporte (« New York » plutôt que « York »).
    text = _norm(name)
    hits = [(len(k), city) for k, city in list(_CANON.items()) + list(ALIASES.items())
            if re.search(rf"(?<![a-z-]){re.escape(k)}(?![a-z-])", text)]
    return max(hits)[1] if hits else None


def find_institution_city(name: str | None) -> str | None:
    if not name:
        return None
    key = _norm(name)
    for frag, city in INSTITUTIONS.items():
        if frag in key:
            return city
    return find_city(name)


def coords(city: str | None) -> tuple[float, float] | None:
    return CITIES.get(city) if city else None
