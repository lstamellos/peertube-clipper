const fs = require('fs/promises')
const path = require('path')
const { canManageVideo } = require('./permission')
const { inspectPeerTubeReadiness } = require('./readiness')

const DEFAULT_BRIDGE_URL = 'http://127.0.0.1:18100'
const CONFIG_FILE = 'bridge.json'
const TOKEN_HEADER = 'X-Peertube-Clipper-Token'
const RECONCILE_INTERVAL_MS = 60 * 1000
const MAX_RECONCILE_BATCH = 20

const DEFAULT_ANALYZER_VERSION = 'locator-v1'
const DEFAULT_MODEL = 'qwen3:1.7b'
const DEFAULT_PROMPT_VERSION = 'anchors-v1'

let reconcileTimer = null
let reconcileBusy = false

async function register ({
  registerHook,
  registerSetting,
  settingsManager,
  peertubeHelpers,
  getRouter
}) {
  registerSetting({
    name: 'bridge-url',
    label: 'Clip Bridge URL',
    type: 'input',
    default: '',
    descriptionHTML: 'Optional override for the private Clip Bridge endpoint. The installer can provision a server-side bridge.json file instead.',
    private: false
  })

  registerSetting({
    name: 'bridge-token',
    label: 'Clip Bridge service token',
    type: 'input-password',
    default: '',
    private: true,
    descriptionHTML: 'Optional server-side credential override. It is never sent to browser JavaScript.'
  })

  registerSetting({
    name: 'auto-analysis-enabled',
    label: 'Automatically track new videos for clip analysis',
    type: 'input-checkbox',
    default: false,
    private: false,
    descriptionHTML: 'Disabled by default. When enabled, new/updated local videos are tracked until PeerTube transcoding and canonical captions are ready. Existing historical videos are not bulk-enqueued.'
  })

  registerSetting({
    name: 'analysis-model',
    label: 'Analysis model',
    type: 'input',
    default: DEFAULT_MODEL,
    private: false
  })

  registerSetting({
    name: 'analyzer-version',
    label: 'Analyzer version',
    type: 'input',
    default: DEFAULT_ANALYZER_VERSION,
    private: false
  })

  registerSetting({
    name: 'prompt-version',
    label: 'Prompt version',
    type: 'input',
    default: DEFAULT_PROMPT_VERSION,
    private: false
  })

  const router = getRouter()

  router.get('/health', async (_req, res) => {
    const user = await peertubeHelpers.user.getAuthUser(res)
    if (!user) return res.status(401).json({ error: 'authentication_required' })

    const status = await getBridgeHealth({ settingsManager, peertubeHelpers })
    return res.status(status.ok ? 200 : 503).json(status)
  })

  router.get('/videos/:uuid/state', async (req, res) => {
    const context = await requireVideoManager({ req, res, peertubeHelpers })
    if (!context) return

    try {
      await bridgeRequest({
        settingsManager,
        peertubeHelpers,
        method: 'PUT',
        route: `/v1/videos/${encodeURIComponent(req.params.uuid)}`
      })

      const state = await bridgeRequest({
        settingsManager,
        peertubeHelpers,
        method: 'GET',
        route: `/v1/videos/${encodeURIComponent(req.params.uuid)}`
      })

      return res.json({
        authorization: context.permission,
        sourceVideo: {
          uuid: req.params.uuid,
          name: context.video.name || null
        },
        workflow: state.body
      })
    } catch (error) {
      peertubeHelpers.logger.error('PeerTube Clipper state proxy failed: %s', error?.message || error)
      return res.status(502).json({ error: 'bridge_unavailable' })
    }
  })

  router.post('/videos/:uuid/readiness', async (req, res) => {
    const context = await requireVideoManager({ req, res, peertubeHelpers })
    if (!context) return

    try {
      const result = await evaluateAndPersistReadiness({
        videoUuid: req.params.uuid,
        settingsManager,
        peertubeHelpers
      })
      return res.json(result)
    } catch (error) {
      peertubeHelpers.logger.error('PeerTube Clipper readiness evaluation failed: %s', error?.message || error)
      return res.status(502).json({ error: 'readiness_evaluation_failed' })
    }
  })

  router.patch('/videos/:uuid/candidates/:candidateId', async (req, res) => {
    const context = await requireVideoManager({ req, res, peertubeHelpers })
    if (!context) return

    const review = normalizeReviewBody(req.body)
    if (!review.ok) return res.status(422).json({ error: review.error })

    try {
      const result = await bridgeRequest({
        settingsManager,
        peertubeHelpers,
        method: 'PATCH',
        route: `/v1/videos/${encodeURIComponent(req.params.uuid)}/candidates/${encodeURIComponent(req.params.candidateId)}`,
        json: {
          status: review.status,
          editor_start: review.editorStart,
          editor_end: review.editorEnd,
          acted_by_user_id: context.user.id
        }
      })

      return res.status(result.status).json(result.body)
    } catch (error) {
      peertubeHelpers.logger.error('PeerTube Clipper review proxy failed: %s', error?.message || error)
      return res.status(502).json({ error: 'bridge_unavailable' })
    }
  })

  const readinessHints = [
    'action:api.video.uploaded',
    'action:api.video.updated',
    'action:api.video.file-updated',
    'action:api.video-caption.created',
    'action:live.video.state.updated'
  ]

  for (const target of readinessHints) {
    registerHook({
      target,
      handler: async payload => {
        if (!await isAutoAnalysisEnabled(settingsManager)) return
        const videoUuid = extractVideoUuid(payload)
        if (!videoUuid) return

        await safelyEvaluateReadiness({
          videoUuid,
          settingsManager,
          peertubeHelpers,
          source: target
        })
      }
    })
  }

  registerHook({
    target: 'action:application.listening',
    handler: async () => {
      if (reconcileTimer) clearInterval(reconcileTimer)

      reconcileTimer = setInterval(() => {
        reconcileTrackedVideos({ settingsManager, peertubeHelpers })
          .catch(error => peertubeHelpers.logger.error('PeerTube Clipper reconciliation failed: %s', error?.message || error))
      }, RECONCILE_INTERVAL_MS)

      if (typeof reconcileTimer.unref === 'function') reconcileTimer.unref()
    }
  })
}

