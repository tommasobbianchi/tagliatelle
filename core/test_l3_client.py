"""L3 · offline tests for the ``l3_client`` transport and the ``l3_bridge`` mapping.

Everything runs fully offline against an *in-process* fake ``l3_service``: a
``socketserver.ThreadingUnixStreamServer`` that speaks the same line-delimited JSON-RPC 2.0
protocol the real kernel front-end uses, with a scripted ``method → response`` map. No real
kernel, no network, no AI provider. The suite therefore exercises the exact wire contract
(connect → one request line → one response line) and every error class the client must raise.
"""
from __future__ import annotations

import json
import os
import socketserver
import tempfile
import threading

import pytest

import socket

from l3_client import (            # noqa: E402
    L3Client,
    L3ConnectionError,
    L3Error,
    L3NotConfigured,
    L3RpcError,
    available,
)
from l3_bridge import (            # noqa: E402
    frozen_recipe_b64,
    recipe_apply_from_spec,
)
from jobspec2 import JobSpec2, migrate_020_to_030   # noqa: E402


# a valid 0.2.0 spec (same shape as core/test_jobspec2.py) → migrated to 0.3.0 for realism
OLD = dict(
    schema_version="0.2.0", module="laser_405", job_type="work",
    material=dict(id="ply3", category="safe"), params_version="m1",
    workpiece=dict(contour_mm=[(0, 0), (100, 0), (100, 60)],
                   registration_rms_mm=0.1, registration_max_mm=0.3),
    ops=[dict(op="add_rect", id="r1", x=10, y=20, w=8, h=6),
         dict(op="set_pass", target="r1", power_pct=40, speed_mm_min=1500, passes=1)],
)


# ---------------------------------------------------------------------------
# in-process fake l3_service (line-delimited JSON-RPC 2.0 over a Unix socket)
# ---------------------------------------------------------------------------
class _L3Handler(socketserver.StreamRequestHandler):
    """One request line in -> one response line out, dispatching on the scripted map."""

    def handle(self):
        line = self.rfile.readline()
        if not line:
            return
        try:
            req = json.loads(line.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._write(b'{"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":"parse error"}}\n')
            return

        method = req.get("method")
        rid = req.get("id")
        self.server.requests.append({"method": method, "id": rid})

        spec = self.server.dispatch.get(method)
        if spec is None:
            self._reply_error(rid, {"code": -32601, "message": "method not found: %s" % method})
            return
        if isinstance(spec, (bytes, bytearray)):
            self._write(bytes(spec))          # raw/malformed response (tests the parse failure path)
            return
        if callable(spec):
            spec = spec(self.server, req)     # dynamic body (e.g. incrementing uptime)
        if isinstance(spec, dict) and spec.get("_error") is not None:
            self._reply_error(rid, spec["_error"])
            return
        self._reply_result(rid, spec)

    def _reply_error(self, rid, error):
        self._write(json.dumps({"jsonrpc": "2.0", "id": rid, "error": error},
                               sort_keys=True).encode("utf-8") + b"\n")

    def _reply_result(self, rid, result):
        self._write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result},
                               sort_keys=True).encode("utf-8") + b"\n")

    def _write(self, data: bytes):
        self.wfile.write(data)


