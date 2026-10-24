param(
    [ValidateSet('up', 'stop', 'status', 'logs', 'checks', 'config')]
    [string] $Action = 'status',
    [ValidateSet('pure', 'delivery-pure', 'desktop-pure', 'history-dispatch', 'project-summaries', 'package-next-actions', 'technical-features-pure', 'technical-assets-pure', 'technical-input-pure', 'technical-vision-pure', 'asset-runtime-pure', 'material-derivation-pure', 'context-derivation-pure', 'provider-errors-pure', 'current-source-native', 'current-scope-native', 'read-purpose-native', 'original-get-pure', 'current-original-native', 'current-original-set-native', 'current-material-native', 'complete-material-native', 'material-archive-pure', 'material-recovery-native', 'material-registration-native', 'material-scope-review-native', 'material-cost-native', 'material-scope-findings-native', 'scope-review-issuers-native', 'current-scope-review-native', 'native-material-store', 'budget', 'requirements-pure', 'requirements-api', 'scope-review-pure', 'scope-review-api', 'completion-pure', 'completion-api')]
    [string] $Suite = 'pure'
)
$ErrorActionPreference = 'Stop'
if ($Action -in @('up', 'checks')) {
    $privateDirectory = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.local/fusion'))
    [IO.Directory]::CreateDirectory($privateDirectory) | Out-Null
    foreach ($fileName in @('owner-password', 'checks-owner-password')) {
        $passwordPath = Join-Path $privateDirectory $fileName
        if (-not [IO.File]::Exists($passwordPath)) {
            $passwordBytes = [Security.Cryptography.RandomNumberGenerator]::GetBytes(48)
            $passwordText = [Convert]::ToHexString($passwordBytes)
            $stream = [IO.File]::Open($passwordPath, [IO.FileMode]::CreateNew)
            try {
                $encoded = [Text.Encoding]::UTF8.GetBytes($passwordText)
                $stream.Write($encoded, 0, $encoded.Length)
            } finally { $stream.Dispose() }
        }
    }
    if ($Action -eq 'up' -and -not [IO.File]::Exists((Join-Path $privateDirectory 'admin-password'))) {
        throw 'Configure the local admin-password file in .local/fusion before startup; existing credentials are never reset.'
    }
    if ($Action -eq 'up') {
        $workbenchRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
        if (-not [IO.File]::Exists((Join-Path $workbenchRoot 'apps/web/dist/index.html'))) {
            throw 'Build the current fusion frontend before starting the Compose group.'
        }
        $inputs = [ordered]@{}
        foreach ($directory in @('packages', 'apps/api', 'apps/worker', 'apps/web/dist', 'deploy')) {
            Get-ChildItem -LiteralPath (Join-Path $workbenchRoot $directory) -Recurse -File |
                Where-Object { $_.FullName -notmatch '[\\/](__pycache__|node_modules|\.local)[\\/]' -and $_.Name -notlike '.env*' } |
                ForEach-Object {
                    $relative = [IO.Path]::GetRelativePath($workbenchRoot, $_.FullName).Replace('\', '/')
                    $inputs[$relative] = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                }
        }
        $images = [ordered]@{}
        foreach ($image in @('tender-fusion-checks:py312', 'pgvector/pgvector@sha256:ac08538c6f8b9904c33c8224c5e5706dbe760aca29db1d096972b4052c22a75d', 'bidwb-web:0.1.0')) {
            $imageIdentity = & docker image inspect --format '{{.Id}}' $image
            if ($LASTEXITCODE -ne 0) { throw 'Required existing fusion image unavailable; no image is installed automatically.' }
            $images[$image] = $imageIdentity
        }
        $receipt = [ordered]@{ project = 'tender-fusion'; observedAt = [DateTimeOffset]::UtcNow.ToString('o'); sourceFiles = $inputs; images = $images; mode = 'development read-only source mounts; startup observation, not immutable deployment' }
        $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $privateDirectory 'runtime-inputs.json') -Encoding utf8NoBOM
    }
}
$composeArguments = @('compose', '--project-name', 'tender-fusion', '--file', (Join-Path $PSScriptRoot 'compose.fusion.yaml'), '--env-file', (Join-Path $PSScriptRoot 'fusion.defaults.env'))
$previousSuite = [Environment]::GetEnvironmentVariable('FUSION_CHECK_SUITE')
try {
    $env:FUSION_CHECK_SUITE = $Suite
    switch ($Action) {
        'up' { & docker @composeArguments up --detach --wait }
        'stop' { & docker @composeArguments --profile checks --profile assets stop }
        'status' { & docker @composeArguments --profile checks --profile assets ps --all }
        'logs' { & docker @composeArguments --profile checks --profile assets logs --tail 100 }
        'config' { & docker @composeArguments --profile checks --profile assets config --quiet }
        'checks' {
            & docker @composeArguments --profile checks up --detach checks
            if ($LASTEXITCODE -ne 0) { throw 'Fusion checks startup failed' }
            & docker @composeArguments --profile checks wait checks
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Fusion Compose command failed: $Action" }
} finally {
    [Environment]::SetEnvironmentVariable('FUSION_CHECK_SUITE', $previousSuite, 'Process')
}
