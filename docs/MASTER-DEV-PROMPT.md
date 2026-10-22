# MASTER DEVELOPMENT PROMPT — TaglIAtelle (version 3, complete, English)

Date: 22 Oct 2026, 13:25. Recipient: **Claude CLI on nativedev**, in `/home/tommaso/projects/tagliatelle`, acting as **orchestrator** of parallel lanes. Everything addressed to Tommy is in **English**. Identifiers and code comments are in English.

**This file is self-contained.** It holds every confirmed decision, the contracts, the safety rules, the lanes and the acceptance criteria. The project documents are only for historical detail and for the existing code; note that they are **written in Italian** (`SPEC.md`, `HANDOFF.md`, `CLAUDE.md`, `docs/UX-CONVERSIONE-decisioni-2026-10-22.md`). **On any conflict this file wins**, then `UX-CONVERSIONE` (§15–§20 over §11–§14), then `SPEC.md`, then `HANDOFF.md`, then `CLAUDE.md` (partly superseded: see Appendix A).

An Italian version of this prompt exists at `docs/PROMPT-SVILUPPO-MASTER.md`. Do not use it; this file is the one to follow.

Tags used below: **[decided]** = chosen by Tommy · **[proposed]** = my proposal, to be confirmed with him · **[open]** = not defined.

---

## 0. Execution rules (non-negotiable)

1. **Before touching anything**, read `CLAUDE.md` and `HANDOFF.md` (project rules and hardware state), then the code of the lanes you are about to open. Do not re-read documents already read in the session.
2. **Before instrumenting or measuring**, apply the `ai-intuition` skill: one-sentence claim + arms → predictions written down as `pending` → the cheapest check → compare with the data. This applies to every physical measurement and every check on the orca-cad kernel.
3. **Small, reversible changes**, one branch (worktree) per lane. **No commits or pushes without Tommy's explicit request**: leave the changes ready and propose the commit. A schema change is a deliberate event (new version + migration + contract test), never a side effect.
4. **One single deployable artifact** wherever it makes sense; no pointless scattered files.
5. **Save tokens**: do not reprint long files in chat; summarise the outcome of each step in a few lines; explain only what Tommy has to decide.
6. **Anything that turns on the laser or the spindle needs Tommy's go-ahead in chat, case by case.** Read-only physical measurements and movements without emission are autonomous (autonomous access to motors and cameras, per HANDOFF).
7. Report status with the task list; at the end of each lane: what was done, tests green, what remains, one line on risks.
8. **If an item is [open] or [proposed], do not decide silently**: implement it behind a replaceable interface and flag it to Tommy.

---

## 1. Goal and mediation model

TaglIAtelle makes access to the 405 nm laser, the 1064 nm laser and the CNC on the **Snapmaker 2.0 A250** **extremely simple**. The human thinks about the result; the LLM translates expectations into operations on the document; the **deterministic engine** compiles, simulates and executes; the machine starts only after approval and physical confirmation. The conversion layer is central and, being physical and not textual, **the visual dominates the interface**.

**One shared object: the Job Spec** (the working document).
- **Human**: intent and judgement, on the visual. Never reads JSON or G-code.
- **LLM**: operations on the document, using the **same primitives as the user** and the same undo. Does not produce G-code and does not touch the machine.
- **Deterministic engine**: resolves, validates, compiles, simulates, executes. Same document → same hash → same G-code.
- **Machine**: receives only what the engine delivers **after the gate**.
- **From the gate onward: zero model calls.** Compiler, simulator, dispatch, watchdog and audit never import the AI provider (CI test, §11).

**The user's only initial choice**: the module (laser 405 / laser 1064 / CNC). From there, projects run in parallel.

**Scope [decided]**: the UI and the contracts are designed for **all** use cases; **delivery proceeds in steps** (§8). First milestone: **laser 405 vector, use case B3**.

---

## 2. Starting state (verify against the code, do not trust this list)

