# HANDOFF — TaglIAtelle (da Claude app/cloud a Claude CLI su server)

Data: 11 ott 2026. Da leggere per intero prima di toccare qualcosa. Poi leggere `docs/SPEC.md`.

## Cos'è
**TaglIAtelle** ("Descrivilo, approva, taglia."): webapp + MCP AI-assisted per la **Snapmaker 2.0 A250** (250×250 mm; laser 405 nm, laser 1064 nm, CNC; camera extra su Raspberry Pi 5, 16 GB da verificare). Sostituisce Luban/LightBurn.
Flusso: interview con l'AI → **Job Spec** (unico artefatto che passa dal gate) → **approvazione** → da qui in poi compilazione, simulazione, invio, watchdog e audit sono **codice deterministico, zero token, nessuna chiamata a modelli** ("stile pre-2026").
Nomi: repo/comandi/URL `tagliatelle` minuscolo; agente RPi 5 = *il Mattarello*; gate di approvazione = *la Sfoglia*.
Controllo dominio/GitHub/marchio per `tagliatelle`: **non fatto**.

## Stato in una riga
Specifica scritta e aggiornata (14 sezioni, 12 principi, task zero con 11 previsioni tutte `pending`). **Nessun codice del software scritto.** Hardware: marker ArUco stampati, supporto camera v2 stampato/in stampa, v3 generato oggi.

