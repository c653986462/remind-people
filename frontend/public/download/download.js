const button = document.getElementById('download-button')
const meta = document.getElementById('download-meta')

function humanSize(bytes) {
  const mb = Number(bytes) / (1024 * 1024)
  return Number.isFinite(mb) && mb > 0 ? `${Math.round(mb)} MB` : ''
}

async function loadLatestRelease() {
  try {
    const response = await fetch('/desktop-updates/latest.yml', { cache: 'no-store' })
    if (!response.ok) return
    const manifest = await response.text()
    const version = manifest.match(/^version:\s*([^\r\n]+)/m)?.[1]?.trim()
    const fileName = manifest.match(/^path:\s*(.+)$/m)?.[1]?.trim().replace(/^['"]|['"]$/g, '')
    const bytes = manifest.match(/^\s+size:\s*(\d+)\s*$/m)?.[1]
    if (!version || !fileName || !fileName.toLowerCase().endsWith('.exe') || /[\\/]/.test(fileName)) return

    button.href = `/desktop-updates/${encodeURIComponent(fileName)}`
    button.download = fileName
    meta.textContent = `Windows 10 / 11 · 64 位 · 版本 ${version}${bytes ? ` · ${humanSize(bytes)}` : ''}`
  } catch {
    // Keep the last known release link if the update manifest is temporarily unavailable.
  }
}

void loadLatestRelease()
