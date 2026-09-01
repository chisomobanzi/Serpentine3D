# Command reference

Every command is typed on the command line (Tab completes,
F1 opens this list inside the app). Aliases in parentheses.

## Booleans

| Command | Does |
|---|---|
| `booleandifference` (`difference`, `bd`) | Booleandifference |
| `booleanintersection` (`intersection`, `bi`) | Booleanintersection |
| `booleanunion` (`union`, `bu`) | Booleanunion |

## Camera

| Command | Does |
|---|---|
| `camera` (`cam`) | Camera |

## Capture

| Command | Does |
|---|---|
| `turntable` | Orbit the camera once around the work and write a video clip; |
| `turntableui` | Record a portrait turntable of the current shot and application UI. |

## Curves

| Command | Does |
|---|---|
| `arc` (`a`) | Arc through three points; or Center and a sweep, or StartEnd. |
| `circle` (`c`, `ci`) | Circle from center and radius; or 2Point across, or 3Point through. |
| `closecrv` (`cc`, `closecurve`) | Close open curves with a straight segment between their ends. |
| `curve` (`cv`) | NURBS curve by control points, as Rhino's Curve does. |
| `divide` | Divide |
| `ellipse` (`el`) | Ellipse from center and two radii; Diameter takes an axis whole. |
| `interpcrv` (`interpcurve`) | NURBS curve through picked points; Close joins it back smoothly. |
| `line` (`l`) | Straight line; BothSides grows it evenly out of its middle. |
| `point` (`pt`) | Point |
| `polyline` (`pl`, `pline`) | Polyline |
| `rectangle` (`rect`, `rec`) | Rectangle corner to corner; or Center out, or 3Point to lean it. |
| `tweencurves` (`tween`) | Tweencurves |

## Deformation

| Command | Does |
|---|---|
| `bend` | Bend |
| `curvaturegraph` (`combs`) | Toggle curvature combs on selected curves. |
| `draftanalysis` (`draft`) | Colour faces by draft angle relative to the pull direction (+Z): |
| `extend` | Extend |
| `flow` (`flowalongcrv`) | Flow |
| `matchcrv` (`match`) | Matchcrv |
| `taper` | Taper |
| `twist` | Twist |

## Display & views

| Command | Does |
|---|---|
| `1view` (`oneview`, `singleview`) | 1view |
| `4view` (`fourview`, `quadview`) | Split the model area into Top / Front / Right / Perspective. |
| `ai` (`assistant`) | Open the AI assistant panel — model by describing what you want. |
| `angle` | Angle at a vertex point between two directions. |
| `area` | Area |
| `back` | Back |
| `bottom` | Bottom |
| `clippingplane` (`clip`) | Place a rectangular clipping plane on the CPlane: geometry on its |
| `cplane` | Reposition the construction plane (drawing plane + grid). |
| `curvature` | Curvature |
| `curvatureanalysis` (`curvmap`) | Curvatureanalysis |
| `disableclippingplane` (`dcc`) | Pause clipping planes (they stay in the scene, the cut stops). |
| `distance` (`dist`) | Distance |
| `enableclippingplane` (`ecc`) | Re-enable paused clipping planes. |
| `floatviewport` (`floatvp`) | Open a floating viewport window (drag it to another monitor). |
| `front` | Front |
| `ghosted` (`gh`) | Ghosted |
| `grid` | Grid |
| `gridsnap` | Gridsnap |
| `gumball` | Gumball |
| `isocurves` (`showisocurves`) | Show or hide the wires across surfaces in this viewport. |
| `isometric` (`iso`) | Isometric |
| `left` | Left |
| `length` (`len`) | Length |
| `maxviewport` (`max`, `maximizeviewport`) | Give the pane you are in the whole window; again puts it back. |
| `namedview` (`nv`) | Namedview |
| `newviewport` (`newvp`, `splitview`) | Open an extra live viewport in a dockable panel — drag its title |
| `ortho` | Toggle ortho: picked points lock to CPlane axes from the last |
| `osnap` | Toggle one object-snap type (or All = the master switch) — |
| `perspective` (`persp`) | Perspective |
| `pictureframe` (`picture`) | Place a reference image in the model (trace over photos/plans). |
| `pointsoff` (`pf`) | Pointsoff |
| `pointson` (`po`) | Show control points for selected curves and surfaces (F10). |
| `printcheck` (`printinfo`) | Check selected objects for 3D-print readiness: watertight, manifold, |
| `radius` | Radius of curvature of a curve at a picked point. |
| `redoview` | Go forward again through the views `undoview` stepped back through. |
| `rendered` (`render`) | Environment-lit display with materials and a ground shadow. |
| `right` | Right |
| `selclippingplane` | Select every clipping plane object. |
| `shaded` (`sh`) | Shaded |
| `snap` | Snap |
| `spacemouse` (`3dmouse`) | SpaceMouse status, on/off toggle, and a live axis readout for |
| `surfaceedges` (`showedges`) | Show or hide the outlines of faces. Curves and text are unaffected. |
| `technical` (`tech`) | Hidden-line technical display (parallel projection linework). |
| `tolerance` | Show or set the document's absolute modelling tolerance. |
| `top` | Top |
| `undoview` | Put the view back where it was before the last view change. |
| `units` | Set document units; optionally rescale the model to keep real size. |
| `viewcapturetoclipboard` (`vcc`) | Copy the active viewport image to the clipboard. |
| `viewcapturetofile` (`vcf`, `viewcapture`) | Save the active viewport as a PNG image. |
| `volume` (`vol`) | Volume |
| `wireframe` (`wf`) | Wireframe |
| `zebra` | Zebra |
| `zoom` (`z`) | Zoom the active view: Selected, Extents, a picked Window, In, Out. |
| `zoomextents` (`ze`, `zea`) | Zoomextents |
| `zoomselected` (`zs`) | Frame the current selection in the active view. |
| `zoomwindow` (`zw`) | Zoom into a window picked with two corner points. |

