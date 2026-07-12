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

## Curves

| Command | Does |
|---|---|
| `arc` (`a`) | Arc |
| `circle` (`c`, `ci`) | Circle |
| `curve` (`cv`, `interpcrv`) | NURBS curve interpolated through picked points. |
| `ellipse` (`el`) | Ellipse |
| `line` (`l`) | Line |
| `polyline` (`pl`, `pline`) | Polyline |
| `rectangle` (`rect`, `rec`) | Rectangle |

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
| `area` | Area |
| `cplane` | Reposition the construction plane (drawing plane + grid). |
| `curvature` | Curvature |
| `curvatureanalysis` (`curvmap`) | Curvatureanalysis |
| `distance` (`dist`) | Distance |
| `front` | Front |
| `ghosted` (`gh`) | Ghosted |
| `grid` | Grid |
| `gridsnap` | Gridsnap |
| `gumball` | Gumball |
| `length` (`len`) | Length |
| `namedview` (`nv`) | Namedview |
| `perspective` (`persp`) | Perspective |
| `pictureframe` (`picture`) | Place a reference image in the model (trace over photos/plans). |
| `pointsoff` (`pf`) | Pointsoff |
| `pointson` (`po`) | Show control points for selected curves and surfaces (F10). |
| `rendered` (`render`) | Environment-lit display with materials and a ground shadow. |
| `right` | Right |
| `shaded` (`sh`) | Shaded |
| `snap` (`osnap`) | Snap |
| `technical` (`tech`) | Hidden-line technical display (parallel projection linework). |
| `tolerance` | Show or set the document's absolute modelling tolerance. |
| `top` | Top |
| `units` | Set document units; optionally rescale the model to keep real size. |
| `volume` (`vol`) | Volume |
| `wireframe` (`wf`) | Wireframe |
| `zebra` | Zebra |
| `zoomextents` (`ze`, `zea`) | Zoomextents |

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
| `exportdxf` | Export the active layout sheet (or the model) to DXF. |
| `exportpdf` (`print`, `pdf`) | Exportpdf |
| `exportsvg` | Exportsvg |
| `hatch` | Hatch |
| `layout` | Layout |
| `leader` | Leader |
| `make2d` | Make2d |
| `revision` (`rev`) | Add a row to this sheet's revision table (drawn by the title block). |
| `scalebar` | Scalebar |
| `sheetindex` | Place an index of all sheets as a note on the current layout. |
| `text` (`note`) | Text |
| `titleblock` | Titleblock |

## Editing

| Command | Does |
|---|---|
| `delete` (`del`, `erase`) | Delete |
| `explode` (`x`) | Explode |
| `fillet` | Fillet |
| `hide` | Hide |
| `join` (`j`) | Join |
| `layer` | Layer |
| `material` (`mat`) | Assign a look (metallic/roughness/opacity) for rendered display |
| `offset` | Offset |
| `plugins` | List loaded plugins and where they came from. |
| `rebuild` | Rebuild |
| `recordhistory` (`history`) | Toggle record history: loft/extrude/revolve outputs rebuild when |
| `redo` | Redo |
| `rename` | Rename |
| `selall` (`sa`) | Selall |
| `selnone` (`sn`) | Selnone |
| `show` (`unhide`) | Show |
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

## Help

| Command | Does |
|---|---|
| `help` (`?`) | Describe a command, or list every command by category. |

## Organisation

| Command | Does |
|---|---|
| `block` | Turn a selection into a reusable block definition + one instance. |
| `blocklist` (`blockmanager`) | Blocklist |
| `breptomesh` (`meshify`) | Convert BREP objects into lightweight native meshes. |
| `count` | Count objects: totals by block, kind and layer (for takeoffs). |
| `group` | Group |
| `insert` | Insert |
| `lock` | Lock |
| `meshtobrep` | Convert mesh objects into exact BREP shells (slow for big meshes). |
| `ungroup` | Ungroup |
| `unlockall` (`unlock`) | Unlockall |

## Selection

| Command | Does |
|---|---|
| `invert` (`selinv`) | Invert |
| `isolate` | Isolate |
| `selcrv` (`selcurves`) | Selcrv |
| `sellast` | Sellast |
| `sellayer` | Sellayer |
| `selname` | Select objects whose name contains the given text. |
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
| `pushpull` (`pp`, `moveface`) | SketchUp-style push/pull on a planar face. |

## Solids

| Command | Does |
|---|---|
| `box` | Box |
| `cone` | Cone |
| `cylinder` (`cyl`) | Cylinder |
| `sphere` (`sph`) | Sphere |
| `torus` | Torus |

## Surfaces

| Command | Does |
|---|---|
| `blendcrv` (`blend`) | Blendcrv |
| `extrude` (`ext`, `extrudecrv`) | Extrude |
| `helix` | Helix |
| `loft` | Loft |
| `offsetsrf` | Offsetsrf |
| `patch` (`networksrf`) | Patch |
| `planarsrf` (`planar`, `planesrf`) | Planarsrf |
| `project` | Project |
| `pull` | Pull |
| `revolve` (`rev`) | Revolve |
| `shell` | Shell |
| `sweep1` (`sweep`) | Sweep1 |
| `sweep2` | Sweep2 |
| `textobject` (`textcurves`) | Textobject |
| `unrollsrf` (`unroll`) | Unrollsrf |

## Transforms

| Command | Does |
|---|---|
| `array` | Array |
| `arraypath` (`arraycrv`) | Arraypath |
| `arraypolar` | Arraypolar |
| `copy` (`co`, `cp`) | Copy |
| `mirror` (`mi`) | Mirror |
| `move` (`m`) | Move |
| `rotate` (`ro`) | Rotate |
| `scale` (`sc`) | Scale |
| `scalenu` | Scalenu |

