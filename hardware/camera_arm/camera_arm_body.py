"""Camera arm as a PARAMETRIC PartDesign Body (FreeCAD 27.1 dev), editable feature by feature.

Run headless:  CAM_ARM_OUT=/path/out freecad.cmd camera_arm_body.py   -> camera_arm_body.FCStd

Frame: origin = centre of the pillar top, z=0 = pillar top (330 mm above the bed), +X toward the
bed centre, +Y toward the bed, +Z up. Everything the user may want to change is a NAMED constraint
or property: sketch constraints (PlateWidth, BoltPitch, ArmWidth ...), the Draft Bezier "Spine"
(drag its control points), Pad/Pocket lengths.

PARAMETERS (Fusion "fx" equivalent): the VarSet "Params" holds every driving value as a named
property (Params.PlateWidth, Params.ArmWidth, Params.SpineA ...; edit them in the Property panel). All sketch dimensions, feature lengths,
sketch placements and the Bezier control points are bound to it by expressions: edit a value in
Params and the whole tree recomputes. Derived values (EndPlateH, InnerW, GussetX ...) are formulas.
The SPLINE ("Spine", a Draft Bezier) is edited directly: change its Points in the Property panel or
use Draft > Edit. Its END point (Points[6]) drives ReachX / EndY / EndZ, hence the camera plate, slot and
gussets. The last 49 mm of the Spine are a straight run (Points[3..6]) so the plate and gussets sit on it.
If you change PlateT, also set Spine Points[0].z to the same value (spline expressions on
control points are not supported by this FreeCAD build).

Tree:  Sk_Plate -> Pad_Plate -> Sk_Bolts -> Hole_M4_CSK -> Sk_Profile -> Pipe_Arm (rectangle swept
along Spine, binormal = X) -> Sk_FootTop/Sk_FootBase -> Loft_Foot -> Sk_Inner -> Cut_Cavity ->
Sk_EndPlate -> Pad_EndPlate -> Sk_Slot -> Pocket_Slot -> Sk_Gusset -> Pad_Gusset -> Mirror_Gusset
-> Sk_Door -> Pocket_Doors
"""
import os
import FreeCAD as App
import Part, Sketcher
import Draft
from FreeCAD import Vector as V

out = os.environ.get("CAM_ARM_OUT", os.path.expanduser("~"))
os.makedirs(out, exist_ok=True)

# ----- design values (mm); also exposed as named sketch constraints below -----
PLATE_W, PLATE_T = 60.0, 8.0          # plate on the 46 mm pillar top
BOLT_PITCH, HOLE_D, CSK_D = 25.0, 4.5, 8.4
ARM_W, ARM_H, WALL = 40.0, 40.0, 3.0
FOOT_R = 8.0                          # root flare (chamfer-like loft)
REACH_X, END_Y, END_Z = 149.0, 189.0, 122.0
SPINE_A, SPINE_C = 180.0, 110.0       # lead-out height / lead-in length of the first Bezier segment
TAIL = 49.0                        # straight final run at x = REACH_X, z = END_Z (gussets/plate sit on it)
PLATE_END_W, PLATE_END_T = 50.0, 6.0
SLOT_Z, SLOT_W, SLOT_L = 70.0, 6.6, 40.0
PLATE_END_Z0 = SLOT_Z - 30.0
GUSSET_W, GUSSET_TOP, GUSSET_BACK = WALL, END_Z, 45.0   # 3 mm web, coplanar with the arm side wall
DOOR_Y, DOOR_Z0, DOOR_Z1 = 26.0, PLATE_T, 38.0

doc = App.newDocument("CameraArm")
body = doc.addObject("PartDesign::Body", "Body")
body.Label = "CameraArm"
ORIGIN = {o.Role: o for o in body.Origin.OriginFeatures}

# spine: Draft Bezier (edit its Points / drag it with Draft Edit); vertical start, +Y arrival.
# The camera plate, slot and gussets read their position from its END point (Points[6]).--
_ty = END_Y - TAIL
spine = Draft.make_bezcurve([
    V(0, 0, PLATE_T), V(0, 0, PLATE_T + SPINE_A), V(REACH_X, _ty - SPINE_C, END_Z), V(REACH_X, _ty, END_Z),
    V(REACH_X, _ty + TAIL / 3, END_Z), V(REACH_X, _ty + 2 * TAIL / 3, END_Z), V(REACH_X, END_Y, END_Z)],
    closed=False, degree=3)
