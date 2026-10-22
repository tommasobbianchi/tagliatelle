import pytest
from pydantic import ValidationError

from jobspec import JobSpec as OldJobSpec, spec_hash
from jobspec2 import (JobSpec2, migrate_020_to_030, spec_hash2, canonical2, AddMaterialGrid,
                      MaterialGridAxis, FrozenSketch, Layer, Workpiece2)

# a valid 0.2.0 spec (matches core/test_jobspec.py BASE)
OLD = dict(schema_version="0.2.0", module="laser_405", job_type="work",
           material=dict(id="ply3", category="safe"), params_version="m1",
           workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)], registration_rms_mm=0.1,
                          registration_max_mm=0.3),
           ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
                dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=1)])


def test_old_spec_still_valid():
    # 0.2.0 contract is preserved (the old schema still round-trips)
    s = OldJobSpec.model_validate(OLD)
    assert s.schema_version == "0.2.0"
    assert spec_hash(s) == spec_hash(OldJobSpec.model_validate(OLD))


def test_migration_all_additive():
    migrated = migrate_020_to_030(dict(OLD))
    assert migrated["schema_version"] == "0.3.0"
    # every old key preserved
    for k in OLD:
        if k != "schema_version":
            assert k in migrated, k
    # new fields defaulted
    assert migrated["workpiece"]["constraints"] == []
    assert migrated["workpiece"]["modified"] is False
    assert migrated["sketch"] == {"profiles": [], "recipe": {}}
    assert migrated["layers"] == []
    assert migrated["exclusion_mask"] == {"polygons": [], "source": "user"}
    assert migrated["imported_blocks"] == []
    assert migrated["variants"] == []


def test_migrated_parses_as_030():
    migrated = migrate_020_to_030(dict(OLD))
    spec = JobSpec2.model_validate(migrated)
    assert spec.schema_version == "0.3.0"


def test_migration_rejects_wrong_version():
    bad = dict(OLD); bad["schema_version"] = "0.1.0"
    with pytest.raises(ValueError):
        migrate_020_to_030(bad)


def test_migration_rejects_missing_version():
    bad = {k: v for k, v in OLD.items() if k != "schema_version"}
    with pytest.raises(ValueError):
        migrate_020_to_030(bad)


def test_migration_hash_deterministic():
    a = canonical2(JobSpec2.model_validate(migrate_020_to_030(dict(OLD))))
    b = canonical2(JobSpec2.model_validate(migrate_020_to_030(dict(OLD))))
    assert a == b
    assert spec_hash2(JobSpec2.model_validate(migrate_020_to_030(dict(OLD)))) == \
        spec_hash2(JobSpec2.model_validate(migrate_020_to_030(dict(OLD))))


def _base_dict(**kw):
    d = migrate_020_to_030(dict(OLD))
    d.update(kw)
    return d


def test_new_grid_primitive_roundtrip():
    ops = [dict(o) for o in OLD["ops"]]
    ops.append(dict(op="add_material_grid", id="g1",
                    axes=[dict(axis="x", start=10, end=90, step=10),
                          dict(axis="y", start=10, end=50, step=10)],
                    row_labels=["a", "b"], col_labels=["1", "2", "3"], x=0, y=0))
    spec = JobSpec2.model_validate(_base_dict(ops=ops))
    assert JobSpec2.model_validate_json(spec.model_dump_json()) == spec


def test_imported_block_hash_preserved():
    spec = JobSpec2.model_validate(_base_dict(
        imported_blocks=[dict(original_hash="abc123", x=5, y=6)]))
    assert spec.imported_blocks[0].original_hash == "abc123"
    assert spec.imported_blocks[0].scale == 1.0
    assert spec.imported_blocks[0].nodes_unlocked is False


def test_duplicate_id_rejected_across_new_primitive():
    ops = [dict(o) for o in OLD["ops"]]
    ops.append(dict(op="add_material_grid", id="r1",
                    axes=[dict(axis="x", start=0, end=10, step=1),
                          dict(axis="y", start=0, end=10, step=1)], x=0, y=0))
    with pytest.raises(ValidationError):
        JobSpec2.model_validate(_base_dict(ops=ops))


def test_layer_order_semantics():
    # layers are a list; engrave/fill before cut
    layers = [dict(op="engrave", color="#111"), dict(op="fill", color="#222"),
              dict(op="cut", color="#333")]
    spec = JobSpec2.model_validate(_base_dict(layers=layers))
    order = [l.op for l in spec.layers]
    assert order.index("engrave") < order.index("fill") < order.index("cut")
