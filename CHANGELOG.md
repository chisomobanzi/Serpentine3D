# Changelog

## Unreleased

### Fixed

- **The gumball and friends hold still far from the origin too.** The
  0.8.0 follow-up fix anchored the geometry, but everything drawn over
  it, the gumball, the control-point display, the rubber band, ghosts,
  curvature combs, direction arrows, image planes and the grid of a
  far construction plane, still went to the GPU absolute and trembled
  against the now solid model. Overlays redraw every frame, so they
  all share one anchor now: where the camera is looking. Near the
  origin the frame is bit-for-bit what it was.

- **A picked edge is drawn wide enough to actually see.** The
  highlight was there all along, but it asked `glLineWidth` for its
  pixels and plenty of drivers cap lines at one, so the pick came back
  as a gold hairline. It now goes through the same screen-space wide
  line shader the object edges already use, gold over a dark rim like
  the control-point markers, on every driver and in details on sheets
  as well. Reported by Lourenço.

- **A live fillet drag no longer lights up a random edge.** Dragging
  the gumball's fillet handle rebuilds the solid on every mouse move,
  and the picked edge's index then names some unrelated edge of the
  new topology, so the highlight wandered while you dragged and could
  stay on the wrong edge after. The highlight now goes quiet for the
  object being rebuilt, in every pane, until the drag settles; the
  growing fillet is the feedback. Push/pull and multi-face drags had
  the same latent wander and are covered by the same flag.

- **Zoom Selected reaches what you are holding.** Pick a control
  point (or an edge, or a face) and ask for Zoom Selected, and the
  command said "Nothing selected": it only ever asked about whole
  objects. A held sub-object now counts, framed together with any
  objects selected beside it, and `zoom` opens on Selected when one is
  held. A single point has no size, so the camera stands off it the
  way it already did for point objects. Control points follow the
  gumball's rule: only points a pane is showing are held.

- **Geometry far from the origin holds still while you orbit.** The GPU
  works in float32, whose grid is 8mm wide at 100,000 units, and both
  the vertices and the one camera matrix were handed over absolute, so
  the world-to-eye subtraction happened in float32 and re-rounded every
  frame the camera moved: a georeferenced survey swam on screen while
  standing perfectly still. Far geometry now goes to the GPU relative
  to an anchor near it, and the anchor is folded back into the matrix
  in double precision, where the subtraction is exact, just before the
  cast. Everything rides along: shading, clipping planes, the ground
  shadow, dashed linetypes, sub-object highlights, point markers,
  details on layouts, and the PDF's raster fallback. Scenes near the
  origin keep the exact single-matrix path they always had.

## 0.8.0 — 2026-09-02

### Added

- **A section cut is hatched by what it cut through.** A detail with a
  section on it drew every cut face the same, so a drawing of a concrete
  wall with a steel pipe through it read as one material. The cut now
  carries the object it came from, and each face is drawn in the hatch
  of that object's layer: cross for the concrete, solid for the steel,
  plain lines for a layer that says nothing. Solid is a flood and not a
  line pattern, so a cut face keeps its bores open where a set of lines
  could not. Screen and plot ask the same two functions, so the sheet
  and the PDF cannot disagree. Clicking a cut face with `hatch` in
  Region mode opens the prompt on the material that was cut, so
  dropping a real hatch into a face does not quietly change what the
  face is made of.

- **A layer says what its material is hatched with.** A drawing is read by
  its fills, and what a thing is made of belongs to the layer rather than to
  the afternoon it was drawn on. Set Concrete to cross once and the `hatch`
  command opens on cross every time it is drawn on Concrete, in Corners mode
  and in Region mode, so hatching a wall is a click and an Enter. It stays a
  prompt, so the one region in another material still gets what you type.
  Set it from the Layers row menu, on every picked layer at once, or with
  `layer` and its new Hatch action. A layer that says nothing leaves the
  command where it was, on lines.

- **`section`: draw a line across the model and get the cut back.** Pick
  the objects, then the two points the saw goes through. The plane stands
  on that line and leans with the construction plane, so the same two
  points cut vertically in Front and horizontally in Top. A solid gives
  back the filled face rather than its outline, which is what a section
  drawing shows and what a hatch will need: a pipe cut across stays a ring
  of wall with a bore down the middle instead of reading as two unrelated
  circles. A surface has no inside, so it gives the curve. Everything
  lands on a `Sections` layer, and the objects you picked are left alone.

### Fixed

- **A hatch over a section leaves the holes in it empty.** A cut through
  a pipe is a ring of wall with a bore down the middle, and hatching it
  as one outline filled the bore in, so the drawing said "bar" where the
  model said "pipe". A detail's section cut now comes back as regions,
  the ring around the outside plus whatever is punched out of it, and
  `hatch` in Region mode picks that up when you click on the wall. The
  screen and the plot used to work the hatching out separately and could
  disagree about the same cut; they now ask one function, so what you
  see on the sheet is what comes out of the PDF.

- **The Layers panel is as wide as its columns need, not as wide as our
  own font wanted.** The panel opens at a set width and the layer name
  takes whatever the four narrow columns beside it leave, so on a machine
  whose sans-serif is wider than the one this was measured on there was
  nothing left and the layer you draw on read `Defa...`. The panel now
  says how many pixels short it is and the window hands them over. A width
  you have set yourself is left alone.

## 0.7.3 — 2026-09-01

### Added

- **Sublayers.** A layer can now live under another layer, as deep as you
  like. `Walls` holds `Interior` and `Exterior`, `Exterior` holds
  `Cladding`, and the layers panel draws each one indented under its
  parent with a triangle to open and close the branch. The `↳` button
  below the list makes a new layer under the one you have picked, and a
  layer can be dragged onto another to move it, along with everything
  under it. The `↰` button beside it takes the picked layer back out
  again, one level at a time, and a right-click on a row offers the same
  move by name ("Move out of Walls") along with "Move to the top level"
  for a layer buried deeper. Switching a parent off takes its whole branch
  off the screen and locking a parent locks the branch, while each layer
  keeps its own switch: a child under a switched-off parent reads greyed but
  is still set to on, so switching the parent back on brings the branch back
  the way you left it. Deleting a parent deletes the branch and moves the
  objects to Default. Requested by Lourenço Vaz Pinto.

- **The layer tree is on the API too.** `scene_info` reports each layer's
  `path` and `parent`, plus `shown`, which is whether the branch above it
  lets it onto the screen as against the layer's own switch. The `layers`
  call takes a `parent` to make a sublayer with, and a layer can be named
  by its path, so an assistant asked to work on `Walls::Interior` no
  longer has to guess which Interior was meant. Same on the MCP server.

- **A layer tree is saved and loaded.** Both `.s3d` and `.3dm` carry the
  tree. On the way out to Rhino a layer is written with its parent and
  with the visible and locked switches Rhino keeps for a layer of its own,
  so a branch you switched off there comes back switched off here.

- **Layers move up and down the list.** Two arrows under the list move the
  picked layer, so the layers read in the order the drawing wants rather than
  the order they happened to be made in. A layer moves among its own siblings
  and takes its branch with it, so one press steps over a whole branch;
  several picked layers travel as a block and stop as a block at the end of
  the list; one press is one undo, and a press that can move nothing costs
  none. The order is written into both `.s3d` and `.3dm`, the Default layer
  included. Requested by Lourenço Vaz Pinto.

