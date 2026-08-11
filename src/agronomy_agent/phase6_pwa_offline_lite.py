from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORT_VERSION = "phase6.pwa_offline_lite.v1"

DEFAULT_PACKET = ROOT / "plans/agronomy_agent_phase6_pre_demo_launch_packet/agronomy_agent_phase6_pre_demo_launch_design_packet.md"
DEFAULT_DOC = ROOT / "docs/phase6_pwa_offline_lite.md"
DEFAULT_INDEX = ROOT / "frontend/index.html"
DEFAULT_MANIFEST = ROOT / "frontend/public/manifest.webmanifest"
DEFAULT_OFFLINE_PAGE = ROOT / "frontend/public/offline.html"
DEFAULT_SERVICE_WORKER = ROOT / "frontend/public/service-worker.js"
DEFAULT_PWA_TS = ROOT / "frontend/src/pwa.ts"
DEFAULT_MAIN_TSX = ROOT / "frontend/src/main.tsx"
DEFAULT_APP_TSX = ROOT / "frontend/src/OpenAgronomyApp.tsx"
DEFAULT_HOSTED_TSX = ROOT / "frontend/src/HostedPlatform.tsx"
DEFAULT_OFFLINE_DRAFTS_TS = ROOT / "frontend/src/offlineDrafts.ts"
DEFAULT_OFFLINE_SCRATCHPAD_TS = ROOT / "frontend/src/offlineScratchpad.ts"
DEFAULT_OFFLINE_STORAGE_REPAIR_TS = ROOT / "frontend/src/offlineStorageRepair.ts"
DEFAULT_DEFERRED_ACTIONS_TS = ROOT / "frontend/src/deferredActions.ts"
DEFAULT_CI = ROOT / ".github/workflows/phase6-pre-demo-ci.yml"