async function unregister () {
  if (reconcileTimer) clearInterval(reconcileTimer)
  reconcileTimer = null
  reconcileBusy = false
}

async function evaluateAndPersistReadiness ({ videoUuid, settingsManager, peertubeHelpers }) {
  const evaluation = await inspectPeerTubeReadiness({ videoUuid, peertubeHelpers })

  await bridgeRequest({
    settingsManager,
    peertubeHelpers,
    method: 'PUT',
    route: `/v1/videos/${encodeURIComponent(videoUuid)}`
  })

  if (!evaluation.ready) {
    await bridgeRequest({
      settingsManager,
      peertubeHelpers,
      method: 'PATCH',
      route: `/v1/videos/${encodeURIComponent(videoUuid)}/status`,
      json: { status: evaluation.workflowStatus }
    })

    return {
      ...evaluation,
      analysisClaim: null
    }
  }

  const analysisConfig = await resolveAnalysisConfig(settingsManager)
  const claim = await bridgeRequest({
    settingsManager,
    peertubeHelpers,
    method: 'POST',
    route: `/v1/videos/${encodeURIComponent(videoUuid)}/analysis-runs/claim`,
    json: {
      caption_language: evaluation.captionLanguage,
      caption_checksum: evaluation.captionChecksum,
      analyzer_version: analysisConfig.analyzerVersion,
      model: analysisConfig.model,
      prompt_version: analysisConfig.promptVersion
    }
  })

  if (claim.status !== 200) {
    throw new Error(`Bridge analysis claim returned ${claim.status}`)
  }

  return {
    ...evaluation,
    analysisClaim: claim.body
  }
}

async function safelyEvaluateReadiness ({ videoUuid, settingsManager, peertubeHelpers, source }) {
  try {
    const result = await evaluateAndPersistReadiness({ videoUuid, settingsManager, peertubeHelpers })
    peertubeHelpers.logger.info(
      'PeerTube Clipper readiness %s for %s from %s (reason=%s, claimCreated=%s)',
      result.ready ? 'ready' : 'waiting',
      videoUuid,
      source,
      result.reason,
      result.analysisClaim?.created === true
    )
    return result
  } catch (error) {
    peertubeHelpers.logger.error(
      'PeerTube Clipper readiness hint failed for %s from %s: %s',
      videoUuid,
      source,
      error?.message || error
    )
    return null
  }
}

async function reconcileTrackedVideos ({ settingsManager, peertubeHelpers }) {
  if (reconcileBusy) return
  if (!await isAutoAnalysisEnabled(settingsManager)) return

  reconcileBusy = true
  try {
    const tracked = await bridgeRequest({
      settingsManager,
      peertubeHelpers,
      method: 'GET',
      route: '/v1/videos?status=waiting_for_video&status=waiting_for_transcript'
    })

    if (tracked.status !== 200 || !Array.isArray(tracked.body)) return

    for (const state of tracked.body.slice(0, MAX_RECONCILE_BATCH)) {
      if (!state?.video_uuid) continue
      await safelyEvaluateReadiness({
        videoUuid: state.video_uuid,
        settingsManager,
        peertubeHelpers,
        source: 'reconciliation'
      })
    }
  } finally {
    reconcileBusy = false
  }
}

async function requireVideoManager ({ req, res, peertubeHelpers }) {
  const user = await peertubeHelpers.user.getAuthUser(res)
  if (!user) {
    res.status(401).json({ error: 'authentication_required' })
    return null
  }

  const video = await peertubeHelpers.videos.loadByIdOrUUID(req.params.uuid)
  if (!video) {
    res.status(404).json({ error: 'video_not_found' })
    return null
  }

  const permission = await canManageVideo({
    videoUuid: req.params.uuid,
    video,
    user,
    peertubeHelpers
  })

  if (!permission.allowed) {
    const status = permission.reason === 'video_not_found' ? 404 : 403
    res.status(status).json({ error: permission.reason })
    return null
  }

  return { user, video, permission }
}