- **Layers can be dragged where they belong.** Dropping a layer on another
  one has always put it inside; dropping it between two rows now moves it
  there, and dropping it above the first row or below the last takes it to
  either end. That is also the way back out of a branch: drag a sublayer into
  the gap between two top-level layers and it leaves the branch and lands in
  that gap. A line shows where the layer would land, indented to the level it
  would land at, so a drop beside a branch reads differently from a drop into
  it. The quarter of a row at each end means beside it and the half between
  them means inside it, rather than the two pixels Qt offers. Several layers
  dragged together land in the order they were in, and one drop is one undo.
  Requested by Lourenço Vaz Pinto.

### Fixed

- **`Walls::Interior` and `Roof::Interior` no longer collide on import.**
  Reading a `.3dm` looked only at a layer's own name, so two sublayers
  named the same under different parents landed on one layer and the
  objects of both were merged onto it. An imported layer is now matched by
  its full path, and the parents it hangs from are made as it goes, with
  the colour, print width and switches the file gives them. Reported by
  Lourenço Vaz Pinto.

### Changed

- **The layer you draw on is chosen with a double-click.** A single click
  on a layer's name used to make it the current layer, so clicking three
  layers in turn to switch them off left the last one current and the next
  curve landed there. A click now only picks the row; a double-click on
  the name says which layer to draw on. Renaming a layer, which that
  double-click used to do, is on the row's right-click menu, and the
  buttons under the list are grouped by what they do: the two that make a
  layer, the one that moves it, the one that deletes it. Reported by
  Lourenço Vaz Pinto.

- **The + button makes a layer beside the one you picked.** It used to add a
  top-level layer at the bottom of the panel however deep the picked row was,
  so pressing it with a sublayer picked gave that layer an uncle rather than
  a sibling, nowhere near the row being looked at. The new layer now lands
  directly under the picked one, at the picked one's level: `+` makes a layer
  beside it, `↳` makes one inside it. With nothing picked it still goes at
  the end of the top level. Either button leaves the new row picked too, so a
  second press works from the layer just made and a name typed straight away
  lands on it. Reported by Lourenço Vaz Pinto.

## 0.7.2 — 2026-09-01

### Added

- **Space is Enter at the command line.** Type `line` and press Space and
  the command starts; type a point and Space commits it; Space on an empty
  prompt repeats the last command, all exactly as Enter does and as Rhino
  does, so one hand can stay on the mouse. While a command is asking for
  text, a layer name say, Space is still a space, so "Ground floor" can be
  typed. Requested by Lourenço Vaz Pinto.

- **The right mouse button orbits, out of the box.** Rhino's chords on the
  orbit button are now Serpentine's: drag orbits, Shift pans, and Ctrl
  zooms, dragging up to come closer. Ctrl+Shift orbits from anywhere,
  including a parallel view, where a plain drag pans. The Preferences page
  now says which button Rhino uses instead of claiming the middle one is
  the Rhino default; anyone who chose the middle button keeps it. A
  right-click with no drag is still Enter. Requested by Lourenço Vaz Pinto.

- **Layer linetype and print width are drop-downs.** The Type cell offered
  its options one click at a time, each click rolling on to the next
  linetype with no way to see the list, and Print was a bare box to type
  into. Both now open a list: every linetype for Type, and Default plus
  the standard pen widths (0.13 to 1.0 mm) for Print, which still takes a
  typed width such as 0.42. A single click on Type no longer changes
  anything. Requested by Lourenço Vaz Pinto.

- **Several layers can be switched off at once.** The layers panel takes a
  Ctrl- or Shift-click selection, and the on/off box of any selected layer
  applies to all of them, as one undo step and one redraw. Clicking a box
  leaves the selection as it was, so the next click switches the same
  layers back on, and a Shift-click picks the range from the layer you
  last clicked, not from the top of the list. Requested by Lourenço Vaz
  Pinto.

- **A detail's scale is set in the Properties panel.** Pick a detail on a
  sheet and the panel shows it as a detail, with its frame size and a Scale
  drop-down of the scales an architect draws at, 1:1 to 1:200, that also
  takes a typed 1:75. A scale that makes no sense is refused and the
  control goes back to the real one. `detailscale` still works. Requested
  by Lourenço Vaz Pinto.

### Fixed

- **`isolate` on a big file no longer crawls.** Hiding, showing, locking,
  grouping, restyling or re-layering many objects at once told the viewport
  about each object separately, and the viewport rebuilt everything it
  draws each time, so isolating one object among three hundred rebuilt the
  scene three hundred times. Every command that changes many objects now
  reports once for the lot: `isolate`, `unisolate`, `hide`, `show`, `lock`,
  `lockother`, `unlockall`, `group`, `ungroup`, `changelayer`, `linetype`,
  `matchprops`, `material` and the draw-order commands. Reported by
  Lourenço Vaz Pinto.

- **Enter in a Properties field no longer runs the last command.** Type a
  new name for an object, or a scale for a detail, and press Enter, and the
  edit was applied and then the last command started again on top of it,
  because an Enter that nothing consumed fell through to the command line's
  "Enter repeats the last command". A field keeps its Enter now; the command
  line and the viewport still repeat.

- **Two crashes in the layers panel.** Renaming a layer by double-clicking
  its name, and clicking its on/off box, could each delete the row Qt was
  still holding and take the app down with it; the panel now finishes
  handling a click before it redraws.

- **The layers panel fits the space it is given, and its drop-downs can be
  read.** Adding the Type and Print columns had made the tree wider than the
  panel column a fresh window gives it, so Print sat off the right-hand edge
  behind a sideways scrollbar and Type was cut in half. The layer name column
  now takes whatever room is left over and the other four keep the width
  their content needs, so all five are on screen at any panel width. The
  Type and Print drop-downs open at the width their own list needs rather
  than the width of the cell, where "Continuous" came up as "Contin", and
  stay inside the panel when there is nothing to their right.

## 0.7.1 — 2026-08-18

### Added

- **A layer carries a print width and a linetype you can set in the panel.**
  The layers panel grows a Print column and a Type column: Print is the pen
  width in millimetres a layer plots at, blank for the device default, and
  Type cycles the layer's linetype. A detail on a layout now plots each
  layer's edges at that layer's width, in PDF and in DXF, rather than the one
  width every line used to get. The on-screen weight is untouched, so nothing
  looks different in the viewport, and the width round-trips through a .3dm as
  Rhino's PlotWeight. Requested by Jonas Pedrotti.

- **`mergeallcoplanarfaces` tidies a polysurface after a boolean.** A union
  of two boxes side by side leaves each spanning side split into two
  coplanar strips, so the result has ten faces where six would do.
  `mergeallcoplanarfaces` (alias `mergeallfaces`) fuses coplanar neighbours
  and drops the seam edges with them, so the box reads as a box again. This
  is Rhino's MergeAllCoplanarFaces. The volume does not move, and an object
  with nothing to merge is left alone. Requested by Jonas Pedrotti.

- **`join` works on surfaces, not just curves.** Pick two surfaces that
  share an edge and `join` (alias `j`) now stitches them into one
  polysurface, exactly as it always has for curves. Surfaces that close up
  a volume between them, the six faces of a box for instance, come back as
  a solid rather than a hollow shell. Surfaces that touch nothing are left
  where they are, and the command says so instead of quietly bundling them
  together. Requested by Jonas Pedrotti.

### Fixed

- **A boolean that cuts a solid in two now gives you two objects.** Saw a
  bar in half with `booleandifference` and Serpentine kept it as one: one
  name in the layers panel, one gumball sitting in the gap, and both halves
  moving together. The kernel was never confused, it handed back a compound
  with a solid in it per piece, but nothing downstream looked inside. Now
  each loose piece is its own object, the first one keeping the original's
  id so its name, its layer and anything built from it survive the cut.
  Union and intersection do the same, so unioning two solids that never
  touch leaves two objects rather than one. Anything still joined is left
  alone, including a solid with a void in it, which has a second shell but
  is emphatically still one object. Reported by Jonas Pedrotti.

