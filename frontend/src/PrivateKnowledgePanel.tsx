import { useState } from 'react'
import { Eraser, Upload } from 'lucide-react'
import { apiUpload } from './api'
import './PrivateKnowledgePanel.css'

export type PrivateKnowledgeDoc = {
  doc_id: string
  title: string
  text: string
  source: string
  source_id: string
  source_type: 'user_upload_private'
  score: number
  tags: string[]
  jurisdictions: string[]
  languages: string[]
  retrieval_policy: 'context_only'
  content_risk_tags: string[]
  license_status: string
  raw_sha256: string
  chunk_sha256: string
  visibility: 'ephemeral_browser_session'
  chunk_index: number
  training_eligible: false
  retrieval_method: string
}

export type PrivateKnowledgeInspection = {
  schema_version: string
  filename: string
  content_type: string
  raw_sha256: string
  parse_status: 'ready' | 'blocked'
  persisted: false
  training_eligible: false
  retrieval_policy: 'context_only'
  quality_flags: string[]
  chunks: PrivateKnowledgeDoc[]
  boundary: string
}

export default function PrivateKnowledgePanel({
  privateKnowledge,
  onAdded,
  onClear,
}: {
  privateKnowledge: PrivateKnowledgeInspection[]
  onAdded: (inspection: PrivateKnowledgeInspection) => void
  onClear: () => void
}) {
  const [status, setStatus] = useState('No private reference loaded.')
  const [busy, setBusy] = useState(false)

  const inspect = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setStatus(`Inspecting ${file.name} on this device`)
    try {
      const form = new FormData()
      form.append('file', file)
      const result = await apiUpload<PrivateKnowledgeInspection>('/api/private-knowledge/inspect', form)
      if (result.parse_status !== 'ready' || !result.chunks.length) {
        setStatus(result.boundary || 'The document could not be loaded.')
        return
      }
      onAdded(result)
      setStatus(`${result.filename}: ${result.chunks.length} context-only excerpts ready for this browser session.`)
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Private reference inspection failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="source-private-knowledge">
      <div>
        <div className="panel-kicker">Private local references</div>
        <h2>Use your own document without adding it to the public corpus</h2>
        <p>
          PDF, text, Markdown, or JSON stays in browser memory as unverified context. It cannot authorize a pesticide,
          set a rate, confirm a diagnosis, enter training, or override current official authority.
        </p>
        <p>Document text is excluded from saved prompts and retrieval traces; answers may paraphrase it in field history.</p>
      </div>
      <div className="source-private-actions">
        <label>
          <Upload size={17} />
          {busy ? 'Inspecting' : 'Choose private reference'}
          <input
            type="file"
            accept=".pdf,.txt,.md,.json,application/pdf,text/plain,text/markdown,application/json"
            disabled={busy}
            onChange={(event) => {
              void inspect(event.target.files?.[0])
              event.currentTarget.value = ''
            }}
          />
        </label>
        <button type="button" onClick={onClear} disabled={!privateKnowledge.length}>
          <Eraser size={16} /> Clear session references
        </button>
        <small>{status}</small>
      </div>
      {privateKnowledge.length ? (
        <div className="source-private-list">
          {privateKnowledge.map((item) => (
            <article key={item.raw_sha256}>
              <strong>{item.filename}</strong>
              <span>{item.chunks.length} excerpts · context only · not persisted</span>
              <small>SHA-256 {item.raw_sha256}</small>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  )
}
