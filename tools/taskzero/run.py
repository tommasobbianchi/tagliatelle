"""Task zero, read-only stages S0-S2 (no motion, no pairing prompt, nothing written on the machine).
  TZ_PI=user@host TZ_PRINTER=ip python3 tools/taskzero/run.py
S0 executor reachable + camera device   S1 Pi camera: tiles seen + registration gate (valid only at home pose Y=238)
S2 printer reachable (ICMP + TCP 8080 + API answers).  Exit 0 only if every stage passes."""
import json, os, subprocess, sys

PI, PRN = os.environ.get("TZ_PI"), os.environ.get("TZ_PRINTER")
assert PI and PRN, "set TZ_PI=user@host and TZ_PRINTER=ip"
APP = "~/tagliatelle-exec/app"


def ssh(cmd, t=60):
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", PI, cmd], capture_output=True, text=True, timeout=t)
    return r.returncode, r.stdout.strip()


def s0():
    rc, o = ssh("hostname; if test -e /dev/video0; then echo cam; fi")
    return rc == 0 and o.endswith("cam"), o.replace("\n", " ")


def s1():
    rc, o = ssh("cd %s; ~/tagliatelle-exec/bin/python calib.py register" % APP, 90)
    try:
        r = json.loads(o.splitlines()[-1])
    except Exception:
        return False, "no result: " + o[-200:]
    return r["ok"], "ids %s rms %s max %s%s" % (r["ids"], r["rms_mm"], r["max_mm"], "" if r["ok"] else " BLOCKED: " + r.get("why", ""))


def s2():
    rc, o = ssh("if ping -c1 -W3 %s >/dev/null; then echo ping; fi; curl -s -m5 -o /dev/null -w 'http=%%{http_code}' http://%s:8080/api/v1/status" % (PRN, PRN))
    return "ping" in o and "http=4" in o, o.replace("\n", " ")  # unauthenticated /status answers 400 when the API is alive


ok = True
for name, f in (("S0 executor", s0), ("S1 camera+registration", s1), ("S2 printer", s2)):
    try:
        good, msg = f()
    except Exception as e:
        good, msg = False, repr(e)
    ok &= good
    print("%-24s %s  %s" % (name, "PASS" if good else "FAIL", msg))
sys.exit(0 if ok else 1)
