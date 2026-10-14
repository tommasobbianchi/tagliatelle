"""Generative member sizing for the camera arm: 3D frame FE + fully-stressed design.

PREDICTIONS (written before the first run, status: pending)
  P1 [PARTLY CONFIRMED 2026-10-11: thickest = chord/root groups; position-by-t not checked] The highest-utilisation members are the root group and first-bay chords
     (t < 0.35); max member force / median member force > 5.
  P2 [CONFIRMED: 72 % at D_MIN, mass -55 % vs uniform 8 mm] After sizing >= 50 % of members sit at D_MIN and total mass is >= 40 % below
     the uniform 8 mm version (216 cm3, ~230 g).
  P3 [REFUTED narrowly: 0.211 mm, limit used was 0.3] Tip deflection under camera+self weight < 0.2 mm after sizing.
  Cheapest check first: this script itself (milliseconds), no CAD run needed.

Run:  python3 size_members.py        -> writes sizing.json (diameter per member, topology order)
ASSUMED material (ASA-GF printed, conservative): E = 5000 MPa, allowable 4 MPa (interlayer
strength / safety), accidental load 15 N applied at the tip in each direction.
"""
import json, math, sys
import numpy as np
import arm_topology as T

E, G = 5000.0, 5000.0 / 2.6          # MPa = N/mm2
SIG_ALLOW = 4.0                      # MPa, against combined axial + bending (+ torsion)
SF_BUCKLE = 3.0
D_MIN, D_MAX = 4.0, 22.0             # mm, printable range
RHO = 1.07e-6                        # kg/mm3
CAMERA_KG = 0.15
PLATE_KG = 0.023
ACCIDENT_N = 15.0
DEFL_LIMIT = 0.3                     # mm at the tip under gravity, camera framing stability

nodes, members, base, tip = T.build()
P = np.array(nodes)
nN, nM = len(nodes), len(members)
Lm = np.array([np.linalg.norm(P[b] - P[a]) for a, b, _ in members])
kinds = [k for _, _, k in members]


def local_k(d, L):
    A = math.pi * d * d / 4
    I = math.pi * d ** 4 / 64
    J = 2 * I
    k = np.zeros((12, 12))
    k[0, 0] = k[6, 6] = E * A / L; k[0, 6] = k[6, 0] = -E * A / L
    k[3, 3] = k[9, 9] = G * J / L; k[3, 9] = k[9, 3] = -G * J / L
    a, b, c, e = 12 * E * I / L ** 3, 6 * E * I / L ** 2, 4 * E * I / L, 2 * E * I / L
    for (v, th, s) in ((1, 5, 1), (2, 4, -1)):          # bending in xy (about z) and xz (about y)
        v2, th2 = v + 6, th + 6
        k[v, v] = k[v2, v2] = a
        k[v, v2] = k[v2, v] = -a
        k[v, th] = k[th, v] = s * b
        k[v, th2] = k[th2, v] = s * b
        k[v2, th] = k[th, v2] = -s * b
        k[v2, th2] = k[th2, v2] = -s * b
        k[th, th] = k[th2, th2] = c
        k[th, th2] = k[th2, th] = e
    return k


def rot(a, b):
    ex = (P[b] - P[a]); ex = ex / np.linalg.norm(ex)
    ref = np.array([0, 0, 1.0]) if abs(ex[2]) < 0.99 else np.array([1.0, 0, 0])
    ey = np.cross(ref, ex); ey /= np.linalg.norm(ey)
    ez = np.cross(ex, ey)
    R = np.array([ex, ey, ez])
    Tm = np.zeros((12, 12))
    for i in range(4):
        Tm[3 * i:3 * i + 3, 3 * i:3 * i + 3] = R
    return Tm


ROT = [rot(a, b) for a, b, _ in members]
fixed = np.array([6 * n + c for n in base for c in range(6)])
free = np.setdiff1d(np.arange(6 * nN), fixed)


def solve(dia, loads):
    K = np.zeros((6 * nN, 6 * nN))
    for m, (a, b, _) in enumerate(members):
        dofs = np.r_[6 * a:6 * a + 6, 6 * b:6 * b + 6]
        kg = ROT[m].T @ local_k(dia[m], Lm[m]) @ ROT[m]
        K[np.ix_(dofs, dofs)] += kg
    u = np.zeros(6 * nN)
    u[free] = np.linalg.solve(K[np.ix_(free, free)], loads[free])
    return u, K


def member_util(dia, u):
    util = np.zeros(nM)
    for m, (a, b, _) in enumerate(members):
        dofs = np.r_[6 * a:6 * a + 6, 6 * b:6 * b + 6]
        f = local_k(dia[m], Lm[m]) @ (ROT[m] @ u[dofs])
        d = dia[m]; A = math.pi * d * d / 4; I = math.pi * d ** 4 / 64
        N = f[6]
        M = max(math.hypot(f[4], f[5]), math.hypot(f[10], f[11]))
        sig = abs(N) / A + M * (d / 2) / I
        tau = abs(f[9]) * (d / 2) / (2 * I)
        s = math.sqrt(sig ** 2 + 3 * tau ** 2) / SIG_ALLOW
        if N < 0:                                              # Euler buckling, pinned-pinned (conservative K=1)
            pcr = math.pi ** 2 * E * I / Lm[m] ** 2 / SF_BUCKLE
            s = max(s, abs(N) / pcr)
        util[m] = s
    return util


