"""Anything driving the app from outside can tell one Interior from another.

`scene_info` is what the RPC socket, the MCP server and the AI assistant
read the layer table from, and it named a layer and nothing else. Now that
a layer can live under another one, two layers can be called Interior and
a name on its own no longer says which is which: an assistant asked to put
a wall on Walls::Interior would have had no way to pick it, and no way to
see the tree it was being asked about at all.
"""

from __future__ import annotations

from serpentine3d.api import SerpApi
from serpentine3d.app import MainWindow


def _api():
    win = MainWindow()
    win._saved_revision = win.scene.revision
    return SerpApi(win), win


def _rows(api):
    return {row["path"]: row for row in api.scene_info()["layers"]}


def _walls_and_roof(scene):
    walls = scene.layers.create("Walls")
    inner = scene.layers.create("Interior", parent=walls.id)
    roof = scene.layers.create("Roof")
    scene.layers.create("Interior", parent=roof.id)
    return walls, inner, roof


def test_a_layer_reports_the_path_it_is_known_by():
    api, win = _api()
    try:
        _walls_and_roof(win.scene)
        rows = _rows(api)
        assert "Walls::Interior" in rows and "Roof::Interior" in rows, \
            "two layers called Interior came back as one row"
        assert rows["Walls::Interior"]["name"] == "Interior", \
            "the plain name a panel would print is gone"
    finally:
        win.mark_saved()
        win.close()


def test_a_layer_reports_the_layer_it_hangs_from():
    api, win = _api()
    try:
        _walls_and_roof(win.scene)
        rows = _rows(api)
        assert rows["Walls::Interior"]["parent"] == "Walls"
        assert rows["Walls"]["parent"] is None, \
            "a layer at the top of the tree hangs from nothing"
    finally:
        win.mark_saved()
        win.close()


def test_a_layer_under_a_switched_off_parent_reports_it_is_not_shown():
    """Its own switch is one answer, whether it is on screen is another."""
    api, win = _api()
    try:
        walls, _inner, _roof = _walls_and_roof(win.scene)
        win.scene.layers.set_visible(walls.id, False)
        rows = _rows(api)
        assert rows["Walls::Interior"]["visible"] is True, \
            "the child's own switch was reported as turned off"
        assert rows["Walls::Interior"]["shown"] is False, \
            "a layer nobody can see is reported as being on screen"
        assert rows["Roof::Interior"]["shown"] is True
    finally:
        win.mark_saved()
        win.close()


# -- addressing one of them --

def test_a_layer_can_be_made_under_another_layer():
    api, win = _api()
    try:
        api.layers(action="create", name="Walls")
        api.layers(action="create", name="Interior", parent="Walls")
        assert "Walls::Interior" in _rows(api), \
            "there is no way to make a sublayer from outside the window"
    finally:
        win.mark_saved()
        win.close()


def test_a_layer_is_addressed_by_path_when_two_share_a_name():
    api, win = _api()
    try:
        _walls_and_roof(win.scene)
        api.layers(action="color", name="Roof::Interior", color=[1, 0, 0])
        rows = _rows(api)
        assert rows["Roof::Interior"]["color"][:3] == [1.0, 0.0, 0.0]
        assert rows["Walls::Interior"]["color"][:3] != [1.0, 0.0, 0.0], \
            "naming one Interior painted the other one"
    finally:
        win.mark_saved()
        win.close()


def test_a_plain_name_still_finds_the_layer_it_always_did():
    api, win = _api()
    try:
        _walls_and_roof(win.scene)
        api.layers(action="rename", name="Walls", new_name="Structure")
        assert "Structure::Interior" in _rows(api)
    finally:
        win.mark_saved()
        win.close()
