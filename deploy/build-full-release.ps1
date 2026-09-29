param([switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path $projectRoot 'frontend'
$version = (Get-Content (Join-Path $frontendRoot 'package.json') -Raw | ConvertFrom-Json).version
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Use a stable x.y.z release version.' }
if (-not $SkipBuild) {
    Push-Location $frontendRoot
    try {
        & npm.cmd run desktop:build
        if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed; no full release created.' }
    } finally { Pop-Location }
}
$builderConfig = Get-Content (Join-Path $frontendRoot 'electron-builder.cjs') -Raw -Encoding UTF8
$productName = [regex]::Match($builderConfig, "productName:\s*'([^']+)'").Groups[1].Value
if (-not $productName) { throw 'Cannot read desktop productName.' }
$installerName = "$productName Setup $version.exe"
$installerPath = Join-Path $frontendRoot "release/$installerName"
$blockmapPath = "$installerPath.blockmap"
foreach ($required in @($installerPath, $blockmapPath, (Join-Path $frontendRoot 'dist/index.html'), (Join-Path $frontendRoot 'dist/download/index.html'))) {
    if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw "Missing release artifact: $required" }
}
$packagesRoot = Join-Path $PSScriptRoot 'packages'
New-Item -ItemType Directory -Path $packagesRoot -Force | Out-Null
$archivePath = Join-Path $packagesRoot "certificate-manager-full-$version.tar.gz"
if (Test-Path -LiteralPath $archivePath) { throw 'Full release already exists. Bump the version instead of overwriting a published release.' }
$stagePath = Join-Path $packagesRoot ('.full-stage-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stagePath | Out-Null
foreach ($directory in @('app', 'frontend', 'deploy', 'desktop-updates')) {
    New-Item -ItemType Directory -Path (Join-Path $stagePath $directory) | Out-Null
}
# Never package .env, live data, uploaded attachments, or local account secrets.
Get-ChildItem (Join-Path $projectRoot 'app') -Filter '*.py' -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring((Join-Path $projectRoot 'app').Length + 1)
    $destination = Join-Path $stagePath "app/$relative"
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
Copy-Item -LiteralPath (Join-Path $frontendRoot 'dist') -Destination (Join-Path $stagePath 'frontend') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot 'requirements.txt') -Destination $stagePath
foreach ($script in @('setup-full-update.sh', 'setup-email-reminders-update.sh', 'verify-full-release.py')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $script) -Destination (Join-Path $stagePath 'deploy')
}
Copy-Item -LiteralPath $installerPath, $blockmapPath -Destination (Join-Path $stagePath 'desktop-updates')
$hashAlgorithm = [Security.Cryptography.SHA512]::Create()
$installerStream = [IO.File]::OpenRead($installerPath)
try { $sha512 = [Convert]::ToBase64String($hashAlgorithm.ComputeHash($installerStream)) }
finally { $installerStream.Dispose(); $hashAlgorithm.Dispose() }
$size = (Get-Item -LiteralPath $installerPath).Length
$date = [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
$latest = "version: $version`nfiles:`n  - url: $installerName`n    sha512: $sha512`n    size: $size`npath: $installerName`nsha512: $sha512`nreleaseDate: '$date'`n"
[IO.File]::WriteAllText((Join-Path $stagePath 'desktop-updates/latest.yml'), $latest, [Text.UTF8Encoding]::new($false))
$hashes = [ordered]@{}
Get-ChildItem -LiteralPath $stagePath -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stagePath.Length + 1).Replace('\', '/')
    $hashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest = [ordered]@{version=$version; installer=$installerName; created_at=$date; files=$hashes}
[IO.File]::WriteAllText((Join-Path $stagePath 'release.json'), ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
& (Join-Path $projectRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'verify-full-release.py') $stagePath
if ($LASTEXITCODE -ne 0) { throw 'Full release verification failed.' }
& tar.exe -czf $archivePath -C $stagePath app frontend requirements.txt deploy desktop-updates release.json
if ($LASTEXITCODE -ne 0) { throw 'Archive creation failed.' }
Write-Output "Full release: $archivePath"
Write-Output "SHA256: $((Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash)"
Write-Output "Staging files retained: $stagePath"
