# Darwin dashboard

The dashboard is an event-sourced Vite/React application. Live WebSocket events and JSONL replay events pass through the same pure reducer, so the offline demo renders the same state as a live optimization.

```bash
npm ci
npm run dev
npm test
npm run build
```

Vite proxies `/api` and `/ws` to `VITE_BACKEND_URL` (default `http://localhost:8000`). The main contracts are imported directly from `../shared/contracts.ts` through the `@shared` alias.

Key folders:

- `src/store/` — reducer, Zustand store, reconnecting WS source, and timed JSONL source.
- `src/geometry/` — fixed-topology parametric fin mesh and analytic checks.
- `src/three/` — morphing preview, STL cross-fade, body tube, and studio scene.
- `src/components/panels/` — charts, lineage, feed, budget, and per-panel error boundaries.

The app targets 1440×900 and remains usable at 1280×800. Three.js pixel ratio is capped at 1.5 for older Intel Macs.
