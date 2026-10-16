# TaglIAtelle — Specifica

Oct 10, 2026 · @Tommaso Bianchi

*Descrivilo, approva, taglia.*

## Obiettivo e perimetro

TaglIAtelle sostituisce Luban e LightBurn con una webapp in cui descrivi il lavoro a parole, rifinisci i dettagli a mano e la Snapmaker 2.0 A250 lo esegue solo dopo la tua approvazione fisica.

**Macchina:** Snapmaker 2.0 A250, area 250×250 mm, moduli laser 405 nm, laser 1064 nm e CNC, con camera aggiuntiva su Raspberry Pi 5.

- **v1 (E1.0):** solo laser 405 nm, solo lavorazioni vettoriali: testo, forme, SVG/DXF importati; segnatura, taglio, riempimento a tratteggio.
- **Fuori dalla v1:** raster (E1.1), laser 1064 nm (E2), CNC (E3), correzione AI a job in corso, generazione di immagini AI.
- **"Non deterministico"** significa che l'AI propone e adatta; il G-code finale resta ispezionabile e riproducibile: stesso Job Spec, stesso G-code.

## Principi e invarianti di sicurezza

Il modello decide cosa fare, il codice decide come, e nessun componente software può avviare la macchina senza che tu sia presente.

1. **L'AI non scrive G-code.** Produce solo un Job Spec chiamando primitive validate; un compilatore deterministico lo trasforma in toolpath e G-code.
2. **Il tool di esecuzione non è chiamabile dal modello.** Si attiva solo dal gate, legato all'hash esatto del Job Spec approvato. Un prompt injection (ad esempio da testo in un file importato) non può far partire la macchina.
3. **Dal gate in poi nessuna chiamata al modello.** Compilatore, simulatore, invio, watchdog e audit non dipendono dal provider AI. Un job approvato è un pacchetto autocontenuto che un runner a riga di comando esegue senza rete e senza chiavi API; rieseguirlo costa zero token.
4. **Avvio con presenza fisica.** Approvazione nel gate più conferma fisica sul touchscreen della macchina: Start sul touchscreen per ogni job che accende laser o CNC, più il tocco su Yes alla richiesta di connessione «Wi-Fi Connection Request» di ogni sessione nuova. Il file inviato porta l'hash dello spec nel nome, e la telemetria controlla che il job partito sia quello. Se la finestra di tempo scade o lo spec cambia di un byte, l'approvazione decade.
5. **Lo stop è sempre disponibile**, anche da remoto. Restano obbligatori uno stop di emergenza hardware indipendente dal software, un estintore a portata di mano e il laser mai lasciato da solo.
6. **Il watchdog è fail-safe.** Perdita di telemetria o connessione vale come pausa; il silenzio non è mai "tutto ok".
7. **Ai laser arrivano solo parametri approvati.** I file YAML dei materiali sono la fonte di verità; la calibrazione su scarto produce una proposta, mai una scrittura automatica.
8. **Il materiale lo dichiari tu, la camera non lo deduce.** È un campo dello spec, con la sua categoria. I materiali vietati bloccano il job; quelli a rischio richiedono una conferma esplicita nel gate; un materiale assente dai YAML non si lavora senza calibrazione su scarto.
9. **Ogni G-code è riverificato dal simulatore** prima di arrivare al gate: area utile, limiti di potenza e velocità, laser spento negli spostamenti, coerenza con lo spec.
10. **Nessuna lavorazione senza calibrazioni valide.** Ogni plugin di modulo dichiara quelle che richiede, e il gate blocca il job se ne manca una o è scaduta.
11. **Rete privata:** tailnet Tailscale, nessuna esposizione su internet.
12. **Riproducibilità:** font versionati nel repo e versione dei parametri registrata in ogni job, così lo stesso spec dà lo stesso G-code su qualsiasi macchina.

## Architettura

Il modello lavora solo sul Job Spec; compilazione, verifica e avvio sono codice deterministico, e l'avvio passa dal gate e dalla conferma fisica sulla macchina.

&#91;embedded content: architettura · 4 nodi esterni, 8 componenti del backend\]

