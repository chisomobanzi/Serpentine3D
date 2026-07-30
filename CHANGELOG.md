# Changelog

## Unreleased

### Added

- You can draw on the sheet itself. A border, a title strip, a detail bubble, a
  north arrow — `line`, `polyline`, `curve`, `circle`, `arc`, `ellipse` and
  `rectangle` now draw on the paper when you are on a sheet with no detail
  entered, in millimetres, and leave the model alone. Inside a detail
  the same commands draw in the model, where the detail is looking, so nothing
  about drawing in a detail or in the model changes. Paper geometry is a real
  shape rather than a list of points, so it is saved with the sheet, carries its
  own colour, linetype and lineweight, is drawn over the details the way the
  annotations are, and comes back with an undo. A lineweight is millimetres on
  the printed page — 0.25 by default, 0.7 for a border that should look like
  one — so it prints at the width it says and is only floored at one pixel on
  screen, where a quarter of a millimetre is a quarter of a pixel. It goes out
  with the sheet to PDF and to DXF, where it lands on its own `PAPER` layer so a
  border can be turned off without losing the drawing it frames. Files written
  before this still open, and files with paper geometry in them open in 0.5.5 as
  sheets without it.

- Paper geometry can be picked. A click on a border, a bubble or a title strip
  selects it, Shift or Ctrl adds to the selection, a band takes several, the
  cursor drags what is picked across the sheet, typed coordinates move it, and
  Delete takes it off in one undo. It is picked by its ink, the way a curve is
  in the model, so a click inside a border means the page and not the border,
  and a crossing band inside one leaves it be. Picked geometry goes gold
  instead of getting a dashed box around it: two lines that overlap share a
  box, and the point of picking one is knowing which you have. A click lands on
  the annotations over the geometry first and on the geometry before the detail
  frames it is drawn across — the order it is all painted in, read from the top
  down.

- The properties panel shows the paper geometry picked on a sheet: its name, its
  ink, its dash pattern and its printed width, each one edit and one undo. The
  rows on offer are the ones that mean something there — no layer, because the
  sheet is its own ink and paper geometry is not on a model layer, and a
  lineweight and a linetype, which are a printed drawing's business and not a
  model object's. It is measured in millimetres of paper whatever the document's
  units are, and the type says "Curve on paper" so a curve on the sheet cannot
  be mistaken for one in the model. Colour falls back to the sheet's ink rather
  than to a layer's, so the reset beside the swatch reads "By sheet".

- `detail` shows you the view while you are still deciding where to put it. The
  frame is dragged as a gold dashed rectangle with the model live inside it, at
  the scale you asked for, and a readout at the corner gives its width, its
  height and that scale — so "will the plan fit on this sheet at 1:50" is a
  question you answer by looking rather than by placing a detail and undoing it.
  The view direction and the scale are asked first, because they are what the
  frame is a window onto and there is nothing to draw inside it until they are
  answered. The preview is wireframe while it moves and the placed detail is
  hidden-line as before: a hidden-line pass is one projection of the whole model,
  which is not something to repeat on every mouse move. There is no rubber band
  on the second corner any more — the frame shows both corners, and a diagonal
  drawn across the view being framed hides the one thing worth looking at.

- The model can be reached through a detail you have stepped into: its features
  snap, and its objects are picked. End, mid, centre, quadrant, intersection,
  perpendicular and nearest all find model geometry through the detail, so a
  line drawn between two corners of a solid on a sheet comes out on those two
  corners at the model's own coordinates rather than near them. A snap is looked
  for before the grid, as it is in the model window, and it reaches geometry that
  is not on the plane the detail's free picks land on — a corner behind that
  plane snaps, which is what makes a detail a window rather than a tracing sheet.
  The marker is drawn on the paper, squared to it, at the place in the frame
  where the model point appears.

  A click inside a detail picks the model object under it: Shift or Ctrl adds and
  toggles, a click on nothing clears, Ctrl+Shift picks an edge or a face, and a
  band swept inside the frame takes a window or a crossing of what it covers. The
  object goes gold in every detail it appears in, because one model object seen
  through two windows is still one object, and the commands that ask for objects
  — `delete`, `move`, `copy` — are answered by what was picked on the sheet. What
  a detail clips at its frame is not pickable through it, however near the paper
  says the cursor came, and faces answer to the detail's own display mode: a
  wireframe detail has edges to hit and no faces. Picking does not step you back
  out of the detail, and a click on the paper outside one still picks the sheet's
  own geometry, its frames and its corners. The readout counts what is picked in
  a detail as the model objects it is, not as the nothing the sheet had picked.

- The gumball comes with what you pick in a detail. Stepping into a detail and
  clicking a model object puts the same handles on it that the model window
  gives it, and they are dragged the same way: an arrow moves, a knob scales, a
  pad moves in a plane, a circle rotates, and a click that does not move arms
  the handle so an exact number can be typed instead. The readout follows the
  drag on the paper. The axes are the detail's own — the plane it looks at —
  rather than the model window's construction plane, so in a front view the
  arrows go across and up the page and the third one runs away from you, which
  is the way the drawing is being read.

  A detail looks squarely down one axis, and squarely down an axis a third of
  the handles have no drag in them: an arrow pointing straight at you cannot be
  pushed anywhere and a circle seen exactly edge-on has no arc to follow. Those
  are left out rather than drawn and refused — edge-on they land right on top of
  the handles that do work, and a handle you cannot use is worse than no handle.
  The rest are drawn over the drawing rather than in it, so an object that
  nearly fills its frame still has handles you can reach past the edge of it.

- A hidden-line detail shows what is picked. Such a detail is line work and
  nothing else — no faces to tint — and the line work was one heap of polylines
  with nothing in it to say which object each came from, so an object picked
  through one was gold in every other frame on the sheet and black in the frame
  you picked it in. Its outline now goes gold like anywhere else, and a detail in
  technical mode with it. The hidden-line pass already keeps its visible edges
  apart per object, to give each one its own dash pattern; carrying the object's
  name out alongside them is enough, because the ink is then chosen when the
  frame is painted. So picking something does not send the projection round
  again, which is the expensive part and the reason the result is cached. A
  picked object keeps its dashes, since going gold says that it is picked and not
  that it is solid, and gold is drawn last, so an edge shared between a picked
  object and one that is not reads as picked. What goes to PDF and to DXF is
  unchanged: a print has no selection in it.

  Not yet: the dashed lines behind an object are computed in one pass over the
  whole model and come back undivided, so they stay grey under a picked object,
  as do the faces a section cut fills in.