- **`explode` on a severed solid gives you the pieces, not the faces.**
  A bar cut in half exploded into twelve faces rather than the two bars,
  because the shape was asked what kind of thing it was before it was asked
  what it held. Compounds of curves exploded into nothing at all, and now
  come apart properly too.

- **Text files are UTF-8 everywhere, not the machine's locale.** A document,
  a config, an autosave, an .obj, an .stl, a .usda or a journal was read and
  written in whatever encoding the operating system defaulted to, which is
  UTF-8 on Linux and macOS but can be cp1252 on a Windows box in a non-English
  locale. A layer name or a file path outside ASCII round-tripped to mojibake,
  or raised, on that one machine and nowhere we could reproduce. Every text
  file now states UTF-8.

## 0.7.0 — 2026-08-18

### Changed

- **`curve` draws by control points now, and `interpcrv` is its own
  command.** These are Rhino's names, and they finally mean what Rhino
  means by them: `curve` (alias `cv`, for control vertex) pulls a NURBS
  curve toward the points you pick, and `interpcrv` runs one through them.
  Serpentine's `curve` used to be the interpolating one, so a Rhino user
  typing the command they use most got the other tool with no sign that
  anything was wrong: both make a smooth curve through roughly the right
  place, and only the control points give it away. A script, alias or habit
  that relied on `curve` interpolating should say `interpcrv`.

### Added

- **You can see the curve while you are drawing it.** Both curve commands
  now ghost the curve the next click would make, instead of showing only
  the points already picked and the straight chain between them. That chain
  is the one shape the curve is not: an interpolated curve bulges away from
  it, and a control point curve does not go through the middle of it at
  all. So `interpcrv` drops the chain entirely, while `curve` keeps it,
  because there the chain is the control polygon and part of what you are
  drawing rather than a stand-in for it.

- **`dir` and `flip`**, Rhino's pair for direction. Which way a curve runs
  and which way a surface faces are invisible until something draws them,
  and then they decide what happens next: which end an offset comes out on,
  which way a sweep travels, which side a shell thickens. `dir` stands green
  arrows on what you picked, along a curve or off a surface, and stays up
  with Flip on the prompt so you can turn a face round and watch the arrows
  come back the other way. `flip` is the same edit without the looking.
  Reversing works on the geometry rather than the topology, so a circle
  turned round is still a circle rather than the b-spline a conversion would
  leave behind. The arrows are a fixed size on screen and they belong to the
  command: they go when it ends, including on Escape.

- **`undoview` and `redoview`**, a history for the camera. An orbit that
  went too far leaves the drawing exactly as it was, so the general undo is
  no help at all: there is nothing about the model to take back, and what
  you want is the view you had a second ago. A whole gesture is one step, so
  a drag that turns the model right round comes back in one, and so does a
  burst of wheel clicks. Typing `top` or running `zoomextents` is a step
  like any other. Each pane keeps its own history, because where the Top
  view has been says nothing about where Perspective has been.

- **`lockother`**, the other half of isolate. Isolate takes the rest of the
  drawing off the screen; this leaves it up to line the new work against and
  only stops you picking it, which is what you actually wanted when the
  thing you keep catching is a background curve you have no intention of
  moving. What you picked stays picked, and `unlockall` releases the rest.
  The scripting API reports `locked` on every object now, so a script can
  see why a pick found nothing.

- **`insertknot`, `insertcontrolpoint`, `removeknot` and
  `removecontrolpoint`**, under Rhino's names. Inserting a knot is the one
  edit that hands you a control point without moving the curve by so much
  as a tolerance, so you can get a handle where you want to pull from
  rather than making do with the ones the curve was built with; Automatic
  puts one in the middle of every span. Removing a knot goes the other way
  and does move the curve, so the command says by how far. With several
  curves picked, the point you click says which one you meant and which
  knot you meant. Both commands turn the control points on for what you
  picked, and both preview under the cursor: the control polygon you would
  get for an insertion, the curve you would be left with for a removal.

### Fixed

- **A closed control point curve is now closed all the way round.**
  `make_control_curve(..., closed=True)` took the argument and ignored it,
  and built an open curve. It builds a periodic one, so the poles are a
  ring with no first or last and the curve runs through the seam as
  smoothly as it runs anywhere else, rather than meeting itself at a
  corner.

## 0.6.3 — 2026-08-13

### Added

- **Alt and a swipe turn the view to the nearest axis.** Blender's gesture:
  hold Alt, flick the orbit button the way you want to go, and the view
  makes a quarter turn and settles on whichever axis it lands nearest. It is
  for a single maximised pane, where the alternative is a function key or
  the View menu. The turn is about the camera's own up and right rather than
  world Z, so a sideways swipe still goes somewhere from Top, where the
  world axis is the one you are looking down. A perspective pane comes out
  perspective, seen from the top, and an ordinary drag orbits straight back
  out of it; a pane that was already parallel lands on the whole named view,
  construction plane and label with it. A flick too short to mean anything
  is handed back to the button, so Alt and a click still opens the popup.

- **Views turn rather than cut.** The swipe, F1 to F4, the View menu and a
  pane's title menu all take about a fifth of a second to get there, easing
  out of the motion. Front and Back are the same picture on a symmetric
  model, so a cut says nothing about where you went and the eye has to
  work it out again; a turn shows you. The camera takes the shortest way
  round, which is the way your hand went, since a swipe turns at most 135
  degrees. A perspective pane asked for a named view stops foreshortening
  as it sets off, while it is moving quickest, rather than popping once it
  has settled. Anything you do next lands the turn at once, so two quick
  presses are two turns and never a race, and `set_viewport` over RPC still
  arrives immediately, as scripts that read the camera back expect.
  `display.view_transition_ms` sets the length; 0 cuts as before.

### Fixed

- **Pressing a space tab draws that space.** Switching between the model
  and a layout told the pane which space it was in, asked for a frame, and
  then rearranged the docks underneath it, which threw the frame away. The
  tab, the title and the echo all changed and the pane went on showing the
  space you had just left until a scroll or an orbit asked for a frame by
  accident. It only bit when both tabs held the same arrangement, which is
  why a brand new layout always looked right: going from four panes to one
  moves every pane, and a pane that moves is redrawn anyway. The frame is
  now asked for once the docks have stopped moving.

- **A viewport that cannot draw says so instead of breaking something
  else.** An error in a frame was an error let out of a Qt virtual call,
  and Qt carried on: the next thing Python was asked for, usually the size
  of some unrelated widget, was what reported it, as a SystemError naming a
  widget that had nothing to do with it. The frame now keeps its own
  errors, prints the traceback that used to be thrown away, and stops
  drawing that pane rather than repeating itself once per repaint.
  Redocking the pane, or reopening the window, builds a new context and it
  tries again.

## 0.6.2 — 2026-08-12

### Added

- **Right-clicking a layout tab renames, duplicates or deletes that sheet.**
  The only way to work on a sheet was knowing the `layout` command had
  those words inside it. The menu acts on the tab you clicked, so it is
  never the wrong sheet, and it asks first when there is work on the one
  you are deleting. Duplicate gives every item on the copied sheet a fresh
  id rather than only the details, and counts the name up instead of
  handing out 'Site plan copy' twice, which is what the command line tells
  sheets apart by.
- **Delete takes control points, one piece of structure at a time.**
  Delete with control points held takes those points rather than the whole
  object. A curve that runs short of points degrades instead of refusing: a
  closed curve opens once two points are left, two points collapse to a
  point object, and deleting the last one takes the object with it. Joined
  wires of mixed degree still refuse a shared corner, which is the one case
  with no honest answer. The command says what changed, because the
  viewport cannot once the points are gone.
