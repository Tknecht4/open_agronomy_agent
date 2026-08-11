export type RuntimeAccess = 'checking' | 'available' | 'unavailable'
export type RuntimeNetworkMode = 'online' | 'offline' | 'unknown'

export type FieldAnswerCapability = {
  canGenerateAnswer: boolean
  state: 'checking' | 'runtime_online' | 'runtime_offline' | 'notes_only'
  badge: string
  detail: string
}

export function fieldAnswerCapability(
  runtimeAccess: RuntimeAccess,
  networkMode: RuntimeNetworkMode,
): FieldAnswerCapability {
  if (runtimeAccess === 'unavailable') {
    return {
      canGenerateAnswer: false,
      state: 'notes_only',
      badge: 'Runtime unavailable · notes only',
      detail: 'This device cannot generate an answer. Your question draft and field notes stay on this device.',
    }
  }
  if (runtimeAccess === 'checking') {
    return {
      canGenerateAnswer: false,
      state: 'checking',
      badge: 'Checking local runtime',
      detail: 'Checking whether this device can reach the local agronomy service.',
    }
  }
  if (networkMode === 'offline') {
    return {
      canGenerateAnswer: true,
      state: 'runtime_offline',
      badge: 'Local runtime · internet blocked',
      detail: 'Local answers are available. Public internet and live sources are blocked.',
    }
  }
  if (networkMode === 'online') {
    return {
      canGenerateAnswer: true,
      state: 'runtime_online',
      badge: 'Local runtime · live sources enabled',
      detail: 'Local answers are available. Live sources may be used when the answer records them.',
    }
  }
  return {
    canGenerateAnswer: true,
    state: 'runtime_offline',
    badge: 'Local runtime · source mode unknown',
    detail: 'The local service is reachable, but public-source availability has not been declared.',
  }
}

export function isRuntimeTransportFailure(error: unknown): boolean {
  const message = String(error instanceof Error ? error.message : error)
  return /failed to fetch|network ?error|network request failed|load failed|fetch failed/i.test(message)
}
