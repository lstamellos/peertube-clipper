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

test('native plugin installer repairs legacy ephemeral staging from package or lock metadata', () => {
  assert.match(script, /pnpm-lock\.yaml/)
  assert.match(script, /find_legacy_stages/)
  assert.match(script, /\/tmp\/peertube-clipper-stage\\\./)
  assert.match(script, /Repairing legacy ephemeral PeerTube plugin dependency metadata/)
  assert.match(script, /verify_no_legacy_reference/)
})

test('native plugin installer does not create a fresh ephemeral installed dependency', () => {
  assert.doesNotMatch(script, /mktemp -d \/tmp\/peertube-clipper-stage/)
  assert.match(script, /npm run plugin:install -- --plugin-path \"\$STABLE_STAGE\"/)
})

test('native plugin installer is intended to be callable through bash even without executable bit', () => {
  assert.match(script, /Usage: bash \.\/scripts\/install-plugin-native-stable\.sh/)
})
