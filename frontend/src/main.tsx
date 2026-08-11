import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { OpenAgronomyApp } from './OpenAgronomyApp'
import { consumeLocalPairingFragment } from './localPairing'
import { registerPhase6Pwa } from './pwa'
import { installFrontendRum, sendFrontendEvent } from './rum'
import './styles.css'

const rootElement = document.getElementById('root')!
const root = createRoot(rootElement)

const renderApp = () => {
  installFrontendRum()
  registerPhase6Pwa()
  sendFrontendEvent('app_shell_loaded', { pwa_registration_attempted: true })
  root.render(
    <StrictMode>
      <OpenAgronomyApp />
    </StrictMode>,
  )
}

void consumeLocalPairingFragment()
  .then(renderApp)
  .catch((error: unknown) => {
    const message =
      error instanceof Error
        ? error.message
        : 'This pairing link could not be verified. Restart field-LAN mode and use the new one-time link.'
    root.render(
      <StrictMode>
        <main className="pairing-error">
          <h1>Field device pairing failed</h1>
          <p>{message}</p>
        </main>
      </StrictMode>,
    )
  })
