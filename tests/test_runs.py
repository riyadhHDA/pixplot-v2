from pixplot.runs import Run, create_run, latest_run, list_runs


def test_run_lifecycle(tmp_path):
    a = create_run("features", "dinov3_vitb16", {"size": 448}, runs_dir=tmp_path)
    assert a.manifest["status"] == "running"
    assert list_runs("features", runs_dir=tmp_path) == []  # pas encore terminé

    a.complete(count=10)
    b = create_run("features", "dinov3_vitb16", runs_dir=tmp_path)  # même seconde : pas d'écrasement
    assert a.path != b.path
    b.fail("boom")

    reloaded = Run.load(a.path)
    assert reloaded.manifest["outputs"] == {"count": 10}
    assert latest_run("features", runs_dir=tmp_path).path == a.path


def test_parent_link(tmp_path):
    a = create_run("features", "x", runs_dir=tmp_path)
    b = create_run("index", "global", parent=a, runs_dir=tmp_path)
    assert b.manifest["parent"] == a.id
