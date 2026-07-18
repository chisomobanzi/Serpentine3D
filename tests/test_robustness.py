"""Robustness: v2 container, record history, geometry fuzzing, HLR corpus."""

import json
import random
import zipfile

import pytest

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene


def test_serp_v2_container(tmp_path):
    from serpentine3d.fileio import native
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 2, 2, 2), name="Crate")
    path = str(tmp_path / "doc.serp")
    fileio.export_file(scene, path)

    assert zipfile.is_zipfile(path)
    meta = native.read_meta(path)
    assert meta["format"] == "serpentine3d" and meta["version"] == 2
    assert meta["objects"] == 1
    assert native.read_thumbnail(path) is None      # headless save

    loaded = Scene()
    fileio.import_file(loaded, path)
    assert loaded.all()[0].name == "Crate"

    # a thumbnail travels inside the container
    fileio.export_file(scene, path, thumbnail=b"\x89PNG fake")
    assert native.read_thumbnail(path) == b"\x89PNG fake"


def test_serp_v1_still_loads(tmp_path):
    from serpentine3d.fileio import native
    scene = Scene()
    scene.add(g.make_sphere((0, 0, 0), 3), name="Ball")
    v2 = str(tmp_path / "doc.serp")
    fileio.export_file(scene, v2)
    with zipfile.ZipFile(v2) as z:                  # unwrap to legacy JSON
        doc = json.loads(z.read("document.json"))
    v1 = str(tmp_path / "legacy.serp")
    with open(v1, "w") as f:
        json.dump(doc, f)
    assert native.read_meta(v1) is None             # not a container
    loaded = Scene()
    fileio.import_file(loaded, v1)
    assert loaded.all()[0].name == "Ball"


def test_record_history_regenerates_loft(env):
    scene, sel, hist, ctx, proc = env
    scene.record_history = True
    c1 = scene.add(g.make_circle((0, 0, 0), 5))
    c2 = scene.add(g.make_circle((0, 0, 10), 5))
    proc.run("loft")
    proc.click_object(c1.id)
    proc.click_object(c2.id)
    proc.finish_selection()
    loft = scene.all()[-1]
    assert scene.history_records[0]["op"] == "loft"
    assert g.bbox(loft.shape)[1][0] == pytest.approx(5, abs=0.1)

    # editing an input curve rebuilds the loft
    scene.replace_shape(c2.id, g.make_circle((0, 0, 10), 12))
    new_loft = scene.get(loft.id)
    assert new_loft.shape is not loft.shape
    assert g.bbox(new_loft.shape)[1][0] == pytest.approx(12, abs=0.2)

    # deleting a parent leaves the child alone (record simply goes stale)
    scene.remove(c1.id)
    scene.replace_shape(c2.id, g.make_circle((0, 0, 10), 6))
    assert scene.get(loft.id) is not None


def test_record_history_extrude_and_persist(env, tmp_path):
    scene, sel, hist, ctx, proc = env
    scene.record_history = True
    c = scene.add(g.make_circle((0, 0, 0), 4))
    proc.run("extrude")
    proc.click_object(c.id)
    proc.finish_selection()
    proc.provide_text("10")
    solid = scene.all()[-1]
    scene.replace_shape(c.id, g.make_circle((0, 0, 0), 8))
    import math
    assert g.volume(scene.get(solid.id).shape) == pytest.approx(
        math.pi * 64 * 10, rel=1e-3)

    path = str(tmp_path / "live.serp")
    fileio.export_file(scene, path)
    loaded = Scene()
    fileio.import_file(loaded, path)
    assert loaded.history_records            # records survive the file


