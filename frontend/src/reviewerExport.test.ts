import { describe, expect, it } from 'vitest'
import { buildReviewerExportMarkdown, reviewerExportFilename } from './reviewerExport'
import { Turn } from './types'

const sampleTurn: Turn = {
  turn_id: 'turn_demo_1',
  session_id: 'session_demo_1',
  user_message: 'Should I sidedress nitrogen after a wet spring?',
  answer:
    'Use the recent wet spring as a leaching-risk signal, but do not change the rate without nitrate test method, yield goal, manure history, and local calibration.',
  answer_status: 'completed',
  answer_integrity_receipt: {
    schema_version: 'open_agronomy_agent.answer_integrity_receipt.v1',
    status: 'verified',
    receipt_sha256: 'a'.repeat(64),
    question_sha256: 'b'.repeat(64),
    answer_sha256: 'c'.repeat(64),
    trace_sha256: 'd'.repeat(64),
    system_state_sha256: 'e'.repeat(64),
    field_snapshot_sha256: 'f'.repeat(64),
    boundary: 'Application-level immutable content receipt; not a digital signature.',
  },
  knowledge_coverage: {
    schema_version: 'open_agronomy_agent.answer_time_knowledge_coverage.v1',
    capture_status: 'captured',
    record_source: 'trace_metadata',
    boundaries: [{
      jurisdiction: 'Iowa',
      status: 'unregistered_jurisdiction',
      requires_prompt_boundary: true,
      retrieved_source_ids: [],
      retrieved_context_source_ids: [],
    }],
  },
  system_state: {
    mode: 'agronomic_rag',
    model_id: 'mlx-community/Qwen3.5-2B-OptiQ-4bit',
    rag_config: 'configs/rag_final_mvp.yaml',
    prompt_version: 'phase6',
    latency_ms: 1200,
    model_identity: {
      status: 'verified_runtime_receipt',
      configured_model_id: 'mlx-community/gemma-4-e2b-it-4bit',
      configured_model_revision: '238767527555cb75a05732a84dff5d6ba0dd6809',
    },
  },
  trace: {
    coverage_checklist: ['hidden checklist item should stay out'],
    prompt_messages: [{ role: 'system', content: 'hidden system prompt should stay out' }],
    route: {
      question_type: 'soil_fertility',
      risk_level: 'regulated',
      namespaces: ['fertility', 'weather'],
      required_tools: ['nasa_power_daily'],
    },
    structured_answer: {
      missing_data_prompts: ['soil nitrate test method', 'yield goal'],
      evidence_cards: [
        {
          title: 'NRCS MLRA 103',
          publisher: 'USDA NRCS',
          source_type: 'map_context',
          adapter_status: 'available',
          url: 'https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra',
          summary: { code: 'MLRA_103', name: 'Central Iowa and Minnesota Till Prairies' },
          known_limitations: ['regional prior, not field truth'],
        },
      ],
    },
  },
}

