"""Selecting by name over RPC or MCP selects every object with that name.

A scene built from copies has many objects sharing a name: three booths each
with a "Headset". `select(names=["Headset"])` picked the first and left the
other two, so a delete that followed removed one of three. An id still names
exactly one object; a name names all of them.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.api import ApiError
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.rpc import RpcServer


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    monkeypatch.setenv("SERP3D_PLUGIN_DIR", str(tmp_path / "plugins"))
    window = MainWindow()
    yield RpcServer(window).api
    window.processor.cancel()
    window.mark_saved()
    window.close()
    QApplication.processEvents()


def _three_booths(api):
    for x in (0, 150, 300):
        api.scene.add(g.make_box((x, 0, 100), 18, 10, 9), name="Headset")
    return api.scene.add(g.make_box((0, 0, 0), 100, 50, 100), name="Table")


def test_a_name_selects_all_of_its_objects(api):
    _three_booths(api)
    picked = api.select(names=["Headset"])["selected"]
    assert picked == ["Headset", "Headset", "Headset"]


def test_an_id_still_selects_just_that_object(api):
    table = _three_booths(api)
    assert api.select(names=[table.id])["selected"] == ["Table"]


def test_names_and_ids_can_be_mixed_without_doubling_up(api):
    table = _three_booths(api)
    picked = api.select(names=["Headset", table.id, "Table"])["selected"]
    assert sorted(picked) == ["Headset", "Headset", "Headset", "Table"]


def test_an_unknown_name_is_still_an_error(api):
    _three_booths(api)
    with pytest.raises(ApiError, match="No object named"):
        api.select(names=["Headphones"])