spine.Label = "Spine"
doc.recompute()
print("TREE spine edges=%d length=%.0f" % (len(spine.Shape.Edges), spine.Shape.Length))


# ----- Params spreadsheet ---------------------------------------------------------------------------
_PARAMS = [   # name, value, unit, note
    ("PlateWidth", PLATE_W, "mm", "start plate width (X)"),
    ("PlateDepth", PLATE_W, "mm", "start plate depth (Y)"),
    ("PlateT", PLATE_T, "mm", "start plate thickness"),
    ("BoltPitch", BOLT_PITCH, "mm", "M4 pattern, square, on the Z pillar top"),
    ("HoleD", HOLE_D, "mm", "M4 clearance hole"),
    ("CskD", CSK_D, "mm", "countersink diameter at the plate top"),
    ("CskAngle", 90.0, "deg", "countersink included angle"),
    ("ArmWidth", ARM_W, "mm", "swept rectangle, lateral side (X)"),
    ("ArmDepth", ARM_H, "mm", "swept rectangle, side in the arch plane"),
    ("Wall", WALL, "mm", "shell wall"),
    ("FootR", FOOT_R, "mm", "root flare size"),
    ("EndPlateW", PLATE_END_W, "mm", "camera plate width (X)"),
    ("EndPlateT", PLATE_END_T, "mm", "camera plate thickness (Y)"),
    ("SlotZ", SLOT_Z, "mm", "slot centre above the pillar top (70 = 400 mm above the bed)"),
    ("SlotW", SLOT_W, "mm", "1/4 inch slot width"),
    ("SlotL", SLOT_L, "mm", "slot length (+/-20 mm focus travel)"),
    ("PlateBelowSlot", 30.0, "mm", "camera plate extends this far below the slot centre"),
    ("GussetBack", GUSSET_BACK, "mm", "gusset length back along Y"),
    ("DoorWidth", DOOR_Y, "mm", "hex-key door width (Y)"),
    ("DoorTopZ", DOOR_Z1, "mm", "hex-key door top height"),
]
_DERIVED = [  # name, formula, note
    ("ReachX", "=<<Spine>>.Points[6].x * 1 mm", "camera plate centre X = END of the Spine, Points[6] (edit the Spine, not this)"),
    ("EndY", "=<<Spine>>.Points[6].y * 1 mm", "inner face of the camera plate Y = END of the Spine"),
    ("EndZ", "=<<Spine>>.Points[6].z * 1 mm", "arm end centre height = END of the Spine"),
    ("GussetW", "=Wall", "gusset thickness = shell wall (coplanar with the arm side walls)"),
    ("GussetTop", "=EndZ", "gusset top height (inside the arm's end section)"),
    ("EndPlateZ0", "=SlotZ - PlateBelowSlot", "camera plate bottom"),
    ("EndPlateTopZ", "=EndZ + ArmDepth / 2", "camera plate top = arm section top"),
    ("EndPlateH", "=EndPlateTopZ - EndPlateZ0", "camera plate height"),
    ("InnerW", "=ArmWidth - 2 * Wall", "cavity width"),
    ("InnerD", "=ArmDepth - 2 * Wall", "cavity depth"),
    ("FootBaseW", "=ArmWidth + 2 * FootR", "flare base width"),
    ("FootBaseD", "=ArmDepth + 2 * FootR", "flare base depth"),
    ("FootTopZ", "=PlateT + FootR", "flare top height"),
    ("GussetX", "=ReachX - ArmWidth / 2", "left gusset X: outer face coplanar with the arm side wall (mirrored about ReachX)"),
    ("DoorH", "=DoorTopZ - PlateT", "hex-key door height"),
]
# VarSet = real persistent properties (survive save/reload with live expression links, unlike spreadsheet aliases)
sheet = doc.addObject("App::VarSet", "Params")
sheet.Label = "Params"
for _n, _v, _u, _note in _PARAMS:
    _typ = "App::PropertyAngle" if _u == "deg" else "App::PropertyLength"
    sheet.addProperty(_typ, _n, "Driving", _note)
    setattr(sheet, _n, App.Units.Quantity("%g %s" % (_v, _u)))
for _n, _f, _note in _DERIVED:
    sheet.addProperty("App::PropertyLength", _n, "Derived", _note)
    sheet.setExpression(_n, _f.lstrip("="))
doc.recompute()


def vol():
    return body.Shape.Volume / 1000.0


