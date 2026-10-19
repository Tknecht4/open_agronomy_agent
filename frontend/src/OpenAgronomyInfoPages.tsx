import { useState } from 'react'

const dataBoundaries = [
  {
    title: 'Field and account data',
    body:
      'Drawn and uploaded fields, field notes, identity, conversations, answers, and traces are private workspace data. Exact geometry stays in the field record and is omitted from operational answer traces and ordinary thread exports.',
  },
  {
    title: 'Reviewer exports',
    body:
      'Review exports are meant for human demo QA. They include the visible answer, field context, retrieved evidence names, map evidence, and public source checks, while excluding raw internal prompt messages and hidden checklist material.',
  },
  {
    title: 'Training boundary',
    body:
      'User data is excluded from training by default. A training candidate requires explicit account and thread eligibility, per-feedback consent, and human review. Official AI AgriBench prompts never enter RAG, KG, screenshots, docs, or training artifacts.',
  },
  {
    title: 'Public sources',
    body:
      'Public soil, weather, crop-cover, pesticide-label, irrigation, and regional source cards provide context for decision support. They are not field truth, legal label interpretation, or an agronomist replacement.',
  },
  {
    title: 'Telemetry and storage',
    body:
      'Telemetry is disabled by default and must never contain raw questions, answers, field notes, geometry, or uploads. Local SQLite is not application-encrypted: the operator must use FileVault or equivalent disk encryption and private file permissions.',
  },
]

function PrivacyPage() {
  const [exporting, setExporting] = useState(false)
  const [exportStatus, setExportStatus] = useState('')
  const exportAccount = async () => {
    setExporting(true)
    setExportStatus('')
    try {
      const response = await fetch('/account/export', { cache: 'no-store' })
      if (response.status === 401) throw new Error('Account export requires a signed-in account. Your local field records have not changed.')
      if (!response.ok) throw new Error('Account export could not be prepared. Try again when the server is available.')
      const payload = await response.json()
      if (payload?.schema_version !== 'phase6.account_data_export.v1') throw new Error('The server did not return an account export. Check the server connection and try again.')
      const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }))
      const link = document.createElement('a')
      link.href = url
      link.download = `open-agronomy-account-${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setExportStatus('Account data downloaded. Keep this file private.')
    } catch (error) {
      setExportStatus(error instanceof Error ? error.message : 'Account export is unavailable. Try again when the server is available.')
    } finally {
      setExporting(false)
    }
  }
  return (
    <div className="privacy-page">
      <section className="privacy-hero">
        <div className="panel-kicker">Privacy</div>
        <h2>Data use boundary for the public demo</h2>
        <p>
          Open Agronomy Agent is being prepared for public testing with a conservative data posture: user fields and
          conversations stay scoped to the workspace, reviewer exports are explicit, and hidden benchmark material is
          kept out of public artifacts and training paths.
        </p>
      </section>
      <section className="privacy-grid">
        {dataBoundaries.map((item) => (
          <article key={item.title}>
            <strong>{item.title}</strong>
            <p>{item.body}</p>
          </article>
        ))}
      </section>
      <section className="privacy-flow">
        <h2>What leaves the device</h2>
        <div>
          <article>
            <span>Offline mode</span>
            <strong>No public API calls</strong>
            <p>Weather, map, label, and other public adapters are blocked before a request is made. Cached evidence remains available.</p>
          </article>
          <article>
            <span>Online mode</span>
            <strong>Minimum query, traced</strong>
            <p>Online source checks may send coordinates, map bounds, or a field boundary when the adapter needs them. Answer-time checks retain source and status receipts; map browsing also requests imagery and regional layers.</p>
          </article>
          <article>
            <span>Export and review</span>
            <strong>User initiated</strong>
            <p>Exports can contain private workspace data. They are created explicitly and must be handled as private files.</p>
          </article>
        </div>
      </section>
      <section className="privacy-boundary">
        <h2>Before public hosting</h2>
        <p>
          Final hosted retention, organization access, account deletion, and cloud-export policies still need product and
          security review before the internal local demo becomes a public hosted service.
        </p>
        <button type="button" className="manifest-link" disabled={exporting} onClick={() => void exportAccount()}>
          {exporting ? 'Preparing account export…' : 'Account data export'}
        </button>
        {exportStatus ? <p role="status">{exportStatus}</p> : null}
      </section>
    </div>
  )
}

function AboutPage() {
  return (
    <div className="about-page">
      <section>
        <div className="panel-kicker">Open Agronomy Agent</div>
        <h2>An evidence-grounded field workspace</h2>
        <p>
          The product goal is simple: help users ask better agronomy questions by starting from field context,
          retrieving relevant evidence, showing uncertainty, and making missing data obvious.
        </p>
      </section>
      <section>
        <h2>Safety boundary</h2>
        <p>
          This is decision support. It does not replace a local agronomist, current product labels, legal
          authority, crop insurance requirements, or region-specific recommendation systems.
        </p>
      </section>
    </div>
  )
}

export default function OpenAgronomyInfoPages({ page }: { page: 'privacy' | 'about' }) {
  return page === 'privacy' ? <PrivacyPage /> : <AboutPage />
}