- **A click back on the first point closes the curve.** Drawing a loop
  meant reaching for the Close option, when the gesture people already make
  is one last click on the point they started from. End osnap puts that
  click exactly on the stored point, so the tolerance only has to absorb
  float noise rather than aim. Two points down is not yet a close: a
  zero-area loop is never what the click meant.
- **Double-clicking a .serp file opens it.** Each platform allows a
  different amount of help, so `setdefaultapp` asks for what it can get.
  Linux registers the MIME type and desktop entry and sets the default
  outright, Windows opens the Default Apps page because the UserChoice key
  is hash-protected against applications setting it themselves, and macOS
  declares the document type in the bundle and points at Finder's Change
  All.

### Changed

- **Escape puts the control points away.** Escape gave up whatever was in
  hand, a running command or the selection, but had nothing to say about
  control points: a drawing covered in markers stayed covered until you
  remembered F11. It gives up one thing at a time now, most recent first:
  the command, then the points, then the selection. The object stays
  selected while the points go, so the key you already press to back out of
  things backs out of point editing too.

### Fixed

- **Deleting a sheet leaves the view somewhere sensible.** Deleting hands
  you the tab below rather than sending you home to Model, which was only
  ever the right answer for the first sheet. It also moves any pane still
  pointing at that sheet: a pane nobody asks to redraw keeps the last frame
  it drew, so a deleted sheet stayed on screen until something else caused
  a repaint. The rule lives in the tab refresh, so the menu, the `layout`
  command and undo all follow the same one.
- **A selection request says why it ignored what you had selected.**
  Running `booleanunion` with 17 meshes selected parked the command at
  "Select 2 solids" with no word about the selection it had thrown out, and
  every click from then on read as a dead viewport. The kinds filter speaks
  for itself now, in the words the filter actually used, and 'all' of
  nothing explains itself instead of falling into the Enter-on-nothing
  cancel. A partly usable selection is carried into the pending pick, so
  adding to it completes the answer rather than starting the count from
  nothing. A control point clicked mid-request is carried through as well.
- **Hiding control points lets go of them.** A held control point is what
  `move` moves and what the gumball stands on, and after F11 those were
  markers nobody could see: the next `move` would quietly drag invisible
  corners instead of asking which objects to work on.

## 0.6.1 — 2026-08-09

### Added

- **A story can show the app that made it.** `turntableui` records the
  current shot turning inside the whole Serpentine3D window, ready for an
  Instagram story: 1080x1920, 30 fps and fifteen seconds by default. It
  keeps the camera's target, distance and elevation, fits the UI without
  cropping or stretching, leaves quiet dark space for a caption or link
  sticker, and puts the live camera exactly back where it started.

### Fixed

- **A turntable holds one camera distance all the way round.** Every frame
  used to fit the model independently, so a rectangular object made the
  shot breathe in and out as its wide and narrow sides turned past the
  camera. The farthest required framing distance is chosen once now and
  kept for the whole orbit, without losing any part of the model.
- **UI turntables fill Retina and HiDPI story frames.** Qt carried the
  monitor's device-pixel ratio into the window grab, then treated the
  already-scaled pixels as logical ones and drew the app at half size in
  a field of empty black. The ratio is normalised before compositing, so
  the window fills the intended width on high-density displays too.
- **One imported mesh used to stop every command in the session.** A
  triangle mesh cannot be written as a BREP, and the journal's idle flush
  tried anyway. The flush is the first thing a command does, so after an
  FBX or OBJ import, delete, hide and move all quietly did nothing, on
  the whole drawing and not just the mesh. Meshes now serialise properly,
  so they record, replay and land back in the right place. Saving a
  drawing with a mesh in it works again too.
- **A journal that fails no longer takes your work with it.** The
  recorder gives up, says so on stderr, and leaves the app alone.
  Whatever it wrote up to that point still replays, and
  `serp3d replay --check` names the moment it stopped rather than letting
  a short recipe look like a complete one.
- **STEP export explains itself.** A mesh handed to the STEP writer used
  to surface a wall of OCP argument signatures in an "Export failed" box.
  Now the solids and surfaces go out and the echo says how many meshes
  stayed behind. A drawing of nothing but meshes gets a plain sentence
  pointing at OBJ, STL or 3MF.
- **Journals are no longer deleted to make room.** The journal directory
  used to keep only the newest forty sessions and drop the rest at every
  launch, which is how a cache behaves and not how a recipe does. A run
  of short sessions could quietly evict a week of real modelling. Now a
  session that recorded any work is kept forever, at any age and any
  count. A session that recorded nothing removes its own file when you
  close the window, and one abandoned by a crash gets swept a day later,
  so opening the app to look at it still leaves nothing behind.

## 0.6.0 — 2026-08-09

### Added

- **Every session is a recipe now.** Serpentine3D keeps a journal as you
  work: each command and every point, number and selection it actually
  received, resolved through snaps and planes, written to
  `~/.local/share/serpentine3d/journals/` as it happens. Gumball drags
  and control point edits ride along as exact geometry, one entry per
  undo step. `serp3d replay <journal> --check` cooks the whole session
  again headless and proves the result identical, which also makes a
  journal the best bug report there is: a file that reproduces your
  session keystroke for keystroke on someone else's machine. Undo, redo,
  cancelled commands, files opened mid-session and drawing inside details
  all replay as they happened. `SERP3D_NO_JOURNAL=1` turns it off.
- **A session replays as a timelapse.** `serp3d replay <journal> --video
  build.mp4` re-executes the session under a slow orbiting camera and
  renders it, no screen recording anywhere: your pauses compress by
  `--speed`, each command lands in a caption band as it runs, and the
  same session comes out 16:9 for a video or `--aspect 9:16` for a reel
  without remodelling a thing. A fumbled take never appears, because the
  journal only holds what was actually done.
- **The `turntable` command.** One command walks the camera around the
  model - the selection if there is one - and writes an .mp4: seconds,
  frame shape (16:9, 9:16, 1:1) and the file are all it asks. Frames
  render offscreen at 1080p whatever size the window is. ffmpeg does the
  encoding; without it you get numbered PNGs and the line that assembles
  them.
- **A quiet end card.** `--endcard` on a replay video, or the
  `media.endcard` setting for turntables, closes a clip with a dark
  card: Built with Serpentine3D, and the address. Off unless you ask.

- **Apparent intersection snaps.** Two curves that pass one over the other
  never meet, so `Int` has nothing to offer at the place they cross on
  screen, and in a Top view that place is very often the one you are
  pointing at: where a rafter runs over a wall, where a rail crosses the
  edge of a solid. The new **AppInt** button on the osnap bar gives you
  that point, on whichever of the two is nearer the camera, since that is
  the one you can see there. Edges of solids count, and so does a curve
  that passes over itself. Where the two really do touch you get `Int` as
  before rather than the same point twice under two names. This snap
  belongs to the view you are looking through instead of to the drawing,
  so it moves when you orbit and it is worked out fresh every time the
  cursor moves. It starts switched off.

