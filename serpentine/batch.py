"""Headless batch runner:  serp-batch script.py [args...]

The script runs with these names predefined:
    doc   — a serpentine.scripting.Document (fresh, or opened via --open)
    geo   — the geometry module
    args  — remaining command-line arguments

Example script:
    doc.add(geo.make_box((0, 0, 0), 100, 100, 100), name="Crate")
    doc.run("filletedge", ["Crate", "", "5"])
    doc.export(args[0] if args else "crate.step")
"""

from __future__ import annotations

import os
import sys


def main(argv: list | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    open_path = None
    if "--open" in argv:
        i = argv.index("--open")
        open_path = argv[i + 1]
        del argv[i:i + 2]
    if not argv:
        print(__doc__)
        return 2
    script_path = argv[0]
    if not os.path.exists(script_path):
        print(f"serp-batch: script not found: {script_path}",
              file=sys.stderr)
        return 2

    from .core import geometry as geo
    from .scripting import Document

    doc = Document(open_path)
    namespace = {
        "__name__": "__main__",
        "__file__": os.path.abspath(script_path),
        "doc": doc,
        "geo": geo,
        "args": argv[1:],
    }
    with open(script_path) as f:
        code = compile(f.read(), script_path, "exec")
    try:
        exec(code, namespace)                       # noqa: S102
    except Exception:                               # noqa: BLE001
        import traceback
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
