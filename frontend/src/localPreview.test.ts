import { describe, expect, it } from 'vitest'
import {
  buildLocalInferencePreviewState,
  disabledWebGpuPreviewState,
  evaluateLocalInferenceDecision,
  isWebGpuPreviewEnabled,
  probeWebGpuPreview,
} from './localPreview'

describe('local preview WebGPU probe', () => {
  it('is disabled unless the explicit feature flag is enabled', async () => {
    expect(isWebGpuPreviewEnabled({})).toBe(false)
    expect(isWebGpuPreviewEnabled({ VITE_ENABLE_WEBGPU_PREVIEW: 'true' })).toBe(true)
    expect(await probeWebGpuPreview({ featureEnabled: false })).toMatchObject(disabledWebGpuPreviewState())
  })

  it('reports unsupported browser state without throwing', async () => {
    const result = await probeWebGpuPreview({
      featureEnabled: true,
      secureContext: true,
      navigatorLike: {} as Navigator,
    })

    expect(result).toMatchObject({
      featureEnabled: true,
      status: 'unsupported',
      supported: false,
      canonicalAnswerPath: 'server_harness',
    })
    expect(result.message).toContain('does not expose WebGPU')
    expect(result.limitations.join(' ')).toContain('No browser model download')
  })

  it('distinguishes available adapters from missing adapters', async () => {
    const available = await probeWebGpuPreview({
      featureEnabled: true,
      secureContext: true,
      navigatorLike: { gpu: { requestAdapter: async () => ({ name: 'test-adapter' }) } } as unknown as Navigator,
    })
    const missing = await probeWebGpuPreview({
      featureEnabled: true,
      secureContext: true,
      navigatorLike: { gpu: { requestAdapter: async () => null } } as unknown as Navigator,
    })

    expect(available.status).toBe('available')
    expect(available.adapterAvailable).toBe(true)
    expect(missing.status).toBe('unsupported')
    expect(missing.adapterAvailable).toBe(false)
  })
})

describe('local inference preview matrix', () => {
  it('keeps all local model downloads blocked by default', () => {
    const state = buildLocalInferencePreviewState({ featureEnabled: false })

    expect(state.canonicalAnswerPath).toBe('server_harness')
    expect(state.noDownloadGuarantee).toContain('No local model download')
    expect(state.capabilities.every((capability) => capability.noDownloadProbe)).toBe(true)
    expect(state.capabilities.find((capability) => capability.stackId === 'transformers_js')?.status).toBe('disabled')
    expect(state.capabilities.find((capability) => capability.stackId === 'webllm')?.status).toBe('disabled')
    expect(state.decisions.every((decision) => decision.downloadAllowed === false)).toBe(true)
    expect(state.decisions.find((decision) => decision.taskId === 'canonical_agronomy_answer')).toMatchObject({
      serverHarnessRequired: true,
      outputLabel: 'server_harness_required',
      localDraftAllowed: false,
    })
    expect(state.decisions.find((decision) => decision.taskId === 'local_note_summarization')?.localOnlyBlockedReason).toBe('feature_flag_disabled')
  })

  it('allows only low-risk drafts after feature flag and consent while preserving server-only tasks', () => {
    const summary = evaluateLocalInferenceDecision('local_note_summarization', {
      featureEnabled: true,
      consentGranted: true,
      downloadConsent: true,
      syncedAndReviewed: true,
    })
    const regulated = evaluateLocalInferenceDecision('regulated_product_label_answer', {
      featureEnabled: true,
      consentGranted: true,
      downloadConsent: true,
      syncedAndReviewed: true,
    })
    const diagnostic = evaluateLocalInferenceDecision('field_specific_diagnostic_answer', {
      featureEnabled: true,
      consentGranted: true,
      downloadConsent: true,
    })

    expect(summary).toMatchObject({
      localDraftAllowed: true,
      downloadAllowed: true,
      trainingCandidateAllowed: true,
      outputLabel: 'local_draft_allowed',
    })
    expect(regulated).toMatchObject({
      serverHarnessRequired: true,
      localDraftAllowed: false,
      downloadAllowed: false,
      localOnlyBlockedReason: 'server_harness_required',
    })
    expect(diagnostic).toMatchObject({
      serverHarnessRequired: true,
      localPreprocessAllowed: true,
      localDraftAllowed: false,
      localOnlyBlockedReason: 'final_answer_requires_server_trace',
    })
  })

  it('detects optional browser adapters without importing or downloading models', () => {
    const state = buildLocalInferencePreviewState({
      featureEnabled: true,
      consentGranted: false,
      webGpuProbe: { ...disabledWebGpuPreviewState(), featureEnabled: true, status: 'available', supported: true, adapterAvailable: true },
      windowLike: {
        Transformers: {},
        MLCEngine: {},
        ai: { summarizer: {}, writer: {} },
      },
    })

    expect(state.capabilities.find((capability) => capability.stackId === 'webgpu')).toMatchObject({ status: 'available', noDownloadProbe: true })
    expect(state.capabilities.find((capability) => capability.stackId === 'transformers_js')).toMatchObject({ status: 'available', noDownloadProbe: true })
    expect(state.capabilities.find((capability) => capability.stackId === 'webllm')).toMatchObject({ status: 'available', noDownloadProbe: true })
    expect(state.capabilities.find((capability) => capability.stackId === 'chrome_built_in_ai')).toMatchObject({ status: 'available', noDownloadProbe: true })
    expect(state.decisions.find((decision) => decision.taskId === 'report_section_rewrite')?.localOnlyBlockedReason).toBe('explicit_consent_required')
  })

  it('keeps local drafts out of training candidates without sync review and consent', () => {
    expect(
      evaluateLocalInferenceDecision('report_section_rewrite', {
        featureEnabled: true,
        consentGranted: true,
        downloadConsent: false,
        syncedAndReviewed: false,
      }),
    ).toMatchObject({
      localDraftAllowed: true,
      downloadAllowed: false,
      trainingCandidateAllowed: false,
    })
  })
})
