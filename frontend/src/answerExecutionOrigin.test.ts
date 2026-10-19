import { describe, expect, it } from 'vitest'
import { answerExecutionOrigin } from './answerExecutionOrigin'
import type { Turn, TurnExecutionStageReceipt } from './types'

const receipt = (stage_id: string, position: number, state: string, evidence: Record<string, unknown>): TurnExecutionStageReceipt => ({
  schema_version: 'open_agronomy_agent.execution_stage_receipt.v2', topology_version: 'open_agronomy_agent.production_stage_topology.v3',
  stage_id, position, state, evidence, evidence_sha256: 'a'.repeat(64), receipt_sha256: 'b'.repeat(64),
})
const fixture = (kind = 'configured_model', path = 'model_generation'): Turn => {
  const deterministic = kind === 'deterministic_bypass', failed = kind === 'analysis_unavailable_fallback'
  const rewrite = kind === 'verifier_editor_rewrite', conservative = kind === 'verifier_conservative_fallback'
  const origin = {
    origin_class: kind, generation_path: path, draft_sha256: 'c'.repeat(64),
    post_verification_sha256: (rewrite || conservative ? 'd' : 'c').repeat(64), final_sha256: 'e'.repeat(64),
    fallback_used: failed || conservative, fallback_kind: conservative ? 'verification_conservative' : failed ? 'generation_unavailable' : null,
    rewrite_accepted: rewrite, verification_fallback_applied: conservative, replacement_used: rewrite || conservative,
    verification_action: rewrite ? 'accepted_editor_rewrite' : conservative ? 'conservative_fallback' : deterministic ? 'typed_capability_validation' : 'not_triggered',
    verification_receipt_sha256: 'f'.repeat(64),
  }
  return {
    turn_id: 'origin-fixture', user_message: 'A synthetic question', answer: 'A synthetic answer', answer_status: 'draft',
    system_state: {
      mode: kind === 'mock_generator' ? 'mock' : 'agronomic_rag', model_id: 'configured-model', rag_config: null, prompt_version: 'fixture', generation_path: path,
      model_identity: { status: 'verified_direct_loader', configured_model_id: 'configured-model', response_model_id: 'response-model' },
    },
    trace: { metadata: { generation_path: path, execution_stage_receipts: [
      receipt('deterministic_bypass', 10, deterministic ? 'executed' : 'not_applicable', { bypass_selected: deterministic, generation_path: path }),
      receipt('draft_generation', 11, deterministic ? 'bypassed' : failed ? 'failed' : 'executed', { model_call_executed: !deterministic && !failed, generation_path: path, draft_sha256: origin.draft_sha256 }),
      receipt('verification', 12, rewrite || conservative ? 'executed' : 'not_applicable', {
        executed: rewrite || conservative, adjudication_sha256: origin.verification_receipt_sha256,
        draft_sha256: origin.draft_sha256, post_verification_sha256: origin.post_verification_sha256,
      }),
      receipt('fallback_origin', 16, 'executed', { ...origin, origin_record: origin }),
    ] } },
  }
}
const stages = (turn: Turn) => turn.trace!.metadata!.execution_stage_receipts!
const changeOrigin = (turn: Turn, changes: Record<string, unknown>) => {
  const evidence = stages(turn).find(stage => stage.stage_id === 'fallback_origin')!.evidence
  Object.assign(evidence, changes)
  Object.assign(evidence.origin_record as Record<string, unknown>, changes)
  if (changes.post_verification_sha256) stages(turn).find(stage => stage.stage_id === 'verification')!.evidence.post_verification_sha256 = changes.post_verification_sha256
}

