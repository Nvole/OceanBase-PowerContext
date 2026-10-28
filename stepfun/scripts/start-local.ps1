param([string]$ConnectionFile = (Join-Path $env:USERPROFILE '.seekdb-local\connection.json'))
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (Test-Path -LiteralPath $ConnectionFile) {
    $config = Get-Content -Raw -LiteralPath $ConnectionFile -Encoding UTF8 | ConvertFrom-Json
    $env:SEEKDB_HOST = [string]$config.host
    $env:SEEKDB_PORT = [string]$config.port
    $env:SEEKDB_USER = [string]$config.user
    $env:SEEKDB_PASSWORD = [string]$config.password
    $env:SEEKDB_DATABASE = 'stepfun_kb'
}
node --env-file-if-exists=.env server.mjs
exit $LASTEXITCODE
