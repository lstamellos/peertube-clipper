const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const stableInstaller = fs.readFileSync(
  path.join(__dirname, '..', '..', '..', 'scripts', 'install-plugin-native-stable.sh'),
  'utf8'
)

const mainInstaller = fs.readFileSync(
  path.join(__dirname, '..', '..', '..', 'scripts', 'install.sh'),
  'utf8'
)

test('native plugin installer keeps local file dependency source persistent', () => {
  assert.match(stableInstaller, /\.peertube-clipper-source/)
  assert.match(stableInstaller, /verify_persistent_dependency/)
  assert.match(stableInstaller, /PeerTube plugin installed from persistent source/)
})

test('native plugin installer repairs legacy ephemeral staging from package or lock metadata', () => {
  assert.match(stableInstaller, /pnpm-lock\.yaml/)
  assert.match(stableInstaller, /find_legacy_stages/)
  assert.match(stableInstaller, /\/tmp\/peertube-clipper-stage\\\./)
  assert.match(stableInstaller, /Repairing legacy ephemeral PeerTube plugin dependency metadata/)
  assert.match(stableInstaller, /verify_no_legacy_reference/)
})

test('native plugin installer does not create a fresh ephemeral installed dependency', () => {
  assert.doesNotMatch(stableInstaller, /mktemp -d \/tmp\/peertube-clipper-stage/)
  assert.match(stableInstaller, /npm run plugin:install -- --plugin-path \"\$STABLE_STAGE\"/)
})

test('native plugin installer is intended to be callable through bash even without executable bit', () => {
  assert.match(stableInstaller, /Usage: bash \.\/scripts\/install-plugin-native-stable\.sh/)
})

test('main native installer delegates to persistent installer and does not recreate ephemeral staging', () => {
  assert.match(mainInstaller, /bash \"\$ROOT\/scripts\/install-plugin-native-stable\.sh\"/)
  assert.match(mainInstaller, /--no-restart/)
  assert.doesNotMatch(mainInstaller, /mktemp -d \/tmp\/peertube-clipper-stage/)
  assert.doesNotMatch(mainInstaller, /--plugin-path \"\$stage\"/)
})
