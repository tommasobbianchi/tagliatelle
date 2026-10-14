"""FreeCAD FEM (CalculiX) static check of the camera arm solid. Headless:
    CAM_ARM_IN=/path/camera_arm.FCStd CAM_ARM_OUT=/path/fem freecad.cmd fem_arm.py

Load cases on one mesh: gravity + camera, then gravity + camera + 15 N accident at the tip in
+/- n (lateral), +/- d (along the arm), +/- z.  Support: the 4 M4 hole cylinders fixed
(conservative: the pad can bend, the bolts carry everything).
ASSUMED material ASA-GF: E 5000 MPa, nu 0.35, 1070 kg/m3; allowable 4 MPa (see size_members.py).
"""
import os, sys, math
sys.path.insert(0, os.getcwd())
import FreeCAD as App
import Part, ObjectsFem
from FreeCAD import Vector as V
import arm_topology as T

src = os.environ["CAM_ARM_IN"]
out = os.environ["CAM_ARM_OUT"]
os.makedirs(out, exist_ok=True)
CAMERA_N = (0.15 + 0.023) * 9.81     # camera + plate
ACC_N = 15.0

doc = App.openDocument(src)
obj = doc.getObject("camera_arm")
shape = obj.Shape
print("FEM shape valid=%s solids=%d vol=%.1f cm3 faces=%d" % (shape.isValid(), len(shape.Solids), shape.Volume / 1000, len(shape.Faces)))

# --- pick faces ---
tip = V(T.REACH_X, T.REACH_Y, 0)
hole_faces, slot_face = [], None
for i, f in enumerate(shape.Faces, 1):
    c = f.CenterOfMass
    s = f.Surface
    if s.__class__.__name__ == "Cylinder" and abs(s.Radius - T.HOLE_D / 2) < 0.05 and c.z < T.PAD_T + 1:
        hole_faces.append("Face%d" % i)
    if s.__class__.__name__ == "Plane" and abs(c.x - tip.x) < 12 and abs(c.y - tip.y) < 12 \
            and abs(c.z - (T.SLOT_Z - T.SLOT_L / 2)) < 1.0 and f.Area < 200:
        slot_face = "Face%d" % i
print("FEM hole faces", hole_faces, "slot lower face", slot_face)
assert len(hole_faces) >= 4 and slot_face, "face selection failed"

# --- direction helper lines (force direction needs an edge) ---
def dirline(name, v):
    ln = doc.addObject("Part::Feature", name)
    ln.Shape = Part.makeLine(V(0, 0, 0), V(*v) * 10)
    return ln
lines = {"n": dirline("dir_n", (T.NN[0], T.NN[1], 0)), "d": dirline("dir_d", (T.D[0], T.D[1], 0)),
         "z": dirline("dir_z", (0, 0, 1))}

analysis = ObjectsFem.makeAnalysis(doc, "Analysis")
solver = ObjectsFem.makeSolverCalculiXCcxTools(doc, "Solver")
solver.AnalysisType = "static"
solver.GeometricalNonlinearity = False   # bool in this FreeCAD (introspected)
solver.WorkingDir = out
analysis.addObject(solver)

mat = ObjectsFem.makeMaterialSolid(doc, "ASA_GF")
mat.Material = {"Name": "ASA-GF", "YoungsModulus": "5000 MPa", "PoissonRatio": "0.35", "Density": "1070 kg/m^3"}
analysis.addObject(mat)

fixed = ObjectsFem.makeConstraintFixed(doc, "BoltHoles")
fixed.References = [(obj, h) for h in hole_faces]
analysis.addObject(fixed)

grav = ObjectsFem.makeConstraintSelfWeight(doc, "Gravity")
grav.GravityDirection = V(0, 0, -1)
analysis.addObject(grav)

force = ObjectsFem.makeConstraintForce(doc, "TipForce")
force.References = [(obj, slot_face)]
analysis.addObject(force)

mesh = ObjectsFem.makeMeshGmsh(doc, "Mesh")
mesh.Shape = obj
mesh.CharacteristicLengthMax = "2.5 mm"      # <= rod radius for the 4-8 mm rods, else 2nd-order tets invert
mesh.CharacteristicLengthMin = "0.8 mm"
mesh.ElementOrder = "2nd"
for opt in ("Elastic+Optimization", "Optimization"):    # fix inverted high-order elements (ccx: nonpositive jacobian)
    try:
        mesh.HighOrderOptimize = opt
        print("FEM HighOrderOptimize =", opt)
        break
    except Exception as e:
        print("FEM HighOrderOptimize", opt, "not accepted:", str(e)[:60])
analysis.addObject(mesh)
doc.recompute()

from femmesh.gmshtools import GmshTools
gm = GmshTools(mesh)
err = gm.create_mesh()
print("FEM mesh err=%r nodes=%d tets=%d" % (err, mesh.FemMesh.NodeCount, mesh.FemMesh.VolumeCount))
assert mesh.FemMesh.NodeCount > 1000, "meshing failed"
doc.recompute()

from femtools import ccxtools

def run(name, axis, sign, magnitude):
    force.Force = App.Units.Quantity("%.4f N" % magnitude)   # bare float = mN in FreeCAD (measured: 15 became 0.015 N)
    force.Direction = (lines[axis], ["Edge1"])
    force.Reversed = sign < 0
    doc.recompute()
    fea = ccxtools.FemToolsCcx(analysis, solver, test_mode=False)
    fea.update_objects()
    fea.setup_working_dir()
    fea.setup_ccx()
    msg = fea.check_prerequisites()
    if msg:
        print("FEM prerequisites:", msg)
    fea.purge_results()
    fea.write_inp_file()
    fea.ccx_run()
    fea.load_results()
    res = [o for o in doc.Objects if o.isDerivedFrom("Fem::FemResultObject")][-1]
    disp = list(res.DisplacementLengths)
    vm = list(res.vonMises)
    if not disp or not vm:
        print("FEM case %-9s FAILED: no results (ccx error)" % name)
        return None
    nodes = (res.Mesh or mesh).FemMesh.Nodes
    ids = list(res.NodeNumbers)
    imax = max(range(len(vm)), key=lambda i: vm[i])
    p = nodes[ids[imax]]
    print("FEM case %-9s max_disp=%.3f mm  max_vonMises=%.2f MPa at (%.0f, %.0f, %.0f)  [allow 4.0]" %
          (name, max(disp), vm[imax], p.x, p.y, p.z))
    return res

run("gravity", "z", -1, CAMERA_N)
for ax in ("n", "d", "z"):
    for sg in (1, -1):
        run("acc%s%s" % ("+" if sg > 0 else "-", ax), ax, sg, CAMERA_N + ACC_N if (ax == "z" and sg < 0) else ACC_N)
doc.saveAs(os.path.join(out, "camera_arm_fem.FCStd"))
print("FEM done")