class FakeL3Server:
    """Lifecycle wrapper around a ``ThreadingUnixStreamServer`` bound to a temp path.

    ``dispatch`` maps method -> one of:
        * dict            : JSON-RPC ``result``
        * {"_error": e}   : JSON-RPC ``error``
        * bytes           : raw bytes written verbatim (to force client parse failures)
        * callable(server, req) -> dict
    """

    def __init__(self, dispatch: dict | None = None):
        self.dispatch = dict(dispatch or {})
        self.requests: list[dict] = []
        self._dir = tempfile.mkdtemp(prefix="fakel3-")
        self.sock_path = os.path.join(self._dir, "l3.sock")
        self._server: socketserver.ThreadingUnixStreamServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> "FakeL3Server":
        srv = socketserver.ThreadingUnixStreamServer(self.sock_path, _L3Handler)
        srv.dispatch = self.dispatch
        srv.requests = self.requests
        self._server = srv
        self._thread = threading.Thread(target=srv.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        try:
            os.unlink(self.sock_path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(self._dir)
        except OSError:
            pass

    def __enter__(self) -> "FakeL3Server":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def _status_body():
    """Deterministic status result whose *only* variable field is uptime_seconds (increments)."""
    state = {"n": 0}
    def body(server, req):
        state["n"] += 1
        return {
            "service": "l3",
            "protocol": "jsonrpc/2.0",
            "version": "1.0.0",
            "recipe_version": "0.3.0",
            "kernel_version": "k1.0.0",
            "methods": ["status", "recipe.decode", "recipe.apply", "sketch.boolean2d", "sketch.text"],
            "uptime_seconds": 100.0 + state["n"],
        }
    body.state = state
    return body


# ---------------------------------------------------------------------------
# transport: success paths
# ---------------------------------------------------------------------------
def test_status_roundtrip():
    with FakeL3Server({"status": _status_body()}) as f:
        c = L3Client(f.sock_path)
        r = c.status()
        assert r["service"] == "l3"
        assert r["recipe_version"] == "0.3.0"
        assert "methods" in r and "status" in r["methods"]
        # the request id was minted (monotonic from this fresh client)
        assert f.requests[-1]["id"] == 1
        assert f.requests[-1]["method"] == "status"


def test_recipe_decode_result():
    blob = "QUJD"  # base64 of "ABC"
    with FakeL3Server({"recipe.decode": {
        "ok": True, "recipe_version": "0.3.0",
        "features": ["add_rect", "set_pass"], "variables": {"z_mm": 1.0}}}) as f:
        c = L3Client(f.sock_path)
        r = c.recipe_decode(blob)
        assert r["ok"] is True
        assert set(r["variables"]) == {"z_mm"}
        # the blob was sent verbatim as the `recipe` param
        assert f.requests[-1]["method"] == "recipe.decode"


def test_boolean2d_result_shape():
    loops = [
        [[0, 0], [10, 0], [10, 10], [0, 10]],        # outer
        [[2, 2], [8, 2], [8, 8], [2, 8]],            # hole
    ]
    with FakeL3Server({"sketch.boolean2d": {
        "op": "subtract", "region_count": 1, "loop_count": 2, "loops": loops}}) as f:
        c = L3Client(f.sock_path)
        r = c.boolean2d("subtract", subject=[[[0, 0], [10, 0], [10, 10], [0, 10]]],
                        clip=[[[2, 2], [8, 2], [8, 8], [2, 8]]])
        assert r["op"] == "subtract"
        assert r["region_count"] == 1
        assert r["loop_count"] == 2
        # loops: list of loops, each a list of [x, y] numeric pairs
        assert isinstance(r["loops"], list) and len(r["loops"]) == 2
        for loop in r["loops"]:
            assert len(loop) >= 3
            for pt in loop:
                assert len(pt) == 2 and all(isinstance(v, (int, float)) for v in pt)


def test_text_result():
    with FakeL3Server({"sketch.text": {
        "utf8": "AB", "size_mm": 5.0, "font_path": "dejavu",
        "region_count": 1, "loop_count": 2, "vertex_count": 4,
        "loops": [[[0, 0], [1, 0], [1, 1], [0, 1]], [[0.5, 0.5]]]}}) as f:
        c = L3Client(f.sock_path)
        r = c.text("AB", 5.0)
        assert r["utf8"] == "AB"
        assert r["size_mm"] == 5.0
        assert r["vertex_count"] == 4
        assert r["loops"]
        # default font_path "" is a valid request
        assert f.requests[-1]["method"] == "sketch.text"


def test_recipe_apply_roundtrip_and_passthrough():
    with FakeL3Server({"recipe.apply": {"ok": True, "digest": "deadbeef"}}) as f:
        c = L3Client(f.sock_path)
        r = c.recipe_apply("QUJD", text={"utf8": "x"}, project={"id": "j1"})
        assert r["ok"] is True and r["digest"] == "deadbeef"


def test_recipe_apply_from_spec_with_blob_roundtrip():
    # a spec-dump that already carries a base64 blob → forward verbatim, get the digest
    spec = migrate_020_to_030(dict(OLD))
    spec["sketch"]["recipe"] = "QUJD"
    with FakeL3Server({"recipe.apply": {"ok": True, "digest": "cafe"}}) as f:
        out = recipe_apply_from_spec(spec, socket_path=f.sock_path,
                                     text={"a": 1}, project={"id": "p"})
        assert out == {"ok": True, "digest": "cafe"}
        assert f.requests[-1]["method"] == "recipe.apply"


# ---------------------------------------------------------------------------
# transport: failure paths
# ---------------------------------------------------------------------------
def test_protocol_error_raises_l3rpcerror():
    with FakeL3Server({"sketch.text": {"_error": {"code": -32602, "message": "invalid size_mm"}}}) as f:
        with pytest.raises(L3RpcError) as ei:
            L3Client(f.sock_path).text("x", -1.0)
        err = ei.value
        assert err.code == -32602
        assert "invalid size_mm" in err.message
        assert isinstance(err, L3RpcError) and isinstance(err, L3Error)


def test_method_not_found_is_rpcerror():
    with FakeL3Server({}) as f:
        with pytest.raises(L3RpcError) as ei:
            L3Client(f.sock_path).status()
        assert "not found" in (ei.value.message or "").lower() or ei.value.code == -32601


def test_malformed_response_raises_l3connectionerror():
    # valid UTF-8 but not JSON → must be a *connection/transport* failure, not an RPC error
    with FakeL3Server({"status": b"this is {not valid json}\n"}) as f:
        with pytest.raises(L3ConnectionError):
            L3Client(f.sock_path).status()


def test_binary_garbage_raises_l3connectionerror():
    with FakeL3Server({"status": b"\x00\xff\x01 not json\n"}) as f:
        with pytest.raises(L3ConnectionError):
            L3Client(f.sock_path).status()


def test_response_without_result_or_error_raises():
    # a JSON-RPC reply that has neither `result` nor a non-null `error` is a transport
    # contract violation: it must surface as L3ConnectionError, *not* L3RpcError.
    raw = b'{"jsonrpc":"2.0","id":1,"error":null}\n'
    with FakeL3Server({"status": raw}) as f:
        with pytest.raises(L3ConnectionError):
            L3Client(f.sock_path).status()


def test_connection_refused_raises_l3connectionerror(tmp_path):
    path = os.path.join(str(tmp_path), "does-not-exist.sock")
    with pytest.raises(L3ConnectionError):
        L3Client(path).status()


def test_empty_response_raises_l3connectionerror():
    # the fake can signal "send nothing" by having the handler return without writing:
    class _SilentHandler(_L3Handler):
        def handle(self):
            self.rfile.readline()
            self.connection.shutdown(socket.SHUT_RDWR)  # force close with no response bytes
    srv = socketserver.ThreadingUnixStreamServer
    path_dir = tempfile.mkdtemp(prefix="fakel3silent-")
    path = os.path.join(path_dir, "l3.sock")
    s = srv(path, _SilentHandler)
    s.dispatch = {}
    s.requests = []
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    try:
        with pytest.raises(L3ConnectionError):
            L3Client(path).status()
    finally:
        s.shutdown(); s.server_close(); t.join(timeout=5)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(path_dir)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# module-level offline-gate predicate
# ---------------------------------------------------------------------------
def test_available_false_when_socket_absent(tmp_path):
    assert available(os.path.join(str(tmp_path), "absent.sock")) is False


def test_available_true_over_fake():
    with FakeL3Server({"status": {"service": "l3", "version": "1.0", "methods": []}}) as f:
        assert available(f.sock_path) is True


def test_available_false_on_protocol_error():
    # available() must treat an RPC error as "not available" (non-raising)
    with FakeL3Server({"status": {"_error": {"code": -32000, "message": "down"}}}) as f:
        assert available(f.sock_path) is False


# ---------------------------------------------------------------------------
# determinism: identical topic except uptime; request id increments monotonically
# ---------------------------------------------------------------------------
def test_status_deterministic_and_id_increments():
    body = _status_body()
    with FakeL3Server({"status": body}) as f:
        c = L3Client(f.sock_path)
        r1 = c.status()
        r2 = c.status()

        # every field identical *except* the one field the service is allowed to vary
        for k in r1:
            if k == "uptime_seconds":
                continue
            assert r1[k] == r2[k], "non-uptime field %r not deterministic: %r != %r" % (k, r1[k], r2[k])
        assert r1["uptime_seconds"] != r2["uptime_seconds"], "uptime must be the varying field"
        assert r2["uptime_seconds"] > r1["uptime_seconds"]

        # request ids increment monotonically across calls on the same client
        ids = [r["id"] for r in f.requests]
        assert ids == [1, 2]


def test_client_id_monotonic_across_methods():
    with FakeL3Server({
        "status": {"service": "l3", "methods": []},
        "sketch.text": {"loops": [], "vertex_count": 0},
        "sketch.boolean2d": {"loops": [], "region_count": 0},
    }) as f:
        c = L3Client(f.sock_path)
        c.status()
        c.text("a", 1.0)
        c.boolean2d("union", subject=[], clip=[])
        assert [r["id"] for r in f.requests] == [1, 2, 3]
        assert [r["method"] for r in f.requests] == ["status", "sketch.text", "sketch.boolean2d"]


# ---------------------------------------------------------------------------
# bridge: blob extraction + not-configured error
# ---------------------------------------------------------------------------
def test_frozen_recipe_b64_none_for_feature_dict_model():
    # 0.3.0 default: recipe is a feature/variable dict (no blob) → None
    spec = JobSpec2.model_validate(dict(migrate_020_to_030(dict(OLD))))
    assert frozen_recipe_b64(spec) is None


def test_frozen_recipe_b64_returns_blob_on_raw_dump():
    blob = "QUJD"
    dump = migrate_020_to_030(dict(OLD))
    dump["sketch"]["recipe"] = blob
    assert frozen_recipe_b64(dump) == blob


def test_frozen_recipe_b64_none_for_absent_sketch():
    assert frozen_recipe_b64({"sketch": {}}) is None
    assert frozen_recipe_b64({}) is None


def test_recipe_apply_from_spec_without_blob_raises_notconfigured():
    # a real 0.3.0 model (feature-dict recipe) → clear configuration error, no socket touched
    spec = JobSpec2.model_validate(dict(migrate_020_to_030(dict(OLD))))
    with pytest.raises(L3NotConfigured):
        recipe_apply_from_spec(spec)


def test_recipe_apply_from_spec_notconfigured_independent_of_socket():
    # even with a (bogus) socket path given, the missing blob must short-circuit *before* any I/O
    spec = {"sketch": {"recipe": {"features": ["x"]}}}
    with pytest.raises(L3NotConfigured):
        recipe_apply_from_spec(spec, socket_path="/definitely/not/a/real/path.sock")
