const fs = require('fs/promises')
const path = require('path')
const { canManageVideo } = require('./permission')

const DEFAULT_BRIDGE_URL = 'http://127.0.0.1:18100'
const CONFIG_FILE = 'bridge.json'
const TOKEN_HEADER = 'X-Peertube-Clipper-Token'

async function register ({
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
}

async function unregister () {
  return
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
  normalizeReviewBody
}
