import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { FieldSetupDialog, importedFieldGeometry, type NewFieldDraft } from './FieldSetupDialog'
import { WorkspaceDialog } from './WorkspaceDialog'
import { apiUpload } from './api'

vi.mock('./api', () => ({ apiUpload: vi.fn() }))
vi.mock('./LeafletFieldMap', () => ({
  LeafletFieldMap: ({ geometry, mode, onGeometryChange }: { geometry: { kind: string; point?: { lon: number }; points?: Array<{ lon: number }> }; mode: string; onGeometryChange: (value: unknown) => void }) =>
    <div data-testid="mock-map" data-kind={geometry.kind} data-lon={geometry.kind === 'point' ? geometry.point?.lon : geometry.points?.[0]?.lon}>
      <button type="button" disabled={mode !== 'point'} onClick={() => onGeometryChange({ kind: 'point', point: { lat: 53.3, lon: -113.6 } })}>Set map point</button>
    </div>,
}))

const uploadMock = vi.mocked(apiUpload)
const openWizard = (onSave: (draft: NewFieldDraft) => Promise<void> = vi.fn().mockResolvedValue(undefined), onClose = vi.fn()) => {
  render(<FieldSetupDialog onSave={onSave} onClose={onClose} allowNetwork={false} />)
  return { onSave, onClose }
}
const moveToLocation = () => {
  fireEvent.change(screen.getByLabelText('Field name'), { target: { value: 'North field' } })
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
}
const polygon = (west: number) => ({ type: 'Polygon', coordinates: [[[west, 53.3], [west + 0.01, 53.3], [west + 0.01, 53.31], [west, 53.3]]] })
const uploadPayload = (geometry: any) => ({
  schema_version: 'boundary-upload-v1', filename: 'fields.geojson', source_format: 'geojson', feature_count: 1,
  selected_feature_id: 'feature-a', geometry, geometry_type: geometry.type,
  feature_collection: { type: 'FeatureCollection', features: [{ type: 'Feature', id: 'feature-a', geometry, properties: {} }] },
  feature_summaries: [{ id: 'feature-a', label: 'North', geometry_type: geometry.type, acres: 10, selected: true, bbox: [], properties: {} }],
})

beforeEach(() => { uploadMock.mockReset() })
afterEach(() => { vi.clearAllMocks() })

