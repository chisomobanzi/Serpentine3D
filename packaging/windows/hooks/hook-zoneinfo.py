# ------------------------------------------------------------------
# Local override of the contributed hook-zoneinfo.py hook.
#
# The upstream hook does, unconditionally on Windows:
#
#     hiddenimports = ['tzdata']
#
# Its rationale is that CPython's zoneinfo has no built-in tz database and
# reads IANA zones from the `tzdata` package. That package is an install-time
# dependency here, so the unconditional demand turns into
# 'Hidden import "tzdata" not found!' on every build.
#
# Nothing in this application resolves IANA zone keys:
#   * serpentine3d does not import zoneinfo/dateutil at all;
#   * the only site-packages references are numpy's doctest example and
#     Babel, which is a docs-only dependency and never imported at runtime.
#
# So the zoneinfo stdlib module itself still ships (it stays in the module
# graph and its hook stays a no-op); only the unresolvable `tzdata` demand is
# dropped. This is a targeted hook override via Analysis(hookspath=...),
# which PyInstaller gives the highest hook priority, so the contributed
# hook is shadowed rather than merged. If a future feature starts resolving
# real IANA zone keys, install the `tzdata` dependency instead of extending
# this override.
# ------------------------------------------------------------------