param([string]$PythonExecutable = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$frontendRoot = Join-Path $projectRoot 'frontend'
if (-not $PythonExecutable) {
    $localPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
    $PythonExecutable = if (Test-Path -LiteralPath $localPython) { $localPython } else { 'python' }
}
$runId = $env:GITHUB_RUN_ID
if (-not $runId -or $runId -notmatch '^\d+$') { throw 'GITHUB_RUN_ID is required to make a server release.' }
$packagesRoot = Join-Path $PSScriptRoot 'packages'
New-Item -ItemType Directory -Path $packagesRoot -Force | Out-Null
$archivePath = Join-Path $packagesRoot "certificate-manager-server-$runId.tar.gz"
if (Test-Path -LiteralPath $archivePath) { throw 'Server release already exists; use a new workflow run.' }
$stagePath = Join-Path $packagesRoot ('.server-stage-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stagePath | Out-Null
foreach ($directory in @('app', 'frontend', 'deploy')) {
    New-Item -ItemType Directory -Path (Join-Path $stagePath $directory) | Out-Null
}
Get-ChildItem (Join-Path $projectRoot 'app') -Filter '*.py' -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring((Join-Path $projectRoot 'app').Length + 1)
    $destination = Join-Path $stagePath "app/$relative"
    New-Item -ItemType Directory -Path (Split-Path $destination -Parent) -Force | Out-Null
    Copy-Item -LiteralPath $_.FullName -Destination $destination
}
Copy-Item -LiteralPath (Join-Path $frontendRoot 'dist') -Destination (Join-Path $stagePath 'frontend') -Recurse
if ($env:GITHUB_SHA) {
    $deployment = [ordered]@{source_commit=$env:GITHUB_SHA; run_id=$runId; run_number=$env:GITHUB_RUN_NUMBER}
    [IO.File]::WriteAllText((Join-Path $stagePath 'frontend/dist/deployment.json'), ($deployment | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'requirements.txt') -Destination $stagePath
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'setup-email-reminders-update.sh') -Destination (Join-Path $stagePath 'deploy')
$hashes = [ordered]@{}
Get-ChildItem -LiteralPath $stagePath -File -Recurse | Sort-Object FullName | ForEach-Object {
    $relative = $_.FullName.Substring($stagePath.Length + 1).Replace('\', '/')
    $hashes[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$manifest = [ordered]@{run_id=$runId; created_at=[DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ'); files=$hashes}
if ($env:GITHUB_SHA) { $manifest['source_commit'] = $env:GITHUB_SHA }
if ($env:GITHUB_RUN_NUMBER) { $manifest['run_number'] = $env:GITHUB_RUN_NUMBER }
[IO.File]::WriteAllText((Join-Path $stagePath 'server-release.json'), ($manifest | ConvertTo-Json -Depth 5), [Text.UTF8Encoding]::new($false))
& $PythonExecutable (Join-Path $PSScriptRoot 'ci/verify-server-release.py') $stagePath
if ($LASTEXITCODE -ne 0) { throw 'Server release verification failed.' }
& tar.exe -czf $archivePath -C $stagePath app frontend requirements.txt deploy server-release.json
if ($LASTEXITCODE -ne 0) { throw 'Server release archive creation failed.' }
$archiveHash = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archivePath.sha256", "$archiveHash  $([IO.Path]::GetFileName($archivePath))`n", [Text.UTF8Encoding]::new($false))
Write-Output "Server-only release: $archivePath"
Write-Output "SHA256: $archiveHash"
