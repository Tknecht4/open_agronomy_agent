import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BenchmarksRoute } from './BenchmarksRoute'

const apiGetMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ apiGet: apiGetMock }))

describe('BenchmarksRoute evidence boundaries', () => {
  afterEach(() => {
    apiGetMock.mockReset()
  })

  it('fails closed without substituting saved benchmark numbers and still shows adaptation readiness', async () => {
    apiGetMock.mockImplementation((path: string) => {
      if (path === '/api/models/adaptation-readiness') {
        return Promise.resolve({
          available: true,
          status: 'do_not_start_new_global_lora',
          new_global_lora_authorized: false,
          hardware_feasibility: {
            status: 'demonstrated_for_bounded_experiments',
          },
          conference_answer_model: {
            model_id: 'mlx-community/gemma-4-e2b-it-4bit',
            revision: '238767527555cb75a05732a84dff5d6ba0dd6809',
            active_identity_matches_decision: false,
          },
          experiments: [
            {
              id: 'gemma3_270m_task_rabbit_lora_v1',
              status: 'rejected_for_runtime',
              strict_json_rate: 100,
              safety_critical_omission_rows: 17,
            },
            {
              id: 'gemma4_e2b_agxqa_grounded_lora_v3',
              status: 'research_only_not_for_global_runtime',
              document_disjoint_balanced_delta: 5.74,
              critical_regression_rows: 7,
            },
          ],
          blockers: [
            { id: 'task_rabbit_independent_transfer', status: 'open' },
            { id: 'global_adapter_system_stability', status: 'open' },
          ],
          next_experiment: {
            authorized_scope: 'One explicitly routed extraction microtask.',
          },
          boundary: 'Hardware fit does not establish quality.',
        })
      }
      if (path === '/api/benchmarks/aiagribench-proxy/latest') {
        return Promise.reject(new Error('offline'))
      }
      return Promise.reject(new Error('unavailable'))
    })

    render(<BenchmarksRoute />)

    expect(screen.getByText(/No saved counts, scores, or model identity are substituted/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('gemma-4-e2b-it-4bit')).toBeInTheDocument())
    expect(screen.getByText(/process mismatch/i)).toBeInTheDocument()
    expect(screen.getByText('Not authorized')).toBeInTheDocument()
    expect(screen.getByText(/rejected for runtime/i)).toBeInTheDocument()
    expect(screen.getByText(/One explicitly routed extraction microtask/)).toBeInTheDocument()
    expect(screen.queryByText('1056')).not.toBeInTheDocument()
    expect(screen.queryByText('MLX local 2B OptiQ')).not.toBeInTheDocument()
  })

  it('uses the frozen Open Agronomy benchmark as the primary summary', async () => {
    apiGetMock.mockImplementation((path: string) => {
      if (path === '/api/benchmarks/open-agronomy/latest') {
        return Promise.resolve({
          available: true,
          benchmark_id: 'open_agronomy_canadian_performance_v1',
          rows: 241,
          unique_questions: 241,
          exact_duplicate_questions: 0,
          traceable_real_user_questions: 0,
          lane_counts: {
            canadian_decision_quality: 90,
            field_history_lineage: 32,
            objective_agronomic_calculation: 16,
          },
          external_diagnostic: {
            benchmark_id: 'open_agronomy_external_agroqa_v1',
            rows: 256,
            separation_status: 'pass',
            exact_overlap: 0,
            near_overlap: 0,
          },
          claim_eligible: false,
          database_available: false,
        })
      }
      return Promise.reject(new Error('unavailable'))
    })

    render(<BenchmarksRoute />)

    await waitFor(() => expect(screen.getByText('open_agronomy_canadian_performance_v1')).toBeInTheDocument())
    expect(screen.getByText('Canadian development suite and external transfer diagnostic')).toBeInTheDocument()
    expect(screen.getAllByText('241').length).toBeGreaterThan(0)
    expect(screen.getByText('256')).toBeInTheDocument()
    expect(screen.getByText(/AgroQA farmer questions · Uganda · diagnostic only/i)).toBeInTheDocument()
    expect(screen.getByText(/0 exact · 0 near overlaps/i)).toBeInTheDocument()
    expect(screen.getByText('32')).toBeInTheDocument()
    expect(screen.getByText('Historical research evidence')).toBeInTheDocument()
    expect(screen.getByText(/not the current benchmark/i)).toBeInTheDocument()
    expect(screen.getByText('Not run')).toBeInTheDocument()
  })
})
