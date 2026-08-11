type WebGpuStatus = 'disabled' | 'unsupported' | 'available' | 'error'
type LocalCapabilityStatus = 'disabled' | 'unsupported' | 'available' | 'research_only'

type NavigatorWithGpu = Navigator & {
  gpu?: {
    requestAdapter?: () => Promise<unknown>
  }
}

type LocalPreviewWindowLike = {
  Transformers?: unknown
  transformers?: unknown
  MLCEngine?: unknown
  webllm?: unknown
  ai?: {
    summarizer?: unknown
    writer?: unknown
    rewriter?: unknown
    languageModel?: unknown
  }
}

export type WebGpuPreviewProbeResult = {
  featureEnabled: boolean
  status: WebGpuStatus
  supported: boolean
  secureContext: boolean
  adapterAvailable: boolean
  canonicalAnswerPath: 'server_harness'
  message: string
  limitations: string[]
}

export type LocalPreviewTaskId =
  | 'canonical_agronomy_answer'
  | 'local_note_summarization'
  | 'report_section_rewrite'
  | 'image_embedding_similarity'
  | 'regulated_product_label_answer'
  | 'field_specific_diagnostic_answer'
  | 'offline_toy_demo'
  | 'private_field_notes_preprocessing'

export type LocalPreviewStackId = 'webgpu' | 'transformers_js' | 'webllm' | 'chrome_built_in_ai' | 'wasm_cpu'

export type LocalInferenceCapability = {
  stackId: LocalPreviewStackId
  label: string
  status: LocalCapabilityStatus
  available: boolean
  noDownloadProbe: true
  reason: string
}

export type LocalInferenceDecision = {
  taskId: LocalPreviewTaskId
  task: string
  risk: string
  candidateRuntime: string
  allowedPhase6: string
  defaultEnabled: boolean
  serverHarnessRequired: boolean
  localPreprocessAllowed: boolean
  localDraftAllowed: boolean
  localOnlyBlockedReason: string
  hybridFallbackReason: string
  requiresConsent: boolean
  downloadAllowed: boolean
  trainingCandidateAllowed: boolean
  outputLabel: 'server_harness_required' | 'local_preprocess_allowed' | 'local_draft_allowed' | 'research_only'
  notes: string
}

export type LocalInferencePreviewState = {
  featureEnabled: boolean
  consentGranted: boolean
  downloadConsent: boolean
  canonicalAnswerPath: 'server_harness'
  noDownloadGuarantee: string
  capabilities: LocalInferenceCapability[]
  decisions: LocalInferenceDecision[]
}

export const localPreviewLimitations = [
  'Canonical agronomy answers stay on the server harness with trace and eval capture.',
  'No browser model download starts from this probe.',
  'Local preview is limited to low-risk drafts or preprocessing after explicit consent.',
]

const taskMatrix: Record<
  LocalPreviewTaskId,
  {
    task: string
    risk: string
    candidateRuntime: string
    allowedPhase6: string
    defaultEnabled: boolean
    notes: string
  }
> = {
  canonical_agronomy_answer: {
    task: 'canonical agronomy answer',
    risk: 'medium/high/regulated',
    candidateRuntime: 'server 4-bit harness',
    allowedPhase6: 'yes',
    defaultEnabled: true,
    notes: 'Retains full trace/eval/guardrail path.',
  },
  local_note_summarization: {
    task: 'local summarization of user notes',
    risk: 'low',
    candidateRuntime: 'Transformers.js or Chrome built-in AI',
    allowedPhase6: 'yes behind flag',
    defaultEnabled: false,
    notes: 'Useful privacy/cost experiment; do not treat as final advice.',
  },
  report_section_rewrite: {
    task: 'rewrite report section',
    risk: 'low',
    candidateRuntime: 'WebLLM or built-in Writer/Rewriter API',
    allowedPhase6: 'yes behind flag',
    defaultEnabled: false,
    notes: 'Clearly label local draft.',
  },
  image_embedding_similarity: {
    task: 'image embedding / similarity search',
    risk: 'low/medium',
    candidateRuntime: 'Transformers.js/OpenCLIP-style model',
    allowedPhase6: 'research only',
    defaultEnabled: false,
    notes: 'May help VLM-RAG, but calibration required.',
  },
  regulated_product_label_answer: {
    task: 'regulated product/label answer',
    risk: 'regulated',
    candidateRuntime: 'server harness only',
    allowedPhase6: 'yes',
    defaultEnabled: true,
    notes: 'Never local-only in Phase 6.',
  },
  field_specific_diagnostic_answer: {
    task: 'field-specific diagnostic answer',
    risk: 'medium',
    candidateRuntime: 'server harness only',
    allowedPhase6: 'yes',
    defaultEnabled: true,
    notes: 'Local preprocessing okay, final answer server.',
  },
  offline_toy_demo: {
    task: 'offline toy demo',
    risk: 'low',
    candidateRuntime: 'WebLLM small model',
    allowedPhase6: 'optional',
    defaultEnabled: false,
    notes: 'Use synthetic data and visible limitations.',
  },
  private_field_notes_preprocessing: {
    task: 'private field notes preprocessing',
    risk: 'low',
    candidateRuntime: 'client worker + optional local model',
    allowedPhase6: 'yes behind consent',
    defaultEnabled: false,
    notes: 'Never silently upload or cache raw notes.',
  },
}

