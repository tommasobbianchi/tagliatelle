import pytest
from pydantic import ValidationError
from jobspec import *

BASE = dict(module="laser_405", job_type="work", material=dict(id="ply3", category="safe"), params_version="m1",
            workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)], registration_rms_mm=0.1, registration_max_mm=0.3),
            ops=[dict(op="add_text", id="t1", text="Ciao", font="dejavu", font_version="2.37", height_mm=10, x=10, y=10),
                 dict(op="center_on_workpiece", target="t1"),
                 dict(op="set_pass", target="t1", power_pct=40, speed_mm_min=1500, passes=1)])


def make(**kw):
    return JobSpec.model_validate({**BASE, **kw})


def test_roundtrip_and_stable_hash():
    s = make()
    assert JobSpec.model_validate_json(s.model_dump_json()) == s
    assert spec_hash(s) == spec_hash(make())


def test_one_byte_changes_hash():
    ops = [dict(o) for o in BASE["ops"]]; ops[0]["text"] = "Ciaq"
    assert spec_hash(make(ops=ops)) != spec_hash(make())


@pytest.mark.parametrize("bad", [dict(schema_version="0.2.0"), dict(module="cnc"), dict(extra_field=1),
                                 dict(ops=[dict(op="set_pass", target="nope", power_pct=1, speed_mm_min=1, passes=1)])])
def test_rejects(bad):
    with pytest.raises(ValidationError):
        make(**bad)


def test_power_limit():
    ops = [dict(o) for o in BASE["ops"]]; ops[2]["power_pct"] = 101
    with pytest.raises(ValidationError):
        make(ops=ops)


def test_gate_blocks_unresolved_and_forbidden():
    assert gate_blockers(make()) == ["center_on_workpiece:t1 unresolved"]
    assert any("forbidden" in b for b in gate_blockers(make(material=dict(id="pvc", category="forbidden"))))