PHASE6_SCOPE_ITEMS = (
    "Installable app shell.",
    "Offline landing page and previously loaded public docs/help pages.",
    "Draft message preservation during network interruptions.",
    "Deferred feedback/report-upload queue.",
    "Local-only scratchpad for field notes, clearly marked as not synced until network returns.",
    "No offline model answer generation in the default demo path.",
)
PRIVATE_API_PREFIXES = (
    "/api",
    "/admin",
    "/auth",
    "/orgs",
    "/workspaces",
    "/field-contexts",
    "/geo",
    "/threads",
    "/chat",
    "/route",
    "/retrieve",
    "/tools",
    "/attachments",
    "/messages",
    "/eval-candidates",
    "/eval-runs",
    "/change-proposals",
    "/data-sources",
    "/ingest-jobs",
    "/corpus-health",
    "/quotas",
    "/audit-events",
    "/exports",
    "/export-jobs",
    "/image-rag",
)
EXPECTED_FRONTEND_TESTS = (
    "pwa.test.ts",
    "offlineDrafts.test.ts",
    "offlineScratchpad.test.ts",
    "offlineStorageRepair.test.ts",
    "fieldRuntimeAvailability.test.ts",
    "openAgronomyMapWorkflow.test.tsx",
    "deferredActions.test.ts",
)
REQUIRED_DOC_SNIPPETS = (
    "installable app shell",
    "no default offline model answer",
    "no private chat contents in service-worker caches",
    "32-entry runtime asset cache cap",
    "Deferred actions are limited to hosted feedback and hosted thread-export POSTs",
    "retry control",
    "npm --prefix frontend test -- --run pwa.test.ts",
    "npm --prefix frontend run typecheck",
)
REQUIRED_SERVICE_WORKER_SNIPPETS: tuple[str, ...] = (
    "PRECACHE_URLS",
    "'/offline.html'",
    "'/manifest.webmanifest'",
    "'/icons/agronomy-agent.svg'",
    "request.method !== 'GET'",
    "url.origin !== self.location.origin",
    "url.pathname.startsWith('/assets/')",
    "request.mode === 'navigate'",
    "RUNTIME_CACHE_NAME",
    "PHASE6_RUNTIME_CACHE_MAX_ENTRIES = 32",
    "ACTIVE_CACHE_NAMES",
    "trimPhase6RuntimeCache",
    "cachePhase6RuntimeAsset",
    "cache.delete(keys[index])",
    "!ACTIVE_CACHE_NAMES.includes(key)",
    "event.waitUntil(cachePhase6ShellIndex(copy))",
    "event.waitUntil(cachePhase6RuntimeAsset(request, copy))",
    *(f"'{prefix}'" for prefix in PRIVATE_API_PREFIXES),
)
REQUIRED_PWA_REGISTRATION_SNIPPETS = (
    "PHASE6_SERVICE_WORKER_PATH = \"/service-worker.js\"",
    "reason: \"unsupported\"",
    "reason: \"not_production\"",
    "reason: \"registered\"",
    "navigatorLike.serviceWorker",
    "if (!production)",
    "register(PHASE6_SERVICE_WORKER_PATH, { scope: \"/\" })",
    "addEventListener(\"load\", register, { once: true })",
)
REQUIRED_MAIN_ENTRY_SNIPPETS = ("import { registerPhase6Pwa } from './pwa'", "registerPhase6Pwa()")
REQUIRED_OFFLINE_PAGE_SNIPPETS = (
    "Offline demo shell",
    "live answers, reports, account actions, and feedback need the server connection",
    "The agent does not generate answers while its local service is unavailable.",
    "Retry the app",
)
REQUIRED_OFFLINE_DRAFTS_SNIPPETS = (
    "PHASE6_CHAT_DRAFT_STORAGE_KEY",
    "PHASE6_CHAT_DRAFT_MAX_CHARS = 8000",
    "sessionId is required to save a Phase 6 chat draft",
    "quarantinePhase6OfflineStorage",
    "store: 'chat_draft'",
    "raw,",
    "message.slice(0, PHASE6_CHAT_DRAFT_MAX_CHARS)",
)
REQUIRED_APP_OFFLINE_UI_SNIPPETS = (
    "loadPhase6ChatDraft(activeFieldConversationKey)",
    "savePhase6ChatDraft(activeFieldConversationKey, message)",
    "clearPhase6ChatDraft(activeFieldConversationKey)",
    "data-testid=\"local-field-notes-status\"",
    "Stored only on this device.",
    "savePhase6Scratchpad(activeFieldConversationKey, scratchpadNotes)",
    "clearPhase6Scratchpad(activeFieldConversationKey)",
    "fieldAnswerCapability(runtimeAccess, networkMode)",
    "The local agronomy runtime is unavailable. Your question draft remains on this device",
    "!answerCapability.canGenerateAnswer",
    "PHASE6_OFFLINE_STORAGE_REPAIRED_EVENT",
    "data-testid=\"offline-storage-recovery-notice\"",
    "Download recovery file",
    "downloadPhase6OfflineStorageRecovery(offlineStorageRepair)",
)
REQUIRED_OFFLINE_SCRATCHPAD_SNIPPETS = (
    "PHASE6_SCRATCHPAD_STORAGE_KEY",
    "PHASE6_SCRATCHPAD_MAX_CHARS = 12000",
    "syncState: 'local_only'",
    "quarantinePhase6OfflineStorage",
    "store: 'scratchpad'",
    "notes.slice(0, PHASE6_SCRATCHPAD_MAX_CHARS)",
    "raw,",
)
REQUIRED_OFFLINE_STORAGE_REPAIR_SNIPPETS = (
    "PHASE6_OFFLINE_STORAGE_QUARANTINE_KEY",
    "quarantinePhase6OfflineStorage",
    "listPhase6OfflineStorageQuarantine",
    "buildPhase6OfflineStorageRecoveryExport",
    "downloadPhase6OfflineStorageRecovery",
    "disposition: 'quarantined' | 'preserved_in_place' | 'preserved_in_memory'",
    "storage.setItem(input.storageKey, input.raw)",
    "emergencyRecoveryRecords.push(record)",
    "This file contains device-local recovery data",
)
REQUIRED_DEFERRED_ACTION_SNIPPETS = (
    "PHASE6_DEFERRED_ACTION_LIMIT = 50",
    "PHASE6_DEFERRED_ACTION_BODY_MAX_CHARS = 16000",
    "'hosted_feedback'",
    "'hosted_thread_export'",
    "hostedFeedbackPathRe = /^\\/messages\\/[^/]+\\/feedback$/",
    "hostedThreadExportPathRe = /^\\/threads\\/[^/]+\\/exports$/",
    "only POST actions can be deferred in Phase 6",
    "action.kind === 'hosted_feedback' && !hostedFeedbackPathRe.test(action.path)",
    "action.kind === 'hosted_thread_export' && !hostedThreadExportPathRe.test(action.path)",
    "unsupported deferred action path",
    "writeActions(storage, [...readActions(storage), queued])",
    "quarantinePhase6OfflineStorage",
    "store: 'deferred_action'",
    "safeFeedbackBodyKeys",
    "safeThreadExportBodyKeys",
    "sanitizeDeferredBody",
    "deferred_text_omitted",
    "const safeAction = { ...action, body: sanitizeDeferredBody(action) }",
)
REQUIRED_HOSTED_DEFERRED_ACTION_SNIPPETS = (
    "enqueuePhase6DeferredAction",
    "Feedback saved locally for retry",
    "Export saved locally for retry",
    "Retry deferred actions",
    "feedback/report uploads only, retried by explicit user action",
    "removePhase6DeferredAction(action.id)",
)
REQUIRED_CI_WORKFLOW_SNIPPETS = EXPECTED_FRONTEND_TESTS[:-1]
REQUIRED_SNIPPETS_BY_SECTION: dict[str, tuple[str, ...]] = {
    "app_offline_ui": REQUIRED_APP_OFFLINE_UI_SNIPPETS,
    "ci_workflow": REQUIRED_CI_WORKFLOW_SNIPPETS,
    "deferred_actions": REQUIRED_DEFERRED_ACTION_SNIPPETS,
    "docs": REQUIRED_DOC_SNIPPETS,
    "hosted_deferred_actions": REQUIRED_HOSTED_DEFERRED_ACTION_SNIPPETS,
    "main_entry": REQUIRED_MAIN_ENTRY_SNIPPETS,
    "offline_drafts": REQUIRED_OFFLINE_DRAFTS_SNIPPETS,
    "offline_page": REQUIRED_OFFLINE_PAGE_SNIPPETS,
    "offline_scratchpad": REQUIRED_OFFLINE_SCRATCHPAD_SNIPPETS,
    "offline_storage_repair": REQUIRED_OFFLINE_STORAGE_REPAIR_SNIPPETS,
    "packet": PHASE6_SCOPE_ITEMS,
    "pwa_registration": REQUIRED_PWA_REGISTRATION_SNIPPETS,
    "service_worker": REQUIRED_SERVICE_WORKER_SNIPPETS,
}


