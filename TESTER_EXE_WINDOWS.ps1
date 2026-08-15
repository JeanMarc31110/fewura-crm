param(
    [Parameter(Mandatory=$true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$dataRoot = Join-Path $env:TEMP ("FEWURA_CRM_SMOKE_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null

$oldData = $env:FEWURA_CRM_DATA_DIR
$env:FEWURA_CRM_DATA_DIR = $dataRoot
try {
    $p = Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru -NoNewWindow
    if ($p.ExitCode -ne 0) { throw "Self-test echoue: code $($p.ExitCode)" }
    $db = Join-Path $dataRoot 'fewura_crm.db'
    if (-not (Test-Path $db)) { throw "Base CRM non creee: $db" }
    Write-Host 'FEWURA CRM EXE SELF-TEST OK' -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ('FEWURA CRM EXE TEST ECHEC: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally {
    if ($null -eq $oldData) { Remove-Item Env:FEWURA_CRM_DATA_DIR -ErrorAction SilentlyContinue } else { $env:FEWURA_CRM_DATA_DIR = $oldData }
}