export const isWebGpuPreviewEnabled = (env: Record<string, unknown> = import.meta.env): boolean =>
  env.VITE_ENABLE_WEBGPU_PREVIEW === 'true'

export const disabledWebGpuPreviewState = (): WebGpuPreviewProbeResult => ({
  featureEnabled: false,
  status: 'disabled',
  supported: false,
  secureContext: false,
  adapterAvailable: false,
  canonicalAnswerPath: 'server_harness',
  message: 'Local preview is disabled by feature flag. Server-hosted answers remain the canonical path.',
  limitations: localPreviewLimitations,
})

export const probeWebGpuPreview = async (
  options: {
    featureEnabled?: boolean
    navigatorLike?: NavigatorWithGpu
    secureContext?: boolean
  } = {},
): Promise<WebGpuPreviewProbeResult> => {
  const featureEnabled = options.featureEnabled ?? isWebGpuPreviewEnabled()
  if (!featureEnabled) {
    return disabledWebGpuPreviewState()
  }

  const secureContext = options.secureContext ?? Boolean(window.isSecureContext)
  const gpu = ((options.navigatorLike || navigator) as NavigatorWithGpu).gpu
  if (!secureContext) {
    return {
      featureEnabled,
      status: 'unsupported',
      supported: false,
      secureContext,
      adapterAvailable: false,
      canonicalAnswerPath: 'server_harness',
      message: 'WebGPU requires a secure browser context. Server-hosted answers remain available.',
      limitations: localPreviewLimitations,
    }
  }
  if (!gpu?.requestAdapter) {
    return {
      featureEnabled,
      status: 'unsupported',
      supported: false,
      secureContext,
      adapterAvailable: false,
      canonicalAnswerPath: 'server_harness',
      message: 'This browser does not expose WebGPU. Server-hosted answers remain available.',
      limitations: localPreviewLimitations,
    }
  }

  try {
    const adapter = await gpu.requestAdapter()
    return {
      featureEnabled,
      status: adapter ? 'available' : 'unsupported',
      supported: Boolean(adapter),
      secureContext,
      adapterAvailable: Boolean(adapter),
      canonicalAnswerPath: 'server_harness',
      message: adapter
        ? 'WebGPU is available for future low-risk local-preview experiments. Server-hosted answers remain canonical.'
        : 'WebGPU did not return an adapter. Server-hosted answers remain available.',
      limitations: localPreviewLimitations,
    }
  } catch {
    return {
      featureEnabled,
      status: 'error',
      supported: false,
      secureContext,
      adapterAvailable: false,
      canonicalAnswerPath: 'server_harness',
      message: 'WebGPU probing failed. Server-hosted answers remain available.',
      limitations: localPreviewLimitations,
    }
  }
}

export const evaluateLocalInferenceDecision = (
  taskId: LocalPreviewTaskId,
  options: {
    featureEnabled?: boolean
    consentGranted?: boolean
    downloadConsent?: boolean
    syncedAndReviewed?: boolean
  } = {},
): LocalInferenceDecision => {
  const featureEnabled = Boolean(options.featureEnabled)
  const consentGranted = Boolean(options.consentGranted)
  const downloadConsent = Boolean(options.downloadConsent)
  const syncedAndReviewed = Boolean(options.syncedAndReviewed)
  const row = taskMatrix[taskId]
  const consentReady = featureEnabled && consentGranted
  const serverOnly = taskId === 'canonical_agronomy_answer' || taskId === 'regulated_product_label_answer'
  const finalServerRequired = serverOnly || taskId === 'field_specific_diagnostic_answer'
  const researchOnly = taskId === 'image_embedding_similarity'
  const lowRiskDraft = taskId === 'local_note_summarization' || taskId === 'report_section_rewrite' || taskId === 'offline_toy_demo'
  const preprocessOnly = taskId === 'private_field_notes_preprocessing'
  const anyLocalLane = lowRiskDraft || preprocessOnly || researchOnly || taskId === 'field_specific_diagnostic_answer'
  const localPreprocessAllowed = !serverOnly && consentReady && anyLocalLane
  const localDraftAllowed = consentReady && lowRiskDraft
  const downloadAllowed = localDraftAllowed && downloadConsent
  const trainingCandidateAllowed = localDraftAllowed && consentGranted && syncedAndReviewed
  const localOnlyBlockedReason = serverOnly
    ? 'server_harness_required'
    : !featureEnabled
      ? 'feature_flag_disabled'
      : !consentGranted
        ? 'explicit_consent_required'
        : researchOnly
          ? 'research_review_required'
          : finalServerRequired
            ? 'final_answer_requires_server_trace'
            : ''
  const outputLabel = researchOnly
    ? 'research_only'
    : localDraftAllowed
      ? 'local_draft_allowed'
      : localPreprocessAllowed
        ? 'local_preprocess_allowed'
        : 'server_harness_required'

  return {
    taskId,
    task: row.task,
    risk: row.risk,
    candidateRuntime: row.candidateRuntime,
    allowedPhase6: row.allowedPhase6,
    defaultEnabled: row.defaultEnabled,
    serverHarnessRequired: finalServerRequired || serverOnly,
    localPreprocessAllowed,
    localDraftAllowed,
    localOnlyBlockedReason,
    hybridFallbackReason: localDraftAllowed || localPreprocessAllowed ? 'server_harness_remains_canonical_fallback' : localOnlyBlockedReason,
    requiresConsent: !serverOnly && anyLocalLane,
    downloadAllowed,
    trainingCandidateAllowed,
    outputLabel,
    notes: row.notes,
  }
}

