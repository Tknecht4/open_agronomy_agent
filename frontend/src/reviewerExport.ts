import { buildPublicToolCard, buildStructuredEvidenceCard } from './sourceCards'
import { GraphHit, RetrievedDoc, StructuredEvidenceCard, ToolInvocation, Turn } from './types'

export type ReviewerFieldContext = {
  crop?: string
  region?: string
  jurisdiction?: string
  acres?: string
  concern?: string
  notes?: string
  geometrySummary?: string
  regionalContext?: string[]
  sourceBoundary?: string
}

export type ReviewerExportInput = {
  generatedAt: string
  field: ReviewerFieldContext
  turn: Turn
  docs?: RetrievedDoc[]
  graphHits?: GraphHit[]
  publicTools?: ToolInvocation[]
  mapEvidenceCards?: StructuredEvidenceCard[]
}

const line = (label: string, value: unknown): string => {
  const text = typeof value === 'string' ? value.trim() : value === undefined || value === null ? '' : String(value)
  return text ? `- ${label}: ${text}` : ''
}

const section = (title: string, body: string[]): string => {
  const clean = body.filter(Boolean)
  return clean.length ? `\n## ${title}\n\n${clean.join('\n')}\n` : ''
}

const bulletList = (items: string[] | undefined): string[] => (items?.length ? items.map((item) => `- ${item}`) : [])

const codeBlock = (text: string): string => `\n\`\`\`text\n${text.trim() || 'No answer text available.'}\n\`\`\`\n`

const compactJson = (value: unknown): string => JSON.stringify(value, null, 2)

const sourceCardLines = (card: ReturnType<typeof buildPublicToolCard>): string[] => [
  `- ${card.title} (${card.provider})`,
  `  - Status: ${card.statusLabel}`,
  card.facts.length ? `  - Facts: ${card.facts.join('; ')}` : '',
  card.sourceUrl ? `  - Source: ${card.sourceUrl}` : card.sourceLabel ? `  - Source: ${card.sourceLabel}` : '',
  card.links?.length ? `  - Links: ${card.links.map((link) => `${link.label} ${link.url}`).join('; ')}` : '',
  `  - Limitation: ${card.limitation}`,
]

const safeSlug = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 56) || 'field-review'

export const reviewerExportFilename = (turn: Turn, generatedAt: string): string => {
  const date = generatedAt.slice(0, 10) || new Date().toISOString().slice(0, 10)
  return `open-agronomy-agent-review-${date}-${safeSlug(turn.turn_id || turn.user_message || 'turn')}.md`
}

export const buildReviewerExportMarkdown = ({
  generatedAt,
  field,
  turn,
  docs = [],
  graphHits = [],
  publicTools = [],
  mapEvidenceCards = [],
}: ReviewerExportInput): string => {
  const structured = turn.trace?.structured_answer
  const route = turn.trace?.route
  const system = turn.system_state
  const publicCards = publicTools.map(buildPublicToolCard)
  const mapCards = mapEvidenceCards.map(buildStructuredEvidenceCard)
  const missingData = [...(structured?.missing_data || []), ...(structured?.missing_data_prompts || [])]

  return [
    '# Open Agronomy Agent Review Export',
    '',
    'This export is for human demo review and app testing. It is not an official AI AgriBench artifact, label interpretation, field diagnosis, or product/rate recommendation.',
    '',
    line('Generated', generatedAt),
    line('Turn ID', turn.turn_id),
    line('Session ID', turn.session_id),
    section('Field Context', [
      line('Crop', field.crop),
      line('Region', field.region),
      line('Jurisdiction', field.jurisdiction),
      line('Acres', field.acres),
      line('Concern', field.concern),
      line('Notes', field.notes),
      line('Geometry', field.geometrySummary),
      ...(field.regionalContext?.map((item) => `- Regional context: ${item}`) || []),
      field.sourceBoundary ? `- Boundary: ${field.sourceBoundary}` : '',
    ]),
    section('Question', [codeBlock(turn.user_message)]),
    section('Answer', [codeBlock(turn.answer)]),
    section('Missing Data To Review', missingData.length ? bulletList([...new Set(missingData)]) : ['- No structured missing-data prompts were returned.']),
    section(
      'Map Evidence Cards',
      mapCards.length ? mapCards.flatMap(sourceCardLines) : ['- No map evidence cards were visible for this turn.'],
    ),
    section(
      'Public Source Checks',
      publicCards.length ? publicCards.flatMap(sourceCardLines) : ['- No public source checks were visible for this turn.'],
    ),
    section(
      'Retrieved Evidence',
      docs.length
        ? docs.slice(0, 8).map((doc) => `- ${doc.title} (${doc.source_type}; score ${doc.score.toFixed(2)})${doc.source ? ` - ${doc.source}` : ''}`)
        : ['- No retrieved documents were visible for this turn.'],
    ),
    section(
      'Knowledge Graph Hints',
      graphHits.length
        ? graphHits.slice(0, 6).map((hit) => `- ${hit.name} (${hit.kind}) - ${hit.evidence}`)
        : ['- No graph hints were visible for this turn.'],
    ),
    section('Route And Runtime', [
      line('Question type', route?.question_type),
      line('Risk level', route?.risk_level),
      line('Namespaces', route?.namespaces?.join(', ')),
      line('Mode', system?.mode),
      line('Model', [
        system?.model_identity?.status,
        system?.model_identity?.configured_model_id || system?.model_id,
        system?.model_identity?.configured_model_revision?.slice(0, 12),
      ].filter(Boolean).join(' · ')),
      line('RAG config', system?.rag_config),
      line('Latency ms', system?.latency_ms),
    ]),
    section('Answer Integrity Receipt', [
      line('Status', turn.answer_integrity_receipt?.status),
      line('Receipt SHA-256', turn.answer_integrity_receipt?.receipt_sha256),
      line('Answer SHA-256', turn.answer_integrity_receipt?.answer_sha256),
      line('Trace SHA-256', turn.answer_integrity_receipt?.trace_sha256),
      turn.answer_integrity_receipt?.boundary
        ? `- Boundary: ${turn.answer_integrity_receipt.boundary}`
        : '- No persisted answer integrity receipt was captured for this legacy turn.',
    ]),
    section('Reviewer Notes', [
      '- Issue:',
      '- Expected:',
      '- Severity:',
    ]),
    section('Machine-Readable Audit Summary', [
      '```json',
      compactJson({
        turn_id: turn.turn_id,
        answer_status: turn.answer_status,
        route: route
          ? {
              question_type: route.question_type,
              risk_level: route.risk_level,
              namespaces: route.namespaces,
              required_tools: route.required_tools,
            }
          : null,
        source_counts: {
          retrieved_docs: docs.length,
          graph_hits: graphHits.length,
          public_tool_checks: publicTools.length,
          map_evidence_cards: mapEvidenceCards.length,
        },
        coverage: turn.knowledge_coverage,
        answer_integrity_receipt: turn.answer_integrity_receipt,
        boundaries: {
          official_ai_agribench: false,
          raw_prompt_messages_excluded: true,
          internal_coverage_checklist_excluded: true,
        },
      }),
      '```',
    ]),
  ].join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}
