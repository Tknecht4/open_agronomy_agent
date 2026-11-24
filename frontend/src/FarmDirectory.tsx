import { ChevronRight, Sprout } from 'lucide-react'
import { FarmFieldList } from './FarmFieldList'
import { fieldArea, type Farm, type FarmField, type FarmOverview } from './farmTypes'

export function FarmDirectory({ farms, overview, fields, unit, expandedFarm, selected, filtering, onToggle, onSelect, onManage }: {
  farms: Farm[]
  overview: FarmOverview
  fields: FarmField[]
  unit: 'ac' | 'ha'
  expandedFarm: string
  selected: string
  filtering: boolean
  onToggle: (id: string) => void
  onSelect: (id: string) => void
  onManage: (farm: Farm) => void
}) {
  const groups = new Map<string, FarmField[]>()
  for (const field of fields) {
    const id = field.farm_id || 'unassigned'
    const members = groups.get(id) || []
    members.push(field)
    groups.set(id, members)
  }
  const unassignedCount = overview.fields.filter(field => !field.farm_id).length
  const entries = farms.map(farm => ({ id: farm.id, name: farm.name, farm }))
  const showUnassigned = unassignedCount > 0 || expandedFarm === 'unassigned'
  const directory = showUnassigned ? [...entries, { id: 'unassigned', name: 'Unassigned fields', farm: null }] : entries

  return <>
    {filtering && !fields.length ? <p className="farm-list-empty">No matching fields</p> : null}
    <ul className="farm-directory" aria-label="Farms">
      {directory.map(({ id, name, farm }) => {
        const members = groups.get(id) || []
        const expanded = expandedFarm === id
        if (filtering && !members.length && !expanded) return null
        const count = members.length
        const coverage = overview.farm_coverage?.[id]
        const groupId = `farm-fields-${id}`
        return <li key={id}>
          <button type="button" className="farm-directory-row" aria-expanded={expanded} aria-controls={groupId} onClick={() => onToggle(id)}>
            <span className="farm-icon"><Sprout size={18} aria-hidden="true" /></span>
            <span className="farm-directory-name"><strong>{name}</strong>
              <small>{count} {count === 1 ? 'field' : 'fields'}{filtering ? ' matching' : ''}{farm?.archived ? ' · Archived' : ''}{coverage?.boundary_area_m2 != null ? ` · ${fieldArea(coverage.boundary_area_m2, unit)}` : ''}</small>
            </span>
            <ChevronRight className="farm-disclosure" size={17} aria-hidden="true" />
          </button>
          <div id={groupId} className="farm-directory-fields" hidden={!expanded}>
            {expanded ? <>
              <FarmFieldList fields={members} unit={unit} selected={selected} onSelect={onSelect} />
              {!count ? <p className="farm-list-empty">{filtering ? 'No matching fields in this farm' : 'No fields yet'}</p> : null}
              {farm || coverage ? <div className="farm-group-footer">
                {coverage?.unknown_area_count ? <small>{coverage.unknown_area_count} with unknown area</small> : null}
                {(coverage?.overlapping_area_m2 || 0) > 1 ? <small>{fieldArea(coverage?.overlapping_area_m2, unit)} of overlapping area excluded</small> : null}
                {farm ? <button type="button" onClick={() => onManage(farm)}>Manage farm</button> : null}
              </div> : null}
            </> : null}
          </div>
        </li>
      })}
    </ul>
  </>
}
