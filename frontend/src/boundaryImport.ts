export type BoundaryImportSnapshot = {
  import_receipt: { schema_version: string; source_sha256: string; source_bytes: number }
  coordinate_reference: Record<string, unknown>
  selected_feature: {
    id: string
    source_layer: string
    source_feature_index: number
    source_feature_id?: string | number | null
    properties: Record<string, unknown>
  }
  binding_status?: string
  validity?: string
}

export const boundaryImportFromUpload = (
  parsed: { import_receipt?: BoundaryImportSnapshot['import_receipt']; coordinate_reference?: Record<string, unknown> } | null,
  selected: { id: string; properties?: Record<string, unknown> } | null,
): BoundaryImportSnapshot | undefined => {
  if (!parsed?.import_receipt || !parsed.coordinate_reference || !selected?.properties) return undefined
  const sourceLayer = selected.properties.upload_source_layer
  const sourceIndex = selected.properties.upload_source_feature_index
  if (typeof sourceLayer !== 'string' || typeof sourceIndex !== 'number') return undefined
  const sourceId = selected.properties.upload_source_feature_id
  return {
    import_receipt: parsed.import_receipt,
    coordinate_reference: parsed.coordinate_reference,
    selected_feature: {
      id: selected.id,
      source_layer: sourceLayer,
      source_feature_index: sourceIndex,
      source_feature_id: typeof sourceId === 'string' || typeof sourceId === 'number' ? sourceId : null,
      properties: selected.properties,
    },
  }
}

