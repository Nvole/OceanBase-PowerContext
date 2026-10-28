param([string]$Image = 'oceanbase/seekdb:latest')
$ErrorActionPreference = 'Stop'
docker inspect stepfun-seekdb *> $null
if ($LASTEXITCODE -eq 0) { docker start stepfun-seekdb; exit $LASTEXITCODE }
docker run -d --name stepfun-seekdb -p 127.0.0.1:2881:2881 -v stepfun-seekdb-data:/var/lib/oceanbase $Image
exit $LASTEXITCODE
