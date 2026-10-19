import { useEffect, useId, useRef, useState } from 'react'
import { BookOpen, ChartNoAxesCombined, Database, MapPin, Menu, MessageSquareText, Sprout } from 'lucide-react'
import type { FieldAnswerCapability } from './fieldRuntimeAvailability'
import { WorkspaceDialog } from './WorkspaceDialog'

export type WorkspacePage = 'analyze' | 'fields' | 'evidence' | 'benchmarks' | 'sources' | 'privacy' | 'about'

export function WorkspaceNavigation({ page, onNavigate, answerCapability, mobile }: {
  page: WorkspacePage
  onNavigate: (page: WorkspacePage) => void
  answerCapability: FieldAnswerCapability
  mobile: boolean
}) {
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const drawerId = useId()
  useEffect(() => { setOpen(false) }, [page, mobile])
  const primaryItems = [
    ['analyze', 'Workspace', MessageSquareText],
    ['fields', 'Fields', MapPin],
    ['sources', 'Data', Database],
  ] as const
  const reviewItems = [
    ['evidence', 'Evidence', BookOpen],
    ['benchmarks', 'Benchmarks', ChartNoAxesCombined],
  ] as const
  const choose = (next: WorkspacePage) => { onNavigate(next); setOpen(false) }
  const brand = <div className="workspace-brand"><span className="workspace-brand-symbol"><Sprout size={22} aria-hidden="true" /></span><span>Open Agronomy<small>Field workspace</small></span></div>
  const navigation = <>
    <nav className="workspace-navigation" aria-label="Primary">
      {primaryItems.map(([id, label, Icon]) => <button key={id} type="button" aria-current={page === id ? 'page' : undefined} onClick={() => choose(id)}><Icon size={18} aria-hidden="true" />{label}</button>)}
    </nav>
    <div className="workspace-navigation-label">Review</div>
    <nav className="workspace-navigation" aria-label="Review">
      {reviewItems.map(([id, label, Icon]) => <button key={id} type="button" aria-current={page === id ? 'page' : undefined} onClick={() => choose(id)}><Icon size={18} aria-hidden="true" />{label}</button>)}
    </nav>
    <footer className="workspace-navigation-footer">
      <div className={`workspace-runtime-state ${answerCapability.state}`}><span className="runtime-state-dot" aria-hidden="true" /><span>{answerCapability.badge}</span></div>
      <nav className="workspace-information" aria-label="Information">{([['privacy', 'Privacy'], ['about', 'About']] as const).map(([id, label]) => <button key={id} type="button" aria-current={page === id ? 'page' : undefined} onClick={() => choose(id)}>{label}</button>)}</nav>
    </footer>
  </>

  return <>
    <aside className="workspace-sidebar" aria-label="Sidebar">{brand}{navigation}</aside>
    <header className="workspace-mobile-header">
      <button ref={trigger} type="button" className="workspace-menu-trigger" aria-label="Open navigation" aria-haspopup="dialog" aria-controls={drawerId} aria-expanded={open} onClick={() => setOpen(true)}><Menu size={21} aria-hidden="true" /></button>
      {brand}
    </header>
    {mobile && open ? <WorkspaceDialog title="Navigation" id={drawerId} className="navigation-drawer" returnFocusRef={trigger} containFocus onClose={() => setOpen(false)}><div className="navigation-drawer-content">{navigation}</div></WorkspaceDialog> : null}
  </>
}
