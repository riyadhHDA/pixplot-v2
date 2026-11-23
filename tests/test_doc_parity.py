"""Chaque document existe en français (`X.fr.md`) et en anglais (`X.md`), au même niveau : mêmes
titres, et dans chaque section autant de blocs de code et de tableaux (condition de la 1.0 :
« documentation complète dans les deux langues »). Un test ne juge pas la traduction ; il attrape
une section oubliée dans l'une des deux langues."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README", "ARCHITECTURE", "ROADMAP", "CHANGELOG", "docs/MCP", "docs/INSTALL_GPU", "docs/FORMATS",
        "docs/COMMANDS"]


def _sections(path: Path) -> list[tuple[str, int, int]]:
    """(titre, blocs de code, lignes de séparation de tableau) pour chaque titre ``##``."""
    out: list[list] = [["(début)", 0, 0]]
    fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fence = not fence
            out[-1][1] += int(fence)
            continue
        if fence:
            continue
        if line.startswith("## "):
            out.append([line, 0, 0])
        elif re.match(r"^\|\s*:?-{3,}", line):
            out[-1][2] += 1
    return [tuple(x) for x in out]


@pytest.mark.parametrize("doc", DOCS)
def test_meme_structure_dans_les_deux_langues(doc):
    fr, en = ROOT / f"{doc}.fr.md", ROOT / f"{doc}.md"
    assert fr.exists() and en.exists(), doc
    a, b = _sections(fr), _sections(en)
    assert len(a) == len(b), f"{doc} : {len(a)} sections en français, {len(b)} en anglais"
    for (ta, ca, ka), (tb, cb, kb) in zip(a, b):
        assert ca == cb, f"{doc} « {ta} » / « {tb} » : {ca} blocs de code en français, {cb} en anglais"
        assert ka == kb, f"{doc} « {ta} » / « {tb} » : {ka} tableaux en français, {kb} en anglais"


@pytest.mark.parametrize("doc", DOCS)
def test_pas_de_renvoi_a_l_autre_langue(doc):
    en = (ROOT / f"{doc}.md").read_text(encoding="utf-8").lower()
    fr = (ROOT / f"{doc}.fr.md").read_text(encoding="utf-8").lower()
    assert "see the french version" not in en and "voir la version anglaise" not in fr
