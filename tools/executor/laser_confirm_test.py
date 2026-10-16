"""Prediction #11, real-job version: does the A250 touchscreen ask for Start on a job that turns the laser on?
Sends (prepare_print) a 10 mm relative line at 1% laser power, parked high (Z untouched, beam unfocused), and NEVER calls
start_print. Then traces status for WAIT seconds: if the job runs, the tap on the machine started it.
Needs explicit human confirmation before each run (laser activation). Run on the executor:  python -u laser_confirm_test.py [WAIT]
"""
import sys, time
import snap

WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 90
GCODE = """;Header Start
;header_type: laser
;tool_head: levelTwoLaserToolheadForSM2
;machine: A250
;gcode_flavor: marlin
;renderMethod: line
;max_power: 1
;file_total_lines: 10
;estimated_time(s): 2
;is_rotate: false
;diameter: 0
;max_x(mm): 10
;max_y(mm): 0
;max_z(mm): 0
;max_b(mm): 0
;min_x(mm): 0
;min_y(mm): 0
;min_b(mm): 0
;min_z(mm): 0
;work_speed(mm/minute): 1000
;jog_speed(mm/minute): 3000
;power(%): 1
;work_size_x: 252
;work_size_y: 252
;origin: zero
;Header End
; tagliatelle laser-confirm test: 10 mm at 1%, relative
G21
G91
M3 S2.55
G1 X10 F1000
M5
G90
"""
open("/tmp/tagliatelle_laser_confirm.gcode", "w").write(GCODE)
print(">>> CONNECTING: if the machine asks to allow Wi-Fi, tap Yes", flush=True)
s = snap.Snap(); s.connect()
st = s.status()
print("before:", {k: st[k] for k in ("status", "x", "y", "z", "homed", "laserPower", "printStatus")}, flush=True)
assert st["status"] == "IDLE" and st["homed"] and st["laserPower"] == 0 and st["z"] >= 200, "refusing: not idle/homed/parked high"
try:
    print("prepare_print:", s.prepare("/tmp/tagliatelle_laser_confirm.gcode"), flush=True)
    print(">>> FILE SENT: look at the machine screen now; Start is yours (start_print is NOT sent)", flush=True)
    t0, last = time.time(), None
    while time.time() - t0 < WAIT:
        time.sleep(2)
        try:
            c = s.status()
        except Exception as e:      # the machine stops answering at times: note it, keep the session alive
            print("%3ds status error %s" % (time.time() - t0, repr(e)[:50]), flush=True)
            continue
        cur = (c["status"], c.get("printStatus"), c.get("laserPower"))
        if cur != last or int(time.time() - t0) % 20 < 2:
            print("%3ds %-9s print=%-10s x=%s y=%s laser=%s" % (time.time() - t0, c["status"], c.get("printStatus"), c["x"], c["y"], c.get("laserPower")), flush=True)
            last = cur
finally:
    try:
        c = s.status()
        if c["status"] not in ("IDLE",):
            print("not idle at end -> stop_print:", snap.post_form("/stop_print", token=s.token), flush=True)
    except Exception as e:
        print("final status err", repr(e)[:60])
    print("disconnect:", s.disconnect())
