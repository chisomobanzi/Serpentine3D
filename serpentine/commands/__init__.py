"""Command registry: importing this package registers all built-in commands."""

from . import (  # noqa: F401
    base, boolean, curves, drafting, edit, file, select, solids,
    solids_edit, surfaces,
    transform,
    view,
)
from .base import (  # noqa: F401
    CommandContext, CommandProcessor, all_commands, command, completions,
    resolve,
)