describe('retained production execution and final origin', () => {
  it.each(['verified_direct_loader', 'verified_runtime_receipt'])('requires observed generation and %s identity', status => {
    const t = fixture(); t.system_state!.model_identity!.status = status
    t.trace!.metadata!.model_identity = { ...t.system_state!.model_identity }
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'recorded', execution: 'Model call recorded', finalOrigin: 'Configured model response', modelResponseBound: true })
  })
  it.each(['unverified', 'unverified_optional', undefined])('retains call without attributing response identity status %s', status => {
    const t = fixture(); t.system_state!.model_identity!.status = status
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', execution: 'Model call recorded', modelResponseBound: false })
  })
  it('does not infer execution from configured/bound identity or non-use from absent identity', () => {
    const t = fixture(); delete t.trace!.metadata!.execution_stage_receipts
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', execution: 'Execution not recorded' })
    const called = fixture(); delete called.system_state!.model_identity
    expect(answerExecutionOrigin(called)).toMatchObject({ status: 'unavailable', execution: 'Model call recorded' })
  })
  it.each([
    ['deterministic_tool_result', 'Local tool result'], ['deterministic_tool_clarification', 'Local tool clarification'],
    ['deterministic_evidence_sufficiency_hold', 'Local evidence clarification'],
  ])('labels %s without model attribution', (path, finalOrigin) => {
    const t = fixture('deterministic_bypass', path); delete t.system_state!.model_identity
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'recorded', execution: 'Model not used', finalOrigin, modelResponseBound: false })
  })
  it.each([
    ['verifier_editor_rewrite', 'Verifier rewrite'], ['verifier_conservative_fallback', 'Verifier conservative fallback'],
    ['analysis_unavailable_fallback', 'Analysis unavailable fallback'], ['mock_generator', 'Mock response'],
  ])('labels final %s separately', (kind, finalOrigin) => {
    expect(answerExecutionOrigin(fixture(kind))).toMatchObject({ status: 'recorded', finalOrigin, modelResponseBound: false })
  })
  it('keeps failed attempted generation separate from its fallback', () => {
    const t = fixture('analysis_unavailable_fallback'); stages(t)[1].evidence.model_call_executed = true
    expect(answerExecutionOrigin(t)).toMatchObject({ execution: 'Model call recorded · generation failed', finalOrigin: 'Analysis unavailable fallback' })
  })
  it('uses recorded mock origin even when the requested mode was agronomic_rag', () => {
    const t = fixture('mock_generator'); t.system_state!.mode = 'agronomic_rag'
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'recorded', execution: 'Mock generator recorded', finalOrigin: 'Mock response', modelResponseBound: false })
  })
  it('requires a complete verified configured identity without inferring non-use', () => {
    const t = fixture(); delete t.system_state!.model_identity!.configured_model_id
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', execution: 'Model call recorded', modelResponseBound: false })
  })
  it.each(['configured_model', 'verifier_conservative_fallback', 'analysis_unavailable_fallback'])('rejects contradictory fallback kind for %s', kind => {
    const t = fixture(kind); changeOrigin(t, { fallback_kind: 'contradiction' })
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it('supports an accepted same-text rewrite without calling it conservative fallback', () => {
    const t = fixture('verifier_editor_rewrite'); changeOrigin(t, { post_verification_sha256: 'c'.repeat(64), replacement_used: false })
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'recorded', finalOrigin: 'Verifier rewrite' })
  })
  it.each(['failed', 'not_applicable', 'disabled_by_arm'])('does not attribute final origin when its stage is %s', state => {
    const t = fixture(); stages(t).find(stage => stage.stage_id === 'fallback_origin')!.state = state
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', execution: 'Model call recorded' })
  })
  it.each(['bypassed', 'not_applicable', 'disabled_by_arm'])('retains skipped draft state %s', state => {
    const t = fixture(); stages(t)[1].state = state; stages(t)[1].evidence.model_call_executed = false
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', execution: 'Model call not executed · generation skipped' })
  })
  it.each(['draft_generation', 'fallback_origin', 'deterministic_bypass'])('fails closed on missing %s', id => {
    const t = fixture(); t.trace!.metadata!.execution_stage_receipts = stages(t).filter(s => s.stage_id !== id)
    expect(answerExecutionOrigin(t)).toMatchObject({ status: 'unavailable', modelResponseBound: false })
  })
  it.each(['schema_version', 'topology_version', 'receipt_sha256'])('rejects unsupported/incomplete %s', key => {
    const t = fixture(); Object.assign(stages(t)[1], { [key]: 'unsupported' })
    expect(answerExecutionOrigin(t).status).toBe('unavailable')
  })
  it.each(['status', 'response_model_id', 'configured_model_revision'])('rejects contradictory trace/system identity %s', key => {
    const t = fixture(); t.trace!.metadata!.model_identity = { ...t.system_state!.model_identity, [key]: 'contradiction' }
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it.each(['verifier_editor_rewrite', 'verifier_conservative_fallback'])('rejects consistently wrong action for %s', kind => {
    const t = fixture(kind); changeOrigin(t, { verification_action: 'not_triggered' })
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it.each(['conservative_fallback', 'accepted_editor_rewrite'])('rejects converse action %s without matching flags on real-shaped tool output', verification_action => {
    const t = fixture('deterministic_bypass', 'deterministic_tool_result'); changeOrigin(t, { verification_action })
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it('rejects conservative fallback combined with a selected deterministic bypass', () => {
    const t = fixture('verifier_conservative_fallback'); stages(t)[0].state = 'executed'; stages(t)[0].evidence.bypass_selected = true
    stages(t)[1].state = 'bypassed'; stages(t)[1].evidence.model_call_executed = false
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it.each(['not_triggered', 'not_recorded', 'reviewed_draft_preserved', 'typed_capability_validation'])('rejects replacement for preserved action %s', verification_action => {
    const t = fixture(); changeOrigin(t, { post_verification_sha256: 'd'.repeat(64), replacement_used: true, verification_action })
    expect(answerExecutionOrigin(t).status).toBe('conflicting')
  })
  it('rejects contradictory paths, calls, duplicate receipts and content hashes without rewriting them', () => {
    const path = fixture(); path.system_state!.generation_path = 'deterministic_tool_result'
    const call = fixture(); stages(call)[1].evidence.model_call_executed = false
    const duplicate = fixture(); stages(duplicate).push(stages(duplicate)[1])
    const hash = fixture(); hash.answer_integrity_receipt = { schema_version: 'fixture', status: 'verified', answer_sha256: 'f'.repeat(64) }
    const invalid = fixture(); invalid.answer_integrity_receipt = { schema_version: 'fixture', status: 'invalid' }
    const record = fixture(); stages(record).find(stage => stage.stage_id === 'fallback_origin')!.evidence.origin_class = 'deterministic_bypass'
    for (const t of [path, call, duplicate, hash, invalid, record]) {
      const before = JSON.stringify(t); expect(answerExecutionOrigin(t).status).toBe('conflicting'); expect(JSON.stringify(t)).toBe(before)
    }
  })
  it.each(['verifier_editor_rewrite', 'verifier_conservative_fallback'])('requires observed verification for %s', kind => {
    const missing = fixture(kind)
    missing.trace!.metadata!.execution_stage_receipts = stages(missing).filter(stage => stage.stage_id !== 'verification')
    expect(answerExecutionOrigin(missing)).toMatchObject({ status: 'unavailable', finalOrigin: 'Final origin unavailable', modelResponseBound: false })
    for (const state of ['failed', 'disabled_by_arm', 'not_applicable']) {
      const t = fixture(kind); stages(t).find(stage => stage.stage_id === 'verification')!.state = state
      expect(answerExecutionOrigin(t)).toMatchObject({ status: 'conflicting', finalOrigin: 'Final origin unavailable' })
    }
  })
  it.each(['verifier_editor_rewrite', 'verifier_conservative_fallback'])('requires actual verifier execution and hash linkage for %s', kind => {
    for (const key of ['adjudication_sha256', 'draft_sha256', 'post_verification_sha256']) {
      const t = fixture(kind); stages(t).find(stage => stage.stage_id === 'verification')!.evidence[key] = '9'.repeat(64)
      expect(answerExecutionOrigin(t).status).toBe('conflicting')
    }
    const notExecuted = fixture(kind); stages(notExecuted).find(stage => stage.stage_id === 'verification')!.evidence.executed = false
    expect(answerExecutionOrigin(notExecuted).status).toBe('conflicting')
    const incomplete = fixture(kind); delete stages(incomplete).find(stage => stage.stage_id === 'verification')!.evidence.executed
    expect(answerExecutionOrigin(incomplete).status).toBe('unavailable')
  })
})
