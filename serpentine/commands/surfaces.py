"""Surface creation commands."""

from ..core import geometry as g
from .base import NumberReq, OptionReq, PointReq, SelectReq, command


@command("extrude", aliases=("ext", "extrudecrv"))
def cmd_extrude(ctx):
    curves = yield SelectReq("Select curves to extrude", kinds=("curve",))
    dist = yield NumberReq("Extrusion distance", default=10.0)
    cap_opt = "No"
    if any(g.is_closed_curve(c.shape) for c in curves):
        cap_opt = yield OptionReq("Cap closed curves to make solids?",
                                  options=["Yes", "No"], default="Yes")
    made = []
    for c in curves:
        srf = g.extrude(c.shape, (0, 0, 1), dist, cap=(cap_opt == "Yes"))
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
