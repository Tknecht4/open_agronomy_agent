import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import OfflineTerrainContextPanel from './OfflineTerrainContextPanel'

afterEach(() => vi.unstubAllGlobals())

it('explains missing local terrain setup after an explicit availability check', async () => {
  const request = vi.fn(async () => new Response(JSON.stringify({ detail: {
    status: 'source_index_not_prepared', message: 'Prepare the verified index.',
  } }), { status: 503 }))
  vi.stubGlobal('fetch', request)
  render(<OfflineTerrainContextPanel id="synthetic-field" m="account_workspace" k="polygon" area="Quebec" />)
  expect(request).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('Offline terrain context'))
  fireEvent.click(screen.getByRole('button', { name: 'Check saved field' }))
  expect(await screen.findByText(/Terrain data needs setup on this device/)).toBeInTheDocument()
  expect(request).toHaveBeenCalledTimes(1)
})