describe('new field setup', () => {
  it('saves an explicitly data-only field with unknown location', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    openWizard(onSave)
    moveToLocation()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'No location yet · data only' }))
    expect(screen.queryByTestId('mock-map')).not.toBeInTheDocument()
    expect(screen.getByText(/map context and imagery require a valid location/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('Unknown · data only')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ name: 'North field', geometry: { kind: 'none' }, acres: '' })))
  })

  it('clears an earlier point when choosing data-only and requires a new point when switching back', async () => {
    openWizard()
    moveToLocation()
    fireEvent.click(await screen.findByRole('button', { name: 'Set map point' }))
    fireEvent.click(screen.getByRole('button', { name: 'No location yet · data only' }))
    fireEvent.click(screen.getByRole('button', { name: 'Place a pin' }))
    expect(screen.getByTestId('mock-map')).toHaveAttribute('data-kind', 'none')
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('requires a name, retains free-form crop and jurisdiction, and accepts zero coordinates', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    openWizard(onSave)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Field name'), { target: { value: 'Equator plot' } })
    fireEvent.change(screen.getByLabelText(/Crop/), { target: { value: 'Experimental crop' } })
    fireEvent.click(screen.getByText(/Region & province/))
    fireEvent.change(screen.getByLabelText('Province / jurisdiction'), { target: { value: 'Unconfirmed jurisdiction' } })
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByText('Enter coordinates instead'))
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }))
    expect(await screen.findByTestId('mock-map')).toHaveAttribute('data-kind', 'point')
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    expect(screen.getByText('Experimental crop')).toBeInTheDocument()
    expect(screen.getByText('Unconfirmed jurisdiction')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    expect(onSave.mock.calls[0][0]).toMatchObject({ name: 'Equator plot', crop: 'Experimental crop', jurisdiction: 'Unconfirmed jurisdiction', geometry: { kind: 'point', point: { lat: 0, lon: 0 } } })
  })

  it('rejects blank, ambiguous, and out-of-range coordinates without advancing', () => {
    openWizard()
    moveToLocation()
    fireEvent.click(screen.getByText('Enter coordinates instead'))
    fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/latitude between/)
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '0x10' } })
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '-113.6' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/latitude between/)
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '91' } })
    fireEvent.click(screen.getByRole('button', { name: 'Use coordinates' }))
    expect(screen.getByRole('alert')).toHaveTextContent(/latitude between/)
    expect(screen.getByTestId('mock-map')).toHaveAttribute('data-kind', 'none')
  })

  it('confirms draft loss on cancel and never calls save', () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    const onClose = vi.fn()
    openWizard(onSave, onClose)
    fireEvent.change(screen.getByLabelText('Field name'), { target: { value: 'Draft name' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onClose).not.toHaveBeenCalled()
    expect(screen.getByRole('alertdialog', { name: 'Discard field draft?' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Keep editing' }))
    expect(screen.getByLabelText('Field name')).toHaveValue('Draft name')
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }))
    fireEvent.click(screen.getByRole('button', { name: 'Discard draft' }))
    expect(onClose).toHaveBeenCalledOnce()
    expect(onSave).not.toHaveBeenCalled()
  })

  it('retains the draft after a failed save and retries the same values', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('Server unavailable')).mockResolvedValueOnce(undefined)
    openWizard(onSave)
    moveToLocation()
    fireEvent.click(await screen.findByRole('button', { name: 'Set map point' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Server unavailable')
    expect(screen.getByText('North field')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2))
    expect(onSave.mock.calls[1][0]).toEqual(onSave.mock.calls[0][0])
  })

  it('selects uploaded features by stable ID, even if summaries are in another order', async () => {
    const a = polygon(-113.6)
    const b = polygon(-114.2)
    uploadMock.mockResolvedValueOnce({
      ...uploadPayload(b), feature_count: 2, selected_feature_id: 'feature-b',
      feature_collection: { type: 'FeatureCollection', features: [
        { type: 'Feature', id: 'feature-b', geometry: b, properties: {} },
        { type: 'Feature', id: 'feature-a', geometry: a, properties: {} },
      ] },
      feature_summaries: [
        { id: 'feature-a', label: 'East field', geometry_type: 'Polygon', acres: 10 },
        { id: 'feature-b', label: 'West field', geometry_type: 'Polygon', acres: 10 },
      ],
    } as never)
    openWizard()
    moveToLocation()
    fireEvent.change(screen.getByLabelText('Import field boundary'), { target: { files: [new File(['{}'], 'fields.geojson', { type: 'application/json' })] } })
    expect(await screen.findByTestId('mock-map')).toHaveAttribute('data-lon', '-114.2')
    fireEvent.change(screen.getByLabelText('Field in this file'), { target: { value: 'feature-a' } })
    expect(screen.getByTestId('mock-map')).toHaveAttribute('data-lon', '-113.6')
  })

  it('rejects holes and multipart geometry without converting them to a different field', async () => {
    const exterior = polygon(-113.6).coordinates[0]
    expect(() => importedFieldGeometry({ type: 'Polygon', coordinates: [exterior, polygon(-113.59).coordinates[0]] })).toThrow(/holes/i)
    expect(() => importedFieldGeometry({ type: 'MultiPolygon', coordinates: [[exterior], [polygon(-114).coordinates[0]]] })).toThrow(/Multipart/i)
    uploadMock.mockResolvedValueOnce(uploadPayload({ type: 'MultiPolygon', coordinates: [[exterior], [polygon(-114).coordinates[0]]] }) as never)
    openWizard()
    moveToLocation()
    fireEvent.change(screen.getByLabelText('Import field boundary'), { target: { files: [new File(['{}'], 'fields.geojson')] } })
    expect(await screen.findByRole('alert')).toHaveTextContent(/Multipart boundaries/i)
    expect(screen.getByTestId('mock-map')).toHaveAttribute('data-kind', 'none')
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('drops upload provenance when the user replaces its boundary with a manual point', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined)
    uploadMock.mockResolvedValueOnce(uploadPayload(polygon(-113.6)) as never)
    openWizard(onSave)
    moveToLocation()
    fireEvent.change(screen.getByLabelText('Import field boundary'), { target: { files: [new File(['{}'], 'fields.geojson')] } })
    expect(await screen.findByText(/Imported from fields.geojson/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Place a pin' }))
    expect(screen.queryByText(/Imported from fields.geojson/)).not.toBeInTheDocument()
    fireEvent.click(await screen.findByRole('button', { name: 'Set map point' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledOnce())
    expect(onSave.mock.calls[0][0]).toMatchObject({ geometry: { kind: 'point' }, notes: '' })
  })

  it('ignores an upload response after its dialog is removed during navigation', async () => {
    let resolveUpload!: (value: any) => void
    uploadMock.mockReturnValueOnce(new Promise(resolve => { resolveUpload = resolve }))
    function Host() {
      const [open, setOpen] = useState(true)
      return <><button type="button" onClick={() => setOpen(false)}>Leave page</button>{open ? <FieldSetupDialog onSave={vi.fn()} onClose={() => setOpen(false)} allowNetwork={false} /> : null}</>
    }
    render(<Host />)
    moveToLocation()
    fireEvent.change(screen.getByLabelText('Import field boundary'), { target: { files: [new File(['{}'], 'fields.geojson')] } })
    expect(await screen.findByRole('button', { name: 'Set map point' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Leave page' }))
    resolveUpload(uploadPayload(polygon(-113.6)))
    await waitFor(() => expect(screen.queryByText(/Imported from fields.geojson/)).not.toBeInTheDocument())
  })

  it('completes an upload after StrictMode replays mount effects', async () => {
    uploadMock.mockResolvedValueOnce(uploadPayload(polygon(-113.6)) as never)
    render(<StrictMode><FieldSetupDialog onSave={vi.fn()} onClose={vi.fn()} allowNetwork={false} /></StrictMode>)
    moveToLocation()
    fireEvent.change(screen.getByLabelText('Import field boundary'), { target: { files: [new File(['{}'], 'fields.geojson')] } })
    expect(await screen.findByText(/Imported from fields.geojson/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled()
  })

  it('shows a failed save and unlocks retry after StrictMode replays mount effects', async () => {
    const onSave = vi.fn().mockRejectedValueOnce(new Error('Temporary save failure')).mockResolvedValueOnce(undefined)
    render(<StrictMode><FieldSetupDialog onSave={onSave} onClose={vi.fn()} allowNetwork={false} /></StrictMode>)
    moveToLocation()
    fireEvent.click(await screen.findByRole('button', { name: 'Set map point' }))
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Temporary save failure')
    expect(screen.getByRole('button', { name: 'Save field' })).toBeEnabled()
    fireEvent.click(screen.getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(2))
  })
})

it('restores focus to the opener and routes Escape through the dialog close handler', () => {
  function Host() {
    const [open, setOpen] = useState(false)
    return <><button type="button" onClick={() => setOpen(true)}>Open panel</button>{open ? <WorkspaceDialog title="Test panel" onClose={() => setOpen(false)}><p>Panel body</p></WorkspaceDialog> : null}</>
  }
  render(<Host />)
  const opener = screen.getByRole('button', { name: 'Open panel' })
  opener.focus()
  fireEvent.click(opener)
  expect(screen.getByRole('button', { name: 'Close Test panel' })).toHaveFocus()
  fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: true, cancelable: true }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  expect(opener).toHaveFocus()
})
