"""Serpentine3D — an open-source NURBS modeller for Linux."""

__version__ = "0.7.2"


def version_line() -> str:
    """What every entry point prints for ``--version``.

    Here rather than in one of them because they all have to agree, and
    because this module is the only thing cheap enough to import when the
    build you are questioning may not survive importing anything else.
    """
    return f"Serpentine3D {__version__}"
