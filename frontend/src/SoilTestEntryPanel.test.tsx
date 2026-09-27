import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
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
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))

    fireEvent.change(screen.getByLabelText('Sample ID'), { target: { value: 'NQ-2026-01' } })
    fireEvent.change(screen.getByLabelText('Measurement'), { target: { value: 'nitrate_n' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '12.5' } })
    fireEvent.change(screen.getByLabelText('Unit on report'), { target: { value: 'ppm' } })
    fireEvent.change(screen.getByLabelText('Lab method'), { target: { value: 'cadmium reduction' } })
    fireEvent.change(screen.getByLabelText('Depth bottom'), { target: { value: '60' } })
    fireEvent.change(screen.getByLabelText('Lab name'), { target: { value: 'Prairie Lab' } })
    expect((screen.getByLabelText('Sampled at') as HTMLInputElement).value).toBe('')
    expect(screen.getByLabelText('Original report retained')).not.toBeChecked()
    fireEvent.click(screen.getByLabelText('Original report retained'))
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
    expect(await screen.findByText('Saved. Keep the original report if available.')).toBeInTheDocument()
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('blocks duplicate saves and keeps the typed sample after an API failure', async () => {
    let rejectSave: ((error: Error) => void) | undefined
    apiPostMock.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectSave = reject }))
    const onSaved = vi.fn()
    render(<SoilTestEntryPanel fieldContextId="field-1" onSaved={onSaved} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    fireEvent.change(screen.getByLabelText('Sample ID'), { target: { value: 'S-1' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Unit on report'), { target: { value: 'ppm' } })
    fireEvent.change(screen.getByLabelText('Lab method'), { target: { value: 'reported method' } })
    fireEvent.change(screen.getByLabelText('Depth bottom'), { target: { value: '15' } })
    const form = screen.getByRole('form', { name: 'Add structured soil-test result' })
    fireEvent.submit(form)
    fireEvent.submit(form)
    expect(apiPostMock).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    await act(async () => { rejectSave?.(new Error('offline')) })
    expect(screen.getByText('Save failed: offline')).toBeInTheDocument()
    expect(screen.getByLabelText('Sample ID')).toHaveValue('S-1')
    expect(screen.getByLabelText('Value')).toHaveValue(7)
    fireEvent.submit(form)
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledTimes(2))
    expect(onSaved).toHaveBeenCalledOnce()
  })

  it('does not apply a completed save to a newly selected field', async () => {
    let resolveSave: ((value: unknown) => void) | undefined
    apiPostMock.mockImplementationOnce(() => new Promise(resolve => { resolveSave = resolve }))
    const onSaved = vi.fn()
    const { rerender } = render(<SoilTestEntryPanel key="field-1" fieldContextId="field-1" onSaved={onSaved} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    fireEvent.change(screen.getByLabelText('Sample ID'), { target: { value: 'S-1' } })
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText('Unit on report'), { target: { value: 'ppm' } })
    fireEvent.change(screen.getByLabelText('Lab method'), { target: { value: 'reported method' } })
    fireEvent.change(screen.getByLabelText('Depth bottom'), { target: { value: '15' } })
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    expect(apiPostMock).toHaveBeenCalledOnce()
    rerender(<SoilTestEntryPanel key="field-2" fieldContextId="field-2" onSaved={onSaved} />)
    await act(async () => { resolveSave?.({ event: { id: 'old-field-event' } }) })
    expect(onSaved).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    expect(screen.getByLabelText('Sample ID')).toHaveValue('')
  })
})
