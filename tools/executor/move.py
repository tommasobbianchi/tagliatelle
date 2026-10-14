"""One absolute XY move on the homed Snapmaker, laser off, Z untouched. Run on the executor.
  move.py X Y [F]        default 0 200 3000
Refuses unless: IDLE, homed, laserPower 0, target inside the soft box. Saves a Pi-camera frame before/after.
"""
import sys, threading, time
import cv2
import camera, snap

X, Y = float(sys.argv[1]) if len(sys.argv) > 2 else 0.0, float(sys.argv[2]) if len(sys.argv) > 2 else 200.0
F = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
assert -15.5 <= X <= 100 and 100 <= Y <= 238 and F <= 3000, "target outside the allowed test box"


def shot(name):
    f = camera.grab(camera.profile())
    cv2.imwrite("/tmp/move_%s.jpg" % name, cv2.resize(f, (1632, 1224)), [cv2.IMWRITE_JPEG_QUALITY, 85])


s = snap.Snap(); s.connect()
st = s.status()
print("before:", {k: st[k] for k in ("status", "x", "y", "z", "homed", "laserPower")}, flush=True)
assert st["status"] == "IDLE" and st["homed"] and st["laserPower"] == 0, "refusing: not idle/homed or laser power != 0"
shot("before")
for code in ("G90", "G1 X%g Y%g F%d" % (X, Y, F)):
    r = snap._req("/execute_code", ("token=%s&code=%s" % (s.token, code.replace(" ", "+"))).encode(), timeout=60,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    print("sent %-22s -> %r" % (code, r[:60]), flush=True)
t0 = time.time()
while time.time() - t0 < 30:
    time.sleep(1)
    c = s.status()
    print("%2ds %-8s x=%s y=%s z=%s" % (time.time() - t0, c["status"], c["x"], c["y"], c["z"]), flush=True)
    if c["status"] == "IDLE" and abs(c["x"] - X) < 0.2 and abs(c["y"] - Y) < 0.2:
        break
time.sleep(1)
shot("after")
c = s.status(); print("after:", {k: c[k] for k in ("status", "x", "y", "z", "homed", "laserPower")})
s.disconnect()
