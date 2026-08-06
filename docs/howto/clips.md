# Make a clip of your work

Serpentine3D can turn what you model into video two ways: a **turntable**
of the finished thing, and a **timelapse replayed from the session
itself**. Neither records your screen.

## The turntable

Type `turntable`. It asks for a length in seconds, a shape for the frame
(16:9 for a video, 9:16 for a reel, 1:1 square) and where to put the
file, then walks the camera once around the model and writes an .mp4.
If anything is selected it orbits the selection; otherwise it orbits
everything. Frames render at full resolution regardless of the window,
so a small laptop screen still produces a 1080p clip.

The encoder is ffmpeg, found on your system. Without it you get the
frames as numbered PNGs and the one command line that assembles them.

## The session timelapse

Serpentine3D keeps a **journal** of every session: each command and every
point, number and selection it actually received, resolved through snaps
and planes, written as it happens to
`~/.local/share/serpentine3d/journals/`. The journal is a recipe — the
whole session can be cooked again.

```
serp3d replay <journal.jsonl> --check
serp3d replay <journal.jsonl> --video build.mp4 --speed 10 --endcard
```

`--check` re-executes the session headless and verifies the geometry
comes out identical to what you saved. `--video` re-executes it under a
slow orbiting camera and renders a timelapse: your pauses are compressed
by `--speed`, every command appears in a caption band as it runs, and
`--aspect 9:16` makes a reel of the same session without remodelling
anything. A fumbled take never appears, because the journal only holds
what was actually done.

Because the video is rendered rather than recorded, you can make it
again tomorrow, taller, faster, or at a different resolution.

## The end card

`--endcard` (or the `media.endcard` setting, for the turntable) closes
the clip with a quiet dark card: *Built with Serpentine3D* and the
address. It is off unless you ask for it.

## What the journal is for besides video

A journal is also the best bug report there is: a file that reproduces
your whole session, keystroke for keystroke, on someone else's machine.
If something misbehaves, attach the journal from
`~/.local/share/serpentine3d/journals/` to the issue. Set
`SERP3D_NO_JOURNAL=1` if you would rather no journal were kept.
