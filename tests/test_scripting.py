import os
import subprocess
import sys

import pytest

from serpentine.scripting import Document


def test_document_api(tmp_path):
    doc = Document()
    box = doc.add(doc.geo.make_box((0, 0, 0), 10, 10, 10), name="Base",
                  layer="Parts")
    assert doc.volume("Base") == pytest.approx(1000)
    msgs = doc.run("filletedge", ["Base", "", "1"])
    assert any("Filleted" in m for m in msgs)
    assert doc.volume("Base") < 1000
    doc.run("circle", ["0,0,20", "5"])
    assert len(doc.objects()) == 2

    path = str(tmp_path / "scripted.serp")
    doc.save(path)
    doc2 = Document(path)
    assert len(doc2.objects()) == 2
    assert doc2.get("Base") is not None

    step = str(tmp_path / "scripted.step")
    doc.export(step, only=["Base"])
    assert os.path.getsize(step) > 500


def test_document_run_error():
    doc = Document()
    with pytest.raises(RuntimeError):
        doc.run("nonsense_command")
    doc.add(doc.geo.make_box((0, 0, 0), 1, 1, 1), name="B")
    with pytest.raises(RuntimeError, match="more input"):
        doc.run("filletedge", ["B", ""])     # missing radius


def test_batch_runner(tmp_path):
    script = tmp_path / "job.py"
    out = tmp_path / "result.step"
    script.write_text(
        "doc.add(geo.make_sphere((0,0,0), 5), name='Ball')\n"
        f"doc.export(r'{out}')\n"
        "print('made', len(doc.objects()))\n")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    res = subprocess.run(
        [sys.executable, "-m", "serpentine.batch", str(script)],
        capture_output=True, text=True, env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert res.returncode == 0, res.stderr
    assert "made 1" in res.stdout
    assert os.path.getsize(out) > 500
