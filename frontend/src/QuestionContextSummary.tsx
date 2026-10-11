import type { FieldGeometry } from './fieldGeometry'

export type QuestionContextKind = 'general' | 'saved' | 'device' | 'example' | 'temporary'

/** Describes visible request inputs, never calculator readiness or field authority. */
export function QuestionContextSummary({ kind, crop, region, geometry, edited, requiresSave, editingLocation, onOpenField }: {
  kind: QuestionContextKind
  crop: string
  region: string
  geometry: FieldGeometry
  edited: boolean
  requiresSave: boolean
  editingLocation: boolean
  onOpenField: () => void
}) {
  const source = kind === 'saved' ? 'Saved field selected' : kind === 'device' ? 'Field on this device'
    : kind === 'example' ? 'Demonstration inputs' : kind === 'temporary' ? 'Temporary context' : 'General question'
  const location = geometry.kind === 'none' ? 'Location unknown'
    : geometry.kind === 'point' ? 'Point location' : 'Boundary · area estimate'

  return (
    <><details className="question-context" aria-label="Context for next question">
      <summary>
        <span className="question-context-target">Next question</span>
        <span>{source}</span>
        <small>{kind === 'general' ? 'No field attached' : `${crop || 'Crop unknown'} · ${location}`}</small>
        {edited || editingLocation ? <strong>Unsaved changes</strong> : null}
      </summary>
      <div className="question-context-body">
        {kind === 'general' ? <p>Ask a general question, or select a field above to include its context.</p> : <>
          <dl>
            <div><dt>Crop</dt><dd>{crop || 'Unknown'}</dd></div>
            <div><dt>Region</dt><dd>{region || 'Unknown'}</dd></div>
            <div><dt>Location</dt><dd>{location}</dd></div>
          </dl>
          <p>{requiresSave ? 'Save these changed field details before asking.' : 'These are question inputs.'} Field records and mapped sources are checked separately; mapped context is not a field measurement.</p>
          {edited ? <p>Current details have unsaved changes. Save them in Fields to update the field record.</p> : null}
          {editingLocation ? <p>Map edits are not saved. Questions use the previous location until you save the edit.</p> : null}
          {kind === 'device' ? <p>This field is stored on this device; it is not confirmed in the server workspace.</p> : null}
          {kind === 'example' ? <p>Demonstration data is illustrative and is not your field record.</p> : null}
          <button type="button" className="text-button" onClick={onOpenField}>Review field details</button>
        </>}
      </div>
    </details>
    {requiresSave ? <div className="question-context-save" role="status">
      <span>Save field changes before asking.</span>
      <button type="button" className="secondary-button" onClick={onOpenField}>Review & save</button>
    </div> : null}</>
  )
}
