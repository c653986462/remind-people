$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$stage = Join-Path $env:TEMP ('certificate-manager-tools-' + [guid]::NewGuid().ToString('N'))
$target = Join-Path $projectRoot "deploy/packages/certificate-manager-ci-tools-update-$((Get-Date).ToString('yyyyMMdd-HHmmss')).tar.gz"
New-Item -ItemType Directory -Path (Join-Path $stage 'deploy/ci') -Force | Out-Null
foreach ($file in @('setup-full-update.sh', 'setup-email-reminders-update.sh', 'verify-full-release.py')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy/$file") -Destination (Join-Path $stage "deploy/$file")
}
foreach ($file in @('certificate-manager.service', 'certificate-manager@.service', 'certificate-manager-upstream.nginx.conf')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "deploy/$file") -Destination (Join-Path $stage "deploy/$file")
}
foreach ($file in @('server-deploy.sh', 'safe-extract.py', 'verify-server-release.py', 'prepare-slot.py', 'check-release-order.py', 'check-desktop-target.py', 'publish-desktop.sh', 'blue-green-deploy.sh', 'blue-green-rollback.sh', 'setup-blue-green.sh', 'repair-blue-green.sh', 'update-server-tools.sh')) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $stage "deploy/ci/$file")
}
New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
& tar.exe -czf $target -C $stage deploy
if ($LASTEXITCODE -ne 0) { throw 'Could not create CI deployment tools package.' }
$hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText("$target.sha256", "$hash  $([IO.Path]::GetFileName($target))`n", [Text.UTF8Encoding]::new($false))
Write-Output "Tools package: $target"
Write-Output "SHA256: $hash"
