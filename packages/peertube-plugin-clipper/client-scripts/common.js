async function register ({ registerClientRoute, peertubeHelpers }) {
  registerClientRoute({
    route: 'peertube-clipper',
    parentRoute: '/',
    title: 'PeerTube Clipper',
    onMount: ({ rootEl }) => mountReviewPage(rootEl, peertubeHelpers)
  })
}

async function mountReviewPage (rootEl, peertubeHelpers) {
  const videoUuid = new URLSearchParams(window.location.search).get('video')

  if (!videoUuid) {
    rootEl.innerHTML = pageShell('No source video selected', '<p>Open PeerTube Clipper from the Plugin settings tab of a video Manage page.</p>')
    return
  }

  rootEl.innerHTML = pageShell('Clip review', '<p class="peertube-clipper-muted">Loading shared workflow state…</p>')

  try {
    const state = await apiRequest(peertubeHelpers, `/videos/${encodeURIComponent(videoUuid)}/state`)
    renderWorkflow(rootEl, peertubeHelpers, videoUuid, state)
  } catch (error) {
    rootEl.innerHTML = pageShell('Clip review unavailable', `<p>${escapeHtml(error.message || 'Unable to load workflow state.')}</p>`)
  }
}

function renderWorkflow (rootEl, peertubeHelpers, videoUuid, payload) {
  const workflow = payload.workflow || {}
  const video = workflow.video || {}
  const candidates = Array.isArray(workflow.candidates) ? workflow.candidates : []
  const analysisRuns = Array.isArray(workflow.analysis_runs) ? workflow.analysis_runs : []
  const auth = payload.authorization || {}
  const name = payload.sourceVideo?.name || videoUuid

  const latestRun = analysisRuns[0] || null
  const analysisLabel = latestRun ? latestRun.status : 'not queued'

  const summary = `
    <div class="peertube-clipper-summary">
      <div><span>Source video</span><strong>${escapeHtml(name)}</strong></div>
      <div><span>Workflow</span><strong>${escapeHtml(video.status || 'unknown')}</strong></div>
      <div><span>Candidates</span><strong>${candidates.length}</strong></div>
      <div><span>Analysis</span><strong>${escapeHtml(analysisLabel)}</strong></div>
      <div><span>Access</span><strong>${escapeHtml(auth.via || 'manage permission')}</strong></div>
    </div>
  `

  const readiness = `
    <div class="peertube-clipper-readiness">
      <button type="button" class="peertube-button grey-button" data-clipper-readiness>Check readiness</button>
      <span class="peertube-clipper-muted" data-clipper-readiness-result>Checks PeerTube transcodes and canonical captions; it does not start rendering.</span>
    </div>
  `

  const list = candidates.length
    ? candidates.map((candidate, index) => candidateCard(videoUuid, candidate, index)).join('')
    : '<div class="peertube-clipper-empty"><strong>No suggestions yet.</strong><p>The shared workflow exists for this video, but analysis has not populated candidates.</p></div>'

  rootEl.innerHTML = pageShell('Clip review', `${summary}${readiness}<div class="peertube-clipper-candidates">${list}</div>`)

  const readinessButton = rootEl.querySelector('[data-clipper-readiness]')
  readinessButton?.addEventListener('click', async () => {
    const resultEl = rootEl.querySelector('[data-clipper-readiness-result]')
    readinessButton.disabled = true
    if (resultEl) resultEl.textContent = 'Checking PeerTube readiness…'

    try {
      const result = await apiRequest(
        peertubeHelpers,
        `/videos/${encodeURIComponent(videoUuid)}/readiness`,
        { method: 'POST' }
      )

      if (result.ready) {
        const created = result.analysisClaim?.created === true
        const message = created
          ? `Ready. Analysis run queued (${result.captionLanguage}).`
          : `Ready. Matching analysis run already exists (${result.captionLanguage}).`
        peertubeHelpers.notifier.success(message)
      } else {
        peertubeHelpers.notifier.info(`Not ready: ${result.reason}.`)
      }

      await mountReviewPage(rootEl, peertubeHelpers)
    } catch (error) {
      peertubeHelpers.notifier.error(error.message || 'Could not evaluate readiness.')
      readinessButton.disabled = false
      if (resultEl) resultEl.textContent = error.message || 'Readiness check failed.'
    }
  })

  rootEl.querySelectorAll('[data-clipper-action]').forEach(button => {
    button.addEventListener('click', async event => {
      const card = event.currentTarget.closest('[data-candidate-id]')
      if (!card) return

      const candidateId = card.getAttribute('data-candidate-id')
      const action = event.currentTarget.getAttribute('data-clipper-action')
      const startInput = card.querySelector('[data-editor-start]')
      const endInput = card.querySelector('[data-editor-end]')

      const body = {
        status: action,
        editorStart: startInput?.value === '' ? null : Number(startInput?.value),
        editorEnd: endInput?.value === '' ? null : Number(endInput?.value)
      }

      setCardBusy(card, true)
      try {
        await apiRequest(
          peertubeHelpers,
          `/videos/${encodeURIComponent(videoUuid)}/candidates/${encodeURIComponent(candidateId)}`,
          { method: 'PATCH', json: body }
        )
        peertubeHelpers.notifier.success(`Candidate ${action}.`)
        await mountReviewPage(rootEl, peertubeHelpers)
      } catch (error) {
        peertubeHelpers.notifier.error(error.message || 'Could not update candidate.')
        setCardBusy(card, false)
      }
    })
  })
}

