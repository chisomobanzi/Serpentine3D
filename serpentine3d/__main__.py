"""``python -m serpentine3d`` → the splash-first launcher."""

from .launcher import main

# Guarded, and it has to stay that way: the .3dm importer spawns a helper
# process, and spawn re-imports this module in the child as `__mp_main__`.
# Unguarded, every import opened a second copy of the app.
if __name__ == "__main__":
    raise SystemExit(main())
