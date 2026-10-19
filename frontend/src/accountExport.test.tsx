import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import OpenAgronomyInfoPages from './OpenAgronomyInfoPages'

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('account export', () => {
  it('downloads a valid authenticated export without navigating away', async () => {
    const payload = { schema_version: 'phase6.account_data_export.v1', user: { id: 'synthetic' }, workspaces: [] }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => payload }))
    const create = vi.fn().mockReturnValue('blob:synthetic')
    const revoke = vi.fn()
    vi.stubGlobal('URL', class extends URL { static createObjectURL = create; static revokeObjectURL = revoke })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    render(<OpenAgronomyInfoPages page="privacy" />)
    fireEvent.click(screen.getByRole('button', { name: 'Account data export' }))
    expect(await screen.findByRole('status')).toHaveTextContent('Account data downloaded')
    expect(fetch).toHaveBeenCalledWith('/account/export', { cache: 'no-store' })
    expect(create).toHaveBeenCalledWith(expect.any(Blob))
    expect(click).toHaveBeenCalledOnce()
    expect((click.mock.instances[0] as HTMLAnchorElement).download).toMatch(/^open-agronomy-account-.*\.json$/)
    expect(revoke).toHaveBeenCalledWith('blob:synthetic')
    expect(screen.getByRole('heading', { name: 'Data use boundary for the public demo' })).toBeVisible()
  })

  it.each([
    { status: 401, ok: false, json: async () => ({}), message: 'requires a signed-in account' },
    { status: 503, ok: false, json: async () => ({}), message: 'could not be prepared' },
    { status: 200, ok: true, json: async () => ({ schema_version: 'wrong' }), message: 'did not return an account export' },
  ])('reports export failures in place without a bogus download', async response => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    render(<OpenAgronomyInfoPages page="privacy" />)
    fireEvent.click(screen.getByRole('button', { name: 'Account data export' }))
    expect(await screen.findByRole('status')).toHaveTextContent(response.message)
    expect(click).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Account data export' })).toBeEnabled()
  })
})
