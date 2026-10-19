import { useState } from 'react'

/** Probe the current origin. A cached shell is not evidence that its API is running. */
export async function checkWorkspaceConnection(): Promise<void> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 4000)
  try {
    const response = await fetch('/api/health', { cache: 'no-store', signal: controller.signal })
    if (!response.ok || (await response.json()).status !== 'ok') throw new Error('Runtime unavailable')
  } finally {
    window.clearTimeout(timeout)
  }
}

export function WorkspaceRecoveryActions() {
  const [checking, setChecking] = useState(false)
  const [unavailable, setUnavailable] = useState(false)
  const [connected, setConnected] = useState(false)
  const reconnect = async () => {
    setChecking(true)
    setUnavailable(false)
    setConnected(false)
    try {
      await checkWorkspaceConnection()
      setConnected(true)
    } catch {
      setUnavailable(true)
    } finally {
      setChecking(false)
    }
  }
  return <div className="workspace-recovery-actions">
    <p>Server address: <strong>{window.location.origin}</strong>. A cached page can open even when this server is stopped.</p>
    <p>Reconnect or start the server for this address, then retry. If you started a different local address, use the URL printed in its terminal. Browser drafts stay with the address where you entered them; do not clear browser storage.</p>
    <button type="button" className="secondary-button" disabled={checking} onClick={() => void reconnect()}>
      {checking ? 'Checking connection…' : 'Check connection'}
    </button>
    {unavailable ? <p role="status">The server at this address is unavailable. This page has been kept open so you can recover your draft.</p> : null}
    {connected ? <div>
      <p role="status">The server is connected. Reloading closes unsaved field setup, boundary edits, and session-only references. Saved question drafts remain in this browser.</p>
      <button type="button" className="secondary-button" onClick={() => setConnected(false)}>Keep this page open</button>{' '}
      <button type="button" className="secondary-button" onClick={() => window.location.reload()}>Reload workspace</button>
    </div> : null}
  </div>
}