- `point` works on a sheet. It was refused there, and the reason was honest: a
  point object is a vertex, a vertex has no edges, and the sheet drew geometry
  by walking edges, so the point would have been stored and never seen again.
  The sheet draws vertices now — a small cross, the same size on screen however
  far the page is zoomed, since a point says where something is and has no size
  of its own. It is geometry like the rest of what is on the paper: clicking the
  cross picks it, either band takes it, it goes gold when it is picked, Delete
  removes it, and it is still there when the file is opened again. Placed inside
  a detail it is a model point, as everything drawn through a detail is.

  A point is a mark to work to rather than ink, so it is not printed — the same
  as in Rhino, and the reason nothing changed in the PDF or DXF export.

- `delete` takes what is picked on a sheet. It never asked the sheet at all, so
  a border or a detail frame picked on paper and then deleted left the command
  waiting for a model selection that no click on bare paper can make: it sat
  there until it was cancelled, and nothing was deleted. It removes them now,
  says how many, and Ctrl+Z brings them back. The Delete key always did this,
  and now the typed command agrees with the key.

  `move` had the same question the other way round: it asked only the sheet, so
  a model object picked through a detail was told that nothing was picked, when
  plainly something was. Both go through one rule now, and it is the rule that
  already decides where a drawn point lands — a detail is a window onto the
  model, so inside one a command works on the model and asks for objects by
  clicking them through the frame; on bare paper there is no model to ask about,
  so the sheet is the answer.

- `copy` follows the same rule. On a sheet it duplicates what is picked —
  geometry, detail frames, annotations — offset by paper millimetres, and keeps
  going until you press Enter, the way it always has in the model. Before, it
  was one of the commands that waited on bare paper for a selection that could
  not be made. Inside a detail it still copies model objects.

  The copy is a new thing on the page and not a second name for the old one: it
  gets its own id, its own shape and its own copy of anything the original held,
  so panning one detail does not swing the other. The originals stay picked and
  untouched, which is what lets a locked frame be copied — the lock is about the
  frame not being disturbed, and it is not — and means each repeat is measured
  from the same place rather than walking away from it. The whole command is one
  undo, however many copies it made.

- Ctrl+C and Ctrl+V work on a sheet, and carry across sheets. Copy takes what
  is picked on the paper — geometry, detail frames, annotations — and paste
  puts it onto whichever sheet is showing, which need not be the one it came
  from: that is how a title block gets from the first sheet to the rest. What
  lands arrives at the same millimetres it was copied from and arrives picked,
  so it can be moved into place at once and so you can see it arrived at all.
  One undo takes back the whole paste.

  The two halves ask different questions on purpose. Copy asks where you are,
  because a sheet has two things on it that could be meant — inside a detail it
  still copies model objects. Paste asks the clipboard, because what it holds
  is not in doubt: model objects go to the model wherever you are standing, and
  it says so when you are on a sheet at the time, since from bare paper they
  land somewhere you cannot see. Sheet items in the model window say to switch
  to a sheet rather than going quiet.

  Copy and paste now say what they did through the same channel as every other
  command, so scripts and the RPC bridge hear them too.

- Zoom drives what you are actually looking at. Every zoom drove the model
  camera, which on a sheet is the one thing you cannot see: `zoom Extents` on
  bare paper silently re-aimed it and left the page exactly where it was, and
  `zoom Window` was refused outright, because a window wants two points and
  bare paper has no model point to give. Inside a detail both moved the camera
  and left the detail alone.

  On bare paper a zoom is now about the page. `zoom Window` frames the
  millimetres you picked, `zoom Selected` frames what is picked on the sheet,
  and `zoom Extents` shows the whole page — together with anything dragged off
  the edge of it, which is the case you most need a way back from. Inside a
  detail a zoom is about the detail: the window you pick is model points, as
  every point in a detail is, and the detail is re-aimed and re-scaled to show
  it, exactly as rolling the wheel there does. A locked detail stays put, for
  the same reason the wheel leaves it alone. `zoom In` and `zoom Out` go
  through the wheel itself, so typing them and rolling it are one behaviour
  rather than two that have to agree.

  Answered once, where the viewport decides, rather than in each command — so
  the RPC bridge, the file-open fit and an extra pane opened straight onto a
  sheet all follow the same rule.

### Fixed

- The welcome screen stays above the window it opened over, on macOS and
  Windows. It asked for a plain window type of its own on every platform, which
  is what Linux needs — GNOME glues a dialog to the main window otherwise — but
  everywhere else nothing was gluing it to anything, so all that bought was a
  window that could fall behind the one it belongs to. It now goes through the
  same rule the file picker and the settings panel do, which asks that only
  where it is needed and centres the screen over the window either way.

- A drawing saved by a newer build opens in an older one. Detail frames and
  annotations were rebuilt from the file by handing it straight to the class,
  which meant the file had to name exactly the fields that build had. It never
  will for long: the moment a field is added — a detail's section plane, a
  note's style — a sheet saved by the newer build stops opening in the older
  one, and not with the new field missing but with an error and no drawing at
  all. One stray key cost you the whole file.

  A field this build has never heard of is now let go, and a field the file
  never mentions takes its default. It is let go rather than kept, so that the
  next save does not write back something this build never drew and claim to
  have meant it — which does mean a sheet saved by an older build loses what
  that build could not read. Losing a field there is no way to draw is a small
  loss; refusing to open the drawing is a total one.

- A detail you have stepped into is a window into the model, and drawing through
  it works like one. Two things stopped it. The construction plane inside a
  detail was still the world plane, so a rectangle drawn in a front, side or
  back view had both of its corners on one line of that plane and came out
  degenerate — nothing was made and the command reported an error — while a
  circle, an arc or an ellipse came out lying flat in world XY, edge-on to the
  view it was drawn in, which also looks like nothing was made. The plane inside
  a detail is now the plane the detail looks at, which is where its picks land
  already, so everything built on a plane — rectangles, circles, arcs, polygons,
  the direction an `extrude` goes, the axis a `revolve` turns about — is built in
  the view you are looking at.

  And a command that is waiting for a point never saw the double-click that
  steps into a detail: the press picked a point before the second click arrived,
  so the clicks meant as a way in landed on the paper and drew there instead. On
  a sheet, a click that lands on a detail while a command wants a point now steps
  into that detail and says so, and the clicks after it draw through it. A click
  on the detail you are already in is a point, as it was, and a command that
  wants paper millimetres — `text` and the dimensions — is not diverted into a
  detail by one.

  Geometry drawn in a top or bottom view also comes out level now. Those views
  are aimed a tenth of a degree off vertical so the camera basis cannot
  degenerate, and a line drawn through one used to inherit that lean; the basis a
  detail measures geometry in is now squared to the axes it is a whisker from,
  while the camera keeps its tilt.

