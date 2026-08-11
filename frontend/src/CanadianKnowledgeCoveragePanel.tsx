import { useEffect, useState } from 'react'

import { apiGet } from './api'
import './CanadianKnowledgeCoveragePanel.css'

type ProvinceCoverage = {
  province: string
  coverage_label: string
  admission_state: string
  candidate: string
  source_url: string
  rights_state: string
  rights_url: string
  rights_reaudit_at?: string
  rights_reaudit_result?: string
  permission_status: string
  permission_route?: string
  permission_withheld_state?: string
  permission_withheld_reason?: string
  permission_preflight_id?: string
  next_action: string
}

type ReviewPacketGroup = {
  packet_id: string
  jurisdiction: string
  required_independent_reviews: number
  cryptographically_verified_reviews: number
  display_lines: string[]
  promotion_warning?: string | null
}

type AdvisoryBlockerDetail = {
  id: string
  status: string
  priority: string
  criterion: string
  note: string
  evidence: Array<{
    path?: string
    exists?: boolean
    sha256?: string | null
    state?: string
  }>
}

type KnowledgeCoverage = {
  available: boolean
  advisory_ready: boolean
  message?: string
  boundary: string
  advisory_readiness?: {
    available: boolean
    status: string
    blockers: string[]
    blocker_details?: AdvisoryBlockerDetail[]
    boundary: string
  }
  summary: {
    province_count?: number
    governed_local_rows?: number
    governed_local_sources?: number
    regional_context_provinces?: number
    standard_applied_guidance_provinces?: number
    bounded_applied_guidance_provinces?: number
    rights_reaudited_blocked_provinces?: number
    actual_french_standard_applied_rows?: number
  }
  discovery_pipeline?: {
    available: boolean
    selected_candidates?: number
    jurisdictions_with_candidates?: number
    french_candidates?: number
    access_barrier_candidates?: number
    federal_publications_candidates?: number
    admitted_candidates: number
    evaluation_contract_status?: string
    evaluation_results_claimed?: boolean
    runtime_admission_before_gate?: boolean
    acquisition_funnel?: {
      official_records_discovered: number
      ranked_leads: number
      admitted_from_ranked_leads: number
      display_text: string
      boundary: string
    }
    review_pipeline?: {
      prepared_packet_groups: number
      source_documents: number
      candidate_summaries: number
      required_independent_reviews: number
      completed_independent_reviews: number
      cryptographically_verified_reviews: number
      independent_review_cleared_packet_groups: number
      admitted_packet_groups: number
      lineage_relation_to_current_ranked_slate: 'mixed_exact_ranked_and_separate_acquisition'
      display_text: string
      boundary: string
      packet_groups: ReviewPacketGroup[]
    }
    french_source_lane?: {
      ranked_french_records: number
      unique_source_families: number
      permission_requests_not_submitted: number
      permission_requests_withheld_pending_source_access: number
      permission_requests_withheld_after_exact_source_preflight: number
      connected_link_only_families: number
      source_asset_access_blocked_families: number
      exact_byte_currentness_rejected_families: number
      exact_byte_rights_blocked_families: number
      packaged_offline_families: number
      runtime_admitted_families: number
      display_text: string
      boundary: string
    }
    source_preflight_pipeline?: {
      preflighted_source_families: number
      ranked_records_resolved: number
      advanced_to_review_packet: number
      rejected_for_actionable_review_packet: number
      blocked_pending_rights_clarification: number
      runtime_admitted: number
      display_text: string
      boundary: string
    }
    message?: string
    boundary: string
  }
  admission_frontier?: {
    current_review_ready_jurisdictions: string[]
    next_third_jurisdiction: {
      jurisdiction: string
      candidate: string
      status: string
      live_verified_at: string
      selection_basis: string
      unresolved_gates: string[]
      source_url: string
      rights_url: string
      runtime_activation_authorized: boolean
    }
    boundary: string
  }
  provinces: ProvinceCoverage[]
}

const readableGate = (identifier: string): string => {
  const label = identifier.replace(/_/g, ' ')
  return label.charAt(0).toUpperCase() + label.slice(1)
}