Compilatore, simulatore e database stanno su the dev server; camera, scansione del pezzo, watchdog e sensore utensile stanno sull'RPi 5, perché sono fisicamente accanto alla macchina. Le immagini restano in locale, tranne il ritaglio dell'area del pezzo inviato al provider AI solo durante l'interview; dal gate in poi nessun componente chiama il cloud.

**Nomi in codice:** l'agente RPi 5 è *il Mattarello* e il gate di approvazione è *la Sfoglia*. Nel repo, nei comandi e negli URL il progetto si chiama `tagliatelle`, minuscolo.

## Job Spec: il primo contratto

Il Job Spec è l'unico artefatto che passa dal gate, e l'unica cosa che compilatore, simulatore, agente RPi e frontend condividono.

- **Costruzione per primitive:** l'AI non emette un JSON monolitico, chiama funzioni; ogni passo è validato, annullabile e visibile mentre l'AI lavora. Le tue modifiche manuali sono le stesse operazioni, nello stesso log di undo.
- **Discriminatore di modulo:** `laser_405`, `laser_1064`, `cnc`. Le primitive comuni sono condivise, quelle specifiche vivono nel plugin del modulo.
- **Tipo di job:** lavorazione oppure `calibration`; stesse regole, stesso compilatore, stesso gate.
- **Versione esplicita dello schema:** un cambio di schema è un evento deliberato (nuova versione, migrazione), mai un effetto collaterale. Ogni componente ha contract test contro lo schema.
- **Valori bloccati:** un campo che tocchi a mano diventa bloccato; l'AI può proporre di cambiarlo ma non lo sovrascrive. A ogni turno l'AI riceve lo stato corrente dello spec con i campi bloccati indicati.
- **Dati della realtà congelati:** il contorno del pezzo misurato dalla camera, la posizione risolta di `center_on_workpiece`, il materiale dichiarato e la versione dei parametri entrano nello spec come numeri e valori fissi. Il compilatore non rilegge mai la camera.
- **Hash:** l'hash dello spec identifica ciò che hai approvato e ciò che verrà eseguito.

