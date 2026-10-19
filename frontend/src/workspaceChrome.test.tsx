import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { ModelSettings, type ModelProfile } from './ModelSettings'
import { WorkspaceNavigation, type WorkspacePage } from './WorkspaceNavigation'
import { fieldAnswerCapability, type RuntimeAccess } from './fieldRuntimeAvailability'

const profiles: ModelProfile[] = [
  { id: 'model/gemma', label: 'Gemma · offline reference', role: 'default', max_tokens: 640, local_ready: true },
  { id: 'model/qwen', label: 'Qwen', role: 'fast', max_tokens: 35, local_ready: true },
]

function ModelHarness({ mobile = false, runtimeAccess = 'available', models = profiles, busy = false, viewKey = 'workspace' }: {
  mobile?: boolean; runtimeAccess?: RuntimeAccess; models?: ModelProfile[]; busy?: boolean; viewKey?: string
}) {
  const [model, setModel] = useState('model/gemma')
  const [draft, setDraft] = useState('Keep this question')
  return <form className="chat-composer"><textarea aria-label="Question draft" value={draft} onChange={event => setDraft(event.target.value)} /><ModelSettings profiles={models} modelId={model} onSelect={setModel} runtimeAccess={runtimeAccess} mobile={mobile} busy={busy} viewKey={viewKey} /><button type="button">Another action</button></form>
}

describe('workspace model settings', () => {
  it('selects the next answer model, discloses its actual limit, and keeps the draft', () => {
    render(<ModelHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Model settings' }))
    const dialog = screen.getByRole('dialog', { name: 'Answer model' })
    fireEvent.click(within(dialog).getByRole('radio', { name: 'Qwen Ready on this device' }))
    expect(within(dialog).getByRole('radio', { name: 'Qwen Ready on this device' })).toBeChecked()
    fireEvent.click(within(dialog).getByText('Technical details'))
    expect(within(dialog).getByText('model/qwen')).toBeVisible()
    expect(within(dialog).getByText('35 tokens')).toBeVisible()
    expect(screen.getByRole('textbox', { name: 'Question draft' })).toHaveValue('Keep this question')
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Model settings' })).toHaveFocus()
  })

  it('dismisses on an outside pointer without stealing focus from the next action', () => {
    render(<ModelHarness />)
    fireEvent.click(screen.getByRole('button', { name: 'Model settings' }))
    const next = screen.getByRole('button', { name: 'Another action' })
    act(() => next.focus())
    fireEvent.pointerDown(next)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(next).toHaveFocus()
  })

  it('keeps unavailable and unknown availability explicit instead of claiming readiness', () => {
    const { rerender } = render(<ModelHarness models={[{ ...profiles[0], local_ready: undefined, role: undefined as unknown as string, max_tokens: undefined as unknown as number }]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Model settings' }))
    expect(screen.getByRole('radio', { name: 'Gemma Availability not reported' })).toBeInTheDocument()
    fireEvent.click(screen.getByText('Technical details'))
    expect(screen.getByText('Not reported', { exact: true })).toBeVisible()
    rerender(<ModelHarness runtimeAccess="unavailable" />)
    expect(screen.getAllByRole('radio').every(input => (input as HTMLInputElement).disabled)).toBe(true)
    expect(screen.getByText(/Connect the local runtime/)).toBeVisible()
    expect(screen.queryByText('Ready on this device')).not.toBeInTheDocument()
  })

  it('disables setup-required and busy models while retaining their details', () => {
    render(<ModelHarness models={[{ ...profiles[0], local_ready: false, local_detail: 'Download the pinned model first.' }, profiles[1]]} busy />)
    fireEvent.click(screen.getByRole('button', { name: 'Model settings' }))
    expect(screen.getByRole('radio', { name: 'Gemma Setup required' })).toBeDisabled()
    expect(screen.getByRole('radio', { name: 'Qwen Ready on this device' })).toBeDisabled()
    expect(screen.getByText('Download the pinned model first.')).toBeVisible()
  })

  it('uses a mobile dialog with Done, native cancellation, and focus restoration', () => {
    render(<ModelHarness mobile />)
    const trigger = screen.getByRole('button', { name: 'Model settings' })
    fireEvent.click(trigger)
    const sheet = screen.getByRole('dialog', { name: 'Answer model' })
    expect(sheet).toHaveClass('answer-model-sheet')
    const done = within(sheet).getByRole('button', { name: 'Done' })
    const close = within(sheet).getByRole('button', { name: 'Close Answer model' })
    // JSDOM has no layout. Mark the two focus-loop boundaries as rendered.
    Object.defineProperty(done, 'getClientRects', { value: () => [{ width: 44, height: 44 }] })
    Object.defineProperty(close, 'getClientRects', { value: () => [{ width: 44, height: 44 }] })
    act(() => done.focus())
    fireEvent.keyDown(done, { key: 'Tab' })
    expect(close).toHaveFocus()
    fireEvent.keyDown(close, { key: 'Tab', shiftKey: true })
    expect(done).toHaveFocus()
    fireEvent.click(done)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    fireEvent.click(trigger)
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByRole('textbox')).toHaveValue('Keep this question')
  })

  it('closes on a workspace change and explains missing model profiles', () => {
    const { rerender } = render(<ModelHarness models={[]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Model settings' }))
    expect(screen.getByText(/No model profiles available/)).toBeVisible()
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    rerender(<ModelHarness models={[]} viewKey="map" />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

describe('workspace navigation', () => {
  it('keeps review pages visible and information pages together in the desktop footer', () => {
    const navigate = vi.fn()
    render(<WorkspaceNavigation page="evidence" onNavigate={navigate} answerCapability={fieldAnswerCapability('available', 'online')} mobile={false} />)
    const review = screen.getByRole('navigation', { name: 'Review' })
    expect(within(review).getByRole('button', { name: 'Evidence' })).toHaveAttribute('aria-current', 'page')
    fireEvent.click(within(screen.getByRole('navigation', { name: 'Information' })).getByRole('button', { name: 'Privacy' }))
    expect(navigate).toHaveBeenCalledWith('privacy')
  })

  it('closes the mobile drawer after navigation and returns focus to its trigger', () => {
    function NavigationHarness() {
      const [page, setPage] = useState<WorkspacePage>('analyze')
      return <WorkspaceNavigation page={page} onNavigate={setPage} answerCapability={fieldAnswerCapability('unavailable', 'unknown')} mobile />
    }
    render(<NavigationHarness />)
    const trigger = screen.getByRole('button', { name: 'Open navigation' })
    fireEvent.click(trigger)
    const drawer = screen.getByRole('dialog', { name: 'Navigation' })
    expect(within(drawer).getByText('Runtime unavailable · notes only')).toBeVisible()
    fireEvent.click(within(drawer).getByRole('button', { name: 'Fields' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
  })
})
