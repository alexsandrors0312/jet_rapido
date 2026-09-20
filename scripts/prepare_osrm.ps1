param([Parameter(Mandatory = $true)][string]$InputFile)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker não está instalado. Disponibilize Docker ou use um endpoint OSRM já preparado.'
}
$sourceMap = (Resolve-Path -LiteralPath $InputFile).Path
if ($sourceMap -notmatch '\.osm(\.pbf)?$') { throw 'Informe um extrato .osm ou .osm.pbf.' }
$projectRoot = Split-Path -Parent $PSScriptRoot
$targetDirectory = Join-Path $projectRoot 'data/osrm'
if (Test-Path -LiteralPath $targetDirectory) {
    throw 'data/osrm já existe. Preserve o extrato atual e use uma pasta de trabalho nova para preparar outra versão.'
}
New-Item -ItemType Directory -Path $targetDirectory | Out-Null
$extension = if ($sourceMap.EndsWith('.pbf')) { '.osm.pbf' } else { '.osm' }
$targetFile = Join-Path $targetDirectory ('map' + $extension)
Copy-Item -LiteralPath $sourceMap -Destination $targetFile
$volumeMount = "${targetDirectory}:/data"
docker run --rm -v $volumeMount osrm/osrm-backend:v5.27.1 osrm-extract -p /opt/foot.lua "/data/map$extension"
if ($LASTEXITCODE -ne 0) { throw 'Falha no osrm-extract. O material foi preservado para diagnóstico.' }
docker run --rm -v $volumeMount osrm/osrm-backend:v5.27.1 osrm-contract /data/map.osrm
if ($LASTEXITCODE -ne 0) { throw 'Falha no osrm-contract. O material foi preservado para diagnóstico.' }
$datasetHash = (Get-FileHash -LiteralPath $targetFile -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Output "Extrato pedestre preparado. OSRM_DATASET_REVISION=$datasetHash"
Write-Output 'Inicie com: docker compose -f compose.osrm.yaml up -d'
