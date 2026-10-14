"""Shared geometry/topology of the camera arm (pure python, no FreeCAD, no numpy).

Frame: origin = centre of the 46x46 pad on the pillar top, z=0 = pillar top (330 mm above
the bed), +X toward the bed centre, +Y toward the bed, +Z up.  ASSUMED = from chat 2026-10-11.
"""
import math

PAD = 46.0
HOLE_PITCH = 25.0     # 4x M4, square
HOLE_D = 4.5
PAD_T = 8.0           # plate thickness (was 6: bolt prying at the root)
PED_W = 33.0          # pedestal width: bolt access holes (r 1.75 at +/-12.5) need a >= 2 mm wall
PED_H = 14.0          # pedestal height above the plate
FILLET_R = 6.0        # pedestal -> plate fillet, ledge = (46-33)/2 = 6.5 mm
CSK_D = 8.4           # DIN 7991 M4 countersink diameter at the plate top, 90 deg
ACCESS_D = 3.5        # hex-key access hole through the pedestal
REACH_X = 149.0       # 136.5 (half of 273 mm medial holes) + 12.5
LENS_Y = 245.0        # ASSUMED: lens target in Y = 23 + 90 gap + 265/2 (265 mm taken as Y depth)
LENS_OFFSET = 50.0    # lens is 50 mm beyond the plate face along the bolt axis (user, 2026-10-11)
REACH_Y = LENS_Y - LENS_OFFSET   # plate plane: vertical plate, normal along machine Y, bolt along Y
SLOT_Z = 70.0         # slot centre above pillar top = 400 mm above the bed
CABLE_UP = 60.0
CLEAR = 25.0          # ASSUMED margin over the highest moving part / cable
RISER_H = CABLE_UP + CLEAR
T_UP, T_DN = 0.22, 0.62
Z_BOT_TIP = 62.0
Z_TOP_ROOT, Z_TOP_TIP, CROWN = 140.0, 112.0, 14.0
Z_BASE = PAD_T + PED_H          # rods start on the pedestal top
Z_BOT_ROOT = Z_BASE + 25.0       # station-0 lower nodes sit above the base nodes
W_ROOT, W_TIP = 12.5, 20.0
PLATE_W, PLATE_T = 50.0, 6.0
PLATE_Z0 = SLOT_Z - 30.0
SLOT_W, SLOT_L = 6.6, 40.0
N = 6

L = math.hypot(REACH_X, REACH_Y)
D = (REACH_X / L, REACH_Y / L)               # plan direction pad -> tip
NN = (-D[1], D[0])                           # lateral
ANG = math.degrees(math.atan2(D[1], D[0]))
H = HOLE_PITCH / 2


def smooth(x):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(x, 0.0), 1.0))


def z_bot(t):
    if t <= 0:
        return Z_BOT_ROOT
    if t <= T_UP:
        return Z_BOT_ROOT + (RISER_H - Z_BOT_ROOT) * smooth(t / T_UP)
    if t <= T_DN:
        return RISER_H
    return RISER_H + (Z_BOT_TIP - RISER_H) * smooth((t - T_DN) / (1 - T_DN))


def z_top(t):
    return Z_TOP_TIP + (Z_TOP_ROOT - Z_TOP_TIP) * (1 - t) + 4 * CROWN * t * (1 - t)


def _node(t, side, level):
    w = W_ROOT + (W_TIP - W_ROOT) * t
    return (REACH_X * t + NN[0] * side * w, REACH_Y * t + NN[1] * side * w,
            z_bot(t) if level == "b" else z_top(t))


def build():
    """-> nodes [(x,y,z)], members [(i,j,kind)], base_ids, tip_ids."""
    nodes, members = [], []

    def add(p):
        nodes.append(p)
        return len(nodes) - 1

    # base nodes on the pedestal top at the edge midpoints (bolt access holes sit at the corners)
    base = [add((sx, sy, Z_BASE)) for sx, sy in ((-H, 0.0), (0.0, -H), (H, 0.0), (0.0, H))]
    st = []
    sgn = math.copysign(1.0, NN[0])
    for k in range(N + 1):
        t = k / N
        if k == N:        # last ring lies IN the tip plate plane (normal = machine Y), width along X
            def tipn(side, level):
                return (REACH_X + side * W_TIP * sgn * -1.0, REACH_Y, z_bot(1.0) if level == "b" else z_top(1.0))
            st.append([add(tipn(-1, "b")), add(tipn(1, "b")), add(tipn(1, "t")), add(tipn(-1, "t"))])
            continue
        st.append([add(_node(t, -1, "b")), add(_node(t, 1, "b")),
                   add(_node(t, 1, "t")), add(_node(t, -1, "t"))])
    seen = set()

    def mem(a, b, kind):
        key = (min(a, b), max(a, b))
        if key not in seen:
            seen.add(key)
            members.append((a, b, kind))

    for b in base:                                   # root ground structure: every base node to every station-0 node
        for s in st[0]:
            mem(b, s, "root")
    for k, s in enumerate(st):
        for i in range(4):
            mem(s[i], s[(i + 1) % 4], "ring")
    for k in range(N):
        a, b = st[k], st[k + 1]
        for i in range(4):
            mem(a[i], b[i], "chord")
        mem(a[0], b[3], "diag"); mem(a[1], b[2], "diag")      # side faces
        mem(a[0], b[1], "diag"); mem(a[3], b[2], "diag")      # bottom / top faces
    return nodes, members, base, st[-1]