def check(tag):
    doc.recompute()
    sh = body.Shape
    print("TREE %-16s valid=%s solids=%d vol=%.1f cm3 bbox x[%.0f..%.0f] y[%.0f..%.0f] z[%.0f..%.0f]" %
          (tag, sh.isValid(), len(sh.Solids), sh.Volume / 1000.0, sh.BoundBox.XMin, sh.BoundBox.XMax,
           sh.BoundBox.YMin, sh.BoundBox.YMax, sh.BoundBox.ZMin, sh.BoundBox.ZMax))


def sketch(name, plane, offset=0.0):
    """plane 'XY'|'XZ'|'YZ'; offset along the sketch normal (XZ normal = -Y, YZ normal = +X)"""
    sk = body.newObject("Sketcher::SketchObject", name)
    sk.AttachmentSupport = [(ORIGIN[plane + "_Plane"], "")]
    sk.MapMode = "FlatFace"
    sk.AttachmentOffset = App.Placement(V(0, 0, offset), App.Rotation())
    return sk


def rect(sk, w, h, wname, hname, cx=0.0, cy=0.0, centred=True, xname=None, yname=None):
    x0, y0 = cx - w / 2, cy - h / 2
    pts = [V(x0, y0, 0), V(x0 + w, y0, 0), V(x0 + w, y0 + h, 0), V(x0, y0 + h, 0)]
    ids = [sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False) for i in range(4)]
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", ids[i], 2, ids[(i + 1) % 4], 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", ids[0]))
    sk.addConstraint(Sketcher.Constraint("Horizontal", ids[2]))
    sk.addConstraint(Sketcher.Constraint("Vertical", ids[1]))
    sk.addConstraint(Sketcher.Constraint("Vertical", ids[3]))
    c = sk.addConstraint(Sketcher.Constraint("DistanceX", ids[0], 1, ids[0], 2, w)); sk.renameConstraint(c, wname)
    c = sk.addConstraint(Sketcher.Constraint("DistanceY", ids[1], 1, ids[1], 2, h)); sk.renameConstraint(c, hname)
    if centred and cx == 0.0 and cy == 0.0:
        sk.addConstraint(Sketcher.Constraint("Symmetric", ids[0], 1, ids[2], 1, -1, 1))
    else:
        c = sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, ids[0], 1, x0)); sk.renameConstraint(c, xname or (wname + "_X0"))
        c = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, ids[0], 1, y0)); sk.renameConstraint(c, yname or (hname + "_Y0"))
    return ids


def set_enum(obj, prop, value):
    try:
        setattr(obj, prop, value)
    except Exception:
        print("TREE enum %s.%s=%r not accepted; options: %s" % (obj.Name, prop, value, obj.getEnumerationsOfProperty(prop)))
        raise


# 1. plate ---------------------------------------------------------------------------------------
sk = sketch("Sk_Plate", "XY")
rect(sk, PLATE_W, PLATE_W, "PlateWidth", "PlateDepth")
pad = body.newObject("PartDesign::Pad", "Pad_Plate")
pad.Profile = sk
pad.Length = PLATE_T
check("Pad_Plate")

