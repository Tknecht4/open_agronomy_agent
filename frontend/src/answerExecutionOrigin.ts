import type { Turn } from './types'

type RecordValue = Record<string, unknown>
export type AnswerExecutionOrigin = {
  status: 'recorded' | 'unavailable' | 'conflicting'
  execution: string
  finalOrigin: string
  detail: string
  modelResponseBound: boolean
}

const record = (value: unknown): RecordValue => value && typeof value === 'object' && !Array.isArray(value)
  ? value as RecordValue : {}
const text = (value: unknown): string => typeof value === 'string' ? value.trim() : ''
const digest = (value: unknown): boolean => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value)
const positions = { deterministic_bypass: 10, draft_generation: 11, verification: 12, fallback_origin: 16 } as const

/** Present the production server's retained observations, not current runtime readiness.
 * Receipt hashes are retained identifiers; this view does not authenticate their bytes.
 */
export function answerExecutionOrigin(turn: Turn | null | undefined): AnswerExecutionOrigin {
  const unavailable = (detail: string, execution = 'Execution not recorded', finalOrigin = 'Final origin unavailable'): AnswerExecutionOrigin => ({
    status: 'unavailable', execution, finalOrigin, detail, modelResponseBound: false,
  })
  const conflict = (): AnswerExecutionOrigin => ({
    status: 'conflicting', execution: 'Execution evidence conflicts', finalOrigin: 'Final origin unavailable',
    detail: 'The retained execution and origin records disagree. No model or tool attribution is established.', modelResponseBound: false,
  })
  const metadata = record(turn?.trace?.metadata)
  const receipts = metadata.execution_stage_receipts
  if (!Array.isArray(receipts)) return unavailable('This answer has no retained production execution receipt, including older answers.', 'Execution not recorded', 'Final origin not recorded')
  const stages: Record<string, RecordValue> = {}
  for (const [id, position] of Object.entries(positions)) {
    const matches = receipts.filter(value => record(value).stage_id === id)
    if (matches.length > 1) return conflict()
    if (!matches.length) continue
    const stage = record(matches[0])
    if (stage.schema_version !== 'open_agronomy_agent.execution_stage_receipt.v2'
      || stage.topology_version !== 'open_agronomy_agent.production_stage_topology.v3'
      || stage.position !== position || !digest(stage.receipt_sha256) || !digest(stage.evidence_sha256)) {
      return unavailable('The retained execution receipt is incomplete or has an unsupported format.')
    }
    stages[id] = stage
  }
  const draft = stages.draft_generation
  if (!draft) return unavailable('The retained receipt does not record draft generation.')
  const generation = record(draft.evidence)
  const path = text(generation.generation_path)
  const called = generation.model_call_executed
  const bypass = stages.deterministic_bypass
  const bypassEvidence = record(bypass?.evidence)
  if (!path || typeof called !== 'boolean') return unavailable('The generation observation is incomplete.')
  for (const value of [turn?.system_state?.generation_path, metadata.generation_path, bypassEvidence.generation_path]) {
    if (value !== undefined && value !== path) return conflict()
  }
  const originStage = stages.fallback_origin
  const originEvidence = record(originStage?.evidence)
  const origin = record(originEvidence.origin_record)
  const originClass = text(origin.origin_class)
  const identity = turn?.system_state?.model_identity
  const traceIdentity = record(metadata.model_identity)
  if (identity && Object.keys(traceIdentity).length && ['status', 'configured_model_id', 'configured_model_revision',
    'backend', 'response_model_id', 'model_config_sha256', 'receipt_sha256'].some(key =>
    traceIdentity[key] !== (identity as RecordValue)[key])) return conflict()
  const mock = originClass === 'mock_generator'
  let execution: string
  if (draft.state === 'executed' && called && bypassEvidence.bypass_selected !== true) {
    execution = mock ? 'Mock generator recorded' : 'Model call recorded'
  } else if (draft.state === 'bypassed' && !called && bypass?.state === 'executed' && bypassEvidence.bypass_selected === true) {
    execution = 'Model not used'
  } else if (draft.state === 'failed' && bypassEvidence.bypass_selected !== true) {
    execution = called ? 'Model call recorded · generation failed' : 'Model call not executed · generation unavailable'
  } else if (['not_applicable', 'disabled_by_arm', 'bypassed'].includes(String(draft.state)) && !called
    && bypassEvidence.bypass_selected !== true) {
    return unavailable('Generation was skipped; no final response origin is established.', 'Model call not executed · generation skipped')
  } else return conflict()
  if (!originStage || originStage.state !== 'executed' || !originClass) {
    return unavailable('Final response origin is missing or was not completed.', execution, originStage ? 'Final origin unavailable' : 'Final origin not recorded')
  }
  if (!bypass || typeof bypassEvidence.bypass_selected !== 'boolean') return unavailable('The bypass observation is incomplete.', execution)
  if ((bypassEvidence.bypass_selected && bypass.state !== 'executed')
    || (!bypassEvidence.bypass_selected && bypass.state !== 'not_applicable')) return conflict()
  const keys = ['origin_class', 'fallback_used', 'fallback_kind', 'draft_sha256', 'post_verification_sha256',
    'final_sha256', 'rewrite_accepted', 'verification_fallback_applied', 'replacement_used', 'verification_action']
  if (keys.some(key => originEvidence[key] !== origin[key]) || origin.generation_path !== path
    || generation.draft_sha256 !== origin.draft_sha256) return conflict()
  if (!digest(origin.draft_sha256) || !digest(origin.post_verification_sha256) || !digest(origin.final_sha256)
    || ['fallback_used', 'rewrite_accepted', 'verification_fallback_applied', 'replacement_used'].some(key => typeof origin[key] !== 'boolean')) {
    return unavailable('Final response origin is incomplete.', execution)
  }
  if (origin.replacement_used !== (origin.draft_sha256 !== origin.post_verification_sha256)
    || (origin.rewrite_accepted && origin.verification_fallback_applied)) return conflict()
  const action = origin.verification_action
  if (['typed_capability_validation', 'reviewed_draft_preserved', 'not_triggered', 'not_recorded'].includes(String(action))
    && origin.replacement_used) return conflict()
  if (origin.verification_fallback_applied && (action !== 'conservative_fallback' || originClass !== 'verifier_conservative_fallback')) return conflict()
  if (origin.rewrite_accepted && (action !== 'accepted_editor_rewrite' || originClass !== 'verifier_editor_rewrite')) return conflict()
  if (action === 'conservative_fallback' && !origin.verification_fallback_applied) return conflict()
  if (action === 'accepted_editor_rewrite' && !origin.rewrite_accepted) return conflict()
  if (!['typed_capability_validation', 'reviewed_draft_preserved', 'not_triggered', 'not_recorded',
    'conservative_fallback', 'accepted_editor_rewrite'].includes(String(action))) return unavailable('The verification action is not recognized.', execution)
  if (originClass === 'verifier_editor_rewrite' || originClass === 'verifier_conservative_fallback') {
    const verifier = stages.verification
    if (!verifier) return unavailable('The claimed verifier origin has no observed verification stage.', execution)
    const observed = record(verifier.evidence)
    if (!['executed', 'completed'].includes(String(verifier.state)) || observed.executed === false) return conflict()
    if (observed.executed !== true || !digest(observed.adjudication_sha256)
      || !digest(observed.draft_sha256) || !digest(observed.post_verification_sha256)
      || !digest(origin.verification_receipt_sha256)) return unavailable('The verifier observation or its origin linkage is incomplete.', execution)
    if (observed.adjudication_sha256 !== origin.verification_receipt_sha256
      || originEvidence.verification_receipt_sha256 !== origin.verification_receipt_sha256
      || observed.draft_sha256 !== origin.draft_sha256
      || observed.post_verification_sha256 !== origin.post_verification_sha256) return conflict()
  }
  const answerStages = record(metadata.answer_stages)
  for (const [name, hash] of [['draft', origin.draft_sha256], ['post_verification', origin.post_verification_sha256], ['final', origin.final_sha256]]) {
    const stageHash = record(answerStages[String(name)]).sha256
    if (stageHash !== undefined && stageHash !== hash) return conflict()
  }
  const integrity = turn?.answer_integrity_receipt
  if (integrity?.status === 'invalid' || (integrity?.answer_sha256 && integrity.answer_sha256 !== origin.final_sha256)) return conflict()
  if (turn?.system_state?.mode === 'mock' && !mock) return conflict()
  if (!origin.fallback_used && origin.fallback_kind !== null) return conflict()
  let finalOrigin: string
  if (originClass === 'deterministic_bypass') {
    if (draft.state !== 'bypassed' || called || origin.fallback_used || origin.rewrite_accepted || origin.verification_fallback_applied) return conflict()
    if (path === 'deterministic_tool_result') finalOrigin = 'Local tool result'
    else if (path === 'deterministic_tool_clarification') finalOrigin = 'Local tool clarification'
    else if (path === 'deterministic_evidence_sufficiency_hold') finalOrigin = 'Local evidence clarification'
    else return unavailable('The recorded deterministic renderer is not recognized.', execution)
  } else if (originClass === 'verifier_conservative_fallback') {
    if (!origin.fallback_used || !origin.verification_fallback_applied || origin.rewrite_accepted
      || bypassEvidence.bypass_selected || draft.state !== 'executed' || !called
      || origin.fallback_kind !== 'verification_conservative') return conflict()
    finalOrigin = 'Verifier conservative fallback'
  } else if (originClass === 'verifier_editor_rewrite') {
    if (!origin.rewrite_accepted || origin.verification_fallback_applied || origin.fallback_used || draft.state !== 'executed' || !called) return conflict()
    finalOrigin = 'Verifier rewrite'
  } else if (originClass === 'analysis_unavailable_fallback') {
    if (!origin.fallback_used || origin.verification_fallback_applied || origin.rewrite_accepted || draft.state !== 'failed'
      || origin.fallback_kind !== 'generation_unavailable') return conflict()
    finalOrigin = 'Analysis unavailable fallback'
  } else if (originClass === 'mock_generator') {
    if (draft.state !== 'executed' || origin.fallback_used || origin.rewrite_accepted || origin.verification_fallback_applied) return conflict()
    finalOrigin = 'Mock response'
  } else if (originClass === 'configured_model') {
    if (draft.state !== 'executed' || !called || path !== 'model_generation'
      || origin.fallback_used || origin.rewrite_accepted || origin.verification_fallback_applied) return conflict()
    if (!text(identity?.configured_model_id) || !text(identity?.response_model_id)
      || !['verified_direct_loader', 'verified_runtime_receipt'].includes(text(identity?.status))) {
      return unavailable('A model call is recorded, but this answer has no verified response-bound model identity.', execution)
    }
    finalOrigin = 'Configured model response'
  } else return unavailable('The retained final origin is not recognized.', execution)
  return {
    status: 'recorded', execution, finalOrigin,
    detail: 'Origin recorded for this answer. This does not establish source support, current authority or agronomic validity.',
    modelResponseBound: originClass === 'configured_model',
  }
}
