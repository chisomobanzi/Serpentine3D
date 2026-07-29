"""The Windows installer offers an update-check opt-out at install time.

SignPath's terms require an opt-out *installation option*, not just a runtime
setting. The installer writes a minimal settings.json when the user clears the
task, so these tests pin the contract it depends on: a partial settings file
must disable the check without disturbing any other default.
"""
import json
from pathlib import Path

from serpentine3d.utils.config import Config

ISS = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "installer.iss"

# byte-for-byte what installer.iss writes when the task is cleared
WRITTEN = '{\r\n  "check_updates": false\r\n}\r\n'


def test_written_file_is_valid_json():
    assert json.loads(WRITTEN) == {"check_updates": False}


def test_partial_settings_file_disables_the_update_check(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(WRITTEN)
    cfg = Config(str(path))
    # app.py gates on `is False`, so the value must survive as a real bool
    assert cfg.get("check_updates", default=True) is False


def test_partial_settings_file_leaves_other_defaults_intact(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(WRITTEN)
    cfg = Config(str(path))
    assert cfg.get("osnaps", "end") is True
    assert cfg.get("default_units") == "mm"
    assert cfg.get("show_welcome") is True


def test_installer_offers_the_task():
    iss = ISS.read_text()
    assert 'Name: "updatecheck"' in iss
    # checked by default: opting out is a deliberate act, not the default path
    assert "Name: \"updatecheck\"; Description:" in iss
    assert "updatecheck\"; Flags: unchecked" not in iss


def test_installer_writes_the_setting_to_the_right_place():
    iss = ISS.read_text()
    assert "check_updates" in iss
    assert r".config\serpentine3d" in iss
    assert "settings.json" in iss
    # must not clobber a settings file the user already has
    assert "FileExists" in iss
