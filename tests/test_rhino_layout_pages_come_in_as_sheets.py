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
