"""Camera arm v4: start pad + end pad + ONE spline + a rectangle swept along it, then shelled.
(replaces the space frame; user decision 2026-10-11)

Run (headless FreeCAD on the workstation):   CAM_ARM_OUT=/path/out freecad.cmd camera_arm_shell.py

Frame: origin = centre of the 46x46 pad on the pillar top, z=0 = pillar top (330 mm above the
bed), +X toward the bed centre, +Y toward the bed, +Z up. ASSUMED = from chat 2026-10-11.

Start pad : 60x60x8 plate (on the 46x46 pillar top), 4x M4 countersunk (DIN 7991) on the 25 mm square.
End pad   : 50 x 6 mm vertical plate, normal = machine Y, face y = LENS_Y - LENS_OFFSET + PLATE_T,
            1/4" slot 6.6 x 40 vertical (+/-20 mm). Bolt axis Y -> camera axes parallel to X/Y,
            lens target 50 mm beyond the plate face.
Spline    : leaves the start pad vertically (+Z), arrives at the end pad horizontally (+Y).
Sweep     : rectangle W x H, hollowed with wall WALL (inner rectangle swept, then cut).
"""
import os, math
import FreeCAD as App
import Part
from FreeCAD import Vector as V

out = os.environ.get("CAM_ARM_OUT", os.path.expanduser("~"))
os.makedirs(out, exist_ok=True)

# --- inputs (mm) ---
PILLAR, PAD, PAD_T = 46.0, 60.0, 8.0   # plate 60 sits on the 46 mm pillar top (7 mm overhang): ledge 10 mm -> R8 fillet
HB = 12.5                         # M4 pattern half-pitch
HOLE_D, CSK_D = 4.5, 8.4
PLATE_W, PLATE_T = 50.0, 6.0
SLOT_W, SLOT_L, SLOT_Z = 6.6, 40.0, 70.0      # slot centre 70 mm above pillar top = 400 mm above bed
REACH_X = 149.0                   # pad centre -> bed centre in X
LENS_Y, LENS_OFFSET = 245.0, 50.0             # ASSUMED lens target Y; lens 50 mm beyond plate face
FACE_Y = LENS_Y - LENS_OFFSET                 # outer face of the end plate
END_Y = FACE_Y - PLATE_T                      # sweep ends at the inner face of the end plate
END_Z = 122.0                                 # sweep end centre: section bottom 102 = slot top (90) + 12 mm for bolt head / nut
W, H, WALL = 40.0, 40.0, 3.0                  # section 40x40: inner 34 clears the M4 heads at +/-12.5 (+4.2)
SPINE_A, SPINE_C, SPINE_K = 180.0, 150.0, -15.0   # cubic Bezier: P1 = start + a up (vertical start), P2 = end - c along Y (horizontal +Y arrival)
CLEAR_Z = 85.0                                # arm underside must stay above this over the gantry zone
FILLET_R = 8.0


def spine():
    """cubic Bezier: leaves the start pad vertically, arrives at the end pad moving +Y.
    Tuned numerically: underside >= 85 over the gantry zone, min radius of curvature ~60 mm,
    no overshoot beyond the end plate."""
    bc = Part.BezierCurve()
    bc.setPoles([V(0, 0, PAD_T), V(0, 0, PAD_T + SPINE_A),
                 V(REACH_X, END_Y - SPINE_C, END_Z + SPINE_K), V(REACH_X, END_Y, END_Z)])
    return bc


def section(w, h, centre, tangent):
    """rectangle: lateral side along machine X always, other side in the YZ arch plane, ~normal to the path"""
    lat = V(1, 0, 0)
    ty = V(0, tangent.y, tangent.z)
    ty.normalize()
    up = lat.cross(ty)                     # start (T=+Z): -Y ; end (T=+Y): +Z
    a, b = lat * (w / 2), up * (h / 2)
    p = [centre - a - b, centre + a - b, centre + a + b, centre - a + b]
    return Part.makePolygon(p + [p[0]])


def sweep(bs, w, h, n=16):
    """rectangle swept along the spline: n oriented sections, smooth loft (non-ruled)"""
    wires = []
    for i in range(n + 1):
        u = bs.FirstParameter + (bs.LastParameter - bs.FirstParameter) * i / n
        wires.append(section(w, h, bs.value(u), bs.tangent(u)[0]))
    return Part.makeLoft(wires, True, False, False)


bs = spine()
outer = sweep(bs, W, H)
inner = sweep(bs, W - 2 * WALL, H - 2 * WALL)

# end-section orientation check: slice the outer sweep just before the end plate
slab = Part.makeBox(400, 2.0, 400, V(-100, END_Y - 3.0, -100))
sl = outer.common(slab)
sb = sl.BoundBox
print("RESULT end section near y=%.0f: x extent %.1f (want ~%.0f), z extent %.1f (want ~%.0f), z centre %.1f" %
      (END_Y, sb.XLength, W, sb.ZLength, H, (sb.ZMin + sb.ZMax) / 2))