## Drafting & layouts

| Command | Does |
|---|---|
| `annotedit` (`editnote`, `edittext`) | Edit the annotation nearest a picked point (text, style). |
| `detail` | Detail |
| `detailborder` | Detailborder |
| `detaildelete` | Detaildelete |
| `detaillock` | Detaillock |
| `detailmode` | Detailmode |
| `detailscale` | Detailscale |
| `detailsection` | Detailsection |
| `dim` (`dimension`, `dimlinear`) | Dim |
| `dimangle` (`dimangular`) | Dimangle |
| `dimdiameter` (`dimdia`) | Dimdiameter |
| `dimradius` (`dimr`) | Dimradius |
| `dimstyle` (`textstyle`) | Create or edit a named annotation style (text height, arrows). |
| `dot` (`annotationdot`) | Model-space annotation dots: a label bubble anchored to a 3D point. |
| `exportdxf` | Export the active layout sheet (or the model) to DXF. |
| `exportpdf` (`print`, `pdf`) | Exportpdf |
| `exportsvg` | Exportsvg |
| `hatch` | Hatch |
| `layout` | Layout |
| `leader` | Leader |
| `make2d` | Make2d |
| `revision` | Add a row to this sheet's revision table (drawn by the title block). |
| `scalebar` | Scalebar |
| `sheetindex` | Place an index of all sheets as a note on the current layout. |
| `text` (`note`) | Text |
| `titleblock` | Titleblock |

## Editing

| Command | Does |
|---|---|
| `boundingbox` (`bb`) | Create the world-aligned bounding box of the selection. |
| `chamfer` | Bevel the corner between two curves with straight cut-offs. |
| `delete` (`del`, `erase`) | Delete |
| `dir` | Show which way curves run and which way surfaces face. |
| `explode` (`x`) | Explode |
| `fillet` | Fillet |
| `flip` | Turn curves round and surfaces inside out, as Rhino's Flip does. |
| `hide` | Hide |
| `insertknot` (`insertcontrolpoint`) | Add a control point to a curve without moving the curve. |
| `join` (`j`) | Join |
| `layer` | Layer |
| `material` (`mat`) | Assign a look (metallic/roughness/opacity) for rendered display |
| `offset` | Offset |
| `plugins` | List loaded plugins and where they came from. |
| `rebuild` | Rebuild |
| `recordhistory` (`history`) | Toggle record history: loft/extrude/revolve outputs rebuild when |
| `redo` | Redo |
| `removecontrolpoint` | Delete the control points you are holding, as Delete does. |
| `removeknot` | Take a knot out of a curve and say how far the curve moved. |
| `rename` | Rename |
| `selall` (`sa`) | Selall |
| `selnone` (`sn`) | Selnone |
| `show` (`unhide`) | Show |
| `smooth` | Relax a curve's control points toward their neighbours. |
| `split` | Split |
| `trim` (`tr`) | Trim |
| `undo` | Undo |

## Files

| Command | Does |
|---|---|
| `export` (`exp`) | Export |
| `import` (`imp`) | Import |
| `new` | New |
| `open` | Open |
| `save` | Save |
| `setdefaultapp` | Make Serpentine3D the default application for .serp files. |

## Help

| Command | Does |
|---|---|
| `help` (`?`) | Describe a command, or list every command by category. |

## Organisation

| Command | Does |
|---|---|
| `audit` | Check every object's geometry for validity. |
| `block` | Turn a selection into a reusable block definition + one instance. |
| `blocklist` (`blockmanager`) | Blocklist |
| `breptomesh` (`meshify`) | Convert BREP objects into lightweight native meshes. |
| `bringforward` (`bringforwards`) | Nudge the selected objects one step towards the front. |
| `bringtofront` (`bf`) | Draw the selected objects on top of overlapping ones. |
| `changelayer` (`tolayer`) | Move objects to a layer by name (created if missing). |
| `count` | Count objects: totals by block, kind and layer (for takeoffs). |
| `group` | Group |
| `insert` | Insert |
| `linetype` (`lt`, `setlinetype`) | Set the dash style of selected objects (Continuous/Dashed/…/ByLayer). |
| `lock` | Lock |
| `lockother` | Lock everything except what you picked, as Rhino's LockOther does. |
| `matchprops` (`matchproperties`) | Copy layer, colour and material from one object to others. |
| `meshtobrep` | Convert mesh objects into exact BREP shells (slow for big meshes). |
| `purge` | Remove empty layers and unused block definitions. |
| `sendbackward` (`sendbackwards`) | Nudge the selected objects one step towards the back. |
| `sendtoback` (`sb`) | Draw the selected objects behind overlapping ones. |
| `ungroup` | Ungroup |
| `unlockall` (`unlock`) | Unlockall |
| `what` | Report details of the selected objects. |

