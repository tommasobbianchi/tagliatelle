"""A1 · Importing files — the deterministic, offline core acceptance of TaglIAtelle A1.

Pipeline (SPEC §10 A1): a coloured *inline* SVG → *operation proposal* (§4.2 work order) →
Job Spec 0.3.0 → resolve (identity for A1) → compile (``compiler2``) → gate → G-code, whose
sha256 is pinned here (mirrors ``test_golden_gcode``).

Hermetic by construction (SPEC principles): every fixture is an *inline* SVG string (no
network, no external files on disk), the pipeline is pure (no randomness / wall-clock / I/O),
and the post-gate import graph must stay free of any AI provider (asserted below).

Regenerating the golden (only after the change is *intended* and reviewed):
    python3 -m test_import_svg --regen
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

CORE = Path(__file__).resolve().parent
import import_svg as I  # noqa: E402  (core/ is on sys.path when running `pytest core/`)

# --------------------------------------------------------------------------- #
# fixtures — inline SVG strings (the whole point: nothing is read from disk) #
# --------------------------------------------------------------------------- #
# The pinned golden: 2-colour + a fill, mm-anchored (width in mm → scale = 1.0).
# red = outer cut / outer contour, black = engrave, grey = fill (a circle).
GOLDEN_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 90" width="120mm" height="90mm">'
    '<rect x="10" y="10" width="100" height="70" fill="#ff0000"/>'
    '<rect x="30" y="30" width="30" height="20" fill="#000000"/>'
    '<circle cx="60" cy="60" r="6" fill="#808080"/></svg>'
)
GOLDEN_PALETTE = {"#000000": "engrave", "#ff0000": "cut", "#808080": "fill"}
GOLDEN_MATERIAL = {"id": "plywood_3", "category": "safe"}

# 2-colour fixture for parse / palette / determinism / differing-colour checks.
TWO_COLOUR_SVG = (
    '<svg viewBox="0 0 100 100">'
    '<rect x="5" y="5" width="90" height="80" fill="#ff0000"/>'
    '<rect x="30" y="30" width="20" height="20" fill="#000000"/></svg>'
)

# §4.2 ordering fixture: an engrave, a fill, and TWO cuts (a small inner + a big outer).
ORDER_SVG = (
    '<svg viewBox="0 0 200 200">'
    '<rect x="10" y="10" width="180" height="160" fill="#ff0000"/>'   # outer cut (largest closed cut)
    '<rect x="40" y="40" width="40" height="40" fill="#cc0000"/>'     # inner cut (smaller)
    '<rect x="80" y="80" width="20" height="15" fill="#000000"/>'    # engrave
    '<circle cx="160" cy="160" r="10" fill="#808080"/>'                 # fill (circle → bbox 20)
)
ORDER_PALETTE = {
    "#ff0000": "cut", "#cc0000": "cut",   # the two cut layers
    "#000000": "engrave", "#808080": "fill",
}

# Open-path rule (A1): a *minimal* closing gap auto-closes (flagged); a *large* gap stays
# open and is highlighted rather than silently closed. Both must remain in the structure.
OPEN_SMALL = '<svg><path d="M 0 0 L 3 0 L 3 3" fill="#000000"/></svg>'    # gap = 3  (<= 5) → auto-close
OPEN_LARGE = '<svg><path d="M 0 0 L 5 0 L 5 50" fill="#000000"/></svg>'   # gap = 50 (> 5) → highlight

# Dimensions: `width` explicit in mm fixes the scale exactly; bare px falls back to 96 dpi.
DIMS_MM = '<svg viewBox="0 0 100 200" width="100mm" height="200mm"/>'
DIMS_PX = '<svg viewBox="0 0 100 200" width="100" height="200"/>'

# Determinism: two SVGs identical except one fill colour → different spec → different hash.
A_COLOUR = '<svg viewBox="0 0 50 50"><rect x="5" y="5" width="40" height="30" fill="#ff0000"/></svg>'
B_COLOUR = '<svg viewBox="0 0 50 50"><rect x="5" y="5" width="40" height="30" fill="#000000"/></svg>'

# Gate: this cut's 50% power exceeds the *risky* category cap (40%) → must block.
RISKY_MATERIAL = {"id": "acrylic_dark_3", "category": "risky"}

# ----------------------------------------------------------------------------
# golden (pinned) — re-emit must reproduce it


def _golden_hash() -> str:
    return I.a1_golden_hash(GOLDEN_SVG, palette=GOLDEN_PALETTE, material=GOLDEN_MATERIAL)


GOLDEN_SHA256 = "191c5ce518b222839430d88a6a3af649f37cbbfa5ddd9c38d4ebea0fc515836b"


# ===========================================================================
# 1. parsing — 2 colours group cleanly
# ===========================================================================
def test_two_colour_parsing():
    layers = I.parse_svg_layers(TWO_COLOUR_SVG)
    assert [l.color for l in layers] == ["#ff0000", "#000000"]
    assert all(len(l.paths) >= 1 for l in layers)
    # every layer colour is normalised to lower-case #rrggbb and hex-valid
    assert all(re.fullmatch(r"#(?:[0-9a-f]{6})", l.color) for l in layers)


def test_is_colour_in_palette():
    pal = GOLDEN_PALETTE
    assert I.is_colour_in_palette("#000000", pal) is True
    assert I.is_colour_in_palette("#FF0000", pal) is True   # case-insensitive
    assert I.is_colour_in_palette("#123456", pal) is False  # not mapped
    assert I.is_colour_in_palette("green", pal) is False     # not hex


# ===========================================================================
# 2. open-path rule — small gap auto-closes, large gap highlighted; both kept
# ===========================================================================
def test_open_path_rules_auto_close_small_gap():
    op = I.propose_operations(I.parse_svg_layers(OPEN_SMALL))[0]
    assert 0 in op.auto_closed_idxs                                   # flagged auto-closed
    assert 0 not in op.highlight_open_idxs
    assert len(op.paths) == 1 and op.paths[0].closed is True          # still in the structure, now closed


def test_open_path_rules_highlight_large_gap():
    op = I.propose_operations(I.parse_svg_layers(OPEN_LARGE))[0]
    assert 0 in op.highlight_open_idxs                                 # left open + flagged for the user
    assert 0 not in op.auto_closed_idxs
    assert len(op.paths) == 1 and op.paths[0].closed is False          # NOT silently closed


# ===========================================================================
# 3. §4.2 work order — engrave/fill → inner cuts → outer contour (last), exact
# ===========================================================================
def test_work_order_engrave_fill_then_inner_cuts_then_outer_last():
    ordered = I.order_operations(I.propose_operations(I.parse_svg_layers(ORDER_SVG), ORDER_PALETTE))
    got = [(o.op, o.color) for o in ordered]
    want = [
        ("engrave", "#000000"),     # engrave first
        ("fill",    "#808080"),     # then fill
        ("cut",     "#cc0000"),     # then the inner cut
        ("cut",     "#ff0000"),     # the outer contour — the largest closed cut — LAST
    ]
    assert got == want, "§4.2 order violated: %r != %r" % (got, want)


def test_work_order_flags_exactly_one_outer_contour_last():
    ordered = I.order_operations(I.propose_operations(I.parse_svg_layers(ORDER_SVG), ORDER_PALETTE))
    assert sum(1 for o in ordered if o.is_outer_contour) == 1          # exactly one outer contour
    assert ordered[-1].is_outer_contour is True                        # and it is the last operation
    assert all(o.is_outer_contour is False for o in ordered[:-1])


# ===========================================================================
# 4. dimensions — known viewBox → mm and a deterministic px→mm scale
# ===========================================================================
def test_deduce_dimensions_mm_fixed_scale():
    w_mm, h_mm, scale = I.deduce_dimensions(DIMS_MM)
    assert scale == 1.0                 # width="100mm" over viewBox width 100
    assert (w_mm, h_mm) == (100.0, 200.0)


def test_deduce_dimensions_bare_px_96dpi_fallback():
    w_mm, h_mm, scale = I.deduce_dimensions(DIMS_PX)
    assert scale == I.PX_TO_MM == 25.4 / 96.0
    assert abs(w_mm - 100.0 * (25.4 / 96.0)) < 1e-9
    assert abs(h_mm - 200.0 * (25.4 / 96.0)) < 1e-9


# ===========================================================================
# 5. §4.2 "visible numbers" — each op carries its own power/speed/passes in the G-code
# ===========================================================================
def test_visible_numbers_per_op_present_in_gcode():
    from compiler2 import compile_jobspec2
    spec = I.svg_to_jobspec(GOLDEN_SVG, palette=GOLDEN_PALETTE, material=GOLDEN_MATERIAL)
    gcode = compile_jobspec2(spec)
    # per-op laser parameters are deterministically visible (engrave 30%/3000, fill 40%/2000, cut 50%/1200)
    assert "S77" in gcode and "F3000" in gcode    # engrave power + speed
    assert "S102" in gcode and "F2000" in gcode   # fill power + speed
    assert "S128" in gcode and "F1200" in gcode   # cut power + speed


# ===========================================================================
# 6. determinism + differing colour + golden re-emit
# ===========================================================================
def test_determinism_same_svg_same_hash():
    assert _golden_hash() == _golden_hash()
    assert I.a1_golden_hash(GOLDEN_SVG) == I.a1_golden_hash(GOLDEN_SVG)


def test_different_colour_different_hash():
    assert I.a1_golden_hash(A_COLOUR) != I.a1_golden_hash(B_COLOUR)


def test_golden_reproduces_pinned_sha256():
    assert _golden_hash() == GOLDEN_SHA256, (
        "golden drifted; rerun `python3 -m test_import_svg --regen` only if intended"
    )


def test_svg_to_jobspec_is_a_valid_030_spec():
    from jobspec2 import JobSpec2
    spec = I.svg_to_jobspec(GOLDEN_SVG, palette=GOLDEN_PALETTE, material=GOLDEN_MATERIAL)
    assert isinstance(spec, JobSpec2)
    assert spec.schema_version == "0.3.0" and spec.module == "laser_405"
    assert spec.material.category == "safe"


# ===========================================================================
# 7. gate — blocked jobs raise A1GateBlocked with the blocker list
# ===========================================================================
def test_gate_blocks_risky_material_and_raises_with_blockers():
    try:
        I.a1_golden_hash(GOLDEN_SVG, palette=GOLDEN_PALETTE, material=RISKY_MATERIAL)
    except I.A1GateBlocked as e:
        assert e.blockers, "A1GateBlocked must carry a non-empty blocker list"
        assert any("cap" in b for b in e.blockers), e.blockers
    else:
        raise AssertionError("a risky material (cut 50% > 40% cap) must be blocked by the A1 gate")


def test_safe_material_passes_gate():
    h = I.a1_golden_hash(GOLDEN_SVG, palette=GOLDEN_PALETTE, material=GOLDEN_MATERIAL)
    assert re.fullmatch(r"[0-9a-f]{64}", h)


# ===========================================================================
# 8. offline + no AI provider (hermetic) — import_svg must be pure
# =========================================================================== #
FORBIDDEN = ("openai", "anthropic", "transformers", "torch", "ollama", "langchain")
_FORBIDDEN_RE = re.compile(r"\b(?:" + "|".join(FORBIDDEN) + r")\b")


def test_no_ai_provider_in_source():
    src = (CORE / "import_svg.py").read_text()
    m = _FORBIDDEN_RE.search(src)
    assert m is None, "AI-provider reference in import_svg: %r" % (m.group(0) if m else None)


def test_importing_does_not_load_forbidden_modules():
    before = set(sys.modules)
    importlib.import_module("import_svg")       # importing is itself the assertion: it must work offline
    new = set(sys.modules) - before
    bad = [mod for mod in sorted(new) for f in FORBIDDEN if mod == f or mod.startswith(f + ".")]
    assert not bad, "import_svg pulled in AI-provider modules: %s" % bad


# --------------------------------------------------------------------------- #
# CLI: regenerate the pinned golden (only after an intended, reviewed change) —
# and run this file as a standalone test module.
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    if "--regen" in sys.argv:
        print(_golden_hash())
        raise SystemExit(0)
    raise SystemExit(__import__("pytest").main([__file__, "-v"]))
