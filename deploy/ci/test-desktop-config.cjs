const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const vm = require('node:vm')
const { test } = require('node:test')

test('desktop startup preference persists and reloads without an undefined fs module', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'certmgr-desktop-config-'))
  try {
    const filename = path.resolve(__dirname, '../../frontend/electron/main.cjs')
    const source = fs.readFileSync(filename, 'utf8')
    const context = vm.createContext({
      URL,
      require(name) {
        if (name === 'electron') return {
          app: { isPackaged: true, getPath: () => directory, setAppUserModelId() {},
            requestSingleInstanceLock: () => false, quit() {} },
          Menu: { setApplicationMenu() {} },
        }
        if (name === 'electron-updater') return { autoUpdater: {} }
        if (name === './runtime-config.cjs') return { SERVER_URL: 'https://124.221.168.72' }
        return require(name)
      },
    })
    vm.runInContext(source, context, { filename })
    vm.runInContext('config.launchAtLogin = false; writeConfig()', context)
    assert.equal(JSON.parse(fs.readFileSync(path.join(directory, 'desktop-settings.json'), 'utf8')).launchAtLogin, false)
    vm.runInContext('config.launchAtLogin = true; readConfig()', context)
    assert.equal(vm.runInContext('config.launchAtLogin', context), false)
  } finally {
    fs.rmSync(directory, { recursive: true, force: true })
  }
})
