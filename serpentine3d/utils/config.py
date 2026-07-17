"""User settings: JSON file at ~/.config/serpentine3d/settings.json."""

from __future__ import annotations

import copy
import json
import os

def _migrate_legacy_dirs():
    """Adopt pre-rebrand data (settings, autosaves, plugins) in place."""
    for old, new in (("~/.serpentine", "~/.serpentine3d"),
                     ("~/.config/serpentine", "~/.config/serpentine3d")):
        src_dir = os.path.expanduser(old)
        dst_dir = os.path.expanduser(new)
        if os.path.isdir(src_dir) and not os.path.exists(dst_dir):
            try:
                os.rename(src_dir, dst_dir)
            except OSError:
                pass


_migrate_legacy_dirs()

CONFIG_DIR = os.path.expanduser("~/.config/serpentine3d")
CONFIG_PATH = os.path.join(CONFIG_DIR, "settings.json")

DEFAULTS = {
    "mouse": {
        "orbit_button": "middle",      # middle | right
        "invert_scroll": False,
        "orbit_speed": 1.0,
        "zoom_speed": 1.0,
    },
    "osnaps": {
        "enabled": True,
        "end": True,
        "mid": True,
        "center": True,
        "quad": True,
        "int": True,
        "perp": False,
        "near": False,
    },
    "grid_snap": False,
    "grid_snap_step": 1.0,
    "default_units": "mm",
    "aliases": {},                     # alias -> command name
    "shortcuts": {},                   # key sequence -> command name
    "display": {
        "grid_extent": 100,
        "grid_major": 10,
    },
}


class Config:
    def __init__(self, path: str | None = None):
        if path is None:
            path = os.environ.get("SERP3D_CONFIG", CONFIG_PATH)
        self.path = path
        self.data = copy.deepcopy(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(self.path) as f:
                stored = json.load(f)
        except (OSError, ValueError):
            return
        _merge(self.data, stored)

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.data, f, indent=2, sort_keys=True)
        if os.name != "nt":
            os.chmod(tmp, 0o600)    # may hold an API key
        os.replace(tmp, self.path)

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.save()

    # convenience accessors
    def get(self, *keys, default=None):
        node = self.data
        for k in keys:
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node

    def set(self, *keys_and_value):
        *keys, value = keys_and_value
        node = self.data
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
        self.save()


