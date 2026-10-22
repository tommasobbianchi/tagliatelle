"""L6 Contour service — workpiece contour from the camera image.

Pipeline position (MASTER-DEV-PROMPT §6): camera image (home pose, after
registration) -> segment in pixels -> camera→plane homography (3x3, ArUco,
already measured by L5) -> polygon in bed mm for ``Workpiece2.contour_mm``.

Design decisions:
- **Classical OpenCV is the default** path; it is also the cross-check for the
  segmentation model (which runs on nativedev, images stay local).
- The model is a **later add**: today only the ``ModelSegmenter`` interface
  exists; ``extract_contour_px(image, method="model")`` with no configured
  model raises a clear ContourError instead of pretending.
- Deterministic: fixed kernels, fixed thresholds, no randomness.
- Confidence: degenerate results (empty / <3 points / implausible area or
  extent) are reported by ``contour_confidence`` so the UI can offer the
  user's manual correction (corrected contour is frozen, flagged ``modified``).

No AI-provider imports (project rule).
"""
from __future__ import annotations

import abc

import cv2
import numpy as np


class ContourError(ValueError):
    """Contour service error (bad input, or model method without a model)."""


# ---- tunables (deterministic; measured on real material later, §6) ----

# Gaussian kernel for noise suppression (odd, as required by OpenCV).
_BLUR_KERNEL = (5, 5)
# polarity heuristics: if the foreground covers more than half the frame the
# threshold fired on the background — the workpiece must leave background.
_POLARITY_SWAP_RATIO = 0.5
# approxPolyDP epsilon as a fraction of arc length.
_EPS_FACTOR = 0.005
# plausibility of the workpiece as a fraction of the image area.
_MIN_AREA_RATIO = 1e-3     # smaller than 0.1% of the frame: noise, not a workpiece
_MAX_AREA_RATIO = 0.99     # larger than 99%: the object fills the frame, suspect

# confidence tiers (low < these < high)
_CONTOUR_MIN_POINTS = 3
_EXTENT_TOL_PX = 0.5


class ModelSegmenter(abc.ABC):
    """Interface for the local segmentation model (a later L6 add, §6).

    A concrete implementation runs the model on nativedev and returns a
    binary mask of the same size as the input image:

    - 2-D array, shape (H, W) matching the image
    - dtype uint8, values 255 where the workpiece is, 0 elsewhere
    """

    @abc.abstractmethod
    def segment(self, image_bgr: np.ndarray) -> np.ndarray:
        """Return the binary workpiece mask (uint8, 0/255) for a BGR image."""


# ------------------------------ inputs ------------------------------


def _validate_image(image_bgr: np.ndarray) -> None:
    if not isinstance(image_bgr, np.ndarray):
        raise ContourError("expected a numpy BGR image (3-channel uint8 array)")
    if image_bgr.ndim != 3 or image_bgr.shape[2] != 3:
        raise ContourError("expected a 3-channel BGR image, got shape %r" % (image_bgr.shape,))
    if image_bgr.dtype != np.uint8:
        raise ContourError("expected uint8 image, got dtype %r" % image_bgr.dtype)


def _validate_mask(mask: np.ndarray) -> None:
    if not isinstance(mask, np.ndarray) or mask.ndim != 2 or mask.dtype != np.uint8:
        raise ContourError("mask must be a 2-D uint8 array (H x W)")


# ------------------------------ classical path ------------------------------


def _classical_mask(image_bgr: np.ndarray) -> np.ndarray:
    """grayscale -> blur -> Otsu threshold; fixed polarity (workpiece = 255).

    Otsu (deterministic, parameter-free) separates the bimodal photo
    (workpiece vs bed background) and — unlike a mean-C adaptive threshold —
    has no flat-region artefact on a uniform dark bed. The polarity is
    verified heuristically: if the foreground covers more than half the frame
    the threshold fired on the background; we invert.
    """
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, _BLUR_KERNEL, 0)
    _, mask = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if float(np.count_nonzero(mask)) / mask.size > _POLARITY_SWAP_RATIO:
        mask = cv2.bitwise_not(mask)
    return mask


def _model_mask(image_bgr: np.ndarray, model: ModelSegmenter | None) -> np.ndarray:
    if model is None:
        raise ContourError(
            "model not configured: method='model' requires a ModelSegmenter "
            "instance; the local segmentation model is a later L6 add (runs on "
            "nativedev). Use method='classical' (the OpenCV fallback)."
        )
    if not isinstance(model, ModelSegmenter):
        raise ContourError("model must be a ModelSegmenter instance, got %r" % type(model).__name__)
    mask = model.segment(image_bgr)
    _validate_mask(mask)
    if mask.shape[:2] != image_bgr.shape[:2]:
        raise ContourError("mask shape %r does not match image shape %r"
                           % (mask.shape, image_bgr.shape[:2]))
    masked = np.where(mask > 0, np.uint8(255), np.uint8(0))
    return masked