## Selection

| Command | Does |
|---|---|
| `invert` (`selinv`) | Invert |
| `isolate` | Isolate |
| `selcrv` (`selcurves`) | Selcrv |
| `seldup` | Select later duplicates of identical, identically-placed objects. |
| `selfilter` (`selectionfilter`) | Restrict viewport picking to one kind of object (Off = anything). |
| `selfiltertoggle` (`sft`) | Pause/resume the selection filter without changing its kind. |
| `sellast` | Sellast |
| `sellayer` | Sellayer |
| `selname` | Select objects whose name contains the given text. |
| `selprev` | Restore the previous selection. |
| `selpt` (`selpoints`) | Selpt |
| `selsolid` (`selsolids`) | Selsolid |
| `selsrf` (`selsurfaces`) | Selsrf |
| `unisolate` | Unisolate |

## Solid editing

| Command | Does |
|---|---|
| `booleansplit` (`bsplit`) | Split solids with cutters, keeping every piece. |
| `cap` | Cap |
| `chamferedge` (`che`) | Chamferedge |
| `contour` | Contour |
| `filletedge` (`fe`) | Fillet edges. Ctrl+Shift-click edges first to fillet only those; |
| `intersect` (`int`) | Intersect |
| `mergeallcoplanarfaces` (`mergeallfaces`) | Fuse coplanar neighbouring faces of each selected polysurface. |
| `pushpull` (`pp`, `moveface`) | SketchUp-style push/pull on a planar face. |
| `section` (`sec`) | Cut the selection with a plane drawn as a line across it. |

## Solids

| Command | Does |
|---|---|
| `box` | Box from a base and height; Center spreads the base evenly. |
| `cone` | Cone |
| `cylinder` (`cyl`) | Cylinder |
| `sphere` (`sph`) | Sphere from center and radius; 2Point spans a diameter instead. |
| `torus` | Torus |

## Surfaces

| Command | Does |
|---|---|
| `blendcrv` (`blend`) | Blendcrv |
| `blendsrf` | G1 blend surface between two Ctrl+Shift-picked surface edges. |
| `dupborder` | Dupborder |
| `dupedge` | Duplicate Ctrl+Shift-picked edges as curves. |
| `dupfaceborder` | Duplicate the border wires of Ctrl+Shift-picked faces as curves. |
| `edgesrf` (`srfedges`) | Edgesrf |
| `extendsrf` | Extend a surface past a Ctrl+Shift-picked boundary edge. |
| `extractisocurve` (`isocurve`) | Extractisocurve |
| `extractsrf` (`extractsurface`, `extractface`) | Pull Ctrl+Shift-picked faces out of the polysurfaces holding them. |
| `extrude` (`ext`, `extrudecrv`) | Extrude |
| `helix` | Helix |
| `loft` | Loft |
| `offsetsrf` | Offsetsrf |
| `patch` (`networksrf`) | Patch |
| `pipe` | Pipe |
| `planarsrf` (`planar`, `planesrf`) | Planarsrf |
| `project` | Project |
| `pull` | Pull |
| `revolve` (`rev`) | Revolve |
| `shell` | Shell |
| `sweep1` (`sweep`) | Sweep1 |
| `sweep2` | Sweep2 |
| `textobject` (`textcurves`) | Textobject |
| `unrollsrf` (`unroll`) | Unrollsrf |
| `untrim` | Untrim |

## Transforms

| Command | Does |
|---|---|
| `array` | Array |
| `arraypath` (`arraycrv`) | Arraypath |
| `arraypolar` | Arraypolar |
| `copy` (`co`, `cp`) | Copy |
| `mirror` (`mi`) | Mirror |
| `move` (`m`) | Move |
| `orient` (`o2`) | Remap objects from two reference points to two target points |
| `orient3pt` (`o3`) | Remap objects from three reference points to three target points |
| `projecttocplane` (`flatten`) | Flatten curves/surfaces/points onto the construction plane. |
| `rotate` (`ro`) | Rotate around the CPlane normal: type an angle, or pick a |
| `rotate3d` (`ro3`) | Rotate around an arbitrary axis picked as two points. |
| `scale` (`sc`) | Scale about a base point: type a factor, or grab a reference |
| `scale1d` | Stretch along one direction only: type a factor and it stretches |
| `scale2d` | Scale in the CPlane only (thickness along the CPlane normal is |
| `scalenu` | Scale by a different amount along each axis: type the three |
| `setpt` (`setpoints`) | Force chosen coordinates of every control point to one value — |

