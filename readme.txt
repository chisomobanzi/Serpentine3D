# Per-object transforms — what was implemented

## Why

Dragging hundreds of selected objects with the gumball froze the app. Every mouse
step rewrote the BREP geometry of every selected object (N kernel transforms +
re-tessellation + GPU re-upload + a journal dump of N B-REPs), and releasing the
mouse froze for 30-40 seconds (N bounding-box walks, buffer re-uploads, journal
flush). The geometry itself was the wrong thing to touch: a move, rotation or
scale does not change the shape, only its pose.

The fix follows Rhino's approach: each object carries an optional 4x4
transform; the shape stays in local coordinates. Moving, rotating or scaling
only writes the matrix. The BREP is rewritten only when the content genuinely
changes (sub-object edits, baking).

The same freeze class hid in the command previews: while running move or
rotate, every mouse move rebuilt the ghost geometry of the whole selection.

## How (stages)

1. Core (serpentine3d/core/scene.py, tessellate.py)
   SceneObject.transform (4x4, None = identity); Scene.set_transforms (one
   batched scene notification for any number of objects); Scene.bake (folds a
   transform into the BREP, reusing the tessellation for pure translations via
   DisplayMesh.translated). bbox() caches the LOCAL box keyed on shape
   identity — the kernel walk runs once per shape, ever, and the pose is
   re-applied per read as a cheap 8-corner affine map.

2. Gumball (serpentine3d/ui/gumball.py)
   Whole-object move/rotate/scale drags write a live 4x4 into
   scene.drag_display (display-only; no scene revision bump) while dragging.
   On release one set_transforms call commits the pose — microsecond-scale,
   no geometry rewrite. Sub-object drags bake the held objects at drag start
   so part indices stay valid.

3. Viewport (serpentine3d/ui/viewport.py)
   Rendering, culling, selection cloud, ground shadow, clip-plane frames,
   picking and snapping are all transform-aware: each object is drawn with its
   pose folded into its GL matrix; boxes, candidates and picked points are
   mapped to world space.

4. Snaps (serpentine3d/core/snaps.py)
   Every snap (ends, mids, intersections, perpendicular feet, near, point
   cloud, apparent crossings) now runs in world space through the object's
   transform, so snaps land on moved, rotated and scaled objects.

5. Persistence (core/journal.py, core/replay.py, fileio/native.py, fileio/*)
   The journal diffs record the 16-float matrix instead of a BREP dump for
   pose-only edits; replay re-applies it via set_transforms. The .serp format
   stores the transform per object. All exporters (STEP, STL, OBJ, FBX, 3MF,
   USD, glTF, DXF, Rhino) export obj.world_geometry().

6. Commands (serpentine3d/commands/transform.py)
   move, rotate, scale, scale1d/2d, scale-by-numbers, mirror, orient,
   rotate3d, copy and all three arrays write 4x4 matrices via set_transforms
   instead of N BREP rewrites. Copies share the local shape (one tessellation
   per original) and carry the composed pose. Every copy-family command
   notifies the scene exactly once (batched). Held-part edits bake the held
   objects first, so they operate in world space.

7. Release-hang fix (core/scene.py)
   set_transforms no longer voids the per-object box cache (it used to,
   forcing N cold kernel walks on the first frame after every release).
   Measured on 200 torus solids: first frame after release 1.3 ms with the
   fix vs 1447 ms without.

8. Command previews (serpentine3d/commands/transform.py, ui/viewport.py,
   commands/base.py)
   While running move/rotate/scale/etc. the preview used to rebuild the BREP
   of every selected object on each mouse move (N kernel transforms +
   make_compound + full re-tessellation). Now pose commands (move, rotate,
   rotate3d, scale, scale_nu, mirror, orient, orient3pt, scale1d, scale2d)
   draw the objects themselves at the destination pose — a 4x4 per object in
   scene.drag_display, zero kernel work — and copy commands (copy, array,
   array_polar) draw a ghost built in numpy from the objects' existing
   tessellations. A preview is pixel-identical to the commit result; the
   command clears the display matrices on finish or cancel (base.py _finish).

## Result

- Dragging hundreds of objects is smooth: per-step cost is one display
  matrix per object and one scene notification; no geometry is touched until
  release.
- Command previews are equally fast: pose commands move the objects in
  place (one matrix write per object, zero kernel); copy commands draw a
  numpy ghost over the existing tessellations.
- The objects being moved/rotated/scaled (gumball drag or a command
  preview) are drawn ghosted (semi-transparent, no depth write) in the
  selection colour — the same highlight a selected object gets — so the
  uncommitted pose is visually distinct from committed geometry; the effect
  costs nothing extra (one per-object alpha and colour in the existing draw
  state) and drops on release.
- Committing a drag is O(N) matrix writes; undo/redo is free (object clones
  carry the transform).
- Saves, journals, replays and exports all keep the pose; the file format
  gained one optional field per object.
- 1543 related tests pass; 5 new test files cover the transform behavior.

## Files

Source (modified):
  serpentine3d/core/scene.py
  serpentine3d/core/tessellate.py
  serpentine3d/core/journal.py
  serpentine3d/core/replay.py
  serpentine3d/core/snaps.py
  serpentine3d/commands/base.py
  serpentine3d/commands/transform.py
  serpentine3d/ui/gumball.py
  serpentine3d/ui/viewport.py
  serpentine3d/fileio/__init__.py
  serpentine3d/fileio/native.py
  serpentine3d/fileio/dxf.py
  serpentine3d/fileio/gltf.py
  serpentine3d/fileio/rhino.py
  serpentine3d/fileio/usd.py

Tests (new):
  tests/test_objects_carry_a_transform.py
  tests/test_gumball_dragging_many_objects_tells_the_scene_once.py
  tests/test_moving_many_objects_is_a_display_offset_until_release.py
  tests/test_snaps_follow_a_transform.py
  tests/test_transform_commands_write_a_matrix.py

Tests (modified):
  tests/test_gumball.py
  tests/test_gumball_on_sheets.py
  tests/test_the_gumball_extrudes_what_it_holds.py
  tests/test_commands.py
  tests/test_commands_gaps.py
  tests/test_command_previews.py
  tests/test_control_points_in_every_pane_and_in_commands.py
  tests/test_draggable_distances.py
  tests/test_arraypath_orientation.py
  tests/test_rotate3d_takes_its_angle_from_the_mouse.py
  tests/test_scale_takes_a_typed_factor.py
  tests/test_scalenu_reference.py
  tests/test_transform_commands_reach_held_subobjects.py
  tests/test_model_text_snaps.py
  tests/test_sheet_command_target.py
  tests/test_sheet_copy.py
  tests/test_fileio.py
  tests/test_session_journal.py
