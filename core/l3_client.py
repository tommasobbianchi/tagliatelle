"""L3 · the thin, deterministic client for the standalone ``l3_service`` kernel front-end.

``l3_service`` (a.k.a. the orca-cad kernel) is a JSON-RPC 2.0 server over a Unix domain
socket, line-delimited: one JSON object per ``\\n``-terminated line. The wire protocol:

    ->  {"jsonrpc":"2.0","id":<n>,"method":"status"}\\n
    <-  {"jsonrpc":"2.0","id":<n>,"result":{...}}\\n

Methods this client wraps (see the L3 service contract):
    status                    -> {service, protocol, version, recipe_version, kernel_version, ...}
    recipe.decode  {recipe}   -> {ok, recipe_version, features, variables}
    recipe.apply   {recipe}   -> {ok, digest, ...}
    sketch.boolean2d {op,subject,clip} -> {op, region_count, loop_count, loops}
    sketch.text    {utf8,size_mm,font_path} -> {utf8,size_mm,...,loops}

This module is post-gate (runs after the approval gate): it is deterministic and offline —
it uses only the stdlib ``socket``/``json`` and connects to a local Unix socket. It imports
no AI provider. See ``test_no_model_after_gate.py`` for the guard that pins that property.
"""
from __future__ import annotations

import json
import os
import socket
import threading

__all__ = [
    "L3Client",
    "L3Error",
    "L3ConnectionError",
    "L3RpcError",
    "L3NotConfigured",
    "available",
    "DEFAULT_SOCKET_PATH",
    "DEFAULT_TIMEOUT",
]

#: Default location of the ``l3_service`` socket (override with :data:`SNAPORCA_L3_SOCK`).
DEFAULT_SOCKET_PATH = "/tmp/snaporca-l3.sock"
SNAPORCA_L3_SOCK_ENV = "SNAPORCA_L3_SOCK"

#: Default per-call timeout in seconds. Deterministic default; no wall-clock dependency.
DEFAULT_TIMEOUT = 10.0


class L3Error(Exception):
    """Base error for the L3 kernel client. Every L3 failure is a subclass of this."""


class L3ConnectionError(L3Error):
    """Transport-level failure: no socket, connect refused, EOF, timeout, or a response
    that is not a usable JSON-RPC reply (parse error / missing result|error)."""


class L3RpcError(L3Error):
    """A well-formed JSON-RPC *error* response (nonzero ``error.code``).

    Attributes
    ----------
    code:    the JSON-RPC ``error.code`` (int when the service supplies one).
    message: the human-readable ``error.message``.
    id:      the request id the error was attached to, if any.
    """

    def __init__(self, code, message, id=None):
        super().__init__("L3 RPC error %r: %s" % (code, message))
        self.code = code
        self.message = message
        self.id = id

    def __repr__(self):  # pragma: no cover - cosmetic
        return "L3RpcError(code=%r, message=%r, id=%r)" % (self.code, self.message, self.id)

    def __str__(self):
        return "L3 RPC error (code=%r): %s" % (self.code, self.message)


class L3NotConfigured(L3Error):
    """Raised by the bridge when a JobSpec does not carry a frozen base64 kernel-recipe
    blob, so there is nothing for ``recipe.apply`` to send to the kernel."""


def default_socket_path() -> str:
    """Resolve the socket path from :data:`SNAPORCA_L3_SOCK_ENV`, else the default path."""
    return os.environ.get(SNAPORCA_L3_SOCK_ENV) or DEFAULT_SOCKET_PATH


def _recv_line(sock: socket.socket) -> bytes:
    """Read exactly one ``\\n``-terminated response line (or until EOF)."""
    # A fresh buffered reader over the socket, per call (each call opens its own socket).
    f = sock.makefile("rb")  # close=False by default; we only close the wrapper, not the socket
    try:
        return f.readline()
    finally:
        f.close()


