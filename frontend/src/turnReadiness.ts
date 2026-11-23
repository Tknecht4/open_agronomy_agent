export type ImageryComparisonSelection = { first_job_id: string; second_job_id: string; geometry_revision_id: string }

export type TurnReadinessPayload = {
  message: string
  mode: string
  model_id?: string
  imagery_job_id?: string
  imagery_comparison?: ImageryComparisonSelection
  session_context?: { field_context_id?: string; [key: string]: unknown }
  [key: string]: unknown
}

export type TurnReadiness = {
  schema_version: 'open_agronomy_agent.turn_readiness.v1'
  request_id: string
  requires_model: boolean | null
  status: 'ready' | 'clarification_required' | 'model_required' | 'unknown'
  reason?: string
  readiness_binding: string
  binding: { message: string; mode: string; session_id: string | null; field_context_id?: string | null; imagery_job_id?: string; imagery_comparison?: { job_ids: string[]; geometry_revision_id: string } }
  calculator: { operation: string; missing_inputs: string[]; clarification?: string | null; requirements: Record<string, unknown> } | null
  boundary: string
}

export type TurnReadinessState = {
  key: string
  status: 'checking' | 'failed' | 'received'
  result?: TurnReadiness
}

export function turnReadinessKey(sessionId: string | undefined, turn: TurnReadinessPayload, contextRevision?: unknown): string {
  return JSON.stringify({ session_id: sessionId || null, turn, context_revision: contextRevision })
}

export function isBoundTurnReadiness(value: unknown, requestId: string, sessionId: string | undefined, turn: TurnReadinessPayload): value is TurnReadiness {
  if (!value || typeof value !== 'object') return false
  const result = value as Partial<TurnReadiness>
  const comparison = turn.imagery_comparison
  const boundComparison = result.binding?.imagery_comparison
  const comparisonMatches = comparison
    ? boundComparison?.geometry_revision_id === comparison.geometry_revision_id
      && Array.isArray(boundComparison.job_ids)
      && JSON.stringify([...boundComparison.job_ids].sort()) === JSON.stringify([comparison.first_job_id, comparison.second_job_id].map(value => value.toLowerCase()).sort())
    : !boundComparison
  return comparisonMatches && result.schema_version === 'open_agronomy_agent.turn_readiness.v1'
    && result.request_id === requestId && (typeof result.requires_model === 'boolean' || result.requires_model === null)
    && typeof result.readiness_binding === 'string' && /^[0-9a-f]{64}$/.test(result.readiness_binding)
    && result.binding?.message === turn.message && result.binding?.mode === turn.mode
    && result.binding?.session_id === (sessionId || null)
    && (result.binding?.field_context_id || '') === (turn.session_context?.field_context_id || '')
    && result.binding?.imagery_job_id === turn.imagery_job_id
    && (result.requires_model === null ? result.status === 'unknown' : result.requires_model ? result.status === 'model_required'
      : comparison ? result.reason === 'saved_imagery_comparison' && result.status === 'ready'
        : Boolean(result.calculator && ['ready', 'clarification_required'].includes(result.status || '')))
}

export function matchingTurnReadiness(state: TurnReadinessState | null, key: string): TurnReadiness | null {
  return state?.key === key && state.status === 'received' ? state.result || null : null
}

export function canAskWithReadiness(modelReady: boolean, state: TurnReadinessState | null, key: string): boolean {
  return modelReady || matchingTurnReadiness(state, key)?.requires_model === false
}
