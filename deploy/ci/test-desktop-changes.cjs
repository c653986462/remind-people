const { test } = require('node:test')
const assert = require('node:assert/strict')
const { desktopChanged } = require('./desktop-changes.cjs')

test('ordinary frontend, backend and CI edits default to small server releases', () => {
  assert.equal(desktopChanged(['frontend/src/App.vue', 'app/main.py', '.github/workflows/release.yml']), false)
  assert.equal(desktopChanged([], { serverOnly: true }), false)
})
test('Electron source, dependencies and explicit force build the installer', () => {
  for (const file of ['frontend/electron/main.cjs', 'frontend/electron/runtime-config.cjs', 'frontend/electron-builder.cjs', 'frontend/package.json', 'frontend/pnpm-lock.yaml']) {
    assert.equal(desktopChanged([file]), true, file)
  }
  assert.equal(desktopChanged([], { force: true }), true)
  assert.equal(desktopChanged([], { serverOnly: false }), true)
  assert.equal(desktopChanged([], { hasBase: false }), true)
})
