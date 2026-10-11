import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useState } from 'react'
import { SoilTestEntryPanel, FieldEventRecoveryPanel } from './FieldSyncPanel'
import { testReceipt, testScope } from './fieldEventTestSupport'

const apiPostMock = vi.hoisted(() => vi.fn())
const apiGetMock = vi.hoisted(() => vi.fn())

vi.mock('./api', async original => ({ ...await original<typeof import('./api')>(), apiPost: apiPostMock, apiGet: apiGetMock }))

describe('SoilTestEntryPanel', () => {
  beforeEach(() => {
    localStorage.clear()
    apiPostMock.mockReset()
    apiGetMock.mockReset()
    apiGetMock.mockImplementation(async (path: string) => testScope(path.split('/')[4]))
    apiPostMock.mockImplementation(async (path, body) => testReceipt(path, body))
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
      client_operation_id: expect.any(String),
      expected_actor_user_id: testScope().actor_user_id,
      expected_workspace_id: testScope().workspace_id,
      expected_operation_protocol: testScope().protocol,
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
        sampling_time_status: 'unknown',
        original_report_retained: true,
      },
    })
    expect(await screen.findByText('Saved. Keep the original report if available.')).toBeInTheDocument()
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  })

  it('retains an explicitly supplied sampling date separately from entry time', async () => {
    render(<SoilTestEntryPanel fieldContextId="field-1" onSaved={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    for (const [label, value] of [['Sample ID', 'dated-sample'], ['Value', '7'], ['Unit on report', 'pH'], ['Lab method', 'water'], ['Depth bottom', '15'], ['Sampled at', '2025-05-12T09:30']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    expect(apiPostMock.mock.calls[0][1]).toMatchObject({
      occurred_at: new Date('2025-05-12T09:30').toISOString(),
      provenance: { sampling_time_status: 'user_supplied', sampled_at: new Date('2025-05-12T09:30').toISOString() },
    })
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
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('leaves the request running')
    fireEvent.click(screen.getByRole('button', { name: 'View pending soil test' }))
    expect(screen.getByRole('button', { name: 'Saving…' })).toBeDisabled()
    expect(screen.getByLabelText('Sample ID')).toHaveValue('S-1')
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    await act(async () => { rejectSave?.(new Error('offline')) })
    expect(screen.getByText(/Save not confirmed: offline/)).toBeInTheDocument()
    expect(screen.getByLabelText('Sample ID')).toHaveValue('S-1')
    expect(screen.getByLabelText('Value')).toHaveValue(7)
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledTimes(2))
    expect(apiPostMock.mock.calls[1][1]).toEqual(apiPostMock.mock.calls[0][1])
    await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  })

  it('keeps acknowledgement distinct from a timeline refresh failure', async () => {
    const onSaved = vi.fn().mockRejectedValue(new Error('History unavailable'))
    render(<SoilTestEntryPanel fieldContextId="field-1" onSaved={onSaved} />)
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    for (const [label, value] of [['Sample ID', 'S-1'], ['Value', '7'], ['Unit on report', 'pH'], ['Lab method', 'water'], ['Depth bottom', '15']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    expect(await screen.findByText(/Saved. Timeline refresh failed/)).toBeInTheDocument()
    expect(screen.queryByText(/Save not confirmed/)).not.toBeInTheDocument()
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    expect(screen.getByLabelText('Value')).toHaveValue(null)
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
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledOnce())
    rerender(<SoilTestEntryPanel key="field-2" fieldContextId="field-2" onSaved={onSaved} />)
    await act(async () => { resolveSave?.(testReceipt(apiPostMock.mock.calls[0][0], apiPostMock.mock.calls[0][1], 'old-field-event')) })
    expect(onSaved).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    expect(screen.getByLabelText('Sample ID')).toHaveValue('')
  })
  it('reconciles the saved soil receipt when parent refresh replaces the callback during scope lookup', async () => {
    apiGetMock.mockImplementation(async (path: string) => {
      await new Promise(resolve => setTimeout(resolve, 10))
      return testScope(path.split('/')[4])
    })
    apiPostMock.mockRejectedValueOnce(new Error('lost'))
    const onSaved = vi.fn()
    function Parent() {
      const [revision, setRevision] = useState(0)
      return <>
        <SoilTestEntryPanel fieldContextId="field-1" onSaved={() => onSaved(revision)} />
        <FieldEventRecoveryPanel fieldContextId="field-1" onRecovered={() => setRevision(n => n + 1)} />
      </>
    }
    render(<Parent />)
    fireEvent.click(screen.getByRole('button', { name: 'Add soil test' }))
    for (const [label, value] of [['Sample ID', 'recovered-soil'], ['Value', '7'], ['Unit on report', 'pH'], ['Lab method', 'water'], ['Depth bottom', '15']]) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } })
    }
    fireEvent.submit(screen.getByRole('form', { name: 'Add structured soil-test result' }))
    await screen.findByText(/Save not confirmed: lost/)
    fireEvent.click(await screen.findByRole('button', { name: 'Retry saved record' }))
    await screen.findByText('Saved record confirmed.')
    await waitFor(() => expect(screen.getByLabelText('Value')).toHaveValue(null))
    expect(onSaved).toHaveBeenCalledOnce()
  })

})
