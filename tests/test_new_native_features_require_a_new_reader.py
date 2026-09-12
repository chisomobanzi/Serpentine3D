"""Older releases must reject new picture/text data instead of losing it."""
import json
import zipfile
import pytest
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.layout import Layout, TextNote
from serpentine3d.core.picture import PictureShape
from serpentine3d.fileio import native
from tests.test_model_text_stays_editable import typography, _text

@pytest.mark.parametrize("kind", ["model_text", "paper_text", "model_picture", "paper_picture"])
def test_new_content_names_the_first_safe_reader(tmp_path, typography, monkeypatch, kind):
    scene=Scene()
    if kind.endswith("text"):
        shape=_text(typography)
    else:
        shape=PictureShape(dict(origin=[0,0,0],u=[10,0,0],v=[0,10,0],path="reference.png"))
    if kind.startswith("model"):
        scene.add(shape)
    else:
        lay=Layout();scene.layouts.append(lay)
        if kind=="paper_text":
            lay.notes.append(TextNote(text="Title",font_family=typography[0],font_style=typography[2]))
        else:
            lay.add(shape)
    path=tmp_path/"drawing.serp"
    native.save_scene(scene,str(path))
    with zipfile.ZipFile(path) as z:
        doc=json.loads(z.read("document.json"))
    assert doc["version"]==4
    assert doc["requires"]=="0.10.0"
    reopened=Scene();native.load_scene(reopened,str(path))
    assert bool(reopened.all() or reopened.layouts)
    monkeypatch.setattr(native,"FORMAT_VERSION",3)
    existing=Scene();obj=existing.add(g.make_box((0,0,0),1,1,1))
    with pytest.raises(ValueError,match="0.10.0"):
        native.load_scene(existing,str(path))
    assert existing.get(obj.id) is obj
