export type BasemapStyle = 'satellite' | 'streets' | 'simple'
export type MapLayerChoice = {
  id: string; label: string; system: string; source_url: string; color: string
  source_mode: string; available_in_current_mode: boolean; installation_status: string; boundary?: string
}
export type MapPreferences = { style: BasemapStyle; layers: string[]; opacity: number }
export const MAP_PREFERENCES_KEY = 'open-agronomy-agent.map-presentation.v1'
export const DEFAULT_MAP_LAYERS = ['canada_ecozones', 'nrcs_mlra', 'epa_l3_us']
export const BASEMAPS = {
  satellite: { label: 'Satellite', description: 'See field edges and land cover.',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community', maxZoom: 19 },
  streets: { label: 'Streets', description: 'Find roads, places, and access.',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 19 },
  simple: { label: 'Simple', description: 'Focus on the boundary and mapped layers.', url: '', attribution: '', maxZoom: 19 },
} as const

export function readMapPreferences(): MapPreferences {
  const defaults: MapPreferences = { style: 'satellite', layers: DEFAULT_MAP_LAYERS, opacity: 35 }
  try {
    const value = JSON.parse(localStorage.getItem(MAP_PREFERENCES_KEY) || 'null')
    if (!value || typeof value !== 'object') return defaults
    return {
      style: ['satellite', 'streets', 'simple'].includes(value.style) ? value.style : defaults.style,
      layers: Array.isArray(value.layers) ? [...new Set(value.layers.filter((id: unknown) => typeof id === 'string' && /^[a-z0-9_]+$/.test(id)))].slice(0, 4) as string[] : defaults.layers,
      opacity: typeof value.opacity === 'number' && Number.isFinite(value.opacity) ? Math.max(10, Math.min(70, value.opacity)) : defaults.opacity,
    }
  } catch { return defaults }
}
export function saveMapPreferences(value: MapPreferences) {
  try { localStorage.setItem(MAP_PREFERENCES_KEY, JSON.stringify(value)) } catch { /* View controls still work without browser storage. */ }
}
export function mapLayerLabel(layer: Pick<MapLayerChoice, 'id' | 'label'>): string {
  const names: Record<string, string> = {
    canada_ecozones: 'Canada ecozones', nrcs_mlra: 'US land resource areas', epa_l3_us: 'US ecoregions',
    ab_detailed_soil: 'Alberta soils', sk_detailed_soil: 'Saskatchewan soils', mb_detailed_soil: 'Manitoba soils',
    sk_thematic_soil: 'Saskatchewan soil themes', bc_agriculture_capability: 'BC land capability',
    pei_detailed_soil: 'PEI soils', ns_pictou_detailed_soil: 'Pictou County soils',
    ca_statcan_2021_provinces_territories: 'Province boundaries', ca_statcan_2021_census_agricultural_regions: 'Agricultural regions',
    ca_aafc_terrestrial_ecoregions_v2_2: 'Canada ecoregions',
  }
  return names[layer.id] || layer.label
}
export const safeSourceUrl = (value?: string) => value && /^https?:\/\//i.test(value) ? value : undefined
