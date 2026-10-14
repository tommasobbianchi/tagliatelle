"""Solid FEM sub-model of the root block (plate + pedestal + countersinks + access holes).
    CAM_ARM_OUT=/path/fem_root freecad.cmd fem_root.py   (cwd = this folder, needs root_loads.json)

Loads: member end forces AND moments from the frame model (size_members.py -> root_loads.json),
applied through rigid-body couplings on a small disc at each strut base. Support: the 4
countersink cone faces fixed (conservative). Material ASA-GF E 5000 MPa, nu 0.35; allowable 4 MPa.
Two variants: R=0.5 (sharp junction) and R=FILLET_R, same loads, same mesh settings.
"""
import os, sys, json, math
sys.path.insert(0, os.getcwd())
import FreeCAD as App
import Part, ObjectsFem
from FreeCAD import Vector as V
import arm_topology as T
from femmesh.gmshtools import GmshTools
from femtools import ccxtools

out = os.environ["CAM_ARM_OUT"]
os.makedirs(out, exist_ok=True)
loads = json.load(open("root_loads.json"))
CASES = ["acc+n", "acc-n", "acc+z", "acc-z"]
Z0 = T.PAD_T
HB = T.HOLE_PITCH / 2


def block(R):
    pad = Part.makeBox(T.PAD, T.PAD, T.PAD_T, V(-T.PAD / 2, -T.PAD / 2, 0))
    ped = Part.makeBox(T.PED_W, T.PED_W, T.PED_H, V(-T.PED_W / 2, -T.PED_W / 2, Z0))
    vert = [e for e in ped.Edges if abs(e.Vertexes[0].Z - e.Vertexes[1].Z) > 1.0]
    ped = ped.makeFillet(3.0, vert)
    body = pad.fuse(ped)
    junction = [e for e in body.Edges
                if all(abs(v.Z - Z0) < 1e-6 for v in e.Vertexes)
                and all(max(abs(v.X), abs(v.Y)) < T.PED_W / 2 + 1e-3 for v in e.Vertexes)]
    body = body.makeFillet(R, junction)
    top = Z0 + T.PED_H
    for sx in (-1, 1):
        for sy in (-1, 1):
            c = V(sx * HB, sy * HB, 0)
            body = body.cut(Part.makeCylinder(T.HOLE_D / 2, Z0 + 2, c + V(0, 0, -1), V(0, 0, 1)))
            body = body.cut(Part.makeCone(T.HOLE_D / 2, T.CSK_D / 2, T.CSK_D / 2 - T.HOLE_D / 2,
                                          c + V(0, 0, Z0 - (T.CSK_D / 2 - T.HOLE_D / 2)), V(0, 0, 1)))
            body = body.cut(Part.makeCylinder(T.ACCESS_D / 2, top - Z0 + 1, c + V(0, 0, Z0), V(0, 0, 1)))
    return body


