"""Snapmaker 2.0 HTTP client, mirroring Luban's SstpHttpChannel + heartBeat worker (stdlib only).

Protocol (read from Snapmaker/Luban src/server/services/machine/channels/SstpHttpChannel.ts and
task-manager/workers/heartBeat.ts, 2025-05 master):
  POST /api/v1/connect       token=...                  -> JSON {token, series, headType}
  GET  /api/v1/status?token&ts   every 2 s (heartBeat)  -> the screen drops the session after ~8 s of silence
  POST /api/v1/prepare_print multipart token,type(Laser|3DP|CNC),file -> file shows on the touchscreen (Start there)
  POST /api/v1/disconnect    token=...
  (/api/v1/upload is a plain file store: it does NOT put the file on the touchscreen.)

  snap.py status
  snap.py prepare FILE [--hold SECONDS]   upload for the touchscreen, keep the session alive, never starts it
Token: first line of $SNAP_TOKEN_FILE (default ~/tagliatelle-exec/app/snap_token, mode 600).
"""
import http.client, io, json, os, sys, threading, time, urllib.error, urllib.request, uuid
from pathlib import Path

HOST = os.environ.get("SNAP_HOST", "")  # set SNAP_HOST to the printer IP
BASE = "http://%s:8080/api/v1" % HOST
TOKEN_FILE = Path(os.environ.get("SNAP_TOKEN_FILE", "~/tagliatelle-exec/app/snap_token")).expanduser()


class _Conn:
    """One keep-alive connection (measured on the A250: new connection per call = 2/80 timeouts and a 1.15 s p90 from
    SYN retransmits; keep-alive = 0/80, p90 0.46 s).  Retry once when it is safe: any GET, or a POST whose reused
    connection was already closed by the peer (the request never reached the machine)."""
    def __init__(self):
        self.c, self.lock = None, threading.Lock()

    def close(self):
        if self.c:
            self.c.close()
        self.c = None

    def req(self, method, path, data, timeout, headers):
        assert HOST, "set SNAP_HOST to the printer IP"
        with self.lock:
            for attempt in (0, 1):
                reused = self.c is not None
                try:
                    if not reused:
                        self.c = http.client.HTTPConnection(HOST, 8080, timeout=timeout)
                    self.c.sock.settimeout(timeout) if self.c.sock else setattr(self.c, "timeout", timeout)
                    self.c.request(method, "/api/v1" + path, body=data, headers=headers)
                    r = self.c.getresponse()
                    body = r.read()
                    break
                except (OSError, http.client.HTTPException) as e:
                    self.close()
                    safe = method == "GET" or (reused and isinstance(e, (ConnectionError, http.client.RemoteDisconnected)))
                    if attempt or not safe:
                        raise
            if r.status >= 400:
                raise urllib.error.HTTPError(BASE + path, r.status, r.reason, r.headers, io.BytesIO(body))
            return body.decode()


_MAIN, _HB = _Conn(), _Conn()   # the heartbeat has its own connection so a 60 s upload never starves it


def _req(path, data=None, timeout=6, headers=None, conn=None):
    return (conn or _MAIN).req("POST" if data is not None else "GET", path, data, timeout, headers or {})


def post_form(path, **kw):
    return _req(path, "&".join("%s=%s" % kv for kv in kw.items()).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"})


def post_file(path, fields, filename, content, timeout=60):
    b = uuid.uuid4().hex
    body = b"".join(b'--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n' % (b.encode(), k.encode(), v.encode())
                    for k, v in fields.items())
    body += b'--%s\r\nContent-Disposition: form-data; name="file"; filename="%s"\r\nContent-Type: application/octet-stream\r\n\r\n' % (b.encode(), filename.encode())
    body += content + b"\r\n--%s--\r\n" % b.encode()
    return _req(path, body, timeout, {"Content-Type": "multipart/form-data; boundary=" + b})


class Snap:
    def __init__(self, token=None):
        self.token = token or TOKEN_FILE.read_text().split()[0]
        self._stop = threading.Event()

    def connect(self):
        info = json.loads(post_form("/connect", token=self.token))
        self.token = info.get("token", self.token)
        threading.Thread(target=self._beat, daemon=True).start()
        return info

    def _beat(self):
        while not self._stop.wait(2.0):       # Luban: 2 s; silence > 8 s = offline
            try:
                self.status(conn=_HB)
            except Exception as e:             # fail loud, not silent: the caller sees .last_error
                self.last_error = repr(e)

    def status(self, conn=None):
        return json.loads(_req("/status?token=%s&%d" % (self.token, time.time() * 1000), timeout=6, conn=conn))

    def prepare(self, path, type_="Laser"):
        p = Path(path)
        return post_file("/prepare_print", {"token": self.token, "type": type_}, p.name, p.read_bytes())

    def disconnect(self):
        self._stop.set()
        return post_form("/disconnect", token=self.token)


def pair(wait=300):
    """Luban's first-contact flow: connect with an EMPTY token -> the touchscreen asks the user to allow it ->
    reconnect with the token it returned until the machine answers with its series.
    The new token replaces snap_token (old kept as snap_token.old)."""
    import urllib.error
    try:
        r = post_form("/connect", token="")
    except urllib.error.HTTPError as e:
        r = e.read().decode()
        print("first connect HTTP", e.code)
    new = (json.loads(r) if r.strip().startswith("{") else {}).get("token")
    print("first connect: token returned =", bool(new), "| body keys =", sorted(json.loads(r)) if r.strip().startswith("{") else r[:80])
    if not new:
        return None
    try:                                      # measured: presenting the token ONCE raises the on-screen prompt
        print("second connect (token presented):", post_form("/connect", token=new)[:40].replace(new, "<tok>"))
    except Exception as e:
        print("second connect:", repr(e)[:70])
    print("-> TAP 'Yes' ON THE MACHINE SCREEN NOW (not Start)", flush=True)
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(2)                         # also the 2 s heartbeat that keeps the request alive
        try:                                  # status only: re-sending /connect re-raises the prompt (Luban connects once)
            st = json.loads(_req("/status?token=%s&%d" % (new, time.time() * 1000), timeout=3))
        except Exception as e:
            print("  %3ds status not ok: %s" % (time.time() - t0, repr(e)[:70]), flush=True)
            continue                          # empty/non-JSON status = not accepted yet (measured)
        old = TOKEN_FILE.read_text() if TOKEN_FILE.exists() else ""
        TOKEN_FILE.with_name(TOKEN_FILE.name + ".old").write_text(old)
        TOKEN_FILE.write_text(new + "\n")
        os.chmod(TOKEN_FILE, 0o600)
        print("accepted on screen; status =", st.get("status"))
        return new
    print("not accepted within %ds" % wait)
    return None


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "pair":
        sys.exit(0 if pair() else 1)
    s = Snap()
    info = s.connect()
    print("connected:", {k: v for k, v in info.items() if k != "token"})
    try:
        if cmd == "status":
            print(s.status())
        elif cmd == "prepare":
            hold = int(sys.argv[sys.argv.index("--hold") + 1]) if "--hold" in sys.argv else 0
            print("prepare_print:", s.prepare(sys.argv[2]))
            t0 = time.time()
            while time.time() - t0 < hold:
                time.sleep(15)
                print("%3ds status=%s" % (time.time() - t0, s.status().get("status")), flush=True)
    finally:
        print("disconnect:", s.disconnect())


if __name__ == "__main__":
    main()
