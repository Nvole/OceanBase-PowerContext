[CmdletBinding()]
param(
    [switch]$Json
)

$ErrorActionPreference = 'Stop'

function Get-CommandVersion {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        return $null
    }

    try {
        return ((& $Name --version 2>&1 | Out-String).Trim())
    }
    catch {
        return 'installed'
    }
}

$issues = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

$dockerVersion = Get-CommandVersion -Name 'docker'
$dockerReady = $false
if (-not $dockerVersion) {
    $issues.Add('Docker CLI not found. Install and start Docker Desktop.')
}
else {
    try {
        $serverVersion = (& docker info --format '{{.ServerVersion}}' 2>$null | Out-String).Trim()
        $dockerReady = -not [string]::IsNullOrWhiteSpace($serverVersion)
        if (-not $dockerReady) {
            $issues.Add('Docker daemon is not ready. Start Docker Desktop.')
        }
    }
    catch {
        $issues.Add('Docker daemon is not ready. Start Docker Desktop.')
    }
}

$wslCommand = Get-Command wsl -ErrorAction SilentlyContinue
$wslDistroCount = 0
if (-not $wslCommand) {
    $issues.Add('WSL is not installed. Run "wsl --install" in an elevated PowerShell and reboot.')
}
else {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $wslOutput = @(& wsl -l -q 2>&1)
        $wslExitCode = $LASTEXITCODE
    }
    catch {
        $wslOutput = @($_.Exception.Message)
        $wslExitCode = 1
    }
    finally {
        $ErrorActionPreference = $previousErrorAction
    }
    $distroNames = @(
        $wslOutput |
            ForEach-Object { "$_".Trim() } |
            Where-Object {
                $_ -and
                $_ -notmatch 'Windows Subsystem|适用于 Linux|没有已安装|wsl\.exe|安装 Linux'
            }
    )
    $wslDistroCount = if ($wslExitCode -eq 0) { $distroNames.Count } else { 0 }
    if ($wslDistroCount -eq 0) {
        $issues.Add('No WSL distribution is installed. Run "wsl --install" and reboot.')
    }
}

$nodeVersion = Get-CommandVersion -Name 'node'
if (-not $nodeVersion) {
    $issues.Add('Node.js not found. The pawnshop backend requires Node.js >= 22.5.')
}
else {
    $nodeMajor = 0
    if ($nodeVersion -match 'v(\d+)\.') {
        $nodeMajor = [int]$Matches[1]
    }
    if ($nodeMajor -gt 0 -and $nodeMajor -lt 22) {
        $issues.Add("Node.js $nodeVersion is too old; use >= 22.5.")
    }
}

$pythonVersion = Get-CommandVersion -Name 'python'
if (-not $pythonVersion) {
    $pythonVersion = Get-CommandVersion -Name 'py'
}
if (-not $pythonVersion) {
    $warnings.Add('Python not found. It is only needed to rebuild or validate the Dify DSL.')
}

$freeGb = $null
try {
    $systemDrive = $env:SystemDrive
    $driveInfo = [System.IO.DriveInfo]::new($systemDrive.TrimEnd(':'))
    $freeGb = [math]::Round($driveInfo.AvailableFreeSpace / 1GB, 1)
    if ($freeGb -lt 20) {
        $issues.Add("Only $freeGb GB free on $systemDrive. Dify needs about 20 GB.")
    }
    elseif ($freeGb -lt 30) {
        $warnings.Add("Only $freeGb GB free on $systemDrive. Consider freeing space before pulling Dify images.")
    }
}
catch {
    $warnings.Add('Could not read free disk space.')
}

$result = [ordered]@{
    checked_at       = (Get-Date).ToString('o')
    docker_version   = $dockerVersion
    docker_ready     = $dockerReady
    wsl_installed    = [bool]$wslCommand
    wsl_distros      = $wslDistroCount
    node_version     = $nodeVersion
    python_version   = $pythonVersion
    free_gb          = $freeGb
    issues           = @($issues)
    warnings         = @($warnings)
    ready_for_dify   = ($issues.Count -eq 0)
}

if ($Json) {
    $result | ConvertTo-Json -Depth 5
}
else {
    Write-Host ''
    Write-Host 'Memory Pawnshop / Dify prerequisite check' -ForegroundColor Cyan
    Write-Host ('-' * 48)
    Write-Host ("Docker:   {0}" -f $(if ($dockerVersion) { $dockerVersion } else { 'not found' }))
    Write-Host ("WSL:      {0}" -f $(if ($wslCommand) { "$wslDistroCount distro(s)" } else { 'not found' }))
    Write-Host ("Node.js:  {0}" -f $(if ($nodeVersion) { $nodeVersion } else { 'not found' }))
    Write-Host ("Python:   {0}" -f $(if ($pythonVersion) { $pythonVersion } else { 'not found (optional)' }))
    Write-Host ("Free C::  {0}" -f $(if ($null -ne $freeGb) { "$freeGb GB" } else { 'unknown' }))
    Write-Host ''

    if ($issues.Count -gt 0) {
        Write-Host 'Blocking issues:' -ForegroundColor Yellow
        $issues | ForEach-Object { Write-Host "  - $_" }
    }
    else {
        Write-Host 'All Dify prerequisites are ready.' -ForegroundColor Green
    }

    if ($warnings.Count -gt 0) {
        Write-Host ''
        Write-Host 'Warnings:' -ForegroundColor DarkYellow
        $warnings | ForEach-Object { Write-Host "  - $_" }
    }
    Write-Host ''
}

if ($issues.Count -gt 0) {
    exit 1
}

