"""Surface creation commands."""

from ..core import geometry as g
from .base import LengthReq, NumberReq, OptionReq, PointReq, SelectReq, command


@command("extrude", aliases=("ext", "extrudecrv"))
def cmd_extrude(ctx):
    curves = yield SelectReq("Select curves to extrude", kinds=("curve",))
    dist = yield LengthReq("Extrusion distance", default=10.0)
    cap_opt = "No"
    if any(g.is_closed_curve(c.shape) for c in curves):
        cap_opt = yield OptionReq("Cap closed curves to make solids?",
                                  options=["Yes", "No"], default="Yes")
    direction = tuple(ctx.cplane.normal)
    made = []
    for c in curves:
        srf = g.extrude(c.shape, direction, dist, cap=(cap_opt == "Yes"))
        made.append(ctx.scene.add(srf))
    ctx.echo(f"Extruded {len(made)} object(s): "
             + ", ".join(o.name for o in made))


@command("revolve", aliases=("rev",))
def cmd_revolve(ctx):
    curves = yield SelectReq("Select curve to revolve", kinds=("curve",),
                             max_count=1)
    p1 = yield PointReq("Start of revolve axis")
    p2 = yield PointReq("End of revolve axis", rubber_from=p1)
    angle = yield NumberReq("Angle in degrees", default=360.0)
    axis_dir = tuple(b - a for a, b in zip(p1, p2))
    srf = g.revolve(curves[0].shape, p1, axis_dir, angle)
    obj = ctx.scene.add(srf)
    ctx.echo(f"Created {obj.name}.")


@command("loft")
def cmd_loft(ctx):
    curves = yield SelectReq("Select 2 or more profile curves in order",
                             kinds=("curve",), min_count=2)
    style = yield OptionReq("Loft style", options=["Normal", "Ruled"],
                            default="Normal")
    srf = g.loft([c.shape for c in curves], ruled=(style == "Ruled"))
    obj = ctx.scene.add(srf)
    ctx.echo(f"Lofted {len(curves)} curves into {obj.name}.")


@command("planarsrf", aliases=("planar", "planesrf"))
def cmd_planar(ctx):
    curves = yield SelectReq("Select closed planar curves", kinds=("curve",))
    made = []
    for c in curves:
        made.append(ctx.scene.add(g.planar_face(c.shape)))
    ctx.echo(f"Created {len(made)} planar surface(s).")


@command("sweep1", aliases=("sweep",))
def cmd_sweep1(ctx):
    rails = yield SelectReq("Select rail curve", kinds=("curve",), max_count=1)
    profiles = yield SelectReq("Select profile curve", kinds=("curve",),
                               max_count=1, allow_preselected=False)
    srf = g.sweep1(profiles[0].shape, rails[0].shape)
    obj = ctx.scene.add(srf)
    ctx.echo(f"Created {obj.name}.")


@command("offsetsrf")
def cmd_offsetsrf(ctx):
    objs = yield SelectReq("Select surfaces to offset",
                           kinds=("surface", "solid"))
    dist = yield LengthReq("Offset distance (negative flips side)")
    made = []
    for o in objs:
        made.append(ctx.scene.add(g.offset_surface(o.shape, dist),
                                  layer_id=o.layer_id))
    ctx.echo(f"Offset {len(made)} surface(s).")


@command("shell")
def cmd_shell(ctx):
    objs = yield SelectReq("Select solids to shell", kinds=("solid",))
    thickness = yield LengthReq("Wall thickness", minimum=1e-9)
    for o in objs:
        ctx.scene.replace_shape(o.id, g.shell_solid(o.shape, thickness))
    ctx.echo(f"Shelled {len(objs)} solid(s) with wall {thickness:g}.")


@command("sweep2")
def cmd_sweep2(ctx):
    rail1 = yield SelectReq("Select first rail", kinds=("curve",),
                            max_count=1)
    rail2 = yield SelectReq("Select second rail", kinds=("curve",),
                            max_count=1, allow_preselected=False)
    profiles = yield SelectReq("Select profile curve", kinds=("curve",),
                               max_count=1, allow_preselected=False)
    srf = g.sweep2(profiles[0].shape, rail1[0].shape, rail2[0].shape)
    obj = ctx.scene.add(srf)
    ctx.echo(f"Created {obj.name}.")
