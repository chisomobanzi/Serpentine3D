"""Command registry: importing this package registers all built-in commands."""

from . import (  # noqa: F401
    base, boolean, camera_cmds, curves, deform_cmds, drafting, edit, file,
    organize,
    select, solids,
    solids_edit, surfaces, surfaces2,
    transform,
    view,
)
from .base import (  # noqa: F401
    CommandContext, CommandProcessor, all_commands, command, completions,
    resolve,
)
