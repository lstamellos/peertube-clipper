async function register ({ registerClientRoute }) {
  registerClientRoute({
    route: 'peertube-clipper',
    parentRoute: '/',
    title: 'PeerTube Clipper',
    onMount: ({ rootEl }) => {
      rootEl.innerHTML = `
        <div class="peertube-clipper-page">
          <h1>PeerTube Clipper</h1>
          <p>Review-first clip discovery and production for PeerTube.</p>
          <p class="peertube-clipper-muted">The final workflow is per source video. The temporary root-level route exists until PeerTube exposes a supported Video Manage child-page extension point.</p>
        </div>
      `
    }
  })
}

async function unregister () {
  return
}

export {
  register,
  unregister
}
