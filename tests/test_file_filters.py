"""File-dialog filters must track what fileio can actually do.

Regression: GitHub #2 — .3dm imports fine but the Open dialog never offered
it, so Rhino files looked unsupported. One shared filter string was used for
both Open and Export, so it was wrong in both directions at once.
"""

import pytest

from serpentine3d import fileio


def _exts_in(filter_str: str) -> set:
    """Every *.ext token mentioned in a Qt name-filter string, dot included."""
    return {tok[1:].lower() for tok in filter_str.replace("(", " ")
            .replace(")", " ").replace(";", " ").split()
            if tok.startswith("*.")}


def test_3dm_is_importable_and_offered():
    """The reported bug: Rhino files open, but weren't listed."""
    assert ".3dm" in fileio.IMPORT_EXTS
    assert ".3dm" in _exts_in(fileio.import_filter())


def test_import_filter_covers_every_importable_format():
    assert _exts_in(fileio.import_filter()) == fileio.IMPORT_EXTS


def test_export_filter_covers_every_exportable_format():
    assert _exts_in(fileio.export_filter()) == fileio.EXPORT_EXTS


def test_open_and_import_default_to_all_supported():
    """One entry that shows every openable file, selected by default — Qt
    picks the first filter, so it must lead the list."""
    assert fileio.import_filter().startswith("All supported (")


def test_export_offers_no_catch_all_filters():
    """Catch-alls are for reading. On save they name no format, so "All files"
    is the one remaining way to get an extensionless path that export can't
    dispatch on — every export filter must name a real format."""
    assert "All files" not in fileio.export_filter()
    assert "All supported" not in fileio.export_filter()
    for part in fileio.export_filter().split(";;"):
        assert fileio.suffix_for_filter(part), f"{part} names no format"


def test_open_keeps_the_all_files_escape_hatch():
    """Reading is the opposite case: a file with an odd or missing extension
    should still be selectable, and import fails loudly if it can't read it."""
    assert fileio.import_filter().endswith("All files (*)")


def test_export_does_not_lead_with_all_supported():
    """On save there is nothing to filter — the chosen format decides the
    output, and a bare filename under 'All supported' has no extension to
    dispatch on."""
    assert not fileio.export_filter().startswith("All supported (")
    assert fileio.export_filter().startswith("Serpentine3D (*.serp)")


def _export_path_for(monkeypatch, typed: str, name_filter: str) -> str:
    """Run the real Export chooser with a canned filename + format choice."""
    from serpentine3d import app as app_mod

    class Rec(app_mod.QFileDialog):
        def __init__(self, parent, title, directory, filters):
            super().__init__(parent, title, directory, filters)
            self.selectNameFilter(name_filter)

        def exec(self):
            return 1                                    # user hits Save

        def selectedFiles(self):
            return [typed]

        def selectedNameFilter(self):
            return name_filter

    monkeypatch.setattr(app_mod, "QFileDialog", Rec)
    win = app_mod.MainWindow()
    try:
        return win._pick_file(save=True, title="Export")
    finally:
        win.close()


def test_save_appends_the_selected_formats_extension(monkeypatch):
    """Typing a bare 'part' must come back as part.stl when STL is chosen —
    export dispatches on the extension, so an extensionless path just fails."""
    assert _export_path_for(monkeypatch, "/tmp/part",
                            "STL — 3D printing (*.stl)") == "/tmp/part.stl"
    assert _export_path_for(monkeypatch, "/tmp/part",
                            "Rhino (*.3dm)") == "/tmp/part.3dm"


