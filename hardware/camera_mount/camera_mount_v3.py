"""Supporto camera USB (ELP) per attacco treppiede, v3 (PCB 62.2 mm): filetto 1/4"-20 UNC femmina
modellato direttamente nella plastica (nessun dado).

Assi: Z = asse della vite del treppiede, Y+ = direzione in cui guarda la camera.
La vite della piastra entra dal piano z=0 (faccia inferiore della base); il filetto e'
passante e ha uno smusso di invito.

Uso:  python3 -I camera_mount_v3.py [cartella_output]
Produce camera_mount_v3.(step|stl) e thread_test.(step|stl), un provino di 12 mm con lo
stesso filetto per verificare l'accoppiamento in pochi minuti di stampa.
Misure in mm; modificare solo la sezione PARAMETRI.

Storia: v2 = PCB_L 61.0 (stampata); v3 = PCB_L 62.2 (misura reale della scheda, dato da Tommy).
Dipendenza: pip install cadquery  (verificato con 2.8.0). Tempo: ~1m50s (il controllo
di interferenza del filetto e' la parte lenta).
"""
import math
import os
import sys

import cadquery as cq

# ---------------- PARAMETRI ----------------
# Filetto 1/4"-20 UNC
MAJOR_D = 6.35
PITCH = 25.4 / 20          # 1.27 mm
CREST_FLAT = PITCH / 8     # piatto di cresta vite
ROOT_FLAT = PITCH / 4      # piatto di fondo vite
THREAD_CLR = 0.1           # gioco radiale su fianchi, cresta e fondo (richiesto: 0.1 mm)
LEAD_IN = 0.7              # smusso di invito all'imbocco

# Base e parete
BASE_X, BASE_Y, BASE_T = 32.0, 24.0, 12.0
WALL_X, WALL_T, WALL_H = 20.0, 6.0, 78.0
GUSSET_T, GUSSET_Y, GUSSET_Z = 3.0, 10.0, 10.0

# Scheda camera (lunghezza misurata dall'utente: 62.2; il resto da foto, da verificare con il calibro)
PCB_L, PCB_W = 62.2, 10.0
POCKET_CLR = 0.3
POCKET_DEPTH = 1.0
PCB_BOTTOM_Z = 14.0
HOLE_FROM_END = 3.3
HOLE_SPACING = 5.5
PILOT_D, PILOT_DEPTH = 1.8, 3.5

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "out"

T30 = math.tan(math.radians(30))
C30 = math.cos(math.radians(30))
# profondita' del filetto esterno: (P - ROOT_FLAT - CREST_FLAT) / 2 / tan30
DEPTH = (PITCH - ROOT_FLAT - CREST_FLAT) / 2 / T30
R_MAJOR = MAJOR_D / 2
R_MINOR = R_MAJOR - DEPTH


def threaded_rod(r_core, base_w, top_w, z_start, z_end, overlap=0.05):
    """Anima cilindrica + cresta elicoidale (profilo trapezoidale a 60 gradi)."""
    length = z_end - z_start
    helix = cq.Wire.makeHelix(PITCH, length, r_core - overlap)
    r_in, r_out = r_core - overlap, r_core + DEPTH
    w_in = base_w + 2 * overlap * T30
    prof = (
        cq.Workplane("XZ")
        .polyline([(r_in, -w_in / 2), (r_in, w_in / 2), (r_out, top_w / 2), (r_out, -top_w / 2)])
        .close()
    )
    ridge = prof.sweep(cq.Workplane(obj=helix), isFrenet=True)
    core = cq.Workplane("XY").circle(r_core).extrude(length)
    # NB: core.union(ridge) scarta l'anima in OCC: le due parti restano separate
    return [core.translate((0, 0, z_start)), ridge.translate((0, 0, z_start))]


def internal_thread_tools(length):
    """Utensili di taglio del filetto femmina: vite nominale espansa di THREAD_CLR."""
    c = THREAD_CLR
    base_w = (PITCH - ROOT_FLAT) + 2 * c / C30 - 2 * c * T30
    top_w = CREST_FLAT + 2 * c / C30 - 2 * c * T30
    core, ridge = threaded_rod(R_MINOR + c, base_w, top_w, -2 * PITCH, length + 2 * PITCH)
    cone = cq.Workplane(obj=cq.Solid.makeCone(R_MAJOR + c + LEAD_IN, R_MINOR + c, DEPTH + c + LEAD_IN))
    return [ridge, core, cone]  # ordine importante: la cresta va tagliata prima dell anima


