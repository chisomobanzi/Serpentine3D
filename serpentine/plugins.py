"""Plugin loading.

Two discovery mechanisms:

1. Python packages exposing a ``serpentine.plugins`` entry point whose
   target is a callable ``register(ctx)``.
2. Plain ``*.py`` files in ``~/.serpentine/plugins`` (override with
   ``SERP_PLUGIN_DIR``) defining ``serpentine_plugin(ctx)``.

Both receive a :class:`PluginContext`: everything a plugin needs to add
commands, reach the scene, and (in the GUI) add menu actions.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import traceback


class PluginContext:
    """The surface Serpentine offers to plugins."""

    def __init__(self, window=None):
        self.window = window

    @property
    def version(self) -> str:
        from serpentine import __version__
        return __version__

    @property
    def scene(self):
        return self.window.scene if self.window is not None else None

    # command registration: same decorator the built-ins use, plus the
    # request types plugins need to drive the command line
    @property
    def command(self):
        from .commands.base import command
        return command

    def requests(self):
        """PointReq/NumberReq/... namespace for generator commands."""
        from .commands import base
        return base

    def add_menu_action(self, label: str, fn) -> bool:
        """Add an entry to the GUI's Plugins menu. False when headless."""
        if self.window is None:
            return False
        self.window.plugin_menu_action(label, fn)
        return True


def plugin_dir() -> str:
    return os.environ.get(
        "SERP_PLUGIN_DIR",
        os.path.join(os.path.expanduser("~"), ".serpentine", "plugins"))


_loaded: list[tuple[str, str]] = []     # (name, origin)


def loaded_plugins() -> list[tuple[str, str]]:
    return list(_loaded)


def load_plugins(window=None) -> list[str]:
    """Load every discoverable plugin once. Returns names, never raises:
    a broken plugin is reported and skipped."""
    ctx = PluginContext(window)
    names = []

    from importlib import metadata
    try:
        eps = metadata.entry_points(group="serpentine.plugins")
    except TypeError:                    # Python <3.10 select API
        eps = metadata.entry_points().get("serpentine.plugins", [])
    for ep in eps:
        if any(n == ep.name for n, _ in _loaded):
            continue
        try:
            ep.load()(ctx)
            _loaded.append((ep.name, f"package:{ep.value}"))
            names.append(ep.name)
        except Exception:                # noqa: BLE001
            traceback.print_exc()

    d = plugin_dir()
    if os.path.isdir(d):
        for fname in sorted(os.listdir(d)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            name = os.path.splitext(fname)[0]
            if any(n == name for n, _ in _loaded):
                continue
            path = os.path.join(d, fname)
            try:
                spec = importlib.util.spec_from_file_location(
                    f"serpentine_plugin_{name}", path)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                hook = getattr(mod, "serpentine_plugin", None)
                if callable(hook):
                    hook(ctx)
                    _loaded.append((name, path))
                    names.append(name)
            except Exception:            # noqa: BLE001
                traceback.print_exc()
    return names
