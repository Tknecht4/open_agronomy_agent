import { useState } from 'react'
import type { Turn } from './types'

type Receipt = Record<string, unknown>

const record = (value: unknown): Receipt => value && typeof value === 'object' && !Array.isArray(value)
  ? value as Receipt : {}
const count = (value: unknown): number | null =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null
const positiveCount = (value: unknown): number | null => {
  const result = count(value)
  return result !== null && result > 0 ? result : null
}
const rate = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
const quantity = (value: number | null): string => value === null ? 'unavailable' : value.toLocaleString()

export function ConversationRuntimeStatus({ turn }: { turn: Turn | null }) {
  const [pinned, setPinned] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [dismissed, setDismissed] = useState(false)
  const expanded = pinned || (!dismissed && (hovered || focused))
  const metadata = record(turn?.trace?.metadata)
  const budget = record(metadata.context_budget)
  const stats = record(metadata.generation_stats)
  const hasBudget = budget.schema_version === 'open_agronomy_agent.context_budget.v1'
  const budgetStatus = hasBudget && typeof budget.status === 'string'
    ? budget.status.replace(/_/g, ' ') : 'unavailable'
  const input = hasBudget ? count(budget.input_tokens) : null
  const limit = hasBudget ? positiveCount(budget.context_limit_tokens) : null
  const reserve = hasBudget ? count(budget.reserved_output_tokens) : null
  const remaining = hasBudget ? count(budget.remaining_tokens) : null
  const included = hasBudget ? count(budget.history_turns_included) : null
  const omitted = hasBudget ? count(budget.history_turns_omitted) : null
  const available = hasBudget ? count(budget.history_turns_available) : null
  const basis = budget.token_count_basis === 'tokenizer' || budget.token_count_basis === 'provider'
    ? 'exact' : budget.token_count_basis === 'estimated_characters' ? 'estimated' : 'unknown'
  const limitLabel = budget.limit_basis === 'configured' ? 'configured operating budget'
    : budget.limit_basis === 'model' ? 'reported model limit' : 'unknown limit'
  const decode = rate(stats.generation_tps)
  const prompt = rate(stats.prompt_tps)
  const cache = stats.prompt_cache_status === 'reused_saved_prefix' ? 'reused saved prefix'
    : stats.prompt_cache_status === 'prepared_this_request' ? 'prepared this request'
      : stats.prompt_cache_status === 'miss' ? 'miss'
        : stats.prompt_cache_status === 'disabled' ? 'disabled'
          : 'status unavailable (not recorded)'
  const cachedTokens = count(stats.cached_prompt_tokens)
  const uncachedTokens = count(stats.uncached_prompt_tokens)
  const formatRate = (value: number) => `${value.toLocaleString(undefined, { maximumFractionDigits: 1 })} tokens/s`

  return (
    <div className="conversation-runtime" aria-label="Last request runtime status">
      <div className="conversation-runtime-summary">
        <span>Last request</span>
        <span>Context {input === null ? 'unavailable' : `${quantity(input)}${limit === null ? '' : ` / ${quantity(limit)}`} · ${basis}`}</span>
        <span>Decode {decode === null ? 'unavailable' : formatRate(decode)}</span>
      </div>
      <div
        className={`conversation-runtime-details${expanded ? ' expanded' : ''}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => {
          setHovered(false)
          if (!focused) setDismissed(false)
        }}
        onFocus={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) setFocused(true)
        }}
        onBlur={(event) => {
          if (!event.currentTarget.contains(event.relatedTarget)) {
            setFocused(false)
            if (!hovered) setDismissed(false)
          }
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape' && expanded) {
            event.preventDefault()
            setPinned(false)
            setDismissed(true)
          }
        }}
      >
        <button type="button" aria-expanded={expanded} aria-controls="last-request-details" onClick={() => {
          setPinned(!pinned)
          setDismissed(pinned)
        }}>Details</button>
        <div id="last-request-details" className="conversation-runtime-popover">
          <strong>Last retained answer</strong>
          <p>Input: {quantity(input)} tokens ({basis}{basis === 'estimated' ? ' character estimate' : ''})</p>
          <p>Limit: {quantity(limit)} tokens ({limitLabel}); output reserved: {quantity(reserve)}; remaining: {quantity(remaining)}</p>
          <p>Budget status: {budgetStatus}</p>
          <p>History turns: {quantity(included)} included, {quantity(omitted)} omitted, {quantity(available)} available</p>
          <p>Model decode: {decode === null ? 'unavailable' : formatRate(decode)}; prompt processing: {prompt === null ? 'unavailable' : formatRate(prompt)}</p>
          <p>Prompt KV cache: {cache}{cache === 'reused saved prefix' || cache === 'prepared this request' || cache === 'miss'
            ? `; ${quantity(cachedTokens)} cached and ${quantity(uncachedTokens)} uncached prompt tokens` : ''}</p>
          <small>These are saved request measurements, not a live rate or the next draft’s usage.</small>
        </div>
      </div>
    </div>
  )
}
