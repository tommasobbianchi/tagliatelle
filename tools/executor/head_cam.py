"""Head (laser) camera calibration against the Pi-calibrated bed frame.
The tiles' bed-mm corners come from calib.json (learned by the Pi camera at the home pose, screw-referenced);
the head camera sees the same tiles from its capture pose (X186 Y130 Z220), so  px -> bed mm  is a homography fit on
the tile corners.  Needs >= 3 mapped tiles (4 for the leave-one-out outlier check); the tiles must not have moved
since `calib.py calibrate`.

  head_cam.py calibrate [IMG]    default IMG=/tmp/laser_cam_new.jpg ; writes head_calib.json (H, rms, scale, ids)
Lens distortion of the head camera is NOT corrected (needs card shots from this pose); the residual below includes it.
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
import camera

HERE = Path(__file__).parent
REF = HERE / "calib.json"
OUT = HERE / "head_calib.json"


def calibrate(img):
    ref = json.loads(REF.read_text())["tiles"]
    det = camera.detect(img)
    ids = sorted(set(det) & {int(k) for k in ref})
    assert len(ids) >= 3, "need >= 3 mapped tiles in the head image, got %s (all detected: %s)" % (ids, sorted(det))
    px = {i: det[i].astype(np.float32) for i in ids}
    mm = {i: np.array(ref[str(i)]["corners_mm"], np.float32) for i in ids}

    def fit(use):
        H, _ = cv2.findHomography(np.vstack([px[i] for i in use]), np.vstack([mm[i] for i in use]), 0)
        return H

    def err(H, i):
        return np.linalg.norm(cv2.perspectiveTransform(px[i][None], H)[0] - mm[i], axis=1)

    H = fit(ids)
    e = np.concatenate([err(H, i) for i in ids])
    loo = {i: round(float(err(fit([j for j in ids if j != i]), i).max()), 3) for i in ids} if len(ids) >= 4 else {}
    # scale: mean tile side in head-image px / mm map side
    side_px = np.mean([np.linalg.norm(px[i][k] - px[i][(k + 1) % 4]) for i in ids for k in range(4)])
    side_mm = np.mean([np.linalg.norm(mm[i][k] - mm[i][(k + 1) % 4]) for i in ids for k in range(4)])
    r = {"ids": ids, "missed": sorted(set(int(k) for k in ref) - set(ids)), "rms_mm": round(float(np.sqrt((e ** 2).mean())), 3),
         "max_mm": round(float(e.max()), 3), "loo_mm": loo, "px_per_mm": round(float(side_px / side_mm), 3),
         "image_wh": [int(img.shape[1]), int(img.shape[0])], "H": H.tolist()}
    return r


if __name__ == "__main__":
    img = cv2.imread(sys.argv[2] if len(sys.argv) > 2 else "/tmp/laser_cam_new.jpg")
    r = calibrate(img)
    OUT.write_text(json.dumps(r, indent=1))
    print({k: v for k, v in r.items() if k != "H"})
    print("wrote", OUT)
