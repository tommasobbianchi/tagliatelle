"""Home all axes (G28) on the Snapmaker via Luban's execute_code, with heartbeat + status trace.
Refuses unless the machine is IDLE with laser power 0. No laser command is sent. Run on the executor."""
import threading, time
import snap

s = snap.Snap(); s.connect()
st = s.status()
print("before:", {k: st[k] for k in ("status", "x", "y", "z", "homed", "toolHead", "laserPower")}, flush=True)
assert st["status"] == "IDLE" and st["laserPower"] == 0, "refusing: machine not idle / laser power not 0"
res = {}


def run():
    try:
        res["r"] = snap._req("/execute_code", b"token=%s&code=G28" % s.token.encode(), timeout=180,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
    except Exception as e:
        res["r"] = "ERR " + repr(e)


t = threading.Thread(target=run); t.start(); t0 = time.time()
while t.is_alive() and time.time() - t0 < 170:
    time.sleep(2)
    try:
        c = s.status()
        print("%3ds %-8s x=%s y=%s z=%s homed=%s" % (time.time() - t0, c["status"], c["x"], c["y"], c["z"], c["homed"]), flush=True)
    except Exception as e:
        print("status err", repr(e)[:60], flush=True)
t.join(5)
print("G28 reply:", res.get("r"))
c = s.status(); print("after:", {k: c[k] for k in ("status", "x", "y", "z", "homed", "laserPower")})
s.disconnect()
