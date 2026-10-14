# Marker ArUco (stampati)

- Dizionario `cv2.aruco.DICT_4X4_50`, **ID 0–4** (5 tile).
- Tile 36 × 36 mm, spessore 1,6 mm (stampati al 50% del file originale da 72 mm: scala definitiva). Marker 30 mm (griglia 6×6, celle 5 mm), cornice esterna 3 mm.
- **Polarità invertita**: cornice esterna scura (zona di quiete), anello del marker chiaro, bit scuri. Rilevare con `detectInvertedMarker=True`; il rilevatore standard non li vede (verificato sull'ID 3).
- Realizzazione: base scura, rilievo chiaro, cambio filamento (M600) a 1,0 mm.
- Da fare: misurare con il calibro il lato fisico del marker (30 mm nominali) e usarlo come costante nell'omografia pixel→mm.
- File sorgente (non nel repo, li ha Tommy): `aruco_markers.3mf` (72 mm, originale) e `aruco_markers_36mm.3mf` (scalato con `tools/scale3mf.py`).
- Camera: autofocus OFF per omografia stabile; posizionare 3–4 marker agli angoli del piano 250×250 senza che il pezzo li copra.

Decodifica di riferimento (OpenCV):
```python
d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
p = cv2.aruco.DetectorParameters(); p.detectInvertedMarker = True
det = cv2.aruco.ArucoDetector(d, p)
corners, ids, _ = det.detectMarkers(gray)
```
