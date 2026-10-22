"""L6 Contour service — offline tests on synthetic OpenCV images.

All images are generated locally (filled shapes on a background), so the suite
runs with no camera, no model and no network.
"""
import numpy as np
import pytest

from contour import (
    ContourError,
    ModelSegmenter,
    contour_confidence,
    contour_px_to_mm,
    extract_contour_px,
)

# image: 600 px high x 800 px wide; workpiece: filled white rect
RECT = (200, 150, 600, 450)          # x0, y0, x1, y1 in px
CORNERS = [(200, 150), (600, 150), (600, 450), (200, 450)]
TOL = 6.0                            # px, threshold edge tolerance


def synthetic_rect() -> np.ndarray:
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    img[150:450, 200:600] = 255
    return img


def _corners_in(contour: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Points of the contour within TOL of at least one ideal corner, in
    contour order (a 4-vertex simplification must contain all four)."""
    found = []
    for p in contour:
        if any(abs(p[0] - cx) <= TOL and abs(p[1] - cy) <= TOL for cx, cy in CORNERS):
            found.append(p)
    found_set = set()
    out = []
    for p in found:                                        # keep one per ideal corner
        k = (round(p[0] / TOL), round(p[1] / TOL))
        if k not in found_set:
            found_set.add(k)
            out.append(p)
    return out


# ------------------------------ classical path ------------------------------


def test_synthetic_square_contour_matches_corners():
    contour = extract_contour_px(synthetic_rect())
    assert len(contour) >= 3
    assert len(_corners_in(contour)) == 4, "all four ideal corners must be captured"
    # ordered, non-self-crossing polygon: shoelace area must match the rect
    x0, y0, x1, y1 = RECT
    area = sum(contour[i][0] * contour[(i + 1) % len(contour)][1]
               - contour[(i + 1) % len(contour)][0] * contour[i][1] for i in range(len(contour)))
    assert abs(abs(area) / 2.0 - (x1 - x0) * (y1 - y0)) / ((x1 - x0) * (y1 - y0)) < 0.02


def test_synthetic_square_confidence_is_high():
    contour = extract_contour_px(synthetic_rect())
    assert contour_confidence(contour, (600, 800, 3)) > 0.9


def test_deterministic_repetition():
    img = synthetic_rect()
    assert extract_contour_px(img) == extract_contour_px(img)


def test_dark_object_on_bright_background_polarity_swapped():
    # black workpiece on a white bed: the Otsu polarity heuristic must invert
    img = np.full((600, 800, 3), 255, dtype=np.uint8)
    img[150:450, 200:600] = 0
    contour = extract_contour_px(img)
    assert len(_corners_in(contour)) == 4
    assert contour_confidence(contour, (600, 800, 3)) > 0.9


# ------------------------------ px -> mm ------------------------------


@pytest.mark.parametrize("homo,expected", [
    # identity: px and mm are the same numbers
    ([[1, 0, 0], [0, 1, 0], [0, 0, 1]], CORNERS),
    # scale 2 + pan (10, 20): the registration map in mm
    ([[2, 0, 10], [0, 2, 20], [0, 0, 1]],
     [(2 * x + 10, 2 * y + 20) for x, y in CORNERS]),
])
def test_px_to_mm(homo, expected):
    got = contour_px_to_mm(CORNERS, homo)
    assert got == [(float(x), float(y)) for x, y in expected]


def test_px_to_mm_accepts_numpy_homography():
    got = contour_px_to_mm([(10.0, 20.0)], np.eye(3))
    assert got == [(10.0, 20.0)]


def test_px_to_mm_rejects_bad_homography():
    with pytest.raises(ContourError):
        contour_px_to_mm(CORNERS, [[1, 0], [0, 1]])            # not 3x3
    with pytest.raises(ContourError):
        contour_px_to_mm(CORNERS, [[0, 0, 0], [0, 0, 0], [0, 0, 0]])  # degenerate
    # empty contour maps to empty contour
    assert contour_px_to_mm([], np.eye(3)) == []


# ------------------------------ model interface ------------------------------


class _RectModel(ModelSegmenter):
    """Stub segmentation model: a fixed binary mask with the same rect."""

    def segment(self, image_bgr):
        h, w = image_bgr.shape[:2]
        m = np.zeros((h, w), dtype=np.uint8)
        m[150:450, 200:600] = 255
        return m


def test_model_method_with_configured_model():
    contour = extract_contour_px(synthetic_rect(), method="model", model=_RectModel())
    assert len(_corners_in(contour)) == 4


def test_model_method_with_none_raises_clear_error():
    with pytest.raises(ContourError, match="model not configured"):
        extract_contour_px(synthetic_rect(), method="model")


def test_model_method_rejects_non_segmenter():
    with pytest.raises(ContourError):
        extract_contour_px(synthetic_rect(), method="model", model=object())


def test_unknown_method_raises():
    with pytest.raises(ContourError):
        extract_contour_px(synthetic_rect(), method="magic")


# ------------------------------ degenerate ------------------------------


def test_all_black_image_gives_empty_contour_and_low_confidence():
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    contour = extract_contour_px(img)
    assert contour == []
    assert contour_confidence(contour, (600, 800, 3)) == 0.0


def test_tiny_speck_is_low_confidence():
    img = np.zeros((600, 800, 3), dtype=np.uint8)
    img[300:304, 400:404] = 255              # 4x4 px speck, clearly not a workpiece
    contour = extract_contour_px(img)
    assert len(contour) in (0, 4)            # either dropped or reduced to 4 px points
    assert contour_confidence(contour, (600, 800, 3)) <= 0.1


def test_contour_out_of_bounds_is_low_confidence():
    bad = [(900.0, 100.0), (910.0, 100.0), (905.0, 110.0)]   # x beyond 800 px width
    assert contour_confidence(bad, (600, 800, 3)) <= 0.1


def test_contour_confidence_degenerate_inputs():
    assert contour_confidence([], (600, 800)) == 0.0
    assert contour_confidence([(0, 0)], (600, 800)) == 0.0
    assert contour_confidence([(0, 0), (10, 0), (10, 10)], (600, 800)) <= 0.1


# ------------------------------ input validation ------------------------------


@pytest.mark.parametrize("bad", [
    np.zeros((600, 800), dtype=np.uint8),            # 2-D, not BGR
    np.zeros((600, 800, 4), dtype=np.uint8),         # 4 channels
    np.zeros((600, 800, 3), dtype=np.float32),       # wrong dtype
])
def test_bad_images_rejected(bad):
    with pytest.raises(ContourError):
        extract_contour_px(bad)
