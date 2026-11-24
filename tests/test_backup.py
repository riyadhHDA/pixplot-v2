"""pixplot sauvegarde : mettre à l'abri le travail fait à la main et copier le dossier de données."""

import json
import sqlite3

import pytest

from pixplot import backup
from pixplot.notebook import Notebook


def _data(tmp_path, rows=3):
    d = tmp_path / "moncorpus"
    (d / "bench").mkdir(parents=True)
    lines = ["a,b,type,status,source,note"] + [f"{i},{i + 1},meme_sujet,validée,test," for i in range(rows)]
    (d / "bench" / "pairs.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (d / "bench" / "review_log.csv").write_text("a,b,verdict\n1,2,pas de lien\n", encoding="utf-8")
    Notebook(d / "notebook.sqlite").add("Une piste", note="Van Gogh d'après Millet", artwork_ids=[1, 2])
    sqlite3.connect(d / "catalog.sqlite").execute("CREATE TABLE t (x)").connection.commit()
    (d / "runs").mkdir()
    (d / "runs" / "gros.npy").write_bytes(b"0" * 100)
    return d


def test_vers_le_depot_et_refus(tmp_path):
    d = _data(tmp_path)
    bench = tmp_path / "depot" / "bench"
    rep = {e["cible"].split("\\")[-1].split("/")[-1]: e for e in backup.to_repo(d, bench, "moncorpus")}
    assert rep["moncorpus_pairs_travail.csv"]["état"] == "copié" and rep["moncorpus_pairs_travail.csv"]["lignes_source"] == 3
    assert (bench / "moncorpus_review_log.csv").exists()
    assert not (bench / "moncorpus_notebook.json").exists()          # carnet seulement sur demande
    assert all(e["état"] == "identique" for e in backup.to_repo(d, bench, "moncorpus"))
    # un dossier de données qui a perdu des lignes n'écrase pas la copie du dépôt…
    (d / "bench" / "pairs.csv").write_text("a,b,type,status,source,note\n1,2,x,validée,,\n", encoding="utf-8")
    r = backup.to_repo(d, bench, "moncorpus")[0]
    assert r["état"].startswith("refusé") and len((bench / "moncorpus_pairs_travail.csv").read_text().splitlines()) == 4
    # … sauf demande expresse
    assert backup.to_repo(d, bench, "moncorpus", force=True)[0]["état"] == "copié"


def test_carnet_en_json(tmp_path):
    d = _data(tmp_path)
    bench = tmp_path / "depot" / "bench"
    rep = backup.to_repo(d, bench, "moncorpus", notebook=True)
    assert rep[-1]["état"] == "copié"
    entries = json.loads((bench / "moncorpus_notebook.json").read_text(encoding="utf-8"))
    assert entries[0]["title"] == "Une piste" and entries[0]["artwork_ids"] == [1, 2]


def test_copie_vers_un_autre_disque(tmp_path):
    d = _data(tmp_path)
    target = tmp_path / "disque" / "pixplot"
    out = backup.mirror(d, target)
    assert out["copiés"] == 4 and not (target / "runs").exists()      # catalogue, carnet, bench/ (2 fichiers)
    assert sqlite3.connect(target / "catalog.sqlite").execute("SELECT count(*) FROM t").fetchone() == (0,)
    (target / "a_garder.txt").write_text("rien n'est effacé", encoding="utf-8")
    again = backup.mirror(d, target)
    assert again["copiés"] == 0 and again["inchangés"] == 4 and (target / "a_garder.txt").exists()
    assert backup.mirror(d, target, everything=True)["copiés"] == 1     # runs/gros.npy en plus
    assert json.loads((target / "sauvegarde.json").read_text(encoding="utf-8"))["mode"] == "tout"
    with pytest.raises(ValueError):
        backup.mirror(d, d / "sauvegarde")


def test_commande(tmp_path, capsys):
    from pixplot.cli import main

    d = _data(tmp_path)
    assert main(["--data", str(d), "sauvegarde", "--sans-depot", "--vers", str(tmp_path / "copie")]) == 0
    assert (tmp_path / "copie" / "bench" / "pairs.csv").exists()
    assert "Rien n'est jamais effacé" in capsys.readouterr().out
