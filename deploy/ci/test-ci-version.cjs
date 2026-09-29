const test = require('node:test')
const assert = require('node:assert/strict')
const { ciVersion } = require('../ci-version.cjs')

test('each run increases the stable desktop version', () => {
  assert.equal(ciVersion('0.1.4', '1'), '0.1.5')
  assert.equal(ciVersion('0.1.4', '20'), '0.1.24')
  assert.equal(ciVersion('1.0.0', '1'), '1.0.1')
})
test('rejects invalid version and run inputs', () => {
  for (const [base, run] of [['0.1.4-beta', '1'], ['0.1.4', '0'], ['0.1.4', '-1'], ['0.1.4', 'abc']]) {
    assert.throws(() => ciVersion(base, run))
  }
})
