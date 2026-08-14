import { useEffect, useState } from 'react'
import { apiGet } from './api'

type CapabilityStatus = {
  implemented?: boolean
  tested?: boolean
  benchmark_exercised?: boolean
}

type CapabilityRecord = {
  capability_id?: string
  status?: CapabilityStatus
}

type CapabilityRegistryResponse = {
  schema_version: string
  surface: string
  capability_count: number
  capabilities: CapabilityRecord[]
  preflight?: {
    status?: string
    issues?: Array<Record<string, unknown>>
  }
}

export type CapabilityReadinessSummary = {
  state: 'loading' | 'ready' | 'review' | 'unavailable'
  label: string
  detail: string
}

const REGISTRY_BOUNDARY =
  'Registry metadata reports declared implementation, test coverage, and parity checks. It does not prove live provider access or agronomic validity.'

const isCapabilityRegistryResponse = (value: unknown): value is CapabilityRegistryResponse => {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<CapabilityRegistryResponse>
  return (
    candidate.schema_version === 'open_agronomy_agent.capability_registry.v1'
    && candidate.surface === 'all'
    && typeof candidate.capability_count === 'number'
    && Number.isInteger(candidate.capability_count)
    && candidate.capability_count >= 0
    && Array.isArray(candidate.capabilities)
    && candidate.capabilities.length === candidate.capability_count
  )
}

export const summarizeCapabilityRegistry = (
  value: unknown,
  loadState: 'loading' | 'loaded' | 'failed' = 'loaded',
): CapabilityReadinessSummary => {
  if (loadState === 'loading') {
    return {
      state: 'loading',
      label: 'Capability registry loading',
      detail: REGISTRY_BOUNDARY,
    }
  }
  if (loadState === 'failed' || !isCapabilityRegistryResponse(value)) {
    return {
      state: 'unavailable',
      label: 'Capability registry unavailable',
      detail: `The canonical capability catalog could not be verified. ${REGISTRY_BOUNDARY}`,
    }
  }

  const implementedCount = value.capabilities.filter((item) => item.status?.implemented === true).length
  const testedCount = value.capabilities.filter((item) => item.status?.tested === true).length
  const benchmarkCount = value.capabilities.filter((item) => item.status?.benchmark_exercised === true).length
  const parityStatus = value.preflight?.status || 'not reported'
  const isReady = value.capability_count > 0
    && implementedCount === value.capability_count
    && parityStatus === 'passed'

  return {
    state: isReady ? 'ready' : 'review',
    label: `Capabilities ${implementedCount}/${value.capability_count} implemented · parity ${parityStatus}`,
    detail: `${testedCount}/${value.capability_count} declared test-covered; ${benchmarkCount}/${value.capability_count} benchmark-exercised. ${REGISTRY_BOUNDARY}`,
  }
}

export function CapabilityReadinessStatus() {
  const [catalog, setCatalog] = useState<unknown>(null)
  const [loadState, setLoadState] = useState<'loading' | 'loaded' | 'failed'>('loading')

  useEffect(() => {
    let active = true
    apiGet<unknown>('/api/tools/capabilities')
      .then((payload) => {
        if (!active) return
        setCatalog(payload)
        setLoadState('loaded')
      })
      .catch(() => {
        if (active) setLoadState('failed')
      })
    return () => {
      active = false
    }
  }, [])

  const summary = summarizeCapabilityRegistry(catalog, loadState)
  return (
    <span
      aria-label="Capability registry readiness"
      data-capability-state={summary.state}
      data-testid="capability-registry-status"
      role="status"
      title={summary.detail}
    >
      {summary.label}
    </span>
  )
}
