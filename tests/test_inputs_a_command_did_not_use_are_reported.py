"""Inputs a command never asked for are an error, not a silent success (#103).

With a layout active, `exportpdf` skips its "Layout to export" prompt, so a
script that sent ["Seat blank", "C:/work/seat.pdf"] had the sheet name answer
the PDF path. The real path was dropped without a word and the reply said
"Exported 1 sheet(s)" to a file nobody asked for. Too few inputs already
raised "Command needs more input"; too many now raises too, naming what was
left over, which prompt each used input answered, and what the command did,
because its result stands and a blind retry would do it twice.
"""

import pytest

from serpentine3d.core.layout import Layout
from serpentine3d.scripting import Document


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.processor.cancel()
    w.mark_saved()
    w.close()


def test_a_path_the_export_never_asked_for_is_reported(window, monkeypatch,
                                                         tmp_path):
    from serpentine3d.api import ApiError, SerpApi
    from serpentine3d.fileio import pdf

    written = []
    monkeypatch.setattr(pdf, "export_layouts_pdf",
                        lambda win, layouts, path: written.append(path))
    monkeypatch.chdir(tmp_path)
    lay = Layout(name="Seat blank")
    window.scene.layouts.append(lay)
    window.scene.notify()
    window.switch_space(lay.id)
    wanted = str(tmp_path / "work" / "seat.pdf")

    with pytest.raises(ApiError) as caught:
        SerpApi(window).command("exportpdf", ["Seat blank", wanted])

    message = str(caught.value)
    assert repr(wanted) in message, "The dropped input must be named"
    assert "PDF path" in message and "'Seat blank'" in message, \
        "Say which prompt the sheet name answered, or the mix-up stays hidden"
    assert "Seat blank.pdf" in message, \
        "The export did run, so say what it wrote"
    assert written == [str(tmp_path / "Seat blank.pdf")]
    assert not window.processor.busy


def test_inputs_that_fit_the_prompts_still_succeed(window, monkeypatch,
                                                   tmp_path):
    from serpentine3d.api import SerpApi
    from serpentine3d.fileio import pdf

    monkeypatch.setattr(pdf, "export_layouts_pdf",
                        lambda win, layouts, path: None)
    lay = Layout(name="Seat blank")
    window.scene.layouts.append(lay)
    window.scene.notify()
    window.switch_space(lay.id)
    wanted = str(tmp_path / "seat.pdf")

    reply = SerpApi(window).command("exportpdf", [wanted])

    assert any(wanted in line for line in reply["messages"])


def test_a_script_hears_about_an_input_its_command_did_not_use():
    doc = Document()

    with pytest.raises(RuntimeError) as caught:
        doc.run("circle", ["0,0,0", "5", "7"])

    message = str(caught.value)
    assert "'7'" in message
    assert "Radius" in message and "'5'" in message
    assert "Created Curve 01" in message, \
        "The circle was made, so a retry would make a second one"
    assert len(doc.objects()) == 1
    assert not doc._proc.busy
