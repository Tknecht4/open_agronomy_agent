/** Presentation names only. Stored measurements, source IDs and receipts stay unchanged. */
export const soilMeasurements = [
  ['soil_ph', 'Soil pH'],
  ['nitrate_n', 'Nitrate nitrogen'],
  ['phosphorus', 'Phosphorus'],
  ['potassium', 'Potassium'],
  ['organic_matter', 'Organic matter'],
  ['salinity_ec', 'Salinity (electrical conductivity)'],
] as const

export function readableLabel(value: string): string {
  const words = value.replace(/[_-]+/g, ' ').trim()
  return words ? words[0].toUpperCase() + words.slice(1) : 'Unknown'
}

export function measurementLabel(value: string): string {
  return soilMeasurements.find(([id]) => id === value)?.[1] || readableLabel(value)
}

export function imagerySourceLabel(id: string, fallback?: string): string {
  const labels: Record<string, string> = {
    'sentinel2-c1-earth-search': 'Sentinel-2',
    'sentinel-2-c1-l2a': 'Sentinel-2',
    'hls-s30-planetary-computer': 'HLS · Sentinel-2',
    'hls-l30-planetary-computer': 'HLS · Landsat',
    'hls2-s30': 'HLS · Sentinel-2',
    'hls2-l30': 'HLS · Landsat',
  }
  return labels[id] || fallback || readableLabel(id)
}

export function displayDate(value: string | null | undefined, includeTime = false): string {
  if (!value) return 'Date unknown'
  // Date-only observations must not move to the previous day in western time zones.
  const parsed = new Date(/^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T12:00:00` : value)
  if (!Number.isFinite(parsed.getTime())) return 'Date unknown'
  return parsed.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    ...(includeTime ? { hour: 'numeric' as const, minute: '2-digit' as const } : {}),
  })
}
