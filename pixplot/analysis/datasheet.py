"""Fiche de données du corpus, sur le modèle des *Datasheets for Datasets* (T. Gebru et al.,
Communications of the ACM 64(12), 2021) : d'où viennent les images et les étiquettes, ce que le
corpus contient et ce qui lui manque, les droits connus, ce qu'on peut en faire et ce qu'il ne faut
pas en tirer.

La fiche est **calculée** à partir du catalogue et des runs (rien n'est écrit à la main pour un
corpus donné), sauf les notes sur les sources connues (``SOURCE_RIGHTS``), qui disent ce que l'on
sait de leurs droits. Elle accompagne chaque Research Pack (``datasheet.md``) et s'écrit avec
``pixplot corpus --datasheet``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .. import __version__
from . import critique

# Ce que l'on sait des droits de chaque source (clé : morceau du nom de source, en minuscules).
# Prudence : une ligne dit ce qui est établi et renvoie à la vérification, jamais plus.
SOURCE_RIGHTS: list[tuple[str, str]] = [
    ("retrouvé par mmart", "Comme WikiArt (le nom de fichier vient de WikiArt.org) ; le rattachement passe "
                           "par MMArt, CC BY 4.0."),
    ("huggan/wikiart", "Images et étiquettes de WikiArt.org, reprises par le jeu Hugging Face "
                       "huggan/wikiart. Les droits d'auteur des images dépendent de chaque œuvre : beaucoup "
                       "d'artistes du XXe siècle sont encore protégés. Usage d'étude et de recherche ; ne pas "
                       "rediffuser les images."),
    ("mmart", "MMArt (Wang et al., 2026), licence CC BY 4.0 : titres, dates et noms de fichier, rattachés "
              "par empreinte d'image. Ses descriptions, écrites par un modèle de langage, ne servent pas de source."),
    ("artemis", "ArtEmis (Achlioptas et al., 2021), obtenu auprès des auteurs : usage de recherche non "
                "commercial, gardé en local."),
    ("iiif", "Notice et image d'un musée, par son manifeste IIIF : la licence est indiquée par chaque "
             "manifeste, à vérifier avant toute diffusion."),
]

USES_OK = [
    "explorer un corpus et formuler des hypothèses à vérifier sur les œuvres et dans la littérature ;",
    "retrouver des œuvres proches, des reprises, des doublons, des étiquettes à vérifier ;",
    "comparer ce que voient plusieurs modèles (les « regards ») sur les mêmes œuvres.",
]
USES_NOT = [
    "conclure à une influence, une attribution ou une datation à partir d'une proximité calculée : "
    "c'est une piste, pas une preuve ;",
    "tirer des statistiques sur « l'histoire de l'art » : le corpus reflète les choix de WikiArt et de "
    "ses contributeurs, pas l'ensemble des œuvres ;",
    "rediffuser les images, ou entraîner un modèle commercial sur ce corpus.",
]


def rights_note(source: str) -> str:
    s = (source or "").lower()
    for key, note in SOURCE_RIGHTS:
        if key in s:
            return note
    return ""


def _pct(x: float) -> str:
    return "< 1 %" if 0 < x < 0.005 else f"{round(x * 100)} %"


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def build(data, now: datetime | None = None) -> str:
    """Fiche de données (Markdown, en français) du corpus chargé dans ``data`` (``AtlasData``)."""
    now = now or datetime.now(timezone.utc)
    report = data.corpus_report()
    n = report["n"]
    name = data.settings.data_dir.name
    lines = [f"# Fiche de données — corpus « {name} »", "",
             f"Calculée par PixPlot v2 {__version__} le {now:%d/%m/%Y}, d'après le catalogue et les runs, "
             "sur le modèle des « Datasheets for Datasets » (Gebru et al., 2021).", ""]

    # 1. Identité
    feats = data.features.manifest.get("params", {})
    conn = data._conn(data.settings)
    status = dict(conn.execute("SELECT status, COUNT(*) FROM artworks GROUP BY status").fetchall())
    conn.close()
    total = sum(status.values())
    lines += ["## 1. Ce qu'est ce corpus", "",
              f"- **{_num(n)} œuvres** dans l'analyse `{data.analysis.id}`."]
    if total > n:
        why = {"duplicate": "copies exactes d'un autre fichier", "error": "illisibles"}
        parts = ", ".join(f"{_num(c)} {why.get(st, st)}" for st, c in sorted(status.items()) if st != "ok")
        lines.append(f"- Le catalogue compte {_num(total)} images ; écartées à l'import : {parts}. "
                     "Les comptes d'étiquettes par source (section 2) portent sur tout le catalogue.")
    lines += [
              f"- Regard principal : `{feats.get('encoder')}`, run `{data.features.id}`.",
              "- Une œuvre = une reproduction numérique (une image), pas l'objet matériel.", ""]

    # 2. Provenance et droits
    sources: dict[str, dict[str, int]] = {}
    for key, c in report["coverage"].items():
        for s in c["sources"]:
            sources.setdefault(s["source"], {})[critique.KEY_LABELS.get(key, key)] = s["count"]
    lines += ["## 2. D'où viennent les images et les étiquettes", ""]
    if sources:
        lines += ["| Source | Étiquettes fournies (œuvres) | Ce que l'on en sait | Droits connus |", "|---|---|---|---|"]
        for src, keys in sorted(sources.items(), key=lambda kv: -max(kv[1].values())):
            given = ", ".join(f"{k} ({_num(v)})" for k, v in sorted(keys.items(), key=lambda kv: -kv[1]))
            lines.append(f"| {src} | {given} | {critique.source_note(src) or '—'} | {rights_note(src) or 'à vérifier'} |")
    else:
        lines.append("Aucune étiquette importée : seules les images sont connues.")
    lines += ["", "Les étiquettes sont des **données saisies par d'autres** : des propositions à vérifier, "
              "jamais des consignes ni des vérités.", ""]

    # 3. Composition
    lines += ["## 3. Ce qu'il contient", "", "| Étiquette | Œuvres renseignées | Valeurs distinctes | Les plus fréquentes |",
              "|---|---|---|---|"]
    for key, c in report["coverage"].items():
        top = ("— (une valeur par œuvre)" if c["distinct"] >= 0.9 * max(c["known"], 1)
               else ", ".join(f"{t['value']} ({_pct(t['share'])})" for t in c["top"][:3]))
        lines.append(f"| {critique.KEY_LABELS.get(key, key)} | {_num(c['known'])} ({_pct(c['share'])}) | "
                     f"{_num(c['distinct'])} | {top} |")
    if report.get("centuries"):
        cent = ", ".join(f"{c['century']}e s. : {_num(c['count'])}" for c in report["centuries"])
        lines += ["", f"Œuvres datées par siècle : {cent}."]
    lines += [""]

    # 4. Manques et déséquilibres
    lines += ["## 4. Ce qui lui manque, ce qui le déséquilibre", ""] + [f"- {x}" for x in report["notes"]] + [""]

    # 5. Ce que PixPlot a repéré dans le catalogue
    dup = (data._duplicates() or {}).get("counts", {})
    sus = (data.suspects or {}).get("counts", {})
    found = []
    if dup:
        found.append(f"{_num(dup.get('same', 0))} paires d'images entrées deux fois et {_num(dup.get('variant', 0))} "
                     "variantes proches (répliques, séries, copies) : `pixplot doublons`.")
    if sus:
        found.append("Étiquettes que toutes les voisines contredisent : "
                     + ", ".join(f"{critique.KEY_LABELS.get(k, k)} {_num(v)}" for k, v in sus.items())
                     + " (erreurs possibles ou œuvres singulières) : `pixplot suspects`.")
    info = data.notions_info() if hasattr(data, "notions_info") else None
    if info and info.get("framed"):
        found.append(f"{_num(info['framed']['count'])} reproductions photographiées avec leur cadre "
                     f"(notion n° {info['framed']['feature']}, ARCHITECTURE § 37).")
    if found:
        lines += ["## 5. Ce que PixPlot y a repéré", ""] + [f"- {x}" for x in found] + [""]

    # 6. Regards
    lines += ["## 6. Les modèles qui le lisent (« regards »)", ""]
    for sp in data.spaces.list():
        card = sp.get("card") or {}
        trained = card.get("trained_on", "?")
        lines.append(f"- **{sp.get('label')}** : {card.get('model', sp.get('encoder'))}"
                     + ("." if trained.startswith("rien") else f". Apprentissage : {trained}."))
    lines += ["", "Chaque regard a ses biais (panneau « Corpus » de l'Atlas, `pixplot corpus`) : lire le corpus "
              "par un modèle, c'est aussi lire le modèle par le corpus.", ""]

    # 7. Usages
    lines += ["## 7. Ce qu'on peut en faire", ""] + [f"- {x}" for x in USES_OK]
    lines += ["", "## 8. Ce qu'il ne faut pas en tirer", ""] + [f"- {x}" for x in USES_NOT] + [""]

    # 9. Mise à jour
    lines += ["## 9. Mise à jour", "",
              "Cette fiche est recalculée à chaque Research Pack et par `pixplot corpus --datasheet`. "
              "Toute nouvelle importation d'étiquettes ou correction du catalogue la change.", ""]
    return "\n".join(lines)