def test_export_of_a_bare_filename_writes_a_real_file(monkeypatch, tmp_path):
    """The whole point, end to end: pick STL, type 'part', get part.stl on
    disk. Before this, export dispatched on the extension and a bare name
    just raised 'Unsupported export format'."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from serpentine3d import app as app_mod

    target = tmp_path / "part"

    class Rec(app_mod.QFileDialog):
        def exec(self):
            return 1                                    # user hits Save

        def selectedFiles(self):
            return [str(target)]

        def selectedNameFilter(self):
            return "STL — 3D printing (*.stl)"

    monkeypatch.setattr(app_mod, "QFileDialog", Rec)
    win = app_mod.MainWindow()
    try:
        win.scene.add(BRepPrimAPI_MakeBox(10., 10., 5.).Shape(), name="box")
        win._pick_stl_quality = lambda: "standard"      # skip the modal
        win._file_export()
    finally:
        win.mark_saved()          # else closeEvent blocks on "Unsaved changes"
        win.close()

    assert not target.exists(), "wrote an extensionless file"
    written = target.with_suffix(".stl")
    assert written.exists() and written.stat().st_size > 0
    assert written.read_bytes()[:5] == b"solid" or written.stat().st_size > 84


def test_typed_extension_beats_the_dropdown(monkeypatch):
    """Someone who types part.3dm means it, whatever the combo box says."""
    assert _export_path_for(monkeypatch, "/tmp/part.3dm",
                            "STL — 3D printing (*.stl)") == "/tmp/part.3dm"


def test_all_files_filter_invents_no_extension():
    """'All files (*)' names no format, so there is nothing to append."""
    assert fileio.suffix_for_filter("All files (*)") == ""
    assert fileio.ensure_suffix("/tmp/part", "All files (*)") == "/tmp/part"
    assert fileio.suffix_for_filter("STEP (*.step *.stp)") == "step"


def test_import_filter_does_not_advertise_export_only_formats():
    """.3mf/.glb/.usd export but cannot be imported — offering them on Open
    produces a confusing 'Unsupported import format' error."""
    offered = _exts_in(fileio.import_filter())
    for ext in (".3mf", ".glb", ".usda"):
        assert ext not in offered


@pytest.mark.parametrize("ext", sorted(fileio.IMPORT_EXTS))
def test_declared_import_exts_are_really_dispatched(ext, tmp_path):
    """A declared extension must reach a real importer — never fall through
    to 'Unsupported import format'. An empty file may import as zero objects
    or raise a parse error; either proves it was dispatched."""
    from serpentine3d.core.scene import Scene
    path = tmp_path / f"empty{ext}"
    path.write_bytes(b"")
    try:
        fileio.import_file(Scene(), str(path))
    except Exception as exc:                       # noqa: BLE001
        assert "Unsupported import format" not in str(exc)


def test_dialogs_use_the_fileio_filters(monkeypatch):
    """Open/Import must get the import filter and Export the export filter —
    the wiring bug behind #2 was one shared string used for both."""
    from serpentine3d import app as app_mod

    seen = {}

    class RecordingDialog(app_mod.QFileDialog):
        def __init__(self, parent, title, directory, filters):
            super().__init__(parent, title, directory, filters)
            seen[title] = filters

        def exec(self):
            return 0                                # user cancels

    monkeypatch.setattr(app_mod, "QFileDialog", RecordingDialog)
    win = app_mod.MainWindow()
    try:
        win._file_open()
        win._file_import()
        win._file_export()
    finally:
        win.close()

    assert ".3dm" in _exts_in(seen["Open"])
    assert seen["Open"] == fileio.import_filter()
    assert seen["Import"] == fileio.import_filter()
    assert seen["Export"] == fileio.export_filter()


def test_unsupported_extension_still_rejected(tmp_path):
    from serpentine3d.core.scene import Scene
    path = tmp_path / "model.sldprt"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="Unsupported import format"):
        fileio.import_file(Scene(), str(path))


def test_export_offers_every_rhino_version():
    """GitHub #5: a file for a colleague on Rhino 6 must not need Rhino 8 to
    open — the version is picked where the format is."""
    f = fileio.export_filter()
    for version in (8, 7, 6, 5):
        assert f"Rhino {version} (*.3dm)" in f


def test_rhino_version_reads_off_the_chosen_filter():
    assert fileio.rhino_version_from_filter("Rhino 7 (*.3dm)") == 7
    assert fileio.rhino_version_from_filter("Rhino 5 (*.3dm)") == 5
    # anything else — old filter text, no filter, another format — means
    # current, not a crash
    assert fileio.rhino_version_from_filter("Rhino (*.3dm)") == 8
    assert fileio.rhino_version_from_filter("STEP (*.step *.stp)") == 8
    assert fileio.rhino_version_from_filter("") == 8
