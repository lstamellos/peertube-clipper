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

test('native plugin installer keeps local file dependency source persistent and version-specific', () => {
  assert.match(stableInstaller, /\.peertube-clipper-source/)
  assert.match(stableInstaller, /PLUGIN_VERSION=/)
  assert.match(stableInstaller, /STABLE_VERSION_PARENT="\$STABLE_PARENT\/\$PLUGIN_VERSION"/)
  assert.match(stableInstaller, /STABLE_STAGE="\$STABLE_VERSION_PARENT\/\$PLUGIN_NAME"/)
  assert.match(stableInstaller, /verify_persistent_dependency/)
  assert.match(stableInstaller, /PeerTube plugin installed from version-specific persistent source/)
})

test('native plugin installer verifies the installed runtime version before restart', () => {
  assert.match(stableInstaller, /verify_runtime_version/)
  assert.match(stableInstaller, /Installed PeerTube plugin runtime version does not match staged version/)

  const installIndex = stableInstaller.indexOf('npm run plugin:install -- --plugin-path "$STABLE_STAGE"')
  const runtimeVerifyIndex = stableInstaller.indexOf('verify_runtime_version || die')
  const restartIndex = stableInstaller.indexOf('systemctl restart "$UNIT"')

  assert.ok(installIndex >= 0)
  assert.ok(runtimeVerifyIndex > installIndex)
  assert.ok(restartIndex > runtimeVerifyIndex)
})

test('native plugin installer repairs legacy ephemeral staging from package or lock metadata', () => {
  assert.match(stableInstaller, /pnpm-lock\.yaml/)
  assert.match(stableInstaller, /find_legacy_stages/)
  assert.match(stableInstaller, /\/tmp\/peertube-clipper-stage\\\./)
  assert.match(stableInstaller, /Repairing legacy ephemeral PeerTube Clipper dependency metadata/)
  assert.match(stableInstaller, /verify_no_legacy_reference/)
})

test('native plugin installer fails closed before pnpm on unrelated broken local plugin dependencies', () => {
  assert.match(stableInstaller, /find_broken_foreign_file_dependencies/)
  assert.match(stableInstaller, /Broken unrelated local PeerTube plugin dependency/)
  assert.match(stableInstaller, /Repair broken unrelated PeerTube plugin file dependencies before installing PeerTube Clipper/)

  const preflightIndex = stableInstaller.indexOf('BROKEN_FOREIGN="$(find_broken_foreign_file_dependencies')
  const installIndex = stableInstaller.indexOf('npm run plugin:install -- --plugin-path "$STABLE_STAGE"')
  assert.ok(preflightIndex >= 0)
  assert.ok(installIndex > preflightIndex)
})

test('native plugin installer uses the PeerTube users real primary group for staged trees', () => {
  assert.match(stableInstaller, /PT_GROUP="\$\(id -gn "\$PT_USER"/)
  assert.match(stableInstaller, /chown -R "\$PT_USER:\$PT_GROUP" "\$destination"/)
  assert.match(stableInstaller, /chown "\$PT_USER:\$PT_GROUP" "\$STABLE_PARENT" "\$STABLE_VERSION_PARENT"/)
  assert.doesNotMatch(stableInstaller, /chown -R "\$PT_USER:\$PT_USER"/)
})

test('native plugin installer does not create a fresh ephemeral installed dependency', () => {
  assert.doesNotMatch(stableInstaller, /mktemp -d \/tmp\/peertube-clipper-stage/)
  assert.match(stableInstaller, /npm run plugin:install -- --plugin-path \"\$STABLE_STAGE\"/)
})

test('native plugin installer is intended to be callable through bash even without executable bit', () => {
  assert.match(stableInstaller, /Usage: bash \.\/scripts\/install-plugin-native-stable\.sh/)
})

test('main native installer delegates to persistent installer and does not recreate ephemeral staging', () => {
  const nativeFunction = mainInstaller.match(/install_plugin_native\(\) \{[\s\S]*?\n\}\n\ninstall_plugin_docker\(\)/)?.[0] || ''
  assert.match(nativeFunction, /bash \"\$ROOT\/scripts\/install-plugin-native-stable\.sh\"/)
  assert.match(nativeFunction, /--no-restart/)
  assert.doesNotMatch(nativeFunction, /mktemp -d \/tmp\/peertube-clipper-stage/)
  assert.doesNotMatch(nativeFunction, /--plugin-path \"\$stage\"/)
})

test('main native installer uses the PeerTube users actual primary group for private plugin config', () => {
  const configFunction = mainInstaller.match(/write_native_plugin_config\(\) \{[\s\S]*?\n\}\n\ninstall_plugin_native\(\)/)?.[0] || ''
  assert.match(configFunction, /id -gn \"\$PT_USER\"/)
  assert.match(configFunction, /chown -R \"\$PT_USER:\$group\"/)
  assert.doesNotMatch(configFunction, /chown -R \"\$PT_USER:\$PT_USER\"/)
})
