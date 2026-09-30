const { execFileSync } = require('node:child_process')
const fs = require('node:fs')

function desktopChanged(files, { force = false, serverOnly = true, hasBase = true } = {}) {
  return force || !serverOnly || !hasBase || files.some(file =>
    file.startsWith('frontend/electron/') ||
    ['frontend/electron-builder.cjs', 'frontend/package.json', 'frontend/pnpm-lock.yaml'].includes(file))
}

if (require.main === module) {
  const event = JSON.parse(fs.readFileSync(process.env.GITHUB_EVENT_PATH, 'utf8'))
  const base = process.env.GITHUB_EVENT_NAME === 'push' ? event.before : event.pull_request?.base?.sha
  const hasBase = Boolean(base && !/^0+$/.test(base))
  const files = hasBase ? execFileSync('git', ['diff', '--name-only', base, process.env.GITHUB_SHA], { encoding: 'utf8' }).trim().split(/\r?\n/) : []
  const changed = desktopChanged(files, {
    force: process.env.FORCE_DESKTOP === 'true',
    serverOnly: process.env.DEPLOY_SERVER_ONLY !== 'false',
    hasBase: process.env.GITHUB_EVENT_NAME === 'workflow_dispatch' || hasBase,
  })
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `changed=${changed}\n`)
  console.log(`Build desktop installer: ${changed}`)
}

module.exports = { desktopChanged }