function normalizeReviewBody (body) {
  const input = body && typeof body === 'object' ? body : {}
  const allowed = new Set(['edited', 'approved', 'rejected'])
  if (!allowed.has(input.status)) return { ok: false, error: 'invalid_status' }

  const editorStart = input.editorStart === null || input.editorStart === undefined ? null : Number(input.editorStart)
  const editorEnd = input.editorEnd === null || input.editorEnd === undefined ? null : Number(input.editorEnd)

  if (editorStart !== null && (!Number.isFinite(editorStart) || editorStart < 0)) {
    return { ok: false, error: 'invalid_editor_start' }
  }
  if (editorEnd !== null && (!Number.isFinite(editorEnd) || editorEnd <= 0)) {
    return { ok: false, error: 'invalid_editor_end' }
  }
  if (editorStart !== null && editorEnd !== null && editorEnd <= editorStart) {
    return { ok: false, error: 'invalid_editor_range' }
  }

  return { ok: true, status: input.status, editorStart, editorEnd }
}

function extractVideoUuid (payload) {
  return payload?.video?.uuid || payload?.caption?.Video?.uuid || payload?.caption?.video?.uuid || null
}

async function isAutoAnalysisEnabled (settingsManager) {
  const value = await settingsManager.getSetting('auto-analysis-enabled')
  return value === true || value === 'true' || value === 1 || value === '1'
}

async function resolveAnalysisConfig (settingsManager) {
  return {
    model: String(await settingsManager.getSetting('analysis-model') || DEFAULT_MODEL).trim() || DEFAULT_MODEL,
    analyzerVersion: String(await settingsManager.getSetting('analyzer-version') || DEFAULT_ANALYZER_VERSION).trim() || DEFAULT_ANALYZER_VERSION,
    promptVersion: String(await settingsManager.getSetting('prompt-version') || DEFAULT_PROMPT_VERSION).trim() || DEFAULT_PROMPT_VERSION
  }
}

async function loadFileConfig (peertubeHelpers) {
  try {
    const dataDir = peertubeHelpers.plugin.getDataDirectoryPath()
    const raw = await fs.readFile(path.join(dataDir, CONFIG_FILE), 'utf8')
    const parsed = JSON.parse(raw)

    return {
      bridgeUrl: typeof parsed.bridgeUrl === 'string' ? parsed.bridgeUrl.trim() : '',
      bridgeToken: typeof parsed.bridgeToken === 'string' ? parsed.bridgeToken : ''
    }
  } catch (error) {
    if (error && error.code === 'ENOENT') return { bridgeUrl: '', bridgeToken: '' }

    peertubeHelpers.logger.warn('Could not read PeerTube Clipper bridge configuration file: %s', error?.message || error)
    return { bridgeUrl: '', bridgeToken: '' }
  }
}

async function resolveBridgeConfig ({ settingsManager, peertubeHelpers }) {
  const fileConfig = await loadFileConfig(peertubeHelpers)
  const settingUrl = String(await settingsManager.getSetting('bridge-url') || '').trim()
  const settingToken = String(await settingsManager.getSetting('bridge-token') || '')

  return {
    bridgeUrl: (settingUrl || fileConfig.bridgeUrl || DEFAULT_BRIDGE_URL).replace(/\/$/, ''),
    bridgeToken: settingToken || fileConfig.bridgeToken || ''
  }
}

async function bridgeRequest ({ settingsManager, peertubeHelpers, method, route, json }) {
  const config = await resolveBridgeConfig({ settingsManager, peertubeHelpers })
  const headers = {}
  if (config.bridgeToken) headers[TOKEN_HEADER] = config.bridgeToken
  if (json !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${config.bridgeUrl}${route}`, {
    method,
    headers,
    body: json === undefined ? undefined : JSON.stringify(json),
    signal: AbortSignal.timeout(5000)
  })

  let body = null
  try {
    body = await response.json()
  } catch (_error) {
    body = null
  }

  if (!response.ok && response.status >= 500) {
    throw new Error(`Bridge returned ${response.status}`)
  }

  return { status: response.status, body }
}

async function getBridgeHealth ({ settingsManager, peertubeHelpers }) {
  const config = await resolveBridgeConfig({ settingsManager, peertubeHelpers })

  try {
    const response = await fetch(`${config.bridgeUrl}/healthz`, {
      headers: config.bridgeToken ? { [TOKEN_HEADER]: config.bridgeToken } : {},
      signal: AbortSignal.timeout(3000)
    })

    return {
      ok: response.ok,
      bridgeStatus: response.status,
      configured: Boolean(config.bridgeToken)
    }
  } catch (_error) {
    return {
      ok: false,
      bridgeStatus: null,
      configured: Boolean(config.bridgeToken)
    }
  }
}

module.exports = {
  register,
  unregister,
  evaluateAndPersistReadiness,
  extractVideoUuid,
  normalizeReviewBody
}
