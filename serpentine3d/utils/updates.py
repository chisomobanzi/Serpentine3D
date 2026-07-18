"""Check GitHub Releases for a newer Serpentine3D and point at the download.

Pure and fail-silent: the network call is injectable (``fetch=``) so the
logic is testable without HTTP, and any failure (offline, rate-limited, bad
JSON) just returns ``None`` — a background update check must never disrupt
launch. The anonymous GET to GitHub is the only thing that leaves the
machine; nothing is phoned home.
"""

from __future__ import annotations

import json

REPO = "chisomobanzi/Serpentine3D"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"

# platform.system() -> the installer asset suffix for that OS
_SUFFIX = {"Linux": ".AppImage", "Windows": ".exe", "Darwin": ".dmg"}


def parse_version(text: str) -> tuple:
    """'v0.3.1' / '0.3' -> (0, 3, 1) / (0, 3). Leading v/V and a
    non-numeric tail on any component are ignored."""
    out = []
    for part in text.strip().lstrip("vV").split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    """Is release string `latest` newer than `current`?"""
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def asset_for_platform(assets: list, system: str) -> str | None:
    """The download URL whose asset matches this OS, or None.
    `system` is platform.system(): 'Linux' | 'Windows' | 'Darwin'."""
    suffix = _SUFFIX.get(system)
    if not suffix:
        return None
    for a in assets:
        if str(a.get("name", "")).endswith(suffix):
            return a.get("browser_download_url")
    return None


def parse_release(data: dict, system: str) -> dict:
    """Normalise a GitHub release payload to {version, url, download}."""
    return {
        "version": str(data.get("tag_name", "")).lstrip("vV"),
        "url": data.get("html_url", ""),
        "download": asset_for_platform(data.get("assets", []), system),
    }


def check_for_update(current: str, system: str, *, fetch=None) -> dict | None:
    """Return {version, url, download} if a newer release exists, else None.
    Never raises — any error returns None. `fetch` is a no-arg callable
    returning the raw JSON (str/bytes/dict); defaults to a live GET."""
    try:
        raw = (fetch or _fetch)()
        data = raw if isinstance(raw, dict) else json.loads(raw)
        rel = parse_release(data, system)
        if rel["version"] and is_newer(rel["version"], current):
            return rel
        return None
    except Exception:
        return None


def _fetch() -> str:
    from urllib.request import Request, urlopen
    req = Request(RELEASES_API, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "Serpentine3D-update-check",
    })
    with urlopen(req, timeout=4) as resp:   # noqa: S310 (fixed HTTPS URL)
        return resp.read().decode("utf-8")
