"""Offering to be the default application for .serp files.

Beta feedback: nothing ever asks. The offer is one dialog on launch
(app.py wires it); everything decidable without a screen lives in
utils/file_assoc.py and is what these tests pin down.
"""

import ntpath
import posixpath
import subprocess

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.utils import file_assoc
from serpentine3d.utils.config import Config


@pytest.fixture
def config(tmp_path):
    return Config(path=str(tmp_path / "settings.json"))


def _own_home(monkeypatch, tmp_path):
    """Give the test a home directory of its own, on any platform.

    HOME alone is a posix answer: expanduser("~") is ntpath's on Windows,
    and that reads USERPROFILE. Both, plus no XDG_DATA_HOME, is what puts
    the whole of _data_home() inside tmp_path wherever this runs.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)


@pytest.mark.parametrize("flavour", [posixpath, ntpath],
                         ids=["posix", "windows"])
def test_the_home_a_test_sets_is_the_home_that_gets_used(
        monkeypatch, tmp_path, flavour):
    """Pointing HOME at a tmp_path only isolates the run on posix.

    expanduser("~") is ntpath's on Windows, and that one reads USERPROFILE
    and never looks at HOME. So make_default went on writing into the real
    user profile while the assertions below looked at an empty tmp_path,
    and the only reason it showed up as a failure rather than as a mess is
    that the .desktop file was not where the test expected it.
    """
    _own_home(monkeypatch, tmp_path)
    monkeypatch.setattr(file_assoc.os.path, "expanduser", flavour.expanduser)
    assert file_assoc._data_home().startswith(str(tmp_path))


# ------------------------------------------------- what gets registered

def test_desktop_entry_names_the_app_and_its_mime_type():
    text = file_assoc.desktop_entry("/opt/Serpentine3D.AppImage %F")
    assert "[Desktop Entry]" in text
    assert "Exec=/opt/Serpentine3D.AppImage %F" in text
    assert f"MimeType={file_assoc.MIME};" in text
    assert "Name=Serpentine3D" in text


def test_mime_xml_claims_the_serp_glob():
    xml = file_assoc.mime_xml()
    assert file_assoc.MIME in xml
    assert '*.serp' in xml


def test_exec_line_prefers_the_appimage_it_runs_from(monkeypatch):
    monkeypatch.setenv("APPIMAGE", "/home/u/Applications/S.AppImage")
    assert file_assoc.exec_line() == "/home/u/Applications/S.AppImage %F"
    monkeypatch.delenv("APPIMAGE")
    line = file_assoc.exec_line()
    assert "-m serpentine3d" in line and "%F" in line


# ------------------------------------------------------- status probing

def test_status_reads_xdg_mime_answer(monkeypatch):
    monkeypatch.setattr(file_assoc.sys, "platform", "linux")

    def fake_run(cmd, **kw):
        assert cmd[:3] == ["xdg-mime", "query", "default"]
        return subprocess.CompletedProcess(cmd, 0,
                                           stdout="serpentine3d.desktop\n")
    monkeypatch.setattr(file_assoc.subprocess, "run", fake_run)
    assert file_assoc.status() == "default"

    def other(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="org.gnome.x\n")
    monkeypatch.setattr(file_assoc.subprocess, "run", other)
    assert file_assoc.status() == "not_default"

    def boom(cmd, **kw):
        raise FileNotFoundError("no xdg-mime")
    monkeypatch.setattr(file_assoc.subprocess, "run", boom)
    assert file_assoc.status() == "unknown"


# ------------------------------------------------------- the offer rule

def test_offers_once_until_answered(monkeypatch, config):
    monkeypatch.setattr(file_assoc, "status", lambda: "not_default")
    assert file_assoc.should_offer(config)
    config.set("file_assoc", "asked", True)
    assert not file_assoc.should_offer(config)


def test_never_offers_when_already_default(monkeypatch, config):
    monkeypatch.setattr(file_assoc, "status", lambda: "default")
    assert not file_assoc.should_offer(config)


# --------------------------------------------- making it stick on linux

def test_make_default_registers_and_sets_the_handler(monkeypatch, tmp_path):
    monkeypatch.setattr(file_assoc.sys, "platform", "linux")
    _own_home(monkeypatch, tmp_path)
    monkeypatch.setenv("APPIMAGE", "/apps/S.AppImage")
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="")
    monkeypatch.setattr(file_assoc.subprocess, "run", fake_run)

    ok, msg = file_assoc.make_default()
    assert ok, msg
    share = tmp_path / ".local" / "share"
    desktop = share / "applications" / "serpentine3d.desktop"
    assert desktop.exists()
    assert "Exec=/apps/S.AppImage %F" in desktop.read_text()
    assert (share / "mime" / "packages" / "serpentine3d.xml").exists()
    assert ["xdg-mime", "default", "serpentine3d.desktop",
            file_assoc.MIME] in calls
    assert ".serp" in msg


def test_make_default_keeps_an_existing_desktop_entry(monkeypatch, tmp_path):
    """install-desktop.sh writes a richer entry; ours must not clobber it."""
    monkeypatch.setattr(file_assoc.sys, "platform", "linux")
    _own_home(monkeypatch, tmp_path)
    apps = tmp_path / ".local" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "serpentine3d.desktop").write_text("[Desktop Entry]\nName=Rich\n")
    monkeypatch.setattr(
        file_assoc.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout=""))
    ok, _ = file_assoc.make_default()
    assert ok
    assert "Name=Rich" in (apps / "serpentine3d.desktop").read_text()


# ----------------------------------------------------- the command form

def test_setdefaultapp_command_reports_what_happened(monkeypatch):
    from serpentine3d.commands.base import (
        CommandContext,
        CommandProcessor,
    )
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager

    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    proc = CommandProcessor(ctx)
    echoes = []
    ctx.add_echo_listener(echoes.append)
    monkeypatch.setattr(file_assoc, "make_default",
                        lambda: (True, "Serpentine3D now opens .serp files."))
    proc.run("setdefaultapp")
    assert not proc.busy
    assert any(".serp" in e for e in echoes)


# --------------------------------------- macOS FileOpen events reach us

class _FakeFileOpen:
    def __init__(self, path):
        self._path = path

    def type(self):
        from PySide6.QtCore import QEvent
        return QEvent.Type.FileOpen

    def file(self):
        return self._path


def test_file_open_events_open_the_document(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import FileOpenRelay

    opened = []

    class _Window:
        def _open_path(self, path):
            opened.append(path)

    relay = FileOpenRelay.__new__(FileOpenRelay)   # no QObject parent needed
    relay._window = _Window()
    handled = FileOpenRelay.eventFilter(relay, None,
                                        _FakeFileOpen("/tmp/a.serp"))
    assert handled and opened == ["/tmp/a.serp"]
