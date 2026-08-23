const fs = require('fs/promises')
const path = require('path')

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

  // Phase 2A intentionally keeps workflow data disabled until the
  // PeerTube-native per-video permission adapter is validated end to end.
  router.get('/videos/:uuid/state', async (req, res) => {
    const user = await peertubeHelpers.user.getAuthUser(res)
    if (!user) return res.status(401).json({ error: 'authentication_required' })

    const video = await peertubeHelpers.videos.loadByIdOrUUID(req.params.uuid)
    if (!video) return res.status(404).json({ error: 'video_not_found' })

    return res.status(501).json({
      error: 'permission_adapter_not_enabled',
      message: 'Per-video review data remains disabled until PeerTube-native manage-video permission semantics are validated.'
    })
  })
}

async function unregister () {
  return
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
  unregister
}
