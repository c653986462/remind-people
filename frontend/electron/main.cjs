const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, screen, session, shell, Tray } = require('electron')
const { autoUpdater } = require('electron-updater')
const fs = require('node:fs')
const path = require('node:path')
const { SERVER_URL } = require('./runtime-config.cjs')

const isDev = !app.isPackaged
const configFile = () => path.join(app.getPath('userData'), 'desktop-settings.json')
let config = { launchAtLogin: true }
let mainWindow
let tray
let isQuitting = false
let reminderPopup
let reminderPopupAction
const trustedOrigin = isDev ? 'http://127.0.0.1:5173' : new URL(SERVER_URL).origin

function readConfig() {
  try {
    const saved = JSON.parse(fs.readFileSync(configFile(), 'utf8'))
    if (typeof saved.launchAtLogin === 'boolean') config.launchAtLogin = saved.launchAtLogin
  } catch {}
}

function writeConfig() {
  fs.mkdirSync(path.dirname(configFile()), { recursive: true })
  fs.writeFileSync(configFile(), JSON.stringify(config, null, 2), { mode: 0o600 })
}

function sendUpdateStatus(payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('desktop:update-status', payload)
}

function isTrustedMainWindow(event) {
  if (!mainWindow || event.sender !== mainWindow.webContents) return false
  try { return new URL(event.senderFrame.url).origin === trustedOrigin }
  catch { return false }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1000,
    minHeight: 680,
    show: false,
    backgroundColor: '#f5f7fa',
    title: '证事',
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  mainWindow.setMenu(null)
  mainWindow.once('ready-to-show', () => { if (!process.argv.includes('--hidden')) mainWindow.show() })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      const parsed = new URL(url)
      if (parsed.protocol === 'https:') void shell.openExternal(url)
    } catch {}
    return { action: 'deny' }
  })
  mainWindow.webContents.on('will-navigate', (event, url) => {
    try { if (new URL(url).origin !== trustedOrigin) event.preventDefault() }
    catch { event.preventDefault() }
  })
  mainWindow.webContents.on('will-redirect', (event, url) => {
    try { if (new URL(url).origin !== trustedOrigin) event.preventDefault() }
    catch { event.preventDefault() }
  })
  mainWindow.on('close', event => {
    if (!isQuitting && tray) { event.preventDefault(); mainWindow.hide() }
  })
  mainWindow.loadURL(isDev ? 'http://127.0.0.1:5173' : SERVER_URL)
}

function closeReminderPopup(action) {
  if (!reminderPopup || reminderPopup.isDestroyed()) return
  if (action) reminderPopupAction = action
  reminderPopup.close()
}

