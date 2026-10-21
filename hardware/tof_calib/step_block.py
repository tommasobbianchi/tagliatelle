"""Blocco a gradini (staircase) per calibrazione di range del sensore ToF VL53L8CX.

Scopo: il ToF ha errori sistematici di distanza (bias, wiggle, walk error) che dipendono
dalla distanza e dalla riflettanza. Un blocco con gradini ad altezza NOTA fornisce piu'
distanze di riferimento in una sola posa: si confronta la Z misurata dall'8x8 con le quote
nominali dei gradini.

Uso:  python3 step_block.py [cartella_output]
Produce step_block.step (CAD parametrico, fonte di verita') e step_block.stl (stampa).

La scala e' un unico profilo (sezione XZ) estruso lungo Y: nessuna faccia interna, quindi
l'STL e' un solo solido aperto e watertight. Le cifre incise sulla fronte (cosmetiche)
restano solo nel STEP, non nell'STL.

NOTA sull'STL: l'exporter standard di CadQuery/OCP in questo ambiente produce mesh vuote
anche per un cubo; per questo l'STL viene generato estruendo lo stesso profilo con
trimesh/shapely. I due file sono geometricamente identici (verifica volumi).

Note di stampa:
- Orientamento: appoggiare la base sul piano di stampa (i gradini salgono in X).
- Filamento MATE (PLA/PETG non glossy); evitare scuro lucido o riflettente: il nero
  lucido legge piu' lontano (walk error) e il glossy genera multipath.
- Layer ~0.2 mm. Le quote nominali vanno VERIFICATE al calibro dopo la stampa (tolleranza
  FDM ~±0.1-0.3 mm): l'asse di calibrazione usa i valori misurati, non quelli nominali.
- La distanza Z=0 e' il piano del letto: il blocco si appoggia sul letto; ogni gradino
  fornisce una quota di elevazione nota rispetto al letto.
"""
import os
import sys

import cadquery as cq

# ---------------- PARAMETRI ----------------
# Altezze dei gradini (mm) rispetto al piano del letto, dal basso verso l'alto.
STEP_HEIGHTS = [10.0, 20.0, 30.0, 45.0]

# Larghezza di ogni gradino lungo X (mm). N gradini => ingombro totale X = N*STEP_X.
STEP_X = 60.0

# Profondita' comune lungo Y (mm). Deve stare nel piano 250x250.
DEPTH_Y = 200.0

# Altezza cifre incise sulla fronte (mm) e profondita' incisione (mm). Solo nel STEP.
ENGRAVE_SIZE = 10.0
ENGRAVE_DEPTH = 0.8

OUT_DIR = sys.argv[1] if len(sys.argv) > 1 else "out"

if len(STEP_HEIGHTS) < 2:
    raise SystemExit("servono almeno 2 gradini")

# ---------------- Profilo della scala (sezione XZ) ----------------
def profile_points():
    pts = [(0.0, 0.0), (0.0, STEP_HEIGHTS[0])]
    x = 0.0
    for i, h in enumerate(STEP_HEIGHTS):
        x += STEP_X
        pts.append((x, h))
        if i + 1 < len(STEP_HEIGHTS):
            pts.append((x, STEP_HEIGHTS[i + 1]))
    pts.append((x, 0.0))
    return pts

PROFILE = profile_points()
TOTAL_X = len(STEP_HEIGHTS) * STEP_X

# ---------------- STEP (CAD parametrico) ----------------
profile = cq.Workplane("XZ").polyline(PROFILE).close()
body = profile.extrude(DEPTH_Y).translate((0, -DEPTH_Y / 2, 0))

front_y = -DEPTH_Y / 2
for i, h in enumerate(STEP_HEIGHTS):
    label = f"{h:g}"
    xc = i * STEP_X + STEP_X / 2
    engrave = (
        cq.Workplane("XZ", origin=(xc, front_y, h / 2))
        .text(label, ENGRAVE_SIZE, ENGRAVE_DEPTH, halign="center", valign="center", font="Arial")
    )
    body = body.cut(engrave)

s = body.val()
assert s.isValid(), "solido non valido"
assert len(body.solids().vals()) == 1, "piu' di un solido"
bb = s.BoundingBox()
vol_cm3 = s.Volume() / 1000.0

# ---------------- STL (estrusione dello stesso profilo) ----------------
def staircase_mesh():
    import numpy as np
    from shapely.geometry import Polygon
    import trimesh
    poly = Polygon(PROFILE)          # (X, quota) trattato come (X, Y) da shapely
    assert poly.is_valid and poly.area > 0
    m = trimesh.creation.extrude_polygon(poly, DEPTH_Y)  # estrusione lungo Z (prima Y=quota)
    # rimappa in (X, Y=depth, Z=quota): nuova Y = Z - prof/2, nuova Z = vecchia Y (quota)
    T = np.array([
        [1, 0, 0, 0],
        [0, 0, 1, -DEPTH_Y / 2],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
    ])
    m.apply_transform(T)
    return m

os.makedirs(OUT_DIR, exist_ok=True)
base = os.path.join(OUT_DIR, "step_block")
cq.exporters.export(body, base + ".step")

mesh = staircase_mesh()
mesh.export(base + ".stl")
assert mesh.is_watertight, "mesh STL non watertight"
assert abs(mesh.volume / 1000.0 - vol_cm3) < 0.5, "volume STL diverso dal STEP"

print(f"step_block: valido, X={bb.xlen:.1f} Y={bb.ylen:.1f} Z={bb.zlen:.1f} mm")
print(f"volume: {vol_cm3:.1f} cm3 (STEP) = {mesh.volume/1000:.1f} cm3 (STL, watertight)")
print(f"gradini (quote nominali, mm): {STEP_HEIGHTS}")
print("-> verificare le quote al calibro dopo la stampa; l'asse di calibrazione usa i valori misurati")