function candidateCard (videoUuid, candidate, index) {
  const suggestedStart = Number(candidate.suggested_start)
  const suggestedEnd = Number(candidate.suggested_end)
  const editorStart = candidate.editor_start == null ? suggestedStart : Number(candidate.editor_start)
  const editorEnd = candidate.editor_end == null ? suggestedEnd : Number(candidate.editor_end)
  const sourceUrl = `/w/${encodeURIComponent(videoUuid)}?start=${Math.max(0, Math.floor(editorStart))}`
  const category = candidate.category ? ` · ${escapeHtml(candidate.category)}` : ''
  const reason = candidate.analysis_reason
    ? `<p class="peertube-clipper-muted"><strong>Why:</strong> ${escapeHtml(candidate.analysis_reason)}</p>`
    : ''

  return `
    <article class="peertube-clipper-candidate" data-candidate-id="${escapeHtml(candidate.candidate_id)}">
      <header>
        <div>
          <span class="peertube-clipper-kicker">Candidate ${index + 1}${category}</span>
          <strong>${formatSeconds(suggestedStart)} – ${formatSeconds(suggestedEnd)}</strong>
        </div>
        <span class="peertube-clipper-status">${escapeHtml(candidate.status || 'suggested')}</span>
      </header>

      ${reason}
      <div class="peertube-clipper-transcript">${escapeHtml(candidate.canonical_transcript || '')}</div>

      <div class="peertube-clipper-boundaries">
        <label>Start (s)<input type="number" min="0" step="0.1" data-editor-start value="${editorStart}"></label>
        <label>End (s)<input type="number" min="0.1" step="0.1" data-editor-end value="${editorEnd}"></label>
        <a class="peertube-button-link" href="${sourceUrl}" target="_blank" rel="noopener">Open source</a>
      </div>

      <footer>
        <button type="button" class="peertube-button grey-button" data-clipper-action="rejected">Reject</button>
        <button type="button" class="peertube-button grey-button" data-clipper-action="edited">Save boundaries</button>
        <button type="button" class="peertube-button orange-button" data-clipper-action="approved">Approve</button>
      </footer>
    </article>
  `
}

async function apiRequest (peertubeHelpers, route, options = {}) {
  const base = peertubeHelpers.getBaseRouterRoute()
  const headers = { ...(peertubeHelpers.getAuthHeader() || {}) }
  if (options.json !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${base}${route}`, {
    method: options.method || 'GET',
    headers,
    body: options.json === undefined ? undefined : JSON.stringify(options.json)
  })

  let body = null
  try { body = await response.json() } catch (_error) {}

  if (!response.ok) {
    const detail = body?.error || body?.detail || `Request failed (${response.status})`
    throw new Error(String(detail))
  }

  return body
}

function setCardBusy (card, busy) {
  card.classList.toggle('is-busy', busy)
  card.querySelectorAll('button, input').forEach(control => { control.disabled = busy })
}

function pageShell (title, content) {
  return `<div class="peertube-clipper-page"><h1>${escapeHtml(title)}</h1>${content}</div>`
}

function formatSeconds (value) {
  const total = Math.max(0, Math.floor(Number(value) || 0))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const seconds = total % 60
  return hours > 0
    ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function escapeHtml (value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

async function unregister () {
  return
}

export {
  register,
  unregister
}