def validate_phase6_pwa_offline_lite(
    *,
    packet_path: Path = DEFAULT_PACKET,
    doc_path: Path = DEFAULT_DOC,
    index_path: Path = DEFAULT_INDEX,
    manifest_path: Path = DEFAULT_MANIFEST,
    offline_page_path: Path = DEFAULT_OFFLINE_PAGE,
    service_worker_path: Path = DEFAULT_SERVICE_WORKER,
    pwa_ts_path: Path = DEFAULT_PWA_TS,
    main_tsx_path: Path = DEFAULT_MAIN_TSX,
    app_tsx_path: Path = DEFAULT_APP_TSX,
    hosted_tsx_path: Path = DEFAULT_HOSTED_TSX,
    offline_drafts_path: Path = DEFAULT_OFFLINE_DRAFTS_TS,
    offline_scratchpad_path: Path = DEFAULT_OFFLINE_SCRATCHPAD_TS,
    offline_storage_repair_path: Path = DEFAULT_OFFLINE_STORAGE_REPAIR_TS,
    deferred_actions_path: Path = DEFAULT_DEFERRED_ACTIONS_TS,
    ci_workflow_path: Path = DEFAULT_CI,
) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    packet = _read_text(packet_path, "packet", failures)
    doc = _read_text(doc_path, "docs", failures)
    index_html = _read_text(index_path, "app_shell", failures)
    manifest = _load_json(manifest_path, "manifest", failures)
    offline_page = _read_text(offline_page_path, "offline_page", failures)
    service_worker = _read_text(service_worker_path, "service_worker", failures)
    pwa_ts = _read_text(pwa_ts_path, "pwa_registration", failures)
    main_tsx = _read_text(main_tsx_path, "pwa_registration", failures)
    app_tsx = _read_text(app_tsx_path, "app_offline_ui", failures)
    hosted_tsx = _read_text(hosted_tsx_path, "hosted_deferred_actions", failures)
    offline_drafts = _read_text(offline_drafts_path, "offline_drafts", failures)
    offline_scratchpad = _read_text(offline_scratchpad_path, "offline_scratchpad", failures)
    offline_storage_repair = _read_text(
        offline_storage_repair_path,
        "offline_storage_repair",
        failures,
    )
    deferred_actions = _read_text(deferred_actions_path, "deferred_actions", failures)
    ci_workflow = _read_text(ci_workflow_path, "ci_workflow", failures)
    texts_by_section = {
        "app_offline_ui": app_tsx,
        "ci_workflow": ci_workflow,
        "deferred_actions": deferred_actions,
        "docs": doc,
        "hosted_deferred_actions": hosted_tsx,
        "main_entry": main_tsx,
        "offline_drafts": offline_drafts,
        "offline_page": offline_page,
        "offline_scratchpad": offline_scratchpad,
        "offline_storage_repair": offline_storage_repair,
        "packet": packet,
        "pwa_registration": pwa_ts,
        "service_worker": service_worker,
    }

    packet_scope_covered = _packet_scope_covered(packet, failures)
    docs_current = _docs_current(doc, failures)
    installable_shell_ready = _installable_shell_ready(index_html, manifest, failures)
    service_worker_cache_bounded = _service_worker_cache_bounded(service_worker, failures)
    service_worker_runtime_cache_budgeted = _service_worker_runtime_cache_budgeted(service_worker)
    production_registration_bounded = _production_registration_bounded(pwa_ts, main_tsx, failures)
    offline_page_ready = _offline_page_ready(offline_page, failures)
    draft_preservation_ready = _draft_preservation_ready(offline_drafts, app_tsx, failures)
    scratchpad_local_only = _scratchpad_local_only(offline_scratchpad, app_tsx, failures)
    offline_storage_recovery_ready = _all_snippets(
        "offline_storage_repair",
        offline_storage_repair,
        REQUIRED_OFFLINE_STORAGE_REPAIR_SNIPPETS,
        failures,
    ) and _all_snippets(
        "app_offline_ui",
        app_tsx,
        REQUIRED_APP_OFFLINE_UI_SNIPPETS[-4:],
        failures,
    )
    deferred_queue_ready = _deferred_queue_ready(deferred_actions, hosted_tsx, failures)
    deferred_queue_privacy_guarded = _deferred_queue_privacy_guarded(deferred_actions, failures)
    no_offline_model_generation = _no_offline_model_generation(
        service_worker=service_worker,
        offline_page=offline_page,
        doc=doc,
        app_tsx=app_tsx,
        hosted_tsx=hosted_tsx,
        deferred_actions=deferred_actions,
        failures=failures,
    )
    frontend_tests_tracked = _frontend_tests_tracked(failures)
    ci_tests_tracked = _ci_tests_tracked(ci_workflow, failures)
    expected_snippets_by_section = _json_snippet_map(REQUIRED_SNIPPETS_BY_SECTION)
    observed_snippets_by_section = _observed_snippets_by_section(texts_by_section)
    missing_snippets_by_section = _missing_snippets_by_section(observed_snippets_by_section)
    snippet_inventory_exact = observed_snippets_by_section == expected_snippets_by_section and not any(missing_snippets_by_section.values())

    return {
        "schema_version": REPORT_VERSION,
        "gate_passed": not failures,
        "phase6_scope_item_count": len(PHASE6_SCOPE_ITEMS),
        "packet_scope_covered": packet_scope_covered,
        "docs_current": docs_current,
        "installable_shell_ready": installable_shell_ready,
        "service_worker_cache_bounded": service_worker_cache_bounded,
        "service_worker_runtime_cache_max_entries": 32,
        "service_worker_runtime_cache_budgeted": service_worker_runtime_cache_budgeted,
        "production_registration_bounded": production_registration_bounded,
        "offline_page_ready": offline_page_ready,
        "draft_preservation_ready": draft_preservation_ready,
        "scratchpad_local_only": scratchpad_local_only,
        "offline_storage_recovery_ready": offline_storage_recovery_ready,
        "deferred_queue_ready": deferred_queue_ready,
        "deferred_queue_privacy_guarded": deferred_queue_privacy_guarded,
        "no_offline_model_generation": no_offline_model_generation,
        "frontend_tests_tracked": frontend_tests_tracked,
        "ci_tests_tracked": ci_tests_tracked,
        "expected_snippets_by_section": expected_snippets_by_section,
        "observed_snippets_by_section": observed_snippets_by_section,
        "missing_snippets_by_section": missing_snippets_by_section,
        "snippet_inventory_exact": snippet_inventory_exact,
        "private_api_prefix_count": len(PRIVATE_API_PREFIXES),
        "private_api_prefixes": list(PRIVATE_API_PREFIXES),
        "external_launch_ready": False,
        "evidence": {
            "packet": _display_path(packet_path),
            "docs": _display_path(doc_path),
            "index": _display_path(index_path),
            "manifest": _display_path(manifest_path),
            "offline_page": _display_path(offline_page_path),
            "service_worker": _display_path(service_worker_path),
            "pwa_registration": _display_path(pwa_ts_path),
            "main_entry": _display_path(main_tsx_path),
            "app_shell": _display_path(app_tsx_path),
            "hosted_platform": _display_path(hosted_tsx_path),
            "offline_drafts": _display_path(offline_drafts_path),
            "offline_scratchpad": _display_path(offline_scratchpad_path),
            "offline_storage_repair": _display_path(offline_storage_repair_path),
            "deferred_actions": _display_path(deferred_actions_path),
            "ci_workflow": _display_path(ci_workflow_path),
        },
        "failure_count": len(failures),
        "failures": failures,
    }


