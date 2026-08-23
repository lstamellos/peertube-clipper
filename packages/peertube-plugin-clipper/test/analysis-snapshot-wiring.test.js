const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')

const main = fs.readFileSync(path.join(__dirname, '..', 'main.js'), 'utf8')

test('readiness keeps caption bytes server-side and snapshots the claimed run', () => {
  assert.match(main, /const \{ captionContent, \.\.\.publicEvaluation \} = evaluation/)
  assert.match(main, /analysis-runs\/\$\{encodeURIComponent\(analysisRunId\)\}\/caption/)
  assert.match(main, /body: captionContent/)
  assert.match(main, /contentType: 'text\/vtt; charset=utf-8'/)
  assert.doesNotMatch(main, /return \{\s*\.\.\.evaluation,\s*analysisClaim:/)
})
