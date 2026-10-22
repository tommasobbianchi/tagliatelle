# TaglIAtelle — UI (lane L4, skeleton)

Single-page app per decision `docs/UX-CONVERSIONE-decisioni-2026-10-22.md`
(§12/§15/§20): **four doors** (Importa, Descrivi, Rilancia, Prova materiale)
that all open **the same workbench** — canvas centre with camera-overlay
placeholder, properties at the left, chat at the right; layout fixed on
computer, collapsible on tablet. Two-level preview: fast (geometry, instant)
and accurate (G-code replay — placeholder here; real replay comes from
`core/replay.py`, lane L2, once the API is wired).

## Stack

TypeScript + React 18 + Vite 5 (SPA, no SSR, no canvas lib),
Vitest 2 + Testing Library (jsdom). Deterministic, dependency-light, no
backend calls yet.

## Layout

```
ui/
├── index.html
├── package.json
├── vite.config.ts          # vitest config included
├── tsconfig.json
└── src/
    ├── main.tsx
    ├── App.tsx             # start screen (four doors) or the workbench
    ├── spec.ts             # typed mirror of Job Spec 0.3.0 subset + sample spec
    ├── styles.css
    ├── doors/              # ImportDoor, DescribeDoor, RelaunchDoor, MaterialTestDoor
    ├── workbench/          # Workbench, Canvas, Chat, Properties
    └── __tests__/          # doors, canvas, chat, properties
```

## Commands

```bash
npm install
npm test          # vitest run
npm run dev       # local dev server
npm run typecheck # tsc --noEmit
npm run build     # typecheck + production build
```