- The preview of what a command is about to make is drawn on a sheet, and in
  technical display mode. `rectangle` on a sheet showed a single line from the
  first corner to the cursor and no rectangle — and so did `circle`, `arc` and
  `ellipse` — because a sheet drew the rubber band and never asked for the shape
  at all. Technical display mode in the model had lost it the same way, for every
  command that previews one, `box` and `extrude` included. Both are drawn by one
  call now, so a paint path cannot pick up one and forget the other, and a
  preview of model geometry drawn inside a detail comes back out through that
  detail rather than sitting on the sheet at the model's own numbers.

- A preview is cleared from every pane it was drawn in. It was set on all of
  them and cleared on one, so in a split view the panes you were not working in
  kept the last ghost of a finished command.

- Edges stop going missing. A shape's edge list was de-duplicated on a key that
  described nothing: OCC hands back a fresh wrapper object each time it is asked
  for an edge's underlying shape, and the key was that wrapper's address. So a
  freed address handed out again for the next edge read as a duplicate, and one
  of two different edges silently disappeared — a box that printed without its
  top edge, a rectangle that drew with three sides, free points in a compound
  that went unplotted. Rare, and it moved around, because it depended on
  what the allocator handed out. The edge itself is the key now. Shared edges
  are also de-duplicated for real for the first time, so a solid's linework is
  drawn once rather than once per face it belongs to.

- Drawing inside a detail draws in the model, where the detail is looking. A
  sheet has two spaces on it — the paper is millimetres, a detail is a window
  onto the model — but a pick used to be paper millimetres either way, and
  every command that draws believed it had been handed a model point. So a
  `line` on a sheet quietly put a curve in your *model* at the paper's
  coordinates, and doing it inside a detail did the same thing rather than
  drawing where the detail was pointed. Now a pick inside a detail comes back
  as the model point that detail shows, on the plane it looks at, and the grid
  snaps in model units there because a round number belongs to the geometry
  being built and not to the paper it is seen through. The rubber band and the
  length readout come back out through the same window, so they land on the
  geometry you picked from instead of at the model's own numbers on a sheet
  measured in millimetres. Typing a coordinate inside a detail still means the
  model coordinate you typed; it is the cursor that needed translating.

- On bare paper, a command that needs a model point says so instead of
  guessing. There is no model point out on the paper, and answering with
  millimetres was how the geometry ended up in the model at the paper's
  numbers. Each command now declares which space its points are in, so a `box`
  or an `extrude` stops at the prompt and names both ways on — double-click a
  detail to work inside it, or annotate the sheet with `text`, `dim`, `leader`
  or `hatch` — while `text`, `dim` and the rest of the paper commands are
  unaffected, inside a detail as much as out, and the curve commands draw on the
  paper instead (see Added). The refusal happens at the point
  prompt rather than at the command, so `zoom` still offers Extents, In, Out
  and Selected on a sheet and only declines its Window.

- The length readout appears while you draw on a sheet. It was positioned with
  the model camera, which is not what is on screen there, so it went wherever
  that camera happened to be looking. It now sits by the cursor on the paper,
  and a leg is measured where it was drawn: in model units through a detail, in
  millimetres on the paper itself, whatever units the model is drawn in.

## 0.5.5 — 2026-07-30

### Added

- You can drag a selection on a layout sheet, and pick more than one thing at a
  time. Dragging on empty paper sweeps a band out of it: left to right takes
  what it wholly encloses, right to left takes anything it touches, the same
  hand as in model space, so the habit carries between the two. Shift or Ctrl
  adds to what is already picked, whether you click or sweep, and Escape drops
  the lot. Dragging any one of the picked items moves all of them, Delete
  removes all of them in a single undo step, and the status bar counts what is
  picked on the sheet instead of reporting the model selection — which was
  always `0 selected` there, and was most of why picking on a sheet looked
  broken even though clicking a detail had always selected it. Resize grips
  still belong to a lone detail, since dragging one corner of five rectangles
  would have to mean something for the other four and it does not.

- A detail frame's corners are things you can pick, not just handles you can
  drag. Select a detail and click one of its gold grips: the corner fills dark
  to say it is chosen, and `move` then puts it at typed paper millimetres
  instead of wherever your hand lands. A corner is where two edges meet, so
  moving one alone stretches the frame in both directions; Shift-click the two
  corners of an edge and that edge travels; take all four and the whole detail
  does. Dragging works on the whole picked set too, so a grip drag can now move
  an edge. With no corner picked, `move` on a sheet moves whatever else is
  picked there — details and annotations alike, in millimetres on the paper.
  Escape lets go of the corner first and the detail second, and none of it
  touches the model.

- The command line finishes the name for you. Type `deta` and the box reads
  `detail`, with the letters you did not type selected, so Enter — or a
  right-click in the viewport — runs the whole command instead of reporting
  `Unknown command: deta`. Tab cycled through the matches before this, but
  cycling is invisible until you press it and nobody presses a key to find out
  whether it does anything, so in practice every command had to be typed out in
  full. The other matches are listed above the prompt; Up and Down walk them
  while the list is up and go back to walking the history when it is not, Tab
  still cycles, and clicking one runs it. What was run lately is guessed first
  and the plain command comes before the variants built on it, because
  alphabetical order offers `tolerance` to someone typing `to`. A name that is
  already a command is never quietly extended — `line` does not become
  `linetype` under your fingers, and `l` stays the alias for line rather than
  turning into `layer` — nothing is guessed over a backspace, and nothing is
  guessed at all while a command is asking for a value, where the words belong
  to the command and not to the registry.

- Mouse chords: a mouse button held with modifiers can now run any command,
  the way a key already could. Bind one in *Settings → Shortcuts* or write it
  straight into settings — `"mouse": {"chords": {"ctrl+shift+mmb":
  "zoomselected"}}` — and Ctrl+Shift with a middle click zooms to what's
  selected. It fires on a click, not on the press, so the same keys held
  through a drag still orbit and pan; the middle and right buttons can be
  bound, the left one being busy selecting. Order and spelling are yours to
  choose: `ctrl+shift+mmb`, `mmb+ctrl+shift` and `shift+ctrl+middle` are one
  binding, so nobody has to guess the house style. Nothing is bound out of
  the box, so the mouse behaves exactly as it did until you ask otherwise.
  Keys and chords now share one Settings page, since both answer the same
  question and which device a binding lives on is a poor thing to have to
  guess at.