def cut_all(wp, tools):
    for t in tools:
        wp = wp.cut(t)
    return wp


def nominal_screw(length):
    return threaded_rod(R_MINOR, PITCH - ROOT_FLAT, CREST_FLAT, 0.0, length)


# ---------------- MODELLO ----------------
tools = internal_thread_tools(BASE_T)

base = cut_all(cq.Workplane("XY").box(BASE_X, BASE_Y, BASE_T, centered=(True, True, False)), tools)

y_back = -BASE_Y / 2
y_front = y_back + WALL_T
wall = (
    cq.Workplane("XY")
    .box(WALL_X, WALL_T, WALL_H + 1.0, centered=(True, False, False))
    .translate((0, y_back, BASE_T - 1.0))
)
body = base.union(wall)

for x0 in (-(WALL_X / 2 - GUSSET_T), WALL_X / 2 - GUSSET_T):
    g = (
        cq.Workplane("YZ")
        .workplane(offset=x0 - GUSSET_T / 2)
        .polyline([(y_front - 0.5, BASE_T - 0.5), (y_front + GUSSET_Y, BASE_T - 0.5), (y_front - 0.5, BASE_T + GUSSET_Z)])
        .close()
        .extrude(GUSSET_T)
    )
    body = body.union(g)

z0 = BASE_T + PCB_BOTTOM_Z
pocket = (
    cq.Workplane("XY")
    .box(PCB_W + 2 * POCKET_CLR, POCKET_DEPTH, PCB_L + 2 * POCKET_CLR, centered=(True, False, False))
    .translate((0, y_front - POCKET_DEPTH, z0 - POCKET_CLR))
)
body = body.cut(pocket)

z_holes = z0 + PCB_L - HOLE_FROM_END
pilots = (
    cq.Workplane("XZ", origin=(0, y_front - POCKET_DEPTH, 0))
    .pushPoints([(-HOLE_SPACING / 2, z_holes), (HOLE_SPACING / 2, z_holes)])
    .circle(PILOT_D / 2)
    .extrude(PILOT_DEPTH)
)
body = body.cut(pilots)

# provino del filetto (disco 20 x 12 mm con lo stesso foro)
coupon = cut_all(cq.Workplane("XY").circle(10.0).extrude(BASE_T), tools)

# ---------------- CONTROLLI ----------------
def check(name, wp):
    s = wp.val()
    assert s.isValid(), f"{name}: solido non valido"
    assert len(wp.solids().vals()) == 1, f"{name}: piu' di un solido"
    return s

solid = check("supporto", body)
check("provino", coupon)

# interferenza tra provino e vite nominale 1/4"-20, scansionando la fase assiale
# (una vite che si avvita ruota e avanza: l'accoppiamento e' una sola fase, ogni PITCH)
core_s, ridge_s = nominal_screw(BASE_T + 4.0)
core_s, ridge_s = core_s.translate((0, 0, -2.0)), ridge_s.translate((0, 0, -2.0))


def interference(s):
    tot = 0.0
    for part in (core_s, ridge_s):
        r = coupon.intersect(part.translate((0, 0, s)))
        tot += r.val().Volume() if r.vals() else 0.0
    return tot


phases = [(interference(k * PITCH / 16), k * PITCH / 16) for k in range(16)]
best_i, best_s = min(phases)
print(f"interferenza minima con vite nominale: {best_i:.3f} mm3 a fase {best_s:.3f} mm (deve essere ~0)")
print(f"interferenza media sulle altre fasi: {sum(p[0] for p in phases)/16:.1f} mm3")

os.makedirs(OUT_DIR, exist_ok=True)
for name, wp in (("camera_mount_v3", body), ("thread_test", coupon)):
    cq.exporters.export(wp, os.path.join(OUT_DIR, name + ".step"))
    cq.exporters.export(wp, os.path.join(OUT_DIR, name + ".stl"), tolerance=0.01, angularTolerance=0.1)
bb = solid.BoundingBox()
print(f"supporto: valido, X={bb.xlen:.1f} Y={bb.ylen:.1f} Z={bb.zlen:.1f} mm, volume={solid.Volume()/1000:.1f} cm3")
print(f"filetto: M{MAJOR_D}=1/4-20 UNC, passo {PITCH:.3f}, profondita' {DEPTH:.3f}, gioco {THREAD_CLR} mm")
