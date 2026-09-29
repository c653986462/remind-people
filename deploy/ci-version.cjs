const fs = require('node:fs')
const path = require('node:path')

function ciVersion(base, runNumber) {
  if (!/^\d+\.\d+\.\d+$/.test(base) || !/^[1-9]\d*$/.test(String(runNumber))) {
    throw new Error('Expected a stable x.y.z base version and a positive workflow run number')
  }
  const [major, minor, patch] = base.split('.').map(Number)
  const nextPatch = patch + Number(runNumber)
  if (![major, minor, nextPatch].every(Number.isSafeInteger)) throw new Error('Version overflow')
  return `${major}.${minor}.${nextPatch}`
}

if (require.main === module) {
  if (process.env.GITHUB_ACTIONS !== 'true') throw new Error('CI versioning only runs inside GitHub Actions')
  const file = path.join(__dirname, '..', 'frontend', 'package.json')
  const pkg = JSON.parse(fs.readFileSync(file, 'utf8'))
  pkg.version = ciVersion(pkg.version, process.env.GITHUB_RUN_NUMBER)
  fs.writeFileSync(file, `${JSON.stringify(pkg, null, 2)}\n`)
  fs.appendFileSync(process.env.GITHUB_OUTPUT, `version=${pkg.version}\n`)
  console.log(`CI release version: ${pkg.version}`)
}

module.exports = { ciVersion }
