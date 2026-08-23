const UUID_RE = /[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i

async function register ({ registerVideoField, registerHook, peertubeHelpers }) {
  registerVideoField(
    {
      type: 'html',
      html: `
        <div class="peertube-clipper-entry">
          <strong>PeerTube Clipper</strong>
          <p>Shared review-first clip workflow for this source video.</p>
          <a class="peertube-clipper-open-review peertube-button-link orange-button" href="/p/peertube-clipper">Open clip review</a>
          <p class="peertube-clipper-muted">Visible workflow state is shared with every user who can manage this video/channel.</p>
        </div>
      `
    },
    {
      type: 'update',
      tab: 'plugin-settings'
    }
  )

  const refreshLink = () => {
    const match = window.location.pathname.match(UUID_RE)
    if (!match) return

    const target = `${peertubeHelpers.getBasePluginClientPath()}/peertube-clipper?video=${encodeURIComponent(match[0])}`
    for (const link of document.querySelectorAll('.peertube-clipper-open-review')) {
      link.setAttribute('href', target)
    }
  }

  registerHook({ target: 'action:video-edit.init', handler: () => setTimeout(refreshLink, 0) })
  registerHook({ target: 'action:router.navigation-end', handler: () => setTimeout(refreshLink, 0) })
  setTimeout(refreshLink, 0)
}

async function unregister () {
  return
}

export {
  register,
  unregister
}