- **More than one way to say a shape.** An arc is start, a point on it,
  end. Unless what you know is the center and the sweep, in which case
  those three picks are a puzzle about a shape you could already describe.
  The creation commands now take options the way Rhino's do: words in the
  prompt's parentheses that you type (a prefix is enough) or click, as
  chips beside the command line. `arc` gains *Center*, where a typed
  number is the sweep in degrees and a minus sign turns it the other way,
  and *StartEnd*, which pins both ends first and bends the middle after.
  `circle` gains *2Point* across a diameter, *3Point* through anywhere,
  and *Diameter*, which makes a typed number mean the width across.
  `rectangle` gains *Center*, spread evenly with clicks or typed sides,
  and *3Point*, which lays one whole edge first so the rectangle can lean.
  `ellipse` gains *Diameter*, taking the first axis end to end at any
  angle. `line` gains *BothSides*, growing evenly out of its middle. `box`
  gains *Center* for its base, `sphere` gains *2Point*, and a `curve` can
  now *Close* back on itself smoothly, as a polyline always could. The
  polyline's own close, and every word like it, is now a clickable chip
  too.

- **`extractsrf`.** Ctrl+Shift-click faces of a polysurface, run it,
  and they come away as surfaces of their own while what is left sews
  back into one open polysurface with a hole where they were. `Copy`
  defaults to No, the way Rhino has it, because the usual reason to
  pull a face off is to rebuild it, and a duplicate sitting exactly
  where the new surface has to go is in the way. Say Yes and the
  original stays whole. Take every face of an object and the object
  goes too rather than staying behind as an empty shell. What you
  extracted is what you are holding afterwards, so the gumball is
  already on it, ready to slide it clear.

### Fixed

- **Sub-object picking goes by depth.** Ctrl+Shift+click and the click
  went to whichever edge fell nearest the cursor on screen, with faces
  looked at only once no edge was within reach at all. On a box that
  means the three edges meeting at the hidden far corner take every click
  aimed at the face in front of them, and there is nowhere else to click
  for that face, because the corner sits in the middle of the shape.
  Edges and faces are now ranked against each other on how far in front
  of the camera they are, the edge counted a thousandth nearer so that
  the face it borders cannot take its click. A wireframe view draws no
  faces, so there is nothing there to take a click or to hide an edge
  behind.

- **Control points round the back stop taking clicks meant for the
  front.** They were ranked on how close they landed to the cursor and on
  nothing else, so on any shape with a far side the point behind won
  whenever it happened to fall a pixel nearer, which on a surface seen
  face on is most of them. Points within a few pixels of each other now
  all count as under the cursor and the front-most of those wins, the
  same rule the edges already followed.

- **`osnap mid toggle` and its relatives now change the snap you are
  using.** They wrote the setting to the config file and stopped there, so
  the osnap bar redrew itself from a snap index that had never heard about
  it and the button flipped back. The setting only took hold next launch.

- **Ortho from a snapped start point stays level.** Hold Shift in the
  Front view, begin a line on a corner that sits behind or in front of
  the construction plane, and drag sideways: the line looked level in
  that view and came out diagonal in Top and Perspective. The
  constrained end kept the plane's depth instead of the start point's,
  so any ortho line begun on existing geometry slid back onto the
  plane. Ortho now means the point lies on an axis through the one you
  started from, all three of its coordinates.

- **Tab holds the direction you aimed with Shift.** Square a line off
  with Shift, press Tab to freeze that direction, then let go of Shift
  and the direction went with it: nothing had been frozen, and the next
  click drew wherever the cursor was. As far as the keyboard is
  concerned Shift+Tab is a key of its own rather than Tab carrying a
  modifier, and only the plain Tab was being listened for. Since Shift
  is what holds ortho, the Tab that worked was the one nobody presses.

- **A flat face is no longer drawn as though it were curved.** A wall
  swept from a NURBS profile, and every extrusion read out of a .3dm,
  arrives with its faces stored as freeform surfaces rather than as
  planes. Isocurves were decided from that stored name, so those walls
  came back under a grid of lines describing nothing: on a flat face
  an isocurve is a straight line lying in the plane of the edges
  already drawn around it. Flatness is measured now instead of taken
  on trust, which also draws those objects quicker, because working
  the lines out cost far more than deciding to skip them.

## 0.5.11 — 2026-08-06

### Added

- **A pane can show a sheet while the panes next to it show the model.**
  The tabs along the bottom are workspaces now, but a space is still a
  property of a pane underneath them, so a pane's own title menu lists
  Model and every sheet in the drawing. Point one pane at Layout 1 and
  leave the other three on the model, and the Model tab keeps that
  arrangement for you. Rhino makes you leave model space to look at a
  sheet.

- **The gumball is on the sheet now.** A detail, a note or a dimension moved
  by dragging the thing itself, which wanted a steady hand and gave you no way
  to say how far. Whatever is picked on a sheet now gets handles of its own: an
  X arrow, a Y arrow and the pad that takes both at once, standing in the same
  place and drawn at the same size as the gumball you already know. Drag one
  and the readout gives the distance in millimetres, or type the distance if
  you want an exact one, and ++esc++ puts it back. Nothing turns and nothing
  scales, because nothing a sheet holds has an angle or a size a handle could
  honestly change. A locked detail offers no handle at all and stays where it
  is when the rest of the selection moves. Step into a detail and the model's
  gumball takes over, since what is picked in there is a model object.

- **The gumball extrudes.** It is already standing on the line you want a
  surface off, with an arrow pointing the way, so the only thing between you
  and the surface was having to leave it, type `extrude` and pick the line
  again. Drag the filled box on any axis and a curve grows a surface along
  that axis and stays where it is, a closed curve gives you the solid it
  encloses rather than the four walls of it, and a surface becomes the solid
  it sweeps out. A selected edge grows a surface of its own and leaves the
  object it came off alone. Type a distance instead of dragging if you want
  an exact one, and drag back to nothing if you change your mind, which
  leaves the drawing as it was. ++ctrl++ and a translate arrow does the same
  thing, for the hand that arrived from Rhino knowing it.

- **The two boxes on each gumball axis now say what they do.** Scale has
  moved to the far side of the pivot, drawn hollow on a dashed leader that
  mirrors the arrow, which leaves the filled box on the shaft to be the
  extrude handle, the way Rhino has it. Each axis now reads as one handle
  with an end of its own either way, the two boxes are told apart by their
  look and by which end they sit on rather than by something you have to be
  holding down, and the filled box appears only where there is something to
  grow: a solid does not offer one, and neither does a gumball standing on
  control points.

- **A rubber band round some vertices now takes the vertices.** Points on gave
  you one way to pick a control point, which was to click it one at a time.
  Dragging a rectangle round a row of them selected the curve they belong to
  instead, because the band only ever asked which objects it had caught and
  knew nothing about the points. It asks for points first now: a window or a
  crossing band takes every control point inside it, ++shift++ adds to what
  you are already holding and ++ctrl++ takes some back out, exactly as
  clicking them does. When the band catches no points it goes on to pick
  objects the way it always has.

- **Move, rotate, scale and mirror work on the control points you are
  holding.** They only ever asked which objects to work on, so a corner you
  had picked was either ignored or moved along with the whole curve. When
  some control points are held they are what the command is for, and it goes
  straight to asking where to move them from: `move`, `rotate`, `scale`,
  `scalenu`, `scale1d`, `scale2d`, `rotate3d` and `mirror` all put the held
  points through the same transform they would have put the objects through,
  live preview included. The points are still held when the command ends, so
  the next nudge does not start with picking them again. Surfaces as well as
  curves.

### Changed

- **The `+` beside the Model tab says what it makes.** A drafting sheet is
  the one thing in the app you would never guess was behind a bare plus, so
  it reads `+  New layout` until you have made one and goes back to a `+`
  once you have. Its menu and tooltip call them layouts too, which is what
  the tabs have always called them.

- **Ctrl and the orbit button is now what orbits an ortho view.** Shift used
  to do it, and Shift is held for so much else while you draw that Top kept
  swinging round into an axonometric view when nobody asked. Shift now pans
  wherever you are, ++ctrl++ orbits wherever you are, and a plain drag still
  orbits in perspective and pans in Top, Front and Right.

