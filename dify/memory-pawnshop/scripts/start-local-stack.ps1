[CmdletBinding()]
param(
    [switch]$CheckOnly,
    [string]$DataDir
)

$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$backendRoot = Join-Path $projectRoot 'backend'
$backendEntry = Join-Path $backendRoot 'server.mjs'
$powerContextExe = Join-Path $workspaceRoot 'work\.venv\Scripts\powercontext.exe'
$powerContextHome = Join-Path $workspaceRoot 'work\powercontext-data'
$logRoot = Join-Path $workspaceRoot 'work\stack'
$powerContextUrl = 'http://127.0.0.1:8000'
$backendUrl = 'http://127.0.0.1:8765'
if (-not $DataDir) {
    $DataDir = Join-Path $workspaceRoot 'work\demo-data'
}
$DataDir = [System.IO.Path]::GetFullPath($DataDir)
if (-not $DataDir.StartsWith(($workspaceRoot.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to write demo data outside the workspace: $DataDir"
}

function Get-Health {
    param([string]$Url)

    try {
        return Invoke-RestMethod -Uri $Url -TimeoutSec 2 -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Wait-Health {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $health = Get-Health -Url $Url
        if ($health) {
            return $health
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    return $null
}

$pcHealth = Get-Health -Url "$powerContextUrl/health/ready"
$backendHealth = Get-Health -Url "$backendUrl/health"

if ($CheckOnly) {
    [ordered]@{
        powercontext = if ($pcHealth) { 'ready' } else { 'unavailable' }
        backend      = if ($backendHealth) { 'ready' } else { 'unavailable' }
        backend_powercontext = if ($backendHealth) { $backendHealth.powercontext } else { $null }
        data_dir     = $DataDir
    } | ConvertTo-Json -Depth 5
    exit $(if ($pcHealth -and $backendHealth) { 0 } else { 1 })
}

New-Item -ItemType Directory -Force -Path $logRoot | Out-Null

if (-not $pcHealth) {
    if (-not (Test-Path -LiteralPath $powerContextExe)) {
        throw "PowerContext executable not found: $powerContextExe. Follow README step 1 to create the Python environment."
    }

    New-Item -ItemType Directory -Force -Path $powerContextHome | Out-Null
    $previousHome = $env:POWERCONTEXT_HOME
    $previousPort = $env:POWERCONTEXT_SERVER_HTTP_PORT
    $env:POWERCONTEXT_HOME = $powerContextHome
    $env:POWERCONTEXT_SERVER_HTTP_PORT = '8000'

    try {
        $pcProcess = Start-Process -FilePath $powerContextExe `
            -ArgumentList @('server', 'run', '--no-env-file') `
            -WorkingDirectory $workspaceRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logRoot 'powercontext.out.log') `
            -RedirectStandardError (Join-Path $logRoot 'powercontext.err.log') `
            -PassThru
        Set-Content -LiteralPath (Join-Path $logRoot 'powercontext.pid') -Value $pcProcess.Id -Encoding ascii
    }
    finally {
        $env:POWERCONTEXT_HOME = $previousHome
        $env:POWERCONTEXT_SERVER_HTTP_PORT = $previousPort
    }

    $pcHealth = Wait-Health -Url "$powerContextUrl/health/ready" -TimeoutSeconds 40
    if (-not $pcHealth) {
        throw "PowerContext did not become ready. Check $logRoot\powercontext.err.log"
    }
}

if (-not $backendHealth) {
    if (-not (Test-Path -LiteralPath $backendEntry)) {
        throw "Backend entry not found: $backendEntry"
    }

    $node = Get-Command node -ErrorAction SilentlyContinue
    if (-not $node) {
        throw 'Node.js is required but was not found.'
    }

    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $previousDataDir = $env:PAWNSHOP_DATA_DIR
    $env:PAWNSHOP_DATA_DIR = $DataDir
    try {
        $backendProcess = Start-Process -FilePath $node.Source `
            -ArgumentList @('server.mjs') `
            -WorkingDirectory $backendRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $logRoot 'backend.out.log') `
            -RedirectStandardError (Join-Path $logRoot 'backend.err.log') `
            -PassThru
    }
    finally {
        $env:PAWNSHOP_DATA_DIR = $previousDataDir
    }
    Set-Content -LiteralPath (Join-Path $logRoot 'backend.pid') -Value $backendProcess.Id -Encoding ascii

    $backendHealth = Wait-Health -Url "$backendUrl/health" -TimeoutSeconds 20
    if (-not $backendHealth) {
        throw "Backend did not become ready. Check $logRoot\backend.err.log"
    }
}

[ordered]@{
    powercontext = [ordered]@{
        url    = $powerContextUrl
        status = 'ready'
    }
    backend = [ordered]@{
        url    = $backendUrl
        status = 'ready'
        data_dir = $DataDir
        powercontext = $backendHealth.powercontext
    }
    logs = $logRoot
} | ConvertTo-Json -Depth 5