export const buildLocalInferencePreviewState = (
  options: {
    featureEnabled?: boolean
    consentGranted?: boolean
    downloadConsent?: boolean
    syncedAndReviewed?: boolean
    webGpuProbe?: WebGpuPreviewProbeResult
    windowLike?: LocalPreviewWindowLike
  } = {},
): LocalInferencePreviewState => {
  const featureEnabled = Boolean(options.featureEnabled)
  const consentGranted = Boolean(options.consentGranted)
  const windowLike: LocalPreviewWindowLike = options.windowLike ?? (typeof window === 'undefined' ? {} : (window as LocalPreviewWindowLike))
  const stackStatus = (available: boolean): LocalCapabilityStatus => (featureEnabled ? (available ? 'available' : 'unsupported') : 'disabled')
  const webGpuAvailable = options.webGpuProbe?.status === 'available'
  const transformersAvailable = Boolean(windowLike.Transformers || windowLike.transformers)
  const webLlmAvailable = Boolean(windowLike.MLCEngine || windowLike.webllm)
  const chromeAiAvailable = Boolean(windowLike.ai?.summarizer || windowLike.ai?.writer || windowLike.ai?.rewriter || windowLike.ai?.languageModel)
  const capabilities: LocalInferenceCapability[] = [
    {
      stackId: 'webgpu',
      label: 'WebGPU',
      status: stackStatus(webGpuAvailable),
      available: featureEnabled && webGpuAvailable,
      noDownloadProbe: true,
      reason: webGpuAvailable ? 'adapter_available' : featureEnabled ? 'adapter_unavailable' : 'feature_flag_disabled',
    },
    {
      stackId: 'transformers_js',
      label: 'Transformers.js',
      status: stackStatus(transformersAvailable),
      available: featureEnabled && transformersAvailable,
      noDownloadProbe: true,
      reason: transformersAvailable ? 'adapter_present' : featureEnabled ? 'adapter_not_loaded' : 'feature_flag_disabled',
    },
    {
      stackId: 'webllm',
      label: 'WebLLM',
      status: stackStatus(webLlmAvailable),
      available: featureEnabled && webLlmAvailable,
      noDownloadProbe: true,
      reason: webLlmAvailable ? 'adapter_present' : featureEnabled ? 'adapter_not_loaded' : 'feature_flag_disabled',
    },
    {
      stackId: 'chrome_built_in_ai',
      label: 'Chrome built-in AI',
      status: stackStatus(chromeAiAvailable),
      available: featureEnabled && chromeAiAvailable,
      noDownloadProbe: true,
      reason: chromeAiAvailable ? 'api_present' : featureEnabled ? 'api_unavailable' : 'feature_flag_disabled',
    },
    {
      stackId: 'wasm_cpu',
      label: 'WASM/CPU fallback',
      status: featureEnabled ? 'research_only' : 'disabled',
      available: false,
      noDownloadProbe: true,
      reason: featureEnabled ? 'small_classifiers_only' : 'feature_flag_disabled',
    },
  ]

  return {
    featureEnabled,
    consentGranted,
    downloadConsent: Boolean(options.downloadConsent),
    canonicalAnswerPath: 'server_harness',
    noDownloadGuarantee: 'No local model download is allowed until feature flag, user consent, and explicit model-download confirmation are all true.',
    capabilities,
    decisions: (Object.keys(taskMatrix) as LocalPreviewTaskId[]).map((taskId) =>
      evaluateLocalInferenceDecision(taskId, {
        featureEnabled,
        consentGranted,
        downloadConsent: options.downloadConsent,
        syncedAndReviewed: options.syncedAndReviewed,
      }),
    ),
  }
}