- `--version` (and `-V`) on every command: `serp3d`, `serp`, `serp3d-batch`
  and `serp3d-mcp`. An installed build is one opaque file — an AppImage, a
  .dmg, an .exe — and until now the only place the version appeared was the
  splash screen, so answering "which build is this?" meant launching the
  whole app. `serp3d` and `serp3d-batch` answer before Qt or the geometry
  kernel is loaded, which matters because you reach for `--version` when a
  build is misbehaving, and a build broken enough to ask about may not
  survive importing 150 MB of OpenCASCADE to tell you.

### Fixed

- Placing a detail view on a layout no longer opens copies of the
  application. Hidden-line removal runs in a worker process, because OpenCASCADE
  can crash on a drawing seen edge-on and losing one detail beats losing the
  session. The worker was started as `sys.executable -m serpentine3d.core.hlr`,
  and in an installed build `sys.executable` is the application, not python:
  the flags meant nothing to it, so it did what it does when it is handed
  arguments it cannot read — it opened a window. The copy never answered, the
  drawing sat waiting on a pipe with no timeout, and the next repaint started
  another one. Reported as a crash, and on a machine with a few gigabytes to
  spare that is how it ends. The worker is now named properly — the interpreter
  inside the bundle where there is one, otherwise the app re-run with a flag it
  answers before it loads any of the graphics stack — a build with no way to
  start a worker at all does the work in-process instead of launching anything,
  and a worker that stops answering is given up on rather than waited for.

- The Settings window can be moved on its own again. GNOME attaches modal
  dialogs to their parent, so Settings was pinned to the middle of the
  drawing it was about and dragging it dragged the whole application along
  behind it — no way to put the panel beside the model and watch a setting
  take effect. Four places had already met this and each dodged it privately;
  Settings, opened the same way, never did. The dodge now has a name and one
  home, and the rule that no dialog is glued to the window that opened it is
  checked for every dialog the app puts on screen rather than remembered a
  fifth time.

- Dragging with the gumball no longer occasionally leaves the drawing
  behind. The object really did move — the gumball sat where it now was,
  and nudging it again made the picture catch up — but the shaded faces
  went on being drawn at the old position. What is uploaded to the graphics
  card was remembered against the *address* of the display mesh it came
  from, and an address is not an identity: moving something builds it a new
  mesh and drops the old one, and CPython hands the freed address straight
  back out. Measured, a new mesh lands on a dead one's address 49 times out
  of 50 in a tight loop, and about 1 time in 20 across a real move, where
  meshing allocates other things in between — which is exactly why it
  happened sometimes and would not reproduce on demand. So the question
  "are these still the right buffers?" was answered yes about a mesh that
  no longer existed. It also explained the odd way it looked: sub-object
  highlights are rebuilt from the geometry every frame, so the yellow was
  at the new position while the grey box behind it was still at the old
  one. Display meshes now carry a serial number that is never reused.

- Editing something while it is still being meshed no longer strands it as
  a wireframe box. Anything heavy enough is meshed on a worker and drawn as
  its bounding box in the meantime; that work was tracked per object, so an
  edit landing mid-build looked like work already in hand. Nothing then
  meshed the new shape, and the box standing in for it stayed where the old
  shape had been. It is now tracked per shape, so replacing the geometry
  queues the new one and moves the placeholder with it.

- Zoom Selected now fills the viewport with what you selected, instead of
  leaving it small in the middle. It framed the *sphere* around the
  selection in the *vertical* field of view and then backed off another
  15%, and all three parts of that gave away room: the sphere around a box
  is half its diagonal where the box on screen is only about half its
  height, the window is wider than it is tall so the sides went unused, and
  the 15% came on top of both. A wide flat model — a set, a floor plan,
  most of what anyone zooms to — came back reaching under half the frame in
  each direction, so filling about a quarter of the picture. It now puts
  the eight corners of the selection on the camera's own axes and stops at
  the distance where the outermost one reaches the edge, reading the shape
  of the window as it goes. Zoom Extents and the zoom window use the same
  fit, so they frame the same way.

- Opening a big file no longer spends seconds redrawing panels nobody has
  looked at yet. Every object added announced itself, and two of the things
  listening answer by reading the whole scene — the layers panel rebuilds
  its tree and counts what is on each layer, the status bar counts the
  objects. So importing n objects meant n walks of a scene on its way to
  holding n of them, and the cost of adding one grew with how full the
  scene already was: 0.08 ms into an empty scene, 0.71 ms into one already
  holding 4000. On the 522 MB cave file that was 7064 announcements and
  3.1 seconds of the open. Nothing wanted the states in between. Imports,
  arrays and paste now make the whole change and announce it once — 3.1
  seconds to none — and the announcement is still sorted by kind, so a
  panel that only asked about layouts is not woken by objects arriving.

- Orbiting and panning with a lot selected is no longer slower than orbiting
  with nothing selected. On a 522 MB cave file a frame took 121 ms with
  nothing selected and 1092 ms with all 7064 objects selected — nine times
  slower for a view change that has nothing to do with what is selected. Two
  things were walking the whole selection every frame. The draw loop asks
  "is this one selected?" once per object, and the answer was found by
  reading the selection rather than indexing it, so a frame cost objects
  times selection: 190 ms of it. The gumball worked out where to sit by
  taking the bounding box of every selected object again, which is about
  100µs an object and was 747 ms — and it did it a second time on every
  mouse move, for the hover test. Objects now remember their own bounds
  until their geometry is replaced, and the selection is indexed as well as
  ordered. Selecting the whole drawing now costs 0.1 ms a frame rather than
  971.

- Opening a drawing with a survey scan in it no longer freezes the window
  after the file has finished loading. The viewport already kept heavy
  tessellation off the thread that draws, but meshes skipped that check
  entirely on the grounds that they convert instantly — true of the couple
  of hundred small ones in a drawing, and false of a scan. Arriving as a
  mesh is not arriving ready to draw: Rhino's own vertex normals cost 36µs
  each to read, 239 s for one 6.6-million-vertex object, so the shading is
  worked out from the geometry instead, and that takes ten seconds. On a
  522 MB cave file two such scans held 13.2M of 16.8M vertices and cost 26
  of the 29 seconds the window spent unresponsive. Meshes past 20,000
  vertices now build in the background behind a bounding box like any other
  heavy shape, which moves 24 of those 25 seconds off the drawing thread —
  and the two scans overlap rather than taking turns, so they cost 12
  seconds between them rather than 22.

### Internal

- The rule that what is drawn must be the geometry the scene holds is now
  stated once and checked, rather than relied on. Three bugs in a row were
  the same shape — the model changed and the picture did not follow — and
  each was found by eye, on one command, by luck. Thirty-eight editing
  sessions now run against the invariant, each of them three times over:
  as the edit happens, across undo and redo, and again with everything
  treated as heavy enough to mesh in the background with the queue held
  back, so the edits land on geometry that is still being built. The check
  is proved able to fail by putting each of the two original bugs back and
  watching it catch them, and a scenario that edits nothing is a failure
  rather than a quiet pass.

