"""Camera arm: tapered arched space truss. Builds TWO solids from arm_topology.py:
    camera_arm_uniform8.FCStd  every member 8 mm
    camera_arm_sized.FCStd     member diameters from sizing.json (size_members.py)

Run (headless FreeCAD, on the workstation, cwd = this folder):
    CAM_ARM_OUT=/path/out freecad.cmd camera_arm.py

Fuse notes (measured, FreeCAD 27.1.0dev): multiFuse(), removeSplitter() and fuse(list, tol) each
gave invalid or EMPTY shapes on this geometry; pairwise sequential fuse works. Node spheres must
STRICTLY contain the incident rod ends (r + 0.75 mm): equal radius = tangent seams = sliver faces
-> invalid fuse and inverted FEM tets.
"""
import os, sys, json
sys.path.insert(0, os.getcwd())
import FreeCAD as App
import Part
from FreeCAD import Vector as V
import arm_topology as T

out = os.environ.get("CAM_ARM_OUT", os.path.expanduser("~"))
os.makedirs(out, exist_ok=True)
nodes, members, base, tip = T.build()
P = [V(*p) for p in nodes]
SPHERE_MARGIN = 0.75


def build_solid(dia):
    parts = [Part.makeBox(T.PAD, T.PAD, T.PAD_T, V(-T.PAD / 2, -T.PAD / 2, 0))]
    node_r = [0.0] * len(nodes)
    for (a, b, _), d in zip(members, dia):
        v = P[b] - P[a]
        parts.append(Part.makeCylinder(d / 2, v.Length, P[a], v))
        node_r[a] = max(node_r[a], d / 2)
        node_r[b] = max(node_r[b], d / 2)
    for p, r in zip(P, node_r):
        if r > 0:
            parts.append(Part.makeSphere(r + SPHERE_MARGIN, p))
    tipP = V(T.REACH_X, T.REACH_Y, 0)
    plate = Part.makeBox(T.PLATE_W, T.PLATE_T, T.z_top(1.0) - T.PLATE_Z0,
                         V(-T.PLATE_W / 2, -T.PLATE_T / 2, T.PLATE_Z0))
    plate.translate(tipP)          # normal along machine Y: bolt axis Y, camera axes parallel to X/Y
    parts.append(plate)

    body = parts[0]
    for p_ in parts[1:]:
        body = body.fuse(p_)
    v_in = sum(q.Volume for q in parts)
    h = T.H
    for sx in (-1, 1):
        for sy in (-1, 1):
            body = body.cut(Part.makeCylinder(T.HOLE_D / 2, T.PAD_T + 2, V(sx * h, sy * h, -1), V(0, 0, 1)))
    slot = Part.makeBox(T.SLOT_W, T.PLATE_T + 2, T.SLOT_L,
                        V(-T.SLOT_W / 2, -T.PLATE_T / 2 - 1, T.SLOT_Z - T.SLOT_L / 2))
    slot.translate(tipP)
    body = body.cut(slot)
    return body, v_in


def save(name, dia):
    body, v_in = build_solid(dia)
    # the summed input volume double-counts joint overlaps, so only a gross-loss guard is possible
    ok = body.isValid() and len(body.Solids) == 1 and body.Volume > 0.4 * v_in
    bb = body.BoundBox
    print("RESULT %-8s valid=%s solids=%d vol=%.1f cm3 (inputs summed %.1f) bbox y[%.0f..%.0f] z[%.0f..%.0f] %s" %
          (name, body.isValid(), len(body.Solids), body.Volume / 1000, v_in / 1000,
           bb.YMin, bb.YMax, bb.ZMin, bb.ZMax, "OK" if ok else "SUSPECT"))
    doc = App.newDocument("camera_arm")
    obj = doc.addObject("Part::Feature", "camera_arm")
    obj.Shape = body
    doc.recompute()
    doc.saveAs(os.path.join(out, "camera_arm_%s.FCStd" % name))
    if ok:
        Part.export([obj], os.path.join(out, "camera_arm_%s.step" % name))
    App.closeDocument(doc.Name)


save("uniform8", [8.0] * len(members))
if os.path.exists("sizing.json"):
    dia = json.load(open("sizing.json"))["diameters"]
    assert len(dia) == len(members), "sizing.json does not match topology: rerun size_members.py"
    save("sized", dia)
