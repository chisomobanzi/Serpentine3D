# Tutorial: model and document a stage flat

A ten-minute tour: a theatrical flat (a braced timber frame with a
skin), documented on an A3 sheet. Everything is typed on the command
line; points can also be clicked in the viewport with osnaps.

## 1. Set up

```
units          → Feet-inches (or stay metric)
grid           → spacing to taste
```

## 2. The skin

```
rectangle      → 0,0 → 4'x8' (or 1220,2440)
extrude        → distance 18 (Cap=Yes chip stays on)
```

While the distance prompt is up you can click the **Cap=Yes** /
**BothSides=No** chips, and the gold ghost preview follows what you
type.

## 3. Rails and stiles

```
box            → 0,0,18 → @75,2440,75          (stile)
copy           → pick it, to the other side
box            → rails top/bottom/middle
```

Or draw one rail and use `array` for the rest. `group` the timbers.

## 4. Look

```
layer          → New "Timber", Weight 2
changelayer    → move the frame onto it
material       → Matte on the skin, pick colours in Layers panel
rendered       → environment-lit preview with a ground shadow
```

## 5. Document it

```
layout         → A3 landscape
detail         → drag a rectangle, front view, 1:20
dim            → dimension the width inside the detail
```

Dims picked inside a detail are **associative**: re-scale or pan the
detail and they follow. Double-click a detail to enter it; drag
annotations to move them, Delete removes them.

```
titleblock     → fill project/title
revision       → "A — issued for construction"
exportpdf      → print the sheet
```

## 6. Save

```
save           → flat.serp
```

`.serp` files are zip containers carrying a thumbnail and version
metadata — safe to autosave, safe to crash.

## Extra credit

- `recordhistory` before the extrude, then edit the base rectangle's
  control points (`pointson`) and watch the solid follow.
- `4view` for a Top/Front/Right/Perspective split.
- `curvaturegraph` and `zebra` for surface quality checks.
