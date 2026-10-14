"""Task-zero prediction #11: can the network start a job without touching the screen?
prepare_print a comment-only file (header + G90/G21/M5: no motion, laser/spindle off), then start_print, then trace status.
Refuses unless IDLE, homed, laserPower 0.  Run on the executor:  python -u start_print_test.py [FILE]
Stops (stop_print) on any status other than IDLE/RUNNING/PAUSED within the trace, and always disconnects.
"""
import json, sys, time, urllib.error
import snap

FILE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/tagliatelle_test2.gcode"
s = snap.Snap(); s.connect()
st = s.status()
print("before:", {k: st[k] for k in ("status", "x", "y", "z", "homed", "laserPower", "printStatus")}, flush=True)
assert st["status"] == "IDLE" and st["homed"] and st["laserPower"] == 0, "refusing: not idle/homed or laser power != 0"
try:
    print("prepare_print:", s.prepare(FILE), flush=True)
    time.sleep(2)
    for name in ("start_print",):
        try:
            r = snap.post_form("/" + name, token=s.token)
        except urllib.error.HTTPError as e:
            r = "HTTP %d %s" % (e.code, e.read().decode()[:120])
        print("%s -> %r" % (name, r), flush=True)
    t0 = time.time()
    while time.time() - t0 < 40:
        time.sleep(2)
        try:
            c = s.status()
        except Exception as e:
            print("status err", repr(e)[:60], flush=True)
            continue
        print("%3ds %-9s print=%-10s x=%s y=%s z=%s laser=%s" % (time.time() - t0, c["status"], c.get("printStatus"), c["x"], c["y"], c["z"], c.get("laserPower")), flush=True)
        if c["status"] == "IDLE" and time.time() - t0 > 6:
            break
finally:
    try:
        c = s.status()
        if c["status"] not in ("IDLE",):
            print("not idle -> stop_print:", snap.post_form("/stop_print", token=s.token), flush=True)
    except Exception as e:
        print("final status err", repr(e)[:60])
    print("disconnect:", s.disconnect())
