/// <reference types="vite/client" />

interface Window {
  reminderPopup?: { submit: (action: 'later' | 'dismiss') => void }
  desktop?: {
    getApiUrl: () => Promise<string>
    getAppVersion: () => Promise<string>
    checkForUpdates: () => Promise<void>
    showNotification: (title: string, body: string, id: string) => void
    showReminderPopup?: (payload: { key: string; person: string; certificate: string; label: string; targetDate: string }) => Promise<boolean>
    onReminderAction?: (callback: (payload: { key: string; action: 'later' | 'dismiss' }) => void) => () => void
    onUpdateStatus: (callback: (status: { state: string; message?: string; percent?: number }) => void) => () => void
  }
}

