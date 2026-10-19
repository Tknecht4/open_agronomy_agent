import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'
import { X } from 'lucide-react'

/** Native modal semantics provide focus containment, Escape and focus restoration. */
export function WorkspaceDialog({ title, onClose, children, busy = false, wide = false, className = '', id, returnFocusRef, containFocus = false }: {
  title: string; onClose: () => void; children: ReactNode; busy?: boolean; wide?: boolean
  className?: string; id?: string; returnFocusRef?: RefObject<HTMLButtonElement | null>; containFocus?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const previous = returnFocusRef?.current || document.activeElement as HTMLElement | null
    const dialog = ref.current
    if (dialog?.showModal) dialog.showModal()
    else dialog?.setAttribute('open', '')
    const initialFocus = dialog?.querySelector<HTMLElement>('[data-dialog-initial-focus]')
      || dialog?.querySelector<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled)')
    initialFocus?.focus()
    return () => {
      if (dialog?.open) dialog.close?.()
      if (previous?.isConnected) previous.focus()
    }
  }, [])
  return <dialog ref={ref} id={id} aria-labelledby={titleId} className={`workspace-dialog ${wide ? 'wide' : ''} ${className}`}
    onKeyDown={(event) => {
      if (!containFocus || event.key !== 'Tab') return
      const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, a[href]'))
        .filter(element => element.getClientRects().length > 0)
      const first = controls[0], last = controls[controls.length - 1]
      if (first && last && event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (first && last && !event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <header className="dialog-heading"><h2 id={titleId}>{title}</h2>
      <button type="button" className="icon-button" aria-label={`Close ${title}`} onClick={onClose} disabled={busy}><X size={20} /></button>
    </header>
    {children}
  </dialog>
}
