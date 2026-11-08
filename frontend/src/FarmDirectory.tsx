import { ArrowUpRight, Sprout } from 'lucide-react'
import { fieldArea, type Farm, type FarmOverview } from './farmTypes'

export function FarmDirectory({ farms, overview, season, unit, onOpen }: {
  farms: Farm[]
  overview: FarmOverview
  season: number
  unit: 'ac' | 'ha'
  onOpen: (id: string) => void
}) {
  const unassigned = overview.fields.filter(field => !field.farm_id)
  return <div className="farm-directory">
    <div className="farm-directory-columns" aria-hidden="true">
      <span>Farm</span><span>Fields</span><span>Boundary area</span><span>Last record</span><span />
    </div>
    <ul aria-label="Farms">
      {farms.filter(farm => !farm.archived).map(farm => {
        const members = overview.fields.filter(field => field.farm_id === farm.id)
        const coverage = overview.farm_coverage?.[farm.id]
        const latest = members.map(field => field.last_record_at).filter((date): date is string => Boolean(date)).sort().pop()
        const review = members.reduce((count, field) => count + (field.context_review_count || 0), 0)
        return <li key={farm.id}>
          <button type="button" className="farm-directory-row" onClick={() => onOpen(farm.id)}>
            <span className="farm-directory-name"><span className="farm-icon"><Sprout size={20} aria-hidden="true" /></span><span><strong>{farm.name}</strong>{review > 0 ? <span className="farm-status caution">{review} source checks to review</span> : null}</span></span>
            <span className="farm-directory-count">{members.length}<span className="mobile-only"> {members.length === 1 ? 'field' : 'fields'}</span></span>
            <span className="farm-directory-area">{fieldArea(coverage?.boundary_area_m2, unit)}</span>
            <span className="farm-directory-date">{latest ? <time dateTime={latest}>{new Date(latest).toLocaleDateString()}</time> : 'No records'}</span>
            <ArrowUpRight size={16} aria-hidden="true" />
          </button>
        </li>
      })}
      {unassigned.length > 0 ? <li>
        <button type="button" className="farm-directory-row" onClick={() => onOpen('unassigned')}>
          <span className="farm-directory-name"><span className="farm-icon"><Sprout size={20} aria-hidden="true" /></span><strong>Unassigned fields</strong></span>
          <span className="farm-directory-count">{unassigned.length}<span className="mobile-only"> fields</span></span>
          <span className="farm-directory-area">Not grouped</span><span className="farm-directory-date" /><ArrowUpRight size={16} aria-hidden="true" />
        </button>
      </li> : null}
    </ul>
    <a className="farm-directory-link" href={`#fields?season=${season}`}>View all {overview.fields.length} fields <ArrowUpRight size={14} aria-hidden="true" /></a>
  </div>
}
