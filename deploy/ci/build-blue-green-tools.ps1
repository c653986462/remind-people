param([string]$TarExecutable = 'tar')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$packageRoot = Join-Path (Split-Path $PSScriptRoot -Parent) 'packages'
New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
$stage = Join-Path $packageRoot ('.blue-green-tools-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path "$stage/deploy/ci" -Force | Out-Null
foreach ($file in @('certificate-manager.service', 'certificate-manager@.service', 'certificate-manager-upstream.nginx.conf')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy/$file") -Destination (Join-Path $stage "deploy/$file")
}
foreach ($file in @('setup-full-update.sh', 'setup-email-reminders-update.sh', 'verify-full-release.py')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy/$file") -Destination (Join-Path $stage "deploy/$file")
}
foreach ($file in @('server-deploy.sh', 'safe-extract.py', 'verify-server-release.py', 'prepare-slot.py', 'check-release-order.py', 'check-desktop-target.py', 'publish-desktop.sh', 'blue-green-deploy.sh', 'blue-green-rollback.sh', 'setup-blue-green.sh', 'repair-blue-green.sh', 'update-server-tools.sh')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $stage "deploy/ci/$file")
}
$archive = Join-Path $packageRoot 'certificate-manager-blue-green-tools.tar.gz'
if (Test-Path -LiteralPath $archive) { throw 'Tools package already exists; archive or move it first.' }
& $TarExecutable -czf $archive -C $stage deploy
if ($LASTEXITCODE -ne 0) { throw 'Failed to package blue/green deployment tools.' }
$hash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$archive.sha256", "$hash  $([IO.Path]::GetFileName($archive))`n", [Text.UTF8Encoding]::new($false))
Write-Output "Blue/green tools package: $archive"
Write-Output "SHA256: $hash"
Write-Output "Upload and extract this package on the server, then run update-server-tools.sh and setup-blue-green.sh."
