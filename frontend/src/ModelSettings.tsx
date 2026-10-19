import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Settings2, X } from 'lucide-react'
import type { RuntimeAccess } from './fieldRuntimeAvailability'
import { WorkspaceDialog } from './WorkspaceDialog'

export type ModelProfile = {
  id: string
  label: string
  role: 'default' | 'fast' | string
  max_tokens: number
  quality_gate?: string
  local_ready?: boolean
  local_status?: string
  local_detail?: string
}

const modelName = (profile: ModelProfile) => (profile.label || profile.id).split(' · ')[0]

export function ModelSettings({ profiles, modelId, onSelect, runtimeAccess, busy, mobile, viewKey }: {
  profiles: ModelProfile[]
  modelId: string
  onSelect: (id: string) => void
  runtimeAccess: RuntimeAccess
  busy: boolean
  mobile: boolean
  viewKey: string
}) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState<CSSProperties>({})
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLElement>(null)
  const dialogId = useId()
  const headingId = useId()
  const radioName = useId()
  const selected = profiles.find(profile => profile.id === modelId)
  const close = (restoreFocus = true) => { setOpen(false); if (restoreFocus) trigger.current?.focus({ preventScroll: true }) }
  useEffect(() => { setOpen(false) }, [viewKey, mobile])

  useLayoutEffect(() => {
    if (!open || mobile) return
    const composer = trigger.current?.closest('.chat-composer')
    if (!composer) return
    const place = () => {
      const bounds = composer.getBoundingClientRect()
      const width = Math.max(0, Math.min(336, bounds.width - 32, window.innerWidth - 32))
      setPosition({ width, left: Math.max(16, Math.min(bounds.right - width - 16, window.innerWidth - width - 16)), bottom: Math.max(16, window.innerHeight - bounds.top + 12), maxHeight: Math.max(120, bounds.top - 28) })
    }
    place()
    const observer = typeof ResizeObserver === 'function' ? new ResizeObserver(place) : null
    observer?.observe(composer)
    window.addEventListener('resize', place)
    document.addEventListener('scroll', place, true)
    const initial = panel.current?.querySelector<HTMLInputElement>('input:checked:not(:disabled)') || panel.current?.querySelector<HTMLButtonElement>('button')
    initial?.focus({ preventScroll: true })
    return () => { observer?.disconnect(); window.removeEventListener('resize', place); document.removeEventListener('scroll', place, true) }
  }, [open, mobile])

  useEffect(() => {
    if (!open || mobile) return
    const outside = (event: Event) => {
      if (event.target instanceof Node && !panel.current?.contains(event.target) && !trigger.current?.contains(event.target)) close(false)
    }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); close() } }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('focusin', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('focusin', outside); document.removeEventListener('keydown', escape) }
  }, [open, mobile])

  const availability = (profile: ModelProfile) => runtimeAccess === 'checking' ? 'Checking availability'
    : runtimeAccess === 'unavailable' ? 'Status unavailable'
      : profile.local_ready === true ? 'Ready on this device'
        : profile.local_ready === false ? 'Setup required' : 'Availability not reported'
  const choices = <div className="answer-model-content">
    <p className="answer-model-note">Applies to your next question.</p>
    {runtimeAccess !== 'available' ? <p className="answer-model-warning" role="status">{runtimeAccess === 'checking' ? 'Checking the local runtime.' : 'Connect the local runtime to check available models.'} Your question draft is kept.</p> : null}
    {profiles.length ? <fieldset className="answer-model-options"><legend className="sr-only">Choose an answer model</legend>{profiles.map(profile => <label key={profile.id} className="answer-model-option">
      <input type="radio" name={radioName} value={profile.id} checked={modelId === profile.id} disabled={busy || runtimeAccess !== 'available' || profile.local_ready === false} onChange={() => onSelect(profile.id)} />
      <span><strong>{modelName(profile)}</strong><small>{availability(profile)}</small></span>
    </label>)}</fieldset> : <p className="answer-model-empty">No model profiles available. The local runtime supplies the selectable models.</p>}
    {selected?.local_ready === false && selected.local_detail ? <p className="answer-model-warning">{selected.local_detail}</p> : null}
    {selected ? <details className="answer-model-technical"><summary>Technical details<ChevronDown size={15} aria-hidden="true" /></summary><dl>
      <div><dt>Model ID</dt><dd>{selected.id}</dd></div>
      <div><dt>Configured answer limit</dt><dd>{Number.isSafeInteger(selected.max_tokens) && selected.max_tokens > 0 ? `${selected.max_tokens.toLocaleString()} tokens` : 'Not reported'}</dd></div>
      <div><dt>Profile</dt><dd>{selected.label || selected.id} · {typeof selected.role === 'string' ? selected.role.replace(/_/g, ' ') : 'Not reported'}</dd></div>
    </dl></details> : null}
  </div>

  return <>
    <button ref={trigger} type="button" className="model-settings-trigger" aria-label="Model settings" aria-haspopup="dialog" aria-controls={open ? dialogId : undefined} aria-expanded={open} onClick={() => setOpen(value => !value)}><Settings2 size={17} aria-hidden="true" /><span>Model</span>{selected ? <span className="model-settings-selected">· {modelName(selected)}</span> : null}<ChevronDown size={14} aria-hidden="true" /></button>
    {open && mobile ? createPortal(<WorkspaceDialog title="Answer model" id={dialogId} className="answer-model-sheet" returnFocusRef={trigger} containFocus onClose={() => close(false)}>{choices}<div className="answer-model-sheet-footer"><button type="button" className="primary-button" onClick={() => close(false)}>Done</button></div></WorkspaceDialog>, document.body) : null}
    {open && !mobile ? createPortal(<section ref={panel} id={dialogId} role="dialog" aria-labelledby={headingId} className="answer-model-popover" style={position}><header><h2 id={headingId}>Answer model</h2><button type="button" className="answer-model-close" aria-label="Close model settings" onClick={() => close()}><X size={18} aria-hidden="true" /></button></header>{choices}</section>, document.body) : null}
  </>
}
