"""A buffer name is valid only in the OpenGL group that allocated it."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject
import shiboken6

from serpentine3d.ui import gpu_share, viewport as vp


@pytest.fixture
def buffers(monkeypatch):
    gpu_share.reset()
    monkeypatch.setattr(vp, "_deferred_buffer_deletes", {})
    monkeypatch.setattr(vp.GL, "glBindVertexArray", lambda *_: None)
    created = []

    def build(*args):
        result = SimpleNamespace(cloud_levels=None, cloud_colored=False,
                                 anchor=None, cloud_count=0, tri_count=0,
                                 line_count=0, iso_count=0, nbytes=0,
                                 release=lambda: None)
        created.append(result)
        return result

    monkeypatch.setattr(vp, "_MeshBuffers", build)
    yield created
    gpu_share.reset()


def test_two_unshared_contexts_upload_separate_buffers(buffers, monkeypatch):
    mesh = SimpleNamespace(uid=123)
    first, second = QObject(), QObject()
    monkeypatch.setattr(vp, "_current_share_group", lambda: first)
    a = vp._GpuObject(mesh)
    monkeypatch.setattr(vp, "_current_share_group", lambda: second)
    b = vp._GpuObject(mesh)
    assert a.buffers is not b.buffers
    assert len(buffers) == 2
    a.forget()
    b.forget()


def test_contexts_in_one_group_still_share_one_upload(buffers, monkeypatch):
    group = QObject()
    monkeypatch.setattr(vp, "_current_share_group", lambda: group)
    mesh = SimpleNamespace(uid=456)
    a, b = vp._GpuObject(mesh), vp._GpuObject(mesh)
    assert a.buffers is b.buffers
    assert len(buffers) == 1
    a.forget()
    b.forget()


def test_retiring_in_another_group_waits_for_the_owner(monkeypatch):
    owner, other = QObject(), QObject()
    monkeypatch.setattr(vp, "_deferred_buffer_deletes", {})
    monkeypatch.setattr(vp, "_current_share_group", lambda: other)
    deleted = []
    monkeypatch.setattr(vp.GL, "glDeleteBuffers", lambda n, ids: deleted.extend(ids))
    buffers = vp._MeshBuffers.__new__(vp._MeshBuffers)
    buffers._share_group, buffers._buffers, buffers.nbytes = owner, [41, 42], 24
    buffers.release()
    assert deleted == []
    vp._flush_buffer_deletes()
    assert deleted == []
    monkeypatch.setattr(vp, "_current_share_group", lambda: owner)
    vp._flush_buffer_deletes()
    assert deleted == [41, 42]
    vp._flush_buffer_deletes()
    assert deleted == [41, 42]


def test_a_destroyed_group_is_retired_without_deleting_foreign_names(monkeypatch):
    owner, current = QObject(), QObject()
    monkeypatch.setattr(vp, "_deferred_buffer_deletes", {owner: [41]})
    monkeypatch.setattr(vp, "_current_share_group", lambda: current)
    deleted = []
    monkeypatch.setattr(vp.GL, "glDeleteBuffers", lambda n, ids: deleted.extend(ids))
    shiboken6.delete(owner)
    vp._flush_buffer_deletes()
    assert deleted == []
    assert vp._deferred_buffer_deletes == {}
