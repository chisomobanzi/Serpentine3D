"""The physical sheet is a snap target for every paper point request."""
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, detail_unproject
from tests.test_commands_snap_to_paper_items import sheet, only, hit, add


@pytest.mark.parametrize("command", ["move", "line", "detail"])
@pytest.mark.parametrize("corner", [(0, 0), (1, 0), (1, 1), (0, 1)])
def test_commands_snap_to_physical_page_corners_with_live_marker(sheet, command, corner):
    w, lay = sheet
    if command == "move":
        w.viewport.layout_view.selected = [add(lay, "rectangle")]
    w.processor.run(command)
    only(w, "end")
    point = (corner[0] * lay.paper_w, corner[1] * lay.paper_h, 0)
    assert hit(w, point) == pytest.approx(point)
    assert w.viewport._active_snap[1] == "end"

    w.viewport.snaps.types["end"] = False
    assert hit(w, point) != pytest.approx(point)
    assert w.viewport._active_snap is None
    only(w, "end")
    w.viewport.snaps.enabled = False
    assert hit(w, point) != pytest.approx(point)
    assert w.viewport._active_snap is None


@pytest.mark.parametrize("kind,fraction", [
    ("mid", (0.5, 0)), ("mid", (1, 0.5)),
    ("mid", (0.5, 1)), ("mid", (0, 0.5)), ("center", (0.5, 0.5)),
])
def test_empty_page_has_midpoints_and_center(sheet, kind, fraction):
    w, lay = sheet
    w.processor.run("line")
    only(w, kind)
    point = (fraction[0] * lay.paper_w, fraction[1] * lay.paper_h, 0)
    assert hit(w, point) == pytest.approx(point)
    assert w.viewport._active_snap[1] == kind
    assert lay.is_empty(), "Snapping must not add actual geometry to the sheet"


@pytest.mark.parametrize("kind", ["near", "perp"])
@pytest.mark.parametrize("edge", ["bottom", "right", "top", "left"])
def test_page_edges_support_nearest_and_perpendicular_snaps(sheet, kind, edge):
    w, lay = sheet
    w.processor.run("line")
    base = (83, 67, 0)
    w.processor.provide(base)
    only(w, kind)
    point = {
        "bottom": (base[0], 0, 0), "top": (base[0], lay.paper_h, 0),
        "left": (0, base[1], 0), "right": (lay.paper_w, base[1], 0),
    }[edge]
    sx, sy = w.viewport.layout_view.paper_to_screen(*point[:2])
    if edge in ("bottom", "top"):
        sy += 2
    else:
        sx += 2
    assert w.viewport.world_point_at(sx, sy) == pytest.approx(point)
    assert w.viewport._active_snap[1] == kind


def test_page_resize_refreshes_snap_targets_without_restarting_command(sheet):
    w, lay = sheet
    w.processor.run("line")
    only(w, "end")
    old_corner = (lay.paper_w, lay.paper_h, 0)
    assert hit(w, old_corner) == pytest.approx(old_corner)
    lay.paper_w, lay.paper_h = 300, 210
    new_corner = (lay.paper_w, lay.paper_h, 0)
    assert hit(w, new_corner) == pytest.approx(new_corner)
    assert w.viewport._active_snap[1] == "end"
    assert hit(w, old_corner) != pytest.approx(old_corner)
    assert w.viewport._active_snap is None


def test_entered_detail_uses_model_snaps_even_at_a_page_corner(sheet):
    w, lay = sheet
    detail = DetailView(x=-20, y=-20, w=100, h=100, scale_denom=2,
                        target=[400, 250, 0])
    lay.details.append(detail)
    model_end = tuple(detail_unproject(detail, 0, 0))
    w.scene.add(g.make_line(model_end, (model_end[0] + 30, model_end[1], model_end[2])))
    w.viewport.layout_view.entered_detail = detail.id
    w.processor.run("line")
    only(w, "end")
    assert hit(w, (0, 0, 0)) == pytest.approx(model_end)
    assert model_end != pytest.approx((0, 0, 0))
    assert w.viewport._active_snap[1] == "end"
