import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { QuestionContextSummary } from './QuestionContextSummary'

const defaults = { kind: 'saved' as const, crop: 'Wheat', region: '', geometry: { kind: 'none' as const }, edited: false, requiresSave: false, editingLocation: false, onOpenField: vi.fn() }

describe('context for the next question', () => {
  it('keeps a general question usable without implying field facts', () => {
    render(<QuestionContextSummary {...defaults} kind="general" crop="" />)
    expect(screen.getByText('General question')).toBeVisible()
    expect(screen.getByText('No field attached')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Review field details' })).not.toBeInTheDocument()
  })

  it('shows missing location immediately and reveals unknown region and provenance on demand', () => {
    const review = vi.fn()
    render(<QuestionContextSummary {...defaults} onOpenField={review} />)
    expect(screen.getByText('Wheat · Location unknown')).toBeVisible()
    expect(screen.getByText('Unknown')).not.toBeVisible()
    fireEvent.click(screen.getByText('Saved field selected'))
    expect(screen.getByText('Unknown')).toBeVisible()
    expect(screen.getByText(/mapped context is not a field measurement/)).toBeVisible()
    fireEvent.click(screen.getByRole('button', { name: 'Review field details' }))
    expect(review).toHaveBeenCalledOnce()
  })

  it('keeps unsaved edits visible and describes the location actually used by questions', () => {
    render(<QuestionContextSummary {...defaults} geometry={{ kind: 'point', point: { lat: 52, lon: -113 } }} edited requiresSave editingLocation />)
    expect(screen.getByText('Unsaved changes')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Review & save' })).toBeVisible()
    expect(screen.getByText('Save field changes before asking.')).toBeVisible()
    expect(screen.getByText('Wheat · Point location')).toBeVisible()
    fireEvent.click(screen.getByText('Saved field selected'))
    expect(screen.getByText(/Questions use the previous location/)).toBeVisible()
    expect(screen.getByText(/Save them in Fields/)).toBeVisible()
  })

  it('distinguishes illustrative and device-only context from server confirmation', () => {
    const { rerender } = render(<QuestionContextSummary {...defaults} kind="example" />)
    fireEvent.click(screen.getByText('Demonstration inputs'))
    expect(screen.getByText(/not your field record/)).toBeVisible()
    rerender(<QuestionContextSummary {...defaults} kind="device" />)
    expect(screen.getByText('Field on this device')).toBeVisible()
    expect(screen.getByText(/not confirmed in the server workspace/)).toBeVisible()
  })
})