def write_phase6_pwa_offline_lite_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _packet_scope_covered(packet: str, failures: list[dict[str, str]]) -> bool:
    return _all_snippets("packet", packet, PHASE6_SCOPE_ITEMS, failures)


def _docs_current(doc: str, failures: list[dict[str, str]]) -> bool:
    return _all_snippets("docs", doc, REQUIRED_DOC_SNIPPETS, failures)


def _installable_shell_ready(index_html: str, manifest: dict[str, Any], failures: list[dict[str, str]]) -> bool:
    checks = [
        _expect('<link rel="manifest" href="/manifest.webmanifest" />' in index_html, "app_shell", "index must link manifest", failures),
        _expect("Agronomy Agent" in str(manifest.get("name") or ""), "manifest", "manifest name must identify Agronomy Agent", failures),
        _expect(manifest.get("start_url") == "/", "manifest", "manifest start_url must be root", failures),
        _expect(manifest.get("scope") == "/", "manifest", "manifest scope must be root", failures),
        _expect(manifest.get("display") == "standalone", "manifest", "manifest display must be standalone", failures),
        _expect(bool(manifest.get("theme_color")), "manifest", "manifest theme_color is required", failures),
        _expect(any(isinstance(icon, dict) and icon.get("src") == "/icons/agronomy-agent.svg" for icon in manifest.get("icons") or []), "manifest", "manifest must include app icon", failures),
    ]
    return all(checks)


