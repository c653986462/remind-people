const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('desktop', {
  getApiUrl: () => ipcRenderer.invoke('desktop:get-api-url'),
  getAppVersion: () => ipcRenderer.invoke('desktop:get-version'),
  checkForUpdates: () => ipcRenderer.invoke('desktop:check-updates'),
  showReminderPopup: payload => ipcRenderer.invoke('desktop:show-reminder', payload),
  onReminderAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('desktop:reminder-action', listener)
    return () => ipcRenderer.removeListener('desktop:reminder-action', listener)
  },
  showNotification: (title, body, id) => ipcRenderer.send('desktop:notify', { title, body, id }),
  onUpdateStatus: callback => {
    const listener = (_event, status) => callback(status)
    ipcRenderer.on('desktop:update-status', listener)
    return () => ipcRenderer.removeListener('desktop:update-status', listener)
  },
})
