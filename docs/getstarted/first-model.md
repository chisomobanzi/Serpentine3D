# Your first model

Five minutes, from an empty scene to a rounded block you could 3D-print.
Everything is typed at the **command line** — the box at the bottom of the
window. Press ++enter++ after each entry; ++esc++ cancels a command.

!!! tip "Right-click = Enter"
    Anywhere in the viewport, a right-click does what ++enter++ does — it runs
    the command you've typed, accepts a value, or repeats the last command.
    You rarely need to reach for the keyboard's Enter key.

## 1. Start a new model

Launch Serpentine3D and pick **New model → millimetres** on the welcome
screen. You get an empty grid and a construction plane.

## 2. Make a box

Type `box`, then give two opposite corners:

```
box
first corner:   0,0,0
opposite corner: @40,40,20
```

`@40,40,20` is *relative* to the first point, so you get a 40 × 40 × 20 mm
block. It appears shaded on the grid.

## 3. Round the edges

```
filletedge
```

Click the edges you want rounded (they highlight), **right-click** when
you're done, then type a radius:

```
radius: 5
```

The block rebuilds with 5 mm rounded edges. (Prefer dragging? Hold
++ctrl+shift++ and click an edge to get a fillet handle on the gumball.)

<figure markdown>
  <video autoplay loop muted playsinline
         style="width:100%;max-width:900px;height:auto;border-radius:6px">
    <source src="../../assets/clips/fillet.webm" type="video/webm">
    <source src="../../assets/clips/fillet.mp4" type="video/mp4">
  </video>
  <figcaption>A bigger radius rounds the edges further — the exact solid
  rebuilds each time.</figcaption>
</figure>

## 4. Look around

- **Middle-mouse drag** orbits · **Shift + middle-drag** pans · **scroll** zooms
- ++f1++–++f4++ snap to Top / Front / Right / Perspective
- ++ctrl+e++ zooms to fit everything

## 5. Save it

```
save
```

`.serp` files are self-contained (they carry a thumbnail and autosave
cleanly). Give it a name and you're done.

## 6. Export it to print

```
export
```

Choose **STL — 3D printing**, pick a quality (**Fine** is a good default for
curved surfaces), and you have a watertight mesh ready for any slicer. Want
to check it first? Run `printcheck`, select the block, and you'll get a
watertight / manifold / thin-wall / overhang report.

---

**Next:** the longer [stage-flat tutorial](stage-flat.md) builds a real
theatrical flat and documents it on a drawing sheet — or jump to
[Export for 3D printing](../howto/3d-printing.md).