### Fixed

- **A layout is a workspace of its own.** Pressing `+ New layout` turned
  whichever pane you happened to be in into paper and left the other three
  showing the model beside it, which is not a drafting sheet. Press it
  again and a second pane went the same way. And when the pane you were in
  was tabbed away behind another one, the button appeared to do nothing at
  all, which is how it was reported. A space was a setting on a single
  pane, while the strip along the bottom looked like it spoke for the
  window, and the two never agreed. Each tab is an arrangement of panes
  now. Model holds the ones you model in, a sheet opens as the sheet
  filling the area, and every tab hands back the arrangement you left it
  in, splitters and all. Properties, Layers and Display sit still through
  all of it.

- **The `+` button asks which paper size.** Clicking the wide part of it
  made an A3 and only the small arrow beside it offered a choice, so the
  size you got depended on which half of a thirty pixel button you hit.
  The whole button opens the menu now.

- **The gap between the Model tab and the button next to it.** A tab bar
  reserves room for the scroll buttons it might one day need and asks for
  that room as a minimum, so a strip holding the one `Model` tab still
  demanded fifty pixels more than the tab, and there they sat. It only
  needs that floor when the tabs are wider than the strip, which with one
  tab they are not. Enough sheets to fill the strip and the scroll buttons
  still turn up.

- **Text picked out of the command history can now be copied.** You could
  always drag a selection across the echoed history and it lit up like a
  selection, but nothing would take it. Typing goes to the command line
  wherever you clicked, which is what it should do, so the history never
  holds the keyboard focus and never saw ++ctrl+c++: the key reached the
  Edit menu's Copy instead, which copies geometry, and with no object
  picked it quietly did nothing. Copy asks the history first and the
  drawing second now, so an error message you can see is an error message
  you can paste into a bug report. Go back to a pane and the selection is
  dropped, so the next ++ctrl+c++ over a picked object still copies the
  object.

- **The command area can be dragged taller.** It was pinned shut two ways
  over: its contents were laid out with a fixed height, which handed the
  dock a maximum equal to the height it opened at, so there was no separator
  to take hold of, and the history view inside it was capped at four lines,
  so even had the dock grown the history would have sat in the same four
  lines with the new room empty below it. Both caps are gone. Take the room
  off the viewports whenever you want to read further back, and it is the
  history that gets it rather than a gap under the prompt. It still opens at
  the height it always did.

- **`4view` lays the four panes out again, whatever state they were left
  in.** It built the 2x2 the first time it was asked and after that only
  un-hid the three side panes, which made every way of disturbing the layout
  a one-way door: close the Perspective pane with the x on its title bar and
  nothing brought it back, drag two panes onto each other into a tab stack
  and they stayed stacked, float one off and it stayed floating. The
  arrangement is saved between sessions too, so a window that got into that
  state came back into it on every launch. Asking for four viewports now
  means four viewports, in a 2x2, every time, and `1view` gives you back the
  one pane whether or not it is the one you closed.

- **Solid primitives are built on the plane you draw them on.** `box`,
  `cylinder`, `cone`, `torus` and `helix` all read their base off the world X
  and Y axes and stood up the world Z axis, whichever pane you were working
  in. A box started in the Front pane got nowhere at all: its two base
  corners differ in X and Z there, the command saw no Y between them, and all
  you got was a rubber line and a complaint about a zero width. They ask the
  construction plane now, so a cylinder drawn in Front comes at you and a box
  drawn in Right stands up out of that pane. `arraypolar` turns its ring
  around the same plane instead of always around world Z.

- **The gumball only offers to grow a thing where growing it makes
  something.** The filled box turned up on all three axes at once, so a flat
  surface offered to be swept sideways within its own plane and a straight
  line offered to be swept along its own length, both of which hand back what
  you started with. Pull a surface off a line now and the surface is left
  with one box, on the axis it faces. The other two axes keep their arrow, so
  a Ctrl-drag along one of them moves the thing rather than laying a
  flattened copy on top of it.

- **A curve cutter now cuts the way the pane it was drawn in is facing.**
  `booleansplit`, `split` and `trim` all sweep an open curve into a cutting
  surface, and the sweep went straight up the world Z axis whichever pane you
  were looking at. So a line drawn across a box in Front, which looked like a
  cut through the middle, came back as a cut down the end. The sweep now
  follows the normal of the plane the command is drawing on: front to back in
  Front, side to side in Right, and still upward in Top and Perspective,
  where it was already right.

- **Right-click no longer repeats undo or redo.** They join delete on the
  list of commands a reflex is not allowed to run again: both already have a
  key and a button of their own, so a right-click meant for something else
  should not walk the drawing back a step. They no longer become the repeat
  target either, so after undoing a circle you got wrong, right-click hands
  you another circle to get right.

- **Points on now shows in every pane.** It was kept per viewport, so turning
  a curve's points on in the Top view left the Right view drawing a bare
  line: no markers there to pick, and a corner picked in one pane showed as
  picked in no other, gumball included, because a gumball will not stand on a
  point its own pane is not showing. Points on belongs to the drawing, so all
  four panes agree about it.

- **Points on now looks like points on.** The markers were two arms along the
  world X and Y axes, which is a cross only when you happen to be looking
  down Z: from anywhere near the horizon both arms lie edge-on and the marker
  flattens into the curve it is sitting on. They were also drawn white, on
  curves that are usually white. Each point is a small square facing the
  screen now, the same size on the glass wherever it sits, in a cool blue
  that nothing else in the viewport uses, with a dark border round it so it
  reads on a pale object as well as against the background. Held points stay
  gold and are drawn larger, since the gumball stands on top of them. The
  control polygon joining the points is quieter than it was, so the points
  read louder than the lines between them.

- A boolean now leaves what it made selected, so the gumball is on it. Every
  command let go of the selection when it was done, which is right for most of
  them: you picked those objects to say which ones, and the pick has been
  spent. A boolean is the other sort. It eats what you picked and puts
  something else in its place, so letting go left you holding nothing at all,
  and the gumball that had been sitting on the solid you were working on
  simply went away rather than moving to the pieces that replaced it. Split
  hands you its pieces, union and intersection the result, and difference the
  objects it cut into.

## 0.5.10 — 2026-08-05

### Added

- **A control point you have clicked is a picked thing.** Points on for a
  curve used to draw them and let you fling one about with the mouse, and
  that was all: clicking a point selected nothing, so the gumball had
  nothing to anchor to and stayed on the whole curve. Now it comes to the
  point, ++shift++ adds a second, and the arrows, ring and knobs move the
  points they are holding and leave the rest of the curve alone. A held
  point is drawn gold. A point is asked for before a gumball handle,
  because both can be under the cursor at once and the point is the more
  particular thing to be pointing at.

- **`selpt` selects every point object**, the way `selcrv`, `selsrf` and
  `selsolid` already do for the rest.

