import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ConversationRuntimeStatus } from './ConversationRuntimeStatus'
import type { Turn } from './types'

const turnWith = (context_budget: unknown, generation_stats: unknown): Turn => ({
  turn_id: 'retained', user_message: 'Question', answer: 'Answer', answer_status: 'draft',
  trace: { metadata: { context_budget, generation_stats } },
})

describe('last request runtime status', () => {
  it('labels the configured budget and character estimate without claiming native model capacity', () => {
    render(<ConversationRuntimeStatus turn={turnWith({
      schema_version: 'open_agronomy_agent.context_budget.v1',
      status: 'estimated_within_budget',
      input_tokens: 640, token_count_basis: 'estimated_characters',
      context_limit_tokens: 4096, limit_basis: 'configured', reserved_output_tokens: 400,
      remaining_tokens: 3056, history_turns_available: 4, history_turns_included: 2,
      history_turns_omitted: 2,
    }, { generation_tps: 31.25, prompt_tps: 80, prompt_cache_enabled: true,
      prompt_cache_hit: true, cached_prompt_tokens: 320, uncached_prompt_tokens: 320 })} />)
    expect(screen.getByLabelText('Last request runtime status')).toHaveTextContent('Context 640 / 4,096 · estimated')
    expect(screen.getByLabelText('Last request runtime status')).toHaveTextContent('Decode 31.3 tokens/s')
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))
    expect(screen.getByText(/configured operating budget/)).toBeInTheDocument()
    expect(screen.getByText('Budget status: estimated within budget')).toBeInTheDocument()
    expect(screen.getByText(/2 included, 2 omitted, 4 available/)).toBeInTheDocument()
    expect(screen.getByText(/prompt processing: 80 tokens\/s/)).toBeInTheDocument()
    expect(screen.getByText(/Prompt KV cache: hit; 320 cached and 320 uncached/)).toBeInTheDocument()
    expect(screen.getByText(/not a live rate/)).toBeInTheDocument()
  })

  it('keeps absent and invalid measurements unavailable, including zero throughput', () => {
    render(<ConversationRuntimeStatus turn={turnWith({
      schema_version: 'open_agronomy_agent.context_budget.v1',
      input_tokens: Number.NaN, context_limit_tokens: 8192, limit_basis: 'model',
      token_count_basis: 'unavailable', history_turns_included: 0,
    }, { generation_tps: 0, prompt_tps: Number.POSITIVE_INFINITY })} />)
    expect(screen.getByLabelText('Last request runtime status')).toHaveTextContent('Context unavailable')
    expect(screen.getByLabelText('Last request runtime status')).toHaveTextContent('Decode unavailable')
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))
    expect(screen.getByText(/reported model limit/)).toBeInTheDocument()
    expect(screen.getByText(/0 included, unavailable omitted/)).toBeInTheDocument()
    expect(screen.getByText(/Model decode: unavailable; prompt processing: unavailable/)).toBeInTheDocument()
    expect(screen.getByText('Prompt KV cache: unavailable')).toBeInTheDocument()
  })
})
