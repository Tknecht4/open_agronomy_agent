export const PHASE6_LOW_BANDWIDTH_STORAGE_KEY = 'agronomy-agent.phase6.low-bandwidth.v1'

export type Phase6LowBandwidthPreference = 'auto' | 'on' | 'off'

export type Phase6NetworkInformation = {
  saveData?: boolean
  effectiveType?: string
  downlink?: number
  rtt?: number
}

export type Phase6LowBandwidthDetection = {
  detected: boolean
  reason: 'save_data' | 'slow_effective_type' | 'low_downlink' | 'high_rtt' | 'not_detected' | 'unsupported'
  effectiveType: string | null
  downlinkMbps: number | null
  rttMs: number | null
  saveData: boolean
}

type NavigatorWithConnection = {
  connection?: Phase6NetworkInformation
}

type BrowserStorage = Pick<Storage, 'getItem' | 'setItem'>

export function detectPhase6LowBandwidth(
  navigatorLike: NavigatorWithConnection | undefined = typeof navigator === 'undefined' ? undefined : (navigator as NavigatorWithConnection),
): Phase6LowBandwidthDetection {
  const connection = navigatorLike?.connection
  if (!connection) {
    return {
      detected: false,
      reason: 'unsupported',
      effectiveType: null,
      downlinkMbps: null,
      rttMs: null,
      saveData: false,
    }
  }

  const effectiveType = String(connection.effectiveType || '').toLowerCase() || null
  const downlinkMbps = Number.isFinite(connection.downlink) ? Number(connection.downlink) : null
  const rttMs = Number.isFinite(connection.rtt) ? Number(connection.rtt) : null
  const saveData = Boolean(connection.saveData)

  if (saveData) {
    return { detected: true, reason: 'save_data', effectiveType, downlinkMbps, rttMs, saveData }
  }
  if (effectiveType === 'slow-2g' || effectiveType === '2g') {
    return { detected: true, reason: 'slow_effective_type', effectiveType, downlinkMbps, rttMs, saveData }
  }
  if (downlinkMbps !== null && downlinkMbps <= 1) {
    return { detected: true, reason: 'low_downlink', effectiveType, downlinkMbps, rttMs, saveData }
  }
  if (rttMs !== null && rttMs >= 800) {
    return { detected: true, reason: 'high_rtt', effectiveType, downlinkMbps, rttMs, saveData }
  }
  return { detected: false, reason: 'not_detected', effectiveType, downlinkMbps, rttMs, saveData }
}

export function loadPhase6LowBandwidthPreference(storage: BrowserStorage | undefined = safeLocalStorage()): Phase6LowBandwidthPreference {
  try {
    const value = storage?.getItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY)
    return value === 'on' || value === 'off' || value === 'auto' ? value : 'auto'
  } catch {
    return 'auto'
  }
}

export function savePhase6LowBandwidthPreference(
  preference: Phase6LowBandwidthPreference,
  storage: BrowserStorage | undefined = safeLocalStorage(),
): void {
  storage?.setItem(PHASE6_LOW_BANDWIDTH_STORAGE_KEY, preference)
}

export function isPhase6LowBandwidthActive(
  preference: Phase6LowBandwidthPreference,
  detection: Phase6LowBandwidthDetection,
): boolean {
  if (preference === 'on') {
    return true
  }
  if (preference === 'off') {
    return false
  }
  return detection.detected
}

export function phase6LowBandwidthSummary(
  preference: Phase6LowBandwidthPreference,
  detection: Phase6LowBandwidthDetection,
): string {
  const active = isPhase6LowBandwidthActive(preference, detection)
  if (preference === 'on') {
    return 'Low-bandwidth mode on: private upload attachments are skipped in chat and list loads use smaller batches.'
  }
  if (preference === 'off') {
    return 'Low-bandwidth mode off: normal hosted cockpit data loading is enabled.'
  }
  if (active) {
    return `Low-bandwidth mode auto: ${detection.reason}; private upload attachments are skipped in chat and list loads use smaller batches.`
  }
  return 'Low-bandwidth mode auto: normal connection detected.'
}

function safeLocalStorage(): BrowserStorage | undefined {
  try {
    return typeof localStorage === 'undefined' ? undefined : localStorage
  } catch {
    return undefined
  }
}
