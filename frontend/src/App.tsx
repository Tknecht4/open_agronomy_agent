import { FormEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from 'react'
import { apiGet, apiPatch, apiPost } from './api'
import { clearPhase6ChatDraft, loadPhase6ChatDraft, savePhase6ChatDraft } from './offlineDrafts'
import { clearPhase6Scratchpad, loadPhase6Scratchpad, savePhase6Scratchpad } from './offlineScratchpad'
import { SessionRecord, SessionStatus, Turn } from './types'

const HostedPlatform = lazy(() => import('./HostedPlatform').then((module) => ({ default: module.HostedPlatform })))
const PublicDemoPages = lazy(() => import('./PublicDemoPages').then((module) => ({ default: module.PublicDemoPages })))

type DataSourceRecord = {
  source_id: string
  source_type: string
  path?: string | null
  url?: string | null
  owner?: string | null
  license_status?: string
  training_eligible?: boolean
  refresh_policy?: string
}

type ToolRunResult = {
  output: unknown
  status: string
}

type ReplayResult = {
  turn_id: string
  config_delta: Record<string, unknown>
}
type SessionEvent = {
  id: number
  event_name: string
  payload: Record<string, unknown>
  turn_id: string | null
}
type TurnCreateResponse = {
  turn_id: string
  turn: Turn
}

type ParsedSseEvent = {
  id?: number
  event: string
  payload: Record<string, unknown>
}

const parseSseEvent = (chunk: string): ParsedSseEvent | null => {
  const lines = chunk.split('\n')
  let eventName = 'message'
  let dataText = ''
  let id: number | undefined

  for (const line of lines) {
    if (line.startsWith('event:')) {
      eventName = line.slice('event:'.length).trim()
      continue
    }
    if (line.startsWith('data:')) {
      const value = line.slice('data:'.length).trim()
      if (value) {
        dataText = `${dataText ? `${dataText}\n` : ''}${value}`
      }
      continue
    }
    if (line.startsWith('id:')) {
      const parsed = Number(line.slice('id:'.length).trim())
      if (Number.isFinite(parsed)) {
        id = parsed
      }
    }
  }

  if (!dataText) {
    return null
  }
  try {
    return {
      id,
      event: eventName,
      payload: JSON.parse(dataText) as Record<string, unknown>,
    }
  } catch {
    return null
  }
}

const parseSsePayload = (text: string): ParsedSseEvent[] => {
  if (!text.trim()) {
    return []
  }
  return text
    .split('\n\n')
    .map(parseSseEvent)
    .filter((value): value is ParsedSseEvent => value !== null)
}

const parseSseStreamText = async (
  response: Response,
  onEvent: (event: string, payload: Record<string, unknown>, id?: number) => void,
): Promise<void> => {
  const reader = response.body?.getReader()
  if (!reader) {
    const text = await response.text()
    for (const event of parseSsePayload(text)) {
      onEvent(event.event, event.payload, event.id)
    }
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const chunk = await reader.read()
    if (chunk.done) {
      if (buffer.trim()) {
        const parsed = parseSsePayload(buffer)
        parsed.forEach((event) => onEvent(event.event, event.payload, event.id))
      }
      break
    }
    buffer += decoder.decode(chunk.value, { stream: true })
    const pieces = buffer.split('\n\n')
    buffer = pieces.pop() || ''
    for (const line of pieces) {
      const event = parseSseEvent(line)
      if (event) {
        onEvent(event.event, event.payload, event.id)
      }
    }
  }
}

const FEEDBACK_TAGS = [
  'wrong route',
  'wrong retrieval',
  'missing source',
  'hallucinated rate',
  'wrong crop',
  'wrong region',
  'wrong crop/region',
  'missing field data',
  'evidence irrelevant',
  'label/legal risk',
  'unsafe certainty',
  'bad fertility calibration',
  'too vague',
  'too verbose',
  'repeated phrasing',
  'bad safety',
  'insufficient proof',
  'missed tool',
  'bad economics',
  'bad weather reasoning',
  'bad geospatial context',
  'other',
]

const EVIDENCE_FEEDBACK_ASPECTS = ['helpful', 'irrelevant', 'missing', 'stale', 'unsafe', 'licensing_restricted']
const ROUTE_CORRECTION_LABELS = [
  'wrong_route',
  'wrong_retrieval',
  'missing_source',
  'evidence_irrelevant',
  'hallucinated_rate',
  'label_legal_risk',
  'missing_field_data',
  'unsafe_certainty',
  'wrong_crop_region',
  'bad_weather_reasoning',
  'bad_fertility_calibration',
  'other',
]
const TOOL_NAMES = ['route', 'retrieve', 'soil-context', 'spray-window', 'fertility-frame', 'diagnostic-frame', 'weather-power']

const REFLECTION_COMPONENTS = [
  'router',
  'retriever',
  'knowledge_graph',
  'tool',
  'system_prompt',
  'answer_planning',
  'corpus',
  'eval',
  'generation',
  'unknown',
]

export function App() {
  const [sessions, setSessions] = useState<SessionRecord[]>([])
  const [sessionId, setSessionId] = useState('')
  const [message, setMessage] = useState('')
  const [scratchpadNotes, setScratchpadNotes] = useState('')
  const [mode, setMode] = useState<'baseline' | 'agronomic_rag' | 'mock'>('mock')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [feedbackTag, setFeedbackTag] = useState(FEEDBACK_TAGS[0])
  const [feedbackRating, setFeedbackRating] = useState(5)
  const [feedbackRouteCorrect, setFeedbackRouteCorrect] = useState('true')
  const [feedbackRouteCorrectionLabels, setFeedbackRouteCorrectionLabels] = useState<string[]>([])
  const [feedbackCorrection, setFeedbackCorrection] = useState('')
  const [feedbackIdeal, setFeedbackIdeal] = useState('')
  const [feedbackEvidence, setFeedbackEvidence] = useState('')
  const [feedbackEvidenceAspect, setFeedbackEvidenceAspect] = useState(EVIDENCE_FEEDBACK_ASPECTS[0])
  const [exportMode, setExportMode] = useState<'none' | 'identifiers' | 'snippets_hashed' | 'training_safe'>('snippets_hashed')
  const [replayMode, setReplayMode] = useState<'baseline' | 'agronomic_rag' | 'mock'>('mock')
  const [replayPipeline, setReplayPipeline] = useState<'full' | 'route_only' | 'retrieve_only' | 'answer_only'>('full')
  const [replayModel, setReplayModel] = useState('')
  const [replayRagConfig, setReplayRagConfig] = useState('configs/rag_final_mvp.yaml')
  const [replayTopK, setReplayTopK] = useState(5)
  const [replayMaxTokens, setReplayMaxTokens] = useState(280)
  const [sources, setSources] = useState<DataSourceRecord[]>([])
  const [sourcePath, setSourcePath] = useState('')
  const [sourceType, setSourceType] = useState('file')
  const [replayDelta, setReplayDelta] = useState<Record<string, unknown> | null>(null)
  const [exportIncludeTurns, setExportIncludeTurns] = useState(true)
  const [exportIncludeArtifacts, setExportIncludeArtifacts] = useState(true)
  const [exportIncludeSources, setExportIncludeSources] = useState(true)
  const [chatModelId, setChatModelId] = useState('mock')
  const [chatRagConfig, setChatRagConfig] = useState('configs/rag_final_mvp.yaml')
  const [availableModels, setAvailableModels] = useState<string[]>(['mock'])
  const [availableRagConfigs, setAvailableRagConfigs] = useState<string[]>(['configs/rag_final_mvp.yaml'])
  const [reflectionObservation, setReflectionObservation] = useState('')
  const [reflectionEvidence, setReflectionEvidence] = useState('')
  const [reflectionHypothesis, setReflectionHypothesis] = useState('')
  const [reflectionRule, setReflectionRule] = useState('')
  const [reflectionComponent, setReflectionComponent] = useState(REFLECTION_COMPONENTS[0])
  const [reflectionConfidence, setReflectionConfidence] = useState(0.7)
  const [sessionCrop, setSessionCrop] = useState('')
  const [sessionRegion, setSessionRegion] = useState('')
  const [sessionJurisdiction, setSessionJurisdiction] = useState('')
  const [sessionSoilContext, setSessionSoilContext] = useState('')
  const [sessionSeason, setSessionSeason] = useState('')
  const [sessionNotes, setSessionNotes] = useState('')
  const [toolName, setToolName] = useState(TOOL_NAMES[0])
  const [toolPayload, setToolPayload] = useState('{"question":"What is the latest update?"}')
  const [toolOutput, setToolOutput] = useState<ToolRunResult | null>(null)
  const [latestEvents, setLatestEvents] = useState<SessionEvent[]>([])
  const [compareMode, setCompareMode] = useState<'baseline' | 'agronomic_rag'>('baseline')
  const [comparisonTurn, setComparisonTurn] = useState<Turn | null>(null)
  const [streamingEnabled, setStreamingEnabled] = useState(false)
  const [streamingAnswer, setStreamingAnswer] = useState('')
  const [streamingInFlight, setStreamingInFlight] = useState(false)
  const [streamingStatus, setStreamingStatus] = useState<'idle' | 'streaming' | 'completed' | 'cancelled' | 'error'>('idle')
  const streamingAbortRef = useRef<AbortController | null>(null)

  const loadSessions = async () => {
    const loaded = await apiGet<SessionRecord[]>('/api/sessions?include_archived=true')
    setSessions(loaded)
    setSessionId((current) => (loaded.length > 0 ? current || loaded[0].session_id : ''))
    if (loaded.length > 0) {
      const selected = loaded.find((entry) => entry.session_id === sessionId) || loaded[0]
      if (selected) {
        setSessionCrop(String(selected.context?.crop || ''))
        setSessionRegion(String(selected.context?.region || ''))
        setSessionJurisdiction(String(selected.context?.jurisdiction || ''))
        setSessionSoilContext(String(selected.context?.soil_context || ''))
        setSessionSeason(String(selected.context?.season || ''))
        setSessionNotes(String(selected.context?.notes || ''))
      }
    }
  }

  const loadConfigs = async () => {
    const configs = await apiGet<{
      modes: string[]
      rag_configs: string[]
      models: string[]
      prompt_versions: string[]
      default_rag_config: string
    }>('/api/configs')
    const models = configs.models.length > 0 ? configs.models : ['mock']
    const ragConfigs = configs.rag_configs.length > 0 ? configs.rag_configs : ['configs/rag_final_mvp.yaml']
    setAvailableModels(models)
    setAvailableRagConfigs(ragConfigs)
    setChatModelId((current) => (models.includes(current) ? current : models[0]))
    setChatRagConfig((current) => (ragConfigs.includes(current) ? current : configs.default_rag_config || ragConfigs[0]))
  }

  const appendTurnToActiveSession = (sessionIdValue: string, turn: Turn) => {
    setSessions((current) =>
      current.map((entry) => {
        if (entry.session_id !== sessionIdValue) {
          return entry
        }
        const sessionTurns = entry.turns || []
        const existing = sessionTurns.some((item) => item.turn_id === turn.turn_id)
        if (existing) {
          return entry
        }
        return { ...entry, turns: [...sessionTurns, turn] }
      }),
    )
  }

  useEffect(() => {
    if (!sessionId) {
      setMessage('')
      setScratchpadNotes('')
      return
    }
    setMessage(loadPhase6ChatDraft(sessionId)?.message || '')
    setScratchpadNotes(loadPhase6Scratchpad(sessionId)?.notes || '')
  }, [sessionId])

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        await Promise.all([loadSessions(), loadConfigs()])
      } catch (err) {
        setError(String((err as Error).message || err))
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  const activeSession = useMemo(
    () => sessions.find((entry) => entry.session_id === sessionId) || null,
    [sessions, sessionId],
  )
  const turns: Turn[] = activeSession?.turns || []
  const latestTurn = turns[turns.length - 1] || null
  const latestReplay = turns.slice(-1).find((turn) => turn.parent_turn_id === turns[turns.length - 2]?.turn_id)
  const canCompare = Boolean(latestTurn && activeSession?.turns && activeSession.turns.length > 0)

  const onCreateSession = async () => {
    const created = await apiPost<SessionRecord>('/api/sessions', {
      title: 'Sprint Cockpit Session',
      consent: {
        local_trace_capture: true,
        research_export_allowed: true,
        training_export_allowed: false,
      },
      tags: ['cockpit'],
      context: {
        crop: sessionCrop || 'corn',
        region: sessionRegion || '',
        jurisdiction: sessionJurisdiction || '',
        soil_context: sessionSoilContext || '',
        season: sessionSeason || '',
        notes: sessionNotes || '',
      },
    })
    await loadSessions()
    setSessionId(created.session_id)
  }

  const onPatchSession = async (payload: Record<string, unknown>) => {
    if (!sessionId) {
      return
    }
    await apiPatch<SessionRecord>(`/api/sessions/${sessionId}`, payload)
    await loadSessions()
  }

  const onSetSessionContext = async () => {
    await onPatchSession({
      context: {
        crop: sessionCrop || undefined,
        region: sessionRegion || undefined,
        jurisdiction: sessionJurisdiction || undefined,
        soil_context: sessionSoilContext || undefined,
        season: sessionSeason || undefined,
        notes: sessionNotes || undefined,
      },
    })
  }

  const onMessageChange = (nextMessage: string) => {
    setMessage(nextMessage)
    if (!sessionId) {
      return
    }
    savePhase6ChatDraft(sessionId, nextMessage)
  }

  const onScratchpadChange = (nextNotes: string) => {
    setScratchpadNotes(nextNotes)
    if (!sessionId) {
      return
    }
    savePhase6Scratchpad(sessionId, nextNotes)
  }

  const onClearScratchpad = () => {
    if (sessionId) {
      clearPhase6Scratchpad(sessionId)
    }
    setScratchpadNotes('')
  }

  const setSessionStatus = async (status: SessionStatus) => {
    await onPatchSession({ status, archived: status === 'archived' })
  }

  const onSend = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    if (!sessionId || !message.trim()) {
      return
    }
    const payload = {
      message,
      mode,
      model_id: mode === 'mock' ? undefined : chatModelId || availableModels[0],
      rag_config: chatRagConfig || availableRagConfigs[0],
      max_tokens: 280,
      trace_options: {
        store_prompt_messages: true,
        store_retrieved_text: true,
        redaction_mode: 'none',
      },
    }

    try {
      if (streamingEnabled) {
        const controller = new AbortController()
        streamingAbortRef.current = controller
        setStreamingAnswer('')
        setStreamingInFlight(true)
        setStreamingStatus('streaming')
        try {
          const response = await fetch('/api/sessions/' + sessionId + '/turns/stream', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify(payload),
            signal: controller.signal,
          })
          if (!response.ok) {
            throw new Error(`${response.status}: ${await response.text()}`)
          }
          await parseSseStreamText(response, (eventName, data) => {
            if (eventName === 'generation.token' && typeof data.token === 'string') {
              setStreamingAnswer((current) => current + data.token)
            }
            if (eventName === 'answer.completed' && typeof data.turn === 'object' && data.turn) {
              const turnPayload = data.turn as { answer?: string }
              const turn = data.turn as Turn
              appendTurnToActiveSession(sessionId, turn)
              if (typeof turnPayload.answer === 'string') {
                setStreamingAnswer(turnPayload.answer)
              }
            }
          })
          setStreamingStatus('completed')
        } catch (error) {
          if (controller.signal.aborted) {
            setStreamingAnswer('Generation cancelled')
            setStreamingStatus('cancelled')
            return
          }
          setStreamingStatus('error')
          setStreamingAnswer('Generation failed')
          throw error
        } finally {
          if (streamingAbortRef.current === controller) {
            streamingAbortRef.current = null
          }
          setStreamingInFlight(false)
        }
      } else {
        const created = await apiPost<TurnCreateResponse>('/api/sessions/' + sessionId + '/turns', payload)
        appendTurnToActiveSession(sessionId, created.turn)
        setStreamingAnswer('')
        setStreamingStatus('idle')
      }
      clearPhase6ChatDraft(sessionId)
      setMessage('')
    } catch (error) {
      setError(String((error as Error).message || error))
      setStreamingInFlight(false)
    }
  }

  const onCancelStreaming = () => {
    if (!streamingInFlight) {
      return
    }
    streamingAbortRef.current?.abort()
    setStreamingAnswer('Generation cancelled')
    setStreamingStatus('cancelled')
    setStreamingInFlight(false)
  }

  const onSaveFeedback = async (turn: Turn) => {
    await apiPost('/api/feedback', {
      session_id: sessionId,
      turn_id: turn.turn_id,
      rating: feedbackRating,
      failure_tags: [feedbackTag],
      accepted: feedbackRouteCorrect === 'true',
      answer_status: 'reviewed',
      route_correct: feedbackRouteCorrect === 'true',
      route_correction_labels: feedbackRouteCorrectionLabels,
      correction: feedbackCorrection || undefined,
      ideal_answer: feedbackIdeal || undefined,
      evidence_feedback: feedbackEvidence
        ? [{ aspect: feedbackEvidenceAspect, note: feedbackEvidence }]
        : [],
    })
    await loadSessions()
  }

  const onSaveReflection = async (turn: Turn) => {
    if (!reflectionObservation.trim() || !reflectionHypothesis.trim() || !reflectionRule.trim()) {
      return
    }
    await apiPost('/api/reflections', {
      session_id: sessionId,
      turn_id: turn.turn_id,
      observation: reflectionObservation,
      evidence: reflectionEvidence ? [reflectionEvidence] : [],
      failure_hypothesis: reflectionHypothesis,
      proposed_rule: reflectionRule,
      affected_component: reflectionComponent,
      confidence: reflectionConfidence,
      review_status: 'candidate',
    })
    await loadSessions()
  }

  const onExport = async () => {
    if (!activeSession) {
      return
    }
    const body = {
      session_id: activeSession.session_id,
      redaction_mode: exportMode,
      include_turns: exportIncludeTurns,
      include_artifacts: exportIncludeArtifacts,
      include_data_sources: exportIncludeSources,
    }
    await apiPost('/api/exports', body)
  }

  const onReplay = async () => {
    if (!latestTurn) {
      return
    }
    const result = await apiPost<ReplayResult & { base_turn: Turn; config_delta: Record<string, unknown> }>(
      '/api/replay',
      {
        base_turn_id: latestTurn.turn_id,
        mode: replayMode,
        max_tokens: replayMaxTokens,
        model_id: replayModel || undefined,
        rag_config: replayRagConfig || undefined,
        top_k: replayTopK,
        pipeline: replayPipeline,
      },
    )
    setReplayDelta(result.config_delta || null)
    await loadSessions()
  }

  const onRunComparison = async () => {
    if (!latestTurn) {
      return
    }
    const result = await apiPost<ReplayResult & { turn: Turn }>(`/api/replay`, {
      base_turn_id: latestTurn.turn_id,
      mode: compareMode,
      pipeline: 'answer_only',
      model_id: chatModelId || undefined,
      rag_config: compareMode === 'baseline' ? undefined : chatRagConfig || availableRagConfigs[0],
    })
    setComparisonTurn(result.turn)
    await loadSessions()
  }

  const onLoadEvents = async () => {
    if (!activeSession) {
      return
    }
    const response = await fetch(`/api/sessions/${activeSession.session_id}/events?block_ms=0`)
    if (!response.ok) {
      throw new Error(`${response.status}: ${await response.text()}`)
    }
    const text = await response.text()
    const events = parseSsePayload(text).map((entry, index) => ({
      id: entry.id ?? index + 1,
      event_name: entry.event,
      payload: entry.payload,
      turn_id: typeof entry.payload.turn_id === 'string' ? entry.payload.turn_id : null,
    }))
    setLatestEvents(events)
  }

  const onRunTool = async () => {
    if (!toolName) {
      return
    }
    let payload: Record<string, unknown> = {}
    try {
      payload = JSON.parse(toolPayload)
    } catch {
      payload = {}
    }
    const output = await apiPost<unknown>(`/api/tools/${toolName}`, payload)
    setToolOutput({ status: 'ok', output })
  }

  const onLoadSources = async () => {
    const data = await apiGet<DataSourceRecord[]>('/api/data-sources')
    setSources(data)
  }

  const onRegisterSource = async () => {
    if (!sourceType.trim() || !sourcePath.trim()) {
      return
    }
    await apiPost('/api/data-sources', {
      source_type: sourceType,
      path: sourcePath,
    })
    await onLoadSources()
  }

  const route = latestTurn?.trace?.route || null
  const docs = latestTurn?.trace?.retrieved_docs || []
  const tools = latestTurn?.trace?.tool_invocations || []
  const checklist = latestTurn?.trace?.coverage_checklist || []

  return (
    <main className="cockpit-shell">
      <h1>Agronomy Agent Cockpit</h1>
      {error ? <p role="alert">{error}</p> : null}
      <Suspense fallback={<div data-testid="hosted-platform-loading">Loading hosted platform</div>}>
        <HostedPlatform />
      </Suspense>
      <Suspense fallback={<div data-testid="public-demo-pages-loading">Loading public demo pages</div>}>
        <PublicDemoPages />
      </Suspense>
      <section>
        <h2>Session</h2>
        {loading ? (
          <div data-testid="sessions-loading">Loading sessions</div>
        ) : sessions.length === 0 || !sessionId ? (
          <button data-testid="create-session" type="button" onClick={onCreateSession}>
            Create session
          </button>
        ) : (
          <div>
            <label>
              Session
              <select
                data-testid="session-select"
                value={sessionId}
                onChange={(event) => setSessionId(event.target.value)}
              >
                {sessions.map((entry) => (
                  <option key={entry.session_id} value={entry.session_id}>
                    {entry.title}
                  </option>
                ))}
              </select>
            </label>
            <p data-testid="session-status">
              Status: {activeSession?.status || 'active'} · archived: {activeSession?.archived ? 'yes' : 'no'}
            </p>
            <button
              type="button"
              onClick={() => setSessionStatus(activeSession?.status === 'paused' ? 'active' : 'paused')}
            >
              {activeSession?.status === 'paused' ? 'Resume session' : 'Pause session'}
            </button>
            <button type="button" onClick={() => setSessionStatus('archived')}>
              Archive session
            </button>
            <div>
              <h3>Pin session context</h3>
              <label>
                Crop
                <input
                  data-testid="session-crop"
                  value={sessionCrop}
                  onChange={(event) => setSessionCrop(event.target.value)}
                />
              </label>
              <label>
                Region
                <input
                  data-testid="session-region"
                  value={sessionRegion}
                  onChange={(event) => setSessionRegion(event.target.value)}
                />
              </label>
              <label>
                Jurisdiction
                <input
                  data-testid="session-jurisdiction"
                  value={sessionJurisdiction}
                  onChange={(event) => setSessionJurisdiction(event.target.value)}
                />
              </label>
              <label>
                Soil context
                <input
                  data-testid="session-soil-context"
                  value={sessionSoilContext}
                  onChange={(event) => setSessionSoilContext(event.target.value)}
                />
              </label>
              <label>
                Season
                <input
                  data-testid="session-season"
                  value={sessionSeason}
                  onChange={(event) => setSessionSeason(event.target.value)}
                />
              </label>
              <label>
                Notes
                <input
                  data-testid="session-notes"
                  value={sessionNotes}
                  onChange={(event) => setSessionNotes(event.target.value)}
                />
              </label>
              <button type="button" onClick={onSetSessionContext}>
                Save context
              </button>
            </div>
          </div>
        )}
      </section>

      {activeSession && (
        <>
          <section>
            <h2>Chat workspace</h2>
            <form onSubmit={onSend}>
              <label>
                Ask
                <textarea
                  data-testid="chat-input"
                  value={message}
                  onChange={(event) => onMessageChange(event.target.value)}
                />
              </label>
            <label>
              Mode
              <select
                data-testid="mode-select"
                value={mode}
                  onChange={(event) => setMode(event.target.value as 'baseline' | 'agronomic_rag' | 'mock')}
                >
                  <option value="mock">mock</option>
                  <option value="baseline">baseline</option>
                <option value="agronomic_rag">agronomic_rag</option>
              </select>
            </label>
            <label>
              Model
              <select
                data-testid="chat-model"
                value={chatModelId}
                onChange={(event) => setChatModelId(event.target.value)}
              >
                {availableModels.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label>
              RAG config
              <select
                data-testid="chat-rag-config"
                value={chatRagConfig}
                onChange={(event) => setChatRagConfig(event.target.value)}
              >
                {availableRagConfigs.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
              <label>
              Use streaming endpoint
              <input
                type="checkbox"
                data-testid="streaming-enabled"
                checked={streamingEnabled}
                onChange={(event) => setStreamingEnabled(event.target.checked)}
              />
            </label>
              <button data-testid="send-turn" type="submit">
                Send
              </button>
              <button data-testid="cancel-streaming" type="button" onClick={onCancelStreaming} disabled={!streamingInFlight}>
                Stop generation
              </button>
            </form>
            {streamingInFlight || streamingAnswer ? (
              <div data-testid="streaming-progress">
                <p data-testid="streaming-status">Streaming status: {streamingStatus}</p>
                <p data-testid="streaming-answer">Streaming: {streamingAnswer || 'waiting for tokens...'}</p>
              </div>
            ) : null}

            <section aria-labelledby="local-scratchpad-heading" data-testid="local-scratchpad">
              <h3 id="local-scratchpad-heading">Local field notes</h3>
              <p data-testid="local-scratchpad-status">Local only - not synced or included in reports until copied into chat.</p>
              <label>
                Scratchpad
                <textarea
                  data-testid="local-scratchpad-input"
                  value={scratchpadNotes}
                  onChange={(event) => onScratchpadChange(event.target.value)}
                />
              </label>
              <button data-testid="local-scratchpad-clear" type="button" onClick={onClearScratchpad}>
                Clear local notes
              </button>
            </section>

            {turns.length === 0 ? (
              <p>No turns yet</p>
            ) : (
              <div data-testid="turn-list">
                {turns.map((turn) => (
                  <article key={turn.turn_id}>
                    <h3>{turn.user_message}</h3>
                    <p>{turn.answer}</p>
                    <p data-testid={`status-${turn.turn_id}`}>Status: {turn.answer_status}</p>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section>
            <h2>Inspector: route and evidence</h2>
            <div data-testid="route-card">
              <strong>Risk:</strong> <span data-testid="risk-badge">{route?.risk_level || 'unknown'}</span>
              <div>
                <strong>Route:</strong> {route?.question_type || 'unknown'}
              </div>
              <div>
                <strong>Namespaces:</strong> {(route?.namespaces || []).join(', ') || 'none'}
              </div>
              <div>
                <strong>Required tools:</strong> {(route?.required_tools || []).join(', ') || 'none'}
              </div>
              <div>
                <strong>Audience:</strong> {route?.audience || 'unspecified'}
              </div>
              <div>
                <strong>Answer style:</strong> {route?.answer_style || 'default'}
              </div>
              <div>
                <strong>Guidance:</strong> {route?.guidance || 'none'}
              </div>
              <div>
                <strong>Query expansion:</strong>{' '}
                {(route?.query_expansion || []).length === 0
                  ? 'none'
                  : (route?.query_expansion || []).map((entry, index) => (
                      <span key={entry + index}>{entry}{index === (route?.query_expansion || []).length - 1 ? '' : ', '}</span>
                    ))}
              </div>
            </div>
            <div>
              <strong>Checklist:</strong>{' '}
              {checklist.length === 0 ? (
                <span>not available</span>
              ) : (
                <ul>
                  {checklist.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
            <div data-testid="evidence-browser">
              <h3>Retrieved docs</h3>
              {docs.length === 0 ? (
                <p>No retrieved docs</p>
              ) : (
                <ul>
                  {docs.map((doc) => (
                    <li key={doc.doc_id}>
                      <span data-testid={`retrieved-doc-rank-${doc.doc_id}`}>{doc.rank}.</span>{' '}
                      <span data-testid={`retrieved-doc-title-${doc.doc_id}`}>{doc.title}</span>{' '}
                      <span data-testid={`retrieved-doc-source-type-${doc.doc_id}`}>{doc.source_type}</span>{' '}
                      <span data-testid={`retrieved-doc-score-${doc.doc_id}`}>score {doc.score.toFixed(2)}</span>{' '}
                      source: <span data-testid={`retrieved-doc-source-${doc.doc_id}`}>{doc.source || 'unknown'}</span>
                      {doc.tags && doc.tags.length > 0 ? (
                        <>
                          {' '}
                          tags:{' '}
                          <span data-testid={`retrieved-doc-tags-${doc.doc_id}`}>{doc.tags.join(',')}</span>
                        </>
                      ) : null}
                      {doc.snippet ? (
                        <>
                          {' '}
                          <span data-testid={`retrieved-doc-snippet-${doc.doc_id}`}>{doc.snippet}</span>
                        </>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <strong>KG hits:</strong>{' '}
              {(latestTurn?.trace?.graph_hits?.length || 0) === 0 ? 'none' : null}
              <ul>
                {(latestTurn?.trace?.graph_hits || []).map((hit) => (
                  <li key={hit.node_id}>
                    {hit.rank}. {hit.name} ({hit.kind}) · neighbors: {hit.neighbors.join(', ')} · evidence: {hit.evidence}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <strong>Tool calls:</strong>{' '}
              {tools.length === 0 ? 'none' : tools.map((tool) => tool.name).join(', ')}
            </div>
          </section>

          <section>
            <h2>Feedback</h2>
            {latestTurn && (
              <div>
                <label>
                  Failure tag
                  <select
                    data-testid="failure-tag"
                    value={feedbackTag}
                    onChange={(event) => setFeedbackTag(event.target.value)}
                  >
                    {FEEDBACK_TAGS.map((option) => (
                      <option key={option}>{option}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Rating
                  <input
                    data-testid="feedback-rating"
                    type="number"
                    min={1}
                    max={5}
                    value={feedbackRating}
                    onChange={(event) => setFeedbackRating(Number(event.target.value))}
                  />
                </label>
                <label>
                  Route was correct
                  <select
                    data-testid="route-correct"
                    value={feedbackRouteCorrect}
                    onChange={(event) => setFeedbackRouteCorrect(event.target.value)}
                  >
                    <option value="true">yes</option>
                    <option value="false">no</option>
                  </select>
                </label>
                <fieldset>
                  <legend>Route correction labels</legend>
                  {ROUTE_CORRECTION_LABELS.map((label) => (
                    <label key={label}>
                      <input
                        type="checkbox"
                        data-testid={`route-correction-${label}`}
                        checked={feedbackRouteCorrectionLabels.includes(label)}
                        onChange={(event) =>
                          setFeedbackRouteCorrectionLabels((current) =>
                            event.target.checked ? [...current, label] : current.filter((item) => item !== label),
                          )
                        }
                      />
                      {label}
                    </label>
                  ))}
                </fieldset>
                <label>
                  Correction
                  <textarea
                    data-testid="feedback-correction"
                    value={feedbackCorrection}
                    onChange={(event) => setFeedbackCorrection(event.target.value)}
                  />
                </label>
                <label>
                  Ideal answer
                  <textarea
                    data-testid="feedback-ideal"
                    value={feedbackIdeal}
                    onChange={(event) => setFeedbackIdeal(event.target.value)}
                  />
                </label>
                <label>
                  Evidence note
                  <input
                    data-testid="feedback-evidence"
                    value={feedbackEvidence}
                    onChange={(event) => setFeedbackEvidence(event.target.value)}
                  />
                </label>
                <label>
                  Evidence aspect
                  <select
                    data-testid="feedback-evidence-aspect"
                    value={feedbackEvidenceAspect}
                    onChange={(event) => setFeedbackEvidenceAspect(event.target.value)}
                  >
                    {EVIDENCE_FEEDBACK_ASPECTS.map((aspect) => (
                      <option key={aspect} value={aspect}>
                        {aspect}
                      </option>
                    ))}
                  </select>
                </label>
                <button data-testid="save-feedback" type="button" onClick={() => onSaveFeedback(latestTurn)}>
                  Save feedback
                </button>
              </div>
            )}
          </section>

          <section>
            <h2>Reflection</h2>
            {latestTurn && (
              <div>
                <label>
                  Observation
                  <textarea
                    data-testid="reflection-observation"
                    value={reflectionObservation}
                    onChange={(event) => setReflectionObservation(event.target.value)}
                  />
                </label>
                <label>
                  Evidence
                  <input
                    data-testid="reflection-evidence"
                    value={reflectionEvidence}
                    onChange={(event) => setReflectionEvidence(event.target.value)}
                  />
                </label>
                <label>
                  Failure hypothesis
                  <textarea
                    data-testid="reflection-hypothesis"
                    value={reflectionHypothesis}
                    onChange={(event) => setReflectionHypothesis(event.target.value)}
                  />
                </label>
                <label>
                  Proposed rule
                  <textarea
                    data-testid="reflection-rule"
                    value={reflectionRule}
                    onChange={(event) => setReflectionRule(event.target.value)}
                  />
                </label>
                <label>
                  Affected component
                  <select
                    data-testid="reflection-component"
                    value={reflectionComponent}
                    onChange={(event) => setReflectionComponent(event.target.value)}
                  >
                    {REFLECTION_COMPONENTS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Confidence
                  <input
                    data-testid="reflection-confidence"
                    type="number"
                    min={0}
                    max={1}
                    step={0.05}
                    value={reflectionConfidence}
                    onChange={(event) => setReflectionConfidence(Number(event.target.value))}
                  />
                </label>
                <button
                  data-testid="save-reflection"
                  type="button"
                  onClick={() => onSaveReflection(latestTurn)}
                >
                  Save reflection
                </button>
              </div>
            )}
          </section>

          <section>
            <h2>Replay</h2>
            <label>
              Replay mode
              <select
                data-testid="replay-mode"
                value={replayMode}
                onChange={(event) => setReplayMode(event.target.value as 'baseline' | 'agronomic_rag' | 'mock')}
              >
                <option value="mock">mock</option>
                <option value="baseline">baseline</option>
                <option value="agronomic_rag">agronomic_rag</option>
              </select>
            </label>
            <label>
              Replay pipeline
              <select
                data-testid="replay-pipeline"
                value={replayPipeline}
                onChange={(event) =>
                  setReplayPipeline(event.target.value as 'full' | 'route_only' | 'retrieve_only' | 'answer_only')
                }
              >
                <option value="full">full</option>
                <option value="route_only">route_only</option>
                <option value="retrieve_only">retrieve_only</option>
                <option value="answer_only">answer_only</option>
              </select>
            </label>
            <label>
              Replay model
              <input
                data-testid="replay-model"
                type="text"
                value={replayModel}
                onChange={(event) => setReplayModel(event.target.value)}
              />
            </label>
            <label>
              Replay rag config
              <input
                data-testid="replay-rag-config"
                type="text"
                value={replayRagConfig}
                onChange={(event) => setReplayRagConfig(event.target.value)}
              />
            </label>
            <label>
              Replay top_k
              <input
                data-testid="replay-top-k"
                type="number"
                min={1}
                value={replayTopK}
                onChange={(event) => setReplayTopK(Number(event.target.value) || 5)}
              />
            </label>
            <label>
              Replay max tokens
              <input
                data-testid="replay-max-tokens"
                type="number"
                min={1}
                value={replayMaxTokens}
                onChange={(event) => setReplayMaxTokens(Number(event.target.value) || 280)}
              />
            </label>
            <p data-testid="replay-config-diff">
              {`Replay config: mode=${replayMode} · pipeline=${replayPipeline} · model=${replayModel || 'default'} · rag=${replayRagConfig} · top_k=${replayTopK} · max_tokens=${replayMaxTokens}`}
            </p>
            <label>
              Compare latest turn with:
              <select
                data-testid="compare-mode"
                value={compareMode}
                onChange={(event) =>
                  setCompareMode(event.target.value as 'baseline' | 'agronomic_rag')
                }
              >
                <option value="baseline">baseline</option>
                <option value="agronomic_rag">agronomic_rag</option>
              </select>
            </label>
            <button
              data-testid="compare-turn"
              type="button"
              onClick={onRunComparison}
              disabled={!canCompare}
            >
              Compare with alternate mode
            </button>
            {replayDelta ? (
              <pre data-testid="replay-delta">{JSON.stringify(replayDelta, null, 2)}</pre>
            ) : null}
            {comparisonTurn ? (
              <div data-testid="comparison-result">
                <h3>Comparison</h3>
                <p>
                  Base: {latestTurn?.answer}
                </p>
                <p>
                  {compareMode}: {comparisonTurn.answer}
                </p>
              </div>
            ) : null}
            <button data-testid="run-replay" type="button" onClick={onReplay}>
              Replay latest turn
            </button>
            {latestReplay ? (
              <p data-testid="latest-replay">
                Latest replay: {latestReplay.turn_id} (based on {latestReplay.parent_turn_id})
              </p>
            ) : null}
          </section>

          <section>
            <h2>Tool runner</h2>
            <label>
              Tool
              <select data-testid="tool-name" value={toolName} onChange={(event) => setToolName(event.target.value)}>
                {TOOL_NAMES.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Tool payload
              <textarea
                data-testid="tool-payload"
                value={toolPayload}
                onChange={(event) => setToolPayload(event.target.value)}
              />
            </label>
            <button type="button" data-testid="run-tool" onClick={onRunTool}>
              Run tool
            </button>
            {toolOutput ? <pre data-testid="tool-output">{JSON.stringify(toolOutput, null, 2)}</pre> : null}
          </section>

          <section>
            <h2>Export center</h2>
            <label>
              Redaction
              <select
                data-testid="export-mode"
                value={exportMode}
                onChange={(event) => {
                  setExportMode(event.target.value as 'none' | 'identifiers' | 'snippets_hashed' | 'training_safe')
                }}
              >
                <option value="none">none</option>
                <option value="identifiers">identifiers</option>
                <option value="snippets_hashed">snippets_hashed</option>
                <option value="training_safe">training_safe</option>
              </select>
            </label>
            <label>
              Include turns
              <input
                data-testid="export-include-turns"
                type="checkbox"
                checked={exportIncludeTurns}
                onChange={(event) => setExportIncludeTurns(event.target.checked)}
              />
            </label>
            <label>
              Include artifacts
              <input
                data-testid="export-include-artifacts"
                type="checkbox"
                checked={exportIncludeArtifacts}
                onChange={(event) => setExportIncludeArtifacts(event.target.checked)}
              />
            </label>
            <label>
              Include data sources
              <input
                data-testid="export-include-sources"
                type="checkbox"
                checked={exportIncludeSources}
                onChange={(event) => setExportIncludeSources(event.target.checked)}
              />
            </label>
            <button data-testid="create-export" type="button" onClick={onExport}>
              Create export
            </button>
          </section>

          <section>
            <h2>Data Sources</h2>
            <label>
              Source type
              <input
                data-testid="source-type"
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value)}
              />
            </label>
            <label>
              Path or URL
              <input
                data-testid="source-path"
                value={sourcePath}
                onChange={(event) => setSourcePath(event.target.value)}
              />
            </label>
            <button data-testid="register-source" type="button" onClick={onRegisterSource}>
              Register source
            </button>
            <button data-testid="load-sources" type="button" onClick={onLoadSources}>
              Load data sources
            </button>
            <ul>
              {sources.map((source) => (
                <li key={source.source_id} data-testid={`data-source-${source.source_id}`}>
                  <span data-testid={`data-source-id-${source.source_id}`}>{source.source_id}</span>
                  <span data-testid={`data-source-type-${source.source_id}`}>{source.source_type}</span>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2>Session events</h2>
            <button type="button" data-testid="load-events" onClick={onLoadEvents}>
              Load events
            </button>
            <ul>
              {latestEvents.map((event) => (
                <li key={event.id}>
                  {event.id} · {event.event_name}
                  {event.turn_id ? ` · ${event.turn_id}` : ''}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      <section>
        <h2>Trace artifacts</h2>
        <pre>{JSON.stringify({ graph_hits: latestTurn?.trace?.graph_hits?.length || 0 }, null, 2)}</pre>
      </section>
    </main>
  )
}
