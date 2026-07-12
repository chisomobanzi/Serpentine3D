"""Regenerate docs/commands.md from the live command registry.

    .venv/bin/python docs/gen_commands.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serpentine.commands.help_cmd import command_reference  # noqa: E402


def main():
    lines = [
        "# Command reference",
        "",
        "Every command is typed on the command line (Tab completes,",
        "F1 opens this list inside the app). Aliases in parentheses.",
        "",
    ]
    for section, cmds in command_reference().items():
        lines.append(f"## {section}")
        lines.append("")
        lines.append("| Command | Does |")
        lines.append("|---|---|")
        for name, aliases, doc in cmds:
            label = f"`{name}`"
            if aliases:
                label += " (" + ", ".join(f"`{a}`" for a in aliases) + ")"
            lines.append(f"| {label} | {doc} |")
        lines.append("")
    out = os.path.join(os.path.dirname(__file__), "commands.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