export default function CanadianKnowledgeCoveragePanel() {
  const [coverage, setCoverage] = useState<KnowledgeCoverage | null>(null)

  useEffect(() => {
    let active = true
    apiGet<KnowledgeCoverage>('/api/knowledge/coverage')
      .then((result) => {
        if (active) setCoverage(result)
      })
      .catch(() => {
        if (active) {
          setCoverage({
            available: false,
            advisory_ready: false,
            boundary: 'Coverage unavailable; guidance remains absent.',
            summary: {},
            provinces: [],
          })
        }
      })
    return () => {
      active = false
    }
  }, [])

  if (!coverage) {
    return <section className="canadian-knowledge-coverage">Loading</section>
  }

  const summary = coverage.summary
  const discovery = coverage.discovery_pipeline
  const nextFrontier = coverage.admission_frontier?.next_third_jurisdiction
  const nextLane = nextFrontier?.jurisdiction
  const nextLaneAction = nextFrontier?.status === 'review_packet_prepared_not_runtime_authorized'
    ? 'review next'
    : nextFrontier?.status.includes('permission')
      ? 'permission next'
      : 'next gate'
  const blockerDetails = coverage.advisory_readiness?.blocker_details || []
  return (
    <section className="canadian-knowledge-coverage">
      <div className="canadian-knowledge-heading">
        <div>
          <div className="panel-kicker">Canada</div>
          <h2>Canadian source coverage</h2>
        </div>
        <span className={coverage.advisory_ready ? 'knowledge-gate-ready' : 'knowledge-gate-blocked'}>
          {coverage.advisory_ready ? 'Advisory ready' : 'Advisory blocked'}
        </span>
      </div>
      {!coverage.available ? (
        <p className="knowledge-coverage-error">{coverage.message || 'Coverage evidence unavailable.'}</p>
      ) : (
        <>
          <div className="knowledge-coverage-summary">
            <article>
              <strong>{summary.governed_local_rows?.toLocaleString()}</strong>
              <span>local reference passages</span>
            </article>
            <article>
              <strong>{summary.governed_local_sources}</strong>
              <span>governed sources</span>
            </article>
            <article>
              <strong>{summary.regional_context_provinces}/{summary.province_count}</strong>
              <span>provinces with context</span>
            </article>
            <article>
              <strong>{summary.standard_applied_guidance_provinces}/{summary.province_count}</strong>
              <span>admitted guidance</span>
            </article>
          </div>
          <div className="knowledge-province-grid">
            {coverage.provinces.map((province) => (
              <article key={province.province}>
                <span>{province.province}</span>
                <strong>{province.coverage_label}</strong>
              </article>
            ))}
          </div>
          {blockerDetails.length ? (
            <details className="knowledge-discovery knowledge-review-packets">
              <summary>
                <span>Why advisory is blocked</span>
                <strong>{blockerDetails.length} open gates</strong>
              </summary>
              <div className="knowledge-discovery-grid">
                {blockerDetails.map((blocker) => (
                  <details key={blocker.id}>
                    <summary>
                      <strong>{readableGate(blocker.id)}</strong>
                    </summary>
                    <small>{blocker.criterion}</small>
                    <small>{blocker.note}</small>
                  </details>
                ))}
              </div>
              <p className="knowledge-discovery-boundary">
                {coverage.advisory_readiness?.boundary}
              </p>
            </details>
          ) : null}
          {discovery?.available ? (
            <section className="knowledge-discovery" aria-labelledby="official-source-discovery">
              <div className="knowledge-discovery-heading">
                <h3 id="official-source-discovery">Source discovery</h3>
                <strong>
                  {discovery.selected_candidates?.toLocaleString()} leads · {discovery.admitted_candidates} admitted
                  {nextLane ? ` · ${nextLane} ${nextLaneAction}` : ''}
                </strong>
              </div>
              <p>
                Leads are not answer evidence.
              </p>
              {[
                discovery.acquisition_funnel,
                discovery.review_pipeline,
                discovery.source_preflight_pipeline,
                discovery.french_source_lane,
              ].map((lane, index) => lane ? (
                <p key={index} className="knowledge-acquisition-funnel">
                  {lane.display_text}
                </p>
              ) : null)}
              {discovery.review_pipeline?.packet_groups?.length ? (
                <section
                  className="knowledge-review-packets"
                  aria-labelledby="independent-review-packets"
                >
                  <div>
                    <div className="panel-kicker">Review gate</div>
                    <h4 id="independent-review-packets">Independent review packets</h4>
                  </div>
                  <div className="knowledge-discovery-grid">
                    {discovery.review_pipeline.packet_groups.map((group) => (
                      <details key={group.packet_id}>
                        <summary>
                          <span>{group.jurisdiction}</span>
                          <strong>
                            {group.cryptographically_verified_reviews}/
                            {group.required_independent_reviews} verified
                          </strong>
                        </summary>
                        {group.display_lines.map((line) => (
                          <small key={line}>{line}</small>
                        ))}
                        {group.promotion_warning ? (
                          <small className="knowledge-review-warning">
                            {group.promotion_warning}
                          </small>
                        ) : null}
                      </details>
                    ))}
                  </div>
                </section>
              ) : null}
              <p className="knowledge-discovery-boundary">{discovery.boundary}</p>
            </section>
          ) : null}
        </>
      )}
      <p className="knowledge-coverage-boundary">{coverage.boundary}</p>
    </section>
  )
}
