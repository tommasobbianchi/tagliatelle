"""L7 · offline runner: the whole core pipeline runs with NO network and NO API keys.

Guard test for CI (SPEC §11 "Offline runner (no network, no keys)"): socket and
urllib are disabled and every known provider credential is stripped from the
environment, then resolve → compile → simulate → gate must still succeed. Core is
already pure by design — this pins that property so a future dependency (a
"convenient" client) that touches the network or a key breaks the build, not the
machine.
"""
from __future__ import annotations

import importlib
import socket
import urllib.request

FORBIDDEN_PROVIDERS = ("openai", "anthropic", "transformers", "torch", "ollama", "langchain")
KEY_ENV_VARS = (
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "OPENROUTER_API_KEY", "HF_TOKEN", "HF_API_KEY", "TRANSFORMERS_CACHE",
    "OLLAMA_HOST", "OLLAMA_API_KEY", "TOGETHER_API_KEY", "GROQ_API_KEY",
)


class _NetDisabled(RuntimeError):
    pass


def test_pipeline_is_offline_and_keyless(monkeypatch):
    # --- strip every provider credential (CI must not rely on ambient keys) ---
    for var in KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    # --- disable the network surface ---
    calls = []
    def _probe(*a, **kw):
        calls.append((a, kw))
        raise _NetDisabled("network access attempted during the offline runner test")
    monkeypatch.setattr(socket, "socket", _probe)
    monkeypatch.setattr(socket, "create_connection", _probe)
    monkeypatch.setattr(socket, "getaddrinfo", _probe)
    monkeypatch.setattr(urllib.request, "urlopen", _probe)

    # --- import the full post-gate surface (fresh where possible) ---
    for name in ("jobspec", "jobspec2", "resolver", "compiler", "compiler2",
                 "simulator", "gcode_scan", "grid", "materials", "replay"):
        importlib.import_module(name)

    from jobspec import JobSpec, gate_blockers
    from jobspec2 import JobSpec2, migrate_020_to_030
    from compiler import compile_gcode
    from compiler2 import compile_jobspec2
    from resolver import resolve_spec
    from simulator import simulate_gcode, validate_against_spec

    # --- run the full pipeline: resolve → compile → simulate → gate ---
    spec = JobSpec.model_validate(dict(
        module="laser_405", job_type="work",
        material=dict(id="ply3", category="safe"), params_version="m1",
        workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                       registration_rms_mm=0.1, registration_max_mm=0.3),
        ops=[dict(op="add_rect", id="r1", x=10, y=20, w=40, h=20),
             dict(op="center_on_workpiece", target="r1"),
             dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=3000, passes=2),
             dict(op="set_depth", target="r1", depth_mm=-0.4, multi_pass_depth_mm=0.2)]))
    resolved = resolve_spec(spec)
    gcode = compile_gcode(resolved)
    gate = validate_against_spec(gcode, resolved)
    assert gate.ok, gate.errors
    assert gate.laser_fired
    assert gate_blockers(resolved) == []      # gate readiness: nothing left unresolved

    d = migrate_020_to_030({"schema_version": "0.2.0",
                            "module": "laser_405", "job_type": "work",
                            "material": dict(id="ply3", category="safe"),
                            "params_version": "m1",
                            "workpiece": dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                                              registration_rms_mm=0.1, registration_max_mm=0.3),
                            "ops": [dict(op="add_rect", id="o", x=10, y=10, w=60, h=30),
                                   dict(op="set_pass", target="o", power_pct=60,
                                        speed_mm_min=1500, passes=1)]})
    d["layers"] = [dict(op="cut", color="#000000", settings=dict(kerf_mm=0.2))]
    gcode3 = compile_jobspec2(JobSpec2.model_validate(d))
    assert simulate_gcode(gcode3).ok

    # --- assert nothing touched the network and no provider ever loaded ---
    assert not calls, "network was attempted: %r" % calls[:3]
    import sys
    bad = [m for m in sys.modules for f in FORBIDDEN_PROVIDERS if m == f or m.startswith(f + ".")]
    assert not bad, "AI provider present in interpreter: %s" % bad
