const { UPDATE_URL } = require('./electron/runtime-config.cjs')
const updateUrl = process.env.DESKTOP_UPDATE_URL || UPDATE_URL

module.exports = {
  appId: 'cn.zhengshi.certificate-manager',
  productName: '证事',
  electronDist: process.env.ELECTRON_DIST || undefined,
  directories: { output: process.env.DESKTOP_BUILD_OUTPUT || 'release' },
  files: ['dist/**/*', 'electron/**/*', 'package.json'],
  win: { target: ['nsis'], verifyUpdateCodeSignature: true },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    perMachine: false,
    // Launch once after install so the packaged app can register its default
    // Windows login startup entry via app.setLoginItemSettings().
    runAfterFinish: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: '证事',
  },
  publish: [{ provider: 'generic', url: updateUrl.endsWith('/') ? updateUrl : `${updateUrl}/` }],
}
