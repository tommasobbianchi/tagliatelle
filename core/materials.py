"""L1 — materials: the YAML-in-repo material library that feeds the laser.

This is the deterministic core of the L0 decision (materials library with a
Snapmaker/Luban-style seed, per-category power caps, a documented "similar
material" rule, risk blocks with unlock-by-declaration, and audit events).

Project rules honoured here (SPEC.md §Materiali + §Principi/safety 7-8):
  * YAML in the repo is the source of truth. We *read* it; we never infer a
    material from a camera image (the human declares it).
  * Categories are exactly ``safe`` | ``risky`` | ``forbidden`` (the schema of
    ``core/jobspec.py:Material``); the category decides the conservative
    power cap and blocks/safety reasons.
  * Forbidden materials block the job; risky ones require an explicit,
    non-empty human declaration to unlock (audited); safe ones need nothing.
  * Deterministic: no AI-provider imports. stdlib + optional PyYAML, with a
    tiny built-in fallback parser for the flat seed shape so nothing new is
    added as a hard dependency.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "Material",
    "MaterialLibrary",
    "power_cap",
    "risk_block",
    "similar_material",
    "unlock",
    "what_is_missing",
    "POWER_CAP",
    "VALID_CATEGORIES",
]

VALID_CATEGORIES = ("safe", "risky", "forbidden")

# Conservative per-category laser power cap, in percent (0..100).
# This is the ceiling the gate/simulator enforce against material YAML params.
#   safe      -> generous but still <100: leaves headroom the operator can see.
#   risky     -> clearly reduced: these melt/drip/fume; less energy is safer.
#   forbidden -> 0: no laser energy at all; the job is blocked.
POWER_CAP: dict[str, float] = {
    "safe": 60.0,
    "risky": 40.0,
    "forbidden": 0.0,
}

# Human-readable block reasons, keyed by a material's risk flag. A flag without
# an entry here still produces a reason (the flag text itself).
_RISK_REASON: dict[str, str] = {
    "fumes": "hazardous fumes (e.g. plastics off-gassing under laser heat)",
    "chlorine": "possible chlorine release (PVC-family plastic) — toxic fumes",
    "reflection": "reflective surface — beam reflection / fire hazard",
    "melting": "melting/dripping — poor cut quality and ignition risk on debris",
    "flammable": "flammable — ignition risk at high power",
}


# --------------------------------------------------------------------------- #
# Material model
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Material:
    """A declared material profile (from YAML truth or the seed).

    ``category`` is the safety-relevant field (see jobspec.Material). The other
    fields carry the physics the interview/similarity rule reason about:
    thickness for the cap/similarity, colour for "similar material", and
    ``wavelength_nm`` for the module/wavelength compatibility check.
    """

    id: str
    category: str = "safe"
    thickness_mm: float = 0.0
    colour: str = ""
    name: str = ""
    wavelength_nm: int | None = None
    risk_flags: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.category not in VALID_CATEGORIES:
            raise ValueError("material %r: invalid category %r" % (self.id, self.category))
        if self.thickness_mm < 0:
            raise ValueError("material %r: thickness_mm must be >= 0" % self.id)


# --------------------------------------------------------------------------- #
# Similarity scoring — fixed, documented, deterministic
# --------------------------------------------------------------------------- #
# A candidate is *close* only when ALL three hold (same category is a hard gate;
# thickness and colour are bounded). Among the close candidates we pick the
# smallest composite score  score = |thickness delta| (mm) + colour_delta (0..1)
# with the id as a deterministic tie-break. Nothing close  ->  None.
THICKNESS_TOL_MM = 1.5      # max allowed |thickness| difference
COLOUR_TOL = 0.5            # max allowed normalised RGB distance (0..1)
_COLOUR_SPAN = 255.0 * math.sqrt(3.0)   # max possible RGB Euclidean distance

_NAMED_COLOURS: dict[str, str] = {
    "black": "#000000", "white": "#ffffff", "red": "#ff0000",
    "green": "#00ff00", "blue": "#0000ff", "yellow": "#ffff00",
    "brown": "#5b3a24", "grey": "#808080", "gray": "#808080",
}


def _parse_colour(c: Any) -> tuple[int, int, int] | tuple[int, int, int] | None:
    """Parse a hex or named colour into an (r, g, b) tuple, or None if unknown."""
    if c is None:
        return None
    s = str(c).strip().lower()
    if s in _NAMED_COLOURS:
        s = _NAMED_COLOURS[s]
    if not s:
        return None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            try:
                return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            except ValueError:
                return None
        return None
    try:
        n = int(s, 16)
        return (n >> 16) & 255, (n >> 8) & 255, n & 255
    except ValueError:
        return None


def _colour_delta(a: Any, b: Any) -> float:
    """Normalised colour distance in 0..1 (Euclidean RGB / max span).

    If either side is unparseable we are *not* close: same unparseable string ->
    0.0, otherwise the worst-case 1.0 so an unknown colour never matches.
    """
    pa, pb = _parse_colour(a), _parse_colour(b)
    if pa is None and pb is None:
        return 0.0 if str(a).strip().lower() == str(b).strip().lower() else 1.0
    if pa is None or pb is None:
        return 1.0
    d = math.sqrt((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2 + (pa[2] - pb[2]) ** 2)
    return d / _COLOUR_SPAN


def _like(x: Any):
    """Material-ish -> Material (accepts a Material or a mapping)."""
    if isinstance(x, Material):
        return x
    if isinstance(x, Mapping):
        row = dict(x)
        flags = row.get("risk_flags", row.get("flags", ()))
        if isinstance(flags, (list, tuple)):
            flags = tuple(flags)
        elif flags:
            flags = (flags,)
        wl = row.get("wavelength_nm", row.get("wavelength"))
        return Material(
            id=str(row.get("id") or row.get("name") or ""),
            name=str(row.get("name", row.get("id", ""))),
            category=str(row.get("category", "safe")),
            thickness_mm=float(row.get("thickness_mm", row.get("thickness", 0.0)) or 0.0),
            colour=str(row.get("colour") or row.get("color") or ""),
            wavelength_nm=int(wl) if wl is not None else None,
            risk_flags=flags,
        )
    raise TypeError("expected a Material or mapping, got %r" % type(x).__name__)


def _materials_of(library: Any) -> list[Material]:
    if isinstance(library, MaterialLibrary):
        return list(library.materials)
    if isinstance(library, (list, tuple)):
        return [_like(m) for m in library]
    raise TypeError("library must be a MaterialLibrary or a sequence of materials")


# --------------------------------------------------------------------------- #
# Seed profiles (Snapmaker/Luban-style starting values)
# --------------------------------------------------------------------------- #
SEED_MATERIALS: list[Material] = [
    Material(id="plywood_3", name="Beech plywood 3 mm", category="safe",
             thickness_mm=3.0, colour="#b59b6b", wavelength_nm=405),
    Material(id="mdf_3", name="MDF 3 mm", category="safe",
             thickness_mm=3.0, colour="#c8a878", wavelength_nm=405),
    Material(id="cardboard_16", name="Cardboard 1.6 mm", category="safe",
             thickness_mm=1.6, colour="#d0b98a", wavelength_nm=405),
    Material(id="leather_16", name="Leather 1.6 mm", category="safe",
             thickness_mm=1.6, colour="#5b3a24", wavelength_nm=405,
             risk_flags=("fumes",)),
    Material(id="acrylic_dark_3", name="Acrilico scuro 3 mm", category="risky",
             thickness_mm=3.0, colour="#20242a", wavelength_nm=405,
             risk_flags=("melting", "fumes")),
]


# --------------------------------------------------------------------------- #
# Minimal YAML fallback (used only when PyYAML is unavailable)
# --------------------------------------------------------------------------- #
def _strip_comment(line: str) -> str:
    out: list[str] = []
    quote = None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out)


def _mini_value(v: str) -> Any:
    v = v.strip()
    if v == "":
        return None
    if (v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'"):
        return v[1:-1]
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_mini_value(p) for p in inner.split(",")]
    low = v.lower()
    if low in ("null", "~", "none"):
        return None
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _mini_yaml_load(text: str) -> Any:
    """Parse the *flat* shape the seed uses: a list of flat key/value mappings.

    Handles comments, blank lines, "- " list items and inline "[a, b]" lists.
    Nested block mappings are out of scope (full YAML is used when PyYAML is
    installed); this only needs to be correct for the built-in seed files.
    """
    items: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        s = line.strip()
        if s == "-" or s.startswith("- "):
            if current is not None:
                items.append(current)
            current = {}
            s = s[2:].strip()
        if current is not None and ":" in s:
            k, v = s.split(":", 1)
            current[k.strip()] = _mini_value(v.strip())
    if current is not None:
        items.append(current)
    return items


def _read_yaml(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        import yaml  # type: ignore
    except ImportError:
        return _mini_yaml_load(text)
    return yaml.safe_load(text)


def _to_materials(data: Any) -> list[Material]:
    if isinstance(data, Mapping):
        data = data.get("materials", data.get("material", []))
    if not isinstance(data, (list, tuple)):
        raise ValueError("materials YAML must be a list of material mappings")
    out = []
    for row in data:
        if isinstance(row, Material):
            out.append(row)
            continue
        m = _like(row)
        if not m.id:
            raise ValueError("material entry is missing an 'id'")
        out.append(m)
    return out


# --------------------------------------------------------------------------- #
# Library + API
# --------------------------------------------------------------------------- #
class MaterialLibrary:
    """An in-memory, ordered view of the material YAML truth (or the seed).

    Deterministic: identity by ``Material.id``; no clocks, no randomness.
    """

    def __init__(self, materials: Sequence[Material] | None = None) -> None:
        self.materials: list[Material] = [_like(m) for m in (materials or [])]

    # -- construction -------------------------------------------------------
    @classmethod
    def from_seed(cls) -> "MaterialLibrary":
        return cls(list(SEED_MATERIALS))

    @staticmethod
    def seed_defaults() -> list[Material]:
        """Built-in seed list (Snapmaker/Luban-style profiles)."""
        return list(SEED_MATERIALS)

    @classmethod
    def load_yaml(cls, path: str) -> "MaterialLibrary":
        """Load the YAML-in-repo (source of truth) into a library."""
        return cls(_to_materials(_read_yaml(path)))

    # -- lookup -------------------------------------------------------------
    def get(self, material_id: str) -> Material | None:
        for m in self.materials:
            if m.id == material_id:
                return m
        return None

    def __iter__(self):
        return iter(self.materials)

    def __len__(self) -> int:
        return len(self.materials)

    def __contains__(self, material_id: str) -> bool:
        return any(m.id == material_id for m in self.materials)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def power_cap(category: str) -> float:
    """Conservative laser power cap in percent (0..100) for a category."""
    if category not in POWER_CAP:
        raise ValueError("unknown category %r (expected one of %s)" % (category, ", ".join(VALID_CATEGORIES)))
    return POWER_CAP[category]


def risk_block(material: Any) -> list[str]:
    """Deterministic block reasons for a material.

    Empty for ``safe``. For ``risky`` / ``forbidden`` it lists the specific
    hazards (fumes, reflection, melting, ...); ``forbidden`` additionally
    states that the material is blocked outright. Order is stable: the
    material is named first, then its flags in stored order.
    """
    m = _like(material)
    if m.category == "safe":
        return []
    reasons: list[str] = []
    if m.category == "forbidden":
        reasons.append("forbidden material %s — job is blocked" % m.id)
    elif m.category == "risky":
        reasons.append("risky material %s — explicit declaration required" % m.id)
    for flag in m.risk_flags:
        reasons.append(_RISK_REASON.get(flag, str(flag)))
    return reasons


def similar_material(library: Any, query: Any) -> Material | None:
    """Nearest seed/library material to ``query``, or ``None`` if nothing close.

    Scoring (fixed and documented in THICKNESS_TOL_MM / COLOUR_TOL):
      1. category must be identical (hard gate);
      2. both |thickness| delta <= THICKNESS_TOL_MM and colour delta <= COLOUR_TOL;
      3. pick the smallest (|thickness delta| + colour delta), tie-broken by id.
    """
    q = _like(query)
    best: tuple[float, str, Material] | None = None
    for m in _materials_of(library):
        if m.category != q.category:
            continue
        t_delta = abs(m.thickness_mm - q.thickness_mm)
        if t_delta > THICKNESS_TOL_MM:
            continue
        c_delta = _colour_delta(m.colour, q.colour)
        if c_delta > COLOUR_TOL:
            continue
        key = (t_delta + c_delta, m.id)
        if best is None or key < (best[0], best[1]):
            best = (t_delta + c_delta, m.id, m)
    return best[2] if best is not None else None


def unlock(
    material: Any,
    declaration: str,
    audit_log: Any,
    clock: Any = None,
) -> bool:
    """Unlock a risky/forbidden material against an explicit human declaration.

    Returns True and appends an audit event (date, category, text, material)
    when the declaration is a non-empty string; returns False and appends
    nothing when it is empty/whitespace. Deterministic except the timestamp,
    which is taken from ``clock`` (default ``datetime.utcnow``).
    """
    if clock is None:
        clock = datetime.utcnow
    if not isinstance(declaration, str) or not declaration.strip():
        return False
    m = _like(material)
    if not isinstance(audit_log, list):
        raise TypeError("audit_log must be a list")
    audit_log.append({
        "event": "unlock",
        "date": clock().isoformat(),
        "category": m.category,
        "material": m.id,
        "text": declaration,
    })
    return True


_MODULE_WAVELENGTH: dict[str, int | None] = {
    "laser_405": 405,
    "laser_1064": 1064,
    "cnc": None,
}
_VALID_MODULES = set(_MODULE_WAVELENGTH)


def what_is_missing(spec: Any) -> list[str]:
    """Deterministic list of what the interview still has to collect ("" = ready).

    Accepts a JobSpec model (``model_dump()``) or a plain mapping. Checks, in a
    fixed order: module declared, material declared, category declared,
    thickness declared (>0), and module/wavelength compatibility with the
    material.
    """
    if spec is None:
        return [
            "module not declared",
            "material not declared",
            "material category undeclared",
            "material thickness missing",
        ]
    if isinstance(spec, Mapping):
        s: dict[str, Any] = dict(spec)
    else:
        dump = getattr(spec, "model_dump", None)
        s = dump() if callable(dump) else dict(vars(spec))

    def getfield(mat: Any, *keys: str) -> Any:
        """Read a (first non-None) field from a material mapping or object, raw."""
        if isinstance(mat, Mapping):
            for k in keys:
                if k in mat and mat[k] is not None:
                    return mat[k]
            return None
        for k in keys:
            v = getattr(mat, k, None)
            if v is not None:
                return v
        return None

    missing: list[str] = []
    mat = s.get("material")

    # 1. module
    module = s.get("module")
    if module not in _VALID_MODULES:
        missing.append("module not declared")

    # 2./3. material + category
    if mat is None or (isinstance(mat, Mapping) and not (getfield(mat, "id") or getfield(mat, "category"))):
        missing.append("material not declared")
        missing.append("material category undeclared")
        missing.append("material thickness missing")
        # wavelength/module check cannot be performed without a material.
        return missing

    category = getfield(mat, "category")
    if category not in VALID_CATEGORIES:
        missing.append("material category undeclared")

    # 4. thickness declared + positive
    thickness = getfield(mat, "thickness_mm", "thickness")
    try:
        thickness_ok = float(thickness) > 0
    except (TypeError, ValueError):
        thickness_ok = False
    if not thickness_ok:
        missing.append("material thickness missing")

    # 5. module / wavelength compatibility
    mod_wl = _MODULE_WAVELENGTH.get(module)
    mat_wl = getfield(mat, "wavelength_nm", "wavelength")
    if mod_wl is not None and mat_wl is not None:
        try:
            if int(mat_wl) != mod_wl:
                missing.append(
                    "wavelength/module mismatch: material fits %s nm, module is %s"
                    % (mat_wl, module)
                )
        except (TypeError, ValueError):
            pass

    return missing
