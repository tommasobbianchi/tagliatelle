"""Pi-camera lens distortion calibration with the ChArUco card (identified from a photo, 2026-10-14):
CharucoBoard((11, 9), square 20 mm, marker 10 mm, DICT_4X4_50), 49 markers, 80 inner corners.
(Its marker ids 0-48 overlap the bed tiles' ids 0-4: take the card off the bed before running calib.py.)

  lens.py capture [N] [SEC]  grab N frames (default 20) SEC apart (default 8) with the card moved/tilted between shots
  lens.py shot               one frame, kept if the card is found; prints corner count and where it sits in the image
  lens.py solve              cv2.calibrateCamera on the kept frames -> lens.json (K, dist, rms), prints the worst
                             displacement at the image corners in px and mm
undistort() is used by calib.py when lens.json exists (full-resolution frames only).
K and dist do not depend on the printed square size (they are in pixels); only the pose scale does.
"""
import glob, json, sys, time
from pathlib import Path
import cv2, numpy as np

HERE = Path(__file__).parent
LENS = HERE / "lens.json"
SHOTS = Path("/tmp/lens")
MIN_CORNERS = 12


def board():
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return cv2.aruco.CharucoBoard((11, 9), 20.0, 10.0, d)


def undistort(img):
    """Undistort a full-resolution frame with lens.json; no-op if there is no calibration or the size differs."""
    if not LENS.exists():
        return img
    d = json.loads(LENS.read_text())
    if img.shape[1] != d["w"] or img.shape[0] != d["h"]:
        return img
    return cv2.undistort(img, np.array(d["K"]), np.array(d["dist"]))


def find(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    cc, ci, _, _ = cv2.aruco.CharucoDetector(board()).detectBoard(g)
    return (cc, ci) if ci is not None and len(ci) >= MIN_CORNERS else None


def capture(n=20, sec=8):
    import camera
    SHOTS.mkdir(exist_ok=True)
    p, kept = camera.profile(), 0
    for i in range(n):
        time.sleep(sec)
        f = camera.grab(p)
        r = find(f)
        if r is not None:
            cv2.imwrite(str(SHOTS / ("%02d.png" % kept)), f)
            kept += 1
        print("shot %d/%d: %s (kept %d)" % (i + 1, n, "%d corners" % len(r[1]) if r else "NO board", kept), flush=True)


def shot():
    import camera
    SHOTS.mkdir(exist_ok=True)
    f = camera.grab(camera.profile())
    r = find(f)
    n = len(glob.glob(str(SHOTS / "*.png")))
    if r is None:
        print("NO card found (kept %d)" % n)
        return
    cv2.imwrite(str(SHOTS / ("%02d.png" % n)), f)
    xy = r[0].reshape(-1, 2)
    h, w = f.shape[:2]
    print("kept #%d: %d corners, x %.0f-%.0f%% y %.0f-%.0f%% of the frame (centre %.0f%%,%.0f%%)" %
          (n + 1, len(r[1]), 100 * xy[:, 0].min() / w, 100 * xy[:, 0].max() / w, 100 * xy[:, 1].min() / h,
           100 * xy[:, 1].max() / h, 100 * xy[:, 0].mean() / w, 100 * xy[:, 1].mean() / h))


def solve():
    b, obj, imgp, size = board(), [], [], None
    for f in sorted(glob.glob(str(SHOTS / "*.png"))):
        im = cv2.imread(f)
        r = find(im)
        if r is None:
            continue
        o, i = b.matchImagePoints(r[0], r[1])
        obj.append(o); imgp.append(i); size = (im.shape[1], im.shape[0])
    assert len(obj) >= 8, "need >= 8 frames with the card found, have %d" % len(obj)
    # k3 fixed at 0: the free k3 term is unconstrained beyond the card's coverage (measured: shift jumps to 41 mm at r=1800 px)
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, imgp, size, None, None, flags=cv2.CALIB_FIX_K3)
    w, h = size
    pts = np.array([[0, 0], [w - 1, 0], [0, h - 1], [w - 1, h - 1], [w / 2, h / 2]], np.float32).reshape(-1, 1, 2)
    shift = np.linalg.norm(cv2.undistortPoints(pts, K, dist, P=K).reshape(-1, 2) - pts.reshape(-1, 2), axis=1)
    LENS.write_text(json.dumps({"K": K.tolist(), "dist": dist.ravel().tolist(), "rms_px": float(rms), "w": w, "h": h,
                                "n_frames": len(obj)}, indent=1))
    print("frames %d, reprojection rms %.3f px" % (len(obj), rms))
    print("K fx=%.1f fy=%.1f cx=%.1f cy=%.1f" % (K[0, 0], K[1, 1], K[0, 2], K[1, 2]))
    print("dist", np.round(dist.ravel(), 5).tolist())
    print("displacement by undistortion at TL,TR,BL,BR,centre: %s px  (~%s mm at 6.66 px/mm)" %
          (np.round(shift, 1).tolist(), np.round(shift / 6.66, 1).tolist()))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "capture":
        capture(int(sys.argv[2]) if len(sys.argv) > 2 else 20, float(sys.argv[3]) if len(sys.argv) > 3 else 8)
    elif cmd == "shot":
        shot()
    elif cmd == "solve":
        solve()
    else:
        print(__doc__)
