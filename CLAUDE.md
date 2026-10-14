# TaglIAtelle

Webapp + MCP AI-assisted per Snapmaker 2.0 A250 (laser 405/1064 nm, CNC). Specifica: `docs/SPEC.md`. Stato e decisioni: `HANDOFF.md` (leggere per primo).

## Regole del progetto
- Dal gate di approvazione in poi: **nessuna chiamata a modelli**, tutto deterministico (compilatore, simulatore, invio, watchdog, audit). Mai importare il provider AI in quei moduli.
- Il Job Spec (schema versionato) è l'unico contratto tra componenti. Cambio di schema = evento deliberato (nuova versione + migrazione).
- Watchdog fail-safe: il silenzio non vale "tutto ok". Nessun avvio di macchina senza conferma fisica (Start sul touchscreen) e hash dello spec.
- Marker ArUco: `DICT_4X4_50`, ID 0–4, polarità invertita → `detectInvertedMarker=True`.
- Raspberry Pi 5: `gpiozero`+`lgpio`/libgpiod, non RPi.GPIO; GPIO a 3,3 V.
- Prima di strumentare o misurare: skill `ai-intuition` (previsioni scritte `pending`, poi il controllo più economico).
- Python (FastAPI) per il core, TypeScript per il frontend; repo/comandi/URL `tagliatelle` minuscolo.
- Cambi piccoli e reversibili, un branch per componente. Italiano nei testi rivolti a Tommy. Niente commit/push senza richiesta.
- Hardware CAD: `hardware/camera_mount/` (CadQuery, `pip install cadquery`, eseguire con `python3 -I`).
