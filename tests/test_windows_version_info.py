"""The Windows .exe must carry ProductName/ProductVersion metadata.

SignPath enforces both at signing time, and without them the shipped binary
shows blank in file Properties and Task Manager. The resource is generated
from serpentine3d.__version__ so it cannot drift from the release.
"""
import ast
import importlib.util
from pathlib import Path

import pytest

from serpentine3d import __version__

SPEC_DIR = Path(__file__).resolve().parent.parent / "packaging" / "windows"


def _load():
    path = SPEC_DIR / "make_version_info.py"
    spec = importlib.util.spec_from_file_location("make_version_info", path)
    if spec is None or spec.loader is None:      # pragma: no cover - import guard
        pytest.fail(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_tuple_pads_to_four_parts():
    assert _load().version_tuple("0.5.2") == (0, 5, 2, 0)
    assert _load().version_tuple("1.10.0") == (1, 10, 0, 0)


def test_version_tuple_ignores_a_v_prefix_and_suffix():
    assert _load().version_tuple("v0.6.0") == (0, 6, 0, 0)
    assert _load().version_tuple("0.6.0rc1") == (0, 6, 0, 0)


def test_resource_is_syntactically_valid_python():
    ast.parse(_load().version_info(__version__))


def test_product_name_and_version_are_set():
    text = _load().version_info(__version__)
    assert "StringStruct('ProductName', 'Serpentine3D')" in text
    assert f"StringStruct('ProductVersion', '{__version__}')" in text
    assert f"StringStruct('FileVersion', '{__version__}')" in text


def test_fixed_info_matches_the_string_table():
    text = _load().version_info("0.5.2")
    assert "filevers=(0, 5, 2, 0)" in text
    assert "prodvers=(0, 5, 2, 0)" in text


def test_spec_generates_the_resource_and_points_exe_at_it():
    spec = (SPEC_DIR / "serp3d.spec").read_text()
    assert "make_version_info" in spec, "spec must generate the version resource"
    assert "version=" in spec, "EXE() must reference the generated resource"