def test_fuzz_random_modelling_pipeline():
    """Random primitives + transforms + booleans + roundtrip: geometry
    errors are allowed, crashes and NaNs are not."""
    rng = random.Random(20260713)
    scene = Scene()
    for i in range(40):
        kind = rng.choice(["box", "sphere", "cyl", "line", "circle"])
        x, y, z = (rng.uniform(-50, 50) for _ in range(3))
        try:
            if kind == "box":
                s = g.make_box((x, y, z), rng.uniform(1e-3, 20),
                               rng.uniform(1e-3, 20), rng.uniform(1e-3, 20))
            elif kind == "sphere":
                s = g.make_sphere((x, y, z), rng.uniform(1e-3, 15))
            elif kind == "cyl":
                s = g.make_cylinder((x, y, z), rng.uniform(1e-3, 10),
                                    rng.uniform(1e-3, 25))
            elif kind == "line":
                s = g.make_line((x, y, z), (x + rng.uniform(-9, 9),
                                            y + rng.uniform(-9, 9), z))
            else:
                s = g.make_circle((x, y, z), rng.uniform(1e-3, 12))
            op = rng.random()
            if op < 0.3:
                s = g.rotate(s, (x, y, z),
                             (rng.random() + 1e-6, rng.random(),
                              rng.random()), rng.uniform(-360, 360))
            elif op < 0.5:
                s = g.scale(s, (x, y, z), rng.uniform(0.05, 4.0))
            scene.add(s)
        except g.GeometryError:
            continue
    solids = [o for o in scene.all() if o.kind == "solid"]
    rng.shuffle(solids)
    for a, b in zip(solids[0::2], solids[1::2]):
        try:
            fused = g.boolean_union(a.shape, b.shape)
            v = g.volume(fused)
            assert v == v and v >= 0            # not NaN, not negative
            scene.replace_shape(a.id, fused)
            scene.remove(b.id)
        except g.GeometryError:
            continue
    for o in scene.all():
        mn, mx = g.bbox(o.shape)
        assert all(m == m for m in (*mn, *mx)), "NaN bbox"
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = d + "/fuzz.serp"
        fileio.export_file(scene, path)
        loaded = Scene()
        fileio.import_file(loaded, path)
        assert len(loaded.all()) == len(scene.all())


def test_hlr_survives_degenerate_inputs():
    """The isolated HLR worker returns (possibly empty) results for the
    crash corpus and keeps serving afterwards."""
    from serpentine3d.core import hlr
    corpus = []
    # planar circle seen exactly edge-on (the classic OCCT killer)
    corpus.append(([g.make_circle((0, 0, 0), 5)], (1, 0, 0), (0, 1, 0)))
    # a bare line along the view direction
    corpus.append(([g.make_line((0, 0, 0), (0, 0, 10))], (0, 0, 1),
                   (1, 0, 0)))
    # tiny sliver box
    corpus.append(([g.make_box((0, 0, 0), 1e-4, 20, 20)], (0, 0, 1),
                   (1, 0, 0)))
    for shapes, view_dir, x_dir in corpus:
        res = hlr.hlr_project_safe(shapes, origin=(0, 0, 0),
                                   view_dir=view_dir, x_dir=x_dir)
        assert isinstance(res, dict)
        assert set(res) >= {"visible", "hidden", "outline"}
    # worker still alive for a normal request afterwards
    res = hlr.hlr_project_safe([g.make_box((0, 0, 0), 5, 5, 5)],
                               origin=(0, 0, 0), view_dir=(0, 0, 1),
                               x_dir=(1, 0, 0))
    assert len(res["visible"]) + len(res["outline"]) > 0


def test_plugin_loading(tmp_path, monkeypatch, env):
    scene, sel, hist, ctx, proc = env
    plug = tmp_path / "hello_plugin.py"
    plug.write_text(
        "def serpentine3d_plugin(ctx):\n"
        "    @ctx.command('helloplugin', mutates=False)\n"
        "    def cmd_hello(c):\n"
        "        c.echo('plugin says hello ' + ctx.version)\n"
        "        yield from ()\n")
    monkeypatch.setenv("SERP3D_PLUGIN_DIR", str(tmp_path))
    from serpentine3d import plugins
    monkeypatch.setattr(plugins, "_loaded", [])
    names = plugins.load_plugins()
    assert "hello_plugin" in names

    echoes = []
    ctx.add_echo_listener(echoes.append)
    proc.run("helloplugin")
    from serpentine3d import __version__
    assert any(f"plugin says hello {__version__}" in e for e in echoes)
    # loading again is a no-op
    assert plugins.load_plugins() == []