# 2. M4 countersunk holes (Hole feature, 90 deg countersink) -------------------------------------
sk = sketch("Sk_Bolts", "XY", PLATE_T)
h = BOLT_PITCH / 2
pids = [sk.addGeometry(Part.Point(V(sx * h, sy * h, 0)), False) for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
sk.addConstraint(Sketcher.Constraint("Horizontal", pids[0], 1, pids[1], 1))
sk.addConstraint(Sketcher.Constraint("Horizontal", pids[3], 1, pids[2], 1))
sk.addConstraint(Sketcher.Constraint("Vertical", pids[0], 1, pids[3], 1))
sk.addConstraint(Sketcher.Constraint("Vertical", pids[1], 1, pids[2], 1))
c = sk.addConstraint(Sketcher.Constraint("DistanceX", pids[0], 1, pids[1], 1, BOLT_PITCH)); sk.renameConstraint(c, "BoltPitchX")
c = sk.addConstraint(Sketcher.Constraint("DistanceY", pids[0], 1, pids[3], 1, BOLT_PITCH)); sk.renameConstraint(c, "BoltPitchY")
sk.addConstraint(Sketcher.Constraint("Symmetric", pids[0], 1, pids[2], 1, -1, 1))
hole = body.newObject("PartDesign::Hole", "Hole_M4_CSK")
hole.Profile = sk
hole.Threaded = False
hole.Diameter = HOLE_D
set_enum(hole, "DepthType", "ThroughAll")
set_enum(hole, "HoleCutType", "Countersink")
hole.HoleCutDiameter = CSK_D
hole.HoleCutCountersinkAngle = 90.0
check("Hole_M4_CSK")

# 4. arm: rectangle swept along the spine (binormal fixed = X so the rectangle keeps its X side) ----
sk = sketch("Sk_Profile", "XY", PLATE_T)
rect(sk, ARM_W, ARM_H, "ArmWidth", "ArmDepth")
pipe = body.newObject("PartDesign::AdditivePipe", "Pipe_Arm")
pipe.Profile = sk
pipe.Spine = (spine, ["Edge%d" % (i + 1) for i in range(len(spine.Shape.Edges))])
set_enum(pipe, "Mode", "Binormal")
pipe.Binormal = V(1, 0, 0)
check("Pipe_Arm")

# 5. root flare: loft from a wide rectangle on the plate to the arm section R above (chamfer-like) --
sk_b = sketch("Sk_FootBase", "XY", PLATE_T)
rect(sk_b, ARM_W + 2 * FOOT_R, ARM_H + 2 * FOOT_R, "FootBaseW", "FootBaseD")
sk_t = sketch("Sk_FootTop", "XY", PLATE_T + FOOT_R)
rect(sk_t, ARM_W, ARM_H, "FootTopW", "FootTopD")
loft = body.newObject("PartDesign::AdditiveLoft", "Loft_Foot")
loft.Profile = sk_b
loft.Sections = [sk_t]
loft.Ruled = True
check("Loft_Foot")

# 6. cavity: inner rectangle swept along the same spine, subtracted ------------------------------
sk = sketch("Sk_Inner", "XY", PLATE_T)
rect(sk, ARM_W - 2 * WALL, ARM_H - 2 * WALL, "InnerWidth", "InnerDepth")
cav = body.newObject("PartDesign::SubtractivePipe", "Cut_Cavity")
cav.Profile = sk
cav.Spine = (spine, ["Edge%d" % (i + 1) for i in range(len(spine.Shape.Edges))])
set_enum(cav, "Mode", "Binormal")
cav.Binormal = V(1, 0, 0)
check("Cut_Cavity")

# 7. camera end plate: XZ plane sketch at y = END_Y, pad toward +Y -------------------------------
z_top = END_Z + ARM_H / 2
sk = sketch("Sk_EndPlate", "XZ", -END_Y)         # XZ normal = -Y, so offset -END_Y puts it at y = END_Y
rect(sk, PLATE_END_W, z_top - PLATE_END_Z0, "EndPlateW", "EndPlateH", cx=REACH_X, cy=(z_top + PLATE_END_Z0) / 2,
     centred=False, xname="EndPlateX0", yname="EndPlateZ0")
pad2 = body.newObject("PartDesign::Pad", "Pad_EndPlate")
pad2.Profile = sk
pad2.Length = PLATE_END_T
pad2.Reversed = True                              # toward +Y
doc.recompute()
if pad2.Shape.BoundBox.YMax < END_Y + PLATE_END_T - 0.5:
    pad2.Reversed = False
check("Pad_EndPlate")

# 8. 1/4" slot (vertical, +/-20 mm) ---------------------------------------------------------------
sk = sketch("Sk_Slot", "XZ", -END_Y)
rect(sk, SLOT_W, SLOT_L, "SlotWidth", "SlotLength", cx=REACH_X, cy=SLOT_Z, centred=False,
     xname="SlotX0", yname="SlotZ0")
pk = body.newObject("PartDesign::Pocket", "Pocket_Slot")
pk.Profile = sk
pk.Length = PLATE_END_T + 1.0
before = vol()
doc.recompute()
if vol() >= before - 1e-6:
    pk.Reversed = True
check("Pocket_Slot")

# 9. gussets: triangle on a YZ-plane sketch at x = REACH_X - PLATE_END_W/2, 7 mm thick, mirrored ----
gx = REACH_X - ARM_W / 2        # outer face coplanar with the arm side wall
sk = sketch("Sk_Gusset", "YZ", gx)
g = [sk.addGeometry(Part.LineSegment(a, b), False) for a, b in (
    (V(END_Y, PLATE_END_Z0, 0), V(END_Y, GUSSET_TOP, 0)),
    (V(END_Y, GUSSET_TOP, 0), V(END_Y - GUSSET_BACK, GUSSET_TOP, 0)),
    (V(END_Y - GUSSET_BACK, GUSSET_TOP, 0), V(END_Y, PLATE_END_Z0, 0)))]
for i in range(3):
    sk.addConstraint(Sketcher.Constraint("Coincident", g[i], 2, g[(i + 1) % 3], 1))
sk.addConstraint(Sketcher.Constraint("Vertical", g[0]))
sk.addConstraint(Sketcher.Constraint("Horizontal", g[1]))
c = sk.addConstraint(Sketcher.Constraint("DistanceY", g[0], 1, g[0], 2, GUSSET_TOP - PLATE_END_Z0)); sk.renameConstraint(c, "GussetHeight")
c = sk.addConstraint(Sketcher.Constraint("DistanceX", g[1], 2, g[1], 1, GUSSET_BACK)); sk.renameConstraint(c, "GussetLength")
c = sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, g[0], 1, END_Y)); sk.renameConstraint(c, "GussetY")
c = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, g[0], 1, PLATE_END_Z0)); sk.renameConstraint(c, "GussetZ0")
gp = body.newObject("PartDesign::Pad", "Pad_Gusset")
gp.Profile = sk
gp.Length = GUSSET_W
doc.recompute()
if gp.Shape.BoundBox.XMax < gx + GUSSET_W - 0.5:
    gp.Reversed = True
