import { useEffect, useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

/** Native modal semantics provide focus containment, Escape and focus restoration. */
export function WorkspaceDialog({ title, onClose, children, busy = false, wide = false }: {
  title: string; onClose: () => void; children: ReactNode; busy?: boolean; wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
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
  return <dialog ref={ref} aria-labelledby={titleId} className={`workspace-dialog ${wide ? 'wide' : ''}`}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <header className="dialog-heading"><h2 id={titleId}>{title}</h2>
      <button type="button" className="icon-button" aria-label={`Close ${title}`} onClick={onClose} disabled={busy}><X size={20} /></button>
    </header>
    {children}
  </dialog>
}
