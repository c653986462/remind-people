const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('reminderPopup', {
  submit: action => ipcRenderer.send('desktop:reminder-popup-action', action),
})
