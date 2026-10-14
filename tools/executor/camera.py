"""Executor camera: fixed profile (exposure/focus/WB off auto) + capture + ArUco check.

  camera.py apply            set the profile from camera_profile.json
  camera.py capture OUT.png  apply + grab one frame + report markers
  camera.py sweep-focus      find the sharpest focus on the marker ROIs, write it to the profile

Profile is applied before every capture: UVC settings are runtime state and reset on re-plug.
"""
import json, subprocess, sys, time
from pathlib import Path
import cv2, numpy as np

DEV, PROFILE = "/dev/video0", Path(__file__).with_name("camera_profile.json")
DEFAULT = {"width": 3264, "height": 2448, "exposure": 100, "focus": 500, "wb_kelvin": 4600}
IDS = {0, 1, 2, 3, 4}


def profile():
    return {**DEFAULT, **(json.loads(PROFILE.read_text()) if PROFILE.exists() else {})}


def v4l(*ctrls):
    for c in ctrls:
        subprocess.run(["v4l2-ctl", "-d", DEV, "--set-ctrl=" + c], check=True, capture_output=True)


def apply(p):
    v4l("auto_exposure=1", "exposure_time_absolute=%d" % p["exposure"],
        "focus_automatic_continuous=0", "focus_absolute=%d" % p["focus"],
        "white_balance_automatic=0", "white_balance_temperature=%d" % p["wb_kelvin"])


def grab(p, settle=10):
    c = cv2.VideoCapture(0, cv2.CAP_V4L2)
    c.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    c.set(cv2.CAP_PROP_FRAME_WIDTH, p["width"]); c.set(cv2.CAP_PROP_FRAME_HEIGHT, p["height"])
    for _ in range(2):
        c.read()       # measured: focus resets to its default (370) when streaming starts, so apply AFTER the stream is up
    apply(p)
    time.sleep(0.8)
    for _ in range(settle):
        c.read()
    ok, f = c.read(); c.release()
    assert ok, "no frame"
    return f


def detect(img):
    """inverted DICT_4X4_50, ids 0-4 only (a wide threshold search yields spurious ids)"""
    p = cv2.aruco.DetectorParameters(); p.detectInvertedMarker = True
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    # measured 10/10 vs 4/10 with defaults: tile 2 sits at the default adaptive-threshold edge
    p.adaptiveThreshConstant = 3
    p.adaptiveThreshWinSizeMax, p.adaptiveThreshWinSizeStep = 63, 6
    g = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    c, ids, _ = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), p).detectMarkers(g)
    if ids is None:
        return {}
    return {int(i): q[0] for q, i in zip(c, ids.flatten()) if int(i) in IDS}


def sharp(img, rois):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float(np.mean([cv2.Laplacian(g[y0:y1, x0:x1], cv2.CV_64F).var() for x0, y0, x1, y1 in rois]))


def rois_from(det, half=150):
    r = []
    for q in det.values():
        cx, cy = q.mean(0)
        r.append((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
    return r


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "apply"
    p = profile()
    if cmd == "apply":
        apply(p)
        print(json.dumps(p))
    elif cmd == "capture":
        f = grab(p)
        cv2.imwrite(sys.argv[2], f)
        det = detect(f)
        side = np.mean([np.linalg.norm(q[k] - q[(k + 1) % 4]) for q in det.values() for k in range(4)]) if det else 0
        print("markers", sorted(det), "mean side %.1f px" % side, "profile", json.dumps(p))
        sys.exit(0 if set(det) == IDS else 2)
    elif cmd == "sweep-focus":
        det = detect(grab(p))
        assert set(det) == IDS, "need all 5 markers to sweep focus, got %s" % sorted(det)
        rois, best = rois_from(det), (-1, None)
        for fo in range(0, 1024, 32):
            s = sharp(grab({**p, "focus": fo}, settle=6), rois)
            print("focus %4d sharpness %.1f" % (fo, s), flush=True)
            if s > best[0]:
                best = (s, fo)
        p["focus"] = best[1]
        PROFILE.write_text(json.dumps(p, indent=1))
        print("BEST focus", best[1], "sharpness %.1f" % best[0], "-> written", PROFILE)


if __name__ == "__main__":
    main()
