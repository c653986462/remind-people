const { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, screen, shell, Tray } = require('electron')
const { autoUpdater } = require('electron-updater')
const fs = require('node:fs')
const http = require('node:http')
const https = require('node:https')
const path = require('node:path')
const mime = require('./mime.cjs')
const { SERVER_URL } = require('./runtime-config.cjs')

const isDev = !app.isPackaged
const configFile = () => path.join(app.getPath('userData'), 'desktop-settings.json')
let config = { launchAtLogin: true }
let mainWindow
let tray
let localServer
let localServerPort
let isQuitting = false
let reminderPopup
let reminderPopupAction
const LOCAL_APP_PORT = 43127

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

function routeRequest(req, res) {
  if (req.headers.host !== `127.0.0.1:${LOCAL_APP_PORT}`) { res.writeHead(403).end(); return }
  if (req.url.startsWith('/api/')) {
    let target
    // Nginx exposes backend routes under /api/, so preserve this prefix.
    try { target = new URL(req.url, `${SERVER_URL}/`) }
    catch { res.writeHead(400).end(); return }
    const transport = target.protocol === 'https:' ? https : http
    const headers = { ...req.headers, host: target.host, 'x-forwarded-proto': target.protocol.slice(0, -1) }
    delete headers.connection
    delete headers.origin
    const proxyReq = transport.request(target, { method: req.method, headers }, proxyRes => {
      res.writeHead(proxyRes.statusCode || 502, proxyRes.headers)
      proxyRes.pipe(res)
    })
    proxyReq.on('error', error => {
      if (!res.headersSent) res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' })
      res.end(JSON.stringify({ detail: `连接服务端失败：${error.message}` }))
    })
    req.pipe(proxyReq)
    return
  }

  const requestedPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname)
  const distRoot = path.resolve(__dirname, '..', 'dist')
  const candidate = path.resolve(distRoot, `.${requestedPath}`)
  const insideDist = candidate === distRoot || candidate.startsWith(`${distRoot}${path.sep}`)
  let file = insideDist && fs.existsSync(candidate) && fs.statSync(candidate).isFile() ? candidate : path.join(distRoot, 'index.html')
  if (req.method !== 'GET' && req.method !== 'HEAD') { res.writeHead(405).end(); return }
  res.writeHead(200, {
    'Content-Type': mime[path.extname(file).toLowerCase()] || 'application/octet-stream',
    'Cache-Control': file.endsWith('index.html') ? 'no-cache' : 'public, max-age=31536000, immutable',
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'",
  })
  if (req.method === 'HEAD') res.end()
  else fs.createReadStream(file).pipe(res)
}

async function startLocalServer() {
  localServer = http.createServer(routeRequest)
  await new Promise((resolve, reject) => {
    localServer.once('error', reject)
    localServer.listen(LOCAL_APP_PORT, '127.0.0.1', resolve)
  })
  localServerPort = LOCAL_APP_PORT
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
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') void shell.openExternal(url)
    } catch {}
    return { action: 'deny' }
  })
  mainWindow.on('close', event => {
    if (!isQuitting && tray) { event.preventDefault(); mainWindow.hide() }
  })
  mainWindow.loadURL(isDev ? 'http://127.0.0.1:5173' : `http://127.0.0.1:${localServerPort}/`)
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
      await startLocalServer()
      app.setLoginItemSettings({ openAtLogin: !!config.launchAtLogin, args: ['--hidden'] })
    }
    ipcMain.handle('desktop:get-api-url', () => isDev ? '/api' : `http://127.0.0.1:${localServerPort}/api`)
    ipcMain.handle('desktop:get-version', () => app.getVersion())
    ipcMain.handle('desktop:check-updates', () => checkUpdates(true))
    ipcMain.handle('desktop:show-reminder', (event, payload) => {
      if (!mainWindow || event.sender !== mainWindow.webContents) return false
      return showReminderPopup(payload)
    })
    ipcMain.on('desktop:reminder-popup-action', (event, action) => {
      if (!reminderPopup || event.sender !== reminderPopup.webContents || !['later', 'dismiss'].includes(action)) return
      closeReminderPopup(action)
    })
    ipcMain.on('desktop:notify', (_event, payload) => {
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
  app.on('before-quit', () => { isQuitting = true; if (localServer) localServer.close() })
  app.on('window-all-closed', event => { if (process.platform !== 'darwin' && !tray) app.quit() })
}
