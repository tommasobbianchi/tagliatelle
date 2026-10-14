"""Laser-camera capture exactly as Luban does it for the A250 10W head (ExtractSquareTrace/takePhotos):
GET /api/request_capture_photo?index=0&x=186&y=130&z=230&feedRate=3000&photoQuality=0   (the machine moves the head),
then GET /api/get_camera_image?index=0.  Pi-camera frame before and after.  Laser stays off.
Refuses unless IDLE, homed, laserPower 0.  Run on the executor.
"""
import hashlib, sys, time, urllib.request
import cv2
import camera, snap

X, Y, Z, F = 186, 130, 230, 3000      # Luban LASER_10W_TAKE_PHOTO_POSITION[A250] (+ material thickness 0)
B = "http://%s:8080" % snap.HOST


def shot(name):
    f = camera.grab(camera.profile())
    cv2.imwrite("/tmp/lc_%s.jpg" % name, cv2.resize(f, (1632, 1224)), [cv2.IMWRITE_JPEG_QUALITY, 85])
    print("Pi frame %s: markers %s" % (name, sorted(camera.detect(f))), flush=True)


def image():
    with urllib.request.urlopen("%s/api/get_camera_image?index=0" % B, timeout=15) as r:
        return r.read()


s = snap.Snap(); s.connect()
st = s.status()
print("before:", {k: st[k] for k in ("status", "x", "y", "z", "homed", "laserPower")}, flush=True)
assert st["status"] == "IDLE" and st["homed"] and st["laserPower"] == 0, "refusing: not idle/homed or laser power != 0"
old = hashlib.md5(image()).hexdigest()
shot("before")
url = "%s/api/request_capture_photo?index=0&x=%s&y=%s&z=%s&feedRate=%s&photoQuality=0" % (B, X, Y, Z, F)
with urllib.request.urlopen(url, timeout=30) as r:
    print("request_capture_photo ->", r.read()[:80], flush=True)
t0, new = time.time(), None
while time.time() - t0 < 60:
    time.sleep(2)
    c = s.status()
    try:
        d = image()
    except Exception as e:
        d = None
    h = hashlib.md5(d).hexdigest() if d else None
    print("%2ds %-8s x=%s y=%s z=%s image=%s" % (time.time() - t0, c["status"], c["x"], c["y"], c["z"], "new" if h and h != old else "old"), flush=True)
    if h and h != old and c["status"] == "IDLE":
        new = d
        break
if new:
    open("/tmp/laser_cam_new.jpg", "wb").write(new)
    print("saved /tmp/laser_cam_new.jpg", len(new), "bytes")
else:
    print("no new image within 60 s")
time.sleep(1)
shot("after")
c = s.status(); print("after:", {k: c[k] for k in ("status", "x", "y", "z", "homed", "laserPower")})
s.disconnect()
