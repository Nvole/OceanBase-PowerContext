[CmdletBinding()]
param(
    [string]$DifyRoot,
    [string]$Tag,
    [int]$WebPort = 80,
    [string]$TagsUrl = 'https://api.github.com/repos/langgenius/dify/tags?per_page=100',
    [string]$ArchiveUrl,
    [switch]$UseMirror,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$workspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $DifyRoot) {
    $DifyRoot = Join-Path $workspaceRoot 'work\dify-src'
}
$DifyRoot = [System.IO.Path]::GetFullPath($DifyRoot)
if (-not $DifyRoot.StartsWith(($workspaceRoot.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to install Dify outside the workspace: $DifyRoot"
}

$dockerCommand = Get-Command docker -ErrorAction SilentlyContinue
if (-not $dockerCommand) {
    throw 'Docker CLI not found. Start Docker Desktop first.'
}

$composePluginOk = $false
$useLegacyCompose = $false
try {
    docker compose version 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $composePluginOk = $true
    }
}
catch {
    $composePluginOk = $false
}
if (-not $composePluginOk) {
    if (Get-Command docker-compose -ErrorAction SilentlyContinue) {
        $useLegacyCompose = $true
    }
    else {
        throw 'Docker Compose is not available. Enable the compose plugin in Docker Desktop.'
    }
}

if ($CheckOnly) {
    [ordered]@{
        workspace    = $workspaceRoot
        dify_root    = $DifyRoot
        tag_override = $Tag
        archive_url  = $ArchiveUrl
        use_mirror   = [bool]$UseMirror
        web_port     = $WebPort
        compose      = if ($useLegacyCompose) { 'docker-compose' } else { 'docker compose' }
    } | ConvertTo-Json -Depth 4
    exit 0
}

$serverVersion = (docker version --format '{{.Server.Version}}' 2>&1 | Out-String).Trim()
if (-not $serverVersion) {
    throw 'Docker daemon is not responding. Start Docker Desktop and wait until the engine is running.'
}
Write-Host "Docker engine: $serverVersion"

if (-not $Tag) {
    Write-Host 'Querying the newest 1.9.x tag from GitHub...'
    try {
        $response = Invoke-RestMethod -Uri $TagsUrl -UseBasicParsing -TimeoutSec 30
        $names = @($response | ForEach-Object { $_.name })
        $strict = @($names | Where-Object { $_ -match '^1\.9\.\d+$' })
        if ($strict.Count -gt 0) {
            $Tag = $strict | Sort-Object { [version]$_ } -Descending | Select-Object -First 1
        }
        else {
            $Tag = $names | Where-Object { $_ -like '1.9.*' } | Sort-Object -Descending | Select-Object -First 1
        }
    }
    catch {
        Write-Warning "Could not query tags: $($_.Exception.Message)"
    }
}
if (-not $Tag) {
    throw 'No 1.9.x tag found. Retry later or pass -Tag <exact-tag> (for example -Tag 1.9.0).'
}
Write-Host "Selected Dify tag: $Tag"

if (-not $ArchiveUrl) {
    if ($UseMirror) {
        $ArchiveUrl = "https://mirror.ghproxy.com/https://github.com/langgenius/dify/archive/refs/tags/$Tag.zip"
    }
    else {
        $ArchiveUrl = "https://codeload.github.com/langgenius/dify/zip/refs/tags/$Tag"
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $DifyRoot 'docker\.env.example'))) {
    $zipPath = Join-Path $workspaceRoot "work\dify-$Tag.zip"
    $extractRoot = Join-Path $workspaceRoot "work\dify-extract-$Tag"

    Write-Host "Downloading $ArchiveUrl"
    Invoke-WebRequest -Uri $ArchiveUrl -OutFile $zipPath -UseBasicParsing -TimeoutSec 600

    if (Test-Path -LiteralPath $extractRoot) {
        $resolvedExtract = (Resolve-Path -LiteralPath $extractRoot).Path
        if (-not $resolvedExtract.StartsWith(($workspaceRoot.TrimEnd('\') + '\work\'), [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove unexpected directory: $resolvedExtract"
        }
        Remove-Item -LiteralPath $resolvedExtract -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $extractRoot | Out-Null
    Expand-Archive -LiteralPath $zipPath -DestinationPath $extractRoot -Force

    $inner = Get-ChildItem -LiteralPath $extractRoot -Directory | Select-Object -First 1
    if (-not $inner) {
        throw 'The downloaded archive did not contain a Dify source directory.'
    }
    if (Test-Path -LiteralPath $DifyRoot) {
        throw "DifyRoot already exists: $DifyRoot. Remove it or pass a different -DifyRoot."
    }
    Move-Item -LiteralPath $inner.FullName -Destination $DifyRoot
    Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Dify $Tag extracted to $DifyRoot"
}
else {
    Write-Host "Reusing existing Dify checkout at $DifyRoot"
}

$dockerDir = Join-Path $DifyRoot 'docker'
$envPath = Join-Path $dockerDir '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    Copy-Item -LiteralPath (Join-Path $dockerDir '.env.example') -Destination $envPath
}
$envLines = @(Get-Content -LiteralPath $envPath)
$foundPortLine = $false
$envLines = @($envLines | ForEach-Object {
    if ($_ -match '^\s*EXPOSE_NGINX_PORT\s*=') {
        $foundPortLine = $true
        "EXPOSE_NGINX_PORT=$WebPort"
    }
    else {
        $_
    }
})
if (-not $foundPortLine) {
    $envLines += "EXPOSE_NGINX_PORT=$WebPort"
}
$envLines | Set-Content -LiteralPath $envPath -Encoding ascii
Write-Host "Dify web port set to $WebPort"

$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    Push-Location $dockerDir
    try {
        if ($useLegacyCompose) {
            $upOutput = docker-compose up -d 2>&1 | Out-String
        }
        else {
            $upOutput = docker compose up -d 2>&1 | Out-String
        }
        $upExit = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $ErrorActionPreference = $previousErrorAction
}
Write-Host $upOutput
if ($upExit -ne 0) {
    throw "docker compose up -d failed with exit code $upExit. See the output above."
}

$installUrl = "http://localhost:$WebPort/install"
Write-Host 'Waiting for Dify web...'
$deadline = (Get-Date).AddSeconds(300)
$ready = $false
do {
    Start-Sleep -Seconds 3
    try {
        $response = Invoke-WebRequest -Uri $installUrl -UseBasicParsing -TimeoutSec 4 -MaximumRedirection 5 -ErrorAction Stop
        if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
            $ready = $true
        }
    }
    catch {
        $ready = $false
    }
} while (-not $ready -and (Get-Date) -lt $deadline)

$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    Push-Location $dockerDir
    try {
        if ($useLegacyCompose) {
            $composeStatus = docker-compose ps 2>&1 | Out-String
        }
        else {
            $composeStatus = docker compose ps 2>&1 | Out-String
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    $ErrorActionPreference = $previousErrorAction
}

[ordered]@{
    dify_root   = $DifyRoot
    dify_tag    = $Tag
    install_url = $installUrl
    web_ready   = $ready
    compose     = $composeStatus
} | ConvertTo-Json -Depth 4

if ($ready) {
    Write-Host ''
    Write-Host "Open $installUrl to create the admin account." -ForegroundColor Green
}
else {
    Write-Warning "Dify web did not respond within 5 minutes. Check 'docker compose ps' in $dockerDir."
    exit 1
}