check("Pad_Gusset")
datum = body.newObject("PartDesign::Plane", "MidPlane_X")
datum.AttachmentSupport = [(ORIGIN["YZ_Plane"], "")]
datum.MapMode = "FlatFace"
datum.AttachmentOffset = App.Placement(V(0, 0, REACH_X), App.Rotation())
mir = body.newObject("PartDesign::Mirrored", "Mirror_Gusset")
mir.Originals = [gp]
mir.MirrorPlane = (datum, [""])
body.Tip = mir
check("Mirror_Gusset")

# 10. side doors for the hex key (shear webs; front/rear walls stay) --------------------------------
sk = sketch("Sk_Door", "YZ", 0.0)
rect(sk, DOOR_Y, DOOR_Z1 - DOOR_Z0, "DoorWidth", "DoorHeight", cx=0.0, cy=(DOOR_Z0 + DOOR_Z1) / 2, centred=False,
     xname="DoorY0", yname="DoorZ0")
dr = body.newObject("PartDesign::Pocket", "Pocket_Doors")
dr.Profile = sk
set_enum(dr, "Type", "ThroughAll")
dr.Midplane = True
check("Pocket_Doors")

# ----- bind everything to Params -----------------------------------------------------------------------
BINDS = [
    ("Sk_Plate", "Constraints.PlateWidth", "Params.PlateWidth"),
    ("Sk_Plate", "Constraints.PlateDepth", "Params.PlateDepth"),
    ("Pad_Plate", "Length", "Params.PlateT"),
    ("Sk_Bolts", "AttachmentOffset.Base.z", "Params.PlateT"),
    ("Sk_Bolts", "Constraints.BoltPitchX", "Params.BoltPitch"),
    ("Sk_Bolts", "Constraints.BoltPitchY", "Params.BoltPitch"),
    ("Hole_M4_CSK", "Diameter", "Params.HoleD"),
    ("Hole_M4_CSK", "HoleCutDiameter", "Params.CskD"),
    ("Hole_M4_CSK", "HoleCutCountersinkAngle", "Params.CskAngle"),
    ("Sk_Profile", "AttachmentOffset.Base.z", "Params.PlateT"),
    ("Sk_Profile", "Constraints.ArmWidth", "Params.ArmWidth"),
    ("Sk_Profile", "Constraints.ArmDepth", "Params.ArmDepth"),
    ("Sk_FootBase", "AttachmentOffset.Base.z", "Params.PlateT"),
    ("Sk_FootBase", "Constraints.FootBaseW", "Params.FootBaseW"),
    ("Sk_FootBase", "Constraints.FootBaseD", "Params.FootBaseD"),
    ("Sk_FootTop", "AttachmentOffset.Base.z", "Params.FootTopZ"),
    ("Sk_FootTop", "Constraints.FootTopW", "Params.ArmWidth"),
    ("Sk_FootTop", "Constraints.FootTopD", "Params.ArmDepth"),
    ("Sk_Inner", "AttachmentOffset.Base.z", "Params.PlateT"),
    ("Sk_Inner", "Constraints.InnerWidth", "Params.InnerW"),
    ("Sk_Inner", "Constraints.InnerDepth", "Params.InnerD"),
    ("Sk_EndPlate", "AttachmentOffset.Base.z", "-Params.EndY"),
    ("Sk_EndPlate", "Constraints.EndPlateW", "Params.EndPlateW"),
    ("Sk_EndPlate", "Constraints.EndPlateH", "Params.EndPlateH"),
    ("Sk_EndPlate", "Constraints.EndPlateX0", "Params.ReachX - Params.EndPlateW / 2"),
    ("Sk_EndPlate", "Constraints.EndPlateZ0", "Params.EndPlateZ0"),
    ("Pad_EndPlate", "Length", "Params.EndPlateT"),
    ("Sk_Slot", "AttachmentOffset.Base.z", "-Params.EndY"),
    ("Sk_Slot", "Constraints.SlotWidth", "Params.SlotW"),
    ("Sk_Slot", "Constraints.SlotLength", "Params.SlotL"),
    ("Sk_Slot", "Constraints.SlotX0", "Params.ReachX - Params.SlotW / 2"),
    ("Sk_Slot", "Constraints.SlotZ0", "Params.SlotZ - Params.SlotL / 2"),
    ("Pocket_Slot", "Length", "Params.EndPlateT + 1 mm"),
    ("Sk_Gusset", "AttachmentOffset.Base.z", "Params.GussetX"),
    ("Sk_Gusset", "Constraints.GussetHeight", "Params.GussetTop - Params.EndPlateZ0"),
    ("Sk_Gusset", "Constraints.GussetLength", "Params.GussetBack"),
    ("Sk_Gusset", "Constraints.GussetY", "Params.EndY"),
    ("Sk_Gusset", "Constraints.GussetZ0", "Params.EndPlateZ0"),
    ("Pad_Gusset", "Length", "Params.GussetW"),
    ("MidPlane_X", "AttachmentOffset.Base.z", "Params.ReachX"),
    ("Sk_Door", "Constraints.DoorWidth", "Params.DoorWidth"),
    ("Sk_Door", "Constraints.DoorHeight", "Params.DoorH"),
    ("Sk_Door", "Constraints.DoorY0", "-Params.DoorWidth / 2"),
    ("Sk_Door", "Constraints.DoorZ0", "Params.PlateT"),
]
bound = 0
for oname, path, expr in BINDS:
    o = doc.getObject(oname) or (doc.getObjectsByLabel(oname) or [None])[0]   # Spine: internal name is BezCurve
    try:
        o.setExpression(path, expr)
        bound += 1
    except Exception as ex:
        print("TREE bind FAILED %s.%s = %s : %s" % (oname, path, expr, str(ex)[:80]))
