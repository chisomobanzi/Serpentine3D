"""Command registry: importing this package registers all built-in commands."""

from . import (  # noqa: F401
    base, boolean, curves, edit, file, solids, surfaces, transform, view,
)
from .base import (  # noqa: F401
    CommandContext, CommandProcessor, all_commands, command, completions,
    resolve,
)