- **A viewport can fill the window.** ++ctrl+m++, a double-click on a
  viewport's title, or `max`. `1view` looked like this and is not: it hides
  the three aux panes and leaves the *primary* one, so working in Top and
  asking for a single view lost Top. There was no way to make an aux pane
  full-size at all (GitHub #5). Maximise takes the pane you are in, and the
  second press puts back the layout you had, splitter positions included,
  rather than rebuilding the even 2x2.

- **Surface isocurves and edges can be switched off.** There is a Display
  panel beside Properties and Layers, and `isocurves` and `surfaceedges`
  commands. Rendered used to draw the wire cage over every surface just as
  shaded does, and on a surveyed model that is what you see instead of the
  model (GitHub #5). Each display mode now has its own default, rendered's
  being off, and the panel sets a per-viewport override on top that
  survives a mode change. It is the pane's own setting, so four panes stay
  four panes.

### Changed

- **Hidden geometry is read but not converted.** An object the file
  marks hidden now arrives as a promise of geometry rather than the
  geometry itself, and is converted when you tick its layer back on,
  unhide it, export, or otherwise ask for it. On a 61 MB survey drawing
  with three layers ticked, opening goes from 10.73s to 8.79s on four
  cores and 6.63s to 5.71s on eight (GitHub #5).

  One consequence worth knowing about: objects the file did not name take
  their `3dm object NN` numbers from the object order now rather than the
  order shapes came out of the converter, so those numbers differ from
  what an older build gave the same file. Objects the file does name are
  untouched.

### Fixed

- A typed length is now a point at every point prompt. It only became one
  where the command named an axis of its own, or where ++tab++ had frozen a
  direction. At the end of a line, the next vertex of a polyline, the far
  corner of a box, the number came back as coordinates and the prompt sat
  there, so a shape begun with the mouse could not be finished from the
  keyboard. The direction is read off the point the cursor is making, so
  object snap, grid and ortho all have their say before the number is
  applied, and ++tab++ still wins where it is held.
- A number at the far corner of a box or a rectangle is a side, not the
  diagonal, and which quadrant the sides run into is read off where the
  cursor is aiming.
- With four panes up, a typed length is aimed by the pane the mouse is in
  rather than the pane the command happens to be acting on.
- Scale1D would not take a factor. Every other scale offers one the moment
  it has a base point; Scale1D wanted a reference point, so clicking the
  base and typing 0.5 scaled nothing.
- Clicking a pane never made it the active one. The window had two
  `eventFilter` methods and Python kept the second, so every pane but
  Perspective was live to draw in and dead to everything that asks which
  pane you are in.
- Dragging a box round a point object selected nothing: the box pick looked
  for edges to cross and triangle vertices to fall inside, and a point is
  neither.
- Points on did nothing for a polyline. Every route to a control point went
  through one edge's b-spline and gave up the moment it was handed more than
  one, so the commonest thing anybody draws was told to explode itself
  first. A corner is two poles underneath but one point to the hand, so
  dragging it moves both its segments together.
- The rubber band, the frame readout and the ghost of a typed number went to
  the Perspective pane wherever you were drawing. They belong in every pane;
  the distance itself is written beside the cursor, in the one pane it is in.
- A line begun in one pane could not be finished in another, and Front and
  Right could not produce a point at all. Every pane drew on the world XY
  plane, and a pane looking along that plane sends its pick ray straight
  down it, never meeting it. A pane set to a named standard view now draws
  on the plane that view faces, so half a four-pane layout is somewhere you
  can draw as well as look, and those panes get a grid of their own instead
  of the world grid seen edge-on.
- The toolbar and the panes came up torn on some launches. The toolbar and
  menu bar were built after the saved layout was restored, so last session's
  dock sizes were laid into a window one toolbar narrower than the one
  anybody sees, and the two passes that settle the layout afterwards never
  asked the panes to draw again at the size they had just been given.
- Every object in a file got a display mesh and vertex buffers whether or
  not its layer was switched on, because the viewport drew
  `visible_objects()` but reconciled its GPU cache over `all()`. The
  510 MB file in GitHub #5 has roughly 65,000 objects and three ticked
  layers, so about 93% of that work was for geometry no draw loop would
  reach. Buffers are released when a layer goes off now, and rebuilt when
  it comes back on.

## 0.5.9 — 2026-08-03

### Added

- **++ctrl++-click stands a vertical up from the construction plane** —
  Rhino's elevator mode. Click a point on the CPlane with ++ctrl++ held and
  the pick runs up the axis through it, so the height can come from the
  mouse or be typed at the prompt. It is the same lock Tab takes, which is
  why everything the lock already does comes with it: the readout, the typed
  distance, the release at the next point. A command that picks along an
  axis of its own, like the height of an extrusion, keeps it.

### Fixed

- Object snaps stopped working while a direction was held. Locking one took
  the point over completely and never consulted them, which left no way to
  run a line out to the height of something already drawn. A snap can't pull
  the point off the locked line, but it now says where along it the thing it
  found sits.
- A locked direction takes a typed length. Tab freezes the direction the
  cursor is pointing in, and the prompt has said "type a length" since it
  landed, but nothing carried the lock as far as the parser: only a command
  with an axis of its own, like the height of an extrusion, accepted a bare
  number. `line` after Tab still wanted a mouse move and a click, or polar
  coordinates typed out in full. A command that names its own direction
  still keeps it, and typed coordinates still override both.

## 0.5.8 — 2026-08-02

### Fixed

- A Make2D curve no longer takes the program with it. `make2d` builds its
  curves on the projection plane, so they carry a 2D curve and the plane it
  lies on rather than a 3D curve of their own, and OCCT answers a request for
  the 3D one with nothing at all. Both places that asked took the answer at
  face value: writing a drawing out to `.3dm` to send to a Rhino seat, and
  reading a curve's control points, which is a button on the tool strip and so
  needs no export to reach. Neither raised — the process died where it stood,
  with whatever was unsaved. Nothing else was affected: lines, arcs, circles,
  interpolated curves and a solid's own edges all carry real 3D curves and all
  wrote correctly. The missing curve is now computed from the 2D one and the
  plane before either operation runs.

- The title block and the scale bar are readable on the sheet. Both drew their
  own text through their own linework. The project name and the drawing title
  were positioned from the top of the whole block instead of from the rule
  under each row, so the project name sat across the frame and the title had
  the rule below it struck through the middle. The scale bar stands above its
  baseline and its labels were drawn on that same baseline, which put the
  leading digit of "1000 mm" inside the last black segment and hid the "0" at
  the left end under the first; the labels go below the bar now.

- The tool palette can be measured before it has been laid out. Its size hint
  read a height that is only worked out once every button exists, and a hint
  asked for any earlier raised inside a Qt override — where it surfaces not as
  itself but as a bare `SystemError` naming whichever widget Qt happened to be
  laying out at the time.

## 0.5.7 — 2026-08-01

### Added

- `.3dm` files for Rhino 5 through 8, written from Save as well as Export.
  Everything went out as Rhino 8, so a file sent to a colleague on an older
  seat would not open at all, and `.3dm` was reachable only through Export —
  `save out.3dm` wrote `out.3dm.serp`. The export dialog now lists Rhino 8,
  7, 6 and 5 as separate filters and writes whichever was chosen; Save and
  Save As offer the same four beside the native format, noting that layouts
  and history live only in `.serp`, and the save command keeps any writable
  extension you type. The docs called `.3dm` an exact round trip, which it is
  not: curves stay NURBS, surfaces write as meshes, and STEP is the exact one.

- The window comes back the way you left it. Geometry, dock sizes and the
  viewport layout all reset on every launch, and the side panel was re-imposed
  at 280 px however wide you had dragged it — which reads as a program with no
  standard arrangement to set. All three are saved on close and restored next
  launch. Only a window somebody actually saw writes them, so a headless run
  closing cannot overwrite a real layout with a default-constructed one. The
  drag separator goes to 6 px with a gold hover so it can be found, and
  Settings → Display gains the display mode new viewports open in, instead of
  always shaded.

### Changed

- A new drawing opens in four viewports, and each pane's title bar is its own
  menu. Both the quad layout and the per-viewport display menu had shipped
  already; this is about where they are rather than what they do. Four
  Viewports and Single Viewport move out of View → Viewports up into View
  itself, leaving behind the rarer business of adding panes. A pane's title
  now carries the view, all eight display modes, zoom extents and the layout,
  acting on that pane rather than on whichever one was last clicked, and it
  says what the pane is showing. The translucent chips that floated inside
  each viewport did half the same job a thumb's width away, so they are gone —
  the title menu has everything they had, Back, Left and Bottom included. The
  four-viewport start is a default only: the layout you leave in is still the
  one you come back to.

### Performance

- Opening a large mechanical `.3dm`: 194.6 s to 51.3 s on a 230 MB cab file.
  Such a file is one or two enormous unioned polysurfaces, and only meshes
  were ever split across the worker pool, so a 19105-face solid was a single
  worker's problem for two and a half minutes while the rest of the pool sat
  idle — every core busy, one of them doing the work. Breps past 512 faces
  (`SERP3D_IMPORT_SPLIT_FACES`) now go out as face ranges the way big meshes
  do, each worker caching the brep's edge table once, and the pieces are sewn
  back into a solid when the last one lands. The per-face edge prune, paid
  19105 times, was also sweeping all 48k edge boxes; it binary-searches boxes
  sorted by least x instead, so only the candidates in the face's span are
  compared. Same 1601 objects out.

- Four viewports cost one copy of the model rather than four. Every viewport
  uploaded its own vertex data for every object: on the cave file 2485 MB of
  GPU buffers where 621 MB would do, and about 2 GB of resident memory for
  the three extra views. Buffers are shareable between contexts in a share
  group, so they are uploaded once and handed out through a reference-counted
  registry; vertex arrays are not shareable and stay per viewport, which costs
  nothing worth counting. Switching to quad on that file went from +2029 MB of
  resident memory to +39 MB.

- Translucent objects are sorted once a frame, not once per object. A single
  object with opacity below 1 puts the whole scene through a back-to-front
  sort, and the sort key was two arrays and a norm worked out per object per
  frame — 6583 times a frame on the cave file, in every viewport, about a
  fifth of a full redraw. The distance is one vectorised subtraction now, over
  centres cached against the mesh they were read from, so an orbit reuses them
  while a remesh cannot. Five frames profiled on that file: quad 7.52M calls
  in 3.24 s to 6.07M in 2.63 s, single 0.91M in 0.63 s to 0.55M in 0.27 s. The
  drawing order is unchanged, ties and objects without bounds included.

- The GPU cache is reconciled when the scene moves rather than on every paint.
  Deciding what needs buffers, what changed linetype and what has gone was
  7064 objects of bookkeeping a frame on the cave file, four times over in the
  quad layout, to reach the same answer as the frame before. It now runs only
  when something it reads has changed — the scene revision, plus a layer's
  linetype and a finished background tessellation, neither of which notifies
  the scene. A full redraw in quad walks the scene 0 times in 40 reconciles.

### Fixed

- Zooming into a detail no longer erases the model around it. The near and far
  clip planes came from the camera distance alone, so closing in on a small
  part collapsed the far plane to a few hundred units and clipped away
  everything behind it. The near floor of 0.01, shared with the zoom clamp,
  put a millimetre detail out of reach besides. The camera now takes the scene
  bounds and derives its planes from them: far reaches the farthest corner of
  the model, near scales with how close you are. The viewport feeds it those
  bounds — the grid included, since it is drawn with the same projection —
  when the scene or the grid changes rather than per frame.

- Hidden layers and objects stay hidden through a `.3dm` round trip. A working
  Rhino file keeps its reference and construction layers switched off; the
  layer table was read but not its visible and locked flags, so opening one put
  everything on show at once. Layer visibility and lock now ride through into
  the scene, per-object hide state with them — a hidden block instance hides
  its members, whose own flags are read inside the definition — and all three
  are written back out.

- A right-click never repeats delete. Right-clicking an idle prompt is Enter
  and Enter repeats the last command, which is Rhino and worth keeping, but it
  put delete one reflex away at all times: pick, delete, right-click to get on
  with something, and whatever is picked now goes too. Commands carry a
  repeatable flag now, and one that is never repeated does not disturb the
  repeat target either, so Enter after a delete goes back to what you were
  drawing.

- New window width goes to the viewports, not the side panel. Maximising handed
  every new pixel to the Properties / Layers column: a 400 px wider window meant
  a 400 px wider panel and not one pixel more drawing, where the viewport is the
  whole reason for the extra screen. The column holds its width across a window
  resize now — maximise included, which lays the docks out half a millisecond
  before the window is told it has resized and so looked exactly like somebody
  dragging the splitter — and dragging the splitter still sets it. A panel
  restored from a saved layout may keep up to three tenths of the window and no
  less than the 280 px a fresh one opens at, so a width dragged out in a
  maximised window does not come back as half of a small one. On a 1444 px
  window that is 433 px rather than 924, and four viewports of 460 px rather
  than 216.

- Every tool stays on the tool strip. Thirty-two tools want 1076 px of column
  and a restored 936 px window gives the strip 854, so Trim, Split, Offset,
  Fillet, Join, Explode, Control points and Delete went into an extension
  chevron at the bottom that nobody finds — eight tools, Delete among them,
  gone from the palette because the screen was not tall enough. The strip is
  one widget now rather than thirty-two toolbar actions: one column of
  full-size tools, and the few that do not fit scroll into view instead of
  being hidden. A maximised window shows all thirty-two at once.

## 0.5.6 — 2026-07-31

### Added

- The About box says which version you are running. It is opened for one of
  two reasons — somebody wants to know what this program is, or somebody is
  filing a bug and needs to say what they are on — and it answered the first
  and not the second, because it never named its own version. It now carries
  a build table: the version, Python, Qt, the OpenCASCADE kernel and the
  host platform, each selectable, with one button that puts the lot on the
  clipboard in the shape an issue wants it pasted. Links to the docs, the
  repository and the support page sit alongside, and the licence and where
  the name comes from are still on it.

- `scalenu` can be pointed at rather than typed at. Every other scale command
  lets you grab a reference point and drag it to where it should end up;
  scalenu wanted three numbers and showed you nothing until it was over,
  which is the one scale where the numbers are hardest to work out in your
  head, because there are three of them and each is about a different
  direction. Its first prompt now takes a point as well as a factor: pick
  one and a second point sets every axis at once, each by how much further
  the point ended up than it started, with a ghost of the result following
  the cursor. An axis the reference point does not move along has no
  reference length, so nothing about it is being asked and it keeps its
  size. Typing the factors works exactly as before, and now previews as you
  type each one.

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

- The first right-click after a command finishes repeats it, instead of the
  second. Right-click is Enter, and Enter on an idle prompt has always meant
  repeat; the click that ends a command is taken by the command itself, so
  the one after it was already a gesture made on an idle prompt. Swallowing
  it meant the gesture did nothing the first time you made it.

- A long filename in the welcome screen's recent list is shortened rather
  than scrolled to. The dialog is a fixed width, so the name could never be
  given room — it could only push a horizontal scrollbar into the bottom of
  the card and ask you to drag it sideways. It now gives in the middle, where
  a file's own name is, rather than at the end, where its kind is; the whole
  path is still on the tooltip.

- Dragging out a rectangle no longer draws a line across it. `rectangle`,
  `box` and `clippingplane` all ask for an opposite corner while a ghost of
  the frame is already under the cursor, and all three were also hanging a
  rubber band from the first corner — which could only run corner to opposite
  corner, straight through the middle of the shape it was meant to be helping
  you place. The number that band carried was the length of that diagonal;
  it now reads the two sides instead, at the corner you are dragging, in the
  units they are being drawn in and on the plane they are being drawn on. A
  band that is still the line being drawn — `line`, an arc, a circle's radius,
  the height of a box — is untouched.

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
