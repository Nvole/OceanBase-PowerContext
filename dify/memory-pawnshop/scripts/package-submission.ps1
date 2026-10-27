[CmdletBinding()]
param(
    [string]$Destination,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
if (-not $Destination) {
    $Destination = Join-Path $workspaceRoot 'work\submission\memory-pawnshop'
}
$Destination = [System.IO.Path]::GetFullPath($Destination)

$allowedRoots = @(
    [System.IO.Path]::GetFullPath($workspaceRoot),
    [System.IO.Path]::GetFullPath((Join-Path $env:USERPROFILE 'Documents\Codex'))
)
$insideAllowed = $false
foreach ($allowed in $allowedRoots) {
    $prefix = $allowed.TrimEnd('\') + '\'
    if ($Destination.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        $insideAllowed = $true
        break
    }
}
if (-not $insideAllowed) {
    throw "Refusing to write outside the workspace or Documents\Codex: $Destination"
}

if (Test-Path -LiteralPath $Destination) {
    if (-not $Force) {
        throw "Destination already exists: $Destination. Pass -Force to replace it."
    }
    $resolvedDestination = (Resolve-Path -LiteralPath $Destination).Path
    if (-not $resolvedDestination.StartsWith(($workspaceRoot.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a directory outside the workspace: $resolvedDestination"
    }
    Remove-Item -LiteralPath $resolvedDestination -Recurse -Force
}

New-Item -ItemType Directory -Force -Path $Destination | Out-Null

$files = @(
    'README.md',
    '.gitignore'
)
foreach ($file in $files) {
    $source = Join-Path $projectRoot $file
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination (Join-Path $Destination $file) -Force
    }
}

$directories = @('dify', 'backend', 'scripts', 'docs', 'evidence')
foreach ($directory in $directories) {
    $source = Join-Path $projectRoot $directory
    if (Test-Path -LiteralPath $source) {
        Copy-Item -LiteralPath $source -Destination $Destination -Recurse -Force
    }
}

$dataTarget = Join-Path $Destination 'data'
New-Item -ItemType Directory -Force -Path $dataTarget | Out-Null
$gitkeep = Join-Path $projectRoot 'data\.gitkeep'
if (Test-Path -LiteralPath $gitkeep) {
    Copy-Item -LiteralPath $gitkeep -Destination (Join-Path $dataTarget '.gitkeep') -Force
}

$excludedNames = @('.env', 'ledger.json', 'node_modules', '__pycache__', '.venv')
$excludedPatterns = @('*.pyc', '*.log', '*.pid')
Get-ChildItem -LiteralPath $Destination -Recurse -Force | Sort-Object FullName -Descending | ForEach-Object {
    if ($_.PSIsContainer) {
        if ($excludedNames -contains $_.Name) {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
        return
    }

    if ($excludedNames -contains $_.Name) {
        Remove-Item -LiteralPath $_.FullName -Force
        return
    }
    foreach ($pattern in $excludedPatterns) {
        if ($_.Name -like $pattern) {
            Remove-Item -LiteralPath $_.FullName -Force
            break
        }
    }
}

$secretPatterns = @(
    'sk-[A-Za-z0-9_-]{20,}',
    '(?m)^\s*(?:PAWNSHOP_API_KEY|POWERCONTEXT_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*=\s*\S+',
    '-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
)
$secretHits = [System.Collections.Generic.List[string]]::new()
Get-ChildItem -LiteralPath $Destination -Recurse -File | ForEach-Object {
    if ($_.Length -gt 2MB) {
        return
    }
    $content = Get-Content -LiteralPath $_.FullName -Raw -ErrorAction SilentlyContinue
    if ($null -eq $content) {
        return
    }
    foreach ($pattern in $secretPatterns) {
        if ($content -match $pattern) {
            $secretHits.Add($_.FullName.Substring($Destination.Length).TrimStart('\'))
            break
        }
    }
}
if ($secretHits.Count -gt 0) {
    throw "Possible secrets found in: $($secretHits -join ', ')"
}

$dslPath = Join-Path $Destination 'dify\Memory_Pawnshop_Chatflow.yml'
$dslHash = if (Test-Path -LiteralPath $dslPath) {
    (Get-FileHash -LiteralPath $dslPath -Algorithm SHA256).Hash.ToLowerInvariant()
}
else {
    $null
}

$manifestFiles = Get-ChildItem -LiteralPath $Destination -Recurse -File | Sort-Object FullName | ForEach-Object {
    [ordered]@{
        path   = $_.FullName.Substring($Destination.Length).TrimStart('\')
        bytes  = $_.Length
        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$manifest = [ordered]@{
    generated_at = (Get-Date).ToString('o')
    source       = $projectRoot
    dsl_sha256   = $dslHash
    file_count   = $manifestFiles.Count
    files        = @($manifestFiles)
}
$manifestPath = Join-Path $Destination 'SUBMISSION_MANIFEST.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding utf8

[ordered]@{
    destination  = $Destination
    files        = $manifestFiles.Count
    dsl_sha256   = $dslHash
    manifest     = $manifestPath
    secrets      = 0
} | ConvertTo-Json -Depth 5

