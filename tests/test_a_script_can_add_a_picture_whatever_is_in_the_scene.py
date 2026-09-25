"""A script adds a picture with the same inputs whether or not there are others.

Picture frame asks "Add/RemoveAll" only when the scene already has a picture.
A script can't see the scene, so the inputs that worked in one scene failed in
the next: sent "Add" into an empty one, the word was taken as the image path.
With no question asked, an "Add" given anyway still means add, and the command
asks for the image again. What works today works the same.
"""

from __future__ import annotations

import pytest
from PIL import Image

from serpentine3d.scripting import Document


@pytest.fixture
def image(tmp_path):
    path = tmp_path / "plan.png"
    Image.new("RGB", (40, 20), (200, 0, 0)).save(path)
    return str(path)


def _pictures(doc):
    return [o for o in doc.objects() if o.kind == "picture"]


def test_add_then_the_image_places_a_picture_in_an_empty_scene(image):
    doc = Document()
    doc.run("pictureframe", ["Add", image, "0,0,0", "40,20,0"])
    assert len(_pictures(doc)) == 1


def test_the_same_inputs_add_a_second_picture(image):
    doc = Document()
    doc.run("pictureframe", ["Add", image, "0,0,0", "40,20,0"])
    doc.run("pictureframe", ["Add", image, "50,0,0", "90,20,0"])
    assert len(_pictures(doc)) == 2


def test_the_image_alone_still_works_in_an_empty_scene(image):
    doc = Document()
    doc.run("pictureframe", [image, "0,0,0", "40,20,0"])
    assert len(_pictures(doc)) == 1


def test_remove_all_with_nothing_to_remove_is_harmless(image):
    doc = Document()
    doc.add(__import__("serpentine3d.core.geometry", fromlist=["x"]).make_box(
        (0, 0, 0), 1, 1, 1), name="Mine")
    doc.run("pictureframe", ["RemoveAll"])
    assert [o.name for o in doc.objects()] == ["Mine"]
