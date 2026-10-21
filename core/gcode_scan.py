"""Deterministic 'active job' scan (SPEC, Avvio): a job needs the on-screen confirmation iff the final G-code
can turn the laser/spindle on, i.e. M3/M4 with S or P != 0.  Fail-safe: anything unparsable counts as active."""
import re

_CMD = re.compile(r"\bM0*([34])\b([^;]*)", re.I)
_ARG = re.compile(r"\b([SP])\s*([-+]?[0-9]*\.?[0-9]+|\S*)", re.I)


def is_active(gcode: str) -> bool:
    for line in gcode.splitlines():
        line = re.sub(r"\([^)]*\)", "", line.split(";", 1)[0])   # strip ; and (...) comments
        for m in _CMD.finditer(line):
            args = _ARG.findall(m.group(2))
            if not args:                      # bare M3/M4: Marlin turns on at the last/default power -> active
                return True
            for _, v in args:
                try:
                    if float(v) != 0:
                        return True
                except ValueError:            # S%var etc.: cannot prove it is zero
                    return True
    return False


def test_scan():
    assert not is_active("G28\nG1 X10 F1000\nM5\n; M3 S100\n(M4 S9)")
    assert not is_active("M3 S0\nM4 P0.0")
    assert is_active("G21\nM3 S2.55\nG1 X10")
    assert is_active("m4 p50")
    assert is_active("M3")
    assert is_active("M3 S#1")
    assert not is_active("M30\nM300 S5")      # M30/M300 are other commands