def _service_worker_cache_bounded(service_worker: str, failures: list[dict[str, str]]) -> bool:
    checks = [
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[0] in service_worker, "service_worker", "service worker must define precache urls", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[1] in service_worker, "service_worker", "offline page must be precached", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[2] in service_worker, "service_worker", "manifest must be precached", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[3] in service_worker, "service_worker", "icon must be precached", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[4] in service_worker, "service_worker", "non-GET requests must bypass cache", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[5] in service_worker, "service_worker", "cross-origin requests must bypass cache", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[6] in service_worker, "service_worker", "only static Vite assets may lazy-cache", failures),
        _expect(REQUIRED_SERVICE_WORKER_SNIPPETS[7] in service_worker, "service_worker", "navigate fallback must be explicit", failures),
        _expect("RUNTIME_CACHE_NAME" in service_worker, "service_worker", "runtime asset cache must be separate from shell cache", failures),
        _expect("PHASE6_RUNTIME_CACHE_MAX_ENTRIES = 32" in service_worker, "service_worker", "runtime cache must keep a finite 32-entry budget", failures),
        _expect("ACTIVE_CACHE_NAMES" in service_worker, "service_worker", "activation must preserve shell and runtime caches", failures),
        _expect("trimPhase6RuntimeCache" in service_worker and "cache.delete(keys[index])" in service_worker, "service_worker", "runtime cache must trim old entries", failures),
        _expect("cachePhase6RuntimeAsset" in service_worker, "service_worker", "runtime asset caching must use the bounded helper", failures),
        _expect("!ACTIVE_CACHE_NAMES.includes(key)" in service_worker, "service_worker", "activation cleanup must keep all current Phase 6 caches", failures),
        _expect("event.waitUntil(cachePhase6ShellIndex(copy))" in service_worker, "service_worker", "navigate shell cache writes must be waitUntil-bound", failures),
        _expect("event.waitUntil(cachePhase6RuntimeAsset(request, copy))" in service_worker, "service_worker", "runtime asset cache writes must be waitUntil-bound", failures),
    ]
    private_prefixes_present = _all_snippets("service_worker", service_worker, (f"'{prefix}'" for prefix in PRIVATE_API_PREFIXES), failures)
    forbidden_precache = [prefix for prefix in PRIVATE_API_PREFIXES if f"'{prefix}" in _precache_block(service_worker)]
    if forbidden_precache:
        failures.append({"section": "service_worker", "reason": f"private prefixes must not be precached: {', '.join(forbidden_precache)}"})
    return all(checks) and private_prefixes_present and not forbidden_precache


