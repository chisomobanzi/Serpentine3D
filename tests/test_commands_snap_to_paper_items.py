"""Every paper point request uses the sheet's objects and the common snap marker."""
import pytest
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import Layout, DetailView, Leader, Hatch, LinearDim, RadialDim, AngularDim

@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Snap coverage")
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    w.viewport.resize(900, 650)
    w.viewport.layout_view.fit()
    w.viewport.grid_snap = False
    yield w, lay
    w.processor.cancel()
    w.mark_saved()
    w.close()

def only(w, kind):
    w.viewport.snaps.enabled = True
    for key in w.viewport.snaps.types:
        w.viewport.snaps.types[key] = key == kind

def hit(w, point):
    sx, sy = w.viewport.layout_view.paper_to_screen(*point[:2])
    return w.viewport.world_point_at(sx + 2, sy + 2)

def add(lay, kind):
    if kind == "detail":
        obj = DetailView(x=50, y=50, w=100, h=80)
        lay.details.append(obj)
    elif kind == "leader":
        obj = Leader(points=[[50,50], [150,50], [150,130]])
        lay.leaders.append(obj)
    elif kind == "hatch":
        obj = Hatch(points=[[50,50], [150,50], [150,130], [50,130]])
        lay.hatches.append(obj)
    else:
        obj = lay.add(g.make_polyline([(50,50,0),(150,50,0),(150,130,0),(50,130,0)], closed=True))
        kind = "object"
    return kind, obj

@pytest.mark.parametrize("command", ["move", "copy", "line", "rectangle", "detail"])
@pytest.mark.parametrize("kind", ["detail", "rectangle", "leader", "hatch"])
def test_commands_offer_end_snap_and_marker_on_paper_items(sheet, command, kind):
    w, lay = sheet
    w.viewport.layout_view.selected = [add(lay, kind)]
    w.processor.run(command)
    only(w, "end")
    assert hit(w, (50,50,0)) == pytest.approx((50,50,0))
    assert w.viewport._active_snap[1] == "end"
    w.viewport.snaps.types["end"] = False
    assert hit(w, (50,50,0)) != pytest.approx((50,50,0))
    assert w.viewport._active_snap is None

@pytest.mark.parametrize("kind,point", [("mid",(100,50,0)), ("center",(100,90,0))])
def test_detail_frame_semantics(sheet, kind, point):
    w, lay = sheet
    add(lay, "detail")
    w.processor.run("line")
    only(w, kind)
    assert hit(w, point) == pytest.approx(point)
    assert w.viewport._active_snap[1] == kind

@pytest.mark.parametrize("kind,point", [("center",(100,100,0)), ("quad",(120,100,0))])
def test_paper_circle_uses_actual_curve_features(sheet, kind, point):
    w, lay = sheet
    lay.add(g.make_circle((100,100,0),20))
    w.processor.run("line")
    only(w, kind)
    assert hit(w, point) == pytest.approx(point)
    assert w.viewport._active_snap[1] == kind

@pytest.mark.parametrize("kind,point", [("int",(90,50,0)),("perp",(80,50,0)),("near",(115,50,0))])
def test_dynamic_paper_curve_snaps(sheet, kind, point):
    w, lay = sheet
    lay.add(g.make_line((50,50,0),(150,50,0)))
    lay.add(g.make_line((90,20,0),(90,80,0)))
    w.processor.run("line")
    w.processor.provide((80,100,0))
    only(w, kind)
    if kind == "near":
        sx, sy = w.viewport.layout_view.paper_to_screen(*point[:2])
        result = w.viewport.world_point_at(sx,sy+2)
    else:
        result = hit(w, point)
    assert result == pytest.approx(point)
    assert w.viewport._active_snap[1] == kind

def test_paper_cache_tracks_move_undo_and_sheet_switch(sheet):
    w, lay = sheet
    kind, obj = add(lay,"rectangle")
    w.viewport.layout_view.selected = [(kind,obj)]
    w.processor.run("move")
    only(w,"end")
    assert hit(w,(50,50,0)) == pytest.approx((50,50,0))
    w.processor.provide((50,50,0))
    w.processor.provide((70,60,0))
    w.processor.run("line")
    assert hit(w,(70,60,0)) == pytest.approx((70,60,0))
    assert hit(w,(50,50,0)) != pytest.approx((50,50,0))
    w.processor.cancel()
    w.history.undo()
    w.processor.run("line")
    assert hit(w,(50,50,0)) == pytest.approx((50,50,0))
    w.processor.cancel()
    other=Layout(name="Empty")
    w.scene.layouts.append(other)
    w.switch_space(other.id)
    w.processor.run("line")
    hit(w,(50,50,0))
    assert w.viewport._active_snap is None

def test_paper_pending_polyline_and_point_snap(sheet):
    w, lay=sheet
    lay.add(g.make_point((50,50,0)))
    w.processor.run("line")
    only(w,"point")
    assert hit(w,(50,50,0)) == pytest.approx((50,50,0))
    only(w,"end")
    w.viewport.pending_points=[(20,20,0),(70,20,0),(70,70,0)]
    assert hit(w,(20,20,0)) == pytest.approx((20,20,0))

@pytest.mark.parametrize("command", ["rotate", "scale"])
def test_other_transforms_use_same_paper_snap_query(sheet, command):
    w, lay = sheet
    w.viewport.layout_view.selected = [add(lay,"rectangle")]
    w.processor.run(command)
    only(w,"end")
    assert w.processor.busy
    assert hit(w,(50,50,0)) == pytest.approx((50,50,0))
    assert w.viewport._active_snap[1] == "end"

@pytest.mark.parametrize("kind", ["dim", "rdim", "adim"])
def test_dimension_anchors_offer_snaps(sheet, kind):
    w, lay=sheet
    if kind == "dim":
        lay.dims.append(LinearDim(x1=50,y1=50,x2=150,y2=50))
    elif kind == "rdim":
        lay.rdims.append(RadialDim(cx=50,cy=50,px=100,py=80))
    else:
        lay.adims.append(AngularDim(vx=50,vy=50,x1=150,y1=50,x2=50,y2=150))
    w.processor.run("line")
    only(w,"end")
    assert hit(w,(50,50,0)) == pytest.approx((50,50,0))
    assert w.viewport._active_snap[1] == "end"

def test_hatch_holes_are_snap_boundaries_too(sheet):
    w, lay=sheet
    kind,hatch=add(lay,"hatch")
    hatch.holes=[[[70,70],[100,70],[100,100],[70,100]]]
    w.processor.run("line")
    only(w,"end")
    assert hit(w,(70,70,0)) == pytest.approx((70,70,0))

def test_circle_tessellation_does_not_invent_endpoints(sheet):
    w,lay=sheet
    lay.add(g.make_circle((100,100,0),20))
    w.processor.run("line")
    only(w,"end")
    hit(w,(120,100,0))
    assert w.viewport._active_snap is None

def test_detail_resize_invalidates_cached_features(sheet):
    w,lay=sheet
    kind,det=add(lay,"detail")
    w.processor.run("line")
    only(w,"end")
    assert hit(w,(150,130,0)) == pytest.approx((150,130,0))
    det.w=130
    assert hit(w,(180,130,0)) == pytest.approx((180,130,0))
    hit(w,(150,130,0))
    assert w.viewport._active_snap is None
