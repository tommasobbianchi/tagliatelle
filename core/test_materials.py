import pytest
from datetime import datetime

from materials import (
    VALID_CATEGORIES,
    POWER_CAP,
    Material,
    MaterialLibrary,
    power_cap,
    risk_block,
    similar_material,
    unlock,
    what_is_missing,
)


def test_seed_deterministic():
    a = MaterialLibrary.seed_defaults()
    b = MaterialLibrary.seed_defaults()
    assert a == b
    ids = [m.id for m in a]
    assert set(ids) >= {"plywood_3", "mdf_3", "cardboard_16", "leather_16", "acrylic_dark_3"}
    for m in a:
        assert m.category in VALID_CATEGORIES


def test_load_yaml_and_library(tmp_path):
    path = tmp_path / "materials.yaml"
    # The repo-YAML shape: a list of flat mappings; inline risk_flags list.
    path.write_text(
        "# seed copy — YAML in the repo is truth\n"
        "- id: plywood_3\n"
        "  name: Beech plywood 3mm\n"
        "  category: safe\n"
        "  thickness_mm: 3.0\n"
        "  colour: \"#b59b6b\"\n"
        "  wavelength_nm: 405\n"
        "- id: pvc_2\n"
        "  name: PVC 2mm\n"
        "  category: forbidden\n"
        "  thickness_mm: 2.0\n"
        "  colour: \"#ffffff\"\n"
        "  risk_flags: [chlorine, fumes]\n"
    )
    lib = MaterialLibrary.load_yaml(str(path))
    assert len(lib) == 2
    pvc = lib.get("pvc_2")
    assert pvc is not None
    assert pvc.category == "forbidden"
    assert pvc.risk_flags == ("chlorine", "fumes")
    assert "pvc_2" in lib and "plywood_3" in lib
    assert lib.get("nope") is None


# --------------------------------------------------------------------------- #
# power cap
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("cat,cap", [("safe", 60.0), ("risky", 40.0), ("forbidden", 0.0)])
def test_power_cap_per_category(cat, cap):
    assert power_cap(cat) == cap
    assert 0.0 <= cap <= 100.0


def test_power_cap_forbidden_is_zero():
    assert power_cap("forbidden") == POWER_CAP["forbidden"] == 0.0


def test_power_cap_unknown_raises():
    with pytest.raises(ValueError):
        power_cap("metal")


# --------------------------------------------------------------------------- #
# similarity
# --------------------------------------------------------------------------- #
def test_similar_returns_close_match():
    lib = MaterialLibrary.from_seed()
    # Exact plywood profile -> plywood, uniquely.
    q = {"id": "query", "category": "safe", "thickness_mm": 3.0, "colour": "#b59b6b"}
    assert similar_material(lib, q).id == "plywood_3"


def test_similar_none_when_nothing_close():
    lib = MaterialLibrary.from_seed()
    # No risky material with this thickness/colour is close enough.
    q = {"id": "q", "category": "risky", "thickness_mm": 12.0, "colour": "#ffffff"}
    assert similar_material(lib, q) is None
    # forbidden is not seeded at all -> no close match.
    q2 = {"id": "q2", "category": "forbidden", "thickness_mm": 3.0, "colour": "#20242a"}
    assert similar_material(lib, q2) is None


def test_similar_none_on_far_colour_or_thickness():
    lib = MaterialLibrary.from_seed()
    # right category & thickness, but colour way off dark acrylic -> not close
    q = {"id": "q", "category": "risky", "thickness_mm": 3.0, "colour": "#00ff00"}
    assert similar_material(lib, q) is None


def test_similar_accepts_material_object():
    lib = MaterialLibrary.from_seed()
    q = Material(id="q", category="safe", thickness_mm=3.0, colour="#b59b6b")
    assert similar_material(lib, q).id == "plywood_3"


# --------------------------------------------------------------------------- #
# risk block
# --------------------------------------------------------------------------- #
def test_risk_block_empty_for_safe():
    assert risk_block(Material(id="ply", category="safe", risk_flags=("fumes",))) == []
    assert risk_block({"id": "ply", "category": "safe"}) == []