print("TREE bound %d/%d expressions to Params" % (bound, len(BINDS)))
v_before = body.Shape.Volume
doc.recompute()
bad = [o.Name for o in doc.Objects if "Invalid" in o.State]
print("TREE after binding: volume %.1f cm3 (was %.1f), invalid objects: %s" % (body.Shape.Volume / 1000, v_before / 1000, bad))

if os.environ.get("TEST_PROP"):
    pad_ = doc.getObject("Pad_Plate")
    sheet.PlateT = App.Units.Quantity("10 mm"); doc.recompute()
    print("TREE PROPTEST in-session after PlateT=10: Pad.Length=%s vol=%.1f" % (pad_.Length, body.Shape.Volume / 1000))
    sheet.PlateT = App.Units.Quantity("8 mm"); doc.recompute()
    print("TREE PROPTEST restored: Pad.Length=%s vol=%.1f" % (pad_.Length, body.Shape.Volume / 1000))
    print("TREE PROPTEST OutList of Pad_Plate:", [o.Name for o in pad_.OutList], "InList of Params:", [o.Name for o in sheet.InList][:6])

body.Tip = dr
doc.recompute()
sh = body.Shape
print("TREE RESULT valid=%s solids=%d vol=%.1f cm3 (~%.0f g) tip=%s features=%d" %
      (sh.isValid(), len(sh.Solids), sh.Volume / 1000, sh.Volume * 1.07e-3, body.Tip.Name,
       len([o for o in body.Group if o.isDerivedFrom("PartDesign::Feature")])))
doc.saveAs(os.path.join(out, "camera_arm_body.FCStd"))
print("TREE saved", os.path.join(out, "camera_arm_body.FCStd"))
