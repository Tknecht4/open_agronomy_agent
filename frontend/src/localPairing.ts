export type LocalPairingResult =
  | { attempted: false; paired: false }
  | { attempted: true; paired: true }

type PairingEnvironment = {
  location?: Location
  history?: History
  fetchImpl?: typeof fetch
}

export async function consumeLocalPairingFragment(
  environment: PairingEnvironment = {},
): Promise<LocalPairingResult> {
  const location = environment.location || window.location
  const history = environment.history || window.history
  const fetchImpl = environment.fetchImpl || window.fetch.bind(window)
  const parameters = new URLSearchParams(location.hash.replace(/^#/, ''))
  const token = parameters.get('pair')?.trim()
  if (!token) return { attempted: false, paired: false }

  history.replaceState(null, '', `${location.pathname}${location.search}`)
  const response = await fetchImpl('/auth/local-pair', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(`This device could not be paired (${response.status}). ${detail}`)
  }
  return { attempted: true, paired: true }
}
