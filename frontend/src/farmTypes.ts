import type { FieldGeometry } from './fieldGeometry'
export type SeasonCrop = { crop: string; cultivar: string | null }
export type CropSystem = 'unknown' | 'single' | 'intercrop' | 'sequence' | 'separate_areas'
export type Farm = { id: string; workspace_id: string; name: string; revision: number; archived: number }
export type FarmField = {
  id: string; name: string; farm_id: string | null; assignment_revision: number
  crop_system?: CropSystem; season: number | null; crop: string | null; crop_status: string; season_revision: number
  legacy_undated_crop: string | null; geometry: FieldGeometry; geometry_revision_id: string
  geometry_sha256: string; geometry_status: 'unknown' | 'point' | 'boundary'
  boundary_area_m2: number | null; boundary_perimeter_m: number | null
  context_checked_count?: number; context_review_count?: number; context_status?: Record<string, SourceState>
  record_count: number; last_record_at: string | null; updated_at: string; country: string | null
}
export type FarmOverview = {
  farm_coverage?: Record<string, { boundary_area_m2: number | null; unknown_area_count: number; overlapping_area_m2: number | null }>
  workspace_id: string; farm_id: string | null; season: number | null; fields: FarmField[]
  coverage: { field_count: number; boundary_count: number; unknown_area_count: number; boundary_area_m2: number | null; overlapping_area_m2: number | null }
  record_count: number; last_record_at: string | null
}
export type SourceState = { freshness?: string; refresh_status?: string; last_success?: SourceState; availability: string; fetched_at?: string; observed_at?: string; message?: string; values?: unknown }
export type FieldSummary = FarmField & {
  latest_image?: { job_id: string; acquired_at: string | null; provider_id: string; scene_id: string; current_geometry: boolean; completed_at: string } | null
  location_confirmation?: unknown
  seasons: Array<{ crops?: SeasonCrop[]; crop_system?: CropSystem; season: number; crop: string | null; cultivar: string | null; planted_at: string | null; harvested_at: string | null; revision: number }>
  geometry_revisions: Array<{ id: string; geometry_sha256: string; supersedes_id: string | null; created_at: string }>
  public_context: { regional: unknown; lineage: unknown; role: string; freshness: string }
  source_status: Record<string, SourceState>; boundary_import: unknown; latest_context_job?: { id: string; status: string } | null
}
export function fieldArea(m2: number | null | undefined, unit: 'ac' | 'ha' = 'ac'): string {
  return m2 == null ? 'Unknown area' : `${(m2 / (unit === 'ac' ? 4046.8564224 : 10000)).toLocaleString(undefined, { maximumFractionDigits: 1 })} ${unit}`
}
export function readableError(cause: unknown): string {
  const text = cause instanceof Error ? cause.message : String(cause)
  try { const payload = JSON.parse(text.replace(/^\d+:\s*/, '')); if (typeof payload.detail === 'string') return payload.detail } catch { /* ordinary error */ }
  return text
}
