"""`serp3d replay` — cook a session journal again.

Check mode is headless and diffs the replayed geometry against the
fingerprints the session wrote; video mode re-executes the session under
a camera and renders a timelapse, which needs a display for GL.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="serp3d replay",
        description="Re-execute a session journal.")
    p.add_argument("journal", help="path to a session .jsonl")
    p.add_argument("--check", action="store_true",
                   help="verify the replay against the session's "
                        "fingerprints (headless)")
    p.add_argument("--video", metavar="OUT.mp4",
                   help="render the replay as a timelapse video")
    p.add_argument("--aspect", default="16:9",
                   choices=["16:9", "9:16", "1:1"],
                   help="frame shape (default 16:9)")
    p.add_argument("--height", type=int, default=None,
                   help="frame height in pixels (default: 1080p the "
                        "right way up for the aspect)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--speed", type=float, default=10.0,
                   help="how many session seconds pass per video second "
                        "(default 10)")
    p.add_argument("--endcard", action="store_true",
                   help="finish with the Built with Serpentine3D card")
    p.add_argument("--no-captions", action="store_true",
                   help="leave the command names off the frames")
    args = p.parse_args(argv)

    from .core.replay import ReplayError, Replayer, load_events
    try:
        events = load_events(args.journal)
    except (OSError, ValueError) as exc:
        print(f"cannot read {args.journal}: {exc}", file=sys.stderr)
        return 2

    if args.video:
        from .media.render import render_replay_video
        try:
            path = render_replay_video(
                events, args.video, aspect=args.aspect, height=args.height,
                fps=args.fps, speed=args.speed, endcard=args.endcard,
                captions=not args.no_captions)
        except ReplayError as exc:
            print(f"replay diverged: {exc}", file=sys.stderr)
            return 1
        print(f"video: {path}")
        return 0

    r = Replayer(events, echo=lambda s: print(f"  {s}"))
    try:
        r.run()
    except ReplayError as exc:
        print(f"replay diverged: {exc}", file=sys.stderr)
        return 1
    n = len(r.scene.all())
    print(f"replayed {len(events)} events -> {n} object(s)")
    if args.check:
        problems = r.verify()
        if problems:
            for m in problems:
                print(f"MISMATCH {m}", file=sys.stderr)
            return 1
        print("fingerprints match: the replay is faithful")
    return 0
