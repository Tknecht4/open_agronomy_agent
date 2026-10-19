import { Component, lazy, useState, type ComponentProps, type ComponentType, type ReactNode } from 'react'
import { WorkspaceRecoveryActions } from './WorkspaceRecovery'

export class WorkspaceSectionBoundary extends Component<{
  children: ReactNode
  label: string
  onRetry?: () => void
}, { error: Error | null }> {
  state: { error: Error | null } = { error: null }
  static getDerivedStateFromError(error: unknown) {
    return { error: error instanceof Error ? error : new Error('The view could not be opened.') }
  }
  render() {
    if (!this.state.error) return this.props.children
    return <section className="workspace-section-recovery" role="alert" aria-label={`${this.props.label} unavailable`}>
      <h3>{this.props.label} is unavailable.</h3>
      <p>You can keep using the other workspace views. Your question and field details have not been cleared. If retry still fails, check the connection and reload below.</p>
      <button type="button" className="secondary-button" onClick={() => {
        this.props.onRetry?.()
        this.setState({ error: null })
      }}>Retry {this.props.label.toLowerCase()}</button>
      <WorkspaceRecoveryActions />
      <details><summary>Browser error details</summary><p>{this.state.error.message}</p></details>
    </section>
  }
}

/** React.lazy remembers rejected imports. Recreate it on an explicit panel retry. */
export function recoverableLazy<T extends ComponentType<any>>(
  load: () => Promise<{ default: T }>,
  label: string,
) {
  // The initial type must survive an initial Suspense render being discarded.
  const InitialPanel = lazy(load)
  return function RecoverablePanel(props: ComponentProps<T>) {
    const [attempt, setAttempt] = useState(0)
    const [Panel, setPanel] = useState(() => InitialPanel)
    const RenderPanel = Panel as ComponentType<ComponentProps<T>>
    return <WorkspaceSectionBoundary key={attempt} label={label} onRetry={() => {
      setPanel(() => lazy(load))
      setAttempt(value => value + 1)
    }}>
      <RenderPanel {...props} />
    </WorkspaceSectionBoundary>
  }
}
