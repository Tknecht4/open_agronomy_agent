import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SoilTestEntryPanel } from './FieldSyncPanel'

const apiPostMock = vi.hoisted(() => vi.fn())

vi.mock('./api', () => ({ apiPost: apiPostMock, apiGet: vi.fn() }))

describe('SoilTestEntryPanel', () => {
  beforeEach(() => {
    apiPostMock.mockReset()
    apiPostMock.mockResolvedValue({ event: { id: 'event-1' } })
  })

  it('sends the exact sample, unit, method, depth, scope, and capture quality', async () => {
    const onSaved = vi.fn()
    render(<SoilTestEntryPanel fieldContextId="field-1" onSaved={onSaved} />)
    fireEvent.click(screen.getByText('Add structured soil-test result'))

    fireEvent.change(screen.getByLabelText('Sample ID'), { target: { value: 'NQ-2026-01' } })
    fireEvent.change(screen.getByLabelText('Measurement'), { target: { value: 'nitrate_n' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '12.5' } })
    fireEvent.change(screen.getByLabelText('Unit on report'), { target: { value: 'ppm' } })
    fireEvent.change(screen.getByLabelText('Lab method'), { target: { value: 'cadmium reduction' } })
    fireEvent.change(screen.getByLabelText('Depth bottom'), { target: { value: '60' } })
    fireEvent.change(screen.getByLabelText('Lab name'), { target: { value: 'Prairie Lab' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save soil test' }))

    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    expect(apiPostMock).toHaveBeenCalledWith('/api/demo/fields/field-1/events', {
      event_type: 'sample',
      payload: {
        summary: 'Nitrate-N: 12.5 ppm · sample NQ-2026-01',
        measurement: {
          schema_version: 'open_agronomy_agent.field_measurement.v1',
          kind: 'soil_test',
          sample_id: 'NQ-2026-01',
          metric: 'nitrate_n',
          label: 'Nitrate-N',
          value: 12.5,
          unit: 'ppm',
          method: 'cadmium reduction',
          sample_depth: { top: 0, bottom: 60, unit: 'cm' },
          spatial_scope: 'composite',
          source_quality: 'user_transcribed_lab_report',
          lab_name: 'Prairie Lab',
        },
      },
      provenance: {
        capture_method: 'user_transcribed_lab_report',
        surface: 'fields_soil_test_form',
        original_report_retained: true,
      },
    })
    expect(await screen.findByText('Saved. Keep the original report.')).toBeInTheDocument()
    expect(onSaved).toHaveBeenCalledOnce()
  })
})
