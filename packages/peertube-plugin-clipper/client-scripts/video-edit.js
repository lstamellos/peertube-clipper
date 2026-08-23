async function register ({ registerVideoField }) {
  registerVideoField(
    {
      type: 'html',
      html: `
        <div class="peertube-clipper-entry">
          <strong>PeerTube Clipper</strong>
          <p>Review-first clip workflow integration is installed for this PeerTube instance.</p>
          <p class="peertube-clipper-muted">The per-video review workspace will be enabled after the native manage-video permission adapter passes end-to-end validation.</p>
        </div>
      `
    },
    {
      type: 'update',
      tab: 'plugin-settings'
    }
  )
}

async function unregister () {
  return
}

export {
  register,
  unregister
}
