const crypto = require('crypto')

const MAX_CAPTION_BYTES = 20 * 1024 * 1024

async function inspectPeerTubeReadiness ({ videoUuid, peertubeHelpers, fetchImpl = fetch }) {
  const [rows] = await peertubeHelpers.database.query(
    `SELECT
       video.id AS "videoId",
       video.uuid AS "videoUuid",
       video.remote AS "remote",
       video."isLive" AS "isLive",
       video.language AS "videoLanguage",
       COALESCE(job."pendingTranscode", 0) AS "pendingTranscode",
       COALESCE(job."pendingTranscription", 0) AS "pendingTranscription",
       caption.language AS "captionLanguage",
       caption.filename AS "captionFilename",
       caption."automaticallyGenerated" AS "captionAutomaticallyGenerated",
       caption."updatedAt" AS "captionUpdatedAt"
     FROM video
     LEFT JOIN "videoJobInfo" job ON job."videoId" = video.id
     LEFT JOIN "videoCaption" caption ON caption."videoId" = video.id
     WHERE video.uuid = $videoUuid
     ORDER BY caption.language ASC`,
    { bind: { videoUuid } }
  )

  if (!Array.isArray(rows) || rows.length === 0) {
    return notReady('video_not_found', 'waiting_for_video')
  }

  const base = rows[0]
  if (isTrue(base.remote)) return notReady('remote_video', 'waiting_for_video')
  if (isTrue(base.isLive)) return notReady('live_video', 'waiting_for_video')

  const pendingTranscode = toNonNegativeInteger(base.pendingTranscode)
  const pendingTranscription = toNonNegativeInteger(base.pendingTranscription)

  if (pendingTranscode > 0) {
    return notReady('pending_transcode', 'waiting_for_video', {
      pendingTranscode,
      pendingTranscription
    })
  }

  if (pendingTranscription > 0) {
    return notReady('pending_transcription', 'waiting_for_transcript', {
      pendingTranscode,
      pendingTranscription
    })
  }

  const captions = rows
    .filter(row => row.captionLanguage && row.captionFilename)
    .map(row => ({
      language: String(row.captionLanguage),
      filename: String(row.captionFilename),
      automaticallyGenerated: isTrue(row.captionAutomaticallyGenerated),
      updatedAt: row.captionUpdatedAt || null
    }))

  const canonical = chooseCanonicalCaption({
    captions,
    videoLanguage: base.videoLanguage ? String(base.videoLanguage) : ''
  })

  if (!canonical.ok) {
    return notReady(canonical.reason, 'waiting_for_transcript', {
      pendingTranscode,
      pendingTranscription,
      captionCount: captions.length
    })
  }

  const webserverUrl = String(peertubeHelpers.config.getWebserverUrl() || '').replace(/\/$/, '')
  if (!webserverUrl) return notReady('webserver_url_unavailable', 'waiting_for_transcript')

  const captionUrl = `${webserverUrl}/lazy-static/video-captions/${encodeURIComponent(canonical.caption.filename)}`
  let response
  try {
    response = await fetchImpl(captionUrl, { signal: AbortSignal.timeout(5000) })
  } catch (_error) {
    return notReady('canonical_caption_unavailable', 'waiting_for_transcript')
  }

  if (!response.ok) {
    return notReady('canonical_caption_unavailable', 'waiting_for_transcript', {
      captionHttpStatus: response.status
    })
  }

  const bytes = Buffer.from(await response.arrayBuffer())
  if (bytes.length === 0) return notReady('canonical_caption_empty', 'waiting_for_transcript')
  if (bytes.length > MAX_CAPTION_BYTES) return notReady('canonical_caption_too_large', 'waiting_for_transcript')

  const prefix = bytes.subarray(0, Math.min(bytes.length, 64)).toString('utf8').replace(/^\uFEFF/, '').trimStart()
  if (!prefix.startsWith('WEBVTT')) {
    return notReady('canonical_caption_invalid_vtt', 'waiting_for_transcript')
  }

  const captionChecksum = crypto.createHash('sha256').update(bytes).digest('hex')

  return {
    ready: true,
    reason: 'ready',
    workflowStatus: 'ready_for_analysis',
    pendingTranscode,
    pendingTranscription,
    captionCount: captions.length,
    captionLanguage: canonical.caption.language,
    captionChecksum,
    captionBytes: bytes.length,
    captionAutomaticallyGenerated: canonical.caption.automaticallyGenerated,
    captionContent: bytes
  }
}

function chooseCanonicalCaption ({ captions, videoLanguage }) {
  if (!Array.isArray(captions) || captions.length === 0) {
    return { ok: false, reason: 'canonical_caption_missing' }
  }

  if (videoLanguage) {
    const languageMatch = captions.find(caption => caption.language === videoLanguage)
    if (languageMatch) return { ok: true, caption: languageMatch }
  }

  if (captions.length === 1) return { ok: true, caption: captions[0] }

  return { ok: false, reason: 'canonical_caption_ambiguous' }
}

function notReady (reason, workflowStatus, extra = {}) {
  return {
    ready: false,
    reason,
    workflowStatus,
    ...extra
  }
}

function isTrue (value) {
  return value === true || value === 1 || value === '1' || value === 't' || value === 'true'
}

function toNonNegativeInteger (value) {
  const number = Number(value)
  if (!Number.isFinite(number) || number < 0) return 0
  return Math.floor(number)
}

module.exports = {
  MAX_CAPTION_BYTES,
  chooseCanonicalCaption,
  inspectPeerTubeReadiness
}
