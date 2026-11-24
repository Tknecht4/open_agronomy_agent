import { describe, expect, it } from 'vitest'
import { canAskWithReadiness, isBoundTurnReadiness, matchingTurnReadiness, turnReadinessKey, type TurnReadiness, type TurnReadinessState } from './turnReadiness'

const turn = { message: 'Convert 100 lb/ac to kg/ha', mode: 'agronomic_rag', model_id: 'missing-model', session_context: { field_context_id: 'field-a', field_record_updated_at: 'revision-a', field_context: { geometry: { type: 'Point', coordinates: [-93, 42] } } } }
const view: TurnReadiness = { schema_version: 'open_agronomy_agent.turn_readiness.v1', request_id: 'request-a', requires_model: false, status: 'ready', readiness_binding: 'a'.repeat(64), binding: { message: turn.message, mode: turn.mode, session_id: 'session-a', field_context_id: 'field-a' }, calculator: { operation: 'unit_conversion', missing_inputs: [], requirements: {} }, boundary: 'Supplied-input arithmetic only.' }

describe('request-bound server readiness', () => {
  it('accepts a current typed server response and rejects simulated/mismatched responses', () => {
    expect(isBoundTurnReadiness(view, 'request-a', 'session-a', turn)).toBe(true)
    expect(isBoundTurnReadiness({}, 'request-a', 'session-a', turn)).toBe(false)
    expect(isBoundTurnReadiness(view, 'request-b', 'session-a', turn)).toBe(false)
    expect(isBoundTurnReadiness(view, 'request-a', 'session-b', turn)).toBe(false)
    expect(isBoundTurnReadiness(view, 'request-a', 'session-a', { ...turn, message: 'Why are leaves yellow?' })).toBe(false)
    expect(isBoundTurnReadiness(view, 'request-a', 'session-a', { ...turn, mode: 'baseline' })).toBe(false)
  })

  it.each(['checking', 'failed'] as const)('keeps %s preview unknown when the model is missing', status => {
    const key = turnReadinessKey('session-a', turn)
    expect(canAskWithReadiness(false, { key, status }, key)).toBe(false)
    expect(canAskWithReadiness(true, { key, status }, key)).toBe(true)
  })

  it.each([
    { ...turn, message: 'Convert 200 lb/ac to kg/ha' },
    { ...turn, model_id: 'another-model' },
    { ...turn, mode: 'baseline' },
    { ...turn, session_context: { ...turn.session_context, field_context_id: 'field-b' } },
    { ...turn, session_context: { ...turn.session_context, field_record_updated_at: 'revision-b' } },
    { ...turn, session_context: { ...turn.session_context, field_context: { geometry: { type: 'Point', coordinates: [-94, 43] } } } },
  ])('ignores an old response after request input changes', changed => {
    const key = turnReadinessKey('session-a', turn)
    const state: TurnReadinessState = { key, status: 'received', result: view }
    expect(canAskWithReadiness(false, state, key)).toBe(true)
    expect(matchingTurnReadiness(state, turnReadinessKey('session-a', changed))).toBeNull()
    expect(canAskWithReadiness(false, state, turnReadinessKey('session-b', turn))).toBe(false)
  })

  it('allows canonical missing-input clarification without granting ordinary generation', () => {
    const key = turnReadinessKey('session-a', turn)
    expect(canAskWithReadiness(false, { key, status: 'received', result: { ...view, status: 'clarification_required' } }, key)).toBe(true)
    expect(canAskWithReadiness(false, { key, status: 'received', result: { ...view, requires_model: true, status: 'model_required', calculator: null } }, key)).toBe(false)
    expect(canAskWithReadiness(false, { key, status: 'received', result: { ...view, requires_model: null, status: 'unknown' } }, key)).toBe(false)
    expect(turnReadinessKey('session-a', turn, 'refresh-a')).not.toBe(turnReadinessKey('session-a', turn, 'refresh-b'))
  })
})