## Dove sta cosa
| Percorso | Contenuto |
|---|---|
| `docs/SPEC.md` | Specifica completa (export markdown del doc Claude Docs "TaglIAtelle — Specifica"; i 2 diagrammi, architettura e roadmap, sono persi nell'export). Fonte viva: il doc su claude.ai, id `95568455-d671-4093-bd7a-ac3575e02bd3`. Il file è una copia ~equivalente (differenze di pochi byte nel tail ricostruito): se divergono, vale il doc. Da qui in avanti si può considerare **SPEC.md la fonte di verità** e archiviare il doc. |
| `conversations/conversazione-condensata.md` | Trascrizione condensata della sessione (testo utente + assistente accorciato; tool omessi). Il jsonl completo (3,9 MB) non è stato trasferibile da qui. |
| `hardware/camera_mount/camera_mount_v3.py` | Generatore CadQuery del supporto camera, **v3** (PCB 62,2 mm). `camera_mount_v2.py` = stessa cosa con `PCB_L = 61.0` (quella stampata). |
| `hardware/aruco/README.md` | Dati dei marker stampati. |
| `tools/scale3mf.py` | Scala 50% del .3mf dei marker (storico: già applicata, scala definitiva). |

**Non trasferito** (rigenerabile o già in mano a Tommy): STEP/STL/3MF (si rigenerano: `pip install cadquery && python3 -I camera_mount_v3.py out/`), le 3 foto camera/treppiede, `aruco_markers.3mf` originale (72 mm) e `aruco_markers_36mm.3mf`, `thread_test.*`. Tommy li ha dalla chat.

## Decisioni chiave (dettaglio in SPEC.md)
- Core **Python (FastAPI)** + frontend **TypeScript**, separati; Luban solo come riferimento per formati/comandi Snapmaker (no fork, no AGPL).
- Job Spec costruito dall'AI via **primitive** (`add_text`, `add_rect`, `center_on_workpiece`, `fit_to_workpiece`, `set_pass`, `set_tool`, `set_depth`); schema **versionato** = contratto; moduli come plugin (descrittore capacità + compilatore deterministico + validatore sicurezza); epic: E0 nucleo, **E1 laser 405 = v1 (E1.0 solo vettoriale, raster E1.1)**, E2 laser 1064, E3 CNC.
- **Materiale dichiarato dall'utente** (con categoria: ferroso/metallo/plastica…), non riconosciuto dalla camera. La camera serve a: scansione area di lavoro, forma/dimensioni/posizione del pezzo (contorno congelato nello spec come numeri), registrazione ArUco, watchdog. Vision model specialistico locale sull'RPi 5 **solo dove OpenCV classico non basta**.
- Comunicazione ibrida: rete per i job (si parte da qui), seriale dall'RPi 5 per telemetria/stop. Rete privata Tailscale.
- **Conferma fisica = tasto Start sul touchscreen della A250** (da verificare che valga per i job di rete: previsione 11 del task zero; se smentita torna il pulsante GPIO).
- Watchdog **fail-safe** a due strati (telemetria+regole fisse come base; visione opzionale). Stop sempre disponibile da remoto.
- Test: golden file + simulatore G-code (anche a runtime) + stack simulato con iniezione guasti (camera persa, marker coperti, fumo, pezzo spostato, telemetria muta) + runner offline senza rete/chiavi come test CI.
- Materiali: YAML versionati in repo = verità; SQLite per storico; calibrazione su scarto = **proposta** da approvare.
- Calibrazioni macchina (camera, offset camera→fascio, scala/ortogonalità, fuoco Z, potenza minima/line interval/kerf, CNC diametro/eccentricità/lunghezza utensile) con **auto-calibrazione supervisionata dalla camera**.
- Zero Z CNC: la A250 non ha sonda nativa (evidenza da forum, da verificare nel task zero). Soluzione: **fotointerruttore a barriera** (fail-safe NC) letto da GPIO dell'RPi 5 con optoisolatore se 24 V; alternativa contatto con clip. Usare `gpiozero`+`lgpio`/libgpiod, **non** RPi.GPIO. GPIO a 3,3 V.
- Audit completo locale e immutabile per job; verso il cloud non esce nessuna immagine (solo testo di interview e spec).

## Hardware: stato e numeri
**Marker ArUco**: `cv2.aruco`, `DICT_4X4_50`, ID 0–4, **polarità invertita** (cornice scura 3 mm, anello chiaro, bit scuri) → rilevare sempre con `detectInvertedMarker=True`. Tile 36×36 mm (marker 30 mm, celle 5 mm), spessore 1,6 mm, già stampati. Verificato ID 3 con decoder OpenCV. **Lato fisico misurato col calibro: 29,94 mm (tile 35,8 mm)**; entra nell'omografia come costante. Autofocus camera OFF per omografia stabile.

**Supporto camera** (v3, 32×24×90 mm, ~17,8 cm³): filetto **1/4"-20 UNC femmina modellato nella plastica**, gioco radiale 0,1 mm (`THREAD_CLR`), asse verticale, foro sul piano di stampa; parete 78 mm con sede PCB e 2 fori pilota Ø1,8 per M2.
- v1: dado captivo sul lato sbagliato → scartata. v2: filetto in plastica, PCB_L 61,0 (sede troppo corta). **v3: PCB_L 62,2 (misura reale) → sede 62,8 con 0,3/lato**; top sede a z=88,5 < 90 (ok). Interferenza con vite nominale 0,000 mm³ alla fase di accoppiamento (verificato).
- Da fare: stampare `thread_test` (12 mm) per tarare il gioco; se stretto portare `THREAD_CLR` a 0,15–0,2. Larghezza PCB 10 mm, interasse fori 5,5 mm, distanza fori dal bordo 3,3 mm sono **da foto**, da verificare col calibro.
- Trappole CadQuery/OCC già incontrate: `core.union(ridge)` scarta l'anima (tenere utensili separati, tagliare cresta → anima → cono); test interferenza va fatto scansionando la fase assiale (16 passi su un passo), non ruotando la vite in loco.

## Task zero: evidenza misurata (14 ott 2026, RPi 5 `executor-pi` <executor-ip> + A250 <printer-ip>)
Codice: `tools/executor/` (snap.py, home.py, move.py, laser_cam.py, camera.py, calib.py, lens.py). Sull'RPi: `~/tagliatelle-exec/` (venv + `app/`). Nota: l'RPi ospita anche il flasher BMCU e `neato-bridge`, non toccarli.
- **Rete (previsione 3/4):** canale **HTTP porta 8080** (stesso di Luban; 8888 chiusa). `/api/v1/connect` con token vuoto → il touchscreen mostra "Wi-Fi Connection Request" → **solo Tommy tocca Yes** → token autorizzato. Presentare il token **una volta** in un secondo `/connect` (ripeterlo rialza il prompt). **Heartbeat `GET /status?token` ogni 2 s** (silenzio >8 s = sessione persa). `/upload` è solo uno store; il file arriva al touchscreen con `/prepare_print` (token, type=Laser, file): API risponde "Prepare successfully", **ma sul touchscreen non è comparso nulla** (collegato, l'unico tasto è Disconnect) → **previsione 11 (Start sul touchscreen) FALSA su Wi-Fi, misurato 14 ott**: `POST /api/v1/start_print` (token autorizzato) risponde `{"code":0}` e il job (file solo commenti + G90/G21/M5) passa a `printStatus=Complete` in <2 s **senza alcun tocco sullo schermo e senza movimenti**. Chi ha il token può avviare job: **torna come requisito il pulsante fisico GPIO sull'RPi** (SPEC riga 143) e il token va tenuto solo sull'RPi (modo 600).
- **Movimento (previsione 9 in parte):** `execute_code` G28 homing ok (5 s; posa home X −15,5 Y 238 Z 220); G90 + G1 X0 Y238/Y130 F3000 ok, posizione letta = comandata. **Il piano si muove in Y** (la testa X/Z).
- **Seriale USB (previsione 5):** il cavo mini-USB non enumera sull'RPi (nessun evento kernel). **Non risolta**; la rete basta per ora.
- **Laser camera:** `GET /api/request_capture_photo?index=0&x=186&y=130&z=230&feedRate=3000` (pose Luban per A250 10W; Z si ferma a 220) poi `/api/get_camera_image?index=0`: JPEG 1024×1280, 3,40 px/mm.
- **Camera RPi (ELP 8MP 32e4:8430):** MJPG 3264×2448, **fuoco fisso** (il controllo UVC non ha effetto), esposizione fissa 100 (finestra 80–150), WB fisso; rilevamento tile con `adaptiveThreshConstant=3` (11/12 contro 4/10 di default).
- **Calibrazione:** 4 viti d'angolo del piano (234 × 257 mm, misurate da Tommy) → omografia px→mm; lato tile misurato col calibro 29,94 mm, ricontrollato dalla camera entro −0,08…+0,26 mm. **Distorsione obiettivo** con la carta ChArUco 11×9 (20/10 mm, DICT_4X4_50): rms 0,305 px, k1 0,170 k2 −0,470 (k3=0); correzione fino a ~2,5 mm agli angoli del piano. Validità: r ≲ 1250 px dal centro (copertura della carta).
- **Registrazione (la Sfoglia):** `calib.py register` alla **posa home Y=238**: rms 0,085 mm, max 0,16, leave-one-out 0,30 mm; blocca (exit 2) se un tile si muove (test: 5 mm → 4,9 mm di errore). A Y=130 fallisce (tile oltre la zona calibrata): **registrare sempre a Y=238**. Soglie 0,5/1,0 mm provvisorie (decisione aperta, SPEC riga 237). Gli ID 0–48 della carta ChArUco confliggono con i tile 0–4: toglierla dal piano prima di registrare.
- **Camera della testa (14 ott):** omografia px→mm dai 4 angoli dei tile mappati dalla camera RPi (`tools/executor/head_cam.py`, posa X186 Y130 Z220): 4/5 tile visti (ID 1 mancante), rms 0,17 mm, max 0,35, leave-one-out 0,28–1,23 mm (con 4 tile il LOO è pessimista), 3,40 px/mm, `head_calib.json` sull'RPi. **Distorsione obiettivo della testa non corretta** (servono scatti della carta da questa posa).
- **Aperto:** se i tile vengono spostati, rifare `calib.py calibrate` a Y=238; calibrazione per altre pose non fatta.

## Cosa fare ora (in ordine)
1. **Task zero** sulla macchina/RPi (Tommy esegue, tu prepari lo script). Seguire la sua skill `ai-intuition`: prima di strumentare, scrivere affermazione sintetica + bracci + predizioni `pending`, poi il controllo più economico. Le 11 previsioni sono in SPEC.md → "Task zero". Punti caldi: modello/RAM RPi 5, firmware A250, connessione usata con Luban, **previsione 11 (Start touchscreen)**, tempo di segmentazione, fps watchdog visivo, movimenti incrementali, ripetibilità sensore utensile.
2. Schema v0 del Job Spec (primitive E1.0 + tipo `calibration` + contorno del pezzo) + contract test.
3. Verticale sottile con componenti in parallelo (compilatore, simulatore, agente RPi, frontend), un branch per agente, merge piccoli e reversibili.
4. Controllo nome `tagliatelle` (dominio, GitHub, marchi).
5. Misure col calibro (marker 30 mm, PCB) e test del filetto.

## Preferenze di lavoro di Tommy (rispettarle)
- Italiano, tono diretto da pari; niente "ti esco" (usare "ti preparo/ti fornisco").
- Lavoro **chirurgico e reversibile** ("come un neurochirurgo"); un solo artefatto distribuibile invece di mille file sparsi, dove sensato.
- Tutte le macchine sono Linux. GitHub: (omitted).
- Previsioni scritte prima di misurare; i dati correggono l'intuizione.
- Nessun commit/push senza richiesta. Il repo è inizializzato (`git init`) ma **vuoto di commit**: i file sono untracked.

## Prima mossa suggerita per Claude CLI
```
cd ~/projects/tagliatelle && claude
> Leggi HANDOFF.md e docs/SPEC.md, poi proponi il piano per il task zero con le previsioni scritte (skill ai-intuition) e lo schema v0 del Job Spec. Non scrivere codice del software prima del mio ok.
```