- **Python core** already present and tested: `core/jobspec.py` (schema **0.2.0**, canonical sha256 hash, `gate_blockers`; primitives `add_text`, `add_rect`, `center_on_workpiece`, `fit_to_workpiece`, `set_pass`, `set_tool`, `set_depth`), `resolver.py`, `compiler.py` (deterministic 405 vector G-code, `S_Scale`, multi-pass, resolved placement), `simulator.py` (limits, laser-fire, modal state), `gcode_scan.py` ("active job" scanner: M3/M4 with S>0).
- **Executor** in `tools/executor/` (`snap.py`, `home.py`, `move.py`, `laser_cam.py`, `camera.py`, `calib.py`, `lens.py`); on the RPi: `~/tagliatelle-exec`. Task zero in `tools/taskzero/run.py`; hardware in `hardware/` (step block for the ToF: `hardware/tof_calib/`).
- Measured hardware: camera–plane homography with ArUco **rms 0.085 mm** (leave-one-out 0.30 mm) at home pose **Y=238**. The ToF and the dedicated light are **not mounted**.
- HANDOFF says "no code written": that is **superseded** (see Appendix A).
- LightBurn reverse engineering in `~/projects/rea-eng/`: useful for the cut-settings model, `S_Scale`, GRBL flavours; **`NOTES-C1` is probably wrong** (`RDFILEVER8.0.01` is the Ruida format, not `.lbrn2`): do not use it for the format. Luban (open source) is the more solid reference. It covers neither the sketch editor nor the document model.

---

## 3. Components and boundaries

| Component | Language / where | Responsibility |
|---|---|---|
| **Core** | Python (FastAPI), nativedev | Job Spec, resolver, compiler, simulator, active-job scanner, materials and recipes library, continuous validator, gate and hash, audit, abstract LLM provider |
| **Sketch kernel** | C++ (orca-cad: `~/projects/orca-cad-primitives`, branch `feature/cad-primitives`; reference `docs/CAD-MAP.md`), headless service | Parametric sketch (SolveSpace solver), constraints, offset, text, SVG, STEP import, construction references; exports frozen 2D profiles + recipe |
| **Web UI** | TypeScript [proposed: stack to be fixed in L4] | Canvas with camera overlay, chat and properties, four doors, two-level preview, shared undo |
| **Il Mattarello** | Python on Raspberry Pi 5 | Camera, light, 2D scan, ToF (stub while absent), session with the Snapmaker, heartbeat, watchdog, stop, alarms |
| **Contour service** | Python, nativedev (GPU: check with `gpu_status`) | Segmentation of the workpiece from the camera image; images stay local |
| **Machine link** | HTTP port 8080 of the A250 (same channel as Luban) over the private Tailscale network | `connect`/token, `upload`, `prepare_print`, `start_print`, `GET /status?token` every 2 s |

**orca-cad kernel [verified on documents and grep]**: ~10 kLOC in `src/libslic3r/CAD/`; the document is a **list of features + named variables**, everything else derived by `recompute()`; undo = snapshot; transactional edits; preview = same replay with one more feature. SolveSpace solver vendored (GPLv3); fork AGPLv3. An MCP route (`McpControl`, JSON-RPC over a Unix socket + bridge) is already available. `SketchEngine` depends on OCCT (~170 symbols), so the service is the **full kernel with OCCT** (it already builds without GUI, route K). Independent of OCCT: `SketchSolver`, `SketchConstraints`, `SketchImport`. **Boolean operations between 2D profiles: not found in the sketch** (they exist on solids): to be added with OCCT or ClipperLib. **[open]** how the text glyph outlines are produced; **[open]** the recipe serialization format. There is already "bring the edges of a body into the sketch as construction references": this is the mechanism for the detected workpiece contour.

**Licence [decided]**: **AGPL accepted**, kernel reused as-is; the kernel still stays a **service behind a JSON-RPC protocol**.

**Development and distribution [decided]**: develop on **Linux (nativedev)**, then **macOS**, then **Windows**. Final goal: **a single installer** with kernel, backend and UI for the three systems on other users' PCs (the RPi 5 agent stays next to the machine); **not part of the first delivery**. Known risk: packaging kernel + OCCT + the segmentation model on three systems.

**LLM provider [decided]**: single abstract interface (Claude by default); for other users, **their own API key**.

---

## 4. Contracts: Job Spec 0.3.0

Lane **L0** takes the schema from 0.2.0 to **0.3.0**, with an explicit migration (no already-approved spec silently becomes invalid) and contract tests, adding:

1. **Sketch document [decided]**: **frozen** profiles (resolved curves and polygons, fixed numbers, inside the hash) **+ recipe as source** so it can be reopened and edited. The compiler does not depend on the solver.
2. **Layer = operation [decided]**: palette with colour and settings (engrave, fill, cut; `set_pass`) **in the Job Spec**; the kernel stays pure geometry. Work order by fixed rules: engraving and fill → inner cuts → outer contour last, with travel moves reduced inside each group and **visible numbers**.
3. **Workpiece contour [decided]**: **locked, constrainable** construction geometry (centre, margin, tangent to edge); frozen in the spec as numbers; if the user corrects it, the corrected one is frozen, flagged as modified.
4. **`add_material_grid` primitive [decided]**: axes, ranges, steps, row/column labels **engraved next to the grid**; the LLM fills it in, the code generates the geometry, always identical.
5. **Exclusion mask [decided]** (already-worked zones, B2): drawn by the user on the design; the LLM may propose it; no automatic interpretation of burn marks.
6. **Text as an object [decided]**: string, font, size, spacing; outlines generated by the engine; **the font version goes into the hash**. Missing font in an import: conversion with the closest of the versioned fonts in the repo, **highlighted** in the preview, with the option to change font or undo.
7. **Material and workpiece declared at the start [decided]** (category, thickness, colour); `calibration` is a job type with the same rules and the same gate.
8. **Material recipe [decided]**: separate entity (versioned YAML in the repo = truth; SQLite for history): material, thickness, module, Z height, calibration version, photo, parameters of the chosen cell. It **expires** if the calibration, the module or the Z height changes (warning and proposal for a new test).
9. **3D data in the spec [decided]**: **only the numbers used (thickness and tilt)**, frozen into the hash; the raw map stays in the audit.
10. **Audit [decided]**: local and immutable per job: spec, hash, G-code, session events, confirmations, **risk unlocks** (date, category, declared text).
11. **Variants [decided]**: branches of the document (lightweight copies of the recipe), comparable and resumable until one is approved.
12. **Imported block [decided]**: transformable object (move, rotate, scale) with the original preserved and its **hash**; nodes are unlocked by an explicit step.

---

## 5. Safety (invariants, each with a test)

