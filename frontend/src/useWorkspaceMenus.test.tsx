import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { useWorkspaceMenus } from './useWorkspaceMenus'

function Menus({ page = 'workspace' }: { page?: string }) {
  useWorkspaceMenus(page)
  return <><details data-workspace-menu><summary>Settings</summary><button>Model</button></details><button>Next action</button></>
}
describe('workspace menus', () => {
  it('keeps interactions inside the menu open and closes on an outside pointer', () => {
    render(<Menus />)
    const summary = screen.getByText('Settings')
    fireEvent.click(summary)
    fireEvent.pointerDown(screen.getByText('Model'))
    expect(summary.closest('details')).toHaveAttribute('open')
    fireEvent.pointerDown(screen.getByText('Next action'))
    expect(summary.closest('details')).not.toHaveAttribute('open')
  })
  it('returns keyboard focus to the disclosure on Escape', () => {
    render(<Menus />)
    const summary = screen.getByText('Settings')
    fireEvent.click(summary)
    screen.getByText('Model').focus()
    fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
    expect(summary).toHaveFocus()
    expect(summary.closest('details')).not.toHaveAttribute('open')
  })
  it('does not resurrect a menu when returning to another view', () => {
    const { rerender } = render(<Menus />)
    fireEvent.click(screen.getByText('Settings'))
    rerender(<Menus page="fields" />)
    expect(screen.getByText('Settings').closest('details')).not.toHaveAttribute('open')
  })
})