def _merge(base: dict, override: dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


# ---------------------------------------------------------------- importers

# Rhino command -> serpentine3d command (used when importing Rhino alias files)
RHINO_COMMAND_MAP = {
    "line": "line", "polyline": "polyline", "interpcrv": "curve",
    "curve": "curve", "circle": "circle", "arc": "arc",
    "ellipse": "ellipse", "rectangle": "rectangle",
    "extrudecrv": "extrude", "extrudesrf": "extrude", "extrude": "extrude",
    "revolve": "revolve", "loft": "loft", "sweep1": "sweep1",
    "sweep2": "sweep2", "planarsrf": "planarsrf", "box": "box",
    "sphere": "sphere", "cylinder": "cylinder", "cone": "cone",
    "torus": "torus", "move": "move", "copy": "copy", "rotate": "rotate",
    "rotate3d": "rotate", "scale": "scale", "scalenu": "scalenu",
    "mirror": "mirror", "arraypolar": "arraypolar", "array": "array",
    "booleanunion": "booleanunion", "booleandifference": "booleandifference",
    "booleanintersection": "booleanintersection", "trim": "trim",
    "split": "split", "join": "join", "explode": "explode",
    "offset": "offset", "fillet": "fillet", "rebuild": "rebuild",
    "delete": "delete", "hide": "hide", "show": "show", "undo": "undo",
    "redo": "redo", "zoomextents": "zoomextents", "zea": "zoomextents",
    "pointson": "pointson", "pointsoff": "pointsoff", "distance": "distance",
    "length": "length", "area": "area", "volume": "volume",
    "selall": "selall", "selnone": "selnone", "selcrv": "selcrv",
    "selsrf": "selsrf", "selsolid": "selsolid", "sellast": "sellast",
    "invert": "invert", "isolate": "isolate", "unisolate": "unisolate",
    "top": "top", "front": "front", "right": "right",
    "perspective": "perspective", "shade": "shaded", "shaded": "shaded",
    "wireframe": "wireframe", "ghosted": "ghosted", "grid": "grid",
    "new": "new", "open": "open", "save": "save", "import": "import",
    "export": "export", "layer": "layer",
}


# full-macro phrases (normalized: prefixes stripped, lowercased) whose
# meaning needs more than the first command token. Values may be Serp3D
# macros ('osnap mid toggle') — aliases and shortcuts both accept those.
RHINO_MACRO_MAP = {
    "zoom": "zoom",
    "zoom extents": "zoomextents",
    "zoom target": "zoom",
    "zoom all extents": "zoomextents",
    "zoom selected": "zoomselected",
    "zoom all selected": "zoomselected",
    "zoom window": "zoomwindow",
    "setview world top": "top",
    "setview world front": "front",
    "setview world back": "back",
    "setview world right": "right",
    "setview world left": "left",
    "setview world bottom": "bottom",
    "setview world perspective": "perspective",
    "setdisplaymode arctic": "rendered",
    "setdisplaymode rendered": "rendered",
    "setdisplaymode shaded": "shaded",
    "setdisplaymode wireframe": "wireframe",
    "setdisplaymode ghosted": "ghosted",
    "osnap end toggle enter": "osnap end toggle",
    "osnap mid toggle enter": "osnap mid toggle",
    "osnap center toggle enter": "osnap center toggle",
    "osnap near toggle enter": "osnap near toggle",
    "osnap quad toggle enter": "osnap quad toggle",
    "osnap int toggle enter": "osnap int toggle",
    "osnap perp toggle enter": "osnap perp toggle",
    "disableosnap toggle": "osnap all toggle",
    "maxviewport": "1view",
    "optionspage plugins": "plugins",
    "curvaturegraphoff": "curvaturegraph",
    "deletesubcrv": "split",
    "selprev": "sellast",
    "selpolysrf": "selsolid",
    "selpolysurface": "selsolid",
    "lockalldetails": "detaillock",
    "hatchborder": "hatch",
    "scale1d": "scalenu",
    "boundingbox": "boundingbox",
    "viewcapturetofile": "viewcapturetofile",
    "viewcapturetoclipboard": "viewcapturetoclipboard",
    "snap": "snap",
    "dim": "dim",
    "orient": "orient",
    "orient3pt": "orient3pt",
    "closecrv": "closecrv",
    "clippingplane": "clippingplane",
    "disableclippingplane": "disableclippingplane all",
    "enableclippingplane": "enableclippingplane all",
    "selclippingplane disableclippingplane": "disableclippingplane all",
    "selectionfiltertoggle": "selfiltertoggle",
}


def normalize_rhino_macro(macro: str) -> str:
    """'noecho -Osnap _Mid _Toggle _Enter' -> 'osnap mid toggle enter'."""
    tokens = []
    for tok in macro.replace("!", " ").replace("'", " ").split():
        tok = tok.lstrip("_-'").lower()
        if tok and tok != "noecho":
            tokens.append(tok)
    return " ".join(tokens)


def map_rhino_macro(macro: str) -> str | None:
    """Best Serp3D command (or macro) for a Rhino macro, else None."""
    phrase = normalize_rhino_macro(macro)
    if not phrase:
        return None
    if phrase in RHINO_MACRO_MAP:
        return RHINO_MACRO_MAP[phrase]
    first = phrase.split()[0]
    mapped = RHINO_COMMAND_MAP.get(first)
    if mapped:
        return mapped
    # many Rhino names are also Serp3D names (or aliases) verbatim
    try:
        from ..commands.base import resolve
        cd = resolve(first)
        if cd is not None:
            return cd.name
    except Exception:                                  # noqa: BLE001
        pass
    return None


def parse_rhino_aliases(text: str) -> tuple[dict, list[str]]:
    """Parse a Rhino alias export (.txt): each line 'alias macro'.

    Macros look like '! _Line' or '_Circle _Vertical'. We take the first
    command token, strip Rhino prefixes, and map known commands to their
    serpentine3d names. Returns (aliases, unmapped_names).
    """
    aliases: dict = {}
    unmapped: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        alias, macro = parts[0].lower(), parts[1]
        mapped = map_rhino_macro(macro)
        if mapped:
            aliases[alias] = mapped
        else:
            phrase = normalize_rhino_macro(macro)
            if not phrase:
                continue
            aliases[alias] = phrase.split()[0]
            unmapped.append(phrase.split()[0])
    return aliases, unmapped


def parse_shortcuts(text: str) -> dict:
    """Parse shortcut definitions: JSON, or lines 'F5 zoomextents' /
    'ctrl+shift+b=box'."""
    text = text.strip()
    if text.startswith("{"):
        data = json.loads(text)
        return {str(k): str(v) for k, v in data.items()}
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if "=" in line:
            key, cmd = line.split("=", 1)
        else:
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, cmd = parts
        out[key.strip()] = cmd.strip().lower()
    return out
