const test = require('node:test')
const assert = require('node:assert/strict')
const path = require('node:path')

const pkg = require(path.join('..', 'package.json'))

test('uses the exact PeerTube plugin npm identity expected by local installer staging', () => {
  assert.equal(pkg.name, 'peertube-plugin-clipper')
  assert.match(pkg.name, /^peertube-plugin-/)
})

test('declares PeerTube-required package metadata', () => {
  assert.equal(typeof pkg.description, 'string')
  assert.ok(pkg.description.length > 0)
  assert.equal(typeof pkg.engine?.peertube, 'string')
  assert.equal(typeof pkg.homepage, 'string')
  assert.ok(pkg.author)
  assert.ok(pkg.bugs)
  assert.equal(typeof pkg.library, 'string')
  assert.equal(typeof pkg.staticDirs, 'object')
  assert.ok(Array.isArray(pkg.css))
  assert.ok(Array.isArray(pkg.clientScripts))
  assert.equal(typeof pkg.translations, 'object')
  assert.equal(Array.isArray(pkg.translations), false)
})

test('ships server permission adapter in publishable files', () => {
  assert.ok(Array.isArray(pkg.files))
  assert.ok(pkg.files.includes('permission.js'))
})
