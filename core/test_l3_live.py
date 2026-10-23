"""L3 · live smoke test — runs only against a *real* reachable ``l3_service``; auto-skipped otherwise.

The rest of the L3 suite is fully offline (in-process fake server). This file is the thin
integration hook: it exercises the real kernel front-end over ``SNAPORCA_L3_SOCK`` **only**
when that socket is configured *and* actually answers a ``status`` round-trip. On a plain
``python3 -m pytest core/`` (CI / offline) it contributes zero cost: every test here skips.

Gate (evaluated once at import, non-raising):
    _CONFIGURED  == ``SNAPORCA_L3_SOCK`` or ``SNAPORCA_L3_BIN`` is set
    _LIVE        == _CONFIGURED AND l3_client.available() returns True

If your CI harness exposes the service via a ``--l3-bin`` pytest option, set the equivalent
``SNAPORCA_L3_BIN`` env var (e.g. in the pre-pytest step) — this module reads that to decide
whether the live socket is worth probing. No network, no provider, no state mutation.
"""
from __future__ import annotations

import os

import pytest

import l3_client
from l3_client import L3Client

_SOCKET = os.environ.get("SNAPORCA_L3_SOCK") or l3_client.DEFAULT_SOCKET_PATH
_CONFIGURED = bool(os.environ.get("SNAPORCA_L3_SOCK") or os.environ.get("SNAPORCA_L3_BIN"))

# l3_client.available() is non-raising: it just fails fast (L3ConnectionError→False) if there
# is no live service. Import-time safe and offline: with nothing configured it is False.
try:
    _REACHABLE = bool(_CONFIGURED) and l3_client.available(_SOCKET)
except Exception:  # defensive: never let a broken probe break collection
    _REACHABLE = False

_LIVE = bool(_REACHABLE)

_REASON = "live l3_service not reachable (set SNAPORCA_L3_SOCK and start it — or SNAPORCA_L3_BIN)"


@pytest.mark.skipif(not _LIVE, reason=_REASON)
def test_live_status_roundtrip():
    r = L3Client(_SOCKET).status()
    assert r.get("service") == "snaporca-l3"
    assert "methods" in r, "status must advertise supported methods"
    for m in ("status", "recipe.decode", "recipe.apply", "sketch.boolean2d", "sketch.text"):
        assert m in r["methods"], "real l3_service is missing method %r" % m


@pytest.mark.skipif(not _LIVE, reason=_REASON)
def test_live_decode_echoes_ok():
    # "ABC" in base64 — the kernel should decode to a well-formed recipe (ok + version)
    decoded = L3Client(_SOCKET).recipe_decode("QUJD")
    assert "ok" in decoded
    assert "recipe_version" in decoded


@pytest.mark.skipif(not _LIVE, reason=_REASON)
def test_live_boolean_on_square():
    square = [[0, 0], [10, 0], [10, 10], [0, 10]]
    out = L3Client(_SOCKET).boolean2d("union", subject=[square], clip=[square])
    assert out.get("region_count", 0) >= 1
    assert isinstance(out.get("loops"), list) and out["loops"]


@pytest.mark.skipif(not _LIVE, reason=_REASON)
def test_live_text_outlines():
    out = L3Client(_SOCKET).text("A", 5.0)
    assert "loop_count" in out and out["loop_count"] >= 1
    assert isinstance(out.get("loops"), list)


@pytest.mark.skipif(not _LIVE, reason=_REASON)
def test_live_error_is_typed():
    # a negative size_mm is invalid; whatever the service returns for it, the client must
    # surface an exception (typed L3RpcError preferred) — never a silent/dict result.
    with pytest.raises(Exception):
        L3Client(_SOCKET).text("A", -1.0)
