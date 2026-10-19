import { Component, type ReactNode } from 'react'
import { WorkspaceRecoveryActions } from './WorkspaceRecovery'

export class WorkspaceErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() {
    if (!this.state.failed) return this.props.children
    return <main className="workspace-recovery" role="alert">
      <h1>The workspace could not be displayed.</h1>
      <p>Your saved fields and answers remain on the local server. Question drafts remain in this browser.</p>
      <WorkspaceRecoveryActions />
      <p>If this repeats, share the browser error with the project maintainer. Avoid clearing browser storage while recovering a draft.</p>
    </main>
  }
}