## 0.5.4 — 2026-07-29

### Added

- Direction lock, on `Tab`. While a command is asking for a point, `Tab`
  freezes the direction you are pointing in so the cursor only sets how far
  along it to go — aim once down the wall you are continuing, then type the
  length. Ortho already did this for the four CPlane directions; this does
  it for the direction you are actually in, which is the case ortho misses.
  `Tab` again releases it, and it lapses on its own once the command moves
  on to the next point. As in Rhino it holds the whole line, so you can
  still cross back over the base point and pick the other way along it.
- An isometric view, on `F5`, the View menu, the viewport's view chip and the
  `isometric` (`iso`) command. It looks from the same corner Rhino's
  `SEIsometric` does, at the one tilt that foreshortens all three axes
  equally, so a cube reads as a cube and you can measure along all three
  directions off the same picture. Detail views on a layout can use it too.

### Changed

- Big meshes are made ready to click on about a third faster. Both the pick
  index and an object's bounding box were read with a reduction that walks
  memory in strides rather than straight through; on the 522 MB survey this
  is measured against, indexing everything that wants an index went from
  3.17 s to 2.08 s, and a click that has to build its own index first went
  from 2.87 s to 1.86 s. Nothing about which object you get has changed.
- The MCP server runs on `mcp` 2.x. 0.5.3 capped the dependency below 2.0 to
  stop fresh installs picking up a release the server could not import; the
  server is now written against 2.x's `mcp.server.mcpserver` and the cap is
  gone, so `serp3d-mcp` installs alongside the current SDK rather than
  holding an MCP client back to last year's. The tools, their names and their
  arguments are unchanged — nothing a client already talks to has moved.
  `httpx`, which the AI assistant uses directly, stays declared in its own
  right now that `mcp` no longer brings it along.

### Fixed

- Blocks come in from a `.3dm`. An instance imported as nothing at all, and
  the definition it placed imported as loose objects sitting at the origin, so
  a drawing that placed one block fifty times gave you one ghost copy in the
  wrong place and none of the fifty. Serpentine3D has no block object of its
  own, so an instance now arrives as its content moved into place — the trade
  Rhino's own Explode makes. Blocks inside blocks are placed through every
  level, a member keeps its own layer and material, a member set to take its
  colour from its parent takes the instance's, and the pieces are named after
  the instance that placed them so you can find them again. Both import paths
  do it, the single-process one and the pool of processes a large file goes
  through.
- An unevenly scaled object keeps its shape. The transform everything went
  through only holds similarities, and handed a matrix it could not express it
  did not refuse — it quietly rounded to the nearest one it could, so a block
  stretched 1x1x3 came back a cube of the same volume.
- Clicking an edge picks the one in front. Edges were ranked by how near they
  fell to the cursor on screen and by nothing else, so an edge on the far side
  of a model could take a click away from the one drawn over it, and the only
  way to reach the near one was to hunt for a spot where the far one happened
  to be further off in 2D. Edges within a few pixels of each other now count
  as equally aimed at, and the front-most of those wins.

## 0.5.3 — 2026-07-29

