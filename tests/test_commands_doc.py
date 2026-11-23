"""La référence des commandes (`docs/COMMANDS.fr.md` / `.md`) suit le code : chaque commande de
`pixplot` y figure, dans les deux langues, et aucune commande décrite n'a disparu (condition de la
1.0 : des commandes stables et documentées)."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from pixplot.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "docs" / "COMMANDS.fr.md", ROOT / "docs" / "COMMANDS.md"]


def _commands() -> set[str]:
    """Commandes du parseur ; pour `pairs`, chaque action (`pairs bench`…) compte à part."""
    parser = build_parser()
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    out: set[str] = set()
    for name, sp in sub.choices.items():
        action = next((a for a in sp._actions if a.dest == "action" and a.choices), None)
        out |= {f"{name} {c}" for c in action.choices} if action else {name}
    return out


def _documented(path: Path) -> set[str]:
    """Commandes écrites `pixplot …` en tête d'une ligne de tableau."""
    found = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^\| `pixplot ([a-z-]+(?: [a-z]+)?)`", line)
        if m:
            found.add(m.group(1))
    return found


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_chaque_commande_est_documentee(doc):
    manque = _commands() - _documented(doc)
    assert not manque, f"{doc.name} : commandes sans description : {sorted(manque)}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_aucune_commande_disparue(doc):
    disparues = _documented(doc) - _commands() - {"--version"}
    assert not disparues, f"{doc.name} : commandes décrites mais absentes du code : {sorted(disparues)}"
