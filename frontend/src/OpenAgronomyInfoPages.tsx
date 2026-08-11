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
            <p>Explicit public adapters receive only the query and generalized location they need; each attempted call is attached to the answer trace.</p>
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
        <a className="manifest-link" href="/account/export">
          Account data export
        </a>
      </section>
    </div>
  )
}

function AboutPage() {
  return (
    <div className="about-page">
      <section>
        <div className="panel-kicker">Open Agronomy Agent</div>
        <h2>A map-first assistant for agronomy questions</h2>
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