# clearance check along the spline (centre height minus half the section height, conservative)
n = 200
zmin_zone, worst = 1e9, None
Ltip = math.hypot(REACH_X, END_Y)
for i in range(n + 1):
    u = bs.FirstParameter + (bs.LastParameter - bs.FirstParameter) * i / n
    p = bs.value(u)
    r = math.hypot(p.x, p.y)
    if 30.0 < r < 0.65 * Ltip:
        under = p.z - H / 2
        if under < zmin_zone:
            zmin_zone, worst = under, p
print("RESULT underside over gantry zone (30 mm < plan radius < 65%% of reach): min %.1f mm at (%.0f,%.0f,%.0f), required >= %.0f"
      % (zmin_zone, worst.x, worst.y, worst.z + H / 2, CLEAR_Z))
apex = max(bs.value(bs.FirstParameter + (bs.LastParameter - bs.FirstParameter) * i / n).z for i in range(n + 1))
print("RESULT spline length %.0f mm, apex centre z %.0f (top z %.0f = %.0f mm above bed)" %
      (bs.length(), apex, apex + H / 2, 330 + apex + H / 2))

# start pad (plate) with countersinks, end pad (plate) with slot
plate = Part.makeBox(PAD, PAD, PAD_T, V(-PAD / 2, -PAD / 2, 0))
endpad = Part.makeBox(PLATE_W, PLATE_T, (END_Z + H / 2) - (SLOT_Z - 30.0),
                      V(REACH_X - PLATE_W / 2, END_Y, SLOT_Z - 30.0))
# root flare ("fillet"): lofted skirt whose half-width follows a quarter circle from the tower wall
# (z = PAD_T + R) down to the plate top. makeFillet() was measured to fail on this loft (4 attempts,
# even R=1); a lofted skirt needs no fillet operator.
K = 8
skirt_wires = []
for k in range(K + 1):
    phi = (math.pi / 2) * k / K                     # 0 = tangent to the wall, pi/2 = on the plate
    hw = W / 2 + FILLET_R * (1 - math.cos(phi))
    z = PAD_T + FILLET_R * (1 - math.sin(phi))
    skirt_wires.append(section(2 * hw, 2 * hw, V(0, 0, z), V(0, 0, 1)))
skirt = Part.makeLoft(skirt_wires, True, True, False)
body = plate.fuse(outer).fuse(skirt).fuse(endpad)
print("RESULT root flare: skirt R%.0f, half-width %.0f -> %.0f mm, plate half-width %.0f" %
      (FILLET_R, W / 2, W / 2 + FILLET_R, PAD / 2))
cav = inner
body = body.cut(cav)
for sx in (-1, 1):
    for sy in (-1, 1):
        c = V(sx * HB, sy * HB, 0)
        body = body.cut(Part.makeCylinder(HOLE_D / 2, PAD_T + 2, c + V(0, 0, -1), V(0, 0, 1)))
        body = body.cut(Part.makeCone(HOLE_D / 2, CSK_D / 2, CSK_D / 2 - HOLE_D / 2,
                                      c + V(0, 0, PAD_T - (CSK_D / 2 - HOLE_D / 2)), V(0, 0, 1)))
slot = Part.makeBox(SLOT_W, PLATE_T + 2, SLOT_L,
                    V(REACH_X - SLOT_W / 2, END_Y - 1, SLOT_Z - SLOT_L / 2))
body = body.cut(slot)
# hex-key doors in the two side (+-X) walls of the root tower: bolts are inside the hollow root
for sx in (-1, 1):   # side doors (shear webs): rear/front walls carry the root bending, keep them intact
    x0 = 14.0 if sx > 0 else -(14.0 + FILLET_R + 10.0)
    body = body.cut(Part.makeBox(FILLET_R + 10.0, 26.0, 32.0, V(x0, -13.0, PAD_T)))


bb = body.BoundBox
print("RESULT valid=%s solids=%d volume=%.1f cm3 (~%.0f g solid shell wall %.0f mm) bbox x[%.0f..%.0f] y[%.0f..%.0f] z[%.0f..%.0f]" %
      (body.isValid(), len(body.Solids), body.Volume / 1000, body.Volume * 1.07e-3, WALL,
       bb.XMin, bb.XMax, bb.YMin, bb.YMax, bb.ZMin, bb.ZMax))

doc = App.newDocument("camera_arm")
obj = doc.addObject("Part::Feature", "camera_arm")
obj.Shape = body
doc.recompute()
doc.saveAs(os.path.join(out, "camera_arm_shell.FCStd"))
Part.export([obj], os.path.join(out, "camera_arm_shell.step"))
print("RESULT saved", os.path.join(out, "camera_arm_shell.FCStd"))
