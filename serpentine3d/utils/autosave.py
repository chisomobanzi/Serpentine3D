"""Autosave and crash recovery.

Every running session owns a lockfile (with its pid) and an autosave slot.
A clean exit removes both. On startup, lockfiles whose pid is dead identify
crashed sessions; their autosaves are offered for recovery.
"""

from __future__ import annotations

import json
import os
import time

AUTOSAVE_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME",
                   os.path.expanduser("~/.local/share")),
    "serpentine3d", "autosave")

DEFAULT_INTERVAL_SEC = 300


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AutosaveManager:
    """Owns this session's autosave slot. Qt-free; the window drives it."""

    def __init__(self, scene, directory: str = AUTOSAVE_DIR):
        self.scene = scene
        self.dir = directory
        os.makedirs(self.dir, exist_ok=True)
        self.pid = os.getpid()
        self.lock_path = os.path.join(self.dir, f"session-{self.pid}.json")
        self.autosave_path = os.path.join(self.dir,
                                          f"autosave-{self.pid}.serp")
        self._last_saved_revision = -1
        self.doc_path: str | None = None
        self._write_lock()

    # -- session lock --

    def _write_lock(self):
        data = {"pid": self.pid, "started": time.time(),
                "autosave": self.autosave_path, "doc_path": self.doc_path}
        tmp = self.lock_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, self.lock_path)

    def set_doc_path(self, path: str | None):
        self.doc_path = path
        self._write_lock()

    # -- saving --

    def maybe_autosave(self) -> bool:
        """Autosave if the scene changed since the last autosave."""
        if self.scene.revision == self._last_saved_revision:
            return False
        return self.autosave_now()

    def autosave_now(self) -> bool:
        from ..fileio import native
        tmp = self.autosave_path + ".tmp"
        try:
            native.save_scene(self.scene, tmp)
            os.replace(tmp, self.autosave_path)
        except Exception:                                     # noqa: BLE001
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False
        self._last_saved_revision = self.scene.revision
        return True

    def clean_exit(self):
        for p in (self.autosave_path, self.lock_path):
            try:
                os.unlink(p)
            except OSError:
                pass

    # -- recovery --

    def find_recoverable(self) -> list[dict]:
        """Stale sessions (dead pid + autosave file), newest first."""
        out = []
        try:
            names = os.listdir(self.dir)
        except OSError:
            return out
        for name in names:
            if not (name.startswith("session-") and name.endswith(".json")):
                continue
            path = os.path.join(self.dir, name)
            try:
                with open(path) as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            pid = int(data.get("pid", -1))
            if pid == self.pid or _pid_alive(pid):
                continue
            autosave = data.get("autosave", "")
            if not autosave or not os.path.exists(autosave):
                # crashed before any autosave: just clean the lock
                try:
                    os.unlink(path)
                except OSError:
                    pass
                continue
            data["lock_path"] = path
            data["mtime"] = os.path.getmtime(autosave)
            out.append(data)
        out.sort(key=lambda d: -d["mtime"])
        return out

    def recover(self, entry: dict) -> str | None:
        """Load a stale autosave into the scene. Returns the original doc
        path (may be None for unsaved documents)."""
        from ..fileio import native
        native.load_scene(self.scene, entry["autosave"])
        for key in ("lock_path", "autosave"):
            try:
                os.unlink(entry[key])
            except OSError:
                pass
        # protect the recovered state immediately
        self._last_saved_revision = -1
        self.autosave_now()
        return entry.get("doc_path")

    @staticmethod
    def discard(entry: dict):
        for key in ("lock_path", "autosave"):
            try:
                os.unlink(entry.get(key, ""))
            except OSError:
                pass
