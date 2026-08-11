import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import CanadianKnowledgeCoveragePanel from './CanadianKnowledgeCoveragePanel'

afterEach(() => {
  vi.unstubAllGlobals()
})

it('separates regional context from applied advisory coverage', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    json: async () => ({
      available: true,
      advisory_ready: false,
      boundary: 'Regional context cannot independently support a management action.',
      advisory_readiness: {
        available: true,
        status: 'blocked',
        blockers: ['applied_guidance_breadth', 'field_offline_topology'],
        blocker_details: [
          {
            id: 'applied_guidance_breadth',
            status: 'blocked',
            priority: 'P1',
            criterion: 'Every province needs current admitted applied guidance.',
            note: 'The prepared candidates still require independent review.',
            evidence: [
              {
                path: 'outputs/applied-guidance-readiness.json',
                exists: true,
                sha256: 'a'.repeat(64),
              },
            ],
          },
          {
            id: 'field_offline_topology',
            status: 'blocked',
            priority: 'P1',
            criterion: 'A portable runtime must answer without public internet.',
            note: 'A distinct client and battery-operable runtime have not been observed.',
            evidence: [
              {
                path: 'outputs/field-topology.json',
                exists: true,
                sha256: 'b'.repeat(64),
              },
              {
                path: 'data/manifests/field-receipt-schema.json',
                exists: true,
                sha256: 'c'.repeat(64),
              },
            ],
          },
        ],
        boundary: 'A system-readiness gate is not evidence of agronomic effectiveness.',
      },
      summary: {
        province_count: 10,
        governed_local_rows: 1046,
        governed_local_sources: 29,
        regional_context_provinces: 10,
        standard_applied_guidance_provinces: 0,
        bounded_applied_guidance_provinces: 2,
        actual_french_standard_applied_rows: 0,
      },
      admission_frontier: {
        current_review_ready_jurisdictions: ['Alberta', 'British Columbia', 'Manitoba'],
        next_third_jurisdiction: {
          jurisdiction: 'British Columbia',
          candidate: 'AEM Code section 59.1 nutrient application plan screen',
          status: 'review_packet_prepared_not_runtime_authorized',
          live_verified_at: '2026-07-27',
          selection_basis: 'The exact regulation and source-specific licence have been checked.',
          unresolved_gates: [
            'two independent signed professional reviews',
            'live official-law currentness recheck',
          ],
          source_url: 'https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/8_2019',
          rights_url: 'https://www.bclaws.gov.bc.ca/standards/Licence.html',
          runtime_activation_authorized: false,
        },
        boundary: 'This ranking allocates source-admission work. It is not a claim that the source is licensed or reviewed.',
      },
      discovery_pipeline: {
        available: true,
        selected_candidates: 97,
        jurisdictions_with_candidates: 10,
        french_candidates: 4,
        access_barrier_candidates: 1,
        federal_publications_candidates: 6,
        admitted_candidates: 0,
        evaluation_contract_status: 'blocked_pending_rights_content_freeze_and_independent_review',
        evaluation_results_claimed: false,
        runtime_admission_before_gate: false,
        acquisition_funnel: {
          official_records_discovered: 23026,
          ranked_leads: 97,
          admitted_from_ranked_leads: 0,
          display_text: '23,026 official records → 97 ranked leads → 0 admitted',
          boundary: 'This discovery lane does not assert packet ancestry and is not evidence of agronomic correctness.',
        },
        review_pipeline: {
          prepared_packet_groups: 3,
          source_documents: 8,
          candidate_summaries: 15,
          required_independent_reviews: 30,
          completed_independent_reviews: 0,
          cryptographically_verified_reviews: 0,
          independent_review_cleared_packet_groups: 0,
          admitted_packet_groups: 0,
          lineage_relation_to_current_ranked_slate: 'mixed_exact_ranked_and_separate_acquisition',
          display_text: 'Separate review lane: 3 prepared groups · 8 source documents · 15 candidate summaries · 0/30 independent reviews cryptographically verified · 0 admitted',
          boundary: 'Manitoba includes exact ranked check-stamp and stored-grain sources; the other sources retain separate acquisition lineage. All candidates remain quarantined.',
          packet_groups: [
            {
              packet_id: 'alberta_2026_ogla_manure_requirements',
              jurisdiction: 'Alberta',
              source_document_count: 3,
              candidates: { count: 6 },
              required_independent_reviews: 12,
              completed_independent_reviews: 0,
              cryptographically_verified_reviews: 0,
              display_lines: [
                '3 source docs · 6 candidates quarantined · 0 admitted',
                'Review evidence: signed reviewer registry, frozen assignments, and individual signatures required',
                'Internal fidelity checked; no external review credit',
                'Census lineage: post census separate acquisition',
                'Ranked-slate lineage: not in current ranked slate',
              ],
              promotion_warning: null,
              independent_review_cleared: false,
              review_evidence_mode: 'coordinator_signed_registry_and_assignment_plus_individually_signed_reviews',
              legacy_csv_is_promotion_evidence: false,
              promotion_transform_status: 'implemented_six_candidate_transform_pending_signed_evidence',
              runtime_admitted: false,
              internal_source_fidelity_review: {
                performed_at: '2026-07-27',
                classification: 'development_side_pdf_fidelity_review_not_independent_agronomic_review',
                source_pages_rendered_and_visually_checked: 13,
                repaired_candidate_count: 3,
                external_review_credit: false,
                decision: 'Repaired candidate hashes supersede the prior unreviewed hashes; all six remain quarantined.',
              },
              census_lineage: {
                relation: 'post_census_separate_acquisition',
                record_ids: [],
              },
              ranked_slate_lineage: {
                relation: 'not_in_current_ranked_slate',
                record_ids: [],
              },
            },
            {
              packet_id: 'british_columbia_aem_section_59_1_navigation',
              jurisdiction: 'British Columbia',
              source_document_count: 1,
              candidates: { count: 1 },
              required_independent_reviews: 2,
              completed_independent_reviews: 0,
              cryptographically_verified_reviews: 0,
              display_lines: [
                '1 source docs · 1 candidates quarantined · 0 admitted',
                'Review evidence: signed reviewer registry, frozen assignments, and individual signatures required',
                'Internal fidelity checked; no external review credit',
                'Census lineage: post census separate acquisition',
                'Ranked-slate lineage: not in current ranked slate',
              ],
              promotion_warning: null,
              independent_review_cleared: false,
              review_evidence_mode: 'coordinator_signed_registry_and_assignment_plus_individually_signed_reviews',
              legacy_csv_is_promotion_evidence: false,
              promotion_transform_status: 'implemented_one_candidate_transform_pending_signed_evidence',
              runtime_admitted: false,
              internal_source_fidelity_review: {
                performed_at: '2026-07-27',
                classification: 'development_side_legal_source_fidelity_review_not_independent_professional_review',
                source_pages_rendered_and_visually_checked: 3,
                repaired_candidate_count: 0,
                external_review_credit: false,
                decision: 'Exact section 59.1 conditions remain quarantined.',
              },
              census_lineage: {
                relation: 'post_census_separate_acquisition',
                record_ids: [],
              },
              ranked_slate_lineage: {
                relation: 'not_in_current_ranked_slate',
                record_ids: [],
              },
            },
            {
              packet_id: 'manitoba_2026_openmb_crop_protection',
              jurisdiction: 'Manitoba',
              source_document_count: 4,
              candidates: { count: 8 },
              required_independent_reviews: 16,
              completed_independent_reviews: 0,
              cryptographically_verified_reviews: 0,
              display_lines: [
                '4 source docs · 8 candidates quarantined · 0 admitted',
                'Review evidence: signed reviewer registry, frozen assignments, and individual signatures required',
                'Internal fidelity checked; no external review credit',
                'Census lineage: all source documents present in census',
                'Ranked-slate lineage: partial source documents in current ranked slate',
              ],
              promotion_warning: null,
              independent_review_cleared: false,
              review_evidence_mode: 'coordinator_signed_registry_and_assignment_plus_individually_signed_reviews',
              legacy_csv_is_promotion_evidence: false,
              promotion_transform_status: 'implemented_eight_candidate_transform_pending_signed_evidence',
              runtime_admitted: false,
              internal_source_fidelity_review: {
                performed_at: '2026-07-27',
                classification: 'development_side_source_fidelity_review_not_independent_agronomic_review',
                source_pages_rendered_and_visually_checked: 8,
                source_html_snapshots_checked: 1,
                repaired_candidate_count: 4,
                external_review_credit: false,
                decision: 'Four candidate hashes supersede their prior unreviewed hashes; all eight remain quarantined.',
              },
              census_lineage: {
                relation: 'all_source_documents_present_in_census',
                record_ids: ['mb-check-stamp'],
              },
              ranked_slate_lineage: {
                relation: 'partial_source_documents_in_current_ranked_slate',
                record_ids: ['mb-check-stamp'],
              },
            },
          ],
        },
        french_source_lane: {
          ranked_french_records: 8,
          unique_source_families: 7,
          permission_requests_not_submitted: 4,
          permission_requests_withheld_pending_source_access: 0,
          permission_requests_withheld_after_exact_source_preflight: 3,
          connected_link_only_families: 4,
          source_asset_access_blocked_families: 0,
          exact_byte_currentness_rejected_families: 1,
          exact_byte_rights_blocked_families: 2,
          packaged_offline_families: 0,
          runtime_admitted_families: 0,
          display_text: 'French source lane: 8 ranked records → 7 source families → 4 connected link-only · 0 source asset access-blocked · 1 exact-byte currentness-rejected · 2 exact-byte rights-blocked → 0 packaged offline → 0 admitted',
          boundary: 'Recovered bytes are preflight evidence only; no source bytes, extracted text, thresholds, pesticide table, index or embedding is packaged or used by runtime retrieval.',
        },
        source_preflight_pipeline: {
          preflighted_source_families: 32,
          ranked_records_resolved: 36,
          advanced_to_review_packet: 3,
          rejected_for_actionable_review_packet: 18,
          blocked_pending_rights_clarification: 11,
          runtime_admitted: 0,
          display_text: 'Source preflights: 32 families · 36 ranked records resolved · 3 advanced · 18 actionable-rejected · 11 rights-blocked',
          boundary: 'Passing rights or extraction cannot compensate for stale recommendations.',
        },
        source_leads: [
          {
            jurisdiction: 'Canada',
            candidate_count: 11,
            access_barrier_count: 0,
            gaps: ['no_exact_open_catalog_candidate_in_slate'],
            leads: [
              {
                record_id: 'federal-french-guide',
                title: 'Guide d’identification des ravageurs',
                url: 'https://publications.gc.ca/site/eng/9.852950/publication.html',
                language: 'fr-CA',
                format: 'pdf',
                rights_lane: 'federal_noncommercial_reproduction_commercial_permission_review',
                currency_state: 'exact_source_bytes_recovered_currentness_rejected',
                access_state: 'recovered_exact_official_bilingual_pdf_via_archive_continuation',
                access_barrier: false,
                source_asset_access_blocked: false,
                source_access: {
                  status: 'recovered_exact_official_bilingual_pdf_via_archive_continuation',
                  exact_pdf_frozen: true,
                  required_next_gate: 'Use only as historical IPM provenance.',
                },
                task_signals: ['guide_or_manual', 'pest_or_disease_decision'],
                required_next_gate: 'Use only as historical IPM provenance.',
              },
            ],
          },
          {
            jurisdiction: 'Manitoba',
            candidate_count: 12,
            access_barrier_count: 0,
            gaps: ['no_exact_open_catalog_candidate_in_slate'],
            leads: [
              {
                record_id: 'mb-soil-fertility',
                title: 'Soil Fertility Guide',
                url: 'https://www.gov.mb.ca/agriculture/crops/soil-fertility/soil-fertility-guide/index.html',
                language: 'en-CA',
                format: 'html',
                rights_lane: 'openmb_candidate_exact_item_review',
                currency_state: 'historical_or_undated_review',
                access_state: 'content',
                access_barrier: false,
                task_signals: ['guide_or_manual', 'soil_or_nutrient_decision'],
                required_next_gate: 'verify_exact_item_licence_and_currency',
                preflight: {
                  preflight_id: 'manitoba_soil_fertility_guide_2007',
                  source_family_id: 'manitoba_soil_fertility_guide',
                  disposition: 'rejected_for_actionable_review_packet',
                  allowed_role: 'historical_or_background_reference_candidate_only',
                  reason: 'The recommendation tables are too old and partly superseded.',
                  next_gate: 'Locate a current source.',
                  runtime_admitted: false,
                },
              },
              {
                record_id: 'mb-check-stamp',
                title: 'Assessing Crop Stands when Fertilizer is Applied at Seeding',
                url: 'https://www.gov.mb.ca/agriculture/crops/seasonal-reports/pubs/assessing-stands-when-fertilizer-applied-at-seeding.pdf',
                language: 'en-CA',
                format: 'pdf',
                rights_lane: 'openmb_candidate_exact_item_review',
                currency_state: 'historical_or_undated_review',
                access_state: 'content',
                access_barrier: false,
                task_signals: ['soil_or_nutrient_decision', 'crop_management'],
                required_next_gate: 'verify_exact_item_licence_third_party_exclusions_and_extractability',
                preflight: {
                  preflight_id: 'manitoba_fertilizer_check_stamp_2020',
                  source_family_id: 'manitoba_fertilizer_check_stamp_method',
                  disposition: 'advanced_to_review_packet',
                  allowed_role: 'quarantined_bounded_field_observation_candidate',
                  reason: 'One hash-bound candidate is ready for two independent reviews.',
                  next_gate: 'Complete two independent reviews.',
                  runtime_admitted: false,
                },
              },
            ],
          },
          {
            jurisdiction: 'Prince Edward Island',
            candidate_count: 0,
            access_barrier_count: 1,
            gaps: ['publisher_access_barrier_requires_resolution'],
            leads: [
              {
                record_id: 'pei-access',
                title: 'Prince Edward Island Department of Agriculture',
                url: 'https://www.princeedwardisland.ca/en/information/agriculture/integrated-pest-management',
                language: 'en-CA',
                format: 'unknown',
                rights_lane: 'private_cache_or_live_reference',
                currency_state: 'publisher_access_blocked',
                access_state: 'waf_interstitial',
                access_barrier: true,
                task_signals: ['pest_or_disease_decision'],
                required_next_gate: 'resolve_access_with_publisher',
              },
            ],
          },
        ],
        boundary: 'Discovery candidates cannot influence answers before all gates pass.',
      },
      provinces: [
        {
          province: 'Alberta',
          coverage_label: 'Bounded context only',
          admission_state: 'candidate_pending_independent_agronomist',
          candidate: '2026 manure guidance',
          source_url: 'https://open.alberta.ca/example',
          rights_state: 'redistributable_open_government_licence',
          rights_url: 'https://open.alberta.ca/licence',
          rights_reaudit_at: '2026-07-25',
          rights_reaudit_result: 'The exact item is covered by the catalogue licence.',
          permission_status: 'not_submitted / none',
          permission_route: 'https://example.test/permission',
          next_action: 'Complete independent review.',
        },
        {
          province: 'British Columbia',
          coverage_label: 'Regional context only',
          admission_state: 'candidate_pending_independent_professional_review',
          candidate: 'AEM Code section 59.1 nutrient application plan screen',
          source_url: 'https://www.bclaws.gov.bc.ca/civix/document/id/complete/statreg/8_2019',
          rights_state: 'kings_printer_licensed_with_currentness_and_attribution_duties',
          rights_url: 'https://www.bclaws.gov.bc.ca/standards/Licence.html',
          permission_status: 'not_required',
          next_action: 'Complete two independent professional reviews and a live-law recheck.',
        },
        {
          province: 'New Brunswick',
          coverage_label: 'Regional context only',
          admission_state: 'permission_and_scope_review_required',
          candidate: 'Cereal Pest Control Selection Guide',
          source_url: 'https://www2.gnb.ca/example.pdf',
          rights_state: 'general_publication_rights_not_established',
          rights_url: 'https://www2.gnb.ca/example-rights',
          permission_status: 'withheld_after_preflight / rejected_for_actionable_review_packet',
          permission_withheld_state: 'withheld_after_exact_source_preflight',
          permission_withheld_reason: 'The shared bilingual insecticide table is headed English 2026 and French 2021.',
          permission_preflight_id: 'new_brunswick_cereal_pest_control_2026_2021',
          next_action: 'Ask New Brunswick Agriculture to publish a corrected exact file.',
        },
      ],
    }),
  })))

  render(<CanadianKnowledgeCoveragePanel />)

  expect(await screen.findByText('Canadian source coverage')).toBeInTheDocument()
  expect(await screen.findByText('Advisory blocked')).toBeInTheDocument()
  expect(screen.getByText('1,046')).toBeInTheDocument()
  expect(screen.getByText('29')).toBeInTheDocument()
  expect(screen.getByText('10/10')).toBeInTheDocument()
  expect(screen.getByText('0/10')).toBeInTheDocument()
  expect(screen.getByText('local reference passages')).toBeInTheDocument()
  expect(screen.getByText('admitted guidance')).toBeInTheDocument()
  expect(screen.getByText('Bounded context only')).toBeInTheDocument()
  expect(screen.queryByText('2026 manure guidance')).not.toBeInTheDocument()
  expect(screen.getByText('Why advisory is blocked')).toBeInTheDocument()
  expect(screen.getByText('2 open gates')).toBeInTheDocument()
  expect(screen.getByText('Applied guidance breadth')).toBeInTheDocument()
  expect(screen.getByText('Field offline topology')).toBeInTheDocument()
  expect(screen.getByText(
    'A system-readiness gate is not evidence of agronomic effectiveness.',
  )).toBeInTheDocument()
  expect(screen.getByText('Source discovery')).toBeInTheDocument()
  expect(screen.getByText(
    '97 leads · 0 admitted · British Columbia review next',
  )).toBeInTheDocument()
  expect(screen.getByText(
    '23,026 official records → 97 ranked leads → 0 admitted',
  )).toBeInTheDocument()
  expect(screen.getByText(
    'Separate review lane: 3 prepared groups · 8 source documents · 15 candidate summaries · 0/30 independent reviews cryptographically verified · 0 admitted',
  )).toBeInTheDocument()
  expect(screen.getByText('Independent review packets')).toBeInTheDocument()
  expect(screen.getAllByText(/signed reviewer registry, frozen assignments, and individual signatures required/)).toHaveLength(3)
  expect(screen.queryByText(/legacy unsigned CSV/)).not.toBeInTheDocument()
  expect(screen.queryByText(/Promotion warning/)).not.toBeInTheDocument()
  expect(screen.getByText('0/12 verified')).toBeInTheDocument()
  expect(screen.getByText('0/2 verified')).toBeInTheDocument()
  expect(screen.getByText('0/16 verified')).toBeInTheDocument()
  expect(screen.getAllByText(
    'Internal fidelity checked; no external review credit',
  )).toHaveLength(3)
  expect(screen.getAllByText(/Census lineage: post census separate acquisition/)).toHaveLength(2)
  expect(screen.getByText(
    /8 ranked records → 7 source families → 4 connected link-only · 0 source asset access-blocked · 1 exact-byte currentness-rejected · 2 exact-byte rights-blocked → 0 packaged offline → 0 admitted/,
  )).toBeInTheDocument()
  expect(screen.getByText(/32 families · 36 ranked records resolved · 3 advanced · 18 actionable-rejected · 11 rights-blocked/)).toBeInTheDocument()
  expect(screen.queryByText('Soil Fertility Guide')).not.toBeInTheDocument()
  expect(screen.queryByText('Coverage rows')).not.toBeInTheDocument()
})

it('fails closed when coverage evidence cannot load', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => {
    throw new Error('offline artifact missing')
  }))

  render(<CanadianKnowledgeCoveragePanel />)

  expect(await screen.findByText('Advisory blocked')).toBeInTheDocument()
  expect(screen.getByText(/guidance remains absent/i)).toBeInTheDocument()
})