def test_risk_block_risky_reasons():
    m = Material(id="acrylic", category="risky", risk_flags=("melting", "fumes"))
    reasons = risk_block(m)
    assert any("risky material acrylic" in r for r in reasons)
    assert any("melting" in r for r in reasons)
    assert any("fumes" in r for r in reasons)


def test_risk_block_forbidden_blocks_outright():
    m = Material(id="pvc", category="forbidden", risk_flags=("chlorine",))
    reasons = risk_block(m)
    assert any("forbidden material pvc" in r for r in reasons)
    assert any("chlorine" in r for r in reasons)


# --------------------------------------------------------------------------- #
# unlock
# --------------------------------------------------------------------------- #
def test_unlock_ok():
    m = Material(id="acrylic", category="risky", risk_flags=("fumes",))
    audit: list = []
    fixed = lambda: datetime(2026, 10, 22, 12, 0, 0)
    assert unlock(m, "I have ventilation and know this material", audit, clock=fixed) is True
    assert len(audit) == 1
    ev = audit[0]
    assert ev["date"] == "2026-10-22T12:00:00"
    assert ev["category"] == "risky"
    assert ev["material"] == "acrylic"
    assert ev["text"] == "I have ventilation and know this material"


def test_unlock_refuses_empty_declaration():
    m = Material(id="acrylic", category="risky")
    audit: list = []
    assert unlock(m, "", audit) is False
    assert unlock(m, "   ", audit) is False
    assert unlock(m, None, audit) is False
    assert audit == []


def test_unlock_is_deterministic_given_clock():
    m = Material(id="acrylic", category="risky")
    fixed = lambda: datetime(2030, 1, 1, 0, 0, 0)
    a1, a2 = [], []
    assert unlock(m, "decl", a1, clock=fixed)
    assert unlock(m, "decl", a2, clock=fixed)
    assert a1 == a2


# --------------------------------------------------------------------------- #
# what_is_missing
# --------------------------------------------------------------------------- #
def test_what_is_missing_empty_when_complete():
    spec = {
        "module": "laser_405",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0, "wavelength_nm": 405},
    }
    assert what_is_missing(spec) == []


def test_what_is_missing_material_undeclared():
    spec = {"module": "laser_405", "material": None}
    out = what_is_missing(spec)
    assert "material not declared" in out
    assert "material category undeclared" in out
    assert "material thickness missing" in out


def test_what_is_missing_category_undeclared():
    spec = {
        "module": "laser_405",
        "material": {"id": "plywood_3", "category": "???wrong", "thickness_mm": 3.0, "wavelength_nm": 405},
    }
    assert "material category undeclared" in what_is_missing(spec)


def test_what_is_missing_thickness():
    spec = {
        "module": "laser_405",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 0, "wavelength_nm": 405},
    }
    assert "material thickness missing" in what_is_missing(spec)


def test_what_is_missing_wavelength_mismatch():
    spec = {
        "module": "laser_1064",
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0, "wavelength_nm": 405},
    }
    out = what_is_missing(spec)
    assert any("wavelength/module mismatch" in m for m in out)


def test_what_is_missing_module_undeclared():
    spec = {
        "module": None,
        "material": {"id": "plywood_3", "category": "safe", "thickness_mm": 3.0},
    }
    assert "module not declared" in what_is_missing(spec)


def test_what_is_missing_none_spec():
    assert what_is_missing(None) == [
        "module not declared",
        "material not declared",
        "material category undeclared",
        "material thickness missing",
    ]


def test_what_is_missing_accepts_model_like_object():
    class _Spec:
        def __init__(self):
            self.material = Material(id="acrylic", category="risky", thickness_mm=0.0)
            self.module = "laser_405"
        def model_dump(self):
            return {"module": self.module, "material": self.material}
    out = what_is_missing(_Spec())
    assert "material thickness missing" in out