def gravity_loads(dia):
    F = np.zeros(6 * nN)
    for m, (a, b, _) in enumerate(members):
        w = RHO * math.pi * dia[m] ** 2 / 4 * Lm[m] * 9.81
        F[6 * a + 2] -= w / 2; F[6 * b + 2] -= w / 2
    for t in tip:
        F[6 * t + 2] -= (CAMERA_KG + PLATE_KG) * 9.81 / len(tip)
    return F


def cases(dia):
    g = gravity_loads(dia)
    out = {"gravity": g}
    dirs = {"+n": (T.NN[0], T.NN[1], 0), "-n": (-T.NN[0], -T.NN[1], 0),
            "+d": (T.D[0], T.D[1], 0), "-d": (-T.D[0], -T.D[1], 0), "+z": (0, 0, 1), "-z": (0, 0, -1)}
    for name, v in dirs.items():
        F = g.copy()
        for t in tip:
            for c in range(3):
                F[6 * t + c] += ACCIDENT_N / len(tip) * v[c]
        out["acc" + name] = F
    return out


dia = np.full(nM, 8.0)
for it in range(600):
    util = np.zeros(nM)
    for name, F in cases(dia).items():
        u, _ = solve(dia, F)
        util = np.maximum(util, member_util(dia, u))
    # fully-stressed update; bending-dominated -> sigma ~ d^-3, axial -> d^-2: use d^(-2.5)
    new = np.clip(dia * np.power(np.maximum(util, 1e-6), 1 / 2.5), D_MIN, D_MAX)
    new = 0.5 * dia + 0.5 * new
    delta = float(np.max(np.abs(new - dia)))
    dia = new
    if delta < 0.01:
        break

# stiffness constraint: tip deflection under gravity + camera
def tip_defl(d):
    u, _ = solve(d, gravity_loads(d))
    return max(abs(u[6 * t + 2]) for t in tip)


scale = 1.0
while tip_defl(np.clip(dia * scale, D_MIN, D_MAX)) > DEFL_LIMIT and scale < 3:
    scale *= 1.05
dia = np.clip(dia * scale, D_MIN, D_MAX)

util = np.zeros(nM)
reac = {}
for name, F in cases(dia).items():
    u, K = solve(dia, F)
    util = np.maximum(util, member_util(dia, u))
    r = K @ u - F
    reac[name] = max(abs(r[6 * b + 2]) for b in base)          # vertical reaction per bolt
mass = sum(RHO * math.pi * dia[m] ** 2 / 4 * Lm[m] for m in range(nM)) * 1000
mass0 = sum(RHO * math.pi * 8.0 ** 2 / 4 * Lm[m] for m in range(nM)) * 1000
t_of = lambda m: max(P[members[m][0]][2], P[members[m][1]][2])
json.dump({"diameters": [round(float(x), 2) for x in dia]}, open("sizing.json", "w"))

order = np.argsort(-dia)
# --- member end loads on the root pedestal, for the solid sub-model (fem_root.py) ---
root_loads = {}
for name in ("gravity", "acc+n", "acc-n", "acc+z", "acc-z"):
    u, _ = solve(dia, cases(dia)[name])
    per = {}
    for m, (a, b, kd) in enumerate(members):
        if kd != "root":
            continue
        dofs = np.r_[6 * a:6 * a + 6, 6 * b:6 * b + 6]
        fg = ROT[m].T @ (local_k(dia[m], Lm[m]) @ (ROT[m] @ u[dofs]))   # forces nodes -> element, global
        e = per.setdefault(a, {"pos": [float(x) for x in P[a]], "F": np.zeros(3), "M": np.zeros(3)})
        e["F"] += -fg[0:3]            # load the element puts on the pedestal at node a
        e["M"] += -fg[3:6]
    root_loads[name] = {str(a): {"pos": v["pos"], "F": [round(float(x), 3) for x in v["F"]],
                                 "M": [round(float(x), 1) for x in v["M"]]} for a, v in per.items()}
json.dump(root_loads, open("root_loads.json", "w"), indent=1)

print("RESULT members=%d scale=%.2f iters=%d last_delta=%.3f mm" % (nM, scale, it + 1, delta))
print("RESULT mass %.0f g (uniform 8 mm: %.0f g, -%.0f%%)" % (mass, mass0, 100 * (1 - mass / mass0)))
print("RESULT at D_MIN: %d/%d (%.0f%%); max util %.2f; tip deflection %.3f mm (limit %.1f)" %
      (int((dia <= D_MIN + 1e-6).sum()), nM, 100 * (dia <= D_MIN + 1e-6).mean(), util.max(),
       tip_defl(dia), DEFL_LIMIT))
print("RESULT thickest 8:", [(kinds[m], round(float(dia[m]), 1)) for m in order[:8]])
by = {}
for m in range(nM):
    by.setdefault(kinds[m], []).append(dia[m])
print("RESULT mean dia by kind:", {k: round(float(np.mean(v)), 1) for k, v in by.items()})
print("RESULT max vertical bolt reaction per base node [N]:", {k: round(float(v), 1) for k, v in reac.items()})
