const assert = require('node:assert/strict')
const test = require('node:test')

const { canManageVideo } = require('../permission')

function helpersWithRow (row) {
  return {
    database: {
      query: async () => [[row], {}]
    }
  }
}

const localVideo = { isLocal: () => true }

test('allows users with UPDATE_ANY_VIDEO', async () => {
  const decision = await canManageVideo({
    videoUuid: '11111111-1111-4111-8111-111111111111',
    video: localVideo,
    user: { id: 7, hasRight: right => right === 17 },
    peertubeHelpers: helpersWithRow({ ownerUserId: 10, acceptedCollaborator: false })
  })

  assert.deepEqual(decision, { allowed: true, via: 'update_any_video' })
})

test('allows channel owner', async () => {
  const decision = await canManageVideo({
    videoUuid: '11111111-1111-4111-8111-111111111111',
    video: localVideo,
    user: { id: 7, hasRight: () => false },
    peertubeHelpers: helpersWithRow({ ownerUserId: 7, acceptedCollaborator: false })
  })

  assert.deepEqual(decision, { allowed: true, via: 'channel_owner' })
})

test('allows accepted channel collaborator', async () => {
  const decision = await canManageVideo({
    videoUuid: '11111111-1111-4111-8111-111111111111',
    video: localVideo,
    user: { id: 7, hasRight: () => false },
    peertubeHelpers: helpersWithRow({ ownerUserId: 10, acceptedCollaborator: true })
  })

  assert.deepEqual(decision, { allowed: true, via: 'channel_collaborator' })
})

test('rejects users without manage permission', async () => {
  const decision = await canManageVideo({
    videoUuid: '11111111-1111-4111-8111-111111111111',
    video: localVideo,
    user: { id: 7, hasRight: () => false },
    peertubeHelpers: helpersWithRow({ ownerUserId: 10, acceptedCollaborator: false })
  })

  assert.deepEqual(decision, { allowed: false, reason: 'cannot_manage_video' })
})

test('rejects remote videos', async () => {
  const decision = await canManageVideo({
    videoUuid: '11111111-1111-4111-8111-111111111111',
    video: { isLocal: () => false },
    user: { id: 7, hasRight: () => true },
    peertubeHelpers: helpersWithRow({ ownerUserId: 7, acceptedCollaborator: true })
  })

  assert.deepEqual(decision, { allowed: false, reason: 'remote_video' })
})
