"""Pi-camera calibration: the 4 permanent bed-corner screws (234 mm along machine X x 257 mm along machine Y,
measured by the user) give a pixel -> bed-mm homography; the ArUco tiles are then measured in that frame
(centre + side, side checked against the caliper value 29.94 mm) and stored as the per-job registration map.

  calib.py calibrate [--image F]   screws -> H, tiles -> tile map, writes calib.json   (needs all 4 corner screws in view,
                                   i.e. bed near home: Y>=~200; at Y=130 the right-hand screws leave the frame)
  calib.py register [--image F]    job gate: homography from the stored tile corners, residual check, exit 0 ok / 2 blocked
                                   env REG_RMS_MM (default 0.5) and REG_MAX_MM (default 1.0) are the thresholds (spec decision)
Bed frame: a = mm along image-horizontal = machine Y direction (0..257), b = mm along image-vertical = machine X (0..234).
Not corrected: lens distortion (needs a checkerboard); homography is exact only for the screw plane.
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
import camera, lens

OUT = Path(__file__).with_name("calib.json")
A_MM, B_MM = 257.0, 234.0           # corner-screw spacing (user): along image-x (Y axis), along image-y (X axis)
TILE_MM = 29.94                     # caliper, printed marker side


def screws(gray):
    """bright round blobs (screw heads) via top-hat, at several thresholds (corner screws differ in brightness)"""
    s = gray.shape[1] / 3264.0
    f = (s / 0.5) ** 2                      # areas below were measured on a 1632 px wide frame
    k = int(41 * s * 2) | 1
    th = cv2.morphologyEx(cv2.GaussianBlur(gray, (3, 3), 0), cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    out = []
    for thr in (45, 30, 20):
        n, _, st, cen = cv2.connectedComponentsWithStats((th > thr).astype(np.uint8))
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if 220 * f <= a <= 700 * f and 0.7 < w / h < 1.5 and a / (w * h) > 0.5:
                if all(np.linalg.norm(cen[i] - o) > 8 * s * 2 for o in out):
                    out.append(cen[i])
    return np.array(out)


def corner_screws(gray):
    """TL, TR, BR, BL: the LARGEST quad of screw blobs that is a parallelogram with the known aspect
    (the 2x2 inner screws also qualify, hence 'largest'; stray bright blobs do not form a parallelogram)."""
    from itertools import permutations
    p = screws(gray)
    assert len(p) >= 4, "found %d screw-like blobs" % len(p)
    best, tol = None, 0.025 * gray.shape[1]
    sc = gray.shape[1] / 3264.0
    for tl, tr, br, bl in permutations(range(len(p)), 4):
        TL, TR, BR, BL = p[tl], p[tr], p[br], p[bl]
        if not (TL[0] < TR[0] and BL[0] < BR[0] and TL[1] < BL[1] and TR[1] < BR[1]):
            continue
        if np.linalg.norm(TL + BR - TR - BL) > tol:
            continue
        w = (np.linalg.norm(TR - TL) + np.linalg.norm(BR - BL)) / 2
        h = (np.linalg.norm(BL - TL) + np.linalg.norm(BR - TR)) / 2
        if abs(w / h - A_MM / B_MM) > 0.04:
            continue
        if not 6.0 <= (w / A_MM) / sc <= 7.3:     # the camera is ~6.65 px/mm at the bed plane (measured)
            continue
        if best is None or w * h > best[0]:
            best = (w * h, np.array([TL, TR, BR, BL], np.float32))
    assert best, "no corner-screw quad with aspect %.2f among %d blobs: screws out of frame or hidden" % (A_MM / B_MM, len(p))
    return best[1]


def load(argv):
    if "--image" in argv:
        return lens.undistort(cv2.imread(argv[argv.index("--image") + 1]))
    return lens.undistort(camera.grab(camera.profile()))


def calibrate(img):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    c = corner_screws(g)
    H, _ = cv2.findHomography(c, np.array([[0, 0], [A_MM, 0], [A_MM, B_MM], [0, B_MM]], np.float32))
    tiles = {}
    for i, q in camera.detect(img).items():
        m = cv2.perspectiveTransform(q.astype(np.float32)[None], H)[0]
        sides = [np.linalg.norm(m[k] - m[(k + 1) % 4]) for k in range(4)]
        tiles[i] = {"centre_mm": [round(float(v), 2) for v in m.mean(0)], "side_mm": round(float(np.mean(sides)), 2),
                    "corners_mm": [[round(float(v), 2) for v in c] for c in m],
                    "side_spread_mm": round(float(np.ptp(sides)), 2)}
    return H, c, tiles


def register(img, rms_max=0.5, max_max=1.0):
    """Per-job registration: pixel -> bed-mm homography from the stored tile corners (needs >= 3 mapped tiles seen).
    Returns dict(ok, n, rms_mm, max_mm, per_tile{id: leave-one-out error mm}, H).  A moved tile shows up as an outlier."""
    ref = json.loads(OUT.read_text())["tiles"]
    det = camera.detect(img)
    ids = sorted(set(det) & {int(k) for k in ref})
    res = {"ok": False, "n": len(ids), "ids": ids, "rms_mm": None, "max_mm": None, "per_tile": {}, "H": None}
    if len(ids) < 3:
        res["why"] = "need >= 3 mapped tiles in view, got %s" % ids
        return res
    # detected corner order is the marker's own (TL,TR,BR,BL of the marker), same in calibration: stored in that order
    px = {i: det[i].astype(np.float32) for i in ids}
    mm = {i: np.array(ref[str(i)]["corners_mm"], np.float32) for i in ids}

    def fit(use):
        H, _ = cv2.findHomography(np.vstack([px[i] for i in use]), np.vstack([mm[i] for i in use]), 0)
        return H

    def err(H, i):
        return np.linalg.norm(cv2.perspectiveTransform(px[i][None], H)[0] - mm[i], axis=1)

    H = fit(ids)
    e = np.concatenate([err(H, i) for i in ids])
    res.update(rms_mm=round(float(np.sqrt((e ** 2).mean())), 3), max_mm=round(float(e.max()), 3), H=H.tolist())
    if len(ids) >= 4:                     # leave-one-out: how far does a tile sit from where the others predict it
        for i in ids:
            res["per_tile"][i] = round(float(err(fit([j for j in ids if j != i]), i).max()), 3)
    worst = max(res["per_tile"].values()) if res["per_tile"] else 0.0
    res["ok"] = res["rms_mm"] <= rms_max and res["max_mm"] <= max_max and worst <= max_max * 2
    if not res["ok"]:
        res["why"] = "rms %.3f/%.2f mm, max %.3f/%.2f mm, worst leave-one-out %.3f mm" % (res["rms_mm"], rms_max, res["max_mm"], max_max, worst)
    return res


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "calibrate"
    img = load(sys.argv)
    if cmd == "register":
        import os
        r = register(img, float(os.environ.get("REG_RMS_MM", 0.5)), float(os.environ.get("REG_MAX_MM", 1.0)))
        r.pop("H")
        print(json.dumps(r))
        sys.exit(0 if r["ok"] else 2)
    if cmd == "calibrate":
        H, c, tiles = calibrate(img)
        px_mm = np.mean([np.linalg.norm(c[1] - c[0]) / A_MM, np.linalg.norm(c[3] - c[2]) / A_MM,
                         np.linalg.norm(c[3] - c[0]) / B_MM, np.linalg.norm(c[2] - c[1]) / B_MM])
        print("corner screws (px) TL,TR,BR,BL:", c.round(1).tolist())
        print("scale %.3f px/mm (image width %d)" % (px_mm, img.shape[1]))
        for i, t in sorted(tiles.items()):
            print("tile %d centre_mm=%s side=%.2f mm (caliper %.2f, delta %+.2f) spread %.2f" %
                  (i, t["centre_mm"], t["side_mm"], TILE_MM, t["side_mm"] - TILE_MM, t["side_spread_mm"]))
        OUT.write_text(json.dumps({"H": H.tolist(), "px_per_mm": float(px_mm), "image_w": int(img.shape[1]),
                                   "tiles": tiles, "screw_spacing_mm": [A_MM, B_MM]}, indent=1))
        print("wrote", OUT)


if __name__ == "__main__":
    main()