- **Silence does not mean "all clear"** (fail-safe watchdog). Heartbeat `GET /status?token` every 2 s; beyond **8 s** the session is lost → stop and warning.
- **Physical confirmation [decided]**: for jobs that **turn on the laser or the spindle** (deterministic scan of the final G-code: M3/M4 with S>0) = **tap Yes on the Snapmaker at the connection request with a NEW token**. **Only** for those jobs: movements, frame, dry runs and scans are autonomous. **Start on the touchscreen only if the firmware allows it** (task-zero prediction 11 not concluded; over Wi-Fi it never appeared: measure, do not assume). **No GPIO button.** Consequence to document: the on-screen request does not identify the job; approval of the content (hash) happens only in the UI.
- **The token stays only on the RPi (mode 600)**; present it once per session (repeating it raises the prompt again). Whoever holds the token can start jobs (measured on 14 Oct).
- **Registration (the Sfoglia)** at home pose Y=238, **repeated for every job, right before the gate [decided]**; it blocks if a marker moves beyond the threshold (**0.5/1.0 mm, provisional**). ArUco markers `DICT_4X4_50`, IDs 0–4, inverted polarity (`detectInvertedMarker=True`), physical side 29.94 mm, autofocus OFF; always register at Y=238; remove the ChArUco sheet from the plane.
- **Stop** always available remotely. **Automatic stop [decided]**: silent telemetry, workpiece or marker moved (beyond threshold), smoke or flame from the camera (optional, with false positives), machine alarms.
- **Link lost during emission [decided]**: the machine carries on alone and the system cannot stop it. Decision: **emission only with the user present** (heartbeat also from the user's app) and a **declared physical stop** (hardware emergency button; a Snapmaker one exists); silence raises a warning and retries the stop. **[open]**: how "user present" is verified technically and how the button is integrated.
- **Risks to people [decided]**: hazardous fumes (e.g. PVC), reflection with the 1064 on polished metal, fire = **hard blocks**, unlockable only with a **declaration per session and category** ("I have extraction and protection"), written to the audit (date, category, text). **Unknown material: refusal** until at least the category is declared. **Power cap per category.** Poor yield alone (e.g. 405 on 3 mm plywood) is a **warning**: the user decides.
- **Images to the model [decided]**: **at the user's choice, image by image**; photos of the machine and of the plane never leave on their own.
- **After the gate, no model calls** (test: imports the post-gate modules and fails if it finds the AI provider).
- Raspberry Pi 5: `gpiozero` + `lgpio`/libgpiod, never `RPi.GPIO`; GPIO at 3.3 V. The BMCU flasher and `neato-bridge` also run on the RPi: **do not touch them**.

---

## 6. Physical pipeline

**Session and parallelism [decided].** As soon as the user chooses the module and declares material and workpiece, these start **on their own, in parallel with the interview and in sequence with each other** (they share the machine): machine check (connection, homing, state) → camera registration and calibration check → **2D scan** → **3D ToF scan** (stub until mounted). If the user finishes first: **the gate stays blocked** with status and estimate visible; they can keep drawing, and the constraints on the contour resolve when the 2D scan arrives.

**First-delivery calibrations (405 vector laser) [decided]**
- **Camera–plane homography** with ArUco (already measured).
- **Camera → beam offset**: a mark engraved at low power on sacrificial material, measured by the camera (**requires the Yes tap**).
- **Focus and Z height**: `G0 Z = focal length + declared thickness` (`G54`); **periodic focus ladder** to check the nominal focal length.
- Axis scale and squareness: **not** in the first delivery.
- **Maintenance**: quick check every session; above threshold (0.5/1.0 mm, provisional) supervised recalibration.

**2D acquisition [decided]**: **one photo at the home pose, after registration**; fixed exposure; optical correction and homography already calibrated. **Dedicated light controlled by the system**: **new hardware requirement, not present today [open: position, power, control]**. Overlay on the workpiece: photo by default, live video on request.

**Workpiece contour**
- **Local segmentation model from the start [decided by Tommy; in tension with SPEC "classical OpenCV, model only where it is not enough"]**. Default **[proposed]**: runs on **nativedev** (not on the RPi), **classical OpenCV as fallback and cross-check**, images local. Measure time and quality on transparent acrylic, polished metal, black on black.
- If confidence is low or the contour is wrong: **the user corrects it or draws it on the image**; the corrected one is frozen, flagged as modified.

**3D data (ToF 8×8, when mounted) [decided]**: thickness and flatness check with warnings; safety (obstacles, raised parts). A difference between measured and declared thickness beyond the threshold = **warning, the user confirms which value to use** (written to the spec). **Height map to compensate Z: designed now, delivered after validation** with the step block (~30 mm grid: accuracy to be measured).

**Command production (405 vector compiler)**
- **Kerf per recipe [decided]**, applied by the engine as a half-kerf offset; the preview shows the compensated path.
- **Multiple passes [decided]**: same height with repetition; **Z step-down only if the recipe declares it**.
- Work order as in §4.2.
- The rest follows `compiler.py`. **[proposed]** lead-in/lead-out and overscan: to be proposed to Tommy, not decided.
- Compilers and validators for **1064 and CNC**: plugins of the same schema (capability descriptor + compiler + validator); **[open]**, outside the first delivery.

---

## 7. UI

- **Centre [decided]**: **canvas with camera overlay**; chat and properties at the sides. **Layout fixed on computer, collapsible on tablet** (the chat opens over the canvas and closes with a gesture). Devices: computer with mouse and keyboard; **iPad/Android tablet to be planned** (gestures, large targets). The RPi touchscreen is not a drawing editor.
- **Start screen [decided]**: four doors, **Import, Describe, Relaunch, Material test**. **A single workbench**: the doors lead to the same canvas and the same document and pre-configure panels and tools (e.g. the grid for Material test).
- **Sketch [decided]**: level **essential + node editing, 2D booleans (to be added to the kernel), offset**. **Dragging**: rigid preview during the gesture, **solver on release** (numeric values on every Enter).
- **LLM in the sketch [decided]**: participates in **three ways**: on request from the chat; **ghosts** (dashed proposals accepted or discarded with one tap); **deterministic flags without an LLM** (below kerf, overlapping strokes, open paths, out of area).
- **Continuous deterministic validator [decided]**: minimum detail, kerf, cutter radius when relevant, risks; highlights on the design; the LLM receives the list and the fix appears as a ghost.
- **Two-level preview [decided]**: **fast** (geometry, instant) and **accurate = replay of the real G-code trajectories** in the simulator (no simulation of burning or removal effects). The accurate one shows: **numbered order and direction (switchable in both)**, **dashed travel moves**, power and passes by colour or stroke, **estimated time** per operation and total, limit checks, **animated replay** with a cursor (reused as progress during a running job). **Recompute** in the background after every confirmed edit (debounce), "updating" indicator, previous result stays visible and marked "out of date". **Cache per layer/operation** (layer hash + machine parameters); **progressive refinement** on large jobs: first contour and order, then times and powers, then full replay.
- Feasibility = **warning** (the user decides); risks = **blocks** (§5). Warnings and blocks live **on the design**, not in a log.

---

## 8. Use cases: requirements and delivery order

**Work order [decided]**: **B3 → A1 → A2**; the first delivery also includes **B2, B6, B7**. **Outside the first delivery**: B1, B4, B5, B8. A3: requirements decided, **[open]** its position in the delivery order (I propose after A2).

**B3 — Material tests (FIRST VERTICAL) [decided]**
- The user tells the LLM the goal; the LLM fills in `add_material_grid`.
- Ranges: **starting from a similar material in the library** (deterministic rule on category, thickness, colour; the LLM explains it). Library with a **seed from the Snapmaker/Luban profiles** and conservative caps per category. **[open]** with no similar material: unknown material stays refused until at least the category is declared.
- Test in a **free area of the real workpiece** (engrave and fill only); **through-cuts only on a separate offcut**.
- Rows and columns **engraved next to the grid**; the user **types the coordinates** of the best cell.
- Thickness **declared** (calipers) and checked by the ToF when mounted; Z height follows from it.
- Outcome: **recipe proposal** (material, thickness, module, Z, calibration version, photo) into the library **only after approval**. Expiry as in §4.8.

**A1 — Importing files [decided]**
- Order: **SVG/DXF → images → STEP/STL**.
- Summary of what was understood (units, scale, number of paths, open paths, duplicates). The LLM proposes operations from colour, layer and stroke width; the user confirms by **colouring the preview**.
- Scale: the system shows the **deduced dimensions in mm** on the real workpiece and asks for confirmation.
- File = **transformable block** (§4.12). Open paths: automatic closing only if the gap is minimal (small, declared tolerance); the others **highlighted**. Missing font: §4.6.
- STEP/STL in the first version: **extracted 2D profiles** (outline, section at a height, outlines of planar faces) treated as vector; 3D CAM is a later epic (E3).

**A2 — Ideas translated by the LLM [decided]**
- The LLM builds with the **sketch primitives** and with **parametric generators** for known objects (finger-joint box, gear), parameters exposed as sliders.
- 2–3 variants as **branches of the document**. Physical constraints from the continuous validator.
- Reference images: the LLM looks at them and rebuilds with primitives; **no automatic tracing**; an image goes to the model only if the user chooses it (§5).

**A3 — Relaunch [decided]**: the job reopens, is repositioned on the new contour and gets a **new spec derived from the old one, a new hash and a new gate** (the original stays intact). What is archived: **spec, sketch recipe, preview, outcome and photo**; the G-code is regenerated from the spec. **Third-party G-code (Luban, LightBurn): not in the first delivery.**

**B2 — Already-worked piece [decided]**: already-worked zones = the user's exclusion mask (§4.5). Second face: **marker on the plane + detected contour** as reference, with new registration; reference points on the piece are constrainable construction geometry.

**B6 — Check before working [decided]**: the frame is **optional, proposed by the system**; on the 1064 (infrared) = **movement with the laser off, verified by the camera with overlay**; dry run. Feasibility: warning; risks: blocks (§5).

**B7 — Recovery and after-work [decided]**: after a stop with possible loss of position: **homing, new registration, resume from the start of the current operation**, with a preview of what is already done and physical confirmation as for a new job. Feedback on the result: the user says what is wrong ("too light", "burnt", "not cut through") and the LLM proposes parameters to approve.

**Outside the first delivery (decisions already made, to be built later)**
- **B1 Series**: arrays and grids with serial numbers and text from CSV; automatic nesting on a sheet; resume from piece K.
- **B4**: switching the physical module is a **new project on the same piece**, with contour and registration inherited.
- **B5**: relief and depth **enter first with the laser**: **depth map translated into passes and power** (405 and 1064); the greyscale image from a file or generated by the LLM. **[open]** how to verify the depth reached (the 8×8 ToF cannot measure millimetre-deep grooves). Pockets, V-carve and drilling stay with the CNC.
- **B8**: **local** library (nativedev today, the user's PC for others). **[open]** export/sharing format.

---

## 9. Lanes (parallel, separate branches) and dependencies

**Order**: L0 first; then all the others in parallel; L8 integrates.

| Lane | Content | Depends on |
|---|---|---|
| **L0 Schema 0.3.0** | §4 with migration and contract tests | — |
| **L1 Core: materials and validator** | materials and recipes library (Snapmaker/Luban seed, caps per category), similarity rule, continuous validator, risk blocks and unlock with audit, deterministic "what is missing" function for the interview, audit | L0 |
| **L2 Compiler and simulator** | grid and engraved text, kerf per recipe and multiple passes, replay for preview (trajectories, travel, times, order/direction), per-layer cache, progressive refinement, frame and dry run | L0 |
| **L3 Kernel service** | headless Linux build, JSON-RPC API (frozen 2D profiles, recipe, constraints, offset, text), **2D booleans**, glyph outlines, recipe serialization, construction references from the workpiece contour | L0 (contract) |
| **L4 Web UI** | skeleton (four doors, one workbench, canvas, photo overlay, chat and properties, fixed/collapsible layout), B3 flow, two-level preview, shared undo, ghosts, flags | L0, L2, L3 |
| **L5 Il Mattarello** | calibration (home, ArUco, camera→beam offset, focus/Z), 2D scan (dedicated light behind an interface, stub until mounted), ToF stub, session and heartbeat (also from the user), watchdog and stop, alarms, token 600 | L0 |
| **L6 Contour service** | local segmentation + OpenCV fallback, measurements on difficult materials, manual correction | L5 (images) |
| **L7 Tests and CI** | §11 | all |
| **L8 Integration** | end-to-end B3 vertical on a fake machine, then on the A250 with Tommy's go-ahead | L1–L7 |

---

## 10. Acceptance criteria

**B3 vertical (the first)**
1. On a **fake machine**: from the interview (goal in words, material and workpiece declared) to a grid with engraved labels, replay preview with times, gate with hash, G-code, "active job" scanner, simulated session, cell choice by typing coordinates, recipe proposal saved after approval.
2. **Preview–machine parity**: the replay shows exactly the compiled trajectories.
3. **Fault injection**: silent telemetry, moved marker, moved workpiece, lost camera → stop and audit.
4. **Safety**: unknown material refused; risk category blocked without declaration; power above the cap blocked; emission denied without the user present.
5. **On the real A250** (only with Tommy's go-ahead): registration at Y=238 within threshold, test in a free area, Yes tap with a new token, execution, complete audit. Start on the touchscreen is measured, not assumed.

**A1**: from an SVG with coloured layers → operation proposal → confirmation on the preview → deduced dimensions confirmed → order as §4.2 → gate → G-code identical to the golden file. Missing font highlighted; small open path closed and large one highlighted; simple STEP → correct 2D profiles.

**A2**: from a description → at least two variants as comparable branches; the validator highlights a detail below the minimum and the fix appears as a ghost acceptable with one tap; a generator (finger-joint box) exposes the sliders.

**A3**: reopening an archived job, repositioning on a new contour, new hash and new gate; the original stays intact; without changes the regenerated G-code has the same hash as the original.

**B2**: no compiled trajectory falls inside the exclusion mask (automatic test); second face with new registration and reference contour.

**B6**: the frame produces G-code without emission (confirmed by the scanner) and the camera verifies the path with overlay; risk blocks unlockable only with a declaration written to the audit.

**B7**: after a simulated stop: homing, new registration, resume from the start of the current operation with a preview of what is done; the feedback produces a recipe proposal to approve.

---

## 11. Tests and checks (lane L7)

- **Contract tests** for schema 0.3.0 and the 0.2.0 → 0.3.0 migration; **golden files** spec → G-code.
- **Simulator also at runtime**: every G-code goes through the simulator before dispatch (limits, laser-fire, modal state).
- **Simulated stack with fault injection** (lost camera, covered markers, smoke, moved workpiece, silent telemetry).
- **Offline runner** (no network, no keys) as a CI test.
- **"No model after the gate" test**: the post-gate modules do not import the AI provider.
- Physical measurements with `ai-intuition`; no laser or spindle turned on without Tommy's go-ahead.

---

## 12. To decide or measure (none of these is resolved)

| Item | Default adopted | Who confirms |
|---|---|---|
| Hosting of the segmentation model | nativedev (check the GPU), OpenCV fallback | Tommy |
| Recipe serialization format of orca-cad | to be measured in L3, then fixed in L0 | L3 |
| 2D booleans and glyph outlines in the kernel | to be added/verified | L3 |
| Start on the touchscreen over Wi-Fi (prediction 11) | not assumed; Yes only | measurement with Tommy's go-ahead |
| Registration thresholds 0.5/1.0 mm | provisional | measurement |
| "User present" and hardware emergency button | not technically defined; emission without the user present does not start | Tommy |
| Dedicated light for the 2D scan | new requirement: position, power, control | Tommy |
| ToF 8×8 | not mounted; stub behind an interface | Tommy |
| B3 with no similar material in the library | unknown material refused until the category is declared | Tommy |
| Lead-in/lead-out and overscan in the compiler | to be proposed | Tommy |
| Position of A3 in the delivery order | after A2 | Tommy |
| Depth verification (B5), sharing format (B8) | not defined | Tommy |
| Compiler and validator differences for 1064 and CNC | deferred (epics E2/E3) | Tommy |
| Single installer on three systems | final goal, not v1 | Tommy |
| Web UI stack | TypeScript, framework to be fixed in L4 | Tommy |
| Updating SPEC.md, CLAUDE.md, HANDOFF.md | **propose the diffs** of Appendix A, do not apply them | Tommy |

---

## 13. First move

Read `CLAUDE.md` and `HANDOFF.md`, then the code in `core/` and `tools/executor/`. Then **propose, without writing product code**: (a) the L0 plan with the `pending` predictions and schema 0.3.0 as a diff against 0.2.0; (b) for each lane the first verifiable step with its test; (c) the list of physical measurements that need Tommy's go-ahead; (d) the diffs of Appendix A. **Wait for his OK before opening the worktrees.**

---

## Appendix A — Corrections to propose to the project documents (do not apply)

- **CLAUDE.md**: "Start on the touchscreen" → physical confirmation = **Yes tap at the connection request with a new token, only for jobs that turn on the laser or the spindle**; Start only if the firmware allows it; **no GPIO**.
- **SPEC.md**: (1) v1 = vector 405 laser only → **design for all cases, deliver in steps**; (2) "no fork, no AGPL" → **AGPL accepted** for reuse of the orca-cad kernel; (3) "no image to the cloud except the workpiece crop" → **at the user's choice, image by image; photos of the machine and of the plane never on their own**; (4) interview on a canvas with the **parametric kernel** behind it; (5) contour with a **local segmentation model**, OpenCV as fallback; (6) **a single installer** in the long term, Linux → macOS → Windows.
- **HANDOFF.md**: "no code written" is superseded (schema 0.2.0, resolver, compiler, simulator, scanner already present); the 14 Oct physical confirmation (GPIO) is superseded.

## Appendix B — Glossary

- **Job Spec**: the working document, the single object shared by human, LLM and engine.
- **Gate / the Sfoglia**: approval with the spec hash and ArUco registration; from there on, no models.
- **Il Mattarello**: the agent on the Raspberry Pi 5 next to the machine.
- **Recipe (material)**: validated parameters for a material, thickness, module and Z height. **Recipe (sketch)**: the kernel's list of features and variables.
- **Replay**: the accurate preview, obtained by re-running the real G-code in the simulator.
