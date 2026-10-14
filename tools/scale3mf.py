"""Scala al 50% i marker ArUco .3mf (BambuStudio): 72 mm -> 36 mm, spessore 1.6 -> 0.8 sul piatto.
Uso: python3 -I scale3mf.py ingresso.3mf uscita.3mf
Nota: valori letterali legati al file originale 'aruco_markers.3mf' di Tommy (tessere 72x72x3.2 mm).
I marker stampati sono gia' al 50% (36 mm / marker 30 mm), scala definitiva.
"""
import re, sys, zipfile
src, dst, k = sys.argv[1], sys.argv[2], 0.5
zin = zipfile.ZipFile(src)
zout = zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED)
def fmt(x): return f"{x:.9g}"
for item in zin.infolist():
    data = zin.read(item.filename)
    if item.filename == "3D/Objects/object_1.model":
        t = data.decode("utf-8")
        t = re.sub(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"',
                   lambda m: f'<vertex x="{fmt(float(m[1])*k)}" y="{fmt(float(m[2])*k)}" z="{fmt(float(m[3])*k)}"', t)
        data = t.encode("utf-8")
    elif item.filename == "3D/3dmodel.model":
        t = data.decode("utf-8")
        t = t.replace("90 90 1.60000002", "90 90 0.8")
        data = t.encode("utf-8")
    elif item.filename == "Metadata/model_settings.config":
        t = data.decode("utf-8")
        t = t.replace("1 0 0 90 0 1 0 90 0 0 1 1.6000000238418579 0 0 0 1", "1 0 0 90 0 1 0 90 0 0 1 0.8 0 0 0 1")
        t = t.replace('"source_offset_x" value="113"', '"source_offset_x" value="56.5"')
        t = t.replace('"source_offset_y" value="74.5"', '"source_offset_y" value="37.25"')
        t = t.replace('"source_offset_z" value="1.6000000238418579"', '"source_offset_z" value="0.8"')
        data = t.encode("utf-8")
    zout.writestr(item, data)
zout.close()
# verifica
z = zipfile.ZipFile(dst); t = z.read("3D/Objects/object_1.model").decode()
V = [tuple(map(float, m)) for m in re.findall(r'<vertex x="([^"]+)" y="([^"]+)" z="([^"]+)"', t)]
for i, n in enumerate("xyz"):
    print(n, min(v[i] for v in V), max(v[i] for v in V))
print(re.findall(r'transform="[^"]*90 90[^"]*"', z.read("3D/3dmodel.model").decode()))
print(z.testzip())
