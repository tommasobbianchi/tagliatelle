"""Prediction: a fresh token raises the touchscreen prompt every time and only the owner's Yes opens the session.
No laser, no motion: reads status, then disconnects.  Run on the executor:  SNAP_HOST=ip python -u fresh_session_test.py"""
import time
import snap

t0 = time.time()
s = snap.new_session(wait=150, say=lambda m: print(m, flush=True))
print("accepted after %.0f s; status:" % (time.time() - t0), {k: s.status()[k] for k in ("status", "homed", "laserPower")}, flush=True)
time.sleep(10)                                  # heartbeat must keep it up
print("still up after 10 s:", s.status()["status"], flush=True)
print("disconnect:", s.disconnect())
