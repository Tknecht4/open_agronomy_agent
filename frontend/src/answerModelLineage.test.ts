import { describe, expect, it } from 'vitest'
import { answerModelLineageView } from './OpenAgronomyApp'

describe('answerModelLineageView', () => {
  it('distinguishes an available runtime model from a model-bound answer', () => {
    expect(answerModelLineageView({
      status: 'verified_runtime_receipt',
      configured_model_id: 'mlx-community/gemma-4-e2b-it-4bit',
      response_model_id: null,
    })).toEqual({
      label: 'Runtime model availability',
      status: 'verified runtime receipt · this answer is not model-bound',
    })
  })

  it('labels an answer as model-generated only when response identity is bound', () => {
    expect(answerModelLineageView({
      status: 'verified_runtime_receipt',
      configured_model_id: 'mlx-community/gemma-4-e2b-it-4bit',
      response_model_id: 'default_model',
    })).toEqual({
      label: 'Answer generation model',
      status: 'Response identity bound',
    })
  })
})
