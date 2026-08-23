const assert = require('node:assert/strict')
const test = require('node:test')

const { chooseCanonicalCaption, inspectPeerTubeReadiness } = require('../readiness')

function helpersWithRows (rows) {
  return {
    database: {
      query: async () => [rows]
    },
    config: {
      getWebserverUrl: () => 'https://video.example.org'
    }
  }
}

function vttFetch (text = 'WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n') {
  return async () => ({
    ok: true,
    status: 200,
    arrayBuffer: async () => Buffer.from(text)
  })
}

test('prefers the caption matching the video language', () => {
  const result = chooseCanonicalCaption({
    videoLanguage: 'el',
    captions: [
      { language: 'en', filename: 'en.vtt' },
      { language: 'el', filename: 'el.vtt' }
    ]
  })

  assert.equal(result.ok, true)
  assert.equal(result.caption.filename, 'el.vtt')
})

test('fails closed on multiple captions without a language match', () => {
  const result = chooseCanonicalCaption({
    videoLanguage: '',
    captions: [
      { language: 'en', filename: 'en.vtt' },
      { language: 'el', filename: 'el.vtt' }
    ]
  })

  assert.deepEqual(result, { ok: false, reason: 'canonical_caption_ambiguous' })
})

test('waits while PeerTube still has transcoding work', async () => {
  const readiness = await inspectPeerTubeReadiness({
    videoUuid: '00000000-0000-4000-8000-000000000001',
    peertubeHelpers: helpersWithRows([
      {
        videoUuid: '00000000-0000-4000-8000-000000000001',
        remote: false,
        isLive: false,
        videoLanguage: 'el',
        pendingTranscode: 2,
        pendingTranscription: 0,
        captionLanguage: 'el',
        captionFilename: 'caption.vtt'
      }
    ]),
    fetchImpl: vttFetch()
  })

  assert.equal(readiness.ready, false)
  assert.equal(readiness.reason, 'pending_transcode')
  assert.equal(readiness.workflowStatus, 'waiting_for_video')
})

test('waits while transcription is pending', async () => {
  const readiness = await inspectPeerTubeReadiness({
    videoUuid: '00000000-0000-4000-8000-000000000002',
    peertubeHelpers: helpersWithRows([
      {
        videoUuid: '00000000-0000-4000-8000-000000000002',
        remote: false,
        isLive: false,
        videoLanguage: 'el',
        pendingTranscode: 0,
        pendingTranscription: 1,
        captionLanguage: null,
        captionFilename: null
      }
    ]),
    fetchImpl: vttFetch()
  })

  assert.equal(readiness.ready, false)
  assert.equal(readiness.reason, 'pending_transcription')
  assert.equal(readiness.workflowStatus, 'waiting_for_transcript')
})

test('returns a stable SHA-256 checksum for the canonical VTT', async () => {
  const readiness = await inspectPeerTubeReadiness({
    videoUuid: '00000000-0000-4000-8000-000000000003',
    peertubeHelpers: helpersWithRows([
      {
        videoUuid: '00000000-0000-4000-8000-000000000003',
        remote: false,
        isLive: false,
        videoLanguage: 'el',
        pendingTranscode: 0,
        pendingTranscription: 0,
        captionLanguage: 'el',
        captionFilename: 'caption.vtt',
        captionAutomaticallyGenerated: true
      }
    ]),
    fetchImpl: vttFetch()
  })

  assert.equal(readiness.ready, true)
  assert.equal(readiness.reason, 'ready')
  assert.equal(readiness.workflowStatus, 'ready_for_analysis')
  assert.equal(readiness.captionLanguage, 'el')
  assert.match(readiness.captionChecksum, /^[0-9a-f]{64}$/)
  assert.equal(readiness.captionAutomaticallyGenerated, true)
})
