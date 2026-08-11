import { useEffect, useState } from 'react'
import { Database } from 'lucide-react'

import { apiPost } from './api'

type QuebecLidarPlanResponse = {
  status: 'ready_to_download' | 'no_matching_tiles' | string
  receipt: {
    matched_tile_count: number
    field_geometry_sha256: string
  }
  boundary: string
}

type OfflineTerrainContextPanelProps = {
  id: string
  m: 'account_workspace' | 'device'
  k: 'none' | 'point' | 'polygon'
  area: string
}

const isQuebecJurisdiction = (jurisdiction: string): boolean =>
  ['quebec', 'québec', 'qc'].includes(jurisdiction.trim().toLowerCase())

const initialStatus = ({
  id,
  m,
  k,
  area,
}: OfflineTerrainContextPanelProps): string => {
  if (!id || m !== 'account_workspace') {
    return 'Save or load the field in this workspace first.'
  }
  if (!isQuebecJurisdiction(area) || k !== 'polygon') {
    return 'This preparation lane currently requires a saved Quebec polygon field.'
  }
  return 'Saved Quebec field ready for an offline terrain availability check.'
}

export default function OfflineTerrainContextPanel(props: OfflineTerrainContextPanelProps) {
  const [plan, setPlan] = useState<QuebecLidarPlanResponse | null>(null)
  const [status, setStatus] = useState(() => initialStatus(props))
  const eligible = Boolean(
    props.id
    && props.m === 'account_workspace'
    && props.k === 'polygon'
    && isQuebecJurisdiction(props.area),
  )

  useEffect(() => {
    setPlan(null)
    setStatus(initialStatus(props))
  }, [props.id, props.m, props.k, props.area])

  const checkAvailability = async () => {
    if (!eligible) {
      setStatus(initialStatus(props))
      return
    }
    setPlan(null)
    setStatus('Checking the verified local MAPAQ tile index. No network request is made.')
    try {
      const result = await apiPost<QuebecLidarPlanResponse>(
        `/api/demo/fields/${encodeURIComponent(props.id)}/context-packs/quebec-lidar/plan`,
        {},
      )
      setPlan(result)
      setStatus(
        result.status === 'ready_to_download'
          ? `${result.receipt.matched_tile_count} source tile${result.receipt.matched_tile_count === 1 ? '' : 's'} available for connected preparation.`
          : 'No MAPAQ source tile matched the saved field.',
      )
    } catch (error) {
      setStatus(`Offline context check unavailable: ${String((error as Error).message || error)}`)
    }
  }

  return (
    <details className="workspace-disclosure offline-context-disclosure">
      <summary>
        <Database size={16} /> Offline terrain context
        {plan ? <span>{plan.receipt.matched_tile_count}</span> : null}
      </summary>
      <div className="offline-context-prep">
        <p>{status}</p>
        <button
          type="button"
          className="map-primary-action"
          onClick={() => void checkAvailability()}
          disabled={!eligible}
        >
          Check saved field
        </button>
        {plan ? (
          <div className="offline-context-receipt" aria-label="Offline terrain availability receipt">
            <strong>
              {plan.receipt.matched_tile_count} official MAPAQ source
              {plan.receipt.matched_tile_count === 1 ? ' tile' : ' tiles'}
            </strong>
            <span>Context only · not downloaded · not recommendation grade</span>
            <small>Field binding {plan.receipt.field_geometry_sha256.slice(0, 12)}</small>
            <small>{plan.boundary}</small>
          </div>
        ) : null}
        <small>
          This local check does not contact MAPAQ. Connected download and validated derivation remain an explicit
          operator step in this build.
        </small>
      </div>
    </details>
  )
}