Primitive iniziali (l'elenco completo si definisce nello schema v0):

| Primitiva | Modulo | Effetto |
| --- | --- | --- |
| `add_text` | comune | testo convertito in percorsi con font versionati nel repo |
| `add_rect` | comune | forma rettangolare |
| `center_on_workpiece` | comune | centra un oggetto sul contorno del pezzo rilevato, risolto in coordinate prima del gate |
| `fit_to_workpiece` | comune | inserisce testo o disegno nel contorno del pezzo con un margine |
| `set_pass` | laser | potenza, velocità e numero di passate per operazione |
| `set_tool` | cnc | utensile (E3) |
| `set_depth` | cnc | profondità e ordine di lavorazione (E3) |

## Interview ed editing misto

L'interview finisce solo quando lo spec è completo e valido, non quando il modello decide che basta: il backend calcola cosa manca, il modello lo chiede in modo conversazionale.

- **Cosa chiedere è codice:** una funzione deterministica elenca i campi obbligatori mancanti o ambigui (dimensioni del pezzo, materiale, testo, font, posizione, tipo di operazione) e li passa al modello. Ha test propri, perché è lei a garantire che al gate arrivi uno spec completo.
- **Come chiederlo è del modello:** una o poche domande alla volta, con default sensati.
- **Campi già bloccati o compilati a mano** non vengono richiesti di nuovo.
- **Interfaccia:** canvas diretto sull'overlay della camera (trascini, ridimensioni, centri), pannello proprietà (font, dimensioni, offset) e chat laterale. Tutto agisce sullo stesso Job Spec e sullo stesso log di undo.
- **Provider AI astratto:** Claude di default per interview e tool-calling; un'interfaccia unica permette di instradare singoli compiti su un modello locale; il materiale non si riconosce dalle immagini, lo dichiari tu.

## Camera, scansione e gate

La camera misura l'area di lavoro e la forma del pezzo, e l'omografia pixel→mm viene ricalcolata a ogni job con un errore residuo misurato e mostrato prima del via.

- **Registrazione:** camera fissa e 3-4 marker ArUco permanenti agli angoli del piano 250×250. Prima di ogni job il sistema li rileva e ricalcola l'omografia. Se i marker non sono visibili o l'errore residuo supera una soglia, il job non parte.
- **Scansione del pezzo:** la camera rileva il contorno del pezzo (forma, dimensioni in mm, posizione e rotazione sul piano). Si usa visione classica e, dove non basta (pezzi trasparenti, riflettenti o poco contrastati), un modello di segmentazione locale sull'RPi 5. Le immagini restano in locale; al provider AI può andare solo il ritaglio dell'area del pezzo, durante l'interview.
- **Contorno modificabile e congelato:** se il rilevamento sbaglia, lo correggi a mano sul canvas. Il contorno finale entra nello spec come numeri.
- **Lavoro dentro la forma:** `center_on_workpiece` e `fit_to_workpiece` lavorano sul contorno rilevato, non su un rettangolo.
- **Requisiti fisici:** la camera deve inquadrare tutto il piano, e i marker non devono poter essere coperti dal pezzo.
- **Overlay nel gate:** il percorso è proiettato sull'immagine reale del piano. Accanto compaiono materiale dichiarato e categoria, errore residuo, tempo stimato e hash del Job Spec. L'overlay si rigenera a ogni cambio di spec, e l'hash mostrato è quello che verrà eseguito.
- **Frame fisico:** un tasto "frame" fa tracciare alla macchina il contorno del lavoro con laser spento o a potenza minima di puntamento, come controllo prima del via.
- **Materiale:** lo dichiari tu nell'interview; la camera non lo deduce.

**Marker e supporto camera (hardware stampato, 11 ottobre 2026):**

- Marker ArUco `DICT_4X4_50`, ID 0–4, **polarità invertita**: anello del marker chiaro, bit scuri, cornice scura esterna come zona di quiete. Il rilevamento usa sempre `detectInvertedMarker=True`; non si mescolano marker standard e invertiti.
- Tile 36 × 36 × 1,6 mm con marker da 30 mm (stampati al 50% della prima versione da 72 mm; la scala è definitiva). Colore: base scura, rilievo chiaro con cambio filamento a 1,0 mm. Già stampati. L'ID 3 è stato verificato con il decoder OpenCV sulla vista ingrandita.
- Il lato fisico del marker (30 mm) entra nell'omografia pixel→mm come costante di calibrazione: da misurare con il calibro sul pezzo stampato, non da assumere.
- Supporto camera per treppiede: filetto 1/4"-20 UNC femmina modellato nella plastica con gioco radiale di 0,1 mm (nessun dado), asse verticale, parete di 78 mm con sede per la scheda e due fori pilota M2. Sorgente `camera_mount_v3.py` (CadQuery; la v2 con scheda 61 mm era troppo corta), provino del filetto `thread_test` di 12 mm. In stampa; se la vite è stretta si porta `THREAD_CLR` a 0,15–0,2 mm.
- Misure della scheda: lunghezza 62,2 mm (misurata); larghezza 10 mm e interasse fori 5,5 mm prese dalle foto, da verificare con il calibro.

## Materiali

I parametri che arrivano al laser vengono solo da file YAML approvati e versionati; lo storico e l'apprendimento stanno in un database a fianco e non li modificano di nascosto.

- **YAML nel repo = fonte di verità.** Un file per materiale: nome, categoria (ferroso, metallo non ferroso, plastica, legno e così via), spessore, parametri validati per operazione (potenza, velocità, passate, line interval) e flag di divieto. Si parte con pochi materiali che conosci davvero (ad esempio compensato, MDF, cuoio, cartone, acrilico scuro) e con i valori noti di Snapmaker come punto di partenza. Ogni cambio è un commit.
- **Dichiarato, non riconosciuto:** scegli il materiale dall'elenco nell'interview. La categoria decide parametri e limiti e blocca le combinazioni non sensate (ad esempio un metallo nudo con il modulo 405 nm).
- **Conferme e blocchi:** per i materiali a rischio (ad esempio plastiche che possono contenere cloro, come il PVC) il gate chiede una conferma esplicita; i materiali vietati bloccano il job; un materiale assente dai YAML si lavora solo dopo una calibrazione su scarto.
- **SQLite = storico.** Job, griglie di test, foto prima e dopo, esiti. Si aggiunge con la prima calibrazione su scarto.
- **Calibrazione su scarto:** il sistema genera una griglia di test (potenza×velocità) su un angolo di scarto, la camera ne valuta il risultato con analisi classica dell'immagine (contrasto, larghezza della linea), senza modelli e senza token, e il sistema produce una **proposta** di aggiornamento YAML. Tu la approvi; nulla cambia da solo.
- **Tracciabilità:** ogni job registra l'hash o il commit del file YAML con cui è stato compilato, quindi si può sempre rieseguire e spiegare.

## Calibrazioni della macchina

Nessun job parte senza calibrazioni valide, e la calibrazione è automatica e supervisionata dalla camera, con la tua approvazione su ogni correzione.

- **Profilo macchina:** un YAML versionato con le calibrazioni attive, come i materiali; lo storico sta in SQLite. La versione del profilo entra nel pacchetto di ogni job.
- **Procedure come job:** ogni calibrazione è un Job Spec di tipo `calibration`, con lo stesso compilatore, simulatore, gate e pulsante fisico. Potenza massima limitata e area di scarto dichiarata in anticipo.
- **Esito = proposta:** la correzione calcolata si applica solo dopo la tua approvazione. Se supera un limite, la procedura si ferma e ti avvisa.
- **Validità:** ogni calibrazione decade in casi precisi (cambio modulo, camera spostata, cambio utensile, aggiornamento firmware, periodo scaduto). Ogni plugin dichiara quelle che richiede, e il gate blocca il job se ne manca una valida.

| Ambito | Calibrazione | Come si misura |
| --- | --- | --- |
| Comune | distorsione ottica della camera e omografia | scacchiera e marker ArUco, visione classica |
| Comune | offset camera→macchina, scala e ortogonalità degli assi | griglia di punti marcati su scarto, confrontata con le coordinate nominali |
| Laser | fuoco in Z | scala di segni a quote diverse; la larghezza minima della linea indica il fuoco |
| Laser | potenza minima, line interval, kerf | griglia potenza×velocità, misura di contrasto e larghezza |
| CNC | diametro effettivo ed eccentricità dell'utensile | taglio di prova su scarto, misurato dalla camera nel piano XY |
| CNC | lunghezza utensile e zero Z | sensore utensile letto dall'RPi 5 (sotto) |

**Sensore utensile CNC.** La camera non può misurare lo zero Z, quindi serve un sensore. Per quanto emerge dal forum Snapmaker, la A250 non ha una sonda CNC nativa: lo verifichiamo nel task zero.

- **Lettura sull'RPi 5:** il sensore va su un GPIO; l'RPi avvicina l'utensile a passi lenti e invia lo stop al primo segnale, senza modificare il firmware. Dipende dal fatto che la macchina accetti movimenti incrementali.
- **Scelta del sensore:** fotointerruttore a barriera (funziona con qualsiasi utensile) come prima scelta; contatto con clip come alternativa semplice; sensore induttivo solo come ripiego (vede solo utensili metallici); telecamera laterale per diametro e usura come estensione.
- **Fail-safe:** segnale normalmente chiuso, quindi un filo staccato o un fascio coperto valgono come contatto e fermano la discesa.
- **Tensione:** i GPIO dell'RPi sono a 3,3 V; con sensori a 24 V serve un optoisolatore, mai un collegamento diretto.
- **Supporto stampato:** fissa il sensore in una posizione nota, fuori dall'area di lavoro e dai marker ArUco; la posizione si calibra e va nel profilo macchina.
- **Ripetibilità:** da misurare nel task zero, con una previsione scritta prima.

## Esecuzione, watchdog e stop

Durante il job decide solo codice con soglie scritte da te: il modello non interviene, e nessun silenzio del sistema vale come via libera.

- **Watchdog sull'agente RPi 5, a due strati.** La base è deterministica: telemetria e regole fisse (stato della macchina, limiti, comunicazione). Lo strato visivo (fiamma o bagliore, fumo, pezzo spostato rispetto ai marker) è aggiuntivo: visione classica o modello locale, da usare solo se regge gli fps misurati nel task zero. Alla prima violazione manda pausa o stop e ti avvisa.
- **Fail-safe:** se l'agente perde telemetria o connessione, il job va in pausa. Quando lo strato visivo è attivo, la perdita della camera o un ritardo del modello valgono come pausa; il fumo può offuscare la camera, quindi anche la perdita di visibilità è una violazione.
- **Avvio (decisione 2026-10-16, vincolante: ogni job che accende laser o CNC è confermato sullo schermo della macchina; il resto è autonomo):** misurato il 2026-10-16 con la foto del touchscreen. A sessione Wi-Fi aperta lo schermo mostra solo «Disconnect» (nome macchina, moduli, SSID e segnale): dopo `prepare_print` non compare nessuna pagina del file e nessun Start, quindi il tocco di Start non esiste su questo percorso, e `start_print` parte senza tocco (visto con un job vuoto; con un job reale e laser acceso non provato). Il gate non può quindi delegare la conferma a un Start che non c'è. L'unica conferma fisica disponibile via rete è la richiesta «Wi-Fi Connection Request» (tocco su Yes) di una sessione nuova con token nuovo. Decisione confermata da Tommy (2026-10-16), solo per i job che attivano laser o fresa (un job «attivo» = il G-code finale contiene M3/M4 con potenza o velocità diverse da zero, deciso da una scansione deterministica del file; assi, homing, camere e calibrazioni senza laser/utensile non chiedono mai il tocco e restano autonomi): ogni job attivo con laser/CNC apre una sessione nuova, tu tocchi Yes sulla macchina, solo dopo si invia e si avvia il file con l'hash nel nome, e la sessione si chiude a fine job. Alternativa senza rete: file su chiavetta USB e Start sul touchscreen (nessuna automazione).
- **Stop:** sempre azionabile, anche da remoto.
- **Correzione AI a job in corso:** rimandata a dopo la calibrazione su scarto, quando ci saranno dati per fidarsi.

Il watchdog non sostituisce i presidi fisici: stop di emergenza hardware indipendente dal software, estintore, laser mai da solo.

## Comunicazione con la A250

Il collegamento è ibrido: rete per i job normali, seriale dall'RPi 5 per telemetria, stop e interventi live; il protocollo esatto si fissa dopo il task zero.

- **Rete:** upload del job e avvio tramite il protocollo Snapmaker via Wi-Fi o Ethernet. Si parte da qui, perché è il percorso più vicino a ciò che Luban fa oggi. Il codice di Luban serve come riferimento per formati e comandi (header dei file, cambio modulo, offset, protocollo di connessione), senza fork e senza ereditare la licenza AGPL.
- **Seriale:** l'RPi 5 in USB alla macchina per telemetria, stop di emergenza software e interventi live. Si aggiunge dopo.
- **Dove gira cosa:** backend, LLM e generazione toolpath su the dev server; l'RPi 5 è un agente periferico separato (camera, watchdog, sensore utensile, seriale).
- **Rete privata:** accesso solo dalla tailnet Tailscale. La webapp è raggiungibile da remoto per preparare, simulare e vedere l'overlay, ma l'avvio richiede la presenza fisica.
- **Da verificare sulla macchina:** versione firmware della A250, connessione usata oggi con Luban e accettazione di movimenti incrementali, necessaria per il sensore utensile (vedi task zero).

## Test e CI

Tutta la catena si testa senza hardware, e i guasti del watchdog si provano su una macchina simulata invece che su una vera.

- **Golden file:** stesso spec, stesso G-code, confronto byte per byte.
- **Simulatore G-code:** rilegge il G-code prodotto e verifica area utile, limiti di potenza e velocità, laser spento negli spostamenti, coincidenza del percorso con lo spec. Gira in CI e anche a runtime, come secondo livello di sicurezza prima del gate.
- **Runner offline:** un job approvato (pacchetto autocontenuto) gira in CI con la rete disattivata e senza chiavi API; il test fallisce se qualcosa tenta di chiamare un modello.
- **Stack simulato:** finto endpoint Snapmaker, finta seriale, sequenze di immagini registrate per la camera. Cresce insieme ai componenti.
- **Iniezione di guasti:** camera persa, marker coperti, fumo, pezzo spostato, telemetria muta.
- **Test obbligatori del watchdog fail-safe:** una release non passa se uno di questi fallisce.
- **Calibrazioni:** le procedure girano sulla macchina simulata con errori noti iniettati (offset, scala, fuoco, lunghezza utensile); la correzione calcolata deve rientrare in una tolleranza dichiarata, e un esito oltre il limite deve fermare la procedura.
- **Contract test** di ogni componente contro la versione dello schema del Job Spec.

## Audit, conservazione e dati in uscita

Ogni job lascia un pacchetto immutabile sulla tua infrastruttura, così "stesso spec, stesso G-code" si può dimostrare dopo un incidente.

**Pacchetto di audit per job** (append-only, con hash di integrità; a job concluso si può solo aggiungere una nota):

- Job Spec finale e hash, versione YAML dei materiali e del profilo macchina, G-code compilato, esito del simulatore
- foto di registrazione con errore residuo, contorno rilevato e versione dei pesi del modello di visione
- conversazione e operazioni dell'AI
- approvazioni (software e fisica) con orari
- eventi del watchdog, telemetria e, per le calibrazioni, correzioni proposte e applicate

**Conservazione:** i pacchetti di job falliti o stoppati restano integri; quelli riusciti si comprimono o archiviano dopo un periodo da stabilire. Lo storico alimenta SQLite e la calibrazione su scarto.

**Verso il cloud:** camera e modello di visione girano in locale sull'RPi 5. Al provider AI vanno il testo dell'interview e dello spec e, solo durante l'interview, il ritaglio dell'area del pezzo, che viene salvato nell'audit del job. Dal gate in poi non c'è nessuna chiamata al cloud.

## Epic e piano di sviluppo

La v1 è una verticale sottile che attraversa tutta la catena su una macchina finta; solo dopo si aggiungono raster, laser 1064 nm e CNC come nuovi plugin dello stesso schema.

&#91;embedded content: roadmap · 6 fasi, 3 gate\]

| Epic | Contenuto |
| --- | --- |
| E0 Nucleo condiviso | schema del Job Spec, primitive base, interview, gate, API, provider AI, audit, runner offline, agente RPi 5 (scansione, watchdog, sensore utensile), server MCP, profilo macchina e calibrazioni comuni |
| E1 Laser 405 nm | E1.0 vettoriale (v1) ed E1.1 raster; compilatore, simulatore, materiali, calibrazione su scarto, auto-calibrazione laser (offset, scala, fuoco, potenza, kerf) |
| E2 Laser 1064 nm | plugin con database materiali, parametri, rischi e calibrazioni propri (ottica, riflessioni) |
| E3 CNC | plugin con utensile, profondità, fissaggio del pezzo; sensore utensile per lunghezza e zero Z; validatore più complesso |

Ogni modulo è un plugin con tre parti: descrittore delle capacità (area utile, potenza, limiti), compilatore deterministico verso G-code e validatore di sicurezza.

**Come si lavora in parallelo**

- Lo schema del Job Spec si fissa per primo ed è l'unico contratto condiviso: compilatore, simulatore, agente RPi e frontend dipendono dallo schema, non l'uno dall'altro.
- Ogni agente lavora su un branch separato, con merge piccoli e reversibili.
- Un cambio di schema è un evento deliberato: nuova versione e migrazione, mai un effetto collaterale.

## Task zero: la macchina prima del codice

Uno script sulla macchina e sul Raspberry chiude i punti aperti (firmware, connessione, vista della camera, prestazioni del modello di visione, sensore utensile) con dati invece che con ipotesi, prima di scrivere una riga del livello di comunicazione.

**Affermazione da verificare:** la catena fisica (A250 raggiungibile in rete, camera con vista completa del piano, RPi 5 collegato in seriale) regge l'architettura scelta senza modifiche.

Le previsioni sono scritte qui prima di guardare i dati; l'esito resta `pending` finché non si esegue il controllo. Ordine = controllo più economico per primo.

| # | Previsione | Controllo | Se smentita | Esito |
| --- | --- | --- | --- | --- |
| 1 | La camera inquadra tutto il piano 250×250 | Una foto del piano dalla posizione attuale | Spostare la camera o rivedere il montaggio prima dell'omografia | pending |
| 2 | C'è spazio per 3-4 marker ArUco agli angoli, visibili e non coperti dal pezzo | Stessa foto, con marker di prova stampati o disegnati | Riposizionare i marker o aumentare il numero | pending |
| 3 | Luban si collega oggi alla A250 via rete | Leggere la connessione e la versione firmware dalla macchina e da Luban | Partire dalla seriale invece che dalla rete | pending |
| 4 | Il firmware accetta l'upload di un file di prova via rete, senza avviarlo | Upload di un file innocuo con il protocollo ricavato da Luban | Rivedere il protocollo, o far partire il job da seriale | pending |
| 5 | L'RPi 5 raggiunge la A250 in seriale USB e legge lo stato | Elencare le porte seriali e leggere solo lo stato, senza inviare movimenti | Tenere solo la rete e rimandare telemetria e stop via seriale | pending |
| 6 | L'RPi 5 ha 16 GB di RAM (da confermare) | `cat /proc/device-tree/model` e `free -h` | Scegliere un modello di visione più leggero | pending |
| 7 | Un modello di segmentazione piccolo estrae il contorno del pezzo in al massimo 5 s sulla sola CPU (soglia proposta) | Eseguire il modello su una foto del piano e misurare il tempo | Usare solo visione classica, o un modello più leggero | pending |
| 8 | Lo strato visivo del watchdog regge almeno 5 fps sull'RPi 5 (soglia proposta) | Misurare gli fps su una sequenza registrata | Watchdog solo su telemetria e regole fisse; acceleratore come opzione | pending |
| 9 | La macchina accetta movimenti incrementali via seriale o rete | Inviare un movimento minimo in X a macchina libera e leggere lo stato | Cercare un altro modo per leggere il sensore utensile | pending |
| 10 | Il sensore utensile ha deviazione standard ≤ 0,05 mm su 10 tastature consecutive (soglia proposta) | Dieci tastature in sequenza sullo stesso punto | Cambiare tipo di sensore (contatto o ottico) | pending |
| 11 | Il firmware non avvia un job ricevuto da rete senza il comando Start sul touchscreen | Caricare un file innocuo, provare ad avviarlo da rete a macchina libera (senza utensile montato) e leggere lo stato | Tornare al pulsante sui GPIO dell'RPi 5 come conferma fisica obbligatoria | **smentita sul percorso Wi-Fi per l'assenza della pagina Start** (2026-10-16, foto del touchscreen; l'avvio con laser acceso resta da provare; vedi Avvio) |

## Decisioni aperte e prossimi passi

Il perimetro è deciso; restano da fissare valori numerici che dipendono dalla macchina e dall'uso reale.

**Valori da stabilire**

- Soglia di errore residuo dell'omografia ArUco, oltre cui il job non parte
- Durata della finestra tra approvazione nel gate e conferma fisica
- Soglie del watchdog (bagliore, fumo, spostamento del pezzo), più fps e latenza minimi dello strato visivo
- Periodo di conservazione dei pacchetti di job riusciti
- Materiali iniziali dei file YAML, categorie, materiali a rischio e lista dei materiali vietati
- Font da includere e versionare nel repo
- Sensore utensile CNC (fotointerruttore consigliato) e posizione del supporto stampato
- Limite di correzione automatica per ogni parametro di calibrazione
- Durata massima di validità di ciascuna calibrazione

**Prossimi passi**

- [ ] Eseguire il task zero (compresi modello di RPi e RAM, tempi del modello di visione, ripetibilità del sensore utensile) e aggiornare l'esito di ogni previsione
- [ ] Scrivere lo schema v0 del Job Spec con le primitive di E1.0, il tipo `calibration` e il contorno del pezzo
- [ ] Preparare i contract test dello schema
- [ ] Avviare la verticale sottile con gli agenti in parallelo (compilatore, simulatore, agente RPi, frontend)