def run_variant(R, tag):
    body = block(R)
    print("ROOT %s block valid=%s solids=%d vol=%.1f cm3" % (tag, body.isValid(), len(body.Solids), body.Volume / 1000))
    base_pos = {}
    for k, n in loads["acc+n"].items():
        base_pos[k] = V(*n["pos"])
    for k, p in base_pos.items():
        body = body.fuse(Part.makeCylinder(6.0, 1.0, p, V(0, 0, 1)))
    doc = App.newDocument("root_%s" % tag)
    obj = doc.addObject("Part::Feature", "root_block")
    obj.Shape = body
    doc.recompute()
    sh = obj.Shape

    csk, disc_top = [], {}
    for i, f in enumerate(sh.Faces, 1):
        cn = f.CenterOfMass
        if f.Surface.__class__.__name__ == "Cone":
            csk.append("Face%d" % i)
        if f.Surface.__class__.__name__ == "Plane" and abs(cn.z - (T.Z_BASE + 1.0)) < 1e-6:
            for k, p in base_pos.items():
                if abs(cn.x - p.x) < 1.0 and abs(cn.y - p.y) < 1.0:
                    disc_top[k] = "Face%d" % i
    print("ROOT %s countersink faces %d, disc faces %s" % (tag, len(csk), disc_top))
    assert len(csk) >= 4 and len(disc_top) == len(base_pos)

    analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
    solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver")
    solver.AnalysisType = "static"
    solver.GeometricalNonlinearity = False
    solver.WorkingDir = out
    analysis.addObject(solver)
    mat = ObjectsFem.makeMaterialSolid(doc, "ASA_GF")
    mat.Material = {"Name": "ASA-GF", "YoungsModulus": "5000 MPa", "PoissonRatio": "0.35", "Density": "1070 kg/m^3"}
    analysis.addObject(mat)
    fixed = ObjectsFem.makeConstraintFixed(doc, "Bolts")
    fixed.References = [(obj, f) for f in csk]
    analysis.addObject(fixed)
    rbs = {}
    for k, face in disc_top.items():
        rb = ObjectsFem.makeConstraintRigidBody(doc, "RB_%s" % k)
        rb.References = [(obj, face)]
        rb.ReferenceNode = base_pos[k] + V(0, 0, 1.0)
        for ax in "XYZ":
            setattr(rb, "TranslationalMode" + ax, "Load")
            setattr(rb, "RotationalMode" + ax, "Load")
        analysis.addObject(rb)
        rbs[k] = rb
    mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
    mesh.Shape = obj
    mesh.CharacteristicLengthMax = "2 mm"
    mesh.CharacteristicLengthMin = "0.5 mm"
    mesh.ElementOrder = "2nd"
    try:
        mesh.HighOrderOptimize = "Elastic+Optimization"
    except Exception:
        pass
    analysis.addObject(mesh)
    doc.recompute()
    err = GmshTools(mesh).create_mesh()
    print("ROOT %s mesh err=%r nodes=%d tets=%d" % (tag, err, mesh.FemMesh.NodeCount, mesh.FemMesh.VolumeCount))
    doc.recompute()

    for case in CASES:
        for k, rb in rbs.items():
            f, m = loads[case][k]["F"], loads[case][k]["M"]
            for ax, val in zip("XYZ", f):
                setattr(rb, "Force" + ax, App.Units.Quantity("%.4f N" % val))
            for ax, val in zip("XYZ", m):
                setattr(rb, "Moment" + ax, App.Units.Quantity("%.3f N*mm" % val))
        doc.recompute()
        fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=False)
        fea.update_objects(); fea.setup_working_dir(); fea.setup_ccx()
        msg = fea.check_prerequisites()
        if msg:
            print("ROOT prerequisites:", msg)
        fea.purge_results(); fea.write_inp_file(); fea.ccx_run(); fea.load_results()
        res = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")][-1]
        vm = list(res.vonMises)
        if not vm:
            print("ROOT %s %-6s FAILED: no results" % (tag, case))
            continue
        ids = list(res.NodeNumbers)
        nodes = (res.Mesh or mesh).FemMesh.Nodes
        band = []
        for i, nid in enumerate(ids):
            p = nodes[nid]
            on_block = p.z <= Z0 + R + 0.3 and p.z >= Z0 - 0.3 and max(abs(p.x), abs(p.y)) >= T.PED_W / 2 - 0.05
            if on_block:
                band.append((vm[i], p))
        gmax = max(range(len(vm)), key=lambda i: vm[i])
        bmax = max(band, key=lambda t: t[0]) if band else (float("nan"), V(0, 0, 0))
        gp = nodes[ids[gmax]]
        print("ROOT %s %-6s global max %.2f MPa at (%.0f,%.0f,%.0f) | fillet/junction band max %.2f MPa at (%.1f,%.1f,%.1f) | max disp %.3f mm"
              % (tag, case, vm[gmax], gp.x, gp.y, gp.z, bmax[0], bmax[1].x, bmax[1].y, bmax[1].z,
                 max(res.DisplacementLengths)))
    doc.saveAs(os.path.join(out, "root_%s.FCStd" % tag))
    if tag == "R%g" % T.FILLET_R:
        Part.export([obj], os.path.join(out, "root_block.step"))
    App.closeDocument(doc.Name)


run_variant(0.5, "R0.5")
run_variant(T.FILLET_R, "R%g" % T.FILLET_R)
print("ROOT done")
