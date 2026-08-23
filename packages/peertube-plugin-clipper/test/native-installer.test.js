const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const script = fs.readFileSync(
  path.join(__dirname, '..', '..', '..', 'scripts', 'install-plugin-native-stable.sh'),
  'utf8'
)

test('native plugin installer keeps local file dependency source persistent', () => {
  assert.match(script, /\.peertube-clipper-source/)
  assert.match(script, /verify_persistent_dependency/)
  assert.match(script, /PeerTube plugin installed from persistent source/)
})

test('native plugin installer recognizes and repairs legacy ephemeral staging', () => {
  assert.match(script, /file:\/tmp\/peertube-clipper-stage\.\*/)
  assert.match(script, /Repairing legacy ephemeral PeerTube plugin dependency/)
})

test('native plugin installer does not use a new mktemp staging directory for the installed dependency', () => {
  assert.doesNotMatch(script, /mktemp -d \/tmp\/peertube-clipper-stage/)
})
