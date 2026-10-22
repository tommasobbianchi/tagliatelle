# TaglIAtelle — Layer di conversione e UI: decisioni

Data: 22 ott 2026. Frutto dell'interview con Tommy (skill `/interview`). **Non sostituisce SPEC.md**: lo precede nelle parti che riguardano UI, sketch e casi d'uso. Dove i due divergono, vedi §9.

Legenda: **[deciso]** scelto da Tommy · **[proposto]** mia proposta non contestata · **[verificato]** misurato sul codice · **[non verificato]**.

## 1. Scopo e ambito

- Rendere semplicissimo l'accesso a laser 405, laser 1064 e CNC: l'uomo pensa al risultato, l'LLM traduce le attese in linguaggio macchina. **[deciso]**
- Il layer di conversione è centrale; essendo fisico e non testuale, **il visuale domina l'interfaccia**. **[deciso]**
- L'UI si progetta su **tutti** i casi d'uso; la consegna procede per gradini. **[deciso]**
- L'unica scelta iniziale è modulo: laser 405 / laser 1064 / CNC; da lì i progetti sono paralleli (calibrazione in parallelo all'interview). **[deciso]**
- Questa parte si definisce **prima** della pipeline di calibrazione, acquisizione immagini e dati 3D, elaborazione e comandi di lavorazione.

## 2. Modello di mediazione uomo – LLM – macchina [proposto]

Un solo oggetto condiviso, il documento di lavoro (Job Spec). Ruoli stretti:

- **Uomo**: intenzione e giudizio, sul visuale. Non legge mai JSON né G-code.
- **LLM**: traduce l'intenzione in operazioni sul documento. Non produce G-code, non tocca la macchina.
- **Motore deterministico**: risolve, valida, compila, simula, esegue. Stesso documento, stesso G-code.
- **Macchina**: riceve solo ciò che il motore consegna dopo il gate.

Il linguaggio comune è il visuale: ogni operazione dell'LLM è un cambiamento visibile e annullabile; ogni gesto dell'uomo è la stessa operazione nello stesso undo.