def _service_worker_runtime_cache_budgeted(service_worker: str) -> bool:
    required = (
        "PHASE6_RUNTIME_CACHE_MAX_ENTRIES = 32",
        "trimPhase6RuntimeCache",
        "cache.delete(keys[index])",
        "event.waitUntil(cachePhase6RuntimeAsset(request, copy))",
        "!ACTIVE_CACHE_NAMES.includes(key)",
    )
    return all(snippet in service_worker for snippet in required)


def _production_registration_bounded(pwa_ts: str, main_tsx: str, failures: list[dict[str, str]]) -> bool:
    return _all_snippets("pwa_registration", pwa_ts, REQUIRED_PWA_REGISTRATION_SNIPPETS, failures) and _all_snippets(
        "main_entry",
        main_tsx,
        REQUIRED_MAIN_ENTRY_SNIPPETS,
        failures,
    )


def _offline_page_ready(offline_page: str, failures: list[dict[str, str]]) -> bool:
    return _all_snippets("offline_page", offline_page, REQUIRED_OFFLINE_PAGE_SNIPPETS, failures)


def _draft_preservation_ready(offline_drafts: str, app_tsx: str, failures: list[dict[str, str]]) -> bool:
    module_ready = _all_snippets(
        "offline_drafts",
        offline_drafts,
        REQUIRED_OFFLINE_DRAFTS_SNIPPETS,
        failures,
    )
    app_ready = _all_snippets(
        "app_offline_ui",
        app_tsx,
        REQUIRED_APP_OFFLINE_UI_SNIPPETS[:3],
        failures,
    )
    return module_ready and app_ready


def _scratchpad_local_only(offline_scratchpad: str, app_tsx: str, failures: list[dict[str, str]]) -> bool:
    module_ready = _all_snippets(
        "offline_scratchpad",
        offline_scratchpad,
        REQUIRED_OFFLINE_SCRATCHPAD_SNIPPETS,
        failures,
    )
    app_ready = _all_snippets(
        "app_offline_ui",
        app_tsx,
        REQUIRED_APP_OFFLINE_UI_SNIPPETS[3:],
        failures,
    )
    return module_ready and app_ready


