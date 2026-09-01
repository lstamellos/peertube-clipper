const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const source = fs.readFileSync(
  path.join(__dirname, '..', 'client-scripts', 'common.js'),
  'utf8'
)

test('recognizes expired PeerTube bearer failures without exposing raw token errors', () => {
  assert.match(source, /response\?\.status !== 401/)
  assert.match(source, /code === 'invalid_token'/)
  assert.match(source, /detail\.includes\('token is invalid'\)/)
  assert.match(source, /detail\.includes\('invalid token'\)/)
  assert.match(source, /detail\.includes\('token'\) && detail\.includes\('expired'\)/)
  assert.match(source, /error\.code = 'peertube_session_expired'/)
  assert.match(source, /PeerTube session expired\. Reload this page/)
})

test('offers a reload action instead of attempting unsupported token refresh internals', () => {
  assert.match(source, /data-clipper-reload-session/)
  assert.match(source, /window\.location\.reload\(\)/)
  assert.doesNotMatch(source, /refreshAccessToken/)
})