function showReminderPopup(payload) {
  if (!mainWindow || mainWindow.isDestroyed() || (reminderPopup && !reminderPopup.isDestroyed())) return false
  const key = String(payload?.key || '').slice(0, 300)
  if (!key || key.length < 5) return false
  const display = screen.getPrimaryDisplay()
  const area = display.workArea
  const width = 360
  const height = 196
  const popup = new BrowserWindow({
    width,
    height,
    x: area.x + area.width - width - 20,
    y: area.y + area.height - height - 20,
    frame: false,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    skipTaskbar: true,
    alwaysOnTop: true,
    show: false,
    backgroundColor: '#ffffff',
    title: '证书事项提醒',
    webPreferences: {
      preload: path.join(__dirname, 'reminder-preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })
  reminderPopup = popup
  reminderPopupAction = undefined
  popup.setAlwaysOnTop(true, 'screen-saver')
  popup.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })
  popup.on('closed', () => {
    const action = reminderPopupAction || 'later'
    if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send('desktop:reminder-action', { key, action })
    if (reminderPopup === popup) {
      reminderPopup = undefined
      reminderPopupAction = undefined
    }
  })
  const query = {
    person: String(payload.person || '').slice(0, 100),
    certificate: String(payload.certificate || '').slice(0, 150),
    label: String(payload.label || '证书事项').slice(0, 50),
    targetDate: String(payload.targetDate || '').slice(0, 10),
  }
  void popup.loadFile(path.join(__dirname, 'reminder-popup.html'), { query }).then(() => {
    if (!popup.isDestroyed()) popup.showInactive()
  }).catch(() => closeReminderPopup('later'))
  return true
}

function createTray() {
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"><rect width="32" height="32" rx="8" fill="#337ecc"/><text x="16" y="23" text-anchor="middle" font-size="20" fill="white" font-family="sans-serif">证</text></svg>'
  tray = new Tray(nativeImage.createFromDataURL(`data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`))
  tray.setToolTip('证事 · 证书事务提醒')
  const menu = () => Menu.buildFromTemplate([
    { label: '打开证事', click: () => { mainWindow.show(); mainWindow.focus() } },
    { label: '检查更新', click: () => checkUpdates(true) },
    { type: 'separator' },
    { label: '开机启动', type: 'checkbox', checked: !!config.launchAtLogin, click: item => {
      config.launchAtLogin = item.checked
      writeConfig()
      app.setLoginItemSettings({ openAtLogin: item.checked, args: ['--hidden'] })
    } },
    { label: '退出证事', click: () => { isQuitting = true; app.quit() } },
  ])
  tray.setContextMenu(menu())
  tray.on('double-click', () => { mainWindow.show(); mainWindow.focus() })
}

async function checkUpdates(manual = false) {
  if (isDev || !app.isPackaged) {
    if (manual) void dialog.showMessageBox(mainWindow, { type: 'info', message: '开发版本不检查更新' })
    return
  }
  try {
    sendUpdateStatus({ state: 'checking' })
    await autoUpdater.checkForUpdates()
  } catch (error) {
    sendUpdateStatus({ state: 'error', message: error.message })
    if (manual) void dialog.showMessageBox(mainWindow, { type: 'warning', message: '检查更新失败', detail: error.message })
  }
}

app.setAppUserModelId('cn.zhengshi.certificate-manager')
Menu.setApplicationMenu(null)
const gotLock = app.requestSingleInstanceLock()
if (!gotLock) app.quit()
else {
  app.on('second-instance', () => { if (mainWindow) { mainWindow.show(); mainWindow.focus() } })
  app.whenReady().then(async () => {
    readConfig()
    if (!isDev) {
      app.setLoginItemSettings({ openAtLogin: !!config.launchAtLogin, args: ['--hidden'] })
      session.defaultSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false))
    }
    ipcMain.handle('desktop:get-api-url', event => isTrustedMainWindow(event) ? '/api' : '')
    ipcMain.handle('desktop:get-version', () => app.getVersion())
    ipcMain.handle('desktop:check-updates', event => { if (isTrustedMainWindow(event)) return checkUpdates(true) })
    ipcMain.handle('desktop:show-reminder', (event, payload) => {
      if (!isTrustedMainWindow(event)) return false
      return showReminderPopup(payload)
    })
    ipcMain.on('desktop:reminder-popup-action', (event, action) => {
      if (!reminderPopup || event.sender !== reminderPopup.webContents || !['later', 'dismiss'].includes(action)) return
      closeReminderPopup(action)
    })
    ipcMain.on('desktop:notify', (event, payload) => {
      if (!isTrustedMainWindow(event)) return
      if (Notification.isSupported()) new Notification({ title: String(payload.title || '证事提醒'), body: String(payload.body || '') }).show()
    })
    createWindow()
    if (!isDev) createTray()
    if (!isDev) {
      autoUpdater.autoDownload = true
      autoUpdater.autoInstallOnAppQuit = true
      autoUpdater.on('checking-for-update', () => sendUpdateStatus({ state: 'checking' }))
      autoUpdater.on('update-available', info => {
        sendUpdateStatus({ state: 'available', message: info.version })
        if (Notification.isSupported()) new Notification({ title: '证事有新版本', body: `正在下载版本 ${info.version}` }).show()
      })
      autoUpdater.on('update-not-available', () => sendUpdateStatus({ state: 'current' }))
      autoUpdater.on('download-progress', progress => sendUpdateStatus({ state: 'downloading', percent: Math.round(progress.percent) }))
      autoUpdater.on('update-downloaded', async info => {
        sendUpdateStatus({ state: 'downloaded', message: info.version })
        const result = await dialog.showMessageBox(mainWindow, {
          type: 'info', title: '更新已就绪', message: `证事 ${info.version} 已下载完成`,
          detail: '现在重新启动以完成安装，或稍后退出程序时自动安装。', buttons: ['立即重启并更新', '稍后'], defaultId: 0, cancelId: 1,
        })
        if (result.response === 0) { isQuitting = true; autoUpdater.quitAndInstall() }
      })
      autoUpdater.on('error', error => sendUpdateStatus({ state: 'error', message: error.message }))
      setTimeout(() => void checkUpdates(), 5000)
      setInterval(() => void checkUpdates(), 6 * 60 * 60 * 1000)
    }
  })
  app.on('before-quit', () => { isQuitting = true })
  app.on('window-all-closed', event => { if (process.platform !== 'darwin' && !tray) app.quit() })
}
