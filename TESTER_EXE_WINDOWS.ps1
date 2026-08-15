param(
    [Parameter(Mandatory=$true)]
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$exe = (Resolve-Path $ExePath).Path
$dataRoot = Join-Path $env:TEMP ("FEWURA_CRM_SMOKE_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $dataRoot | Out-Null

$oldData = $env:FEWURA_CRM_DATA_DIR
$oldNoBrowser = $env:FEWURA_CRM_NO_BROWSER
$oldPort = $env:FEWURA_CRM_PORT
$env:FEWURA_CRM_DATA_DIR = $dataRoot
$env:FEWURA_CRM_NO_BROWSER = '1'
$env:FEWURA_CRM_PORT = '18020'

try {
    $self = Start-Process -FilePath $exe -ArgumentList '--self-test' -Wait -PassThru
    if ($self.ExitCode -ne 0) { throw "Self-test echoue: code $($self.ExitCode)" }
    $db = Join-Path $dataRoot 'fewura_crm.db'
    if (-not (Test-Path $db)) { throw "Base CRM non creee: $db" }

    $p = Start-Process -FilePath $exe -PassThru
    $url = 'http://127.0.0.1:18020/'
    $ok = $false
    for ($i=0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 250
        try {
            $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200 -and $r.Content -match 'FEWURA CRM' -and $r.Content -match 'FEWURA PROSPECT' -and $r.Content -match 'Contacts / Prospects') { $ok = $true; break }
        } catch {}
    }
    if (-not $ok) { throw 'Interface de gestion FEWURA CRM inaccessible ou incomplete.' }

    $prospects = Invoke-WebRequest -Uri 'http://127.0.0.1:18020/prospects' -UseBasicParsing -TimeoutSec 3
    if ($prospects.Content -notmatch 'Supprimer la sélection' -or $prospects.Content -notmatch 'Supprimer tout') { throw 'Gestion des suppressions absente.' }

    $prospectEngine = Invoke-WebRequest -Uri 'http://127.0.0.1:18020/prospect' -UseBasicParsing -TimeoutSec 3
    if ($prospectEngine.Content -notmatch 'Rechercher et importer dans le CRM') { throw 'Interface FEWURA PROSPECT absente.' }

    Invoke-WebRequest -Uri 'http://127.0.0.1:18020/shutdown' -Method Post -UseBasicParsing -TimeoutSec 3 | Out-Null
    $p.WaitForExit(8000) | Out-Null
    if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; throw 'Le processus ne se ferme pas après /shutdown.' }

    Write-Host 'FEWURA CRM 1.2.0 INTERFACE + EXE TEST OK' -ForegroundColor Green
    exit 0
}
catch {
    if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    Write-Host ('FEWURA CRM EXE TEST ECHEC: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
finally {
    if ($null -eq $oldData) { Remove-Item Env:FEWURA_CRM_DATA_DIR -ErrorAction SilentlyContinue } else { $env:FEWURA_CRM_DATA_DIR = $oldData }
    if ($null -eq $oldNoBrowser) { Remove-Item Env:FEWURA_CRM_NO_BROWSER -ErrorAction SilentlyContinue } else { $env:FEWURA_CRM_NO_BROWSER = $oldNoBrowser }
    if ($null -eq $oldPort) { Remove-Item Env:FEWURA_CRM_PORT -ErrorAction SilentlyContinue } else { $env:FEWURA_CRM_PORT = $oldPort }
}
