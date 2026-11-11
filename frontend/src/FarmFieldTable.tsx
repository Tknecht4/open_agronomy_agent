import { MapPin } from 'lucide-react'
import { displayDate } from './fieldLabels'
import { fieldArea, type Farm, type FarmField } from './farmTypes'

export function FarmFieldTable({ fields, farms, season, unit, selected, showFarm, onOpen, onSelect }: {
  fields: FarmField[]
  farms: Farm[]
  season: number
  unit: 'ac' | 'ha'
  selected: string
  showFarm: boolean
  onOpen: (id: string) => void
  onSelect: (id: string) => void
}) {
  return <div className="farm-table-scroll">
    <table className="farm-field-table" role="table">
      <caption className="sr-only">Fields for {season}</caption>
      <thead role="rowgroup"><tr role="row"><th scope="col">Field</th><th scope="col">Crop</th><th scope="col">Boundary area</th><th scope="col">Sources</th><th scope="col">Last record</th></tr></thead>
      <tbody role="rowgroup">{fields.map(field => <tr key={field.id} role="row" aria-selected={selected === field.id}>
        <td role="cell" className="farm-field-name">
          <div><button type="button" className="field-open" onClick={() => onOpen(field.id)}>{field.name}</button>{showFarm ? <small>{farms.find(farm => farm.id === field.farm_id)?.name || 'Unassigned'}</small> : null}</div>
          <button type="button" className="field-on-map" aria-label={`Show ${field.name} on map`} title={field.geometry.kind === 'none' ? 'Location unknown' : 'Show on map'} disabled={field.geometry.kind === 'none'} onClick={() => onSelect(field.id)}><MapPin size={16} aria-hidden="true" /></button>
        </td>
        <td role="cell" data-label="Crop">{field.crop || <span className="farm-unknown">Not confirmed</span>}{field.legacy_undated_crop && !field.crop ? <small>Undated: {field.legacy_undated_crop}</small> : null}</td>
        <td role="cell" data-label="Boundary area">{fieldArea(field.boundary_area_m2, unit)}{field.geometry_status === 'point' ? <small>Point only</small> : null}</td>
        <td role="cell" data-label="Sources">{field.context_review_count ? <span className="farm-status caution">{field.context_review_count} to review</span> : <span className="farm-unknown">{field.context_checked_count ? `${field.context_checked_count}/4 checked` : 'Not checked'}</span>}</td>
        <td role="cell" data-label="Last record">{field.last_record_at ? <time dateTime={field.last_record_at}>{displayDate(field.last_record_at)}</time> : <span className="farm-unknown">No records</span>}</td>
      </tr>)}</tbody>
    </table>
    {!fields.length ? <div className="farm-table-empty">No matching fields</div> : null}
  </div>
}
