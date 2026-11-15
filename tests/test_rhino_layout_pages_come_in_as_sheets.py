"""A Rhino file's layout pages come in as sheets, not into the model.

Rhino keeps a layout's title block, notes, dimensions and detail viewports
in page space, in paper millimetres. The import never looked, so every
Rhino file with layouts had its sheets piled into the model at paper
coordinates: a film set of 714 model objects came in as more than 10,000.

tests/data/rhino_layout_page.3dm is McNeel's openNURBS
V5/v5_example_file.3dm (see OPENNURBS-LICENSE.txt), 30 model objects and a
Letter page "Page 1" with a top-view detail and four leaders, with a line,
a polyline, text, a hatch and a dimension added on the page
(tests/data/make_rhino_layout_page.py).
"""

from pathlib import Path

import pytest

from serpentine3d.fileio import rhino

DATA = Path(__file__).parent / "data"
PAGED = str(DATA / "rhino_layout_page.3dm")
# what the 30 model objects convert to: three are kinds the import skips
MODEL_ITEMS = 27


def test_page_objects_stay_out_of_the_model():
    items = rhino.import_3dm(PAGED)
    assert len(items) == MODEL_ITEMS


def test_page_objects_stay_out_of_the_model_read_in_parallel():
    from serpentine3d.fileio import rhino_parallel as rp
    items = rp.import_3dm_parallel(PAGED, workers=2)
    assert len(items) == MODEL_ITEMS


# -- the sheets -----------------------------------------------------------------

import math  # noqa: E402
import struct  # noqa: E402
import uuid  # noqa: E402


def _pages(units="mm", parallel=False):
    pages = []
    if parallel:
        from serpentine3d.fileio import rhino_parallel as rp
        rp.import_3dm_parallel(PAGED, workers=2, units=units, pages=pages)
    else:
        rhino.import_3dm(PAGED, units=units, pages=pages)
    return pages


def test_a_page_becomes_a_sheet_named_after_it_on_paper_that_holds_it():
    (sheet,) = _pages()
    assert sheet.name == "Page 1"
    assert (sheet.paper_w, sheet.paper_h) == \
        pytest.approx((215.9, 279.4)), "Letter, upright, holds it"


def test_its_detail_looks_where_rhino_s_does():
    """Rhino's top view of the model: 159.9 model mm across a 195.9 mm
    window, centred on (22.74, 6.65)."""
    (sheet,) = _pages()
    (det,) = sheet.details
    assert (det.x, det.y, det.w, det.h) == \
        pytest.approx((10.0, 10.0, 195.9, 259.4), abs=0.05)
    assert det.scale_denom == pytest.approx(159.925 / 195.9, rel=1e-3)
    assert det.azimuth == pytest.approx(math.radians(-90))
    assert det.elevation == pytest.approx(math.radians(89.9))
    assert det.target[:2] == pytest.approx([22.7371, 6.65206], abs=1e-3)
    assert not det.perspective


def test_its_text_leaders_linework_hatch_and_dimension_come_with_it():
    (sheet,) = _pages()
    (note,) = sheet.notes
    assert note.text == "Hello World"
    assert (note.x, note.y) == pytest.approx((155.0, 25.0), abs=0.01)
    assert sorted(ld.text for ld in sheet.leaders) == \
        ["Breps", "Curves", "Meshes", "Points"]
    breps = next(ld for ld in sheet.leaders if ld.text == "Breps")
    assert breps.points[0] == pytest.approx([140.76, 81.9], abs=0.01), \
        "the arrow at Rhino's first point"
    assert len(sheet.objects) == 2, "the border line and the title box"
    red = next(o for o in sheet.objects if o.color is not None)
    assert red.color == pytest.approx((1.0, 0.0, 0.0))
    (hatch,) = sheet.hatches
    xs, ys = zip(*hatch.points)
    assert (min(xs), min(ys), max(xs), max(ys)) == \
        pytest.approx((40.0, 220.0, 60.0, 240.0), abs=0.05)
    (dim,) = sheet.dims
    assert math.dist((dim.x1, dim.y1), (dim.x2, dim.y2)) == \
        pytest.approx(40.0, abs=1e-6)
    assert dim.measures_paper, "drawn on bare paper, not through the detail"
    assert dim.text == "40.00"


