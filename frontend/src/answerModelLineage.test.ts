import { describe, expect, it } from 'vitest'
import { answerModelLineageView } from './OpenAgronomyApp'
import type { Turn } from './types'

const turn: Turn = {
  turn_id: 'identity-only', user_message: 'Question', answer: 'Answer', answer_status: 'draft',
  system_state: {
    mode: 'agronomic_rag', model_id: 'configured-model', rag_config: null, prompt_version: 'fixture',
    model_identity: { status: 'verified_runtime_receipt', configured_model_id: 'configured-model', response_model_id: null },
  },
}

describe('answerModelLineageView', () => {
  it('does not attribute an available configured model to an answer', () => {
    expect(answerModelLineageView(turn)).toEqual({ label: 'Response model identity', status: 'Not recorded · configured model does not establish answer generation' })
  })

  it('does not attribute a bound identity without execution/final origin receipts', () => {
    const identityOnly = structuredClone(turn)
    identityOnly.system_state!.model_identity!.response_model_id = 'response-model'
    expect(answerModelLineageView(identityOnly)).toEqual({ label: 'Response model identity', status: 'Recorded identity · final origin not recorded' })
  })
  it('keeps missing identity unknown instead of claiming a model was unused', () => {
    expect(answerModelLineageView(undefined)).toEqual({ label: 'Response model identity', status: 'Not recorded' })
  })
})
