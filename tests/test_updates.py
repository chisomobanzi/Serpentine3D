"""Update-notifier logic (TDD, written before serpentine3d/utils/updates.py).

Pure + network-injected: no real HTTP in tests. The UI wiring (welcome-screen
banner, Help menu, launch check) is visual and verified in the app, not here.
"""

import json

import pytest

from serpentine3d.utils import updates as u


# ---------------------------------------------------------- version parsing

@pytest.mark.parametrize("text,expected", [
    ("0.3.1", (0, 3, 1)),
    ("v0.3.1", (0, 3, 1)),
    ("V1.2.3", (1, 2, 3)),
    ("0.3", (0, 3)),
    ("2.0.0", (2, 0, 0)),
    ("  v0.4.0  ", (0, 4, 0)),
])
def test_parse_version(text, expected):
    assert u.parse_version(text) == expected


@pytest.mark.parametrize("latest,current,newer", [
    ("0.3.2", "0.3.1", True),
    ("0.3.1", "0.3.1", False),       # equal is not newer
    ("0.3.0", "0.3.1", False),
    ("v0.4.0", "0.3.9", True),        # minor beats larger patch
    ("1.0.0", "0.9.9", True),
    ("0.3.1", "0.3", True),           # 0.3.1 > 0.3 (padded)
    ("0.3", "0.3.1", False),
])
def test_is_newer(latest, current, newer):
    assert u.is_newer(latest, current) is newer


# ------------------------------------------------------- asset by platform

def _assets():
    return [
        {"name": "Serpentine3D-x86_64.AppImage",
         "browser_download_url": "https://x/Serpentine3D-x86_64.AppImage"},
        {"name": "Serpentine3D-Setup-x86_64.exe",
         "browser_download_url": "https://x/Serpentine3D-Setup-x86_64.exe"},
        {"name": "Serpentine3D-0.3.2-arm64.dmg",
         "browser_download_url": "https://x/Serpentine3D-0.3.2-arm64.dmg"},
    ]


@pytest.mark.parametrize("system,suffix", [
    ("Linux", ".AppImage"),
    ("Windows", ".exe"),
    ("Darwin", ".dmg"),
])
def test_asset_for_platform_picks_right_file(system, suffix):
    url = u.asset_for_platform(_assets(), system)
    assert url is not None and url.endswith(suffix)


def test_asset_for_platform_unknown_os_is_none():
    assert u.asset_for_platform(_assets(), "Plan9") is None


def test_asset_for_platform_no_matching_asset_is_none():
    only_exe = [_assets()[1]]
    assert u.asset_for_platform(only_exe, "Linux") is None


# ------------------------------------------------------------ parse release

def _release(tag="v0.3.2"):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/chisomobanzi/Serpentine3D/releases/"
                    f"tag/{tag}",
        "assets": _assets(),
    }


def test_parse_release_normalises_fields():
    rel = u.parse_release(_release(), "Linux")
    assert rel["version"] == "0.3.2"
    assert rel["url"].endswith("/tag/v0.3.2")
    assert rel["download"].endswith(".AppImage")


# -------------------------------------------------- check_for_update (glue)

def test_check_returns_release_when_newer():
    got = u.check_for_update("0.3.1", "Linux",
                             fetch=lambda: json.dumps(_release()))
    assert got is not None
    assert got["version"] == "0.3.2"
    assert got["download"].endswith(".AppImage")


def test_check_returns_none_when_equal():
    assert u.check_for_update("0.3.2", "Linux",
                              fetch=lambda: json.dumps(_release())) is None


def test_check_returns_none_when_current_is_ahead():
    assert u.check_for_update("0.4.0", "Windows",
                              fetch=lambda: json.dumps(_release())) is None


def test_check_is_fail_silent_on_fetch_error():
    def boom():
        raise OSError("offline")
    assert u.check_for_update("0.3.1", "Linux", fetch=boom) is None


def test_check_is_fail_silent_on_bad_json():
    assert u.check_for_update("0.3.1", "Linux",
                              fetch=lambda: "not json {{{") is None


def test_check_accepts_bytes_payload():
    got = u.check_for_update("0.3.1", "Linux",
                             fetch=lambda: json.dumps(_release()).encode())
    assert got is not None and got["version"] == "0.3.2"
