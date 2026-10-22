# PROMPT MASTER DI SVILUPPO — TaglIAtelle (versione 3, completa)

Data: 22 ott 2026, 13:20. Destinatario: **Claude CLI su nativedev**, in `/home/tommaso/projects/tagliatelle`, come **orchestratore** di lane parallele. Italiano per tutto ciò che è rivolto a Tommy (italiano standard: **mai** l'espressione «ti esco»); identificatori e commenti di codice in inglese.

**Questo file è autosufficiente.** Contiene tutte le decisioni confermate, i contratti, le regole di sicurezza, le lane e i criteri di accettazione. I documenti di progetto servono solo per il dettaglio storico e per il codice esistente. **In caso di divergenza vale questo file**, poi `docs/UX-CONVERSIONE-decisioni-2026-10-22.md` (§15–§20 sopra §11–§14), poi `docs/SPEC.md`, poi `HANDOFF.md`, poi `CLAUDE.md` (che è in parte superato: vedi Appendice A).

Marcatura usata sotto: **[deciso]** = scelto da Tommy · **[proposto]** = proposta mia, da confermare con lui · **[aperto]** = non definito.

---

## 0. Regole di esecuzione (non negoziabili)

1. **Prima di toccare qualsiasi cosa** leggi `CLAUDE.md` e `HANDOFF.md` (regole del progetto e stato dell'hardware), poi il codice delle lane che stai per aprire. Non rileggere documenti già letti nella sessione.
2. **Prima di strumentare o misurare** applica la skill `ai-intuition`: affermazione sintetica + bracci → previsioni scritte come `pending` → il controllo più economico → confronto con i dati. Vale per ogni misura fisica e per ogni verifica sul kernel di orca-cad.
3. **Cambi piccoli e reversibili**, un branch (worktree) per lane. **Niente commit né push senza richiesta esplicita di Tommy**: lascia le modifiche pronte e proponi il commit. Un cambio di schema è un evento deliberato (nuova versione + migrazione + contract test), mai un effetto collaterale.
4. **Un solo artefatto distribuibile** dove ha senso; niente file sparsi inutili.
5. **Risparmio di token**: non ristampare file lunghi in chat; riassumi in poche righe l'esito di ogni passo; spiega solo ciò che Tommy deve decidere.
6. **Tutto ciò che accende laser o fresa richiede il via di Tommy in chat, caso per caso.** Misure fisiche in sola lettura e movimenti senza emissione sono autonomi (accesso autonomo a motori e camere, come da HANDOFF).
7. Stato con la task list; a fine lane: cosa è stato fatto, test verdi, cosa resta, una riga sui rischi.
8. **Se un punto è [aperto] o [proposto], non decidere in silenzio**: implementa dietro un'interfaccia sostituibile e segnalalo a Tommy.

---

## 1. Obiettivo e modello di mediazione

TaglIAtelle rende **semplicissimo** l'accesso a laser 405 nm, laser 1064 nm e CNC sulla **Snapmaker 2.0 A250**. L'uomo pensa al risultato; l'LLM traduce le attese in operazioni sul documento; il **motore deterministico** compila, simula ed esegue; la macchina parte solo dopo approvazione e conferma fisica. Il layer di conversione è centrale e, essendo fisico e non testuale, **il visuale domina l'interfaccia**.

**Un solo oggetto condiviso: il Job Spec** (il documento di lavoro).
- **Uomo**: intenzione e giudizio, sul visuale. Non legge mai JSON né G-code.
- **LLM**: operazioni sul documento, con le **stesse primitive dell'utente** e lo stesso undo. Non produce G-code, non tocca la macchina.
- **Motore deterministico**: risolve, valida, compila, simula, esegue. Stesso documento → stesso hash → stesso G-code.
- **Macchina**: riceve solo ciò che il motore consegna **dopo il gate**.
- **Dal gate in poi: zero chiamate a modelli.** Compilatore, simulatore, invio, watchdog e audit non importano mai il provider AI (test CI, §11).

**Scelta iniziale dell'utente**: solo il modulo (laser 405 / laser 1064 / CNC). Da lì i progetti sono paralleli.

**Ambito [deciso]**: l'UI e i contratti si progettano su **tutti** i casi d'uso; la **consegna procede a gradini** (§8). Primo traguardo: **laser 405 vettoriale, caso B3**.

---

## 2. Stato di partenza (verifica sul codice, non fidarti di questo elenco)

- **Core Python** già presente e con test: `core/jobspec.py` (schema **0.2.0**, hash sha256 canonico, `gate_blockers`; primitive `add_text`, `add_rect`, `center_on_workpiece`, `fit_to_workpiece`, `set_pass`, `set_tool`, `set_depth`), `resolver.py`, `compiler.py` (G-code laser 405 vettoriale deterministico, `S_Scale`, multi-passata, posizionamento risolto), `simulator.py` (limiti, laser-fire, stato modale), `gcode_scan.py` (scanner «job attivo»: M3/M4 con S>0).
- **Esecutore** in `tools/executor/` (`snap.py`, `home.py`, `move.py`, `laser_cam.py`, `camera.py`, `calib.py`, `lens.py`); sull'RPi: `~/tagliatelle-exec`. Task zero in `tools/taskzero/run.py`; hardware in `hardware/` (blocco a gradini per il ToF: `hardware/tof_calib/`).
- Hardware misurato: omografia camera–piano con ArUco **rms 0,085 mm** (leave-one-out 0,30 mm) a posa home **Y=238**. ToF e luce dedicata **non sono montati**.
- HANDOFF dice «nessun codice scritto»: è **superato** (vedi Appendice A).
- Reverse engineering di LightBurn in `~/projects/rea-eng/`: utile per il modello delle impostazioni di taglio, `S_Scale`, flavor GRBL; **`NOTES-C1` è probabilmente errata** (`RDFILEVER8.0.01` è formato Ruida, non `.lbrn2`): non usarla per il formato. Luban (open source) è il riferimento più solido. Non copre editor di sketch né modello di documento.

---

## 3. Componenti e confini

| Componente | Linguaggio / dove | Responsabilità |
|---|---|---|
| **Core** | Python (FastAPI), nativedev | Job Spec, resolver, compilatore, simulatore, scanner job attivo, libreria materiali e ricette, validatore continuo, gate e hash, audit, provider LLM astratto |
| **Kernel sketch** | C++ (orca-cad: `~/projects/orca-cad-primitives`, branch `feature/cad-primitives`; riferimento `docs/CAD-MAP.md`), servizio headless | Sketch parametrico (solver SolveSpace), vincoli, offset, testo, SVG, import STEP, riferimenti di costruzione; esporta profili 2D congelati + ricetta |
| **UI web** | TypeScript [proposto: stack da fissare in L4] | Canvas con overlay camera, chat e proprietà, quattro porte, anteprima a due livelli, undo condiviso |
| **Il Mattarello** | Python su Raspberry Pi 5 | Camera, luce, scansione 2D, ToF (stub finché assente), sessione con la Snapmaker, heartbeat, watchdog, stop, allarmi |
| **Servizio contorno** | Python, nativedev (GPU: verifica con `gpu_status`) | Segmentazione del pezzo dall'immagine camera; le immagini restano in locale |
| **Collegamento macchina** | HTTP porta 8080 della A250 (stesso canale di Luban) su rete privata Tailscale | `connect`/token, `upload`, `prepare_print`, `start_print`, `GET /status?token` ogni 2 s |

**Kernel di orca-cad [verificato su documenti e grep]**: ~10 kLOC in `src/libslic3r/CAD/`; il documento è una **lista di feature + variabili con nome**, tutto il resto derivato da `recompute()`; undo = snapshot; modifiche transazionali; preview = stesso replay con una feature in più. Solver SolveSpace vendored (GPLv3); fork AGPLv3. Rotta MCP (`McpControl`, JSON-RPC su socket Unix + bridge) già disponibile. `SketchEngine` dipende da OCCT (~170 simboli), quindi il servizio è il **kernel completo con OCCT** (si compila già senza GUI, rotta K). Indipendenti da OCCT: `SketchSolver`, `SketchConstraints`, `SketchImport`. **Booleane tra profili 2D: non trovate nello sketch** (esistono sui solidi): da aggiungere con OCCT o ClipperLib. **[aperto]** come nascono i contorni dei glifi del testo; **[aperto]** formato di serializzazione della ricetta. Esiste già «porta gli spigoli di un corpo nello sketch come riferimenti di costruzione»: è il meccanismo per il contorno del pezzo rilevato.

**Licenza [deciso]**: **AGPL accettata**, riuso del kernel così com'è; il kernel resta comunque un **servizio con protocollo JSON-RPC**.

**Sviluppo e distribuzione [deciso]**: sviluppo su **Linux (nativedev)**, poi **macOS**, poi **Windows**. Obiettivo finale: **un solo installabile** con kernel, backend e UI per i tre sistemi sul PC degli altri utenti (l'agente RPi 5 resta accanto alla macchina); **non è della prima consegna**. Rischio noto: impacchettare kernel + OCCT + modello di segmentazione su tre sistemi.

**Provider LLM [deciso]**: interfaccia unica e astratta (Claude di default); per gli altri utenti, **la loro chiave API**.

---

## 4. Contratti: Job Spec 0.3.0

Lane **L0** porta lo schema da 0.2.0 a **0.3.0**, con migrazione esplicita (nessuno spec già approvato diventa invalido in silenzio) e contract test, aggiungendo:

1. **Documento sketch [deciso]**: profili **congelati** (curve e poligoni risolti, numeri fissi, nell'hash) **+ ricetta come sorgente** per riaprire e modificare. Il compilatore non dipende dal solver.
2. **Layer = operazione [deciso]**: palette con colore e impostazioni (incisione, riempimento, taglio; `set_pass`) **nel Job Spec**; il kernel resta geometria pura. Ordine di lavorazione per regole fisse: incisione e riempimento → tagli interni → contorno per ultimo, con spostamenti a vuoto ridotti dentro ogni gruppo e **numeri visibili**.
3. **Contorno del pezzo [deciso]**: geometria di costruzione **bloccata e vincolabile** (centra, margine, tangente al bordo); congelato nello spec come numeri; se l'utente lo corregge si congela il corretto, segnato come modificato.
4. **Primitiva `add_material_grid` [deciso]**: assi, intervalli, passi, etichette di riga/colonna **incise accanto alla griglia**; l'LLM la compila, la geometria la genera il codice, sempre uguale.
5. **Maschera di esclusione [deciso]** (zone già lavorate, B2): segnata dall'utente sul disegno; l'LLM può proporla; nessuna interpretazione automatica delle bruciature.
6. **Testo come oggetto [deciso]**: stringa, font, dimensione, spaziatura; tracciati generati dal motore; **la versione del font entra nell'hash**. Font mancante in un import: conversione col font più vicino tra quelli versionati nel repo, **evidenziata** in anteprima, con possibilità di cambiare font o annullare.
7. **Materiale e pezzo dichiarati all'inizio [deciso]** (categoria, spessore, colore); `calibration` è un tipo di job con le stesse regole e lo stesso gate.
8. **Ricetta di materiale [deciso]**: entità separata (YAML versionati nel repo = verità; SQLite per lo storico): materiale, spessore, modulo, quota Z, versione delle calibrazioni, foto, parametri della cella scelta. **Decade** se cambia la calibrazione, il modulo o la quota Z (avviso e proposta di nuova prova).
9. **Dato 3D nello spec [deciso]**: **solo i numeri usati (spessore e inclinazione)**, congelati nell'hash; la mappa grezza resta nell'audit.
10. **Audit [deciso]**: locale e immutabile per job: spec, hash, G-code, eventi di sessione, conferme, **sblocchi di rischio** (data, categoria, testo dichiarato).
11. **Varianti [deciso]**: rami del documento (copie leggere della ricetta), confrontabili e riprendibili finché non si approva.
12. **Blocco importato [deciso]**: oggetto trasformabile (sposta, ruota, scala) con originale conservato e **hash**; i nodi si sbloccano con un passo esplicito.

---

## 5. Sicurezza (invarianti, ciascuna con un test)

- **Il silenzio non vale «tutto ok»** (watchdog fail-safe). Heartbeat `GET /status?token` ogni 2 s; oltre **8 s** sessione persa → stop e avviso.
- **Conferma fisica [deciso]**: per i job che **accendono laser o fresa** (scanner deterministico del G-code finale: M3/M4 con S>0) = **tocco Yes sulla Snapmaker alla richiesta di connessione con token NUOVO**. **Solo** per quei job: movimenti, frame, prove a secco e scansioni sono autonomi. **Start sul touchscreen solo se il firmware lo permette** (previsione 11 del task zero non conclusa; via Wi-Fi non è mai comparso: misurare, non assumere). **Nessun pulsante GPIO.** Conseguenza da documentare: la richiesta sullo schermo non identifica il job; l'approvazione del contenuto (hash) avviene solo nell'UI.
- **Il token resta solo sull'RPi (modo 600)**; presentarlo una volta per sessione (ripeterlo rialza il prompt). Chi ha il token può avviare job (misurato il 14 ott).
- **Registrazione (la Sfoglia)** alla posa home Y=238, **ripetuta a ogni job, subito prima del gate [deciso]**; blocca se un marker si muove oltre soglia (**0,5/1,0 mm, provvisorie**). Marker ArUco `DICT_4X4_50`, ID 0–4, polarità invertita (`detectInvertedMarker=True`), lato fisico 29,94 mm, autofocus OFF; registrare sempre a Y=238; togliere la carta ChArUco dal piano.
- **Stop** sempre disponibile da remoto. **Stop automatico [deciso]**: telemetria muta, pezzo o marker spostato (oltre soglia), fumo o fiamma dalla camera (opzionale, con falsi positivi), allarmi della macchina.
- **Collegamento perso durante l'emissione [deciso]**: la macchina prosegue da sola e il sistema non può fermarla. Decisione: **emissione solo con utente presente** (heartbeat anche dall'app dell'utente) e **stop fisico dichiarato** (pulsante di emergenza hardware; esiste quello Snapmaker); il silenzio avvisa e ritenta lo stop. **[aperto]**: come si verifica tecnicamente «utente presente» e come si integra il pulsante.
- **Rischi per le persone [deciso]**: fumi pericolosi (es. PVC), riflessione col 1064 su metallo lucido, incendio = **blocchi duri**, sbloccabili solo con **conferma dichiarata per sessione e categoria** («ho aspirazione e protezioni»), scritta nell'audit (data, categoria, testo). **Materiale ignoto: rifiuto** finché non è dichiarata almeno la categoria. **Tetto di potenza per categoria.** La sola resa scarsa (es. 405 su compensato 3 mm) è un **avviso**: decide l'utente.
- **Immagini verso il modello [deciso]**: **a scelta dell'utente per ciascuna immagine**; foto della macchina e del piano non escono mai da sole.
- **Dopo il gate nessuna chiamata a modelli** (test: importa i moduli post-gate e fallisce se trova il provider AI).
- Raspberry Pi 5: `gpiozero` + `lgpio`/libgpiod, mai `RPi.GPIO`; GPIO a 3,3 V. Sull'RPi girano anche il flasher BMCU e `neato-bridge`: **non toccarli**.

---

## 6. Pipeline fisica

**Sessione e parallelismo [deciso].** Appena l'utente sceglie modulo e dichiara materiale e pezzo, partono **da soli, in parallelo all'interview e in sequenza tra loro** (condividono la macchina): controllo macchina (connessione, homing, stato) → registrazione camera e controllo calibrazione → **scansione 2D** → **scansione 3D ToF** (stub finché non montato). Se l'utente finisce prima: **il gate resta bloccato** con stato e stima visibili; si può continuare a disegnare e i vincoli sul contorno si risolvono all'arrivo della scansione 2D.

**Calibrazioni della prima consegna (laser 405 vettoriale) [deciso]**
- **Omografia camera–piano** con ArUco (già misurata).
- **Offset camera → fascio**: segno inciso a bassa potenza su materiale sacrificale, misurato dalla camera (**richiede il tocco Yes**).
- **Fuoco e quota Z**: `G0 Z = focale + spessore dichiarato` (`G54`); **scala di fuoco periodica** per verificare la focale nominale.
- Scala e ortogonalità degli assi: **non** nella prima consegna.
- **Manutenzione**: controllo rapido a ogni sessione; sopra soglia (0,5/1,0 mm, provvisorie) ricalibrazione supervisionata.

**Acquisizione 2D [deciso]**: **una foto alla posa home, dopo la registrazione**; esposizione fissa; correzione ottica e omografia già calibrate. **Luce dedicata controllata dal sistema**: **requisito hardware nuovo, non presente oggi [aperto: posizione, potenza, controllo]**. Overlay sul pezzo: foto di default, video live su richiesta.

**Contorno del pezzo**
- **Modello di segmentazione locale fin dall'inizio [deciso da Tommy; in tensione con SPEC «OpenCV classico, modello solo dove non basta»]**. Default **[proposto]**: gira su **nativedev** (non sull'RPi), **OpenCV classico come ripiego e controllo incrociato**, immagini in locale. Misurare tempo e qualità su acrilico trasparente, metallo lucido, nero su nero.
- Se la confidenza è bassa o il contorno è sbagliato: **l'utente lo corregge o lo disegna sull'immagine**; si congela il corretto, segnalato come modificato.

**Dato 3D (ToF 8×8, quando montato) [deciso]**: verifica di spessore e planarità con avvisi; sicurezza (ostacoli, pezzi rialzati). Scarto tra spessore misurato e dichiarato oltre soglia = **avviso, l'utente conferma il valore da usare** (scritto nello spec). **Mappa di quota per compensare Z: progettata ora, consegnata dopo la validazione** col blocco a gradini (griglia ~30 mm: accuratezza da misurare).

**Produzione dei comandi (compilatore 405 vettoriale)**
- **Kerf per ricetta [deciso]**, applicato dal motore come offset di mezzo kerf; l'anteprima mostra la traiettoria compensata.
- **Passate multiple [deciso]**: stessa quota con ripetizione; **discesa Z solo se la ricetta la dichiara**.
- Ordine di lavorazione come in §4.2.
- Il resto segue `compiler.py`. **[proposto]** entrata/uscita (lead-in/out) e overscan: da proporre a Tommy, non decisi.
- Compilatori e validatori per **1064 e CNC**: plugin dello stesso schema (descrittore delle capacità + compilatore + validatore); **[aperto]**, fuori dalla prima consegna.

---

## 7. UI

- **Centro [deciso]**: **canvas con overlay camera**; chat e proprietà ai lati. **Layout fisso su computer, a scomparsa su tablet** (la chat si apre sopra il canvas e si chiude con un gesto). Dispositivi: computer con mouse e tastiera; **tablet iPad/Android da prevedere** (gesti, bersagli grandi). Il touchscreen dell'RPi non è un editor di disegno.
- **Schermata iniziale [deciso]**: quattro porte, **Importa, Descrivi, Rilancia, Prova materiale**. **Un solo banco**: le porte portano allo stesso canvas e allo stesso documento e preconfigurano pannelli e strumenti (es. la griglia per Prova materiale).
- **Sketch [deciso]**: livello **essenziale + modifica nodi, booleane 2D (da aggiungere al kernel), offset**. **Trascinamento**: anteprima rigida durante il gesto, **solver al rilascio** (valori numerici a ogni Invio).
- **LLM nello sketch [deciso]**: partecipa in **tre modi**: su richiesta dalla chat; **fantasmi** (proposte tratteggiate accettate o scartate con un tocco); **segnalazioni deterministiche senza LLM** (sotto il kerf, tratti sovrapposti, percorsi aperti, fuori area).
- **Validatore deterministico continuo [deciso]**: dettaglio minimo, kerf, raggio fresa quando serve, rischi; evidenzia sul disegno; l'LLM riceve l'elenco e la correzione appare come fantasma.
- **Anteprima a due livelli [deciso]**: **veloce** (geometria, istantanea) e **accurata = replay delle traiettorie del G-code reale** nel simulatore (nessuna simulazione dell'effetto di bruciatura o asportazione). L'accurata mostra: **ordine numerato e direzione (accendibili in entrambe)**, **movimenti a vuoto tratteggiati**, potenza e passate per colore o tratto, **tempo stimato** per operazione e totale, verifiche dei limiti, **replay animato** con cursore (riusato come avanzamento a job in corso). **Ricalcolo** in background a ogni modifica confermata (debounce), indicatore «in aggiornamento», risultato precedente visibile e marcato «non aggiornato». **Cache per layer/operazione** (hash del layer + parametri macchina); **raffinamento progressivo** sui lavori grandi: prima contorno e ordine, poi tempi e potenze, poi replay completo.
- Fattibilità = **avviso** (decide l'utente); rischi = **blocchi** (§5). Avvisi e blocchi stanno **sul disegno**, non in un log.

---

## 8. Casi d'uso: requisiti e ordine di consegna

**Ordine di lavoro [deciso]**: **B3 → A1 → A2**; nella prima consegna entrano anche **B2, B6, B7**. **Fuori dalla prima consegna**: B1, B4, B5, B8. A3: requisiti decisi, **[aperto]** posizione nell'ordine di consegna (propongo dopo A2).

**B3 — Prove materiale (PRIMA VERTICALE) [deciso]**
- L'utente racconta l'obiettivo all'LLM, che compila `add_material_grid`.
- Intervalli: **partendo da un materiale simile in libreria** (regola deterministica su categoria, spessore, colore; l'LLM la spiega). Libreria con **seed dai profili Snapmaker/Luban** e tetti prudenti per categoria. **[aperto]** senza materiale simile: il materiale ignoto resta rifiutato finché non è dichiarata la categoria.
- Prova in **area libera del pezzo vero** (solo incisione e riempimento); **i tagli passanti solo su ritaglio separato**.
- Righe e colonne **incise accanto alla griglia**; l'utente **digita le coordinate** della cella migliore.
- Spessore **dichiarato** (calibro) e verificato dal ToF quando montato; da lì la quota Z.
- Esito: **proposta di ricetta** (materiale, spessore, modulo, Z, versione calibrazioni, foto) in libreria **solo dopo approvazione**. Decade come in §4.8.

**A1 — Importare file [deciso]**
- Ordine: **SVG/DXF → immagini → STEP/STL**.
- Riepilogo di ciò che è stato capito (unità, scala, numero di tracciati, percorsi aperti, duplicati). L'LLM propone le operazioni da colore, layer e spessore del tratto; l'utente conferma **colorando l'anteprima**.
- Scala: il sistema mostra le **dimensioni dedotte in mm** sul pezzo reale e chiede conferma.
- File = **blocco trasformabile** (§4.12). Percorsi aperti: chiusura automatica solo se il vuoto è minimo (tolleranza piccola e dichiarata); gli altri **evidenziati**. Font mancante: §4.6.
- STEP/STL nella prima versione: **profili 2D estratti** (sagoma, sezione a una quota, contorni delle facce piane) trattati come vettoriali; il CAM 3D è un epic successivo (E3).

**A2 — Idee tradotte dall'LLM [deciso]**
- L'LLM costruisce con le **primitive dello sketch** e con **generatori parametrici** per oggetti noti (scatola a incastro, ingranaggio), parametri esposti come cursori.
- 2–3 varianti come **rami del documento**. Vincoli fisici dal validatore continuo.
- Immagini di riferimento: l'LLM le guarda e ricostruisce con primitive; **nessun tracciamento automatico**; l'immagine va al modello solo se l'utente lo sceglie (§5).

**A3 — Rilancio [deciso]**: il lavoro si riapre, si riposiziona sul nuovo contorno e riceve **nuovo spec derivato dal vecchio, nuovo hash e nuovo gate** (l'originale resta intatto). Si archiviano **spec, ricetta sketch, anteprima, esito e foto**; il G-code si rigenera dallo spec. **G-code di terzi (Luban, LightBurn): non nella prima consegna.**

**B2 — Pezzo già lavorato [deciso]**: zone già lavorate = maschera di esclusione dell'utente (§4.5). Seconda faccia: **marker sul piano + contorno rilevato** come riferimento, con nuova registrazione; i punti di riferimento sul pezzo sono geometria di costruzione vincolabile.

**B6 — Verifica prima di lavorare [deciso]**: il frame è **facoltativo, proposto dal sistema**; sul 1064 (infrarosso) = **movimento a laser spento verificato dalla camera con overlay**; prova a secco. Fattibilità: avviso; rischi: blocchi (§5).

**B7 — Recupero e dopo-lavoro [deciso]**: dopo un arresto con possibile perdita di posizione: **homing, nuova registrazione, ripresa dall'inizio dell'operazione corrente**, con anteprima di ciò che è già fatto e conferma fisica come per un nuovo job. Feedback sul risultato: l'utente dice cosa non va («troppo chiaro», «bruciato», «non passante») e l'LLM propone parametri da approvare.

**Fuori dalla prima consegna (decisioni già prese, da realizzare dopo)**
- **B1 Serie**: array e griglie con numero di serie e testo da CSV; nesting automatico su lastra; ripresa dal pezzo K.
- **B4**: il cambio di modulo fisico è un **nuovo progetto sullo stesso pezzo**, con contorno e registrazione ereditati.
- **B5**: rilievo e profondità **entrano prima col laser**: **mappa di profondità tradotta in passate e potenza** (405 e 1064); l'immagine in grigi da file o generata dall'LLM. **[aperto]** come verificare la profondità raggiunta (il ToF 8×8 non misura solchi di millimetri). Tasche, V-carve e foratura restano della CNC.
- **B8**: libreria **locale** (nativedev oggi, PC dell'utente per gli altri). **[aperto]** formato di esportazione/condivisione.

---

## 9. Lane (parallele su branch separati) e dipendenze

**Ordine**: L0 prima; poi tutte le altre in parallelo; L8 integra.

| Lane | Contenuto | Dipende da |
|---|---|---|
| **L0 Schema 0.3.0** | §4 con migrazione e contract test | — |
| **L1 Core materiali e validatore** | libreria materiali e ricette (seed Snapmaker/Luban, tetti per categoria), regola di similitudine, validatore continuo, blocchi di rischio e sblocco con audit, funzione deterministica «cosa manca» per l'interview, audit | L0 |
| **L2 Compilatore e simulatore** | griglia e testo inciso, kerf per ricetta e passate multiple, replay per anteprima (traiettorie, vuoto, tempi, ordine/direzione), cache per layer, raffinamento progressivo, frame e prova a secco | L0 |
| **L3 Kernel-servizio** | build headless Linux, API JSON-RPC (profili 2D congelati, ricetta, vincoli, offset, testo), **booleane 2D**, contorni dei glifi, serializzazione ricetta, riferimenti di costruzione dal contorno del pezzo | L0 (contratto) |
| **L4 UI web** | scheletro (quattro porte, un banco, canvas, overlay foto, chat e proprietà, layout fisso/scomparsa), flusso B3, anteprima a due livelli, undo condiviso, fantasmi, segnalazioni | L0, L2, L3 |
| **L5 Il Mattarello** | calibrazione (home, ArUco, offset camera→fascio, fuoco/Z), scansione 2D (luce dedicata dietro interfaccia, stub finché non montata), stub ToF, sessione e heartbeat (anche dell'utente), watchdog e stop, allarmi, token 600 | L0 |
| **L6 Servizio contorno** | segmentazione locale + ripiego OpenCV, misure su materiali difficili, correzione manuale | L5 (immagini) |
| **L7 Test e CI** | §11 | tutte |
| **L8 Integrazione** | verticale B3 end-to-end su macchina finta, poi sulla A250 con il via di Tommy | L1–L7 |

---

## 10. Criteri di accettazione

**Verticale B3 (la prima)**
1. Su **macchina finta**: dall'interview (obiettivo a parole, materiale e pezzo dichiarati) a griglia con etichette incise, anteprima replay con tempi, gate con hash, G-code, scanner «job attivo», sessione simulata, scelta della cella digitando le coordinate, proposta di ricetta salvata dopo approvazione.
2. **Parità anteprima–macchina**: il replay mostra esattamente le traiettorie compilate.
3. **Fault injection**: telemetria muta, marker spostato, pezzo spostato, camera persa → stop e audit.
4. **Sicurezza**: materiale ignoto rifiutato; categoria a rischio bloccata senza dichiarazione; potenza sopra il tetto bloccata; emissione negata senza utente presente.
5. **Sulla A250 reale** (solo con il via di Tommy): registrazione a Y=238 entro soglia, prova in area libera, tocco Yes con token nuovo, esecuzione, audit completo. Lo Start sul touchscreen è misurato, non assunto.

**A1**: da un SVG con layer colorati → proposta di operazioni → conferma sull'anteprima → dimensioni dedotte confermate → ordine come §4.2 → gate → G-code identico al golden file. Font mancante evidenziato; percorso aperto piccolo chiuso e grande evidenziato; STEP semplice → profili 2D corretti.

**A2**: da una descrizione → almeno due varianti come rami confrontabili; il validatore evidenzia un dettaglio sotto il minimo e la correzione compare come fantasma accettabile con un tocco; un generatore (scatola a incastro) espone i cursori.

**A3**: riapertura di un lavoro archiviato, riposizionamento su un nuovo contorno, nuovo hash e nuovo gate; l'originale resta intatto; senza modifiche il G-code rigenerato ha lo stesso hash dell'originale.

**B2**: nessuna traiettoria compilata cade dentro la maschera di esclusione (test automatico); seconda faccia con nuova registrazione e contorno di riferimento.

**B6**: il frame produce G-code senza emissione (lo conferma lo scanner) e la camera verifica il percorso con overlay; blocchi di rischio sbloccabili solo con dichiarazione scritta nell'audit.

**B7**: dopo uno stop simulato: homing, nuova registrazione, ripresa dall'inizio dell'operazione corrente con anteprima di ciò che è fatto; il feedback produce una proposta di ricetta da approvare.

---

## 11. Test e verifiche (lane L7)

- **Contract test** dello schema 0.3.0 e della migrazione 0.2.0 → 0.3.0; **golden file** di spec → G-code.
- **Simulatore anche a runtime**: ogni G-code passa dal simulatore prima dell'invio (limiti, laser-fire, stato modale).
- **Stack simulato con iniezione di guasti** (camera persa, marker coperti, fumo, pezzo spostato, telemetria muta).
- **Runner offline** (senza rete né chiavi) come test CI.
- **Test «nessun modello dopo il gate»**: i moduli post-gate non importano il provider AI.
- Misure fisiche con `ai-intuition`; nessuna accensione di laser o fresa senza il via di Tommy.

---

## 12. Da decidere o misurare (nessuno è risolto)

| Punto | Default adottato | Chi conferma |
|---|---|---|
| Hosting del modello di segmentazione | nativedev (verificare la GPU), OpenCV di ripiego | Tommy |
| Formato di serializzazione della ricetta di orca-cad | da misurare in L3, poi fissare in L0 | L3 |
| Booleane 2D e contorni dei glifi nel kernel | da aggiungere/verificare | L3 |
| Start sul touchscreen via Wi-Fi (previsione 11) | non assunto; solo Yes | misura con il via di Tommy |
| Soglie di registrazione 0,5/1,0 mm | provvisorie | misura |
| «Utente presente» e pulsante di emergenza hardware | non definiti tecnicamente; l'emissione senza utente presente non parte | Tommy |
| Luce dedicata per la scansione 2D | requisito nuovo: posizione, potenza, controllo | Tommy |
| ToF 8×8 | non montato; stub dietro interfaccia | Tommy |
| B3 senza materiale simile in libreria | materiale ignoto rifiutato finché non è dichiarata la categoria | Tommy |
| Entrata/uscita e overscan del compilatore | da proporre | Tommy |
| Posizione di A3 nell'ordine di consegna | dopo A2 | Tommy |
| Verifica della profondità (B5), formato di condivisione (B8) | non definiti | Tommy |
| Differenze di compilatore e validatore per 1064 e CNC | rimandate (epic E2/E3) | Tommy |
| Installabile unico su tre sistemi | obiettivo finale, non v1 | Tommy |
| Stack dell'UI web | TypeScript, framework da fissare in L4 | Tommy |
| Aggiornare SPEC.md, CLAUDE.md, HANDOFF.md | **proporre i diff** dell'Appendice A, non applicarli | Tommy |

---

## 13. Prima mossa

Leggi `CLAUDE.md` e `HANDOFF.md`, poi il codice di `core/` e `tools/executor/`. Poi **proponi, senza scrivere codice di prodotto**: (a) il piano di L0 con le previsioni `pending` e lo schema 0.3.0 come diff contro 0.2.0; (b) per ogni lane il primo passo verificabile con il suo test; (c) l'elenco delle misure fisiche che richiedono il via di Tommy; (d) i diff dell'Appendice A. **Attendi il suo ok prima di aprire i worktree.**

---

## Appendice A — Correzioni da proporre ai documenti di progetto (non applicare)

- **CLAUDE.md**: «Start sul touchscreen» → conferma fisica = **tocco Yes alla richiesta di connessione con token nuovo, solo per i job che accendono laser o fresa**; Start solo se il firmware lo permette; **nessun GPIO**.
- **SPEC.md**: (1) v1 = solo laser 405 vettoriale → **si progetta su tutti i casi, si consegna a gradini**; (2) «no fork, no AGPL» → **AGPL accettata** per il riuso del kernel di orca-cad; (3) «nessuna immagine verso il cloud tranne il ritaglio del pezzo» → **a scelta dell'utente per ciascuna immagine, foto della macchina e del piano mai da sole**; (4) interview su canvas con **kernel parametrico** dietro; (5) contorno con **modello di segmentazione locale**, OpenCV di ripiego; (6) **un solo installabile** a lungo termine, Linux → macOS → Windows.
- **HANDOFF.md**: «nessun codice scritto» è superato (schema 0.2.0, resolver, compilatore, simulatore, scanner già presenti); la conferma fisica del 14 ott (GPIO) è superata.

## Appendice B — Glossario

- **Job Spec**: il documento di lavoro, unico oggetto condiviso tra uomo, LLM e motore.
- **Gate / la Sfoglia**: approvazione con hash dello spec e registrazione ArUco; da lì in poi nessun modello.
- **Il Mattarello**: l'agente su Raspberry Pi 5 accanto alla macchina.
- **Ricetta (di materiale)**: parametri validati per materiale, spessore, modulo e quota Z. **Ricetta (dello sketch)**: lista di feature e variabili del kernel.
- **Replay**: anteprima accurata ottenuta rieseguendo nel simulatore il G-code reale.
