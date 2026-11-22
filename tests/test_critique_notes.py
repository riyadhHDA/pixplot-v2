"""Bilan du corpus : la note sur les artistes suit les chiffres réels (ARCHITECTURE § 34)."""
from collections import Counter

from pixplot.analysis.critique import corpus_report


def test_note_artistes_compte_les_artistes_retrouves():
    meta = {i: {"artist": "Unknown Artist" if i < 1 else f"a{i}", "style": "Baroque"} for i in range(10)}
    sources = {"artist": Counter({"huggan/wikiart (Hugging Face)": 6,
                                  "nom de fichier WikiArt (retrouvé par MMArt)": 4})}
    notes = " ".join(corpus_report(meta, sources)["notes"])
    assert "4 ont été retrouvés" in notes and "10 % des œuvres restent" in notes