An import release, and both halves of it came from one person opening their
own Rhino files. A 65259-object survey took about fifteen minutes to open
([#3](https://github.com/chisomobanzi/Serpentine3D/issues/3)), and when it
opened it had none of its colours
([#4](https://github.com/chisomobanzi/Serpentine3D/issues/4)). Neither was the
machine's fault: the first was rhino3dm's Python binding being read one
attribute at a time on one core, the second was the importer reading an
object's layer and ignoring everywhere else Rhino keeps a colour.

The rest is about not needing to know a number before you can draw one. Twelve
commands that would only take a typed distance now take a drag with a live
preview of the result, and the length reads out beside the cursor as you pull.

- **A fresh install stops picking up an MCP release we do not run on**: `mcp`
  2.0 renamed `mcp.server.fastmcp` and swapped `httpx` for `httpx2`, so any
  install resolving `mcp>=1.0` got a server that will not import and lost the
  HTTP client the AI assistant talks through. `mcp` is now capped below 2.0
  until the server is ported, and `httpx` — which we import directly — is
  declared instead of being borrowed from someone else's dependency list. A
  test now fails on any third-party import the project never asked for.

- **Every distance in the model can now be drawn with the mouse**: a torus'
  tube radius, a wall thickness, a fillet radius, a push/pull depth, a contour
  spacing, an array step, a curve extension, a text height — all of them used
  to be a number you had to know before you could see anything. Each is now a
  drag with a live ghost of the result, and typing the number still works
  exactly as before. Where the distance has a side to it (offsets, push/pull,
  contours) the cursor is pinned to the line being measured, so the number
  beside the cursor is the number the click will use.

  Distances on things already in the scene are measured off the geometry
  itself rather than from thin air: a 1 mm wall on a 100 mm box is a 1 mm
  drag, not a drag from the origin. Two commands were reordered so the pick
  that makes a preview possible comes first — `fillet` asks for the corner
  before the radius, and `textobject` asks for the text and its position
  before the height.

- **New commands are held to that standard by the test suite**: the tests read
  every command's source and fail if a prompt asks for a distance in the model
  that only the keyboard can answer, if a drag has nothing to show while you
  make it, or if a signed drag lets the cursor wander off the line it is
  measuring. Prompts that genuinely cannot do better carry a written reason
  next to the exemption.

- **The distance you are drawing reads out at the cursor**: pulling out a
  line, a circle's radius or a move now shows the length of the open leg in a
  small label beside the cursor, in the document's units. It follows the
  snapped point rather than the raw mouse, so the number agrees with the point
  the click will actually place — and it disappears the moment the command
  ends. Asked for on the Rhino forum.

- **Snaps work on the curve you are still drawing**: a polyline is not in the
  scene until you finish it, so it offered no snap points at all — you could
  not close it back onto its own start, or bring a later leg down onto an
  earlier vertex. End and Mid now see the legs already picked. The point you
  are pulling from is deliberately left out: it sits under the cursor the
  moment you place it, and offering it would glue every new leg to nothing.

- **The build stops shipping a package that no longer exists**: renaming
  `serpentine` to `serpentine3d` left the old tree behind in setuptools'
  staging directory, which is never cleaned out but is zipped into the wheel
  wholesale — so every build since the rename also installed 73 files of dead
  code under the old top-level name. All three installer builds now rebuild
  staging from scratch, and the AppImage build fails outright if the finished
  bundle carries a top-level package we did not intend to own. Nothing was ever
  published to PyPI, and the .exe and .dmg were unaffected because PyInstaller
  takes only what the entry script imports — but that was luck, not design.

- **...and on every other command that takes more than one point**: the end of
  an arc could not find the arc's start, and neither could the third pick of a
  box, a dimension or an angle. The points a command has taken are now tracked
  as it takes them instead of each command having to volunteer them, so End
  works across all of them. Midpoints stay with the curves that draw a
  connected run — halfway along a box's diagonal is not a feature of anything.

- **The AppImage runs the code it ships**: it started with `python -m`, which
  puts the launch directory first on the import path, so opening it from a
  folder that happened to contain a `serpentine3d/` directory ran that code
  instead of the bundled build — silently, with no error. It no longer takes
  anything from the launch directory. The build also cleared its own stale
  wheel from pip's cache: because the version string only moves at release
  time, rebuilds between releases were shipping the previous build's code.

- **Rhino files open across every core**: a 65259-object `.3dm` took about
  fifteen minutes to open on a 22-core machine, and the machine was idle for
  almost all of it
  ([#3](https://github.com/chisomobanzi/Serpentine3D/issues/3)). The cost is
  not the geometry kernel: it is rhino3dm's Python binding, where reading one
  float off a point costs 11 µs and reaching one mesh vertex costs 25 µs,
  against 0.25 µs for a plain Python attribute. A survey mesh has millions of
  vertices, so mesh reading alone was 90% of an import — and it is Python-side
  work, which holds the GIL, so no amount of threads would have moved it.

  Objects convert independently, so they now convert in parallel processes.
  Three details are what make that a fix rather than a disappointment. Workers
  are forked from the process that read the file, so they inherit the model
  copy-on-write instead of each paying ten seconds and a private copy to open
  it again. Objects are dealt out interleaved rather than in blocks, because a
  drawing keeps its meshes together and a block split hands one worker every
  expensive object. And the reader itself is a separate, thread-free process,
  because the app cannot fork: its tessellation threads hold locks a forked
  child would inherit already locked.

  Sharing objects out, though, means a drawing opens no faster than its
  dearest single object. The 522 MB cave survey ends in two meshes of 6.6
  million vertices; each took fifty seconds, and for forty-eight of them the
  dialog read "Converting object 11631 of 11759" while fifteen of the sixteen
  workers had nothing to do. A mesh past 200000 vertices is now read in vertex
  ranges by the whole pool rather than by one worker, which takes that object
  from 59.5 s to 6.2 s and the file from 77.6 s to 37.2 s.

  Progress and Cancel work exactly as before. Files under 8 MB stay on the
  single-process path, where starting a helper would cost more than it saves,
  and `SERP3D_IMPORT_WORKERS=1` forces it everywhere.

- **An imported object keeps the colour it was given**: Rhino takes an
  object's colour from one of four places — its layer, the object itself, its
  material, or the block it sits in — and the importer read the layer and
  nothing else. A drawing that colours objects individually, or by material as
  you would for anything meant to be rendered, arrived in one flat layer
  colour, which in Rendered mode looked like no colours at all
  ([#4](https://github.com/chisomobanzi/Serpentine3D/issues/4)). Object and
  material colours now come across, and materials arrive with them, so a
  transparent or glossy surface in the file is transparent or glossy here.
  Saving writes an object's own colour and its material back out, so opening a
  file and saving it no longer flattens it onto its layers.

- **Rendered mode shows the colour on the material**: an object carries two
  colours, the one it displays and the one on its material, and the ordinary
  way to set a drawing up for rendering is to leave every object on its layer
  colour and put the real colours on materials. Shaded mode is meant to show
  the layer and Rendered the material; we showed the layer in both, so a
  drawing whose layers were left at Rhino's default black rendered black
  ([#4](https://github.com/chisomobanzi/Serpentine3D/issues/4)). Surfaces in
  Rendered mode now take the material's colour where there is one, while edges
  stay on the colour the object displays. The glTF and USD exporters follow
  the same colour, since they were pairing a material's metal and roughness
  with a colour from somewhere else.

- **Imported meshes are shaded by their surface, not by their triangles**:
  Rhino stores a mesh unwelded — every face owning its own corners — so
  averaging face normals per vertex index averaged exactly one face and shaded
  every triangle flat. One survey object came out with 23870 distinct normals
  across 23369 triangles. Normals are now worked out by welding coincident
  corners and averaging the faces that meet within 30° of each other, each
  face weighted by the angle it occupies, so a curved wall is smooth and the
  rim at the top of it stays sharp. Rhino's own normals are in the file, but
  rhino3dm hands them over one attribute at a time — 239 s for one object's
  6.6 million — so they are computed instead.

- **Meshes stopped drawing a wireframe over themselves**: feature edges
  matched faces by vertex index, and an unwelded mesh shares none, so every
  triangle edge was called a boundary. One survey object produced 9.9 million
  of them — 238 MB uploaded to the card and redrawn every frame. Edges are now
  matched by position.

- **A broken macOS build now fails the build**: 0.5.2's `.dmg` was assembled
  from an empty app bundle and reported success, because the bundle died
  before writing its selftest report and the check read the file the previous
  release had left behind.

## 0.5.2 — 2026-07-28

A performance release, measured on one 522 MB cave survey: 5933 objects,
8.3 million triangles. It drew at 5.8 fps and took nearly five seconds to
answer a click. Both of those turned out to be work the app was repeating
rather than work the machine couldn't do.

- **Big scenes are workable again**: a 5900-object cave survey drew at 5.8 fps —
  slow enough that orbiting it was guesswork. Almost none of that was the
  graphics card. The draw loop asked the driver where each shader variable
  lived, by name, once per object per frame — 26000 lookups before a single
  pixel was filled, about a third of the frame — and re-sent the camera matrix,
  the display mode and the object colour for every object even when they hadn't
  changed since the object before. It also drew everything, including the
  five-sixths of the model behind you. Uniform locations are now looked up once
  per shader, values are only sent when they actually differ, and objects whose
  bounding box falls outside the view are skipped. An object now costs two GL
  calls to draw — bind its geometry, draw it — down from about seven. Draw
  order is unchanged, so coincident surfaces and transparency still resolve
  the same way.

  The other per-frame pass had the same shape. Before drawing, the viewport
  asks every object which dash style it uses, so it can notice when the answer
  changes — and that meant fetching the object's layer once per object, plus
  an `import` statement inside the loop that Qt's import hook turned into real
  work 5900 times a frame. A drawing has thousands of objects and a few dozen
  layers, so the layers are now read once per frame and the import moved to
  the top of the file. That pass went from 11.9 ms to 2.7 ms.

  Together: the cave went from **5.8 fps to 16.6 fps zoomed out, and 48 fps
  working inside the model**, where culling does the most good.

- **Clicking to select is immediate again**: in the 5900-object cave survey,
  picking an object meant a wait of about five seconds before it highlighted.
  Deciding what you clicked on means testing the cursor against geometry, and
  that test is linear in how much geometry there is, so the fix was to stop
  looking at nearly all of it.

  Three of the four passes over the drawing were pure overhead. Each object's
  bounding box was projected to the screen one object at a time, and each
  projection rebuilt the whole camera matrix from scratch — for a camera that
  cannot move part-way through a click. The matrix is now worked out once and
  reused until the camera actually moves, the boxes are tested in a single pass
  over the drawing, and objects wholly behind the camera are ruled out rather
  than tested, which working inside a model is most of the model.

  That still left the shape a survey file actually takes: two of those 5900
  objects are scanned meshes of 3.3 million triangles each, so narrowing the
  drawing to "the objects near the cursor" narrows it to the cave. Each big
  mesh now sorts its triangles and wireframe segments into a coarse grid once,
  with a bounding box per cell, and a click rejects cells by exactly the test
  that rejects whole objects. Working inside the cave, a click went from
  **4712 ms to 134 ms**. The sort takes a second or two per million triangles,
  so it happens on a background thread when the mesh first reaches the screen —
  never on the click that needs it. Box selection and sub-object (Ctrl+Shift)
  picking take the same route and got the same speed-up.

## 0.5.1 — 2026-07-27

A fix release, all of it from one real file: a 921 MB Rhino set design that
wouldn't open. Large imports now finish, say what they are doing while they
work, and can be cancelled — plus the dialog and shading problems that turned
up alongside, and the file-format filters from
[#2](https://github.com/chisomobanzi/Serpentine3D/issues/2).

- **Large Rhino files finish importing**: a 921 MB set-design `.3dm` (17802
  objects, 1900 of them polysurfaces totalling 42k faces and 78k edges) never
  came back at all. Each face rediscovered which edges bound it by testing
  every edge in the brep — about 1.1 billion surface projections — and the
  fallback that splits an untrimmed face handed OpenCASCADE's boolean engine
  the whole edge list too, one such face taking 62 seconds. Edges are now
  pruned by bounding box first, and each stage gets only the edges it can
  actually use. The worst polysurface in that file went from an estimated 103
  minutes to 3.5, and the file as a whole now loads in about half an hour
  (13492 objects, 2.1 GB peak). Still slow, but finite — and now visible and
  interruptible while it runs.

- **Import shows what it is doing, and can be cancelled**: opening a big file
  no longer just stops repainting with no way out but killing the app. A
  progress dialog appears once the work is slow enough to warrant one, names
  the object (and, on a large polysurface, the face) being converted, and
  Cancel stops it — leaving the scene exactly as it was. Large meshes report
  as they convert too: the same file holds four over 1.5 million faces, each
  21 seconds in what used to be one uninterruptible call. That conversion also
  got about a fifth quicker on the way — it was re-resolving the mesh's face
  list once per face — so the progress costs nothing.

- **The progress dialog moves on its own**: dragging the "Opening" dialog
  dragged the main window with it. Under GNOME's `attach-modal-dialogs` a
  dialog-type window is glued to its parent; this one now asks for a normal
  window type, as the file and STL-quality choosers already did, and places
  itself over the middle of the main window rather than wherever the window
  manager felt like putting it.

- **Black objects are visible in shaded mode**: shading multiplies the object's
  colour, so an object on a black layer had nothing left to shade — it came out
  flat black against a viewport background that is itself nearly black, and the
  only way to see the model was to change the layer colour. Dark fills are now
  lifted clear of black, more the darker they are, the way Rhino keeps
  black-layer objects legible. Hue is preserved and colours that are bright
  enough already are untouched, so a dark blue stays blue and nothing else
  changes. Only the fill is lifted: edges keep the object's true colour, so a
  black object still draws black wireframe over its surface.

- **Rhino import no longer crashes on breps with unconvertible faces**: when a
  face can't be rebuilt as an exact surface, the importer falls back to its
  render mesh — but then handed that mesh to OpenCASCADE's sewer along with
  the real faces, so one bad face killed the whole file (`Add(): incompatible
  function arguments ... MeshShape`). Exact faces and mesh fallbacks are now
  kept apart, so the rest of the object still comes in as real geometry.

- **File dialogs list every supported format** ([#2](https://github.com/chisomobanzi/Serpentine3D/issues/2)):
  Open/Import were missing **Rhino `.3dm`**, DXF and SVG — all of which import
  fine — while offering `.3mf`, which can only be exported; Export was missing
  `.3dm`, DXF, glTF and USD. One shared filter string was used for both
  directions. Filters now derive from `fileio`, so the chooser can't drift from
  what the app can actually read and write.
- **Open/Import default to "All supported"**: one entry listing every readable
  format, selected by default, so you no longer have to know which format
  dropdown a file hides behind. Export is the opposite case — the filter *is*
  the format choice — so it lists real formats only (no "All files"), and a
  filename typed without an extension now takes the selected format's
  (`part` → `part.stl`) rather than failing to export.

## 0.5.0 — 2026-07-22

The "interchange" release: real interoperability with the rest of the 3D
world — FBX, STL and 3MF in and out — plus print-readiness checks, Rhino-style
linetypes and draw order on drawing sheets, and a full documentation site.

- **FBX import/export**: pure-Python, mesh-based FBX in both directions;
  exports **binary** FBX so Blender, Maya, Unreal and Unity import it cleanly.
- **STL for 3D printing**: import and export with **mesh-quality presets**
  (deflection settings) so you choose how finely exact surfaces are sampled;
  the quality dialog is untethered from the main window (GNOME fix).
- **3MF export**: modern print format alongside STL.
- **printcheck**: 3D-print readiness analysis — flags problems before you
  send a model to the slicer.
- **Linetypes on sheets**: dashed / dotted / hidden / center line styles
  (Rhino parity), with hidden-line removal now computing per-shape visible
  edges so dashed solids hide correctly in layout export (PDF/SVG).
- **Draw order**: bring-to-front / send-to-back (Rhino parity).
- **Drafting sheets**: a `+` button on the bottom tab bar to add a sheet.
- **Command line**: right-click runs the typed command (Rhino-style).
- **Documentation site**: a full MkDocs (Material) site — Diátaxis-structured
  tutorials, how-to guides, reference and explanation — published to GitHub
  Pages, with a landing page covering the headless/batch workflow, downloadable
  sample scenes, and privacy-friendly (cookieless) analytics.
- **Linux polish**: modal dialogs and file choosers untethered from the main
  window (GNOME attach-modal-dialogs), using Qt's own sized file dialog.

## 0.3.0 — 2026-07-16

The "daily-driver" release: everything learned from real playtesting,
plus the rebrand.

- **Live everywhere**: creation commands previsualise as you pick (box
  grows to the cursor, cylinder/sphere/arc ghost-follow); Rhino-style
  reference-point transforms (scale/rotate by grabbing a point and
  dragging it home) with live previews on move, copy, mirror, extrude
  and arrays.
- **Gumball, finished**: drag or click-and-type exact distances/angles/
  factors with a live readout, grid snapping, Alt-copy — and a hard
  crash fixed (OCCT null-surface segfault when scaling a second axis).
- **Right mouse button**: Enter during a command (finishes selections,
  accepts defaults), repeat-last when idle, drag still orbits; commands
  now terminate cleanly when done (a bubbled Return used to re-run
  them instantly).
- **Viewports**: dockable/floatable extra viewports — model space and a
  paper sheet side by side; zoom tools (zoomselected/zoomwindow/zoom).
- **New commands**: orient/orient3pt, closecrv, clipping planes
  (gumball-movable section planes), selection filters (F6), pipe,
  point/divide, dupborder/dupedge, untrim, edgesrf, extractisocurve,
  seldup, purge, what, boundingbox, viewcapture to file/clipboard,
  back/left/bottom views, osnap toggles, command macros.
- **Rhino import**: aliases *and* keyboard shortcuts from a real Rhino
  8 settings file map onto Serpentine3D equivalents (62/88 in the
  reference setup), with user shortcuts overriding built-in keys.
- `dot` — Rhino-style model-space annotation dots: camera-facing label
  bubbles anchored to 3D points, constant screen size, selectable,
  saved in `.serp`. Copies, mirrors, arrays and orient now carry
  object colour, material, annotation and group across (`add_from`).
- Daily-driver command batch: `pipe` (round-corner tube along any rail,
  capped or open), `point` / `divide` (point objects with viewport
  markers, picking, snapping and `.serp` round-trip), `dupborder` /
  `dupedge` (extract naked borders or Ctrl+Shift-picked edges as
  curves), `untrim` (Holes/All modes), `edgesrf` (Coons patch from
  2–4 connected curves), `extractisocurve` (U/V/Both at a picked
  point), `seldup`, `purge` (empty layers + unused blocks) and `what`
  (object report: kind, layer, measures, bbox, validity).
- Renamed to **Serpentine3D** across the board (after Rhinoceros3D /
  Rhino3D): Python package `serpentine3d`, CLI `serp3d` /
  `serp3d-mcp` / `serp3d-batch` (`serp` kept as a convenience alias),
  desktop entry + icon + `application/x-serpentine3d` MIME type, data
  dirs `~/.serpentine3d` and `~/.config/serpentine3d` (pre-rename dirs
  migrate automatically on first launch), plugin entry-point group
  `serpentine3d.plugins`, drop-in hook `serpentine3d_plugin(ctx)`,
  env vars `SERP3D_*`, AppImage `Serpentine3D-x86_64.AppImage`.
  `.serp` files keep their extension; files saved before the rename
  still load.
- Desktop integration (`packaging/install-desktop.sh`): launcher,
  icon, `.serp` file association; MIT licence; `examples/hero_scene.py`.

## 0.2.0 — 2026-07-14

The "documentation and depth" release: nine feature waves on top of the
0.1 core.

### Modelling
- Sub-object selection (Ctrl+Shift+click edges/faces) feeding
  `filletedge` (smooth chains, variable start/end radii),
  `chamferedge` and `pushpull`.
- Deformers: `twist`, `taper`, `bend`, `flow` (curve-to-curve with
  rotation-minimizing frames).
- `extend`, `matchcrv` (G0/G1), curvature combs (`curvaturegraph`),
  `draftanalysis` display mode, `zebra`, false-colour curvature.
- Native mesh objects: OBJ/3DM/DXF meshes import instantly without
  sewing, transform, export and round-trip through `.serp`;
  `meshtobrep` / `breptomesh` convert both ways.
- Central tolerance policy (`core/tolerance.py`).

### UX
- Clickable command option chips, settable any time (`Cap=Yes`,
  `BothSides`, `Style`...), Rhino-style `Name=Value` typing.
- Live ghost previews while typing values (extrude, offsetsrf).
- `help` command + F1 searchable command browser; arrow-key nudge
  (Shift ×10, Ctrl ×0.1); scroll zoom anchors under the cursor.
- Gumball manipulator, settings dialog, osnap bar, mouse remapping,
  Rhino alias/shortcut import (0.1.x, polished here).

### Drafting
- Annotations on sheets are selectable, draggable, deletable and
  editable (`annotedit`); detail frames move/resize with grips.
- Associative dimensions anchored through detail views.
- Named annotation styles (`dimstyle`), multiline text, click-region
  hatching from detail linework, `sheetindex`, per-sheet revision
  tables.

### Performance
- Background tessellation with AABB placeholders for heavy shapes.
- Picking prefiltered by projected bounds; granular scene
  notifications keep panels quiet during sheet edits.
- Screen-space wide-line shader (llvmpipe-safe) + per-layer
  lineweights on screen.

### Rendering & viewports
- `4view` quad layout (Top/Front/Right/Perspective, all live).
- Per-object materials (metallic/roughness/opacity) with presets,
  exported to GLB PBR and bound UsdPreviewSurface in USDA.
- `rendered` display mode: studio lighting, ground shadow, sorted
  transparency.

### Robustness & platform
- `.serp` v2: atomic zip container with metadata + thumbnail; v1 still
  loads.
- Record history: `recordhistory` makes loft/extrude/revolve rebuild
  when their input curves change; records persist and undo.
- Seeded fuzz tests and an HLR crash corpus against the isolated
  hidden-line worker.
- Plugin architecture: `~/.serpentine3d/plugins/*.py` or
  `serpentine3d.plugins` entry points; Plugins menu; `plugins` command.
- mkdocs documentation site (`docs/`), AppImage recipe
  (`packaging/appimage`), 160+ unit/integration tests + 24-check GUI
  E2E suite.

## 0.1.0 — 2026-07

Initial build: OCC-backed scene, generator command engine, viewport
with snaps/CPlanes/display modes, curves→surfaces→solids→booleans,
transforms, layers, undo, units (feet-inches), autosave + crash
recovery, STEP/3DM/OBJ/DXF/SVG/GLB/USD/PDF interchange, layouts with
HLR details, Python console + API + batch, MCP server, CI.
