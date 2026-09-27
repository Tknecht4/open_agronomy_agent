# React cockpit

## Purpose and status

`frontend/` is the supported field/question React workspace. **Workspace** keeps conversation primary and opens the map on demand; **Fields** manages setup, records, soil tests, history, and map context; **Data** presents private references, knowledge coverage, and adapter diagnostics. It is a client of the FastAPI application; a rendered page does not prove the API, model, corpus, or adapters are ready. See the [workspace guide](../docs/public/operations/workspace.md) for the user flow.

## Entry points and map

- `src/main.tsx` mounts the application.
- `src/OpenAgronomyApp.tsx` owns the primary cockpit workflow.
- `src/FieldSetupDialog.tsx` owns the name/location/review field wizard; `src/WorkspaceDialog.tsx` supplies accessible modal behavior.
- `src/MapPresentationControls.tsx` and `src/mapPresentation.ts` own map style/layer display preferences. `src/FieldMapInsights.tsx` renders lazy, on-demand analysis with stale-request cancellation.
- `src/api.ts` is the API client boundary.
- `src/LeafletFieldMap.tsx` and `src/fieldGeometry.ts` render and validate pin, boundary, and imported-geometry interaction.
- `src/types.ts` defines shared client-side response shapes.
- `src/fieldContextReadiness.ts` and `fieldRuntimeAvailability.ts` keep missing context/capability state explicit.
- `src/sourceCards.ts` and `formattedAnswer` present answer evidence.
- `src/offline*.ts`, `pwa.ts`, and `localPairing.ts` implement bounded local client behavior.
- `src/workspacePerformance.tsx` and `rum.ts` capture bounded workspace performance diagnostics.
- `src/*InfoPages.tsx` and `PublicDemoPages.tsx` are application information views, not the canonical documentation site.

## Inputs and outputs

Inputs are API responses, user-entered questions/field records, map geometry, permitted attachments, and browser-local draft state. Outputs are API requests, progressive answer/trace UI, offline drafts, and explicit readiness/error states.

General questions do not require a fabricated field. The field wizard requires a name and a valid pin/boundary/import before saving; crop and region remain optional. Imported geometry is reviewed before persistence. Regional overlays and calculated polygon area are labelled context/estimates, never field measurements. **Sources & checks** opens answer evidence without hiding the question or saved answer.

## Invariants

- Never present map context as sampled field truth.
- Display source, status, timing, assumptions, missing inputs, and boundaries without hiding the direct answer.
- Sanitize rendered content; never execute model-provided markup or URLs.
- Keep keyboard, contrast, responsive, and low-bandwidth behavior testable.
- Treat browser storage as local convenience, not durable server confirmation.
- Offline drafts must not be shown as synced until acknowledged by the API.
- Keep private-reference inspection separate from governed shared-corpus ingestion; a browser upload cannot silently activate a runtime source.

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

Run the API and exercise a general question, field creation/edit/reload, source inspection, and an offline draft after automated checks. Confirm `/api/health` independently. The [backend profile](../docs/reviews/artifacts/ui-backend-findings-20260927.md) and `scripts/profile_frontend_build.mjs` provide development diagnostics; they do not establish a user latency budget or answer quality.

## Failure modes

Expected states include API unavailable, model setup required, field context incomplete, adapter blocked/offline, stale local draft, invalid geometry, upload rejected, and stream interrupted. Preserve the user's input and actionable recovery information where safe.