def _largest_contour_px(mask: np.ndarray, eps_factor: float) -> list[tuple[float, float]]:
    """Largest external contour of the mask, simplified, as ordered (x, y) px.

    Returns [] when nothing meaningful is found (degenerate input); callers
    check that and report low confidence via ``contour_confidence``.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)          # deterministic: max area
    if cv2.contourArea(largest) < 3.0:                      # sub-pixel speck: noise
        return []
    simplified = cv2.approxPolyDP(largest, eps_factor * cv2.arcLength(largest, True), True)
    return [(float(p[0][0]), float(p[0][1])) for p in simplified]


# ------------------------------ public API ------------------------------


def extract_contour_px(
    image_bgr: np.ndarray,
    method: str = "classical",
    model: ModelSegmenter | None = None,
) -> list[tuple[float, float]]:
    """Extract the outer workpiece contour as an ordered list of (x, y) pixels.

    ``method``:
      - ``"classical"`` (default, offline, deterministic): grayscale -> blur ->
        Otsu threshold (polarity checked) -> largest external contour -> approxPolyDP.
      - ``"model"``: segment with a configured ``ModelSegmenter`` and use the
        same contour extraction on the mask. ``model=None`` (the default, the
        interface is a later add) raises ContourError with a clear message.

    Returns an empty list on degenerate input (nothing found) — check with
    ``contour_confidence``.
    """
    _validate_image(image_bgr)
    if method == "classical":
        mask = _classical_mask(image_bgr)
    elif method == "model":
        mask = _model_mask(image_bgr, model)
    else:
        raise ContourError("unknown method %r (expected 'classical' or 'model')" % method)
    return _largest_contour_px(mask, _EPS_FACTOR)


def contour_px_to_mm(
    contour_px: list[tuple[float, float]],
    homography: np.ndarray | list,
) -> list[tuple[float, float]]:
    """Map a pixel contour into bed millimetres with the camera→plane homography.

    ``homography`` is a 3x3 matrix (numpy array or nested list) such that
    ``[x_mm, y_mm, 1] ∝ H @ [x_px, y_px, 1]`` (the ArUco-registered map from L5).
    """
    H = np.asarray(homography, dtype=np.float64)
    if H.shape != (3, 3):
        raise ContourError("homography must be 3x3, got shape %r" % (H.shape,))
    if not np.all(np.isfinite(H)):
        raise ContourError("homography must be finite")
    if not contour_px:
        return []
    pts = np.asarray(contour_px, dtype=np.float64).reshape(-1, 2)
    if not np.all(np.isfinite(pts)):
        raise ContourError("contour contains non-finite coordinates")
    homog = np.column_stack([pts, np.ones(pts.shape[0], dtype=np.float64)])
    out = H @ homog.T                                # (3, N)
    denom = out[2]
    if np.any(np.abs(denom) < 1e-12):
        raise ContourError("homography maps a contour point to infinity (degenerate map)")
    mm = np.column_stack([out[0] / denom, out[1] / denom])
    return [(float(x), float(y)) for x, y in mm]


def contour_confidence(contour_px: list[tuple[float, float]], image_shape: tuple) -> float:
    """Deterministic confidence in ``[0, 1]`` for a px contour in an image.

    Tiers:
      - 0.0  degenerate: empty or fewer than 3 points (definitely re-draw);
      - 0.1  out of bounds or implausibly small (less than 0.1% of the frame);
      - 0.3  plausible but suspicious: covers more than 99% of the frame;
      - 1.0  a well-behaved workpiece contour.

    Not a probability — a rule-based score, so a low value always has a reason
    the UI can show ("too small", "out of frame", "no contour found").
    """
    try:
        h, w = image_shape[:2]
    except (TypeError, ValueError, IndexError):
        raise ContourError("image_shape must give (H, W[, C])")
    if not contour_px or len(contour_px) < _CONTOUR_MIN_POINTS:
        return 0.0
    pts = np.asarray(contour_px, dtype=np.float64).reshape(-1, 2)
    if (pts < -_EXTENT_TOL_PX).any() or (pts[:, 0] > w + _EXTENT_TOL_PX).any() \
            or (pts[:, 1] > h + _EXTENT_TOL_PX).any():
        return 0.1
    area = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        area += x0 * y1 - x1 * y0
    area = abs(area) / 2.0
    ratio = area / float(h * w)
    if ratio <= _MIN_AREA_RATIO:
        return 0.1
    if ratio >= _MAX_AREA_RATIO:
        return 0.3
    return 1.0
