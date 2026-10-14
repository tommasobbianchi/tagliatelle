"""Beam-element FEM of the sized camera arm in the FreeCAD FEM workbench (CalculiX), headless:
    CAM_ARM_OUT=/path/fem_beam freecad.cmd fem_beam.py        (cwd = this folder, needs sizing.json)

No solid booleans: the truss is a network of line edges (generalFuse merges the shared node
vertices), every member is a circular beam section with its sized diameter.
Cross-check target (numpy frame model, size_members.py): tip deflection under gravity+camera 0.21 mm.
ASSUMED material ASA-GF: E 5000 MPa, nu 0.35, 1070 kg/m3, allowable 4 MPa.
"""
import os, sys, json, math
sys.path.insert(0, os.getcwd())
import FreeCAD as App
import Part, ObjectsFem
from FreeCAD import Vector as V
import arm_topology as T

out = os.environ["CAM_ARM_OUT"]
os.makedirs(out, exist_ok=True)
CAMERA_N = (0.15 + 0.023) * 9.81
ACC_N = 15.0

nodes, members, base, tip = T.build()
dia = json.load(open("sizing.json"))["diameters"]
assert len(dia) == len(members)
P = [V(*p) for p in nodes]

doc = App.newDocument("beam_arm")
lines = [Part.makeLine(P[a], P[b]) for a, b, _ in members]
frag = lines[0].generalFuse(lines[1:])[0]
geo = doc.addObject("Part::Feature", "truss")
geo.Shape = frag
doc.recompute()
print("BEAM geometry: %d edges, %d vertices (members %d, nodes %d)" %
      (len(frag.Edges), len(frag.Vertexes), len(members), len(nodes)))

def member_of(edge):
    m_pt = edge.valueAt((edge.FirstParameter + edge.LastParameter) / 2)
    best, bd = None, 1e9
    for k, ln in enumerate(lines):
        d = ln.distToShape(Part.Vertex(m_pt))[0]
        if d < bd:
            best, bd = k, d
    assert bd < 1e-3, "edge not on any member"
    return best

groups = {}
for i, e in enumerate(frag.Edges, 1):
    d = round(dia[member_of(e)], 1)
    groups.setdefault(d, []).append("Edge%d" % i)
print("BEAM %d distinct sections:" % len(groups), sorted(groups))

analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver")
solver.AnalysisType = "static"
solver.GeometricalNonlinearity = False
solver.WorkingDir = out
analysis.addObject(solver)

mat = ObjectsFem.makeMaterialSolid(doc, "ASA_GF")
mat.Material = {"Name": "ASA-GF", "YoungsModulus": "5000 MPa", "PoissonRatio": "0.35", "Density": "1070 kg/m^3"}
analysis.addObject(mat)

for d, edges in groups.items():
    sec = ObjectsFem.makeElementGeometry1D(doc, name="Sec_%s" % str(d).replace(".", "_"))
    try:
        sec.SectionType = "Circular"
        sec.CircDiameter = d
    except Exception as ex:
        print("BEAM section property error:", ex, [p for p in sec.PropertiesList if "Circ" in p or "Section" in p])
        raise
    sec.References = [(geo, e) for e in edges]
    analysis.addObject(sec)

def vertices_at(coords):
    res = []
    for i, v in enumerate(frag.Vertexes, 1):
        if any((v.Point - c).Length < 1e-4 for c in coords):
            res.append("Vertex%d" % i)
    return res

base_v = vertices_at([P[i] for i in base])
tip_v = vertices_at([P[i] for i in tip])
print("BEAM base vertices", base_v, "tip vertices", tip_v)
assert len(base_v) == len(base) and len(tip_v) == len(tip)

fixed = ObjectsFem.makeConstraintFixed(doc, "Bolts")
fixed.References = [(geo, v) for v in base_v]
analysis.addObject(fixed)

grav = ObjectsFem.makeConstraintSelfWeight(doc, "Gravity")
grav.GravityDirection = V(0, 0, -1)
analysis.addObject(grav)

def dirline(name, v):
    ln = doc.addObject("Part::Feature", name)
    ln.Shape = Part.makeLine(V(0, 0, 0), V(*v) * 10)
    return ln