class L3Client:
    """A deterministic, connect-per-call JSON-RPC 2.0 client for ``l3_service``.

    Each :meth:`_call` opens a fresh Unix-stream connection, sends one request line,
    reads exactly one response line, and closes. Request ids are minted monotonically on
    this instance (no randomness), so the wire order of any client is fully deterministic.
    """

    def __init__(self, socket_path: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        self.socket_path: str = (
            socket_path if socket_path is not None else default_socket_path()
        )
        self.timeout = timeout
        self._next_id = 1
        self._id_lock = threading.Lock()

    # -- id allocation (monotonic, deterministic) ----------------------------
    def _allocate_id(self) -> int:
        with self._id_lock:
            i = self._next_id
            self._next_id = i + 1
            return i

    # -- core transport -------------------------------------------------------
    def _call(self, method: str, params: dict | None = None,
              timeout: float | None = None) -> dict:
        """Send one JSON-RPC request and return the ``result`` object.

        Raises
        ------
        L3RpcError          on a well-formed JSON-RPC error response.
        L3ConnectionError   on connect/EOF/timeout/parse failure or a reply with
                            neither ``result`` nor ``error``.
        """
        req_id = self._allocate_id()
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        line = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

        timeout = self.timeout if timeout is None else timeout

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                try:
                    sock.connect(self.socket_path)
                except (OSError, socket.timeout) as exc:
                    raise L3ConnectionError(
                        "cannot reach l3_service on %r (%s)" % (self.socket_path, _exc_repr(exc))
                    ) from exc

                try:
                    sock.sendall(line)
                except (OSError, socket.timeout) as exc:
                    raise L3ConnectionError(
                        "send to l3_service on %r failed (%s)" % (self.socket_path, _exc_repr(exc))
                    ) from exc

                try:
                    frame = _recv_line(sock)
                except (OSError, socket.timeout) as exc:
                    raise L3ConnectionError(
                        "read from l3_service on %r failed (%s)" % (self.socket_path, _exc_repr(exc))
                    ) from exc
        except L3Error:
            raise

        # ---- parse the single response line (transport-level failures) ----
        if not frame:
            raise L3ConnectionError(
                "l3_service (%r) closed the connection before a response (method=%r)"
                % (self.socket_path, method)
            )
        try:
            text = frame.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise L3ConnectionError(
                "l3_service returned non-UTF8 response: %r" % (frame[:64],)
            ) from exc
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise L3ConnectionError(
                "l3_service returned malformed JSON (%r): %r" % (frame[:64], exc)
            ) from exc
        if not isinstance(obj, dict):
            raise L3ConnectionError(
                "l3_service response is not a JSON object: %r" % (frame[:64],)
            )

        # ---- protocol-level (error) vs successful (result) reply ----------
        if obj.get("error") is not None:
            err = obj["error"]
            code = err.get("code") if isinstance(err, dict) else None
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise L3RpcError(code=code, message=message, id=obj.get("id"))

        if "result" not in obj:
            raise L3ConnectionError(
                "l3_service response has neither 'result' nor 'error': %r" % (obj, )
            )
        return obj["result"]

    # -- typed wrappers -------------------------------------------------------
    def status(self) -> dict:
        """-> {service, protocol, version, recipe_version, kernel_version, methods, ...}"""
        return self._call("status")

    def recipe_decode(self, recipe_b64: str) -> dict:
        """-> {ok, recipe_version, features, variables}"""
        return self._call("recipe.decode", {"recipe": recipe_b64})

    def recipe_apply(self, recipe_b64: str,
                     text: dict | None = None,
                     project: dict | None = None) -> dict:
        """-> {ok, digest, ...}. ``text``/``project`` are optional passthrough payloads."""
        params = {"recipe": recipe_b64}
        if text is not None:
            params["text"] = text
        if project is not None:
            params["project"] = project
        return self._call("recipe.apply", params)

    def boolean2d(self, op: str, subject: list, clip: list) -> dict:
        """2D boolean op. -> {op, region_count, loop_count, loops (list of [x,y] loops)}"""
        return self._call("sketch.boolean2d", {"op": op, "subject": subject, "clip": clip})

    def text(self, utf8: str, size_mm: float, font_path: str = "") -> dict:
        """Outline text to loops. -> {utf8, size_mm, font_path, region_count, loop_count, ...}"""
        return self._call("sketch.text", {"utf8": utf8, "size_mm": size_mm, "font_path": font_path})


def available(socket_path: str | None = None) -> bool:
    """Official offline-gate predicate: is a reachable ``l3_service`` answering right now?

    Attempts a single ``status`` round-trip and returns True only on a successful result.
    Non-raising: any failure (no socket, refused, EOF, timeout, malformed reply, protocol
    error) simply yields False, so callers can gate the whole feature on this one call.
    """
    path = socket_path if socket_path is not None else default_socket_path()
    if not path:
        return False
    try:
        L3Client(path).status()
    except Exception:  # noqa: BLE001 - this is a probe: *any* failure means "not available"
        return False
    return True


def _exc_repr(exc: BaseException) -> str:
    return exc.strerror if getattr(exc, "strerror", None) else exc.__class__.__name__
