const UPDATE_ANY_VIDEO_RIGHT = 17
const ACCEPTED_COLLABORATOR_STATE = 2

async function canManageVideo ({ videoUuid, video, user, peertubeHelpers }) {
  if (!user) return { allowed: false, reason: 'authentication_required' }
  if (!video) return { allowed: false, reason: 'video_not_found' }

  if (typeof video.isLocal !== 'function') {
    return { allowed: false, reason: 'video_locality_unavailable' }
  }

  if (!video.isLocal()) {
    return { allowed: false, reason: 'remote_video' }
  }

  if (typeof user.hasRight === 'function' && user.hasRight(UPDATE_ANY_VIDEO_RIGHT) === true) {
    return { allowed: true, via: 'update_any_video' }
  }

  const [rows] = await peertubeHelpers.database.query(
    `SELECT
       owner_account."userId" AS "ownerUserId",
       EXISTS (
         SELECT 1
         FROM "videoChannelCollaborator" collaborator
         INNER JOIN "account" collaborator_account
           ON collaborator_account."id" = collaborator."accountId"
          AND collaborator_account."userId" = $userId
         WHERE collaborator."channelId" = channel."id"
           AND collaborator."state" = $acceptedState
       ) AS "acceptedCollaborator"
     FROM "video" video
     INNER JOIN "videoChannel" channel
       ON channel."id" = video."channelId"
     INNER JOIN "account" owner_account
       ON owner_account."id" = channel."accountId"
     WHERE video."uuid" = $videoUuid
     LIMIT 1`,
    {
      bind: {
        videoUuid,
        userId: user.id,
        acceptedState: ACCEPTED_COLLABORATOR_STATE
      }
    }
  )

  const row = rows && rows[0]
  if (!row) return { allowed: false, reason: 'video_not_found' }

  if (Number(row.ownerUserId) === Number(user.id)) {
    return { allowed: true, via: 'channel_owner' }
  }

  if (row.acceptedCollaborator === true || row.acceptedCollaborator === 1 || row.acceptedCollaborator === 't') {
    return { allowed: true, via: 'channel_collaborator' }
  }

  return { allowed: false, reason: 'cannot_manage_video' }
}

module.exports = {
  ACCEPTED_COLLABORATOR_STATE,
  UPDATE_ANY_VIDEO_RIGHT,
  canManageVideo
}
