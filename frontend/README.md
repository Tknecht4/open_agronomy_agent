# React cockpit

## Purpose and status

`frontend/` is the supported map-first React interface for fields, sessions, questions, sources, traces, and local/offline state. It is a client of the FastAPI application; a rendered page does not prove the API, model, corpus, or adapters are ready.

## Entry points and map

- `src/main.tsx` mounts the application.
- `src/OpenAgronomyApp.tsx` owns the primary cockpit workflow.
- `src/api.ts` is the API client boundary.
- `src/LeafletFieldMap.tsx` renders field/map interaction.
- `src/types.ts` defines shared client-side response shapes.
- `src/fieldContextReadiness.ts` and `fieldRuntimeAvailability.ts` keep missing context/capability state explicit.
- `src/sourceCards.ts` and `formattedAnswer` present answer evidence.
- `src/offline*.ts`, `pwa.ts`, and `localPairing.ts` implement bounded local client behavior.
- `src/*InfoPages.tsx` and `PublicDemoPages.tsx` are application information views, not the canonical documentation site.

## Inputs and outputs

Inputs are API responses, user-entered questions/field records, map geometry, permitted attachments, and browser-local draft state. Outputs are API requests, progressive answer/trace UI, offline drafts, and explicit readiness/error states.

## Invariants

- Never present map context as sampled field truth.
- Display source, status, timing, assumptions, missing inputs, and boundaries without hiding the direct answer.
- Sanitize rendered content; never execute model-provided markup or URLs.
- Keep keyboard, contrast, responsive, and low-bandwidth behavior testable.
- Treat browser storage as local convenience, not durable server confirmation.
- Offline drafts must not be shown as synced until acknowledged by the API.

## Extend the UI

1. Add or update a typed API shape in `src/types.ts`/`src/api.ts`.
2. Keep network/state logic outside presentation components when practical.
3. Add accessible loading, empty, blocked, degraded, error, and success states.
4. Add Vitest/Testing Library coverage and update responsive/accessibility audits.
5. If exposing a capability, derive status from the server contract; do not infer availability from a button or static list.

## Configuration

`VITE_API_TARGET` controls the Vite development proxy target and defaults to `http://127.0.0.1:8000`. Production/field-LAN builds are served by the configured backend/container and have separate security gates.

## Validation

```bash
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

Run the API and visit the main field/question flow after automated checks. Confirm `/api/health` independently.

## Failure modes

Expected states include API unavailable, model setup required, field context incomplete, adapter blocked/offline, stale local draft, invalid geometry, upload rejected, and stream interrupted. Preserve the user's input and actionable recovery information where safe.
