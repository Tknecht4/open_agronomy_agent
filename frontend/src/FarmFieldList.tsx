import { MapPin, MapPinOff } from 'lucide-react'
import { displayDate } from './fieldLabels'
import { fieldArea, type FarmField } from './farmTypes'

export function FarmFieldList({ fields, unit, selected, onSelect }: {
  fields: FarmField[]
  unit: 'ac' | 'ha'
  selected: string
  onSelect: (id: string) => void
}) {
  return <ul className="farm-field-list" aria-label="Fields">
    {fields.map(field => {
      const location = field.geometry_status === 'point' ? 'Point location'
        : field.geometry.kind === 'none' ? 'Location unknown' : fieldArea(field.boundary_area_m2, unit)
      const Icon = field.geometry.kind === 'none' ? MapPinOff : MapPin
      return <li key={field.id}>
        <button type="button" className="farm-field-row" aria-pressed={selected === field.id} onClick={() => onSelect(field.id)}>
          <Icon size={16} aria-hidden="true" />
          <span className="farm-field-summary">
            <strong>{field.name}</strong>
            <small>{field.crop || 'Crop not confirmed'} · {location}</small>
            {!field.crop && field.legacy_undated_crop ? <small>Undated crop: {field.legacy_undated_crop}</small> : null}
          </span>
          <span className="farm-field-status">
            {field.context_review_count ? <span className="farm-status caution">{field.context_review_count} {field.context_review_count === 1 ? 'source' : 'sources'} to review</span>
              : <small>{field.context_checked_count ? `${field.context_checked_count}/4 sources checked` : 'Sources not checked'}</small>}
            <small>{field.last_record_at ? <time dateTime={field.last_record_at}>{displayDate(field.last_record_at)}</time> : 'No records'}</small>
          </span>
        </button>
      </li>
    })}
  </ul>
}