describe('reviewer export', () => {
  it('builds a reviewer-safe markdown report from visible turn evidence', () => {
    const markdown = buildReviewerExportMarkdown({
      generatedAt: '2026-07-10T02:40:00.000Z',
      field: {
        crop: 'corn',
        region: 'Central Iowa',
        jurisdiction: 'Iowa',
        acres: '148',
        concern: 'wet spring nitrogen risk',
        geometrySummary: 'boundary 5 vertices 148 acres',
        regionalContext: ['NRCS MLRA MLRA_103 (100% field coverage estimate)'],
        sourceBoundary: 'Map context is a regional prior, not field truth.',
      },
      turn: sampleTurn,
      docs: [
        {
          rank: 1,
          doc_id: 'doc_1',
          title: 'Nitrogen after wet spring',
          source_type: 'extension',
          score: 0.91,
          source: 'public extension note',
        },
      ],
      graphHits: [{ rank: 1, node_id: 'n1', name: 'Nitrate leaching', kind: 'concept', neighbors: [], evidence: 'water movement risk' }],
      publicTools: [
        {
          name: 'nasa_power_daily',
          payload: {
            kind: 'public_adapter',
            status: 'available',
            source: 'https://power.larc.nasa.gov/api/temporal/daily/point',
            summary: { parameter_summary: { PRECTOTCORR: { sum: 2.4 } } },
            boundary: 'NASA POWER is gridded weather context, not a field sensor.',
          },
        },
      ],
      mapEvidenceCards: sampleTurn.trace?.structured_answer?.evidence_cards,
    })

    expect(markdown).toContain('# Open Agronomy Agent Review Export')
    expect(markdown).toContain('wet spring nitrogen risk')
    expect(markdown).toContain('Should I sidedress nitrogen')
    expect(markdown).toContain('soil nitrate test method')
    expect(markdown).toContain('NASA POWER')
    expect(markdown).toContain('NRCS MLRA 103')
    expect(markdown).toContain('https://power.larc.nasa.gov/api/temporal/daily/point')
    expect(markdown).toContain('https://www.nrcs.usda.gov/resources/data-and-reports/major-land-resource-area-mlra')
    expect(markdown).toContain('Map context is a regional prior, not field truth.')
    expect(markdown).toContain('Reviewer Notes')
    expect(markdown).toContain('verified_runtime_receipt · mlx-community/gemma-4-e2b-it-4bit · 238767527555')
    expect(markdown).toContain('Nitrogen after wet spring')
    expect(markdown).toContain('"raw_prompt_messages_excluded": true')
    expect(markdown).toContain('"internal_coverage_checklist_excluded": true')
    expect(markdown).toContain('"coverage"')
    expect(markdown).toContain('## Answer Integrity Receipt')
    expect(markdown).toContain(`Receipt SHA-256: ${'a'.repeat(64)}`)
    expect(markdown).toContain(`Trace SHA-256: ${'d'.repeat(64)}`)
    expect(markdown).toContain('not a digital signature')
    expect(markdown).toContain('"status": "unregistered_jurisdiction"')
    expect(markdown).not.toContain('hidden system prompt should stay out')
    expect(markdown).not.toContain('hidden checklist item should stay out')
  })

  it('exports unavailable public-source cards without leaking hidden trace internals', () => {
    const markdown = buildReviewerExportMarkdown({
      generatedAt: '2026-07-10T02:40:00.000Z',
      field: {
        crop: 'tomato',
        region: 'Central Valley',
        jurisdiction: 'California',
        concern: 'irrigation timing',
      },
      turn: {
        ...sampleTurn,
        user_message: 'What should I know before using ET context?',
        answer: 'OpenET is not configured, so use local irrigation records and soil moisture before acting.',
        trace: {
          ...sampleTurn.trace,
          prompt_messages: [{ role: 'system', content: 'do not expose this hidden prompt' }],
          coverage_checklist: ['internal hidden checklist'],
        },
      },
      publicTools: [
        {
          name: 'openet_point_timeseries',
          payload: {
            kind: 'public_adapter',
            status: 'not_configured',
            source: 'OpenET API',
            summary: {
              required_env_vars: ['AGRONOMY_AGENT_OPENET_API_KEY', 'OPENET_API_KEY'],
              model: 'Ensemble',
              variable: 'ET',
            },
            boundary: 'OpenET is public ET context, not an irrigation prescription.',
          },
        },
      ],
    })

    expect(markdown).toContain('OpenET')
    expect(markdown).toContain('needs key')
    expect(markdown).toContain('Needs AGRONOMY_AGENT_OPENET_API_KEY or OPENET_API_KEY')
    expect(markdown).toContain('OpenET API')
    expect(markdown).toContain('OpenET is public ET context, not an irrigation prescription.')
    expect(markdown).toContain('raw_prompt_messages_excluded')
    expect(markdown).not.toContain('do not expose this hidden prompt')
    expect(markdown).not.toContain('internal hidden checklist')
  })

  it('creates a stable markdown filename', () => {
    expect(reviewerExportFilename(sampleTurn, '2026-07-10T02:40:00.000Z')).toBe(
      'open-agronomy-agent-review-2026-07-10-turn-demo-1.md',
    )
  })
})
