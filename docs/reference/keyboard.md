# Keyboard & mouse

Serpentine3D is command-line first, but the mouse and shortcuts cover
navigation, selection and the common operations. Everything here is
remappable in *Settings → Shortcuts* and *Settings → Mouse*.

## Navigation

| Input | Action |
|---|---|
| **Right-mouse drag** | Orbit (pan in a parallel view) |
| **Shift + right-drag** | Pan |
| **Ctrl + right-drag** | Zoom (drag up to come closer) |
| **Ctrl + Shift + right-drag** | Orbit, even in a parallel view |
| **Alt + right-drag** | Turn to face the nearest axis (see below) |
| **Scroll wheel** | Zoom (anchors on the cursor) |
| ++f1++ / ++f2++ / ++f3++ / ++f4++ | Top / Front / Right / Perspective |
| ++ctrl+e++ | Zoom to fit (extents) |
| ++f7++ | Toggle grid |

These are Rhino's chords. Orbit can be moved to the **middle** mouse button
in *Settings → Mouse*; whichever button orbits is the one that takes the
Shift, Ctrl and Alt chords, and the one that swipes.

## Swipe to an axis

Hold ++alt++ and flick the orbit button the way you want to go. The view
turns a quarter of the way round, then settles on whichever axis is nearest,
so a swipe left from Front lands on Right and a swipe down lands on Top. It
is the quickest way to get somewhere in a single maximised pane, where the
alternative is a function key or the View menu.

The swipe turns the camera and nothing else. Do it in a perspective pane and
you get Top *in perspective*, with an ordinary drag to orbit back out of it.
Do it in a pane that is already parallel, such as one of the four in the
default layout, and you land on the whole named view: construction plane,
label and all, exactly as if you had picked it from the menu.

A flick under about 12 pixels is not a swipe, so ++alt++ and a click still
does whatever it did before.

If nothing happens, check whether your desktop uses ++alt++ and a drag to
move windows: some Linux setups do, and the window manager takes the drag
before Serpentine3D sees it. GNOME and current KDE use the Super key for
that, so this is mostly older or hand-configured setups.

## Views turn rather than cut

The swipe, ++f1++ to ++f4++, the View menu and a pane's own title menu all
turn the camera to the new view over about a fifth of a second. Front and
Back look identical on a symmetric model, so a cut tells you nothing about
where you ended up; the motion does. Anything you do next lands it at once,
so two quick presses are two turns rather than a race, and a script that
sets a view and reads it back still sees the answer immediately.

Change the length, or switch it off, in your settings file:

```json
"display": { "view_transition_ms": 180 }
```

Zero cuts straight there, as it did before.

## Mouse chords

A mouse button held with modifiers can run any command. Add one in
*Settings → Shortcuts*, or write it into your settings file:

```json
"mouse": { "chords": { "ctrl+shift+mmb": "zoomselected" } }
```

The chord fires on a **click**, so a drag with the same keys held still
orbits and pans as before. Only the middle and right buttons can be bound —
the left one is busy selecting. Order and spelling don't matter:
`ctrl+shift+mmb`, `mmb+ctrl+shift` and `shift+ctrl+middle` are one binding.
Nothing is bound out of the box.

## Files & editing

| Shortcut | Action |
|---|---|
| ++ctrl+n++ / ++ctrl+o++ / ++ctrl+s++ | New / Open / Save |
| ++ctrl+z++ / ++ctrl+y++ | Undo / Redo |
| ++ctrl+a++ | Select all |
| ++delete++ | Delete selection |
| ++ctrl+p++ | Export the current sheet to PDF |
| ++ctrl+comma++ | Settings |

## Selection

- **Click** to select; **Shift-click** adds, **Ctrl-click** removes; click
  empty space to deselect.
- **Box selection**: drag **left→right** for a *window* (fully enclosed, gold
  box); **right→left** for a *crossing* (anything touched, white box).
- **Object snaps** — end, mid, center, quadrant, intersection, apparent
  intersection, perpendicular, nearest — toggle on the **osnap bar** under
  the command line. They keep working while a direction is held: the point
  lands on the locked line beside whatever the snap found.
- **AppInt** is the crossing you can see but cannot touch: where a rafter
  passes over a wall in a Top view the two never meet, so **Int** has
  nothing there, and **AppInt** gives you the point anyway, on whichever
  curve is nearer the camera. It belongs to the view you are looking
  through, so it moves when you orbit. Off until you switch it on.

## Control points & sub-objects

<figure markdown="span">
  ![The gumball on a selected solid](../assets/img/gumball.png){ width="640" }
  <figcaption>The gumball: arrows move, arcs rotate, knobs scale — and
  ++ctrl+shift++-click a face for push/pull.</figcaption>
</figure>

| Shortcut | Action |
|---|---|
| ++f10++ / ++f11++ | Show / hide control points (curves *and* surfaces) |
| ++ctrl+shift++ + click | Pick a **face** (push/pull) or **edge** (fillet) of a solid |
| ++tab++ | While a command wants a point: lock the direction you're aiming in, then type the distance. ++tab++ again releases it |
| ++ctrl++ + click | While a command wants a point: stand a vertical up from the point you clicked, then type the height (Rhino's elevator mode) |
| ++ctrl+m++ | Give the viewport you're in the whole window; again puts the layout back. Double-clicking a viewport's title does the same |
| Arrow keys | Nudge the selection along the construction plane (++shift++ ×10, ++ctrl++ ×0.1) |

## Command line

- **Tab** completes command names, except while a command is waiting for a
  point, when it locks the direction instead; **↑ / ↓** recall history.
- **Enter** on an empty line repeats the last command; **Space** is Enter
  too, as in Rhino, so one hand can stay on the mouse (while a command is
  asking for text, such as a layer name, Space is just a space); a
  **right-click** in the viewport is Enter as well — it runs what you've
  typed or repeats the last command. `delete` is never repeated, so a right-click after deleting
  something repeats whatever you were doing before it instead.
- Type command options inline (`cap=n`) or click the chips under the prompt.
- ++f1++ opens the searchable [command reference](commands.md) inside the app.
