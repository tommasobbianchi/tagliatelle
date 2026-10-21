"""Deterministic G-code simulator / validator for the TaglIAtelle E1.0 laser-405 vertical.

Role (SPEC, principle #9 + "Simulatore G-code"): re-read the G-code the deterministic compiler
produced and re-verify it before it ever reaches the approval gate. Runs in CI (the golden-file /
second safety layer) and at runtime, as the check in front of the gate.

Guarantees / non-goals:
- Pure and deterministic: stdlib + pydantic only. No I/O, no clock, no randomness. Same
  (gcode, spec) -> same SimulationResult, so the audit package can store the result byte-stably.
- Fail-safe on syntax: the simulator deliberately understands ONLY the small set the E1.0 laser
  compiler emits -- G0/G1/G21/G90/G91 and M3/M4/M5. Any other G/M code is a hard ERROR: we never
  assume an unknown command is safe (same spirit as gcode_scan's fail-safe scanning).
- Laser on/off is M3/M4 (on) and M5 (off). ``G1 S#`` updates the modal power but does NOT toggle
  the beam -- the E1.0 compiler contract uses the M-codes for on/off.
- Warnings are non-fatal (no feed rate while firing, laser left on at end of file, spec gate
  blockers); any ERROR sets ``ok=False``.
- Bed/axis contract is the shared Job Spec machine constants: X,Y <= BED_MM (250), Z <= FOCAL_Z_MM
  (220). ``validate_against_spec`` ties those checks to the spec and adds the "a work job must
  fire the laser" rule, reusing the spirit of ``gate_blockers``.

The tool starts at the bed origin (0,0,0); absolute positioning (G90) is the default, matching the
laser G-code the compiler emits.
"""
from __future__ import annotations

import re
from pydantic import BaseModel, ConfigDict, Field

from jobspec import BED_MM, FOCAL_Z_MM, JobSpec, gate_blockers

__all__ = ["SimulationResult", "simulate_gcode", "validate_against_spec"]

# Machine bed/axis contract, imported from the Job Spec schema (the single shared contract).
BED_XY_MM: float = BED_MM          # X and Y usable area (A250)
BED_Z_MM: float = FOCAL_Z_MM       # Z max (focus plane, measured in task zero)

# The only commands this simulator understands. Anything else is rejected by design (fail-safe).
_SUPPORTED_G = {0, 1, 21, 90, 91}
_SUPPORTED_M = {3, 4, 5}

_CMD = re.compile(r"^([GMgm])(\d+)$")
_PARAM = re.compile(r"^([A-Za-z])(.*)$")
_INLINE_COMMENT = re.compile(r"\([^)]*\)")


class SimulationResult(BaseModel):
    """Outcome of simulating a G-code program (against the machine contract, optionally a spec).

    ``ok`` is True iff there are no errors. ``max_x``/``max_y``/``max_z`` are the furthest
    positions the tool actually reached (rejected moves are not applied and do not count), starting
    from the bed origin. ``laser_fired`` is True iff the program contains an M3/M4 with effective
    power S>0.
    """
    model_config = ConfigDict(frozen=True)
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0
    laser_fired: bool = False
    moves: int = 0
    lines: int = 0


def _strip_comments(line: str) -> str:
    """Drop ';' line comments and '( ... )' inline comments (matches gcode_scan's handling)."""
    line = line.split(";", 1)[0]
    return _INLINE_COMMENT.sub(" ", line).strip()


def _check_bounds(x: float, y: float, z: float) -> list[str]:
    """Return one reason-string per axis that is negative or beyond the bed/axis limit."""
    bad = []
    for axis, val, hi in (("X", x, BED_XY_MM), ("Y", y, BED_XY_MM), ("Z", z, BED_Z_MM)):
        if val < 0.0:
            bad.append("%s=%.4f is negative (min 0)" % (axis, val))
        elif val > hi:
            bad.append("%s=%.4f exceeds bed limit %.0f" % (axis, val, hi))
    return bad


def _parse_stmt(body: str, lineno: int, errors: list[str]) -> tuple[tuple[str, int] | None, dict]:
    """Split one already-cleaned statement into (command, params).

    ``command`` is ``(letter, code)`` or None; ``params`` is a dict of uppercase letter -> float.
    Appends a descriptive error (already referencing the line) for each non-numeric or
    unrecognized token it meets, so the caller gets *all* problems in one pass.
    """
    command: tuple[str, int] | None = None
    params: dict = {}
    for tok in body.split():
        m = _CMD.match(tok)
        if m:
            if command is None:
                command = (m.group(1).upper(), int(m.group(2)))
            else:
                errors.append("line %d: a G/M command appears more than once on one line (%s)" % (lineno, tok))
            continue
        p = _PARAM.match(tok)
        if p:
            name, raw = p.group(1).upper(), p.group(2)
            try:
                params[name] = float(raw)
            except ValueError:
                errors.append("line %d: non-numeric parameter %s=%r" % (lineno, name, raw))
        else:
            errors.append("line %d: unrecognized token %r" % (lineno, tok))
    return command, params