def _deferred_queue_ready(deferred_actions: str, hosted_tsx: str, failures: list[dict[str, str]]) -> bool:
    module_ready = _all_snippets(
        "deferred_actions",
        deferred_actions,
        REQUIRED_DEFERRED_ACTION_SNIPPETS[:13],
        failures,
    )
    hosted_ready = _all_snippets(
        "hosted_deferred_actions",
        hosted_tsx,
        REQUIRED_HOSTED_DEFERRED_ACTION_SNIPPETS,
        failures,
    )
    return module_ready and hosted_ready


def _deferred_queue_privacy_guarded(deferred_actions: str, failures: list[dict[str, str]]) -> bool:
    forbidden = ("human_correction", "ideal_answer", "uploaded_file_text", "raw_field_notes", "public_answer_markdown")
    found = [term for term in forbidden if term in deferred_actions]
    if found:
        failures.append({"section": "deferred_actions", "reason": f"deferred queue must not allow raw text fields: {', '.join(found)}"})
    return _all_snippets("deferred_actions", deferred_actions, REQUIRED_DEFERRED_ACTION_SNIPPETS[10:], failures) and not found


def _no_offline_model_generation(
    *,
    service_worker: str,
    offline_page: str,
    doc: str,
    app_tsx: str,
    hosted_tsx: str,
    deferred_actions: str,
    failures: list[dict[str, str]],
) -> bool:
    combined = "\n".join([service_worker, offline_page, doc, app_tsx, hosted_tsx, deferred_actions]).lower()
    forbidden = ("webllm", "transformers.js", "browser_model", "offline model answer generation enabled")
    found = [term for term in forbidden if term in combined]
    if found:
        failures.append({"section": "offline_boundary", "reason": f"default offline shell must not include browser model generation hooks: {', '.join(found)}"})
    return _expect("The agent does not generate answers while its local service is unavailable." in offline_page, "offline_boundary", "offline no-model boundary must be visible", failures) and not found


def _frontend_tests_tracked(failures: list[dict[str, str]]) -> bool:
    missing = [test for test in EXPECTED_FRONTEND_TESTS if not (ROOT / "frontend/src" / test).exists()]
    if missing:
        failures.append({"section": "frontend_tests", "reason": f"missing frontend tests: {', '.join(missing)}"})
    return not missing


def _ci_tests_tracked(ci_workflow: str, failures: list[dict[str, str]]) -> bool:
    return _all_snippets("ci_workflow", ci_workflow, REQUIRED_CI_WORKFLOW_SNIPPETS, failures)


def _precache_block(service_worker: str) -> str:
    start = service_worker.find("PRECACHE_URLS")
    end = service_worker.find("const PRIVATE_API_PREFIXES")
    if start == -1 or end == -1 or end < start:
        return ""
    return service_worker[start:end]


def _read_text(path: Path, section: str, failures: list[dict[str, str]]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return ""


def _load_json(path: Path, section: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        failures.append({"section": section, "reason": f"could not read {_display_path(path)}: {exc}"})
        return {}
    if not isinstance(payload, dict):
        failures.append({"section": section, "reason": f"{_display_path(path)} must contain a JSON object"})
        return {}
    return payload


def _all_snippets(section: str, text: str, snippets: Any, failures: list[dict[str, str]]) -> bool:
    results = [_expect(str(snippet) in text, section, f"missing snippet: {snippet}", failures) for snippet in snippets]
    return all(results)


def _expect(condition: bool, section: str, reason: str, failures: list[dict[str, str]]) -> bool:
    if not condition:
        failures.append({"section": section, "reason": reason})
    return condition


def _json_snippet_map(snippets_by_section: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    return {section: list(snippets) for section, snippets in sorted(snippets_by_section.items())}


def _observed_snippets_by_section(texts_by_section: dict[str, str]) -> dict[str, list[str]]:
    observed: dict[str, list[str]] = {}
    for section, snippets in sorted(REQUIRED_SNIPPETS_BY_SECTION.items()):
        text = texts_by_section.get(section, "")
        observed[section] = [snippet for snippet in snippets if snippet in text]
    return observed


def _missing_snippets_by_section(observed_snippets_by_section: dict[str, list[str]]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    for section, snippets in sorted(REQUIRED_SNIPPETS_BY_SECTION.items()):
        observed = set(observed_snippets_by_section.get(section, []))
        missing[section] = [snippet for snippet in snippets if snippet not in observed]
    return missing


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)