def test_the_detail_is_in_the_scene_s_units():
    (sheet,) = _pages(units="m")
    (det,) = sheet.details
    assert det.scale_denom == pytest.approx(159.925 / 195.9 / 1000, rel=1e-3)
    assert det.target[:2] == pytest.approx([0.0227371, 0.00665206], abs=1e-6)
    assert sheet.paper_w == pytest.approx(215.9), "paper stays millimetres"


def test_the_parallel_reader_brings_the_same_sheets():
    (serial,) = _pages()
    (parallel,) = _pages(parallel=True)
    assert parallel.name == serial.name
    assert [len(getattr(parallel, k)) for k in
            ("details", "notes", "leaders", "objects", "hatches", "dims")] \
        == [len(getattr(serial, k)) for k in
            ("details", "notes", "leaders", "objects", "hatches", "dims")]


def test_a_page_dimension_measured_through_a_detail_reads_its_scale():
    """A page dimension Rhino measured through a detail carries that
    detail's id and then the detail's scale, which is what its number is
    multiplied by. rhino3dm has no word for it, so it is read from the
    object's bytes."""
    from serpentine3d.fileio.rhino_pages import measured_through
    detail = uuid.uuid4()
    data = b"\x00" * 40 + detail.bytes_le + struct.pack("<d", 25.0) + \
        b"\x00" * 24
    assert measured_through(data, {str(detail): "d1"}) == ("d1", 25.0)
    assert measured_through(data, {str(uuid.uuid4()): "d2"}) is None


def test_import_puts_the_sheets_in_the_drawing_and_says_so():
    from serpentine3d import fileio
    from serpentine3d.core.scene import Scene
    scene, notes = Scene(), []
    fileio.import_file(scene, PAGED, notes=notes)
    assert [lay.name for lay in scene.layouts] == ["Page 1"]
    assert any("sheet" in note for note in notes)
    assert len(scene.all()) == MODEL_ITEMS


def test_paper_is_the_page_s_own_size_whatever_lies_off_it(tmp_path):
    """Rhino users park notes off the paper, so what lies on a page says
    little about its size. The page's own size is in the file's view
    settings, which rhino3dm does not offer, so it is read from there:
    with a note parked far off it, Page 1 is still Letter."""
    import rhino3dm as r3
    model = r3.File3dm.Read(PAGED)
    page = next(v for v in model.Views if v.Name == "Page 1")
    attrs = r3.ObjectAttributes()
    attrs.ActiveSpace = r3.ActiveSpace.PageSpace
    attrs.ViewportId = page.Viewport.Id
    model.Objects.AddLine(r3.Point3d(-300, -400, 0), r3.Point3d(900, 50, 0),
                          attrs)
    path = str(tmp_path / "parked.3dm")
    assert model.Write(path, 7)
    pages = []
    rhino.import_3dm(path, pages=pages)
    (sheet,) = pages
    assert (sheet.paper_w, sheet.paper_h) == pytest.approx((215.9, 279.4))


def test_a_title_block_s_fields_are_filled_in():
    """Rhino draws %<pagename>% as the page's name and %<DocumentText(...)>%
    from the file's document user text; rhino3dm hands over the formula."""
    from serpentine3d.fileio.rhino_pages import fill_fields
    doc = {"_SetNameShort": "INT_SAM_CAVE", "_ProdDesigner": "C. H."}
    assert fill_fields('%<documenttext("_SetNameShort")>% | %<pagename>%',
                       "ELEVATIONS", doc) == "INT_SAM_CAVE | ELEVATIONS"
    assert fill_fields('%<DocumentText("_prodDESIGNER")>%', "P", doc) == \
        "C. H.", "names are matched as Rhino does, whatever their case"
    assert fill_fields("%<PageName()>%", "Page 1", {}) == "Page 1"
    unknown = '%<Date("yyyy")>% %<DocumentText("_Missing")>%'
    assert fill_fields(unknown, "P", doc) == unknown, \
        "what cannot be worked out is left as written"