dl = {"n": dirline("dir_n", (T.NN[0], T.NN[1], 0)), "d": dirline("dir_d", (T.D[0], T.D[1], 0)),
      "z": dirline("dir_z", (0, 0, 1))}

force = ObjectsFem.makeConstraintForce(doc, "TipForce")
force.References = [(geo, v) for v in tip_v]
analysis.addObject(force)

mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
mesh.Shape = geo
mesh.ElementOrder = "2nd"
mesh.CharacteristicLengthMax = "25 mm"
mesh.CharacteristicLengthMin = "5 mm"
try:
    mesh.ElementDimension = "1D"
except Exception as ex:
    print("BEAM ElementDimension not settable:", str(ex)[:60], [p for p in mesh.PropertiesList if "Dim" in p])
analysis.addObject(mesh)
doc.recompute()

from femmesh.gmshtools import GmshTools
err = GmshTools(mesh).create_mesh()
print("BEAM mesh err=%r nodes=%d edges=%d" % (err, mesh.FemMesh.NodeCount, mesh.FemMesh.EdgeCount))
assert mesh.FemMesh.EdgeCount > 0, "no beam elements"
doc.recompute()

from femtools import ccxtools

def run(name, axis, sign, magnitude):
    force.Force = App.Units.Quantity("%.4f N" % magnitude)   # bare float = mN in FreeCAD (measured: 15 became 0.015 N)
    force.Direction = (dl[axis], ["Edge1"])
    force.Reversed = sign < 0
    doc.recompute()
    fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=False)
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx()
    msg = fea.check_prerequisites()
    if msg:
        print("BEAM prerequisites:", msg)
    fea.purge_results()
    fea.write_inp_file()
    import shutil, re
    shutil.copy(fea.inp_file_name, os.path.join(out, "case_%s.inp" % name))
    inp = open(fea.inp_file_name).read()
    print("BEAM inp %-9s CLOAD lines=%d DLOAD=%d BOUNDARY lines=%d force=%.2f N dir=%s rev=%s" % (
        name, len(re.findall(r"(?im)^\s*\d+\s*,\s*[123]\s*,\s*-?[\d.eE+-]+\s*$", inp.split("*CLOAD")[-1].split("*")[0])) if "*CLOAD" in inp else 0,
        inp.count("*DLOAD"), inp.upper().count("*BOUNDARY"), float(force.Force.getValueAs("N")),
        str(force.Direction)[:40], force.Reversed))
    fea.ccx_run()
    fea.load_results()
    res = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")][-1]
    disp = list(res.DisplacementLengths)
    if not disp:
        print("BEAM case %-9s FAILED: no results" % name)
        return
    ids = list(res.NodeNumbers)
    fm = (res.Mesh or mesh).FemMesh
    # tip deflection = max |z displacement| over tip nodes
    zs = list(res.DisplacementVectors)
    tip_nodes = [n for n, pos in fm.Nodes.items() if n in set(ids) and any((pos - P[t]).Length < 1e-3 for t in tip)]
    tip_dz = max(abs(zs[ids.index(n)].z) for n in tip_nodes) if tip_nodes else float("nan")
    vm = list(res.vonMises) if len(res.vonMises) else []
    if vm:
        imax = max(range(len(vm)), key=lambda i: vm[i])
        p = fm.Nodes[ids[imax]]
        s = "max_vonMises=%.2f MPa at (%.0f,%.0f,%.0f) [allow 4.0]" % (vm[imax], p.x, p.y, p.z)
    else:
        s = "no stress output"
    print("BEAM case %-9s max_disp=%.3f mm tip_dz=%.3f mm  %s" % (name, max(disp), tip_dz, s))

run("gravity", "z", -1, CAMERA_N)
for ax in ("n", "d", "z"):
    for sg in (1, -1):
        run("acc%s%s" % ("+" if sg > 0 else "-", ax), ax, sg, ACC_N + (CAMERA_N if (ax == "z" and sg < 0) else 0.0))
doc.saveAs(os.path.join(out, "camera_arm_beam.FCStd"))
print("BEAM done")