**Anteprima: due livelli, una verità.** Veloce (geometria, istantanea) e accurata = **replay delle traiettorie del G-code reale** nel simulatore. **[deciso]** (nessuna simulazione dell'effetto di bruciatura o asportazione in questa fase).

## 3. Casi d'uso e priorità

Ordine di lavoro **[deciso]**: **B3, poi A1, poi A2**.

- **A1** Portare nel fisico file esistenti (SVG/DXF, immagini, STEP/STL).
- **A2** Idee tradotte dall'LLM in elementi 2D/2.5D/3D.
- **A3** Rilancio di lavori vecchi (stesso hash → stesso G-code; riposizionamento = nuovo spec e nuovo gate; G-code di terzi solo traslazione/rotazione + scansione di sicurezza).
- **B1** Serie e personalizzazione (CSV/nomi, nesting, array, ripresa dal pezzo K).
- **B2** Pezzo reale/irregolare/già lavorato (riferimento a feature, zone da escludere, seconda faccia con nuova registrazione).
- **B3** Prove materiale e calibrazione guidata.
- **B4** Sequenze multi-operazione/multi-utensile (il cambio di modulo fisico è una sequenza di progetti sullo stesso riferimento).
- **B5** 2.5D e rilievo, compensazione su superficie non piana con il ToF.
- **B6** Verifica prima di lavorare (frame, prova a secco, fattibilità utensile×materiale, rischi del materiale).
- **B7** Esecuzione, recupero e dopo-lavoro (ripresa dopo interruzione, foto del risultato → proposta di correzione).
- **B8** Esplorazione e libreria (fattibilità, modelli, esportazione del pacchetto).

Requisiti dettagliati definiti finora solo per B3, A1, A2 (qui sotto). B1, B2, B4–B8: solo elencati.

## 4. B3 — Prove materiale [deciso]

- L'utente racconta l'obiettivo all'LLM, che compila una **primitiva di griglia deterministica** (assi, intervalli, passi, etichette). La geometria la genera il codice.
- Punto di partenza: **libreria materiali con seed Snapmaker/Luban** e tetti prudenti per categoria. "Materiale simile" = **regola deterministica** (categoria, spessore, colore); l'LLM la spiega.
- **Materiale ignoto: rifiuto** finché non è dichiarata almeno la categoria.
- La prova si esegue in **area libera del pezzo vero** (incisione e riempimento); **i tagli passanti solo su ritaglio separato**.
- Righe e colonne **incise accanto alla griglia**; l'utente digita le coordinate della cella migliore.
- Spessore **dichiarato** (calibro), verificato dal ToF quando montato; da lì la quota Z.
- Esito: **proposta di ricetta** (materiale, spessore, modulo, quota Z, versione calibrazioni, foto), in libreria solo dopo approvazione.
- **Decadenza**: la ricetta decade se cambia la calibrazione, il modulo o la quota Z (avviso e proposta di nuova prova).

## 5. A1 — Importare file esistenti [deciso]

- Ordine di supporto: **SVG/DXF → immagini → STEP/STL**.
- Operazioni: l'LLM propone da colore, layer e spessore del tratto; l'utente conferma colorando l'anteprima.
- Scala: il sistema mostra le **dimensioni dedotte in mm** sul pezzo reale e chiede conferma.
- Oggetto importato: **blocco trasformabile** con originale conservato (hash); i nodi si sbloccano con un passo esplicito.
- Testo con font mancante: conversione in tracciati col font più vicino tra quelli versionati nel repo, **evidenziata** in anteprima.
- Percorsi aperti: chiusura automatica solo se il vuoto è minimo (tolleranza piccola e dichiarata); gli altri restano evidenziati.
- Ordine di lavorazione: regole fisse (incisione e riempimento → tagli interni → contorno per ultimo), spostamenti a vuoto ridotti dentro ogni gruppo, **numeri visibili** in anteprima.
- STEP/STL: nella prima versione si **estraggono profili 2D** (sagoma, sezione a una quota, contorni delle facce piane) trattati come vettoriali; il CAM 3D resta in E3.

## 6. Sketch 2D [deciso]

- **Base: il kernel di orca-cad** (parametrico, solver di vincoli SolveSpace) come **servizio headless**, con **UI web nuova**. Licenza: **AGPL accettata**, riuso del kernel così com'è.
- Livello strumenti: essenziale + modifica nodi, booleane, offset.
- **Testo**: oggetto (stringa, font, dimensione, spaziatura) modificabile; i tracciati li genera il motore; la versione del font entra nell'hash.
- **Job Spec**: profili **congelati** (numeri fissi, nell'hash) **+ ricetta come sorgente** per riaprire e modificare.
- **Contorno del pezzo** rilevato dalla camera: **geometria di costruzione bloccata e vincolabile** (centra, margine, tangente al bordo); resta congelato nello spec.
- **Operazioni**: layer con colore e impostazioni **nel Job Spec**; il kernel resta geometria pura.
- **Trascinamento**: anteprima rigida durante il gesto, **solver al rilascio** (valori numerici risolti a ogni Invio).
- **LLM nello sketch**: proposte «fantasma» sul disegno, accettate o scartate con un tocco.
- **Dispositivi**: computer con mouse e tastiera; **prevedere UI per iPad/tablet Android** (gesti, bersagli grandi). Il touchscreen dell'RPi 5 non è un editor di disegno.

## 7. A2 — Idee tradotte dall'LLM [deciso]

- L'LLM costruisce con le **primitive dello sketch** (le stesse dell'utente) e con **generatori parametrici** per oggetti noti (scatola a incastro, ingranaggio), parametri esposti come cursori.
- Le 2–3 varianti sono **rami del documento** (copie leggere della ricetta), confrontabili e riprendibili finché non si approva.
- Vincoli fisici (dettaglio minimo, kerf, raggio minimo della fresa): **validatore deterministico continuo**; l'LLM riceve l'elenco e la correzione appare come fantasma.
- Immagini di riferimento: l'LLM le guarda e ricostruisce con primitive; **nessun tracciamento automatico**.

## 8. Cosa si sa di orca-cad [verificato su documenti e grep, non sul codice dello sketch]

Repo vivo: `~/projects/orca-cad-primitives`, branch `feature/cad-primitives`; documento di riferimento `docs/CAD-MAP.md`.

- Kernel senza GUI in `src/libslic3r/CAD/` (~10 kLOC): il documento è **lista di feature + variabili con nome**, tutto il resto derivato da `recompute()`. Undo = snapshot di feature e variabili; modifiche transazionali con rollback; preview = stesso replay con una feature in più.
- Solver SolveSpace vendored (`src/libslic3r/slvs`, GPLv3); fork AGPLv3.
- Rotta MCP (`McpControl`, JSON-RPC su socket Unix + bridge) già disponibile per pilotare il kernel.
- `SketchEngine` dipende da OCCT (header e ~170 simboli in `SketchEngine.cpp`); `SketchInference` per via indiretta. Indipendenti da OCCT: `SketchSolver`, `SketchConstraints`, `SketchImport`. Il servizio sarà quindi il kernel completo con OCCT (si compila già senza GUI nella rotta K).
- Booleane tra profili 2D: **non trovate** nello sketch (esistono `Boolean` sui solidi). Da aggiungere (OCCT o ClipperLib).
- Testo e SVG: «arte 2D rigida» importata come regioni piene. **[non verificato]** come si producono i contorni dei glifi (nessuna classe font OCCT trovata; accenno a FreeType).
- Esiste già «porta gli spigoli di un corpo nello sketch come riferimenti di costruzione»: base del meccanismo per il contorno del pezzo.
- **[non verificato]** formato di serializzazione della ricetta (JSON?) e come viaggerebbe nel Job Spec.

Reverse engineering di LightBurn (`~/projects/rea-eng/`): utile per il modello delle impostazioni di taglio, `S_Scale`, flavor GRBL, separazione seriale/rete; non copre l'editor di sketch né il modello di documento. **`NOTES-C1` probabilmente errata**: `RDFILEVER8.0.01` compare accanto a stringhe Ruida, quindi non è il formato `.lbrn2` (che non è stato misurato). Controllo economico proposto: salvare un progetto minimo dall'AppImage ed esportarne il G-code per confrontarlo con `compiler.py`.

## 9. Da riconciliare con SPEC.md, CLAUDE.md, HANDOFF.md (non modificati)

- SPEC: v1 = solo laser 405 vettoriale. Qui: progettazione su tutti i casi, consegna a gradini.
- SPEC/appunti: «no fork, no AGPL» (riferito a Luban). Qui: **AGPL accettata** per il riuso del kernel di orca-cad.
- CLAUDE.md dice ancora «Start sul touchscreen»; HANDOFF (16 ott sera): conferma fisica = tocco su Yes alla richiesta di connessione con token nuovo, solo per job che accendono laser/fresa. Chiarire se il pulsante GPIO esiste ancora.
- HANDOFF dice «nessun codice scritto»; il git log mostra schema 0.2.0, resolver, compilatore e simulatore già uniti.
- SPEC §Interview: «canvas diretto sull'overlay della camera» — compatibile, ma ora con kernel parametrico dietro.

## 10. Punti aperti (superato dalle sezioni successive)

1. **Struttura dell'UI** per i casi (schermate e modi: importa, descrivi, ripeti, prova materiale).
2. **Specifica del motore di preview** (cosa calcola, quando, cache per hash, raffinamento progressivo).
3. Requisiti di B1, B2, B4–B8.
4. Booleane 2D e origine dei contorni dei glifi nel kernel.
5. Formato di serializzazione della ricetta e suo trasporto nel Job Spec.
6. Pipeline fisica: calibrazione (in parallelo all'interview), acquisizione immagini e dati 3D, elaborazione, comandi di lavorazione.
7. Schema `/anatomy` per verificare la comprensione, poi prompt di sviluppo.

## 11. Aggiornamento — secondo giro (22 ott, mattina)

**Casi d'uso [deciso]**
- **B6** Il frame è **facoltativo, proposto dal sistema**.
- **B1** Servono presto tutti e tre: array e griglie con numero di serie e testo da CSV; nesting automatico su lastra; ripresa dal pezzo K.
- **B2** Secondo fissaggio e seconda faccia: **marker sul piano + contorno rilevato** come riferimento; i punti di riferimento sul pezzo sono geometria di costruzione vincolabile.
- **B7** Dopo un'interruzione: **ripresa dall'inizio dell'operazione in corso**, con nuova registrazione e conferma fisica.
- **B4** Il cambio di modulo fisico è un **nuovo progetto sullo stesso pezzo**, con contorno e registrazione ereditati.
- **B8** Libreria **locale**: su nativedev oggi, **sul PC dell'utente per gli altri utenti**. Formato di esportazione/condivisione: non deciso.

**Preview [deciso]**
- L'anteprima accurata si ricalcola **in background dopo ogni modifica, con debounce**, con indicatore «in aggiornamento».
- Contenuto: movimenti a vuoto tratteggiati; tempo stimato per operazione e totale; replay animato con cursore (usato anche come avanzamento a job in corso); **numeri di ordine e direzione in entrambe le anteprime, accendibili**.
- Cache **per layer/operazione** (hash del layer + parametri macchina).
- Overlay sul pezzo: **foto di default, video live su richiesta**.

**Pipeline fisica [deciso]**
- Appena si sceglie il modulo partono **da soli, in parallelo all'interview**: controllo macchina (connessione, homing, stato), registrazione camera con marker e controllo calibrazione, scansione 2D di piano e pezzo, scansione 3D ToF (quando il sensore sarà montato).
- **L'utente sceglie** se disegnare prima o piazzare prima il pezzo; i vincoli sul contorno si risolvono quando il pezzo arriva.
- Calibrazione: **verifica leggera a ogni sessione, completa solo se fuori soglia**.
- ToF nel primo gradino: **spessore e planarità** per quota Z e fuoco.
- Contorno rilevato sbagliato: l'utente **corregge sul canvas** e si congela quello corretto, segnalato come modificato.

**Conseguenza emersa [aperta]**: se per gli altri utenti il software gira sul loro PC, il kernel (con OCCT) e il resto devono essere distribuibili; sistemi operativi target e modo di distribuzione non sono ancora decisi.

**Aggiornamento di §10**: chiusi, nelle decisioni principali, preview (punto 2), B1/B2/B4/B6/B7/B8 (punto 3) e parte della pipeline fisica (punto 6: parallelismo, pezzo, calibrazione, ToF, contorno). Restano aperti: struttura dell'UI; B5; booleane 2D e glifi; serializzazione della ricetta; sistemi operativi e distribuzione; elaborazione delle immagini e produzione dei comandi in dettaglio; schema `/anatomy` e prompt di sviluppo.

## 12. Aggiornamento — distribuzione, UI, conferma fisica

- **Sistemi target [deciso]**: Linux, Windows e macOS sul PC degli altri utenti.
- **Distribuzione [deciso]**: **un solo installabile** con kernel, backend e UI dentro; l'agente RPi 5 resta accanto alla macchina. Rischio da valutare: impacchettare kernel + OCCT su tre sistemi.
- **Schermata iniziale [deciso]**: quattro porte, **Importa, Descrivi, Rilancia, Prova materiale**, tutte verso lo stesso canvas e lo stesso documento.
- **Conferma fisica [interpretazione da confermare]**: job **con emissione** = tocco su Yes alla richiesta di connessione (token nuovo) **e poi** Start sul touchscreen; job **senza emissione** = autonomi. Problema tecnico noto: in HANDOFF il «Start sul touchscreen» via Wi-Fi non è mai comparso (previsione 11 non conclusa; Luban non mostra un tocco); se il firmware non lo permette serve un'alternativa per la seconda conferma.

## 13. Aggiornamento — conferma, layout, B5

- **Conferma fisica [deciso, confermata la lettura di §12]**: job con emissione = tocco su Yes (token nuovo) **e** Start sul touchscreen; job senza emissione = autonomi.
- **Fallback [deciso]**: se il firmware non permette il Start sul touchscreen via Wi-Fi, **resta come unica conferma il tocco su Yes**. Conseguenza da tenere presente: la richiesta sullo schermo della macchina («Wi-Fi Connection Request») non identifica il job; l'approvazione del contenuto (hash dello spec) avviene solo nell'UI web.
- **Layout [deciso]**: schermo di lavoro **diviso fisso** (canvas e chat sempre visibili). Tensione da risolvere con «il visuale è dominante» e con i tablet: proporzioni e comportamento su schermi piccoli non ancora definiti.
- **B5 [deciso]**: rilievo e profondità **entrano prima, col laser**, con profondità a passate (405 e 1064); requisiti da definire. Tasche, V-carve e foratura restano della CNC.

## 14. Aggiornamento — B5 laser, layout, LLM, immagini

- **B5 laser [deciso]**: la profondità si descrive con una **mappa di profondità tradotta in passate** (e potenza); l'immagine in grigi può venire da file o essere generata/ricostruita dall'LLM. Da definire: come si verifica la profondità raggiunta (la risoluzione 8×8 del ToF non basta a misurare solchi di millimetri).
- **Layout [deciso]**: **fisso su computer, a scomparsa su tablet** (la chat si apre sopra il canvas e si chiude con un gesto). Risolve la tensione di §13.
- **Provider LLM per altri utenti [deciso]**: **la loro chiave API**, con provider astratto (Claude di default, altri modelli tramite l'interfaccia unica).
- **Immagini di riferimento (A2) [deciso]**: possono andare al modello **solo se l'utente lo sceglie per ciascuna immagine**. Foto della macchina e del piano non escono mai da sole. Differisce da SPEC («nessuna immagine verso il cloud, tranne il ritaglio dell'area del pezzo durante l'interview»): da riconciliare.

## 15. Aggiornamento (chat Claude app) — UI, preview, casi per la prima consegna, pipeline fisica [deciso]

**UI e flusso**
- Centro della schermata: **canvas con overlay camera**; chat e proprietà ai lati.
- **Materiale e pezzo si dichiarano all'inizio**, subito dopo la scelta del modulo, così calibrazione e scansioni partono in parallelo all'interview.
- Se l'utente è più veloce delle scansioni: **il gate resta bloccato** con stato e stima visibili; si può continuare a disegnare e i vincoli sul contorno si risolvono all'arrivo della scansione 2D.

**Anteprima accurata (replay delle traiettorie)**
- Mostra: ordine numerato e spostamenti a vuoto; potenza e passate per colore o tratto; tempo stimato e verifiche dei limiti; animazione del replay.
- Ricalcolo: **a ogni modifica confermata, in background**; il risultato precedente resta visibile marcato «non aggiornato» finché il nuovo non è pronto.

**Casi nella prima consegna** (oltre a B3, A1, A2): **B2, B6, B7**. B1 (serie) resta fuori.
- **B2**: le zone già lavorate le segna l'utente sul disegno (maschera di esclusione); l'LLM può proporle. Nessuna interpretazione automatica delle bruciature.
- **B6**: il frame col 1064 (infrarosso, fascio invisibile) è un **movimento a laser spento verificato dalla camera con overlay**. Fattibilità: **sempre avviso, decide l'utente**. Restano però **blocchi** i rischi per le persone (fumi pericolosi, riflessione, incendio) e i due blocchi già decisi (materiale ignoto rifiutato; tetto di potenza per categoria). Come si sblocca un rischio (conferma di protezioni dichiarata, registrata nell'audit) è da definire.
- **B7**: dopo un arresto con possibile perdita di posizione: **homing, nuova registrazione, ripresa dall'inizio dell'operazione corrente**, con anteprima di ciò che è già fatto e conferma fisica come per un nuovo job. Feedback sul risultato: l'utente dice cosa non va ("troppo chiaro", "bruciato", "non passante") e l'LLM propone parametri da approvare.

**Pipeline fisica**
- All'inizio parte da sola, **in sequenza** e in parallelo all'interview: **calibrazione → scansione 2D → scansione 3D** (il ToF non è ancora montato).
- Calibrazioni nella prima consegna (laser 405 vettoriale): **omografia camera–piano con ArUco**, **offset camera → fascio**, **fuoco e quota Z**. Scala e ortogonalità degli assi: non nella prima consegna.
- Manutenzione: **controllo rapido a ogni sessione**; sopra soglia (0,5/1,0 mm, provvisorie) ricalibrazione supervisionata.
- Contorno incerto (acrilico trasparente, metallo lucido, nero su nero): **l'utente corregge o disegna il contorno sull'immagine**; resta nello spec come numeri.
- **Conferma fisica**: solo **tocco Yes sulla Snapmaker alla richiesta di connessione con token nuovo**, per i job che attivano laser o fresa; **nessun pulsante GPIO**. Chiude l'incongruenza di §9 (CLAUDE.md e HANDOFF del 14 ott sono superati).
- Dato 3D (ToF 8×8): verifica di spessore e planarità con avvisi; sicurezza (ostacoli, pezzi rialzati); **mappa di quota per compensare Z: progettata ora, consegnata dopo la validazione** del sensore col blocco a gradini (la griglia è grossolana, accuratezza da misurare).
- **Stop automatico**: telemetria muta (soglia oggi 8 s), pezzo o marker spostato, fumo o fiamma dalla camera (opzionale, rischio di falsi positivi), allarmi della macchina.

## 16. Punti aperti (chat Claude app; da fondere con quelli di §11 e §14)

1. **Schermate per modo**: il centro è deciso; mancano i modi (importa, descrivi, ripeti, prova materiale, frame/verifica, recupero).
2. **Motore di preview**: cache per hash, raffinamento progressivo, replay su lavori grandi.
3. **Sblocco dei blocchi di rischio** (conferma di protezioni dichiarata) e sua registrazione nell'audit.
4. Requisiti non definiti: B1, B4, B5, B8 e la seconda faccia di B2 (nuova registrazione).
5. Kernel di orca-cad: booleane 2D, origine dei contorni dei glifi, formato di serializzazione della ricetta.
6. Elaborazione dati: estrazione del contorno (OpenCV classico o modello), budget di tempo, dove gira.
7. Differenze di compilatore e validatore per 1064 e CNC.
8. Schema `/anatomy` per verificare la comprensione, poi prompt di sviluppo.

## 17. Nota di riconciliazione tra §11–§14 e §15–§16

Le sezioni §11–§14 e §15–§16 sono state scritte da due sessioni diverse nella stessa mattina; la numerazione di §15–§16 è stata corretta (prima duplicava §11–§12). Nessun contenuto è stato rimosso.

- **Conferma fisica — conflitto da risolvere.** §13: job con emissione = tocco Yes (token nuovo) **e** Start sul touchscreen; se il firmware non permette lo Start via Wi-Fi, resta solo Yes. §15: **solo** tocco Yes, nessun GPIO. Lettura che le concilia: *Yes sempre; Start solo se il firmware lo permette* (HANDOFF: lo Start via Wi-Fi non è mai comparso, previsione 11 non conclusa). Da confermare.
- **B1**: §11 «servono presto tutti e tre» e §15 «B1 fuori dalla prima consegna» sono compatibili se «presto» significa subito dopo B2, B6, B7.
- **Parallelismo**: §11 (controllo macchina, registrazione, scansioni in parallelo all'interview) e §15 (calibrazione → 2D → 3D in sequenza) sono compatibili: in parallelo all'interview, in sequenza tra loro perché condividono la macchina.
- **Frame (B6)**: §11 «facoltativo, proposto dal sistema» e §15 «movimento a laser spento verificato dalla camera» si integrano: è un controllo facoltativo, eseguito così.
- **Non ancora riconciliati con §15**: distribuzione come unico installabile su Linux/Windows/macOS (§12) contro il kernel come servizio headless su nativedev (§6); immagini verso il modello a scelta per ciascuna immagine (§14) contro SPEC.

## 18. Risoluzioni (22 ott, 10:38) [deciso]

- **Conferma fisica**: *Yes sempre; Start sul touchscreen solo se il firmware lo permette.* Nessun GPIO. Chiude il conflitto di §17.
- **Kernel e distribuzione**: si sviluppa **per Linux su nativedev**, poi si porta su **macOS**, poi su **Windows**. Il kernel resta servizio headless (§6); l'installabile unico per i tre sistemi (§12) è l'obiettivo finale, non della prima consegna. Rischio noto: impacchettare kernel + OCCT su tre sistemi.
- **Immagini verso il modello**: **a scelta dell'utente per ciascuna immagine**; foto della macchina e del piano non escono mai da sole. Da riconciliare nel testo di SPEC («nessuna immagine verso il cloud, tranne il ritaglio del pezzo durante l'interview»).

## 19. Aggiornamento — verifica delle risposte e terzo giro (22 ott, ~12:50) [deciso]

Riaperti i punti la cui risposta non risultava registrata (le risposte dell'interview non sono leggibili nel log, quindi sono state richieste di nuovo, due domande per volta).

- **Sketch, testo**: confermato — oggetto testo, tracciati generati dal motore, versione del font nell'hash.
- **Sketch, LLM**: partecipa in **tutti e tre** i modi — su richiesta dalla chat, proposte «fantasma», segnalazioni deterministiche senza LLM. **Sostituisce** «solo fantasmi» di §6.
- **B3, intervalli**: da un **materiale simile in libreria**. Senza materiale simile: **[non definito]** (il materiale ignoto resta rifiutato finché non è dichiarata la categoria).
- **A3, rilancio**: **nuovo spec derivato dal vecchio, con nuovo gate**. Si conservano spec, ricetta sketch, anteprima, esito e foto (il G-code si rigenera dallo spec). **G-code di terzi: non nella prima consegna.**
- **Registrazione ArUco**: **a ogni job, subito prima del gate**.
- **Collegamento perso durante l'emissione**: emissione **solo con utente presente** (heartbeat anche dall'app dell'utente) e **stop fisico dichiarato** (pulsante di emergenza hardware); il silenzio avvisa e ritenta lo stop. **[da verificare]** cosa significa tecnicamente «utente presente» e come si integra il pulsante Snapmaker.
- **Offset camera → fascio**: segno inciso a bassa potenza su materiale sacrificale, misurato dalla camera (richiede il tocco Yes).
- **Fuoco e quota Z**: calcolata da focale e spessore dichiarato; **scala di fuoco periodica** per verificare la focale.

## 20. Aggiornamento — quarto giro (22 ott, ~12:55) [deciso]

- **Illuminazione**: luce **dedicata, controllata dal sistema**. **Requisito hardware nuovo, non presente oggi** [da progettare: posizione, potenza, controllo].
- **Acquisizione 2D**: **una foto alla posa home, dopo la registrazione**; esposizione fissa; correzione ottica e omografia già calibrate.
- **ToF**: scarto tra spessore misurato e dichiarato oltre soglia = **avviso, l'utente conferma il valore da usare** (scritto nello spec). Nello spec entrano **solo i numeri usati (spessore e inclinazione)**; la mappa grezza resta nell'audit.
- **Kerf**: per ricetta, applicato dal motore come offset di mezzo kerf; l'anteprima mostra la traiettoria compensata.
- **Passate multiple**: stessa quota con ripetizione; **discesa Z solo se la ricetta la dichiara**.
- **Anteprima su lavori grandi**: cache per layer (hash + parametri macchina) e **raffinamento progressivo** (contorno e ordine → tempi e potenze → replay completo).
- **Schermate**: **un solo banco**; ogni porta preconfigura pannelli e strumenti.
- **Fuori dalla prima consegna e non definiti**: B1, B4, B5, B8; differenze di compilatore e validatore per 1064 e CNC.