def simulate_gcode(gcode: str) -> SimulationResult:
    """Simulate/validate raw G-code text against the E1.0 machine contract (see module docstring)."""
    errors: list[str] = []
    warnings: list[str] = []

    x = y = z = 0.0                 # tool starts at the bed origin
    absolute = True                 # G90 default for laser G-code
    laser_on = False
    modal_s = 0.0
    modal_f: float | None = None
    laser_fired = False
    moves = 0
    lines = 0
    warned_no_feed = False
    max_x = max_y = max_z = 0.0

    for lineno, raw in enumerate(gcode.splitlines(), start=1):
        body = _strip_comments(raw)
        if not body:
            continue
        lines += 1

        command, params = _parse_stmt(body, lineno, errors)
        if command is None:
            # Non-empty line that is only bare parameters (or garbage): not a valid laser command.
            errors.append("line %d: missing G/M command (bare parameters)" % lineno)
            continue

        letter, code = command

        if letter == "M":
            if code not in _SUPPORTED_M:
                errors.append("line %d: unsupported command M%d" % (lineno, code))
                continue
            if code in (3, 4):                     # laser on, at this or the modal power
                power = params.get("S", modal_s)
                modal_s = power
                laser_on = True
                if power > 0:
                    laser_fired = True
            elif code == 5:                        # laser off
                laser_on = False

        else:  # letter == "G"
            if code not in _SUPPORTED_G:
                errors.append("line %d: unsupported command G%d" % (lineno, code))
                continue
            if code == 90:                         # absolute positioning
                absolute = True
            elif code == 91:                       # relative positioning
                absolute = False
            elif code == 21:                       # millimeters: the only supported unit
                pass
            elif code in (0, 1):                   # rapid / linear movement
                if "S" in params:                  # modal power tweak (does not toggle the beam)
                    modal_s = params["S"]
                if "F" in params:                  # modal feed rate
                    modal_f = params["F"]

                tx, ty, tz = x, y, z
                if "X" in params:
                    tx = params["X"] if absolute else x + params["X"]
                if "Y" in params:
                    ty = params["Y"] if absolute else y + params["Y"]
                if "Z" in params:
                    tz = params["Z"] if absolute else z + params["Z"]

                if not (("X" in params) or ("Y" in params) or ("Z" in params)):
                    continue                        # e.g. "G1 F1000": sets modal, moves nothing

                bad = _check_bounds(tx, ty, tz)
                if bad:
                    errors.extend("line %d: %s" % (lineno, b) for b in bad)
                    continue                        # fail-safe: reject the move, tool stays put

                if laser_on and modal_f is None and not warned_no_feed:
                    warnings.append("line %d: moving while laser on with no feed rate (F) set" % lineno)
                    warned_no_feed = True

                x, y, z = tx, ty, tz
                moves += 1
                max_x = max(max_x, x)
                max_y = max(max_y, y)
                max_z = max(max_z, z)

    if laser_on:
        warnings.append("file ends with the laser on (no M5 to switch it off)")

    return SimulationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        max_x=max_x, max_y=max_y, max_z=max_z,
        laser_fired=laser_fired,
        moves=moves,
        lines=lines,
    )


def validate_against_spec(gcode: str, spec: JobSpec) -> SimulationResult:
    """Validate G-code against a specific Job Spec (SPEC: "coerenza con lo spec").

    Builds on ``simulate_gcode`` and additionally enforces, using the spec's own constants:
      - every reached coordinate stays within the spec's bed (X,Y <= BED_MM; Z <= FOCAL_Z_MM);
      - a job of type ``work`` must actually fire the laser (a ``work`` job that never fires the
        beam is meaningless -- the spirit of ``gate_blockers``).
    The spec's own gate blockers are surfaced as non-fatal warnings so the caller sees readiness.
    """
    base = simulate_gcode(gcode)
    errors = list(base.errors)
    warnings = list(base.warnings)

    if base.max_x > BED_MM:
        errors.append("spec: reached max_x=%.4f exceeds bed BED_MM=%.0f" % (base.max_x, BED_MM))
    if base.max_y > BED_MM:
        errors.append("spec: reached max_y=%.4f exceeds bed BED_MM=%.0f" % (base.max_y, BED_MM))
    if base.max_z > FOCAL_Z_MM:
        errors.append("spec: reached max_z=%.4f exceeds focal FOCAL_Z_MM=%.0f" % (base.max_z, FOCAL_Z_MM))

    if spec.job_type == "work" and not base.laser_fired:
        errors.append("spec: job_type=work but the program never fires the laser (no M3/M4 with S>0)")

    for blocker in gate_blockers(spec):
        warnings.append("spec gate blocker: " + blocker)

    return SimulationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        max_x=base.max_x, max_y=base.max_y, max_z=base.max_z,
        laser_fired=base.laser_fired,
        moves=base.moves,
        lines=base.lines,
    )
